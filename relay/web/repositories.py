"""Django persistence adapters used by Relay application services."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timedelta
from functools import lru_cache
from hashlib import sha256
import json
import logging
from pathlib import Path
import shutil
import tempfile
from typing import NamedTuple, NoReturn, TypeVar
import uuid

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, IntegrityError, models, transaction
from django.db.models import Max, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from pydantic import ValidationError

from relay.agents.models import ModelObservation
from relay.constants import (
    API_MAX_PAGE,
    API_MAX_PAGE_BYTES,
    ATTEMPT_STALE_AFTER_SECONDS,
    CONTROL_CLAIM_STALE_AFTER_SECONDS,
    CONTROL_REQUEST_TTL_SECONDS,
    DEFAULT_RETRY_HANDOFF_PROMPT,
    DEFAULT_UNSTARTED_HANDOFF_PROMPT,
    DISPATCH_ORPHAN_AFTER_SECONDS,
    EDITOR_LEASE_TTL_SECONDS,
    EVENT_MAX_PAYLOAD_BYTES,
    INSTANCE_STALE_AFTER_SECONDS,
    RECONCILE_MAX_ITEMS,
    RETRY_HANDOFF_MAX_BYTES,
    REVIEW_PREVIEW_MAX_BYTES,
    RUN_PROBLEM_MESSAGE_MAX_EVENTS,
    RUN_PROBLEM_TEXT_MAX_CHARS,
    WORKFLOW_DOCUMENT_NAMES,
)
from relay.errors import (
    ConfigError,
    PermissionFlowError,
    PersistenceError,
    ProjectDiscoveryError,
    ProjectRelinkError,
    RelayError,
)
from relay.execution.automatic import (
    PENDING_RECOVERY_STATES,
    RECOVERABLE_ERRORS,
    recovery_instruction,
)
from relay.execution.completion import MergeTarget, complete_run_merge
from relay.execution.control import (
    ClaimedControl,
    ControlRecovery,
    ControlResult,
    cancel_stop_reason,
)
from relay.execution.dispatch import (
    ClaimDisposition,
    ClaimedAttempt,
    ClaimResult,
    defer_dispatch,
    notify_dispatch,
    release_admission,
)
from relay.execution.launch import LaunchRequest
from relay.execution.locks import decide_admission
from relay.execution.machine import (
    transition_control,
    transition_interaction,
    transition_node,
    transition_run,
)
from relay.execution.process_identity import ProcessIdentity, process_identity
from relay.execution.reconcile import AttemptRecovery
from relay.execution.relaunch import PreviousRunInputs
from relay.execution.resources import cleanup_run_resources
from relay.execution.resume import (
    RecoveryTarget,
    RetryAgent,
    RetryEffort,
    RetryPermissionMode,
    recovery_workspace_lock,
)
from relay.execution.runner import ExecutionOutcome, OutcomeKind, ScopeNodeRecord
from relay.execution.scheduler import (
    RunSchedule,
    ScheduledNode,
    SchedulingChange,
    reachable_node_ids,
)
from relay.execution.state import (
    TERMINAL_NODE_STATUSES,
    AttemptStatus,
    AttemptStopReason,
    CleanupPolicy,
    ControlKind,
    ControlState,
    DispatchState,
    DraftValidationState,
    DriverKind,
    EventSensitivity,
    EventSource,
    InteractionKind,
    InteractionStatus,
    NodeStatus,
    NodeType,
    PreservationState,
    RunStatus,
    WorktreeState,
)
from relay.execution.step_settings import UnstartedAgentTarget
from relay.execution.timing import duration_seconds
from relay.paths import (
    artifacts_dir,
    clear_application_logs,
    safe_resolve,
    shutdown_marker_path,
    worktrees_dir,
)
from relay.projects.identity import ProjectIdentity
from relay.projects.service import ProjectRecord
from relay.vcs.artifacts import (
    PreservationResult,
    RecoveryReport,
    preserve_recovery_reports,
    validate_attempt_evidence,
)
from relay.vcs.git import git_stdout, run_git, run_git_to_file
from relay.vcs.worktree import (
    reader_worktree_path,
    remove_worktree,
    run_branch,
    run_worktree_path,
)
from relay.workflows.graph import CompiledGraph, compile_graph
from relay.workflows.loader import load_workflow_text, workflow_key_parts
from relay.workflows.schema import NodeDefinition, RecoveryPolicy
from relay.workflows.scope import (
    enclosing_scope,
    node_scope,
    parse_scope_path,
    scope_is_ancestor,
    sibling_scope,
)
from relay.workflows.snapshot import SnapshotBundle

from .models import (
    AgentModelObservation,
    Artifact,
    AutomaticRetry,
    ControlRequest,
    DispatchClaim,
    EditorLease,
    HumanInteraction,
    Instance,
    NodeAttempt,
    NodeRun,
    Project,
    ProjectRelink,
    Run,
    RunEvent,
    RunLock,
    RunSnapshot,
    UsageRetry,
    WorkflowDraft,
)

ModelT = TypeVar("ModelT", bound=models.Model)
LOGGER = logging.getLogger(__name__)
_CONTROL_INTERACTION_KINDS: dict[str, str] = {
    ControlKind.PERMISSION_ANSWER.value: InteractionKind.PERMISSION.value,
    ControlKind.ELICITATION_ANSWER.value: InteractionKind.ELICITATION.value,
    ControlKind.WAIT_ANSWER.value: InteractionKind.WAIT.value,
}


def _recovery_policy(run: Run) -> RecoveryPolicy:
    try:
        return RecoveryPolicy.model_validate(_mapping(run, "recovery_policy"))
    except ValidationError:
        message = "The stored automatic recovery policy is invalid."
        raise PersistenceError(message, context={"run": _identifier(run)}) from None


def _recovery_record(retry: AutomaticRetry) -> dict[str, object]:
    attempt = _related(retry, "attempt", NodeAttempt)
    node = _related(attempt, "node_run", NodeRun)
    return {
        "scope_path": _string(node, "scope_path"),
        "attempt_number": _integer(attempt, "attempt_number"),
        "retry_number": _integer(retry, "retry_number"),
        "state": _string(retry, "state"),
        "instruction": _string(retry, "instruction"),
        "instruction_sha256": _string(retry, "instruction_sha256"),
        "message": _string(retry, "error_message"),
    }


def _run_recovery(run: Run) -> dict[str, object]:
    latest = (
        AutomaticRetry.objects.select_related("attempt__node_run")
        .filter(attempt__node_run__run=run)
        .order_by("-created_at", "-pk")
        .first()
    )
    return {
        **_recovery_policy(run).model_dump(mode="json"),
        "current": _recovery_record(latest) if latest is not None else None,
    }


class _ClaimContext(NamedTuple):
    """Validated snapshot values used to construct one claimed attempt."""

    inputs: dict[str, object]
    upstream_outputs: dict[str, dict[str, object]]
    run_metadata: dict[str, object]
    prompt_contents: tuple[str, ...]
    route: dict[str, object]
    subworkflows: dict[str, object]


@lru_cache(maxsize=RECONCILE_MAX_ITEMS)
def _compiled_run_graph(run_id: str) -> CompiledGraph:
    """Compile each immutable snapshot once while its run stays in the cache."""
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    loaded = load_workflow_text(
        _string(snapshot, "workflow_yaml"), source=Path(f"snapshot:{run_id}")
    )
    return compile_graph(loaded.definition.nodes)


@lru_cache(maxsize=RECONCILE_MAX_ITEMS)
def _reachable_run_nodes(run_id: str, entry_root: str | None) -> frozenset[str]:
    graph = _compiled_run_graph(run_id)
    return (
        reachable_node_ids(entry_root, graph, graph.control_downstream)
        if entry_root is not None
        else frozenset(graph.nodes)
    )


class DjangoAgentStore:
    """Advisory model observations, replaced only by a fresh successful probe."""

    def replace_model_observations(
        self,
        agent_id: str,
        observations: tuple[ModelObservation, ...],
    ) -> None:
        if any(item.agent_id != agent_id for item in observations):
            message = "An agent observation does not match its cache identity."
            raise PersistenceError(message, context={"agent": agent_id})
        try:
            with transaction.atomic():
                AgentModelObservation.objects.filter(agent_id=agent_id).delete()
                AgentModelObservation.objects.bulk_create(
                    [
                        AgentModelObservation(
                            agent_id=item.agent_id,
                            model_value=item.model_value,
                            model_name=item.model_name,
                            config_id=item.config_id,
                            agent_version=item.agent_version,
                            observed_at=item.observed_at,
                        )
                        for item in observations
                    ]
                )
        except DatabaseError:
            message = "Relay could not update cached agent model observations."
            raise PersistenceError(message, context={"agent": agent_id}) from None

    def list_model_observations(self) -> tuple[ModelObservation, ...]:
        try:
            rows = AgentModelObservation.objects.order_by("agent_id", "model_value")
            return tuple(
                ModelObservation(
                    agent_id=_string(row, "agent_id"),
                    model_value=_string(row, "model_value"),
                    model_name=_string(row, "model_name"),
                    config_id=_string(row, "config_id"),
                    agent_version=_string(row, "agent_version"),
                    observed_at=row.observed_at,
                )
                for row in rows
            )
        except DatabaseError:
            message = "Relay could not read cached agent model observations."
            raise PersistenceError(message) from None


def _set_model_field(instance: models.Model, name: str, value: object) -> None:
    """Assign a validated value through a Django model descriptor."""
    setattr(instance, name, value)


def _string(instance: models.Model, name: str) -> str:
    value = getattr(instance, name)
    if not isinstance(value, str):
        message = f"Stored field {name} is not text."
        raise PersistenceError(message)
    return value


def _boolean(instance: models.Model, name: str) -> bool:
    value = getattr(instance, name)
    if not isinstance(value, bool):
        message = f"Stored field {name} is not boolean."
        raise PersistenceError(message)
    return value


def _integer(instance: models.Model, name: str) -> int:
    value = getattr(instance, name)
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"Stored field {name} is not an integer."
        raise PersistenceError(message)
    return value


def _mapping(instance: models.Model, name: str) -> dict[str, object]:
    value = getattr(instance, name)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        message = f"Stored field {name} is not a string-keyed object."
        raise PersistenceError(message)
    return dict(value)


def _string_list(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        message = f"Stored field {field} is not a list of strings."
        raise PersistenceError(message)
    return tuple(value)


def _related(instance: models.Model, name: str, expected: type[ModelT]) -> ModelT:
    value = getattr(instance, name)
    if not isinstance(value, expected):
        message = f"Stored relation {name} has an unexpected type."
        raise PersistenceError(message)
    return value


def _identifier(instance: models.Model) -> str:
    value = instance.pk
    if value is None:
        message = "A durable Relay record has no primary key."
        raise PersistenceError(message)
    return str(value)


def _record(project: Project) -> ProjectRecord:
    return ProjectRecord(
        id=str(project.pk),
        canonical_path=_string(project, "canonical_path"),
        display_name=_string(project, "display_name"),
        git_root=_string(project, "git_root"),
    )


def _require_project(project: Project | None, old_path: str) -> Project:
    if project is None:
        message = f"No registered project matches {old_path}."
        raise ProjectRelinkError(message)
    return project


def _reject_duplicate(project: Project, new_path: str) -> None:
    if Project.objects.exclude(pk=project.pk).filter(canonical_path=new_path).exists():
        message = f"A project is already registered at {new_path}."
        raise ProjectRelinkError(message)


class DjangoProjectStore:
    """Short-transaction project storage backed by the central SQLite DB."""

    def register(self, identity: ProjectIdentity) -> ProjectRecord:
        try:
            project, _created = Project.objects.update_or_create(
                canonical_path=identity.canonical_path,
                defaults={
                    "display_name": identity.display_name,
                    "git_root": identity.git_root,
                    "last_opened_at": timezone.now(),
                },
            )
        except DatabaseError:
            message = "Relay could not register the current project."
            raise PersistenceError(message) from None
        return _record(project)

    def list_projects(self) -> list[ProjectRecord]:
        try:
            projects = Project.objects.order_by("-last_opened_at", "display_name")
            return [_record(project) for project in projects]
        except DatabaseError:
            message = "Relay could not list registered projects."
            raise PersistenceError(message) from None

    def get_project(self, project_id: str) -> ProjectRecord:
        """Resolve an explicitly selected project without changing the process default."""
        try:
            return _record(_project_by_id(project_id))
        except DatabaseError:
            message = "Relay could not read the selected project."
            raise PersistenceError(message, context={"project": project_id}) from None

    def relink(self, old_path: str, identity: ProjectIdentity) -> ProjectRecord:
        try:
            with transaction.atomic():
                project = _require_project(
                    Project.objects.select_for_update().filter(canonical_path=old_path).first(),
                    old_path,
                )
                _reject_duplicate(project, identity.canonical_path)
                previous = _string(project, "canonical_path")
                _set_model_field(project, "canonical_path", identity.canonical_path)
                _set_model_field(project, "display_name", identity.display_name)
                _set_model_field(project, "git_root", identity.git_root)
                _set_model_field(project, "last_opened_at", timezone.now())
                project.save(
                    update_fields=(
                        "canonical_path",
                        "display_name",
                        "git_root",
                        "last_opened_at",
                    )
                )
                ProjectRelink.objects.create(
                    project=project,
                    old_path=previous,
                    new_path=identity.canonical_path,
                )
                return _record(project)
        except ProjectRelinkError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not relink the project."
            raise PersistenceError(message) from None


def _project_by_id(project_id: str) -> Project:
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        message = "The requested Relay project does not exist."
        raise ProjectDiscoveryError(message, context={"project": project_id})
    return project


def _require_run(run: Run | None, run_id: str) -> Run:
    if run is None:
        message = "The requested run does not exist."
        raise ProjectDiscoveryError(message, context={"run": run_id})
    return run


def _require_job(node: NodeRun | None, run_id: str, scope_path: str) -> NodeRun:
    if node is None:
        message = "The requested job does not exist in this run."
        raise ProjectDiscoveryError(message, context={"run": run_id, "job": scope_path})
    return node


def _require_artifact(artifact: Artifact | None) -> Artifact:
    if artifact is None:
        message = "The requested artifact does not exist."
        raise ProjectDiscoveryError(message)
    return artifact


def _reject_lease_holder(project_id: str, workflow_key: str) -> NoReturn:
    message = "Another browser holds the workflow editor lease."
    raise PermissionFlowError(
        message,
        context={"project": project_id, "workflow": workflow_key},
        next_action="Wait for the lease to expire or return to its open tab.",
    )


def _reject_schedule_mismatch(run_id: str) -> NoReturn:
    message = "The durable top-level node set differs from the run snapshot."
    raise PersistenceError(message, context={"run": run_id})


def _reject_active_cleanup(project_id: str) -> NoReturn:
    message = "Relay will not clean data while this project has an active run."
    raise PermissionFlowError(message, context={"project": project_id})


def _reject_incomplete_cleanup_evidence(run_id: str) -> NoReturn:
    message = "Relay retained the run worktree because its evidence is incomplete."
    raise PersistenceError(message, context={"run": run_id})


def _reject_branch_with_worktree(run_id: str) -> NoReturn:
    message = "Remove a run worktree before deleting its retained branch."
    raise PermissionFlowError(
        message,
        context={"run": run_id},
        next_action="Clean worktrees first or select scope all.",
    )


def _reject_run_with_git_state(run_id: str) -> NoReturn:
    message = "Remove the retained run worktree and Git refs before deleting its records."
    raise PermissionFlowError(
        message,
        context={"run": run_id},
        next_action="Clean worktrees, then branches and attempt refs, before run records.",
    )


def _retained_branch_exists(repository: Path, branch: str) -> bool:
    result = run_git(
        repository,
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    # Re-run without quiet mode so the Relay-owned Git error retains useful context.
    run_git(repository, ["show-ref", "--verify", f"refs/heads/{branch}"])
    return False


def _retained_attempt_refs(repository: Path, run_id: str) -> tuple[str, ...]:
    """Map run `abc` to retained refs below `refs/relay/attempts/abc/`."""
    prefix = f"refs/relay/attempts/{run_id}/"
    output = git_stdout(repository, ["for-each-ref", "--format=%(refname)", prefix])
    refs = tuple(line for line in output.splitlines() if line)
    if any(not ref.startswith(prefix) for ref in refs):
        message = "Git returned a retained attempt ref outside the requested run namespace."
        raise PersistenceError(message, context={"run": run_id})
    return refs


def _run_worktree_paths(run: Run) -> tuple[Path, ...]:
    """Return known reader checkouts before the run's primary checkout.

    For example, a read-only attempt ``42`` uses ``<run>/r-42``. Removing
    that nested checkout first keeps Git from rejecting removal of the parent
    and ensures confirmed cleanup covers reader worktrees left by a crash.
    """
    primary = safe_resolve(worktrees_dir(), _string(run, "worktree_path"))
    reader_ids = NodeAttempt.objects.filter(
        node_run__run=run,
        node_run__writes=False,
        node_run__node_type__in=(NodeType.AGENT.value, NodeType.COMMAND.value),
    ).values_list("pk", flat=True)
    readers = tuple(reader_worktree_path(primary, str(attempt_id)) for attempt_id in reader_ids)
    return (*readers, primary)


def _derived_control_key(namespace: str, *parts: str) -> str:
    """Map `cancel`, `key-1`, `attempt-2` to `cancel:<64 hex characters>`."""
    digest = sha256("\0".join(parts).encode()).hexdigest()
    return f"{namespace}:{digest}"


def _require_retained_file(path: Path) -> Path:
    if not path.is_file():
        message = "The retained artifact file is missing."
        raise ProjectDiscoveryError(message)
    return path


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_field(instance: models.Model, name: str) -> datetime | None:
    value = getattr(instance, name)
    if value is None or isinstance(value, datetime):
        return value
    message = f"Stored field {name} is not a datetime."
    raise PersistenceError(message)


def _foreign_key_text(instance: models.Model, name: str) -> str:
    value = getattr(instance, f"{name}_id")
    if value is None:
        message = f"Stored relation {name} has no identifier."
        raise PersistenceError(message)
    return str(value)


class DjangoWorkflowStore:
    """Recovery drafts and renewable editor leases for project YAML files."""

    def get_draft(self, project_id: str, workflow_key: str) -> dict[str, object] | None:
        try:
            row = WorkflowDraft.objects.filter(
                project_id=project_id, workflow_key=workflow_key
            ).first()
            if row is None:
                return None
            return {
                "yaml": _string(row, "recovery_yaml"),
                "base_hash": _string(row, "base_file_hash"),
                "validation_state": _string(row, "validation_state"),
                "updated_at": _datetime_text(row.updated_at),
            }
        except DatabaseError:
            message = "Relay could not read the workflow recovery draft."
            raise PersistenceError(message, context={"workflow": workflow_key}) from None

    def save_draft(
        self,
        project_id: str,
        workflow_key: str,
        yaml_text: str,
        base_hash: str,
        validation_state: DraftValidationState,
    ) -> dict[str, object]:
        try:
            project = _project_by_id(project_id)
            row, _created = WorkflowDraft.objects.update_or_create(
                project=project,
                workflow_key=workflow_key,
                defaults={
                    "recovery_yaml": yaml_text,
                    "base_file_hash": base_hash,
                    "validation_state": validation_state.value,
                },
            )
            return {
                "yaml": _string(row, "recovery_yaml"),
                "base_hash": _string(row, "base_file_hash"),
                "validation_state": _string(row, "validation_state"),
                "updated_at": _datetime_text(row.updated_at),
            }
        except ProjectDiscoveryError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not save the workflow recovery draft."
            raise PersistenceError(message, context={"workflow": workflow_key}) from None

    def discard_draft(self, project_id: str, workflow_key: str) -> None:
        try:
            WorkflowDraft.objects.filter(project_id=project_id, workflow_key=workflow_key).delete()
        except DatabaseError:
            message = "Relay saved the workflow but could not clear its recovery draft."
            raise PersistenceError(message, context={"workflow": workflow_key}) from None

    def acquire_lease(
        self,
        project_id: str,
        workflow_key: str,
        holder: str,
    ) -> dict[str, object]:
        try:
            with transaction.atomic():
                project = _project_by_id(project_id)
                now = timezone.now()
                expires = now + timedelta(seconds=EDITOR_LEASE_TTL_SECONDS)
                lease = (
                    EditorLease.objects.select_for_update()
                    .filter(project=project, workflow_key=workflow_key)
                    .first()
                )
                if lease is not None and lease.expires_at > now:
                    current_holder = _string(lease, "holder")
                    if current_holder != holder:
                        _reject_lease_holder(project_id, workflow_key)
                if lease is None:
                    lease = EditorLease.objects.create(
                        project=project,
                        workflow_key=workflow_key,
                        holder=holder,
                        acquired_at=now,
                        expires_at=expires,
                    )
                else:
                    _set_model_field(lease, "holder", holder)
                    _set_model_field(lease, "acquired_at", now)
                    _set_model_field(lease, "expires_at", expires)
                    lease.save(update_fields=("holder", "acquired_at", "expires_at"))
                return {
                    "holder": holder,
                    "acquired_at": _datetime_text(lease.acquired_at),
                    "expires_at": _datetime_text(lease.expires_at),
                }
        except (ProjectDiscoveryError, PermissionFlowError):
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not acquire the workflow editor lease."
            raise PersistenceError(message, context={"workflow": workflow_key}) from None

    def require_lease(self, project_id: str, workflow_key: str, holder: str) -> None:
        """Reject a write unless this exact browser still owns the live lease."""
        try:
            lease = EditorLease.objects.filter(
                project_id=project_id,
                workflow_key=workflow_key,
                holder=holder,
                expires_at__gt=timezone.now(),
            ).first()
            if lease is None:
                _reject_lease_holder(project_id, workflow_key)
        except PermissionFlowError:
            raise
        except DatabaseError:
            message = "Relay could not verify the workflow editor lease."
            raise PersistenceError(message, context={"workflow": workflow_key}) from None


def _run_record(run: Run) -> dict[str, object]:
    return {
        "id": _identifier(run),
        "project_id": _foreign_key_text(run, "project"),
        "workflow_key": _string(run, "workflow_key"),
        "number": _integer(run, "number"),
        "title": _string(run, "title"),
        "source_branch": run.source_branch,
        "created_at": _datetime_text(_datetime_field(run, "created_at")),
        "status": _string(run, "status"),
        "source_commit": _string(run, "source_commit"),
        "run_branch": _string(run, "run_branch"),
        "worktree_state": _string(run, "worktree_state"),
        "cleanup_policy": _string(run, "cleanup_policy"),
        "merged_commit": run.merged_commit,
        "launcher": _string(run, "launcher"),
        "started_at": _datetime_text(_datetime_field(run, "started_at")),
        "ended_at": _datetime_text(_datetime_field(run, "ended_at")),
        "failure_code": run.failure_code,
        "failure_summary": run.failure_summary,
        "entry_point": run.entry_point,
        "dispatch_paused": _boolean(run, "dispatch_paused"),
        "waiting_count": _integer(run, "read_waiting_count"),
    }


def _provider_failure_message(attempt: NodeAttempt) -> tuple[str | None, bool]:
    """Read a bounded tail of this attempt's public final message, never thoughts."""
    rows = list(
        RunEvent.objects.filter(
            attempt=attempt,
            type="agent.message",
            source=EventSource.AGENT.value,
            sensitivity=EventSensitivity.NORMAL.value,
        )
        .order_by("-id")
        .values_list("payload", flat=True)[: RUN_PROBLEM_MESSAGE_MAX_EVENTS + 1]
    )
    if not rows or not isinstance(rows[0].get("text"), str):
        return None, False
    latest = rows[0]
    identity = (latest.get("message_id"), latest.get("turn"))
    chunks = []
    for payload in rows[:RUN_PROBLEM_MESSAGE_MAX_EVENTS]:
        if (payload.get("message_id"), payload.get("turn")) != identity:
            break
        text = payload.get("text")
        if not isinstance(text, str):
            break
        chunks.append(text)
        # Without a provider message ID, adjacent messages cannot be proven
        # to belong together; preserve the last chunk rather than joining them.
        if identity[0] is None:
            break
    # Stored chunks arrive newest first: ["resets 1:50pm", "Limit · "]
    # becomes "Limit · resets 1:50pm", keeping the provider's own wording.
    text = "".join(reversed(chunks))
    truncated = len(text) > RUN_PROBLEM_TEXT_MAX_CHARS or (
        len(chunks) == RUN_PROBLEM_MESSAGE_MAX_EVENTS
        and len(rows) > len(chunks)
        and (rows[-1].get("message_id"), rows[-1].get("turn")) == identity
    )
    return text[:RUN_PROBLEM_TEXT_MAX_CHARS], truncated


def _effective_route(node: NodeRun, snapshot: RunSnapshot) -> dict[str, object]:
    """Apply owner retry choices without mutating the captured launch route."""
    scope = _string(node, "scope_path")
    route = _mapping(snapshot, "route_table").get(scope, {})
    if not isinstance(route, dict):
        message = "The snapshotted route entry is invalid."
        raise PersistenceError(message, context={"node": scope})
    options = _mapping(node, "retry_options")
    fields = {"effort", "permission_mode"}
    replacement = "selected_agent" in options or "model_value" in options
    if replacement:
        fields.update(
            {
                "selected_agent",
                "model_value",
                "effective_agent_order",
                "permission_profile",
            }
        )
    invalid = bool(set(options) - (fields | {"handoff_prompt"} if replacement else fields))
    invalid |= any(
        value is not None and (not isinstance(value, str) or not value)
        for value in (options.get("effort"), options.get("permission_mode"))
    )
    if replacement:
        invalid |= not fields.issubset(options) or any(
            not isinstance(options.get(field), str) or not options.get(field)
            for field in ("selected_agent", "model_value")
        )
        invalid |= options.get("effective_agent_order") != [options.get("selected_agent")]
        invalid |= options.get("permission_profile") is not None
        handoff = options.get("handoff_prompt")
        invalid |= handoff is not None and (
            not isinstance(handoff, str)
            or not handoff.strip()
            or len(handoff.encode("utf-8")) > RETRY_HANDOFF_MAX_BYTES
        )
    if invalid:
        message = "The stored retry configuration is invalid."
        raise PersistenceError(message, context={"node": scope})
    return {**route, **options}


def _retry_configuration(node: NodeRun, snapshot: RunSnapshot) -> dict[str, object]:
    """Read this step's current retry choices without another database query."""
    route = _effective_route(node, snapshot)
    return {
        "scope_path": _string(node, "scope_path"),
        "agent_id": route.get("selected_agent"),
        "model_value": route.get("model_value"),
        "effort": route.get("effort"),
        "permission_mode": route.get("permission_mode"),
        "default_handoff_prompt": DEFAULT_RETRY_HANDOFF_PROMPT,
        "handoff_prompt_max_bytes": RETRY_HANDOFF_MAX_BYTES,
    }


def _run_problem(run: Run) -> dict[str, object] | None:
    """Expose the initiating failure independently of node and event pagination."""
    if _string(run, "status") not in {RunStatus.FAILED.value, RunStatus.CANCELING.value}:
        return None
    latest_number = (
        NodeAttempt.objects.filter(node_run_id=models.OuterRef("node_run_id"))
        .order_by("-attempt_number")
        .values("attempt_number")[:1]
    )
    attempt = (
        NodeAttempt.objects.select_related("node_run")
        .filter(node_run__run=run, node_run__status=NodeStatus.FAILED.value)
        .annotate(latest_number=models.Subquery(latest_number))
        .filter(attempt_number=models.F("latest_number"), status=AttemptStatus.TERMINAL.value)
        .exclude(
            stop_reason__in=(AttemptStopReason.CANCELED.value, AttemptStopReason.INTERRUPTED.value)
        )
        .order_by("ended_at", "pk")
        .first()
    )
    if attempt is None:
        return None
    ended = RunEvent.objects.filter(attempt=attempt, type="attempt.ended").order_by("-id").first()
    message = _mapping(ended, "payload").get("error_message") if ended else None
    provider_message, truncated = _provider_failure_message(attempt)
    retry = UsageRetry.objects.filter(run=run, attempt=attempt).first()
    node = _related(attempt, "node_run", NodeRun)
    return {
        **_retry_configuration(node, _related(run, "snapshot", RunSnapshot)),
        "attempt_number": _integer(attempt, "attempt_number"),
        "agent_id": _string(attempt, "agent_id"),
        "model_value": _string(attempt, "model_value"),
        "error_code": attempt.error_code,
        "stop_reason": attempt.stop_reason,
        "exit_code": attempt.exit_code,
        "message": message if isinstance(message, str) else None,
        "provider_message": provider_message,
        "provider_message_truncated": truncated,
        "retry": (
            {
                "state": _string(retry, "state"),
                "reset_at": retry.reset_at.isoformat() if retry.reset_at is not None else None,
                "error_message": retry.error_message,
            }
            if retry is not None
            else None
        ),
    }


def _repair_groups(run: Run) -> dict[str, str]:
    groups = {}
    for scope, source in _mapping(run, "repair_groups").items():
        if not isinstance(source, str):
            message = "The stored repair presentation is invalid."
            raise PersistenceError(message, context={"run": _identifier(run)})
        groups[scope] = source
    return groups


def _node_record(
    node: NodeRun,
    snapshot: RunSnapshot,
    *,
    dispatch_paused: bool = False,
    repair_groups: Mapping[str, str] | None = None,
) -> dict[str, object]:
    # Monitor summaries omit outputs; paged events retain their visible source bytes.
    frozen = _mapping(node, "frozen_def")
    scope = _string(node, "scope_path")
    # root.build#2.check + needs ["plan"] becomes root.build#2.plan, never root.plan.
    parent = scope.rsplit(".", 1)[0]
    needs = frozen.get("needs", [])
    branches = frozen.get("branches", {})
    repair = frozen.get("repair_rule")
    repair_for = (repair_groups or {}).get(scope)
    if isinstance(repair, dict) and isinstance(repair.get("source"), str):
        repair_for = sibling_scope(scope, repair["source"])
    repair_settings = None
    if (
        repair_for is not None
        and _string(node, "node_type") == NodeType.LOOP.value
        and parse_scope_path(scope)[-1].iteration is None
    ):
        body = frozen.get("body", {})
        repair_settings = {
            "legacy": not isinstance(repair, dict),
            "max_rounds": frozen.get("max_iterations"),
            "accepted_output": repair.get("accepted_output") if isinstance(repair, dict) else None,
            "accepted_value": repair.get("accepted_value") if isinstance(repair, dict) else None,
            "fix_instruction": repair.get("fix_instruction") if isinstance(repair, dict) else None,
            "verify_instruction": repair.get("verify_instruction")
            if isinstance(repair, dict)
            else None,
            "roles": {
                role: {
                    field: definition.get(field)
                    for field in ("type", "model", "agents", "agent_options", "writes")
                }
                for role, definition in (body.items() if isinstance(body, dict) else ())
                if isinstance(role, str) and isinstance(definition, dict)
            },
        }
    controls = [
        {"target": f"{parent}.{target}", "label": label}
        for label, target in (branches.items() if isinstance(branches, dict) else ())
        if isinstance(label, str) and isinstance(target, str)
    ]
    for field, label in (("on_timeout", "Time limit"), ("exhausted", "Iteration limit")):
        target = frozen.get(field)
        if isinstance(target, str) and target:
            controls.append({"target": f"{parent}.{target}", "label": label})
    return {
        "id": _identifier(node),
        "scope_path": _string(node, "scope_path"),
        "node_id": _string(node, "node_id"),
        "node_type": _string(node, "node_type"),
        "status": _string(node, "status"),
        "started_at": _datetime_text(_datetime_field(node, "latest_started_at")),
        "ended_at": _datetime_text(_datetime_field(node, "latest_ended_at")),
        "writes": _boolean(node, "writes"),
        "selected_branch": node.selected_branch,
        "loop_index": node.loop_index,
        "parent_scope": node.parent_scope_path,
        "dependencies": [f"{parent}.{needed}" for needed in needs if isinstance(needed, str)]
        if isinstance(needs, list)
        else [],
        "controls": controls,
        "repair_for": repair_for,
        "repair_settings": repair_settings,
        "retry_settings": (
            _retry_configuration(node, snapshot)
            if _string(node, "node_type") == NodeType.AGENT.value
            and _string(node, "status") == NodeStatus.FAILED.value
            else None
        ),
        "pending_settings": (
            {
                **_retry_configuration(node, snapshot),
                "default_handoff_prompt": DEFAULT_UNSTARTED_HANDOFF_PROMPT,
            }
            if dispatch_paused
            and _string(node, "node_type") == NodeType.AGENT.value
            and _string(node, "status")
            in {NodeStatus.PENDING.value, NodeStatus.READY.value, NodeStatus.DISPATCHED.value}
            and not _boolean(node, "has_attempt")
            else None
        ),
    }


def _interaction_record(interaction: HumanInteraction) -> dict[str, object]:
    return {
        "id": _identifier(interaction),
        "attempt_id": _foreign_key_text(interaction, "attempt"),
        "scope_path": _string(_related(interaction, "node_run", NodeRun), "scope_path"),
        "kind": _string(interaction, "kind"),
        "request": _mapping(interaction, "request_payload"),
        "response": (
            _mapping(interaction, "response_payload")
            if interaction.response_payload is not None
            else None
        ),
        "status": _string(interaction, "status"),
        "respondable": _string(interaction, "status") == InteractionStatus.PENDING.value
        and _string(_related(interaction, "attempt", NodeAttempt), "status")
        == AttemptStatus.WAITING.value,
        "deadline": _datetime_text(_datetime_field(interaction, "deadline")),
        "created_at": _datetime_text(_datetime_field(interaction, "created_at")),
        "answered_at": _datetime_text(_datetime_field(interaction, "answered_at")),
    }


def _event_record(event: RunEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "type": _string(event, "type"),
        "version": _integer(event, "version"),
        "source": _string(event, "source"),
        "ts": _datetime_text(_datetime_field(event, "ts")),
        "payload": _mapping(event, "payload"),
    }


def _artifact_record(artifact: Artifact) -> dict[str, object]:
    attempt = _related(artifact, "attempt", NodeAttempt)
    node = _related(attempt, "node_run", NodeRun)
    return {
        "scope_path": _string(node, "scope_path"),
        "attempt_number": _integer(attempt, "attempt_number"),
        "id": _identifier(artifact),
        "attempt_id": _foreign_key_text(artifact, "attempt"),
        "name": _string(artifact, "declared_name"),
        "source_path": _string(artifact, "source_path"),
        "sha256": _string(artifact, "sha256"),
        "bytes": _integer(artifact, "bytes"),
        "media_type": _string(artifact, "media_type"),
        "preservation_state": _string(artifact, "preservation_state"),
    }


def _bounded_page(
    rows: Sequence[ModelT],
    limit: int,
    serialize: Callable[[ModelT], dict[str, object]],
    *,
    byte_budget: int = API_MAX_PAGE_BYTES,
) -> tuple[list[dict[str, object]], bool]:
    """Serialize an ordered prefix once, retaining a first row so cursors advance."""
    more = len(rows) > limit
    records = []
    byte_count = 0
    for row in rows[:limit]:
        record = serialize(row)
        encoded = json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if records and byte_count + len(encoded) > byte_budget:
            more = True
            break
        records.append(record)
        byte_count += len(encoded)
    return records, more


def _job_attempt_record(attempt: NodeAttempt) -> dict[str, object]:
    """Expose attempt facts without worker, process, session, or provider-private fields."""
    ended = (
        RunEvent.objects.filter(
            attempt=attempt, type="attempt.ended", sensitivity=EventSensitivity.NORMAL.value
        )
        .order_by("-id")
        .first()
    )
    error = _mapping(ended, "payload").get("error_message") if ended else None
    provider_message, truncated = _provider_failure_message(attempt)
    return {
        "id": _identifier(attempt),
        "number": _integer(attempt, "attempt_number"),
        "status": _string(attempt, "status"),
        "agent_id": _string(attempt, "agent_id"),
        "model_value": _string(attempt, "model_value"),
        "started_at": _datetime_text(_datetime_field(attempt, "started_at")),
        "ended_at": _datetime_text(_datetime_field(attempt, "ended_at")),
        "stop_reason": attempt.stop_reason,
        "exit_code": attempt.exit_code,
        "error_code": attempt.error_code,
        "error_message": _truncate_utf8(error, RUN_PROBLEM_TEXT_MAX_CHARS)
        if isinstance(error, str)
        else None,
        "provider_message": provider_message,
        "provider_message_truncated": truncated,
        "starting_head": _string(attempt, "starting_head"),
        "ending_head": attempt.ending_head,
    }


class DjangoReadStore:
    """Bounded, presentation-neutral reads for the authenticated browser."""

    def previous_run_inputs(self, run_id: str) -> PreviousRunInputs:
        """Read launch input values without returning prompts or provider routes."""
        try:
            run = _require_run(
                Run.objects.select_related("snapshot", "project").filter(pk=run_id).first(), run_id
            )
            snapshot = _related(run, "snapshot", RunSnapshot)
            source = PreviousRunInputs(
                project_id=_identifier(_related(run, "project", Project)),
                workflow_key=_string(run, "workflow_key"),
                status=_string(run, "status"),
                inputs=_mapping(snapshot, "typed_inputs"),
            )
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not read the previous run's inputs."
            raise PersistenceError(message, context={"run": run_id}) from None
        else:
            return source

    def attention(self, since: int | None) -> dict[str, object]:
        """Read owner requests and new completion facts without event payloads."""
        try:
            with transaction.atomic():
                pending = HumanInteraction.objects.filter(
                    status=InteractionStatus.PENDING.value,
                    attempt__status=AttemptStatus.WAITING.value,
                )
                waiting_runs = pending.values_list("run_id", flat=True).distinct()
                latest = RunEvent.objects.order_by("-id").first()
                cursor = _integer(latest, "id") if latest is not None else 0
                finished: list[dict[str, object]] = []
                more = False
                if since is not None:
                    rows = list(
                        RunEvent.objects.select_related("run")
                        .filter(
                            id__gt=since,
                            type__in=("run.succeeded", "run.failed", "run.canceled"),
                        )
                        .order_by("id")[: API_MAX_PAGE + 1]
                    )
                    finished, more = _bounded_page(
                        rows,
                        API_MAX_PAGE,
                        lambda event: {
                            "id": _integer(event, "id"),
                            "run_id": _foreign_key_text(event, "run"),
                            "project_id": _foreign_key_text(_related(event, "run", Run), "project"),
                            "workflow_key": _string(_related(event, "run", Run), "workflow_key"),
                            "status": _string(event, "type").removeprefix("run."),
                        },
                    )
                    if more and finished:
                        cursor = int(str(finished[-1]["id"]))
                    cursor = max(since, cursor)
                waiting_count = waiting_runs.count()
                return {
                    "waiting_count": waiting_count,
                    "waiting_runs": [str(value) for value in waiting_runs[:API_MAX_PAGE]],
                    "waiting_runs_truncated": waiting_count > API_MAX_PAGE,
                    "finished": finished,
                    "event_cursor": cursor,
                    "more": more,
                }
        except DatabaseError:
            message = "Relay could not read waiting requests."
            raise PersistenceError(message) from None

    def run_changes(
        self, run_id: str, *, scope_path: str | None = None, attempt_number: int | None = None
    ) -> dict[str, object]:
        """Preview committed changes from the source commit to the protected run head."""
        try:
            run = _require_run(
                Run.objects.select_related("project").filter(pk=run_id).first(), run_id
            )
            project = _related(run, "project", Project)
            source_commit = _string(run, "source_commit")
            recorded_head = _string(run, "recorded_head")
            commits: list[dict[str, str]] = []
            if scope_path is not None:
                parse_scope_path(scope_path)
                node = _require_job(
                    NodeRun.objects.filter(run=run, scope_path=scope_path).first(),
                    run_id,
                    scope_path,
                )
                query = NodeAttempt.objects.filter(node_run=node)
                if attempt_number is not None:
                    query = query.filter(attempt_number=attempt_number)
                attempt = query.order_by("-attempt_number").first()
                if attempt is not None:
                    source_commit = _string(attempt, "starting_head")
                    recorded_head = str(attempt.ending_head or source_commit)
                else:
                    recorded_head = source_commit
                with tempfile.TemporaryFile(mode="w+b") as log:
                    run_git_to_file(
                        Path(_string(project, "git_root")),
                        [
                            "log",
                            "--format=%H%x00%s",
                            "-100",
                            f"{source_commit}..{recorded_head}",
                            "--",
                        ],
                        log,
                    )
                    log.seek(0)
                    for line in (
                        log.read(REVIEW_PREVIEW_MAX_BYTES)
                        .decode("utf-8", errors="replace")
                        .splitlines()
                    ):
                        sha, separator, title = line.partition("\0")
                        if separator:
                            commits.append({"sha": sha, "title": title})
            with tempfile.TemporaryFile(mode="w+b") as output:
                run_git_to_file(
                    Path(_string(project, "git_root")),
                    [
                        "diff",
                        "--no-ext-diff",
                        "--no-textconv",
                        source_commit,
                        recorded_head,
                        "--",
                    ],
                    output,
                )
                output.seek(0)
                content = output.read(REVIEW_PREVIEW_MAX_BYTES + 1)
            result: dict[str, object] = {
                "text": content[:REVIEW_PREVIEW_MAX_BYTES].decode("utf-8", errors="replace"),
                "truncated": len(content) > REVIEW_PREVIEW_MAX_BYTES,
                "source_commit": source_commit,
                "recorded_head": recorded_head,
            }
            if scope_path is not None:
                result["commits"] = commits
        except DatabaseError:
            message = "Relay could not read the run's committed changes."
            raise PersistenceError(message, context={"run": run_id}) from None
        else:
            return result

    def list_runs(
        self,
        *,
        project_id: str | None,
        status: str | None,
        since: str | None,
        limit: int,
        workflow: str | None = None,
        branch: str | None = None,
        query_text: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None]:
        bounded = min(max(limit, 1), API_MAX_PAGE)
        try:
            query = Run.objects.annotate(
                read_waiting_count=models.Count(
                    "interactions",
                    filter=models.Q(
                        interactions__status=InteractionStatus.PENDING.value,
                        interactions__attempt__status=AttemptStatus.WAITING.value,
                    ),
                )
            ).order_by("-started_at", "-pk")
            if project_id is not None:
                query = query.filter(project_id=project_id)
            if status is not None:
                query = query.filter(status=status)
            if workflow is not None:
                canonical = "/".join(workflow_key_parts(workflow))
                aliases = {canonical, workflow}
                if canonical.endswith(".yaml"):
                    aliases.add(canonical[:-5])
                query = query.filter(workflow_key__in=aliases)
            if branch is not None:
                query = query.filter(source_branch=branch)
            if query_text:
                query = query.filter(
                    models.Q(title__icontains=query_text)
                    | models.Q(workflow_key__icontains=query_text)
                    | models.Q(source_commit__startswith=query_text)
                )
            if since is not None:
                cursor = _require_run(Run.objects.filter(pk=since).first(), since)
                cursor_started = _datetime_field(cursor, "started_at")
                if cursor_started is None:
                    query = query.filter(started_at__isnull=True, pk__lt=cursor.pk)
                else:
                    query = query.filter(
                        models.Q(started_at__lt=cursor_started)
                        | models.Q(started_at=cursor_started, pk__lt=cursor.pk)
                        | models.Q(started_at__isnull=True)
                    )
            rows = list(query[: bounded + 1])
            records, more = _bounded_page(rows, bounded, _run_record)
            next_value = str(records[-1]["id"]) if more and records else None
        except ProjectDiscoveryError:
            raise
        except DatabaseError:
            message = "Relay could not read run history."
            raise PersistenceError(message) from None
        else:
            return records, next_value

    def run_detail(
        self,
        run_id: str,
        *,
        collection: str,
        since: int,
        limit: int,
        pending_only: bool = False,
        interaction_id: str | None = None,
    ) -> tuple[dict[str, object], int | None]:
        """Read one bounded node or interaction page plus stable run metadata."""
        bounded = min(max(limit, 1), API_MAX_PAGE)
        try:
            # Read the run and its cursor in one statement. A retry committed
            # before this read cannot leave its old terminal event above the cursor.
            latest_event = RunEvent.objects.filter(run_id=run_id).order_by("-id").values("id")[:1]
            run = _require_run(
                Run.objects.select_related("snapshot", "project")
                .annotate(
                    read_waiting_count=models.Count(
                        "interactions",
                        filter=models.Q(
                            interactions__status=InteractionStatus.PENDING.value,
                            interactions__attempt__status=AttemptStatus.WAITING.value,
                        ),
                    ),
                    read_event_cursor=Coalesce(
                        models.Subquery(latest_event), 0, output_field=models.BigIntegerField()
                    ),
                )
                .filter(pk=run_id)
                .first(),
                run_id,
            )
            snapshot = _related(run, "snapshot", RunSnapshot)
            result = _run_record(run)
            result["working_folder"] = _string(run, "worktree_path")
            result["problem"] = _run_problem(run)
            result["recovery"] = _run_recovery(run)
            result["event_cursor"] = _integer(run, "read_event_cursor")
            result["project"] = asdict(_record(_related(run, "project", Project)))
            result["snapshot"] = {
                "relay_version": _string(snapshot, "relay_version"),
                "runtime_versions": _mapping(snapshot, "runtime_versions"),
                "hashes": _mapping(snapshot, "hashes"),
                "created_at": _datetime_text(_datetime_field(snapshot, "created_at")),
            }
            result["nodes"] = []
            result["interactions"] = []
            # Reserve half the response ceiling for run and snapshot metadata.
            byte_budget = API_MAX_PAGE_BYTES // 2
            if collection == "nodes":
                repair_groups = _repair_groups(run)
                # Legacy exhaustion sentinels belong to the explicitly grouped
                # repair loop. Their execution and frozen definitions stay intact.
                for coordinator in NodeRun.objects.filter(run=run, scope_path__in=repair_groups):
                    target = _mapping(coordinator, "frozen_def").get("exhausted")
                    if isinstance(target, str) and target:
                        repair_groups[sibling_scope(_string(coordinator, "scope_path"), target)] = (
                            repair_groups[_string(coordinator, "scope_path")]
                        )
                nodes = list(
                    NodeRun.objects.filter(run=run, pk__gt=since)
                    .annotate(
                        has_attempt=models.Exists(
                            NodeAttempt.objects.filter(node_run_id=models.OuterRef("pk"))
                        ),
                        latest_started_at=models.Subquery(
                            NodeAttempt.objects.filter(node_run_id=models.OuterRef("pk"))
                            .order_by("-attempt_number")
                            .values("started_at")[:1]
                        ),
                        latest_ended_at=models.Subquery(
                            NodeAttempt.objects.filter(node_run_id=models.OuterRef("pk"))
                            .order_by("-attempt_number")
                            .values("ended_at")[:1]
                        ),
                    )
                    .order_by("pk")[: bounded + 1]
                )
                records, more = _bounded_page(
                    nodes,
                    bounded,
                    lambda node: _node_record(
                        node,
                        snapshot,
                        dispatch_paused=_boolean(run, "dispatch_paused"),
                        repair_groups=repair_groups,
                    ),
                    byte_budget=byte_budget,
                )
            else:
                query = HumanInteraction.objects.select_related("node_run", "attempt").filter(
                    run=run, pk__gt=since
                )
                if pending_only:
                    query = query.filter(status=InteractionStatus.PENDING.value)
                if interaction_id is not None:
                    query = query.filter(pk=interaction_id)
                interactions = list(query.order_by("pk")[: bounded + 1])
                records, more = _bounded_page(
                    interactions, bounded, _interaction_record, byte_budget=byte_budget
                )
            result[collection] = records
            next_value = int(str(records[-1]["id"])) if more and records else None
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except DatabaseError:
            message = "Relay could not read run detail."
            raise PersistenceError(message, context={"run": run_id}) from None
        else:
            return result, next_value

    def page_events(
        self,
        run_id: str,
        since: int,
        limit: int,
        *,
        scope_path: str | None = None,
        attempt_number: int | None = None,
        latest: bool = False,
        before: int | None = None,
    ) -> tuple[list[dict[str, object]], int | None]:
        bounded = min(max(limit, 1), API_MAX_PAGE)
        try:
            _require_run(Run.objects.filter(pk=run_id).first(), run_id)
            query = RunEvent.objects.filter(run_id=run_id, id__gt=since).order_by("id")
            if scope_path is not None:
                parse_scope_path(scope_path)
                query = query.filter(node_run__scope_path=scope_path)
            if attempt_number is not None:
                query = query.filter(attempt__attempt_number=attempt_number)
            if scope_path is not None or attempt_number is not None:
                query = query.filter(sensitivity=EventSensitivity.NORMAL.value)
            if before is not None:
                query = query.filter(id__lt=before)
            if latest:
                query = query.order_by("-id")
            rows = list(query[: bounded + 1])
            events, more = _bounded_page(rows, bounded, _event_record)
            next_value = int(str(events[-1]["id"])) if more and events else None
            if latest:
                events.reverse()
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except DatabaseError:
            message = "Relay could not read the run event page."
            raise PersistenceError(message, context={"run": run_id}) from None
        else:
            return events, next_value

    def run_job(
        self, run_id: str, scope_path: str, *, since: int, limit: int
    ) -> tuple[dict[str, object], int | None]:
        """Read captured instructions and a bounded page of this job's attempts."""
        parse_scope_path(scope_path)
        bounded = min(max(limit, 1), API_MAX_PAGE)
        try:
            with transaction.atomic():
                run = _require_run(
                    Run.objects.select_related("snapshot").filter(pk=run_id).first(), run_id
                )
                node = _require_job(
                    NodeRun.objects.filter(run=run, scope_path=scope_path).first(),
                    run_id,
                    scope_path,
                )
                frozen = _mapping(node, "frozen_def")
                snapshot = _related(run, "snapshot", RunSnapshot)
                references = frozen.get("prompts", [])
                contents = _resolved_prompt_contents(snapshot, frozen)
                instructions: list[dict[str, object]] = []
                remaining = API_MAX_PAGE_BYTES // 4
                for index, content in enumerate(contents):
                    reference = references[index] if isinstance(references, list) else {}
                    text = _truncate_utf8(content, max(remaining, 0))
                    remaining -= len(text.encode("utf-8"))
                    instructions.append(
                        {"reference": reference, "text": text, "truncated": text != content}
                    )
                attempts = list(
                    NodeAttempt.objects.filter(node_run=node, pk__gt=since).order_by("pk")[
                        : bounded + 1
                    ]
                )
                records, more = _bounded_page(attempts, bounded, _job_attempt_record)
                result = {
                    "scope_path": scope_path,
                    "working_folder": _string(run, "worktree_path"),
                    "node_type": _string(node, "node_type"),
                    "status": _string(node, "status"),
                    "writes": _boolean(node, "writes"),
                    "command": frozen.get("run"),
                    "retry_settings": (
                        _retry_configuration(node, snapshot)
                        if _string(node, "node_type") == NodeType.AGENT.value
                        and _string(node, "status") == NodeStatus.FAILED.value
                        else None
                    ),
                    "prompt": frozen.get("prompt"),
                    "instructions": instructions,
                    "outputs": _mapping(node, "outputs"),
                    "attempts": records,
                    "latest_attempt": _job_attempt_record(latest)
                    if (
                        latest := NodeAttempt.objects.filter(node_run=node)
                        .order_by("-attempt_number")
                        .first()
                    )
                    is not None
                    else None,
                }
                next_value = int(str(records[-1]["id"])) if more and records else None
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except DatabaseError:
            message = "Relay could not read this job's attempts."
            raise PersistenceError(message, context={"run": run_id, "job": scope_path}) from None
        else:
            return result, next_value

    def run_workflow(self, run_id: str) -> dict[str, object]:
        """Read the immutable workflow captured for a run, with a bounded preview."""
        try:
            run = _require_run(
                Run.objects.select_related("snapshot").filter(pk=run_id).first(), run_id
            )
            snapshot = _related(run, "snapshot", RunSnapshot)
            content = _string(snapshot, "workflow_yaml").encode("utf-8")
            return {
                "workflow_key": _string(run, "workflow_key"),
                "yaml": content[:REVIEW_PREVIEW_MAX_BYTES].decode("utf-8", errors="ignore"),
                "truncated": len(content) > REVIEW_PREVIEW_MAX_BYTES,
                "sha256": sha256(content).hexdigest(),
            }
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except DatabaseError:
            message = "Relay could not read the captured workflow."
            raise PersistenceError(message, context={"run": run_id}) from None

    def page_artifacts(
        self,
        run_id: str,
        since: int,
        limit: int,
    ) -> tuple[list[dict[str, object]], int | None]:
        """Read retained artifact metadata by monotonic primary-key cursor."""
        bounded = min(max(limit, 1), API_MAX_PAGE)
        try:
            _require_run(Run.objects.filter(pk=run_id).first(), run_id)
            rows = list(
                Artifact.objects.filter(
                    attempt__node_run__run_id=run_id,
                    pk__gt=since,
                )
                .select_related("attempt__node_run")
                .order_by("pk")[: bounded + 1]
            )
            records, more = _bounded_page(rows, bounded, _artifact_record)
            next_value = int(str(records[-1]["id"])) if more and records else None
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except DatabaseError:
            message = "Relay could not list retained run artifacts."
            raise PersistenceError(message, context={"run": run_id}) from None
        else:
            return records, next_value

    def artifact_file(self, artifact_id: str) -> tuple[Path, str, str]:
        from relay.paths import artifacts_dir, safe_resolve

        try:
            row = _require_artifact(
                Artifact.objects.filter(
                    pk=artifact_id, preservation_state=PreservationState.PRESERVED.value
                ).first()
            )
            path = _require_retained_file(
                safe_resolve(artifacts_dir(), _string(row, "retained_path"))
            )
            return path, _string(row, "declared_name"), _string(row, "media_type")
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except DatabaseError:
            message = "Relay could not resolve the retained artifact."
            raise PersistenceError(message) from None


def _append_event(
    run: Run,
    event_type: str,
    source: EventSource,
    payload: Mapping[str, object],
    *,
    node: NodeRun | None = None,
    attempt: NodeAttempt | None = None,
    sensitivity: EventSensitivity = EventSensitivity.NORMAL,
) -> RunEvent:
    key = payload.get("idempotency_key")
    return RunEvent.objects.create(
        run=run,
        node_run=node,
        attempt=attempt,
        type=event_type,
        idempotency_key=key if isinstance(key, str) else None,
        version=1,
        source=source.value,
        payload=dict(payload),
        sensitivity=sensitivity.value,
    )


def _bounded_attempt_event_payload(
    payload: Mapping[str, object],
    node: NodeRun,
    attempt: NodeAttempt,
) -> dict[str, object]:
    event_payload = dict(payload)
    event_payload["scope_path"] = _string(node, "scope_path")
    event_payload["attempt_number"] = _integer(attempt, "attempt_number")
    try:
        encoded = json.dumps(
            event_payload,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        message = "An attempt event payload is not JSON-compatible."
        raise PersistenceError(message, context={"node": _identifier(attempt)}) from None
    if len(encoded) > EVENT_MAX_PAYLOAD_BYTES:
        message = "An attempt event exceeded Relay's persisted payload limit."
        raise PersistenceError(message, context={"node": _identifier(attempt)})
    return event_payload


def _truncate_utf8(value: str, limit: int) -> str:
    """``aéz`` with a 2-byte limit -> ``a``; with 3 bytes -> ``aé``."""
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    end = limit
    while end > 0 and (encoded[end] & 0xC0) == 0x80:
        end -= 1
    return encoded[:end].decode("utf-8")


def _bounded_interaction_request(
    prompt: str,
    options: tuple[Mapping[str, object], ...],
) -> dict[str, object]:
    """Keep the public interaction useful while honoring the persisted event ceiling."""
    # Reserve half the event ceiling for scope, attempt, and response metadata.
    budget = EVENT_MAX_PAYLOAD_BYTES // 2
    payload = {
        "prompt": _truncate_utf8(prompt, budget),
        "options": [],
    }
    retained = []
    byte_count = len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    for option in options:
        record = dict(option)
        encoded = json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        # Each option is encoded once; later options add one JSON comma byte.
        added_bytes = len(encoded) + (1 if retained else 0)
        if byte_count + added_bytes > budget:
            payload["options_truncated"] = True
            break
        retained.append(record)
        byte_count += added_bytes
    payload["options"] = retained
    return payload


def _control_public_result(state: str) -> ControlResult:
    if state == ControlState.APPLIED.value:
        return ControlResult.ALREADY_APPLIED
    if state == ControlState.STALE.value:
        return ControlResult.STALE
    if state == ControlState.INVALID.value:
        return ControlResult.INVALID
    return ControlResult.ACCEPTED


def _control_replay_result(state: str) -> ControlResult:
    if state == ControlState.STALE.value:
        return ControlResult.STALE
    if state == ControlState.INVALID.value:
        return ControlResult.INVALID
    return ControlResult.ALREADY_APPLIED


def _interaction_accepts_payload(
    kind: str,
    payload: Mapping[str, object],
    interaction: HumanInteraction,
) -> bool:
    """Validate an answer against the exact pending interaction it targets."""
    if "interaction_id" in payload and payload["interaction_id"] != _identifier(interaction):
        return False
    if "feedback" in payload:
        feedback = payload["feedback"]
        if not isinstance(feedback, str) or not feedback.strip():
            return False
    if kind == ControlKind.PERMISSION_ANSWER.value:
        decision = payload.get("decision")
        request = _mapping(interaction, "request_payload")
        options = request.get("options")
        if not isinstance(decision, str) or not isinstance(options, list):
            return False
        return any(isinstance(option, dict) and option.get("id") == decision for option in options)
    if kind == ControlKind.ELICITATION_ANSWER.value:
        value = payload.get("value")
        return value is None or isinstance(value, dict)
    return True


def _missing_dispatch_claim() -> NoReturn:
    message = "A dispatched node has no durable claim."
    raise PersistenceError(message)


def _invalid_rerun_target(run_id: str, scope_path: str | None = None) -> NoReturn:
    if scope_path is None:
        message = "Only a failed run can rerun a node."
        raise PermissionFlowError(message, context={"run": run_id})
    message = "Only the failed node can be selected for rerun."
    raise PermissionFlowError(message, context={"run": run_id, "node": scope_path})


def _scope_persistence_error(message: str, run_id: str) -> NoReturn:
    raise PersistenceError(message, context={"run": run_id})


def _resolved_prompt_contents(
    snapshot: RunSnapshot, frozen: Mapping[str, object]
) -> tuple[str, ...]:
    references = frozen.get("prompts", [])
    if not isinstance(references, list):
        message = "The frozen node prompt list is invalid."
        raise PersistenceError(message)
    rows = snapshot.resolved_prompts
    if not isinstance(rows, list):
        message = "The run snapshot prompt list is invalid."
        raise PersistenceError(message)
    contents = []
    for reference in references:
        if not isinstance(reference, dict):
            message = "A frozen prompt reference is invalid."
            raise PersistenceError(message)
        source = "global" if "global" in reference else "local"
        value = reference.get(source)
        match = next(
            (
                row
                for row in rows
                if isinstance(row, dict)
                and row.get("source") == source
                and row.get("reference") == value
                and isinstance(row.get("content"), str)
            ),
            None,
        )
        if match is None:
            message = "A frozen prompt is missing from the immutable run snapshot."
            raise PersistenceError(message)
        content = match.get("content")
        if not isinstance(content, str):
            message = "A snapshotted prompt has invalid content."
            raise PersistenceError(message)
        contents.append(content)
    return tuple(contents)


def _reject_active_instance() -> NoReturn:
    message = "Another Relay supervisor is already active."
    raise ConfigError(
        message,
        next_action=("Use the running Relay instance or stop it before starting another one."),
    )


def _lost_instance_lease() -> NoReturn:
    message = "Relay lost ownership of the supervisor lease."
    raise PersistenceError(message)


def _too_many_interrupted_runs() -> NoReturn:
    message = "Too many interrupted runs require one bounded startup pass."
    raise PersistenceError(
        message,
        next_action="Clean old retained runs before starting Relay again.",
    )


class DjangoExecutionStore(DjangoAgentStore):
    """Short-transaction adapter for execution, dispatch, controls, and recovery."""

    def acquire_instance(self, process_id: int, host: str) -> str:
        """Acquire the singleton supervisor lease or replace an expired owner."""
        cutoff = timezone.now() - timedelta(seconds=INSTANCE_STALE_AFTER_SECONDS)
        try:
            with transaction.atomic():
                existing = Instance.objects.select_for_update().filter(singleton_key=1).first()
                if existing is not None:
                    if (
                        _integer(existing, "pid") == process_id
                        and _string(existing, "host") == host
                    ):
                        _set_model_field(existing, "heartbeat_at", timezone.now())
                        _set_model_field(existing, "shutdown_requested", False)
                        existing.save(update_fields=("heartbeat_at", "shutdown_requested"))
                        return _identifier(existing)
                    if existing.heartbeat_at > cutoff:
                        _reject_active_instance()
                    existing.delete()
                instance = Instance.objects.create(pid=process_id, host=host)
                return _identifier(instance)
        except ConfigError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not acquire the local supervisor lease."
            raise PersistenceError(message) from None

    def heartbeat_instance(self, instance_id: str) -> bool:
        try:
            updated = Instance.objects.filter(
                pk=instance_id,
                singleton_key=1,
                shutdown_requested=False,
            ).update(heartbeat_at=timezone.now())
        except DatabaseError:
            message = "Relay could not update the supervisor heartbeat."
            raise PersistenceError(message) from None
        else:
            return updated == 1

    def request_orderly_shutdown(self, instance_id: str) -> int:
        """Gate launch, mark active runs interrupted, and request worker cancellation."""
        try:
            with transaction.atomic():
                instance = Instance.objects.select_for_update().filter(pk=instance_id).first()
                if instance is None:
                    _lost_instance_lease()
                now = timezone.now()
                _set_model_field(instance, "shutdown_requested", True)
                _set_model_field(instance, "heartbeat_at", now)
                instance.save(update_fields=("shutdown_requested", "heartbeat_at"))

                runs = list(
                    Run.objects.select_for_update().filter(
                        status__in=(
                            RunStatus.RUNNING.value,
                            RunStatus.PAUSED_WAIT.value,
                        )
                    )
                )
                for run in runs:
                    transition = transition_run(_string(run, "status"), "orderly_shutdown")
                    _set_model_field(run, "status", transition.status)
                    run.save(update_fields=("status",))
                    _append_event(
                        run,
                        transition.event,
                        EventSource.RUN,
                        {"status": transition.status},
                    )

                expires = now + timedelta(seconds=CONTROL_REQUEST_TTL_SECONDS)
                attempts = list(
                    NodeAttempt.objects.select_for_update().filter(
                        status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value)
                    )
                )
                for attempt in attempts:
                    ControlRequest.objects.get_or_create(
                        attempt=attempt,
                        idempotency_key=f"shutdown:{instance_id}:{_identifier(attempt)}",
                        defaults={
                            "kind": ControlKind.CANCEL.value,
                            "payload": {"reason": "orderly_shutdown"},
                            "state": ControlState.PENDING.value,
                            "expires_at": expires,
                        },
                    )
                return len(attempts)
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not persist orderly-shutdown intent."
            raise PersistenceError(message) from None

    def active_attempt_processes(self) -> tuple[tuple[str, int], ...]:
        try:
            rows = NodeAttempt.objects.filter(
                status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
                process_pid__isnull=False,
            ).values_list("pk", "process_pid")
            return tuple(
                (str(attempt_id), process_id)
                for attempt_id, process_id in rows
                if isinstance(process_id, int)
            )
        except DatabaseError:
            message = "Relay could not enumerate active attempt processes."
            raise PersistenceError(message) from None

    def _stop_active_attempts(self, reason: AttemptStopReason) -> int:
        attempts = NodeAttempt.objects.filter(
            status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value)
        )
        if reason is AttemptStopReason.WORKER_LOST:
            # Human waits and yielded structural scopes have no worker to lose.
            attempts = attempts.exclude(node_run__node_type=NodeType.HUMAN_WAIT.value).exclude(
                status=AttemptStatus.WAITING.value,
                node_run__node_type__in=(NodeType.LOOP.value, NodeType.SUBWORKFLOW.value),
            )
        attempt_ids = list(attempts.order_by("started_at", "pk").values_list("pk", flat=True))
        stopped = 0
        for attempt_id in attempt_ids:
            with transaction.atomic():
                attempt = (
                    NodeAttempt.objects.select_for_update()
                    .filter(
                        pk=attempt_id,
                        status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
                    )
                    .first()
                )
                if attempt is None:
                    continue
                self._discard_attempt_mailbox(attempt)
                self.finish_attempt(
                    _identifier(attempt),
                    ExecutionOutcome(
                        OutcomeKind.FAILED, stop_reason=reason, error_code=reason.value
                    ),
                    _string(attempt, "starting_head"),
                )
                DispatchClaim.objects.filter(attempt=attempt).update(
                    state=DispatchState.CONSUMED.value, consumed_at=timezone.now()
                )
                self.release_attempt_lock(_identifier(attempt))
                stopped += 1
        return stopped

    def interrupt_active_attempts(self) -> int:
        """Force any attempt left after child exit into the resumable terminal state."""
        try:
            stopped = self._stop_active_attempts(AttemptStopReason.INTERRUPTED)
        except PersistenceError:
            raise
        except DatabaseError:
            message = "Relay could not reconcile attempts after supervisor shutdown."
            raise PersistenceError(message) from None
        else:
            return stopped

    def fail_worker_attempts(self) -> int:
        """Fail attempts whose worker process exited without orderly-shutdown intent."""
        try:
            stopped = self._stop_active_attempts(AttemptStopReason.WORKER_LOST)
        except PersistenceError:
            raise
        except DatabaseError:
            message = "Relay could not record attempts lost with the worker process."
            raise PersistenceError(message) from None
        else:
            return stopped

    def release_instance(self, instance_id: str) -> None:
        try:
            Instance.objects.filter(pk=instance_id, singleton_key=1).delete()
        except DatabaseError:
            message = "Relay could not release the supervisor lease."
            raise PersistenceError(message) from None

    def create_pending_run(
        self,
        project_id: str,
        request: LaunchRequest,
        source_commit: str,
        snapshot: SnapshotBundle,
        nodes: Mapping[str, NodeDefinition],
    ) -> str:
        """Create the complete immutable launch record in one transaction."""
        run_id = str(uuid.uuid4())
        branch = run_branch(run_id)
        worktree = run_worktree_path(run_id)
        policy = load_workflow_text(snapshot.workflow_yaml, source=Path(request.workflow_key))
        try:
            with transaction.atomic():
                instance = Instance.objects.select_for_update().filter(singleton_key=1).first()
                if shutdown_marker_path().exists() or (
                    instance is not None and _boolean(instance, "shutdown_requested")
                ):
                    message = "Relay is shutting down and is not accepting new runs."
                    raise ConfigError(
                        message,
                        next_action="Start Relay again, then relaunch the workflow.",
                    )
                project = _project_by_id(project_id)
                number = _integer(project, "next_run_number")
                Project.objects.filter(pk=project.pk).update(next_run_number=number + 1)
                run_transition = transition_run(None, "launch")
                run = Run.objects.create(
                    id=run_id,
                    project=project,
                    workflow_key=request.workflow_key,
                    number=number,
                    title=policy.definition.name,
                    source_branch=request.source_branch,
                    status=run_transition.status,
                    source_commit=source_commit,
                    run_branch=branch,
                    worktree_path=str(worktree),
                    worktree_state=WorktreeState.NONE.value,
                    cleanup_policy=request.cleanup_policy,
                    launcher=request.launcher,
                    entry_point=request.entry_point,
                    recorded_head=source_commit,
                    recovery_policy=snapshot.launch_defaults.get(
                        "recovery", policy.definition.recovery.model_dump(mode="json")
                    ),
                )
                RunSnapshot.objects.create(run=run, **snapshot.to_dict())
                _append_event(
                    run,
                    run_transition.event,
                    EventSource.RUN,
                    {"status": run_transition.status},
                )
                for node_id, definition in nodes.items():
                    node_transition = transition_node(None, "create")
                    node = NodeRun.objects.create(
                        run=run,
                        scope_path=node_scope(None, node_id),
                        parent_scope_path=None,
                        node_id=node_id,
                        node_type=definition.type,
                        frozen_def=definition.model_dump(mode="json", by_alias=True),
                        status=node_transition.status,
                        writes=getattr(definition, "writes", False),
                    )
                    _append_event(
                        run,
                        node_transition.event,
                        EventSource.NODE,
                        {
                            "scope_path": _string(node, "scope_path"),
                            "node_type": definition.type,
                            "status": node_transition.status,
                        },
                        node=node,
                    )
                return run_id
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not persist the pending run and immutable snapshot."
            raise PersistenceError(message, context={"run": run_id}) from None

    def mark_run_started(
        self,
        run_id: str,
        branch: str,
        worktree: Path,
        source_commit: str,
    ) -> None:
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=run_id)
                transition = transition_run(_string(run, "status"), "worktree_ready")
                if not transition.changed:
                    return
                _set_model_field(run, "run_branch", branch)
                _set_model_field(run, "worktree_path", str(worktree))
                _set_model_field(run, "source_commit", source_commit)
                _set_model_field(run, "recorded_head", source_commit)
                _set_model_field(run, "worktree_state", WorktreeState.CREATED.value)
                _set_model_field(run, "status", transition.status)
                _set_model_field(run, "started_at", timezone.now())
                run.save(
                    update_fields=(
                        "run_branch",
                        "worktree_path",
                        "source_commit",
                        "recorded_head",
                        "worktree_state",
                        "status",
                        "started_at",
                    )
                )
                _append_event(
                    run,
                    transition.event,
                    EventSource.RUN,
                    {"status": transition.status},
                )
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not mark the run worktree ready."
            raise PersistenceError(message, context={"run": run_id}) from None

    def mark_run_launch_failed(self, run_id: str, error: RelayError) -> None:
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=run_id)
                transition = transition_run(_string(run, "status"), "worktree_failed")
                if not transition.changed:
                    return
                _set_model_field(run, "status", transition.status)
                _set_model_field(run, "worktree_state", WorktreeState.NONE.value)
                _set_model_field(run, "failure_code", error.error_code)
                _set_model_field(run, "failure_summary", error.message)
                _set_model_field(run, "ended_at", timezone.now())
                run.save(
                    update_fields=(
                        "status",
                        "worktree_state",
                        "failure_code",
                        "failure_summary",
                        "ended_at",
                    )
                )
                _append_event(
                    run,
                    transition.event,
                    EventSource.RUN,
                    {"status": transition.status, "failure_code": error.error_code},
                )
                _append_event(
                    run,
                    "error",
                    EventSource.SYSTEM,
                    error.to_envelope(),
                )
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not retain the failed launch state."
            raise PersistenceError(message, context={"run": run_id}) from None

    def run_graph(self, run_id: str) -> CompiledGraph:
        """Reuse this immutable run's bounded cached graph."""
        try:
            return _compiled_run_graph(run_id)
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not load the immutable scheduling graph."
            raise PersistenceError(message, context={"run": run_id}) from None

    def reachable_run_nodes(self, run_id: str, entry_root: str | None) -> frozenset[str]:
        return _reachable_run_nodes(run_id, entry_root)

    def load_run_schedule(
        self, run_id: str, node_ids: tuple[str, ...] | None = None
    ) -> RunSchedule:
        try:
            run = Run.objects.select_related("snapshot").get(pk=run_id)
            snapshot = _related(run, "snapshot", RunSnapshot)
            graph = self.run_graph(run_id)
            required = (
                set(graph.nodes)
                if node_ids is None
                else {
                    name
                    for node_id in node_ids
                    for name in (node_id, *graph.dependencies[node_id], *graph.activators[node_id])
                }
            )
            rows = {
                _string(node, "node_id"): node
                for node in NodeRun.objects.filter(
                    run=run, parent_scope_path__isnull=True, node_id__in=required
                )
            }
            if set(rows) != required:
                _reject_schedule_mismatch(run_id)
            scheduled = {
                node_id: ScheduledNode(
                    _identifier(rows[node_id]),
                    node_id,
                    definition,
                    _string(rows[node_id], "status"),
                    _mapping(rows[node_id], "outputs"),
                    (value if isinstance((value := rows[node_id].selected_branch), str) else None),
                )
                for node_id in required
                for definition in (graph.nodes[node_id],)
            }
            return RunSchedule(
                run_id,
                scheduled,
                _mapping(snapshot, "typed_inputs"),
                {
                    "run_id": run_id,
                    "workflow_key": _string(run, "workflow_key"),
                    "source_commit": _string(run, "source_commit"),
                    "run_branch": _string(run, "run_branch"),
                    "status": _string(run, "status"),
                    "dispatch_paused": _boolean(run, "dispatch_paused"),
                },
                run.entry_point if isinstance(run.entry_point, str) else None,
            )
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not load durable scheduling state."
            raise PersistenceError(message, context={"run": run_id}) from None

    def scheduling_changes(self, after: int) -> tuple[int, tuple[SchedulingChange, ...]]:
        """Read only newly committed scheduling events through the primary-key index."""
        try:
            upper = RunEvent.objects.aggregate(value=Max("id"))["value"] or after
            events = list(
                RunEvent.objects.filter(
                    id__gt=after,
                    id__lte=upper,
                    type__in=(
                        "run.started",
                        "run.rerun",
                        "run.resumed",
                        "node.ready",
                        "node.succeeded",
                        "node.failed",
                        "node.canceled",
                        "node.skipped",
                        "node.pending",
                    ),
                    node_run__parent_scope_path__isnull=True,
                    run__status__in=(RunStatus.RUNNING.value, RunStatus.PAUSED_WAIT.value),
                )
                .order_by("id")
                .values_list("id", "run_id", "node_run__node_id")[:RECONCILE_MAX_ITEMS]
            )
            cursor = events[-1][0] if len(events) == RECONCILE_MAX_ITEMS else upper
            return cursor, tuple(
                SchedulingChange(str(run_id), node_id) for _, run_id, node_id in events
            )
        except DatabaseError:
            message = "Relay could not read scheduling changes."
            raise PersistenceError(message) from None

    def latest_event_id(self) -> int:
        try:
            return RunEvent.objects.aggregate(value=Max("id"))["value"] or 0
        except DatabaseError:
            message = "Relay could not read the scheduling cursor."
            raise PersistenceError(message) from None

    def settle_run(self, run_id: str) -> None:
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=run_id)
                self._finish_run_if_terminal(run)
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not settle the run after scheduling."
            raise PersistenceError(message, context={"run": run_id}) from None

    def active_run_ids(self) -> tuple[str, ...]:
        try:
            values = (
                Run.objects.filter(
                    status__in=(RunStatus.RUNNING.value, RunStatus.PAUSED_WAIT.value)
                )
                .order_by("started_at", "pk")
                .values_list("pk", flat=True)[:RECONCILE_MAX_ITEMS]
            )
            return tuple(str(value) for value in values)
        except DatabaseError:
            message = "Relay could not enumerate active runs for scheduling."
            raise PersistenceError(message) from None

    def clean_project_data(
        self, project_id: str, scope: str, *, run_id: str | None = None
    ) -> dict[str, int]:
        """Clean a confirmed category for the project or one explicitly selected run."""
        if run_id is not None:
            # Recovery must not reopen the selected run while its checkout is removed.
            with recovery_workspace_lock(run_id):
                return self._clean_project_data(project_id, scope, run_id=run_id)
        return self._clean_project_data(project_id, scope)

    def _clean_project_data(
        self, project_id: str, scope: str, *, run_id: str | None = None
    ) -> dict[str, int]:
        """Apply the selected cleanup in worktree, ref, then record order."""
        if scope not in {"runs", "worktrees", "branches", "all"}:
            message = "scope must be runs, worktrees, branches, or all."
            raise PermissionFlowError(message)
        try:
            project = _project_by_id(project_id)
            active = Run.objects.filter(project=project).exclude(
                status__in=(
                    RunStatus.SUCCEEDED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELED.value,
                    RunStatus.INTERRUPTED.value,
                )
            )
            if active.exists():
                _reject_active_cleanup(project_id)
            candidates = Run.objects.filter(project=project)
            if run_id is not None:
                # An unknown or foreign run must never fall back to project-wide cleanup.
                runs = [_require_run(candidates.filter(pk=run_id).first(), run_id)]
            else:
                runs = list(candidates.order_by("started_at", "pk"))
            if run_id is not None and scope == "worktrees":
                pending_evidence = Artifact.objects.filter(attempt__node_run__run=runs[0]).exclude(
                    preservation_state=PreservationState.PRESERVED.value
                )
                if pending_evidence.exists():
                    _reject_incomplete_cleanup_evidence(run_id)
            repository = Path(_string(project, "git_root"))
            deleted = {
                "runs": 0,
                "worktrees": 0,
                "branches": 0,
                "attempt_refs": 0,
                "artifact_roots": 0,
                "logs": 0,
            }
            if scope in {"worktrees", "all"}:
                for run in runs:
                    for path in _run_worktree_paths(run):
                        if path.exists():
                            remove_worktree(repository, path)
                            deleted["worktrees"] += 1
                    if _string(run, "worktree_state") != WorktreeState.REMOVED.value:
                        _set_model_field(run, "worktree_state", WorktreeState.REMOVED.value)
                        with transaction.atomic():
                            run.save(update_fields=("worktree_state",))
                            if run_id is not None:
                                _append_event(
                                    run,
                                    "run.cleanup_succeeded",
                                    EventSource.SYSTEM,
                                    {"worktree_state": WorktreeState.REMOVED.value},
                                )
            if scope in {"branches", "all"}:
                for run in runs:
                    worktree = safe_resolve(worktrees_dir(), _string(run, "worktree_path"))
                    if worktree.exists():
                        _reject_branch_with_worktree(_identifier(run))
                    branch = _string(run, "run_branch")
                    if _retained_branch_exists(repository, branch):
                        run_git(repository, ["branch", "-D", branch])
                        deleted["branches"] += 1
                    for retained_ref in _retained_attempt_refs(
                        repository,
                        _identifier(run),
                    ):
                        run_git(repository, ["update-ref", "-d", retained_ref])
                        deleted["attempt_refs"] += 1
            if scope in {"runs", "all"}:
                if scope == "runs":
                    for run in runs:
                        worktrees = _run_worktree_paths(run)
                        branch = _string(run, "run_branch")
                        retained_refs = _retained_attempt_refs(repository, _identifier(run))
                        if (
                            any(worktree.exists() for worktree in worktrees)
                            or _retained_branch_exists(repository, branch)
                            or retained_refs
                        ):
                            _reject_run_with_git_state(_identifier(run))
                artifact_root = artifacts_dir()
                for run in runs:
                    eligible = frozenset(
                        str(value)
                        for value in NodeAttempt.objects.filter(
                            node_run__run=run, ended_at__isnull=False
                        ).values_list("pk", flat=True)
                    )
                    cleanup_run_resources(_identifier(run), eligible_attempts=eligible)
                    directory = safe_resolve(artifact_root, _identifier(run))
                    if directory.is_dir():
                        shutil.rmtree(directory)
                        deleted["artifact_roots"] += 1
                deleted["runs"] = len(runs)
                Run.objects.filter(pk__in=[run.pk for run in runs]).delete()
            # Process logs are shared across runs; selected-run deletion cannot clear them.
            if scope == "all" and run_id is None:
                deleted["logs"] = clear_application_logs()
        except (PermissionFlowError, PersistenceError, ProjectDiscoveryError):
            raise
        except (DatabaseError, OSError):
            message = "Relay could not complete the confirmed data cleanup."
            raise PersistenceError(message, context={"project": project_id}) from None
        else:
            return deleted

    def _record_cleanup_failure(self, run_id: str, error: RelayError) -> None:
        """Keep a successful run terminal while surfacing recoverable cleanup failure."""
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().filter(pk=run_id).first()
                if run is None:
                    return
                _set_model_field(run, "worktree_state", WorktreeState.CLEANUP_FAILED.value)
                run.save(update_fields=("worktree_state",))
                payload = error.to_envelope()
                payload["worktree_state"] = WorktreeState.CLEANUP_FAILED.value
                _append_event(run, "run.cleanup_failed", EventSource.SYSTEM, payload)
        except DatabaseError:
            LOGGER.exception(
                "Relay could not persist worktree cleanup failure",
                extra={"run": run_id},
            )

    def clean_run_resources(self, run_id: str) -> int:
        """Clean scratch folders only for already finished attempts of a terminal run."""
        try:
            run = _require_run(Run.objects.filter(pk=run_id).first(), run_id)
            if _string(run, "status") not in {
                RunStatus.SUCCEEDED.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELED.value,
            }:
                message = "Temporary resources cannot be cleaned while this run is active."
                raise PermissionFlowError(message)
            # A concurrent retry receives new attempt IDs and cannot enter this set.
            eligible = frozenset(
                str(value)
                for value in NodeAttempt.objects.filter(
                    node_run__run=run, ended_at__isnull=False
                ).values_list("pk", flat=True)
            )
            removed = cleanup_run_resources(run_id, eligible_attempts=eligible)
            with transaction.atomic():
                current = Run.objects.filter(pk=run_id).first()
                if current is not None:
                    _append_event(
                        current,
                        "resource.cleanup_succeeded",
                        EventSource.SYSTEM,
                        {"removed": removed},
                    )
        except DatabaseError:
            message = "Relay could not clean the run's temporary resources."
            raise PersistenceError(message) from None
        else:
            return removed

    def _cleanup_terminal_resources(self, run_id: str) -> None:
        try:
            self.clean_run_resources(run_id)
        except RelayError:
            LOGGER.exception("Finished run scratch cleanup failed", extra={"run": run_id})
            try:
                with transaction.atomic():
                    run = Run.objects.filter(pk=run_id).first()
                    if run is not None:
                        _append_event(
                            run,
                            "resource.cleanup_failed",
                            EventSource.SYSTEM,
                            {
                                "message": "Temporary resources could not be removed. "
                                "Retry cleanup from the run's advanced view."
                            },
                        )
            except DatabaseError:
                LOGGER.exception(
                    "Relay could not record scratch cleanup failure", extra={"run": run_id}
                )

    def _cleanup_successful_run(self, run_id: str) -> None:
        """Remove one successful primary worktree after its transaction commits."""
        try:
            run = Run.objects.select_related("project").get(pk=run_id)
            if (
                _string(run, "status") != RunStatus.SUCCEEDED.value
                or _string(run, "cleanup_policy") != CleanupPolicy.CLEAN_ON_SUCCESS.value
                or _string(run, "worktree_state") != WorktreeState.CREATED.value
            ):
                return
            pending_evidence = Artifact.objects.filter(attempt__node_run__run=run).exclude(
                preservation_state=PreservationState.PRESERVED.value
            )
            if pending_evidence.exists():
                message = (
                    "Relay retained the run worktree because evidence preservation is incomplete."
                )
                raise PersistenceError(message, context={"run": run_id})
            project = _related(run, "project", Project)
            repository = Path(_string(project, "git_root"))
            worktree = safe_resolve(worktrees_dir(), _string(run, "worktree_path"))
            if worktree.exists():
                remove_worktree(repository, worktree)
            with transaction.atomic():
                current = Run.objects.select_for_update().filter(pk=run_id).first()
                if current is None:
                    return
                if _string(current, "worktree_state") != WorktreeState.CREATED.value:
                    return
                _set_model_field(current, "worktree_state", WorktreeState.REMOVED.value)
                current.save(update_fields=("worktree_state",))
                _append_event(
                    current,
                    "run.cleanup_succeeded",
                    EventSource.SYSTEM,
                    {"worktree_state": WorktreeState.REMOVED.value},
                )
        except ObjectDoesNotExist:
            return
        except RelayError as error:
            LOGGER.exception(
                "Relay could not remove a successful run worktree",
                extra={"run": run_id},
            )
            self._record_cleanup_failure(run_id, error)
        except (DatabaseError, OSError):
            LOGGER.exception(
                "Unexpected successful-run cleanup failure",
                extra={"run": run_id},
            )
            error = PersistenceError(
                "Relay could not remove the successful run worktree.",
                context={"run": run_id},
                next_action=(
                    "Close processes using the worktree, then run confirmed data cleanup."
                ),
            )
            self._record_cleanup_failure(run_id, error)

    def run_merge_target(self, run_id: str) -> MergeTarget | None:
        run = (
            Run.objects.select_related("project")
            .filter(pk=run_id, status=RunStatus.COMPLETING.value)
            .first()
        )
        if run is None:
            return None
        project = _related(run, "project", Project)
        return MergeTarget(
            Path(_string(project, "git_root")),
            safe_resolve(worktrees_dir(), _string(run, "worktree_path")),
            run.source_branch if isinstance(run.source_branch, str) else None,
            _string(run, "run_branch"),
            _string(run, "recorded_head"),
            run.merged_commit if isinstance(run.merged_commit, str) else None,
        )

    def require_completion_evidence(self, run_id: str) -> None:
        if (
            Artifact.objects.filter(attempt__node_run__run_id=run_id)
            .exclude(preservation_state=PreservationState.PRESERVED.value)
            .exists()
        ):
            message = "Relay kept the run working copy because evidence preservation is incomplete."
            raise PersistenceError(message, context={"run": run_id})
        run = Run.objects.select_related("project").get(pk=run_id)
        project = _related(run, "project", Project)
        repository = Path(_string(project, "git_root"))
        for attempt in NodeAttempt.objects.filter(
            node_run__run=run,
            node_run__node_type__in=(NodeType.AGENT.value, NodeType.COMMAND.value),
        ):
            validate_attempt_evidence(
                repository, run_id, _identifier(attempt), _string(attempt, "starting_head")
            )

    def record_run_merge(self, run_id: str, commit: str) -> None:
        with transaction.atomic():
            run = Run.objects.select_for_update().get(pk=run_id)
            if _string(run, "status") != RunStatus.COMPLETING.value or run.merged_commit:
                return
            _set_model_field(run, "merged_commit", commit)
            run.save(update_fields=("merged_commit",))
            _append_event(
                run,
                "run.merged",
                EventSource.RUN,
                {"branch": run.source_branch, "merged_commit": commit},
            )

    def finish_run_completion(self, run_id: str, error: RelayError | None) -> None:
        with transaction.atomic():
            run = Run.objects.select_for_update().get(pk=run_id)
            if _string(run, "status") != RunStatus.COMPLETING.value:
                return
            transition = transition_run(
                _string(run, "status"),
                "completion_failed" if error else "completion_succeeded",
            )
            _set_model_field(run, "status", transition.status)
            _set_model_field(run, "ended_at", timezone.now())
            if error:
                _set_model_field(run, "failure_code", error.error_code)
                _set_model_field(run, "failure_summary", error.message)
                _append_event(run, "error", EventSource.SYSTEM, error.to_envelope())
            else:
                _set_model_field(run, "worktree_state", WorktreeState.REMOVED.value)
                _append_event(
                    run,
                    "run.cleanup_succeeded",
                    EventSource.SYSTEM,
                    {"worktree_state": WorktreeState.REMOVED.value},
                )
            run.save(
                update_fields=(
                    "status",
                    "ended_at",
                    "failure_code",
                    "failure_summary",
                    "worktree_state",
                )
            )
            _append_event(
                run,
                transition.event,
                EventSource.RUN,
                {
                    "status": transition.status,
                    "failure_code": run.failure_code,
                    "failure_summary": run.failure_summary,
                },
            )
            transaction.on_commit(lambda: self._cleanup_terminal_resources(run_id))

    def _complete_merged_run(self, run_id: str) -> None:
        try:
            complete_run_merge(self, run_id)
        except RelayError as error:
            self.finish_run_completion(run_id, error)
        except (DatabaseError, ObjectDoesNotExist):
            LOGGER.exception(
                "Could not persist run integration; reconciliation will resume it",
                extra={"run": run_id},
            )

    def resume_run_completions(self) -> None:
        for run_id in (
            Run.objects.filter(status=RunStatus.COMPLETING.value)
            .order_by("created_at")
            .values_list("pk", flat=True)[:RECONCILE_MAX_ITEMS]
        ):
            self._complete_merged_run(str(run_id))

    def append_attempt_event(
        self,
        attempt_id: str,
        event_type: str,
        source: EventSource,
        payload: Mapping[str, object],
        *,
        sensitivity: EventSensitivity = EventSensitivity.NORMAL,
    ) -> None:
        try:
            with transaction.atomic():
                attempt = (
                    NodeAttempt.objects.select_related("node_run__run")
                    .select_for_update()
                    .get(pk=attempt_id)
                )
                node = _related(attempt, "node_run", NodeRun)
                run = _related(node, "run", Run)
                event_payload = _bounded_attempt_event_payload(payload, node, attempt)
                _append_event(
                    run,
                    event_type,
                    source,
                    event_payload,
                    node=node,
                    attempt=attempt,
                    sensitivity=sensitivity,
                )
        except PersistenceError:
            raise
        except DatabaseError:
            message = "Relay could not persist the attempt event."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def _claim_context(
        self,
        run: Run,
        node: NodeRun,
        snapshot: RunSnapshot,
        frozen: Mapping[str, object],
    ) -> _ClaimContext:
        parent_scope = node.parent_scope_path
        if parent_scope is not None and not isinstance(parent_scope, str):
            message = "The stored node parent scope is invalid."
            raise PersistenceError(message)
        inputs = (
            _mapping(snapshot, "typed_inputs")
            if parent_scope is None
            else _mapping(node, "scope_inputs")
        )
        needs = _string_list(frozen.get("needs", []), field="needs")
        upstream = {}
        repaired_outputs = {}
        scope_path = _string(node, "scope_path")
        for needed in needs:
            dependency = NodeRun.objects.filter(
                run=run,
                scope_path=sibling_scope(scope_path, needed),
            ).first()
            if dependency is None:
                message = f"The durable dependency {needed!r} is missing."
                raise PersistenceError(message, context={"node": scope_path})
            upstream[needed] = _mapping(dependency, "outputs")
            repair = _mapping(dependency, "frozen_def").get("repair_rule")
            if isinstance(repair, dict) and isinstance(repair.get("source"), str):
                repaired_outputs[repair["source"]] = _mapping(dependency, "outputs")
        # Keep rejected source rows intact; dependents see the accepted verifier's
        # outputs as needs.review.outputs instead of the original rejection.
        upstream.update(repaired_outputs)
        metadata = {
            "run_id": _identifier(run),
            "workflow_key": _string(run, "workflow_key"),
            "source_commit": _string(run, "source_commit"),
            "run_branch": _string(run, "run_branch"),
            "scope_path": scope_path,
            "project_id": _foreign_key_text(run, "project"),
            "project_path": _string(_related(run, "project", Project), "canonical_path"),
            "worktree_path": _string(run, "worktree_path"),
        }
        if isinstance(run.entry_point, str):
            metadata["entry_point"] = run.entry_point
        loop_index = node.loop_index
        if loop_index is not None:
            if not isinstance(loop_index, int) or isinstance(loop_index, bool):
                message = "The stored loop iteration is invalid."
                raise PersistenceError(message, context={"node": scope_path})
            metadata["loop_index"] = loop_index
        route = _effective_route(node, snapshot)
        prompts = _resolved_prompt_contents(snapshot, frozen)
        if parent_scope is not None and _string(node, "node_id") in {"fix", "verify"}:
            # root.relay_repair_review#2 -> root.relay_repair_review. Only an
            # explicitly marked coordinator can add repair instructions.
            coordinator_scope = parent_scope.rsplit("#", maxsplit=1)[0]
            coordinator = NodeRun.objects.filter(run=run, scope_path=coordinator_scope).first()
            repair = (
                _mapping(coordinator, "frozen_def").get("repair_rule")
                if coordinator is not None
                else None
            )
            if isinstance(repair, dict) and isinstance(repair.get("source"), str):
                source_scope = sibling_scope(coordinator_scope, repair["source"])
                report_scope = source_scope
                if isinstance(loop_index, int) and loop_index > 1:
                    report_scope = f"{coordinator_scope}#{loop_index - 1}.verify"
                report = NodeRun.objects.filter(run=run, scope_path=report_scope).first()
                repair_context = {
                    "source_scope": source_scope,
                    "round": loop_index,
                    "max_rounds": _mapping(coordinator, "frozen_def").get("max_iterations"),
                    "rejected_report_scope": report_scope,
                    "rejected_outputs": _mapping(report, "outputs") if report is not None else {},
                    "retained_evidence": str(artifacts_dir() / _identifier(run)),
                }
                metadata["repair"] = repair_context
                instruction = repair.get(f"{_string(node, 'node_id')}_instruction")
                if isinstance(instruction, str):
                    prompts = (
                        *prompts,
                        instruction + "\nRepair context:\n" + json.dumps(repair_context),
                    )
        handoff = route.get("handoff_prompt")
        if isinstance(handoff, str):
            # ("Review the code",) becomes ("Review the code", "Continue...").
            # Captured prompt bytes remain intact; the retry instruction follows them.
            prompts = (*prompts, handoff)
        instruction = _string(node, "recovery_instruction")
        if instruction:
            # ("Review the plan",) gains a separate recovery instruction while
            # the immutable snapshot and provider configuration remain identical.
            prompts = (*prompts, instruction)
            previous = (
                AutomaticRetry.objects.filter(attempt__node_run=node, state="resumed")
                .order_by("-created_at", "-pk")
                .first()
            )
            if previous is not None:
                metadata["recovery"] = {
                    "source_attempt": _foreign_key_text(previous, "attempt"),
                    "instruction_sha256": _string(previous, "instruction_sha256"),
                    "retained_evidence": str(artifacts_dir() / _identifier(run)),
                }
        return _ClaimContext(
            inputs,
            upstream,
            metadata,
            prompts,
            route,
            _mapping(snapshot, "subworkflows"),
        )

    def create_dispatch(self, node_run_id: str) -> str | None:
        try:
            with transaction.atomic():
                node = NodeRun.objects.select_for_update().select_related("run").get(pk=node_run_id)
                run = _related(node, "run", Run)
                resuming = _string(node, "status") == NodeStatus.WAITING.value and _string(
                    node, "node_type"
                ) in {NodeType.LOOP.value, NodeType.SUBWORKFLOW.value}
                if _string(node, "status") in {
                    NodeStatus.RUNNING.value,
                    NodeStatus.SUCCEEDED.value,
                    NodeStatus.SKIPPED.value,
                    NodeStatus.FAILED.value,
                    NodeStatus.CANCELED.value,
                } or (_string(node, "status") == NodeStatus.WAITING.value and not resuming):
                    # Scheduling reads can precede another caller's claim or cancel.
                    # An advanced node must never gain a second dispatch or regress.
                    return None
                transition = transition_node(
                    _string(node, "status"), "scope_ready" if resuming else "dispatch"
                )
                if not transition.changed:
                    existing = (
                        DispatchClaim.objects.filter(
                            node_run=node,
                            state__in=(
                                DispatchState.DISPATCHED.value,
                                DispatchState.CLAIMED.value,
                            ),
                        )
                        .order_by("-created_at")
                        .first()
                    )
                    if existing is None:
                        _missing_dispatch_claim()
                    return _string(existing, "claim_token")
                existing = (
                    DispatchClaim.objects.filter(
                        node_run=node, attempt__status=AttemptStatus.WAITING.value
                    )
                    .order_by("-created_at")
                    .first()
                    if resuming
                    else None
                )
                if resuming and existing is None:
                    _missing_dispatch_claim()
                token = (
                    _string(existing, "claim_token") if existing is not None else uuid.uuid4().hex
                )
                _set_model_field(node, "status", transition.status)
                node.save(update_fields=("status",))
                if existing is not None:
                    _set_model_field(existing, "state", DispatchState.DISPATCHED.value)
                    _set_model_field(existing, "enqueued_at", None)
                    existing.save(update_fields=("state", "enqueued_at"))
                else:
                    DispatchClaim.objects.create(
                        node_run=node, claim_token=token, state=DispatchState.DISPATCHED.value
                    )
                _append_event(
                    run,
                    transition.event,
                    EventSource.NODE,
                    {
                        "scope_path": _string(node, "scope_path"),
                        "node_type": _string(node, "node_type"),
                        "status": transition.status,
                    },
                    node=node,
                )
                return token
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not commit node dispatch intent."
            raise PersistenceError(message, context={"node": node_run_id}) from None

    def mark_dispatch_enqueued(self, claim_token: str) -> None:
        try:
            DispatchClaim.objects.filter(
                claim_token=claim_token,
                state=DispatchState.DISPATCHED.value,
            ).update(enqueued_at=timezone.now())
        except DatabaseError:
            message = "Relay could not record the Huey enqueue time."
            raise PersistenceError(message) from None

    def _claim_record(self, claim_token: str) -> DispatchClaim | None:
        return (
            DispatchClaim.objects.select_for_update()
            .select_related("node_run__run__project", "attempt")
            .filter(claim_token=claim_token)
            .first()
        )

    def claim_dispatch(self, claim_token: str, worker_id: str) -> ClaimResult:
        try:
            with transaction.atomic():
                claim = self._claim_record(claim_token)
                if claim is None or _string(claim, "state") != DispatchState.DISPATCHED.value:
                    return ClaimResult(ClaimDisposition.IGNORED)
                node = _related(claim, "node_run", NodeRun)
                related_run = _related(node, "run", Run)
                run = Run.objects.select_for_update().get(pk=related_run.pk)
                project = _related(run, "project", Project)
                snapshot = _related(run, "snapshot", RunSnapshot)
                if _string(run, "status") not in {
                    RunStatus.RUNNING.value,
                    RunStatus.PAUSED_WAIT.value,
                }:
                    return ClaimResult(ClaimDisposition.IGNORED)
                if _string(node, "status") != NodeStatus.DISPATCHED.value:
                    return ClaimResult(ClaimDisposition.IGNORED)
                if _boolean(run, "dispatch_paused"):
                    # An already queued token can arrive after the owner's pause.
                    # Keep its intent and defer admission; the active attempt is untouched.
                    defer_dispatch(_identifier(run), claim_token)
                    return ClaimResult(ClaimDisposition.BUSY)

                node_type = _string(node, "node_type")
                needs_lock = node_type in {NodeType.AGENT.value, NodeType.COMMAND.value}
                writes = _boolean(node, "writes")
                decision = decide_admission(
                    writes,
                    RunLock.objects.select_for_update()
                    .filter(run=run)
                    .values_list("mode", flat=True),
                )
                if needs_lock and not decision.allowed:
                    defer_dispatch(_identifier(run), claim_token)
                    return ClaimResult(ClaimDisposition.BUSY)

                scope_path = _string(node, "scope_path")
                frozen = _mapping(node, "frozen_def")
                context = self._claim_context(run, node, snapshot, frozen)
                selected_agent = context.route.get("selected_agent", "")
                model_value = context.route.get("model_value", "")
                if not isinstance(selected_agent, str) or not isinstance(model_value, str):
                    message = "The snapshotted agent route is malformed."
                    raise PersistenceError(message, context={"node": scope_path})  # noqa: TRY301
                driver_kind = None
                if node_type == NodeType.AGENT.value:
                    driver_kind = (
                        DriverKind.ANTIGRAVITY.value
                        if selected_agent == "antigravity"
                        else DriverKind.ACP.value
                    )

                now = timezone.now()
                starting_head = _string(run, "recorded_head")
                existing_attempt = claim.attempt
                resuming = isinstance(existing_attempt, NodeAttempt)
                if resuming:
                    if (
                        not isinstance(existing_attempt, NodeAttempt)
                        or _string(existing_attempt, "status") != AttemptStatus.WAITING.value
                    ):
                        return ClaimResult(ClaimDisposition.IGNORED)
                    attempt = existing_attempt
                    attempt_number = _integer(attempt, "attempt_number")
                    starting_head = _string(attempt, "starting_head")
                    _set_model_field(attempt, "worker_id", worker_id)
                    _set_model_field(attempt, "status", AttemptStatus.RUNNING.value)
                    _set_model_field(attempt, "heartbeat_at", now)
                    attempt.save(update_fields=("worker_id", "status", "heartbeat_at"))
                else:
                    maximum = NodeAttempt.objects.filter(node_run=node).aggregate(
                        value=Max("attempt_number")
                    )["value"]
                    attempt_number = (maximum if isinstance(maximum, int) else 0) + 1
                    timeout = frozen.get("timeout")
                    seconds = duration_seconds(timeout) if isinstance(timeout, str) else None
                    deadline = now + timedelta(seconds=seconds) if seconds is not None else None
                    # Descendants inherit persisted deadlines, including after a yielded wait.
                    scopes = parse_scope_path(scope_path)
                    for depth in range(1, len(scopes)):
                        ancestor = "root." + ".".join(part.render() for part in scopes[:depth])
                        ancestor = (
                            ancestor.rsplit("#", maxsplit=1)[0]
                            if scopes[depth - 1].iteration is not None
                            else ancestor
                        )
                        ancestor_deadline = (
                            NodeAttempt.objects.filter(
                                node_run__run=run,
                                node_run__scope_path=ancestor,
                                status__in=(
                                    AttemptStatus.RUNNING.value,
                                    AttemptStatus.WAITING.value,
                                ),
                            )
                            .values_list("deadline_at", flat=True)
                            .first()
                        )
                        if isinstance(ancestor_deadline, datetime):
                            deadline = (
                                min(deadline, ancestor_deadline)
                                if deadline is not None
                                else ancestor_deadline
                            )
                    attempt = NodeAttempt.objects.create(
                        node_run=node,
                        attempt_number=attempt_number,
                        status=AttemptStatus.RUNNING.value,
                        worker_id=worker_id,
                        driver_kind=driver_kind,
                        agent_id=selected_agent,
                        model_value=model_value,
                        starting_head=starting_head,
                        started_at=now,
                        heartbeat_at=now,
                        deadline_at=deadline,
                    )
                if needs_lock:
                    RunLock.objects.create(
                        run=run,
                        attempt=attempt,
                        mode=decision.mode.value,
                        starting_head=starting_head,
                        recorded_head=starting_head,
                        heartbeat_at=now,
                    )
                _set_model_field(claim, "attempt", attempt)
                _set_model_field(claim, "state", DispatchState.CLAIMED.value)
                _set_model_field(claim, "claim_owner", worker_id)
                _set_model_field(claim, "claimed_at", now)
                claim.save(update_fields=("attempt", "state", "claim_owner", "claimed_at"))
                node_transition = transition_node(_string(node, "status"), "attempt_started")
                _set_model_field(node, "status", node_transition.status)
                node.save(update_fields=("status",))
                _append_event(
                    run,
                    node_transition.event,
                    EventSource.NODE,
                    {
                        "scope_path": scope_path,
                        "node_type": node_type,
                        "status": node_transition.status,
                    },
                    node=node,
                    attempt=attempt,
                )
                if not resuming:
                    _append_event(
                        run,
                        "attempt.started",
                        EventSource.ATTEMPT,
                        {
                            "scope_path": scope_path,
                            "attempt_number": attempt_number,
                            "driver_kind": driver_kind,
                            "agent_id": selected_agent,
                            "model_value": model_value,
                        },
                        node=node,
                        attempt=attempt,
                    )
                record = ClaimedAttempt(
                    claim_token=claim_token,
                    attempt_id=_identifier(attempt),
                    attempt_number=attempt_number,
                    worker_id=worker_id,
                    run_id=_identifier(run),
                    node_run_id=_identifier(node),
                    project_path=_string(project, "git_root"),
                    primary_worktree=_string(run, "worktree_path"),
                    scope_path=scope_path,
                    node_id=_string(node, "node_id"),
                    node_type=node_type,
                    frozen_def=frozen,
                    inputs=context.inputs,
                    upstream_outputs=context.upstream_outputs,
                    run_metadata=context.run_metadata,
                    prompt_contents=context.prompt_contents,
                    route=context.route,
                    subworkflows=context.subworkflows,
                    writes=writes,
                    starting_head=starting_head,
                    recorded_head=starting_head,
                    deadline_at=attempt.deadline_at
                    if isinstance(attempt.deadline_at, datetime)
                    else None,
                )
                return ClaimResult(ClaimDisposition.CLAIMED, record)
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not claim the dispatched node attempt."
            raise PersistenceError(message, context={"node": claim_token}) from None

    def mark_dispatch_consumed(self, claim_token: str) -> None:
        try:
            DispatchClaim.objects.filter(
                claim_token=claim_token,
                state=DispatchState.CLAIMED.value,
            ).update(state=DispatchState.CONSUMED.value, consumed_at=timezone.now())
        except DatabaseError:
            message = "Relay could not mark the dispatch claim consumed."
            raise PersistenceError(message) from None

    def heartbeat_attempt(self, attempt_id: str, worker_id: str) -> bool:
        now = timezone.now()
        try:
            updated = NodeAttempt.objects.filter(
                pk=attempt_id,
                worker_id=worker_id,
                status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
            ).update(heartbeat_at=now)
        except DatabaseError:
            message = "Relay could not update the attempt heartbeat."
            raise PersistenceError(message) from None
        else:
            if updated:
                RunLock.objects.filter(attempt_id=attempt_id).update(heartbeat_at=now)
            return updated == 1

    def owned_attempt_processes(self) -> tuple[tuple[str, ProcessIdentity], ...]:
        """Only identities recorded at spawn may authorize later escalation."""
        try:
            rows = NodeAttempt.objects.filter(
                status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
                process_pid__isnull=False,
                process_started__isnull=False,
            ).values_list("pk", "process_pid", "process_started")
            return tuple(
                (str(attempt_id), ProcessIdentity(pid, started))
                for attempt_id, pid, started in rows
                if isinstance(pid, int) and isinstance(started, str)
            )
        except DatabaseError:
            message = "Relay could not load verified attempt process identities."
            raise PersistenceError(message) from None

    def record_attempt_process(self, attempt_id: str, process_id: int | None) -> None:
        identity = process_identity(process_id) if process_id is not None else None
        try:
            NodeAttempt.objects.filter(
                pk=attempt_id,
                status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
            ).update(process_pid=process_id, process_started=identity.started if identity else None)
        except DatabaseError:
            message = "Relay could not record the attempt process."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def record_agent_session(
        self,
        attempt_id: str,
        *,
        process_id: int | None,
        session_id: str | None,
        agent_version: str,
        config_ids: Mapping[str, object],
    ) -> None:
        """Persist process/session correlation without changing attempt ownership."""
        identity = process_identity(process_id) if process_id is not None else None
        try:
            NodeAttempt.objects.filter(
                pk=attempt_id,
                status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
            ).update(
                process_pid=process_id,
                process_started=identity.started if identity else None,
                acp_session_id=session_id,
                agent_version=agent_version,
                config_ids=dict(config_ids),
            )
        except DatabaseError:
            message = "Relay could not record the agent session."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def request_agent_interaction(
        self,
        attempt_id: str,
        kind: str,
        prompt: str,
        options: tuple[Mapping[str, object], ...],
    ) -> str:
        """Pause one live attempt on a redacted ACP permission or elicitation."""
        if kind not in {InteractionKind.PERMISSION.value, InteractionKind.ELICITATION.value}:
            message = f"Unsupported agent interaction kind {kind!r}."
            raise PersistenceError(message, context={"node": attempt_id})
        try:
            with transaction.atomic():
                attempt = (
                    NodeAttempt.objects.select_for_update()
                    .select_related("node_run__run")
                    .get(pk=attempt_id)
                )
                if not self._attempt_is_current(attempt):
                    message = "The agent interaction no longer belongs to a live attempt."
                    raise PersistenceError(message, context={"node": attempt_id})  # noqa: TRY301
                node = _related(attempt, "node_run", NodeRun)
                run = _related(node, "run", Run)
                if HumanInteraction.objects.filter(
                    attempt=attempt, status=InteractionStatus.PENDING.value
                ).exists():
                    message = "The agent attempt already has a pending owner interaction."
                    raise PersistenceError(message, context={"node": attempt_id})  # noqa: TRY301
                request_payload = _bounded_interaction_request(prompt, options)
                interaction = HumanInteraction.objects.create(
                    run=run,
                    node_run=node,
                    attempt=attempt,
                    kind=kind,
                    request_payload=request_payload,
                    status=InteractionStatus.PENDING.value,
                )
                if _string(node, "status") == NodeStatus.RUNNING.value:
                    node_transition = transition_node(
                        _string(node, "status"), "interaction_requested"
                    )
                    _set_model_field(node, "status", node_transition.status)
                    node.save(update_fields=("status",))
                    _set_model_field(attempt, "status", AttemptStatus.WAITING.value)
                    attempt.save(update_fields=("status",))
                _append_event(
                    run,
                    f"{kind}.requested",
                    EventSource.AGENT,
                    {
                        "scope_path": _string(node, "scope_path"),
                        "attempt_number": _integer(attempt, "attempt_number"),
                        "interaction_id": _identifier(interaction),
                        "prompt": request_payload["prompt"],
                        **(
                            {"options": request_payload["options"]}
                            if request_payload["options"]
                            else {}
                        ),
                        **(
                            {"options_truncated": True}
                            if request_payload.get("options_truncated") is True
                            else {}
                        ),
                    },
                    node=node,
                    attempt=attempt,
                    sensitivity=EventSensitivity.REDACTED,
                )
                if _string(run, "status") == RunStatus.RUNNING.value:
                    run_transition = transition_run(_string(run, "status"), "node_waiting")
                    _set_model_field(run, "status", run_transition.status)
                    run.save(update_fields=("status",))
                    _append_event(
                        run,
                        run_transition.event,
                        EventSource.RUN,
                        {"status": run_transition.status},
                    )
                return _identifier(interaction)
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError, ObjectDoesNotExist):
            message = "Relay could not persist the agent interaction."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def ensure_scope_nodes(
        self,
        run_id: str,
        parent_scope: str,
        nodes: Mapping[str, Mapping[str, object]],
        inputs: Mapping[str, object],
        loop_index: int | None,
    ) -> None:
        """Materialize one bounded child scope once without changing frozen rows."""
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=run_id)
                for node_id, frozen in nodes.items():
                    node_type = frozen.get("type")
                    if not isinstance(node_type, str):
                        message = f"Scoped node {node_id!r} has no valid type."
                        _scope_persistence_error(message, run_id)
                    writes = frozen.get("writes", False)
                    if not isinstance(writes, bool):
                        message = f"Scoped node {node_id!r} has an invalid write flag."
                        _scope_persistence_error(message, run_id)
                    scope_path = node_scope(parent_scope, node_id)
                    node, created = NodeRun.objects.get_or_create(
                        run=run,
                        scope_path=scope_path,
                        defaults={
                            "parent_scope_path": parent_scope,
                            "node_id": node_id,
                            "node_type": node_type,
                            "frozen_def": dict(frozen),
                            "scope_inputs": dict(inputs),
                            "status": NodeStatus.PENDING.value,
                            "writes": writes,
                            "loop_index": loop_index,
                        },
                    )
                    if not created:
                        if _mapping(node, "frozen_def") != dict(frozen) or _mapping(
                            node, "scope_inputs"
                        ) != dict(inputs):
                            message = f"Scoped node {scope_path!r} conflicts with durable state."
                            _scope_persistence_error(message, run_id)
                        continue
                    transition = transition_node(None, "create")
                    _append_event(
                        run,
                        transition.event,
                        EventSource.NODE,
                        {
                            "scope_path": scope_path,
                            "node_type": node_type,
                            "status": transition.status,
                        },
                        node=node,
                    )
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError, ObjectDoesNotExist):
            message = "Relay could not materialize the nested workflow scope."
            raise PersistenceError(message, context={"run": run_id}) from None

    def scope_node_records(
        self,
        run_id: str,
        parent_scope: str,
        node_ids: tuple[str, ...],
    ) -> Mapping[str, ScopeNodeRecord]:
        try:
            paths = tuple(node_scope(parent_scope, node_id) for node_id in node_ids)
            rows = NodeRun.objects.filter(
                run_id=run_id,
                parent_scope_path=parent_scope,
                scope_path__in=paths,
            ).order_by("pk")
            return {
                _string(node, "node_id"): ScopeNodeRecord(
                    node_run_id=_identifier(node),
                    node_id=_string(node, "node_id"),
                    status=_string(node, "status"),
                    outputs=_mapping(node, "outputs"),
                    selected_branch=(
                        value if isinstance((value := node.selected_branch), str) else None
                    ),
                )
                for node in rows
            }
        except DatabaseError:
            message = "Relay could not load nested workflow state."
            raise PersistenceError(message, context={"run": run_id}) from None

    def scope_node_record(self, run_id: str, node_run_id: str) -> ScopeNodeRecord:
        """Load one child after execution without rescanning its whole scope."""
        try:
            node = NodeRun.objects.get(run_id=run_id, pk=node_run_id)
            return ScopeNodeRecord(
                node_run_id=_identifier(node),
                node_id=_string(node, "node_id"),
                status=_string(node, "status"),
                outputs=_mapping(node, "outputs"),
                selected_branch=(
                    value if isinstance((value := node.selected_branch), str) else None
                ),
            )
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not load nested workflow node state."
            raise PersistenceError(
                message,
                context={"run": run_id, "node": node_run_id},
            ) from None

    def transition_scope_node(
        self, node_run_id: str, action: str, *, expected_status: str | None = None
    ) -> str:
        try:
            with transaction.atomic():
                node = NodeRun.objects.select_for_update().select_related("run").get(pk=node_run_id)
                run = _related(node, "run", Run)
                current = _string(node, "status")
                if expected_status is not None and current != expected_status:
                    return current
                transition = transition_node(current, action)
                if not transition.changed:
                    return current
                _set_model_field(node, "status", transition.status)
                node.save(update_fields=("status",))
                _append_event(
                    run,
                    transition.event,
                    EventSource.NODE,
                    {
                        "scope_path": _string(node, "scope_path"),
                        "node_type": _string(node, "node_type"),
                        "status": transition.status,
                    },
                    node=node,
                )
                return transition.status
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not advance the nested workflow node."
            raise PersistenceError(message, context={"node": node_run_id}) from None

    def record_loop_iteration(
        self,
        coordinator_node_run_id: str,
        scope_path: str,
        iteration: int,
        kind: OutcomeKind,
        outputs: Mapping[str, Mapping[str, object]],
    ) -> None:
        """Record one structural loop-iteration row after its child scope settles."""
        try:
            with transaction.atomic():
                coordinator = (
                    NodeRun.objects.select_for_update()
                    .select_related("run")
                    .get(pk=coordinator_node_run_id)
                )
                run = _related(coordinator, "run", Run)
                status = {
                    OutcomeKind.SUCCEEDED: NodeStatus.SUCCEEDED.value,
                    OutcomeKind.FAILED: NodeStatus.FAILED.value,
                    OutcomeKind.WAITING: NodeStatus.WAITING.value,
                }[kind]
                marker, created = NodeRun.objects.get_or_create(
                    run=run,
                    scope_path=scope_path,
                    defaults={
                        "parent_scope_path": enclosing_scope(scope_path),
                        "node_id": _string(coordinator, "node_id"),
                        "node_type": NodeType.LOOP.value,
                        "frozen_def": _mapping(coordinator, "frozen_def"),
                        "scope_inputs": _mapping(coordinator, "scope_inputs"),
                        "outputs": {
                            node_id: dict(node_outputs) for node_id, node_outputs in outputs.items()
                        },
                        "status": status,
                        "writes": False,
                        "loop_index": iteration,
                    },
                )
                if created:
                    _append_event(
                        run,
                        f"node.{status}",
                        EventSource.NODE,
                        {
                            "scope_path": scope_path,
                            "node_type": NodeType.LOOP.value,
                            "status": status,
                        },
                        node=marker,
                    )
                    return
                current_status = _string(marker, "status")
                if current_status == status:
                    return
                if current_status in {
                    NodeStatus.RUNNING.value,
                    NodeStatus.FAILED.value,
                    NodeStatus.WAITING.value,
                }:
                    _set_model_field(marker, "status", status)
                    _set_model_field(
                        marker,
                        "outputs",
                        {node_id: dict(node_outputs) for node_id, node_outputs in outputs.items()},
                    )
                    marker.save(update_fields=("status", "outputs"))
                    _append_event(
                        run,
                        f"node.{status}",
                        EventSource.NODE,
                        {
                            "scope_path": scope_path,
                            "node_type": NodeType.LOOP.value,
                            "status": status,
                        },
                        node=marker,
                    )
                    return
                message = f"Loop iteration {scope_path!r} conflicts with durable state."
                _scope_persistence_error(message, _identifier(run))
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError, ObjectDoesNotExist):
            message = "Relay could not record the loop iteration."
            raise PersistenceError(message, context={"node": scope_path}) from None

    def mark_attempt_waiting(self, attempt_id: str, timeout_seconds: float | None) -> None:
        try:
            with transaction.atomic():
                attempt = (
                    NodeAttempt.objects.select_for_update()
                    .select_related("node_run__run")
                    .get(pk=attempt_id)
                )
                if _string(attempt, "status") == AttemptStatus.WAITING.value:
                    return
                node = _related(attempt, "node_run", NodeRun)
                run = _related(node, "run", Run)
                structural = _string(node, "node_type") in {
                    NodeType.LOOP.value,
                    NodeType.SUBWORKFLOW.value,
                }
                transition = transition_node(
                    _string(node, "status"),
                    "scope_waiting" if structural else "interaction_requested",
                )
                _set_model_field(attempt, "status", AttemptStatus.WAITING.value)
                attempt.save(update_fields=("status",))
                _set_model_field(node, "status", transition.status)
                node.save(update_fields=("status",))
                if structural:
                    _append_event(
                        run,
                        transition.event,
                        EventSource.NODE,
                        {
                            "scope_path": _string(node, "scope_path"),
                            "node_type": _string(node, "node_type"),
                            "status": transition.status,
                        },
                        node=node,
                        attempt=attempt,
                    )
                    # A child can settle just before its parent publishes waiting.
                    descendants = NodeRun.objects.filter(
                        run=run, scope_path__startswith=_string(node, "scope_path") + "."
                    )
                    if _string(node, "node_type") == NodeType.LOOP.value:
                        descendants = NodeRun.objects.filter(
                            run=run, scope_path__startswith=_string(node, "scope_path") + "#"
                        ).exclude(node_type=NodeType.LOOP.value, attempts__isnull=True)
                    if not descendants.filter(
                        status__in=(
                            NodeStatus.RUNNING.value,
                            NodeStatus.WAITING.value,
                            NodeStatus.DISPATCHED.value,
                        )
                    ).exists():
                        token = self.create_dispatch(_identifier(node))
                        if token is not None:
                            transaction.on_commit(lambda: notify_dispatch(token))
                    return
                prompt = _mapping(node, "frozen_def").get("prompt", "Owner input required.")
                interaction = HumanInteraction.objects.create(
                    run=run,
                    node_run=node,
                    attempt=attempt,
                    kind=InteractionKind.WAIT.value,
                    request_payload={"prompt": prompt if isinstance(prompt, str) else str(prompt)},
                    status=InteractionStatus.PENDING.value,
                    deadline=(
                        timezone.now() + timedelta(seconds=timeout_seconds)
                        if timeout_seconds is not None
                        else None
                    ),
                )
                _append_event(
                    run,
                    "wait.requested",
                    EventSource.SYSTEM,
                    {
                        "scope_path": _string(node, "scope_path"),
                        "attempt_number": _integer(attempt, "attempt_number"),
                        "interaction_id": _identifier(interaction),
                        "prompt": prompt,
                    },
                    node=node,
                    attempt=attempt,
                )
                run_transition = transition_run(_string(run, "status"), "node_waiting")
                if run_transition.changed:
                    _set_model_field(run, "status", run_transition.status)
                    run.save(update_fields=("status",))
                    _append_event(
                        run,
                        run_transition.event,
                        EventSource.RUN,
                        {"status": run_transition.status},
                    )
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not persist the human-wait state."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def record_preservation(self, attempt_id: str, preservation: PreservationResult) -> None:
        try:
            with transaction.atomic():
                attempt = (
                    NodeAttempt.objects.select_for_update()
                    .select_related("node_run__run")
                    .get(pk=attempt_id)
                )
                if Artifact.objects.filter(attempt=attempt).exists():
                    return
                rows = [
                    Artifact(
                        attempt=attempt,
                        declared_name=item.name,
                        source_path=item.source_path,
                        retained_path=item.retained_path,
                        sha256=item.sha256,
                        media_type=item.media_type,
                        bytes=item.bytes,
                        preservation_state=PreservationState.PRESERVED.value,
                    )
                    for item in preservation.files
                ]
                Artifact.objects.bulk_create(rows)
                node = _related(attempt, "node_run", NodeRun)
                run = _related(node, "run", Run)
                for item in preservation.files:
                    _append_event(
                        run,
                        "artifact.preserved",
                        EventSource.SYSTEM,
                        {
                            "scope_path": _string(node, "scope_path"),
                            "attempt_number": _integer(attempt, "attempt_number"),
                            "name": item.name,
                            "sha256": item.sha256,
                            "bytes": item.bytes,
                            "media_type": item.media_type,
                        },
                        node=node,
                        attempt=attempt,
                    )
        except DatabaseError:
            message = "Relay preserved attempt files but could not record their metadata."
            raise PersistenceError(
                message,
                context={"node": attempt_id},
                next_action="Keep the evidence directory and inspect the local Relay log.",
            ) from None

    def capture_recovery_reports(self, target: RecoveryTarget) -> None:
        """Retain older rejected root reports without replacing attempt evidence."""
        if target.attempt_id is None:
            return
        node = NodeRun.objects.get(pk=target.node_run_id)
        outputs = _mapping(node, "frozen_def").get("outputs", {})
        references = set()
        if isinstance(outputs, dict):
            for selector in outputs.values():
                if not isinstance(selector, dict):
                    continue
                for kind in ("label", "json_path", "yaml_path"):
                    value = selector.get(kind)
                    if isinstance(value, dict) and isinstance(value.get("artifact"), str):
                        reference = value["artifact"]
                        if reference in WORKFLOW_DOCUMENT_NAMES:
                            references.add(reference)
        files = preserve_recovery_reports(
            Path(target.worktree_path),
            target.run_id,
            target.attempt_id,
            tuple(sorted(references)),
        )
        with transaction.atomic():
            attempt = NodeAttempt.objects.select_for_update().get(pk=target.attempt_id)
            for item in files:
                artifact, created = Artifact.objects.get_or_create(
                    attempt=attempt,
                    retained_path=item.retained_path,
                    defaults={
                        "declared_name": item.name,
                        "source_path": item.source_path,
                        "sha256": item.sha256,
                        "media_type": item.media_type,
                        "bytes": item.bytes,
                        "preservation_state": PreservationState.PRESERVED.value,
                    },
                )
                if created:
                    run = Run.objects.get(pk=target.run_id)
                    _append_event(
                        run,
                        "artifact.preserved",
                        EventSource.SYSTEM,
                        {
                            "scope_path": target.scope_path,
                            "name": item.name,
                            "sha256": item.sha256,
                            "bytes": item.bytes,
                        },
                        node=node,
                        attempt=attempt,
                    )
                elif _string(artifact, "sha256") != item.sha256:
                    message = "Recovery report metadata disagrees with retained evidence."
                    raise PersistenceError(message)

    def recovery_reports(self, target: RecoveryTarget) -> tuple[RecoveryReport, ...]:
        """Restore successful handoffs plus this failed attempt's rejected report."""
        reports = {}
        rows = (
            Artifact.objects.select_related("attempt__node_run")
            .filter(
                attempt__node_run__run_id=target.run_id,
                preservation_state=PreservationState.PRESERVED.value,
            )
            .filter(
                Q(attempt__node_run__status=NodeStatus.SUCCEEDED.value)
                | Q(attempt_id=target.attempt_id)
            )
            .order_by("attempt__ended_at", "pk")
        )
        # Only exact root report exemptions can be rehydrated as untracked files.
        # Other files remain retained evidence and cannot hide dirty source code.
        for row in rows:
            filename = Path(_string(row, "source_path")).name
            attempt = _related(row, "attempt", NodeAttempt)
            node = _related(attempt, "node_run", NodeRun)
            run = _related(node, "run", Run)
            source = Path(_string(row, "source_path"))
            expected = (Path(_string(run, "worktree_path")) / filename).resolve()
            if filename not in WORKFLOW_DOCUMENT_NAMES or source != expected:
                continue
            reports[filename] = RecoveryReport(
                filename, _string(row, "retained_path"), _string(row, "sha256")
            )
        return tuple(reports.values())

    def _schedule_automatic_retry(
        self,
        run: Run,
        node: NodeRun,
        attempt: NodeAttempt,
        message: str,
        *,
        owner_request: bool = False,
    ) -> None:
        policy = _recovery_policy(run)
        existing = AutomaticRetry.objects.filter(attempt=attempt).first()
        if not policy.enabled:
            return
        if existing is not None and not (
            owner_request and _string(existing, "state") == "canceled"
        ):
            return
        stored_code = getattr(attempt, "error_code", None)
        error_code = (
            stored_code if isinstance(stored_code, str) else _string(attempt, "stop_reason")
        )
        if error_code == "agent_usage_limit":
            return
        used = AutomaticRetry.objects.filter(attempt__node_run=node, state="resumed").count()
        state = "scheduled"
        reason = ""
        if _string(node, "node_type") != NodeType.AGENT.value:
            state, reason = "blocked", "This failed step has no assigned recovery agent."
        elif _mapping(node, "frozen_def").get("auto_retry", True) is False:
            state, reason = "blocked", "Automatic recovery is disabled for this agent step."
        elif error_code not in RECOVERABLE_ERRORS or _string(attempt, "stop_reason") in {
            AttemptStopReason.CANCELED.value,
            AttemptStopReason.INTERRUPTED.value,
            AttemptStopReason.SOFT_DENIED.value,
        }:
            state, reason = "blocked", "This failure requires an owner decision or safe recovery."
        elif used >= policy.max_retries:
            state, reason = "exhausted", "The automatic retry budget for this step is exhausted."
        instruction, digest = recovery_instruction(_string(node, "scope_path"), error_code, message)
        retry, _created = AutomaticRetry.objects.update_or_create(
            attempt=attempt,
            defaults={
                "retry_number": min(used + 1, policy.max_retries),
                "state": state,
                "instruction": instruction,
                "instruction_sha256": digest,
                "error_message": reason,
            },
        )
        _append_event(
            run,
            f"run.recovery_{state}",
            EventSource.RUN,
            _recovery_record(retry),
            node=node,
            attempt=attempt,
        )

    def _finish_node_transition(
        self, node: NodeRun, outcome: ExecutionOutcome
    ) -> tuple[str, str, str]:
        if (
            outcome.kind is OutcomeKind.SUCCEEDED
            and outcome.stop_reason is AttemptStopReason.TIMEOUT
            and outcome.selected_branch is not None
        ):
            transition = transition_node(_string(node, "status"), "timeout_routed")
            reason = AttemptStopReason.TIMEOUT.value
        elif outcome.kind is OutcomeKind.SUCCEEDED:
            transition = transition_node(_string(node, "status"), "complete")
            reason = (outcome.stop_reason or AttemptStopReason.COMPLETED).value
        elif outcome.stop_reason == AttemptStopReason.CANCELED:
            transition = transition_node(_string(node, "status"), "cancel")
            reason = AttemptStopReason.CANCELED.value
        elif outcome.stop_reason == AttemptStopReason.INTERRUPTED:
            transition = transition_node(_string(node, "status"), "interrupt")
            reason = AttemptStopReason.INTERRUPTED.value
        else:
            transition = transition_node(_string(node, "status"), "fail")
            reason = (outcome.stop_reason or AttemptStopReason.FAILED).value
        return transition.status, transition.event, reason

    def _cancel_not_started(self, run: Run) -> None:
        nodes = NodeRun.objects.select_for_update().filter(
            run=run,
            status__in=(
                NodeStatus.PENDING.value,
                NodeStatus.READY.value,
                NodeStatus.DISPATCHED.value,
            ),
        )
        canceled_loops = {
            _string(node, "scope_path")
            for node in nodes
            if _string(node, "node_type") == NodeType.LOOP.value
        }
        for node in nodes:
            transition = transition_node(_string(node, "status"), "fail_fast")
            _set_model_field(node, "status", transition.status)
            node.save(update_fields=("status",))
            DispatchClaim.objects.filter(
                node_run=node, state=DispatchState.DISPATCHED.value
            ).update(state=DispatchState.CONSUMED.value, consumed_at=timezone.now())
            _append_event(
                run,
                transition.event,
                EventSource.NODE,
                {
                    "scope_path": _string(node, "scope_path"),
                    "node_type": _string(node, "node_type"),
                    "status": transition.status,
                },
                node=node,
            )
        if not canceled_loops:
            return
        summaries = NodeRun.objects.select_for_update().filter(
            run=run,
            node_type=NodeType.LOOP.value,
            status=NodeStatus.RUNNING.value,
            attempts__isnull=True,
        )
        for summary in summaries:
            # root.repeat#1 belongs to root.repeat; root.outer#1.inner#2
            # belongs to root.outer#1.inner, preserving the enclosing iteration.
            coordinator = sibling_scope(_string(summary, "scope_path"), _string(summary, "node_id"))
            if coordinator not in canceled_loops:
                continue
            # A summary has no attempt to drain if its loop never starts.
            # Active loops keep their summaries until the child scope settles.
            _set_model_field(summary, "status", NodeStatus.CANCELED.value)
            summary.save(update_fields=("status",))
            _append_event(
                run,
                "node.canceled",
                EventSource.NODE,
                {
                    "scope_path": _string(summary, "scope_path"),
                    "node_type": NodeType.LOOP.value,
                    "status": NodeStatus.CANCELED.value,
                },
                node=summary,
            )

    def _fan_out_fail_fast(self, run: Run, failed_attempt: NodeAttempt) -> None:
        expires = timezone.now() + timedelta(seconds=CONTROL_REQUEST_TTL_SECONDS)
        active_attempts = (
            NodeAttempt.objects.select_for_update()
            .filter(
                node_run__run=run,
                status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
            )
            .exclude(pk=failed_attempt.pk)
        )
        for attempt in active_attempts:
            key = (
                f"fail-fast:{_identifier(run)}:{_identifier(failed_attempt)}:{_identifier(attempt)}"
            )
            ControlRequest.objects.get_or_create(
                attempt=attempt,
                idempotency_key=key,
                defaults={
                    "kind": ControlKind.CANCEL.value,
                    "payload": {"reason": "fail_fast"},
                    "state": ControlState.PENDING.value,
                    "expires_at": expires,
                },
            )

    def _finish_run_if_terminal(self, run: Run) -> None:
        status = _string(run, "status")
        active = NodeRun.objects.filter(run=run).exclude(
            status__in=tuple(item.value for item in TERMINAL_NODE_STATUSES)
        )
        if active.exists():
            return
        if status == RunStatus.CANCELING.value:
            action = (
                "failure_drain_complete"
                if run.failure_code is not None
                else "cancel_drain_complete"
            )
        elif status == RunStatus.RUNNING.value:
            failed_node = (
                NodeRun.objects.filter(run=run, status=NodeStatus.FAILED.value)
                .order_by("scope_path", "pk")
                .first()
            )
            if failed_node is None:
                # Canceled nodes cannot satisfy the run's all-success guard.
                if (
                    NodeRun.objects.filter(run=run)
                    .exclude(status__in=(NodeStatus.SUCCEEDED.value, NodeStatus.SKIPPED.value))
                    .exists()
                ):
                    return
                action = "all_succeeded"
            else:
                latest_error = (
                    NodeAttempt.objects.filter(node_run=failed_node)
                    .exclude(error_code__isnull=True)
                    .order_by("-attempt_number")
                    .values_list("error_code", flat=True)
                    .first()
                )
                failure_code = (
                    latest_error
                    if isinstance(latest_error, str) and latest_error
                    else AttemptStopReason.FAILED.value
                )
                failing = transition_run(status, "node_failed")
                _set_model_field(run, "status", failing.status)
                _set_model_field(run, "failure_code", failure_code)
                run.save(update_fields=("status", "failure_code"))
                _append_event(
                    run,
                    failing.event,
                    EventSource.RUN,
                    {"status": failing.status, "failure_code": failure_code},
                )
                status = failing.status
                action = "failure_drain_complete"
        else:
            return
        if (
            action == "all_succeeded"
            and _string(run, "cleanup_policy") == CleanupPolicy.MERGE_ON_SUCCESS.value
        ):
            transition = transition_run(status, "completion_started")
            _set_model_field(run, "status", transition.status)
            run.save(update_fields=("status",))
            _append_event(
                run,
                transition.event,
                EventSource.RUN,
                {
                    "status": transition.status,
                    "branch": run.source_branch,
                },
            )
            run_id = _identifier(run)
            transaction.on_commit(lambda: self._complete_merged_run(run_id))
            return
        transition = transition_run(status, action)
        if not transition.changed:
            return
        _set_model_field(run, "status", transition.status)
        _set_model_field(run, "ended_at", timezone.now())
        run.save(update_fields=("status", "ended_at"))
        _append_event(
            run,
            transition.event,
            EventSource.RUN,
            {
                "status": transition.status,
                "failure_code": run.failure_code,
            },
        )
        if (
            transition.status == RunStatus.SUCCEEDED.value
            and _string(run, "cleanup_policy") == CleanupPolicy.CLEAN_ON_SUCCESS.value
        ):
            run_id = _identifier(run)
            transaction.on_commit(lambda: self._cleanup_successful_run(run_id))
        run_id = _identifier(run)
        transaction.on_commit(lambda: self._cleanup_terminal_resources(run_id))

    def finish_attempt(
        self,
        attempt_id: str,
        outcome: ExecutionOutcome,
        ending_head: str,
    ) -> None:
        try:
            with transaction.atomic():
                attempt = (
                    NodeAttempt.objects.select_for_update()
                    .select_related("node_run__run")
                    .get(pk=attempt_id)
                )
                if _string(attempt, "status") == AttemptStatus.TERMINAL.value:
                    return
                node = _related(attempt, "node_run", NodeRun)
                run = _related(node, "run", Run)
                # Shutdown interruptions must not reopen canceled work. Preserve
                # completed results, including a successful writer's protected head.
                if (
                    _string(run, "status") == RunStatus.CANCELING.value
                    and outcome.kind is OutcomeKind.FAILED
                    and outcome.stop_reason is AttemptStopReason.INTERRUPTED
                ):
                    outcome = ExecutionOutcome(
                        OutcomeKind.FAILED,
                        stop_reason=AttemptStopReason.CANCELED,
                        error_code=AttemptStopReason.CANCELED.value,
                    )
                node_status, node_event, stop_reason = self._finish_node_transition(node, outcome)
                # A 5,000-character diagnostic retains its first 4,096 characters
                # in both the run header and the terminal attempt event.
                failure_message = (
                    outcome.error_message[:RUN_PROBLEM_TEXT_MAX_CHARS]
                    if outcome.error_message is not None
                    else None
                )
                now = timezone.now()
                _set_model_field(attempt, "status", AttemptStatus.TERMINAL.value)
                _set_model_field(attempt, "ending_head", ending_head)
                _set_model_field(attempt, "ended_at", now)
                _set_model_field(attempt, "stop_reason", stop_reason)
                _set_model_field(attempt, "exit_code", outcome.exit_code)
                _set_model_field(attempt, "error_code", outcome.error_code)
                attempt.save(
                    update_fields=(
                        "status",
                        "ending_head",
                        "ended_at",
                        "stop_reason",
                        "exit_code",
                        "error_code",
                    )
                )
                # A terminal session cannot answer an interaction still tied
                # to it, so close that mailbox before publishing completion.
                self._discard_attempt_mailbox(attempt)
                _set_model_field(node, "status", node_status)
                _set_model_field(node, "selected_branch", outcome.selected_branch)
                _set_model_field(node, "outputs", dict(outcome.outputs))
                node.save(update_fields=("status", "selected_branch", "outputs"))
                if outcome.kind is OutcomeKind.SUCCEEDED and _boolean(node, "writes"):
                    _set_model_field(run, "recorded_head", ending_head)
                    run.save(update_fields=("recorded_head",))
                _append_event(
                    run,
                    "attempt.ended",
                    EventSource.ATTEMPT,
                    {
                        "scope_path": _string(node, "scope_path"),
                        "attempt_number": _integer(attempt, "attempt_number"),
                        "driver_kind": attempt.driver_kind,
                        "agent_id": _string(attempt, "agent_id"),
                        "model_value": _string(attempt, "model_value"),
                        "stop_reason": stop_reason,
                        "exit_code": outcome.exit_code,
                        "error_code": outcome.error_code,
                        "error_message": failure_message,
                    },
                    node=node,
                    attempt=attempt,
                )
                _append_event(
                    run,
                    node_event,
                    EventSource.NODE,
                    {
                        "scope_path": _string(node, "scope_path"),
                        "node_type": _string(node, "node_type"),
                        "status": node_status,
                        "stop_reason": stop_reason,
                    },
                    node=node,
                    attempt=attempt,
                )
                if outcome.kind is OutcomeKind.FAILED and stop_reason not in {
                    AttemptStopReason.CANCELED.value,
                    AttemptStopReason.INTERRUPTED.value,
                }:
                    run_status = _string(run, "status")
                    if run_status in {
                        RunStatus.RUNNING.value,
                        RunStatus.PAUSED_WAIT.value,
                    }:
                        run_transition = transition_run(run_status, "node_failed")
                        if run_transition.changed:
                            _set_model_field(run, "status", run_transition.status)
                            _set_model_field(run, "failure_code", outcome.error_code or stop_reason)
                            _set_model_field(run, "failure_summary", failure_message)
                            run.save(update_fields=("status", "failure_code", "failure_summary"))
                            if outcome.usage_limit is not None:
                                limit = outcome.usage_limit
                                _retry, _created = UsageRetry.objects.update_or_create(
                                    run=run,
                                    defaults={
                                        "attempt": attempt,
                                        "reset_at": limit.reset_at,
                                        "state": "scheduled"
                                        if limit.reset_at is not None
                                        else "blocked",
                                        "error_message": None,
                                    },
                                )
                                _append_event(
                                    run,
                                    "run.retry_scheduled"
                                    if limit.reset_at is not None
                                    else "run.retry_blocked",
                                    EventSource.RUN,
                                    {**limit.payload(), "scope_path": _string(node, "scope_path")},
                                    node=node,
                                    attempt=attempt,
                                )
                            else:
                                self._schedule_automatic_retry(
                                    run,
                                    node,
                                    attempt,
                                    failure_message or outcome.error_code or stop_reason,
                                )
                            _append_event(
                                run,
                                run_transition.event,
                                EventSource.RUN,
                                {
                                    "status": run_transition.status,
                                    "failure_code": outcome.error_code or stop_reason,
                                    "failure_summary": run.failure_summary,
                                },
                            )
                        self._cancel_not_started(run)
                        self._fan_out_fail_fast(run, attempt)
                elif stop_reason == AttemptStopReason.INTERRUPTED.value:
                    run_transition = transition_run(_string(run, "status"), "orderly_shutdown")
                    if run_transition.changed:
                        _set_model_field(run, "status", run_transition.status)
                        run.save(update_fields=("status",))
                        _append_event(
                            run,
                            run_transition.event,
                            EventSource.RUN,
                            {"status": run_transition.status},
                        )
                self._resume_run_after_waits(run)
                self._finish_run_if_terminal(run)
                self._wake_enclosing_scope(node, run)
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not finish the node attempt transaction."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def release_attempt_lock(self, attempt_id: str) -> None:
        try:
            run_id = (
                RunLock.objects.filter(attempt_id=attempt_id)
                .values_list("run_id", flat=True)
                .first()
            )
            RunLock.objects.filter(attempt_id=attempt_id).delete()
            if run_id is not None:
                transaction.on_commit(lambda: release_admission(str(run_id)))
        except DatabaseError:
            message = "Relay could not release the attempt's worktree lock."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def close_heartbeat_connections(self) -> None:
        """Close only connections owned by the current heartbeat thread."""
        from django.db import connections

        connections.close_all()

    def _wake_enclosing_scope(self, node: NodeRun, run: Run) -> None:
        if _string(run, "status") not in {RunStatus.RUNNING.value, RunStatus.PAUSED_WAIT.value}:
            return
        parent_scope = _string(node, "scope_path").rsplit(".", maxsplit=1)[0]
        if parent_scope == "root":
            return
        parent_scope = (
            parent_scope.rsplit("#", maxsplit=1)[0]
            if "#" in parent_scope.rsplit(".", maxsplit=1)[-1]
            else parent_scope
        )
        parent = NodeRun.objects.filter(
            run=run,
            scope_path=parent_scope,
            status=NodeStatus.WAITING.value,
            node_type__in=(NodeType.LOOP.value, NodeType.SUBWORKFLOW.value),
        ).first()
        if parent is not None:
            token = self.create_dispatch(_identifier(parent))
            if token is not None:
                transaction.on_commit(lambda: notify_dispatch(token))

    def _attempt_is_current(self, attempt: NodeAttempt) -> bool:
        node = _related(attempt, "node_run", NodeRun)
        latest = (
            NodeAttempt.objects.filter(node_run=node)
            .order_by("-attempt_number")
            .values_list("pk", flat=True)
            .first()
        )
        return str(latest) == _identifier(attempt) and _string(attempt, "status") in {
            AttemptStatus.RUNNING.value,
            AttemptStatus.WAITING.value,
        }

    def submit_control(
        self,
        attempt_id: str,
        kind: str,
        idempotency_key: str,
        payload: Mapping[str, object],
        ttl_seconds: float,
    ) -> ControlResult:
        if kind not in {item.value for item in ControlKind}:
            return ControlResult.INVALID
        try:
            with transaction.atomic():
                attempt = (
                    NodeAttempt.objects.select_for_update()
                    .select_related("node_run__run")
                    .filter(pk=attempt_id)
                    .first()
                )
                if attempt is None:
                    return ControlResult.INVALID
                existing = ControlRequest.objects.filter(
                    attempt=attempt, idempotency_key=idempotency_key
                ).first()
                if existing is not None:
                    return _control_replay_result(_string(existing, "state"))
                now = timezone.now()
                state = transition_control(None, "post").status
                if not self._attempt_is_current(attempt):
                    state = transition_control(state, "supersede").status
                expected_interaction = _CONTROL_INTERACTION_KINDS.get(kind)
                interaction = None
                if state == ControlState.PENDING.value and expected_interaction is not None:
                    interaction = (
                        HumanInteraction.objects.select_for_update()
                        .filter(
                            attempt=attempt,
                            kind=expected_interaction,
                            status=InteractionStatus.PENDING.value,
                        )
                        .order_by("-created_at")
                        .first()
                    )
                if (
                    state == ControlState.PENDING.value
                    and expected_interaction is not None
                    and (
                        interaction is None
                        or not _interaction_accepts_payload(kind, payload, interaction)
                    )
                ):
                    state = transition_control(None, "reject").status
                ControlRequest.objects.create(
                    attempt=attempt,
                    kind=kind,
                    idempotency_key=idempotency_key,
                    payload=dict(payload),
                    state=state,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
                return _control_public_result(state)
        except (DatabaseError, IntegrityError):
            message = "Relay could not persist the control request."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def claim_next_control(
        self,
        attempt_id: str,
        worker_id: str,
        kinds: tuple[str, ...] | None = None,
    ) -> ClaimedControl | None:
        try:
            with transaction.atomic():
                attempt = (
                    NodeAttempt.objects.select_for_update()
                    .select_related("node_run")
                    .filter(pk=attempt_id)
                    .first()
                )
                if attempt is None or not self._attempt_is_current(attempt):
                    ControlRequest.objects.filter(
                        attempt_id=attempt_id,
                        state__in=(ControlState.PENDING.value, ControlState.CLAIMED.value),
                    ).update(state=ControlState.STALE.value)
                    return None
                if _string(attempt, "worker_id") != worker_id:
                    return None
                now = timezone.now()
                ControlRequest.objects.filter(
                    attempt=attempt,
                    state=ControlState.PENDING.value,
                    expires_at__lte=now,
                ).update(state=ControlState.STALE.value)
                requests = ControlRequest.objects.select_for_update().filter(
                    attempt=attempt,
                    state=ControlState.PENDING.value,
                    expires_at__gt=now,
                )
                if kinds is not None:
                    requests = requests.filter(kind__in=kinds)
                request = requests.order_by("created_at", "pk").first()
                if request is None:
                    return None
                control_transition = transition_control(_string(request, "state"), "claim")
                _set_model_field(request, "state", control_transition.status)
                _set_model_field(request, "claim_owner", worker_id)
                _set_model_field(request, "claimed_at", now)
                _set_model_field(request, "claim_heartbeat_at", now)
                request.save(
                    update_fields=("state", "claim_owner", "claimed_at", "claim_heartbeat_at")
                )
                return ClaimedControl(
                    request_id=_identifier(request),
                    attempt_id=attempt_id,
                    kind=_string(request, "kind"),
                    payload=_mapping(request, "payload"),
                    idempotency_key=_string(request, "idempotency_key"),
                )
        except DatabaseError:
            message = "Relay could not claim the next control request."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def apply_control(self, request_id: str, worker_id: str) -> bool:
        try:
            with transaction.atomic():
                request = (
                    ControlRequest.objects.select_for_update()
                    .select_related("attempt__node_run__run")
                    .filter(pk=request_id)
                    .first()
                )
                if request is None:
                    return False
                attempt = _related(request, "attempt", NodeAttempt)
                node = _related(attempt, "node_run", NodeRun)
                run = _related(node, "run", Run)
                if _string(request, "state") != ControlState.CLAIMED.value:
                    return False
                if request.claim_owner != worker_id or _string(attempt, "worker_id") != worker_id:
                    return False
                if request.expires_at <= timezone.now() or not self._attempt_is_current(attempt):
                    control_transition = transition_control(_string(request, "state"), "supersede")
                    _set_model_field(request, "state", control_transition.status)
                    request.save(update_fields=("state",))
                    return False
                now = timezone.now()
                control_transition = transition_control(_string(request, "state"), "apply")
                _set_model_field(request, "state", control_transition.status)
                _set_model_field(request, "applied_at", now)
                request.save(update_fields=("state", "applied_at"))
                kind = _string(request, "kind")
                interaction_kind = _CONTROL_INTERACTION_KINDS.get(kind)
                if interaction_kind is not None:
                    interaction = (
                        HumanInteraction.objects.select_for_update()
                        .filter(
                            attempt=attempt,
                            kind=interaction_kind,
                            status=InteractionStatus.PENDING.value,
                        )
                        .order_by("-created_at")
                        .first()
                    )
                    if interaction is not None:
                        interaction_transition = transition_interaction(
                            _string(interaction, "status"), "answer"
                        )
                        _set_model_field(interaction, "status", interaction_transition.status)
                        _set_model_field(
                            interaction, "response_payload", _mapping(request, "payload")
                        )
                        _set_model_field(interaction, "answered_at", now)
                        interaction.save(
                            update_fields=("status", "response_payload", "answered_at")
                        )
                        if _string(node, "status") == NodeStatus.WAITING.value:
                            node_transition = transition_node(
                                _string(node, "status"), "interaction_answered"
                            )
                            _set_model_field(node, "status", node_transition.status)
                            node.save(update_fields=("status",))
                            _set_model_field(attempt, "status", AttemptStatus.RUNNING.value)
                            attempt.save(update_fields=("status",))
                        _append_event(
                            run,
                            f"{interaction_kind}.answered",
                            EventSource.SYSTEM,
                            {
                                "scope_path": _string(node, "scope_path"),
                                "attempt_number": _integer(attempt, "attempt_number"),
                                "interaction_id": _identifier(interaction),
                                "result": _mapping(request, "payload"),
                            },
                            node=node,
                            attempt=attempt,
                        )
                        self._resume_run_after_waits(run)
                return True
        except DatabaseError:
            message = "Relay could not acknowledge the control request."
            raise PersistenceError(message) from None

    def recover_control_claims(self) -> ControlRecovery:
        cutoff = timezone.now() - timedelta(seconds=CONTROL_CLAIM_STALE_AFTER_SECONDS)
        now = timezone.now()
        returned = 0
        stale = 0
        try:
            request_ids = list(
                ControlRequest.objects.filter(
                    state__in=(ControlState.PENDING.value, ControlState.CLAIMED.value)
                )
                .filter(
                    models.Q(expires_at__lte=now)
                    | models.Q(
                        state=ControlState.CLAIMED.value,
                        claim_heartbeat_at__lte=cutoff,
                    )
                )
                .order_by("created_at")
                .values_list("pk", flat=True)[:RECONCILE_MAX_ITEMS]
            )
            for request_id in request_ids:
                with transaction.atomic():
                    request = (
                        ControlRequest.objects.select_for_update()
                        .select_related("attempt__node_run")
                        .get(pk=request_id)
                    )
                    attempt = _related(request, "attempt", NodeAttempt)
                    expired = request.expires_at <= now
                    heartbeat_fresh = attempt.heartbeat_at > cutoff
                    if not expired and heartbeat_fresh and self._attempt_is_current(attempt):
                        # The owning session is alive; its lost mailbox lease is safe to replay.
                        control_transition = transition_control(
                            _string(request, "state"), "lease_recover"
                        )
                        _set_model_field(request, "state", control_transition.status)
                        _set_model_field(request, "claim_owner", None)
                        _set_model_field(request, "claimed_at", None)
                        _set_model_field(request, "claim_heartbeat_at", None)
                        request.save(
                            update_fields=(
                                "state",
                                "claim_owner",
                                "claimed_at",
                                "claim_heartbeat_at",
                            )
                        )
                        returned += 1
                    else:
                        control_transition = transition_control(
                            _string(request, "state"), "supersede"
                        )
                        _set_model_field(request, "state", control_transition.status)
                        request.save(update_fields=("state",))
                        stale += 1
        except DatabaseError:
            message = "Relay could not reconcile control-request leases."
            raise PersistenceError(message) from None
        return ControlRecovery(returned, stale)

    def resolve_human_wait_controls(self) -> int:
        """Apply bounded controls for wait nodes, which own no live subprocess."""
        try:
            attempt_ids = list(
                ControlRequest.objects.filter(
                    state=ControlState.PENDING.value,
                    kind__in=(ControlKind.WAIT_ANSWER.value, ControlKind.CANCEL.value),
                    attempt__status=AttemptStatus.WAITING.value,
                    attempt__node_run__node_type__in=(
                        NodeType.HUMAN_WAIT.value,
                        NodeType.LOOP.value,
                        NodeType.SUBWORKFLOW.value,
                    ),
                )
                .order_by("created_at")
                .values_list("attempt_id", flat=True)[:RECONCILE_MAX_ITEMS]
            )
            applied = 0
            for attempt_id in dict.fromkeys(attempt_ids):
                attempt = NodeAttempt.objects.get(pk=attempt_id)
                worker_id = _string(attempt, "worker_id")
                control = self.claim_next_control(str(attempt_id), worker_id)
                if control is None or not self.apply_control(control.request_id, worker_id):
                    continue
                outcome = (
                    ExecutionOutcome(
                        OutcomeKind.FAILED,
                        stop_reason=cancel_stop_reason(control),
                        error_code=cancel_stop_reason(control).value,
                    )
                    if control.kind == ControlKind.CANCEL.value
                    else ExecutionOutcome(OutcomeKind.SUCCEEDED)
                )
                if control.kind == ControlKind.CANCEL.value:
                    self._discard_attempt_mailbox(attempt)
                self.finish_attempt(str(attempt_id), outcome, _string(attempt, "starting_head"))
                self.release_attempt_lock(str(attempt_id))
                applied += 1
        except PersistenceError:
            raise
        except DatabaseError:
            message = "Relay could not resolve human-wait controls."
            raise PersistenceError(message) from None
        else:
            return applied

    def expire_human_waits(self) -> int:
        """Resolve each elapsed wait deadline once, taking its declared edge if present."""
        now = timezone.now()
        try:
            interaction_ids = list(
                HumanInteraction.objects.filter(
                    status=InteractionStatus.PENDING.value,
                    kind=InteractionKind.WAIT.value,
                    deadline__lte=now,
                    node_run__node_type=NodeType.HUMAN_WAIT.value,
                )
                .order_by("deadline")
                .values_list("pk", flat=True)[:RECONCILE_MAX_ITEMS]
            )
            expired = 0
            for interaction_id in interaction_ids:
                with transaction.atomic():
                    interaction = (
                        HumanInteraction.objects.select_for_update()
                        .select_related("attempt__node_run__run")
                        .get(pk=interaction_id)
                    )
                    if (
                        _string(interaction, "status") != InteractionStatus.PENDING.value
                        or interaction.deadline is None
                        or interaction.deadline > now
                    ):
                        continue
                    transition = transition_interaction(_string(interaction, "status"), "deadline")
                    _set_model_field(interaction, "status", transition.status)
                    interaction.save(update_fields=("status",))
                    attempt = _related(interaction, "attempt", NodeAttempt)
                    node = _related(attempt, "node_run", NodeRun)
                    run = _related(node, "run", Run)
                    on_timeout = _mapping(node, "frozen_def").get("on_timeout")
                    if isinstance(on_timeout, str):
                        outcome = ExecutionOutcome(
                            OutcomeKind.SUCCEEDED,
                            stop_reason=AttemptStopReason.TIMEOUT,
                            selected_branch=on_timeout,
                        )
                    else:
                        outcome = ExecutionOutcome(
                            OutcomeKind.FAILED,
                            stop_reason=AttemptStopReason.TIMEOUT,
                            error_code="node_timeout",
                        )
                    self.finish_attempt(
                        _identifier(attempt), outcome, _string(attempt, "starting_head")
                    )
                    if isinstance(on_timeout, str):
                        self._resume_run_after_waits(run)
                        self._finish_run_if_terminal(run)
                    self.release_attempt_lock(_identifier(attempt))
                    expired += 1
        except PersistenceError:
            raise
        except DatabaseError:
            message = "Relay could not expire human-wait deadlines."
            raise PersistenceError(message) from None
        else:
            return expired

    def _resume_run_after_waits(self, run: Run) -> None:
        """Resume only after all waits have settled without a failed node."""
        if _string(run, "status") != RunStatus.PAUSED_WAIT.value:
            return
        if NodeRun.objects.filter(
            run=run, status__in=(NodeStatus.WAITING.value, NodeStatus.FAILED.value)
        ).exists():
            return
        transition = transition_run(_string(run, "status"), "wait_answered")
        _set_model_field(run, "status", transition.status)
        run.save(update_fields=("status",))
        _append_event(run, transition.event, EventSource.RUN, {"status": transition.status})

    def expire_scope_waits(self) -> int:
        """Enforce enclosing deadlines even while a scope owns no worker."""
        try:
            with transaction.atomic():
                attempts = list(
                    NodeAttempt.objects.select_for_update()
                    .filter(
                        status=AttemptStatus.WAITING.value,
                        node_run__node_type__in=(NodeType.LOOP.value, NodeType.SUBWORKFLOW.value),
                        deadline_at__lte=timezone.now(),
                    )
                    .order_by("deadline_at")[:RECONCILE_MAX_ITEMS]
                )
                for attempt in attempts:
                    self.finish_attempt(
                        _identifier(attempt),
                        ExecutionOutcome(
                            OutcomeKind.FAILED,
                            stop_reason=AttemptStopReason.TIMEOUT,
                            error_code="node_timeout",
                        ),
                        _string(attempt, "starting_head"),
                    )
                return len(attempts)
        except DatabaseError:
            message = "Relay could not expire suspended scope deadlines."
            raise PersistenceError(message) from None

    def orphaned_dispatch_tokens(self) -> tuple[str, ...]:
        cutoff = timezone.now() - timedelta(seconds=DISPATCH_ORPHAN_AFTER_SECONDS)
        try:
            tokens = (
                DispatchClaim.objects.filter(
                    state=DispatchState.DISPATCHED.value,
                    attempt__isnull=True,
                    node_run__status=NodeStatus.DISPATCHED.value,
                    node_run__run__status__in=(
                        RunStatus.RUNNING.value,
                        RunStatus.PAUSED_WAIT.value,
                    ),
                    node_run__run__dispatch_paused=False,
                )
                .filter(
                    models.Q(enqueued_at__lte=cutoff)
                    | models.Q(enqueued_at__isnull=True, created_at__lte=cutoff)
                )
                .order_by("created_at")
                .values_list("claim_token", flat=True)[:RECONCILE_MAX_ITEMS]
            )
            return tuple(str(token) for token in tokens)
        except DatabaseError:
            message = "Relay could not scan durable dispatch claims."
            raise PersistenceError(message) from None

    def _discard_attempt_mailbox(self, attempt: NodeAttempt) -> None:
        interaction_transition = transition_interaction(
            InteractionStatus.PENDING.value, "attempt_lost"
        )
        HumanInteraction.objects.filter(
            attempt=attempt, status=InteractionStatus.PENDING.value
        ).update(status=interaction_transition.status)
        requests = ControlRequest.objects.select_for_update().filter(
            attempt=attempt,
            state__in=(ControlState.PENDING.value, ControlState.CLAIMED.value),
        )
        for request in requests:
            control_transition = transition_control(_string(request, "state"), "supersede")
            _set_model_field(request, "state", control_transition.status)
            request.save(update_fields=("state",))

    def _reap_stale_attempt(
        self,
        attempt_id: int,
        cutoff: datetime,
        *,
        orderly_shutdown: bool,
    ) -> AttemptStopReason | None:
        with transaction.atomic():
            attempt = (
                NodeAttempt.objects.select_for_update()
                .select_related("node_run")
                .filter(pk=attempt_id)
                .first()
            )
            if attempt is None or _string(attempt, "status") not in {
                AttemptStatus.RUNNING.value,
                AttemptStatus.WAITING.value,
            }:
                return None
            if attempt.heartbeat_at > cutoff:
                return None
            node = _related(attempt, "node_run", NodeRun)
            if (
                not orderly_shutdown
                and _string(node, "node_type")
                in {NodeType.HUMAN_WAIT.value, NodeType.LOOP.value, NodeType.SUBWORKFLOW.value}
                and _string(attempt, "status") == AttemptStatus.WAITING.value
            ):
                return None
            self._discard_attempt_mailbox(attempt)
            reason = (
                AttemptStopReason.INTERRUPTED if orderly_shutdown else AttemptStopReason.WORKER_LOST
            )
            outcome = ExecutionOutcome(
                OutcomeKind.FAILED,
                stop_reason=reason,
                error_code=reason.value,
            )
            self.finish_attempt(_identifier(attempt), outcome, _string(attempt, "starting_head"))
            self.release_attempt_lock(_identifier(attempt))
            return reason

    def reap_stale_attempts(self, *, orderly_shutdown: bool) -> AttemptRecovery:
        cutoff = timezone.now() - timedelta(seconds=ATTEMPT_STALE_AFTER_SECONDS)
        try:
            attempt_ids = list(
                NodeAttempt.objects.filter(
                    status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
                    heartbeat_at__lte=cutoff,
                )
                .order_by("heartbeat_at")
                .values_list("pk", flat=True)[:RECONCILE_MAX_ITEMS]
            )
            interrupted = 0
            lost = 0
            for attempt_id in attempt_ids:
                reason = self._reap_stale_attempt(
                    attempt_id, cutoff, orderly_shutdown=orderly_shutdown
                )
                if reason is AttemptStopReason.INTERRUPTED:
                    interrupted += 1
                elif reason is AttemptStopReason.WORKER_LOST:
                    lost += 1
            return AttemptRecovery(interrupted, lost)
        except PersistenceError:
            raise
        except DatabaseError:
            message = "Relay could not reconcile stale attempts."
            raise PersistenceError(message) from None

    def _attempt_for_claim(self, claim_token: str) -> NodeAttempt | None:
        claim = (
            DispatchClaim.objects.select_related("attempt").filter(claim_token=claim_token).first()
        )
        if claim is None:
            return None
        attempt = claim.attempt
        return attempt if isinstance(attempt, NodeAttempt) else None

    def mark_huey_interrupted(self, claim_token: str) -> None:
        attempt = self._attempt_for_claim(claim_token)
        if attempt is None:
            return
        outcome = ExecutionOutcome(
            OutcomeKind.FAILED,
            stop_reason=AttemptStopReason.INTERRUPTED,
            error_code="interrupted",
        )
        self._discard_attempt_mailbox(attempt)
        self.finish_attempt(_identifier(attempt), outcome, _string(attempt, "starting_head"))
        self.release_attempt_lock(_identifier(attempt))

    def mark_huey_error(self, claim_token: str) -> None:
        attempt = self._attempt_for_claim(claim_token)
        if attempt is None:
            return
        outcome = ExecutionOutcome(
            OutcomeKind.FAILED,
            stop_reason=AttemptStopReason.FAILED,
            error_code="dispatch_error",
        )
        self.finish_attempt(_identifier(attempt), outcome, _string(attempt, "starting_head"))
        self.release_attempt_lock(_identifier(attempt))

    def request_run_cancellation(self, run_id: str, idempotency_key: str) -> ControlResult:
        try:
            with transaction.atomic():
                run = _require_run(
                    Run.objects.select_for_update().filter(pk=run_id).first(), run_id
                )
                duplicate = RunEvent.objects.filter(
                    run=run,
                    type="run.canceling",
                    idempotency_key=idempotency_key,
                ).exists()
                if duplicate:
                    return ControlResult.ALREADY_APPLIED
                status = _string(run, "status")
                canceled_recovery = AutomaticRetry.objects.filter(
                    attempt__node_run__run=run, state__in=PENDING_RECOVERY_STATES
                ).update(state="canceled")
                if canceled_recovery:
                    _append_event(
                        run,
                        "run.recovery_canceled",
                        EventSource.RUN,
                        {"idempotency_key": idempotency_key},
                    )
                retry = (
                    UsageRetry.objects.select_for_update()
                    .filter(run=run, state="scheduled")
                    .first()
                )
                if retry is not None:
                    _set_model_field(retry, "state", "canceled")
                    retry.save(update_fields=("state",))
                    _append_event(
                        run,
                        "run.retry_canceled",
                        EventSource.RUN,
                        {"idempotency_key": idempotency_key},
                    )
                    if status == RunStatus.FAILED.value:
                        return ControlResult.ACCEPTED
                if canceled_recovery and status == RunStatus.FAILED.value:
                    return ControlResult.ACCEPTED
                if status in {
                    RunStatus.PENDING.value,
                    RunStatus.INTERRUPTED.value,
                    RunStatus.COMPLETING.value,
                }:
                    return ControlResult.STALE
                if status in {
                    RunStatus.SUCCEEDED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELED.value,
                }:
                    return ControlResult.ALREADY_APPLIED
                if status != RunStatus.CANCELING.value:
                    transition = transition_run(status, "owner_cancel")
                    if transition.changed:
                        _set_model_field(run, "status", transition.status)
                        run.save(update_fields=("status",))
                        _append_event(
                            run,
                            transition.event,
                            EventSource.RUN,
                            {
                                "status": transition.status,
                                "idempotency_key": idempotency_key,
                            },
                        )
                else:
                    return ControlResult.ALREADY_APPLIED
                self._cancel_not_started(run)
                expires = timezone.now() + timedelta(seconds=CONTROL_REQUEST_TTL_SECONDS)
                attempts = NodeAttempt.objects.filter(
                    node_run__run=run,
                    status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
                )
                for attempt in attempts:
                    _request, _created = ControlRequest.objects.get_or_create(
                        attempt=attempt,
                        idempotency_key=_derived_control_key(
                            "cancel",
                            idempotency_key,
                            _identifier(attempt),
                        ),
                        defaults={
                            "kind": ControlKind.CANCEL.value,
                            "payload": {"reason": "owner_cancel"},
                            "state": ControlState.PENDING.value,
                            "expires_at": expires,
                        },
                    )
                self._finish_run_if_terminal(run)
                return ControlResult.ACCEPTED
        except (PersistenceError, ProjectDiscoveryError):
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not persist run cancellation."
            raise PersistenceError(message, context={"run": run_id}) from None

    @staticmethod
    def _recovery_target(
        run: Run,
        node: NodeRun,
        attempt: NodeAttempt | None,
        *,
        interrupted: bool,
    ) -> RecoveryTarget:
        project = _related(run, "project", Project)
        primary = Path(_string(run, "worktree_path"))
        uses_git = _string(node, "node_type") in {
            NodeType.AGENT.value,
            NodeType.COMMAND.value,
        }
        ephemeral_reader = bool(attempt is not None and not _boolean(node, "writes") and uses_git)
        worktree = (
            reader_worktree_path(primary, _identifier(attempt))
            if ephemeral_reader and attempt is not None
            else primary
        )
        route = _effective_route(node, _related(run, "snapshot", RunSnapshot))
        agent_id, model_value = route.get("selected_agent"), route.get("model_value")
        return RecoveryTarget(
            run_id=_identifier(run),
            node_run_id=_identifier(node),
            scope_path=_string(node, "scope_path"),
            attempt_id=_identifier(attempt) if attempt is not None else None,
            project_path=_string(project, "git_root"),
            worktree_path=str(worktree),
            starting_head=(
                _string(attempt, "starting_head")
                if attempt is not None
                else _string(run, "recorded_head")
            ),
            protected_head=_string(run, "recorded_head"),
            uses_git=uses_git,
            ephemeral_reader=ephemeral_reader,
            interrupted=interrupted,
            agent_id=agent_id if isinstance(agent_id, str) else None,
            model_value=model_value if isinstance(model_value, str) else None,
        )

    def manual_rerun_target(
        self,
        run_id: str,
        scope_path: str,
        idempotency_key: str,
    ) -> RecoveryTarget | None:
        try:
            run = Run.objects.select_related("project").get(pk=run_id)
            duplicate = RunEvent.objects.filter(
                run=run,
                type="run.rerun",
                idempotency_key=idempotency_key,
            ).exists()
            if duplicate:
                return None
            if _string(run, "status") != RunStatus.FAILED.value:
                _invalid_rerun_target(run_id)
            selected = NodeRun.objects.get(run=run, scope_path=scope_path)
            if _string(selected, "status") != NodeStatus.FAILED.value:
                _invalid_rerun_target(run_id, scope_path)
            candidates = [
                node
                for node in NodeRun.objects.filter(
                    run=run,
                    status=NodeStatus.FAILED.value,
                    attempts__isnull=False,
                ).distinct()
                if scope_is_ancestor(_string(node, "scope_path"), scope_path)
                or scope_is_ancestor(scope_path, _string(node, "scope_path"))
            ]
            if not candidates:
                _invalid_rerun_target(run_id, scope_path)
            # Structural parents fail after their child. Recover the deepest
            # related attempt so partial Git state is preserved/reset before
            # reopening the chain. Scope text breaks equal-depth ties deterministically.
            node = max(
                candidates,
                key=lambda item: (
                    len(parse_scope_path(_string(item, "scope_path"))),
                    _string(item, "scope_path"),
                ),
            )
            attempt = NodeAttempt.objects.filter(node_run=node).order_by("-attempt_number").first()
            return self._recovery_target(run, node, attempt, interrupted=False)
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not find the requested failed-node rerun target."
            raise PersistenceError(message, context={"run": run_id, "node": scope_path}) from None

    def configure_repair_groups(
        self, run_id: str, groups: Mapping[str, str], idempotency_key: str
    ) -> ControlResult:
        """Fold explicitly selected legacy loops into a paused run's repair panel."""
        from relay.execution.control import valid_idempotency_key

        if not valid_idempotency_key(idempotency_key):
            return ControlResult.INVALID
        try:
            with transaction.atomic():
                run = _require_run(
                    Run.objects.select_for_update().filter(pk=run_id).first(), run_id
                )
                if RunEvent.objects.filter(
                    run=run, type="run.repairs_changed", idempotency_key=idempotency_key
                ).exists():
                    return ControlResult.ALREADY_APPLIED
                if not _boolean(run, "dispatch_paused"):
                    return ControlResult.STALE
                if len(set(groups.values())) != len(groups):
                    return ControlResult.INVALID
                paths = set(groups) | set(groups.values())
                nodes = {
                    _string(node, "scope_path"): node
                    for node in NodeRun.objects.filter(run=run, scope_path__in=paths)
                }
                if set(nodes) != paths:
                    return ControlResult.INVALID
                for coordinator, source in groups.items():
                    loop = nodes[coordinator]
                    if (
                        _string(loop, "node_type") != NodeType.LOOP.value
                        or parse_scope_path(coordinator)[-1].iteration is not None
                        or coordinator == source
                        or scope_is_ancestor(coordinator, source)
                        or source in groups
                        or nodes[source].parent_scope_path != loop.parent_scope_path
                        or _mapping(loop, "frozen_def").get("repair_rule") is not None
                    ):
                        return ControlResult.INVALID
                _set_model_field(run, "repair_groups", dict(groups))
                run.save(update_fields=("repair_groups",))
                _append_event(
                    run,
                    "run.repairs_changed",
                    EventSource.RUN,
                    {"groups": dict(groups), "idempotency_key": idempotency_key},
                )
                return ControlResult.ACCEPTED
        except DatabaseError:
            message = "Relay could not save the repair presentation."
            raise PersistenceError(message, context={"run": run_id}) from None

    def configure_dispatch_pause(
        self, run_id: str, paused: bool, idempotency_key: str
    ) -> ControlResult:
        """Gate future claims while preserving every current attempt and session."""
        from relay.execution.control import valid_idempotency_key

        if not valid_idempotency_key(idempotency_key):
            return ControlResult.INVALID
        try:
            with transaction.atomic():
                run = _require_run(
                    Run.objects.select_for_update().filter(pk=run_id).first(), run_id
                )
                if RunEvent.objects.filter(
                    run=run, type="run.dispatch_changed", idempotency_key=idempotency_key
                ).exists():
                    return ControlResult.ALREADY_APPLIED
                if _string(run, "status") in {
                    RunStatus.SUCCEEDED.value,
                    RunStatus.CANCELED.value,
                    RunStatus.CANCELING.value,
                }:
                    return ControlResult.STALE
                _set_model_field(run, "dispatch_paused", paused)
                run.save(update_fields=("dispatch_paused",))
                _append_event(
                    run,
                    "run.dispatch_changed",
                    EventSource.RUN,
                    {"paused": paused, "idempotency_key": idempotency_key},
                )
                return ControlResult.ACCEPTED
        except DatabaseError:
            message = "Relay could not save the run's pause setting."
            raise PersistenceError(message, context={"run": run_id}) from None

    def pending_dispatch_tokens(self, run_id: str) -> tuple[str, ...]:
        """Wake existing delivery intent immediately after an explicit resume."""
        try:
            return tuple(
                DispatchClaim.objects.filter(
                    node_run__run_id=run_id,
                    state=DispatchState.DISPATCHED.value,
                    node_run__run__dispatch_paused=False,
                )
                .order_by("created_at")
                .values_list("claim_token", flat=True)[:RECONCILE_MAX_ITEMS]
            )
        except DatabaseError:
            message = "Relay could not read the run's paused dispatch tokens."
            raise PersistenceError(message, context={"run": run_id}) from None

    def unstarted_agent_target(
        self, run_id: str, scope_path: str, idempotency_key: str
    ) -> UnstartedAgentTarget | None:
        """Capture choices for a fresh probe, without holding a lock during I/O."""
        try:
            run = _require_run(
                Run.objects.select_related("project", "snapshot").filter(pk=run_id).first(),
                run_id,
            )
            if RunEvent.objects.filter(
                run=run, type="node.settings_changed", idempotency_key=idempotency_key
            ).exists():
                return None
            node = NodeRun.objects.filter(run=run, scope_path=scope_path).first()
            if (
                node is None
                or not _boolean(run, "dispatch_paused")
                or _string(run, "status")
                in {RunStatus.SUCCEEDED.value, RunStatus.CANCELED.value, RunStatus.CANCELING.value}
                or _string(node, "node_type") != NodeType.AGENT.value
                or _string(node, "status")
                not in {
                    NodeStatus.PENDING.value,
                    NodeStatus.READY.value,
                    NodeStatus.DISPATCHED.value,
                }
                or NodeAttempt.objects.filter(node_run=node).exists()
            ):
                message = "Pause new steps before changing an agent step that has never started."
                raise PermissionFlowError(message, context={"run": run_id, "node": scope_path})
            return UnstartedAgentTarget(
                run_id,
                _identifier(node),
                scope_path,
                _string(_related(run, "project", Project), "git_root"),
                _effective_route(node, _related(run, "snapshot", RunSnapshot)),
                _mapping(node, "retry_options"),
            )
        except DatabaseError:
            message = "Relay could not read the unstarted agent step's settings."
            raise PersistenceError(message, context={"run": run_id, "node": scope_path}) from None

    def save_unstarted_agent_settings(
        self,
        target: UnstartedAgentTarget,
        options: Mapping[str, object],
        idempotency_key: str,
    ) -> ControlResult:
        """Recheck pause, admission, and prior choices after the provider probe."""
        try:
            with transaction.atomic():
                run = _require_run(
                    Run.objects.select_for_update().filter(pk=target.run_id).first(), target.run_id
                )
                if RunEvent.objects.filter(
                    run=run, type="node.settings_changed", idempotency_key=idempotency_key
                ).exists():
                    return ControlResult.ALREADY_APPLIED
                node = (
                    NodeRun.objects.select_for_update()
                    .filter(pk=target.node_run_id, run=run)
                    .first()
                )
                if (
                    node is None
                    or not _boolean(run, "dispatch_paused")
                    or _string(run, "status")
                    in {
                        RunStatus.SUCCEEDED.value,
                        RunStatus.CANCELED.value,
                        RunStatus.CANCELING.value,
                    }
                    or _string(node, "status")
                    not in {
                        NodeStatus.PENDING.value,
                        NodeStatus.READY.value,
                        NodeStatus.DISPATCHED.value,
                    }
                    or _mapping(node, "retry_options") != target.options
                    or NodeAttempt.objects.filter(node_run=node).exists()
                ):
                    return ControlResult.STALE
                _set_model_field(node, "retry_options", dict(options))
                node.save(update_fields=("retry_options",))
                _append_event(
                    run,
                    "node.settings_changed",
                    EventSource.NODE,
                    {
                        "scope_path": target.scope_path,
                        "options": dict(options),
                        "idempotency_key": idempotency_key,
                    },
                    node=node,
                )
                return ControlResult.ACCEPTED
        except DatabaseError:
            message = "Relay could not save the unstarted agent step's settings."
            raise PersistenceError(message, context={"run": target.run_id}) from None

    def configure_recovery(self, run_id: str, enabled: bool, idempotency_key: str) -> ControlResult:
        """Record an owner policy override without modifying the launch snapshot."""
        from relay.execution.control import valid_idempotency_key

        if not valid_idempotency_key(idempotency_key):
            return ControlResult.INVALID
        try:
            with transaction.atomic():
                run = _require_run(
                    Run.objects.select_for_update().filter(pk=run_id).first(), run_id
                )
                if RunEvent.objects.filter(
                    run=run, type="run.recovery_changed", idempotency_key=idempotency_key
                ).exists():
                    return ControlResult.ALREADY_APPLIED
                if _string(run, "status") in {RunStatus.SUCCEEDED.value, RunStatus.CANCELED.value}:
                    return ControlResult.STALE
                policy = _recovery_policy(run).model_copy(update={"enabled": enabled})
                _set_model_field(run, "recovery_policy", policy.model_dump(mode="json"))
                run.save(update_fields=("recovery_policy",))
                _append_event(
                    run,
                    "run.recovery_changed",
                    EventSource.RUN,
                    {**policy.model_dump(mode="json"), "idempotency_key": idempotency_key},
                )
                if not enabled:
                    changed = AutomaticRetry.objects.filter(
                        attempt__node_run__run=run, state__in=PENDING_RECOVERY_STATES
                    ).update(state="canceled")
                    if changed:
                        _append_event(run, "run.recovery_canceled", EventSource.RUN, {})
                elif _string(run, "status") == RunStatus.FAILED.value:
                    problem = _run_problem(run)
                    if problem is not None:
                        node = NodeRun.objects.get(run=run, scope_path=problem["scope_path"])
                        attempt = (
                            NodeAttempt.objects.filter(node_run=node)
                            .order_by("-attempt_number")
                            .first()
                        )
                        if attempt is not None:
                            message = problem.get("message")
                            self._schedule_automatic_retry(
                                run,
                                node,
                                attempt,
                                message if isinstance(message, str) else "The agent step failed.",
                                owner_request=True,
                            )
                return ControlResult.ACCEPTED
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not save the run's automatic recovery policy."
            raise PersistenceError(message, context={"run": run_id}) from None

    def automatic_rerun_target(
        self, run_id: str, scope_path: str, idempotency_key: str
    ) -> RecoveryTarget | None:
        """Authorize workspace preparation under the shared recovery lock."""
        with transaction.atomic():
            run = Run.objects.select_for_update().get(pk=run_id)
            if (
                _boolean(run, "dispatch_paused")
                or not _recovery_policy(run).enabled
                or _string(run, "status") != RunStatus.FAILED.value
            ):
                return None
            if RunLock.objects.filter(run=run).exists():
                return None
            target = self.manual_rerun_target(run_id, scope_path, idempotency_key)
            if target is None:
                return None
            retry = (
                AutomaticRetry.objects.select_for_update()
                .filter(attempt_id=target.attempt_id, state__in=PENDING_RECOVERY_STATES)
                .first()
            )
            if retry is None:
                return None
            unrelated = any(
                not scope_is_ancestor(other, target.scope_path)
                for other in NodeRun.objects.filter(
                    run=run, status=NodeStatus.FAILED.value
                ).values_list("scope_path", flat=True)
            )
            if unrelated:
                message = "Another failed step must be resolved before automatic recovery."
                raise PersistenceError(message)
            if _string(retry, "state") != "preparing":
                _set_model_field(retry, "state", "preparing")
                retry.save(update_fields=("state",))
                _append_event(
                    run, "run.recovery_preparing", EventSource.RUN, _recovery_record(retry)
                )
            return target

    def resume_automatic_retries(self) -> int:
        """Recover settled failures once; crashes retain the same retry budget."""
        from relay.execution.recovery import prepare_recovery_workspace
        from relay.execution.resume import rerun_failed_node

        if Instance.objects.filter(shutdown_requested=True).exists():
            return 0
        resumed = 0
        retries = list(
            AutomaticRetry.objects.select_related("attempt__node_run")
            .filter(
                state__in=PENDING_RECOVERY_STATES,
                attempt__node_run__run__status=RunStatus.FAILED.value,
                attempt__node_run__run__dispatch_paused=False,
            )
            .order_by("created_at", "pk")[:RECONCILE_MAX_ITEMS]
        )
        for retry in retries:
            attempt = _related(retry, "attempt", NodeAttempt)
            node = _related(attempt, "node_run", NodeRun)
            run_id = _foreign_key_text(node, "run")
            try:
                result = rerun_failed_node(
                    self,
                    run_id,
                    _string(node, "scope_path"),
                    f"automatic:{_identifier(attempt)}",
                    lambda target: prepare_recovery_workspace(self, target),
                    automatic_retry=True,
                )
                resumed += int(result is ControlResult.ACCEPTED)
            except Exception as error:
                LOGGER.exception("Automatic step recovery failed", extra={"run_id": run_id})
                message = (
                    error.message
                    if isinstance(error, RelayError)
                    else "Relay could not safely prepare this retry."
                )
                with transaction.atomic():
                    changed = AutomaticRetry.objects.filter(
                        pk=retry.pk, state__in=PENDING_RECOVERY_STATES
                    ).update(state="blocked", error_message=message[:RUN_PROBLEM_TEXT_MAX_CHARS])
                    if changed:
                        run = Run.objects.get(pk=run_id)
                        _append_event(
                            run,
                            "run.recovery_blocked",
                            EventSource.RUN,
                            {
                                "scope_path": _string(node, "scope_path"),
                                "message": message[:RUN_PROBLEM_TEXT_MAX_CHARS],
                            },
                        )
        return resumed

    def activate_automatic_recovery(self, target: RecoveryTarget, idempotency_key: str) -> bool:
        """Recheck owner cancellation and the exact failed attempt before reopening."""
        with transaction.atomic():
            run = Run.objects.select_for_update().get(pk=target.run_id)
            retry = (
                AutomaticRetry.objects.select_for_update()
                .filter(attempt_id=target.attempt_id, state="preparing")
                .first()
            )
            latest = (
                NodeAttempt.objects.filter(node_run_id=target.node_run_id)
                .order_by("-attempt_number")
                .first()
            )
            if (
                retry is None
                or latest is None
                or _identifier(latest) != target.attempt_id
                or _boolean(run, "dispatch_paused")
                or not _recovery_policy(run).enabled
                or _string(run, "status") != RunStatus.FAILED.value
                or Instance.objects.filter(shutdown_requested=True).exists()
            ):
                return False
            activated = self.activate_recovery(
                target, idempotency_key, recovery_note=_string(retry, "instruction")
            )
            if activated:
                _set_model_field(retry, "state", "resumed")
                retry.save(update_fields=("state",))
                _append_event(run, "run.recovery_resumed", EventSource.RUN, _recovery_record(retry))
            return activated

    def resume_usage_retries(self) -> int:
        """Recover due provider limits once through the existing failed-node path."""
        from relay.execution.recovery import prepare_recovery_workspace
        from relay.execution.resume import rerun_failed_node

        if Instance.objects.filter(shutdown_requested=True).exists():
            return 0
        resumed = 0
        due = list(
            UsageRetry.objects.select_related("attempt__node_run")
            .filter(
                state="scheduled",
                reset_at__lte=timezone.now(),
                run__status=RunStatus.FAILED.value,
                run__dispatch_paused=False,
            )
            .order_by("reset_at", "pk")[:RECONCILE_MAX_ITEMS]
        )
        for retry in due:
            run_id = str(retry.run_id)
            attempt = _related(retry, "attempt", NodeAttempt)
            node = _related(attempt, "node_run", NodeRun)
            scope = _string(node, "scope_path")
            try:
                unrelated_failure = any(
                    not scope_is_ancestor(other, scope)
                    for other in NodeRun.objects.filter(
                        run_id=run_id, status=NodeStatus.FAILED.value
                    ).values_list("scope_path", flat=True)
                )
                if unrelated_failure:
                    message = "Another failed step must be resolved before automatic recovery."
                    raise PersistenceError(message)  # noqa: TRY301
                result = rerun_failed_node(
                    self,
                    run_id,
                    scope,
                    f"quota:{_identifier(attempt)}",
                    lambda target: prepare_recovery_workspace(self, target),
                    usage_reset=True,
                )
                if result is ControlResult.ACCEPTED:
                    resumed += 1
            except Exception as error:
                LOGGER.exception("Scheduled provider recovery failed", extra={"run_id": run_id})
                message = (
                    error.message
                    if isinstance(error, RelayError)
                    else "Relay could not prepare the failed step for its scheduled retry."
                )
                with transaction.atomic():
                    updated = UsageRetry.objects.filter(pk=retry.pk, state="scheduled").update(
                        state="blocked", error_message=message[:RUN_PROBLEM_TEXT_MAX_CHARS]
                    )
                    if updated:
                        run = Run.objects.get(pk=run_id)
                        _append_event(
                            run,
                            "run.retry_blocked",
                            EventSource.RUN,
                            {"scope_path": scope, "message": message[:RUN_PROBLEM_TEXT_MAX_CHARS]},
                            node=node,
                            attempt=attempt,
                        )
        return resumed

    def interrupted_targets(self) -> tuple[RecoveryTarget, ...]:
        try:
            targets = []
            run_ids = self.interrupted_run_ids()
            nodes = (
                NodeRun.objects.select_related("run__project")
                .filter(
                    run_id__in=run_ids,
                    status=NodeStatus.PENDING.value,
                    attempts__stop_reason=AttemptStopReason.INTERRUPTED.value,
                )
                .distinct()
            )
            for node in nodes:
                run = _related(node, "run", Run)
                attempt = (
                    NodeAttempt.objects.filter(
                        node_run=node, stop_reason=AttemptStopReason.INTERRUPTED.value
                    )
                    .order_by("-attempt_number")
                    .first()
                )
                targets.append(self._recovery_target(run, node, attempt, interrupted=True))
            return tuple(targets)
        except DatabaseError:
            message = "Relay could not load interrupted run targets."
            raise PersistenceError(message) from None

    def interrupted_run_ids(self) -> tuple[str, ...]:
        try:
            values = list(
                Run.objects.filter(status=RunStatus.INTERRUPTED.value)
                .order_by("started_at", "pk")
                .values_list("pk", flat=True)[: RECONCILE_MAX_ITEMS + 1]
            )
            if len(values) > RECONCILE_MAX_ITEMS:
                _too_many_interrupted_runs()
            return tuple(str(value) for value in values)
        except PersistenceError:
            raise
        except DatabaseError:
            message = "Relay could not enumerate interrupted runs."
            raise PersistenceError(message) from None

    def activate_usage_recovery(self, target: RecoveryTarget, idempotency_key: str) -> bool:
        """Recheck reset authorization after workspace preparation and owner actions."""
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=target.run_id)
                retry = (
                    UsageRetry.objects.select_for_update()
                    .filter(
                        run=run,
                        attempt_id=target.attempt_id,
                        state="scheduled",
                        reset_at__lte=timezone.now(),
                    )
                    .first()
                )
                if (
                    retry is None
                    or _boolean(run, "dispatch_paused")
                    or _string(run, "status") != RunStatus.FAILED.value
                ):
                    return False
                return self.activate_recovery(target, idempotency_key, preserve_recovery_note=True)
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not authorize the scheduled usage retry."
            raise PersistenceError(message, context={"run": target.run_id}) from None

    def activate_recovery(
        self,
        target: RecoveryTarget,
        idempotency_key: str,
        *,
        effort: RetryEffort | None = None,
        agent: RetryAgent | None = None,
        permission_mode: RetryPermissionMode | None = None,
        recovery_note: str | None = None,
        preserve_recovery_note: bool = False,
    ) -> bool:
        if target.interrupted:
            return self.activate_interrupted_run(target.run_id, idempotency_key)
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=target.run_id)
                node = NodeRun.objects.select_for_update().get(pk=target.node_run_id, run=run)
                duplicate = RunEvent.objects.filter(
                    run=run,
                    type__in=("run.rerun", "run.resumed"),
                    idempotency_key=idempotency_key,
                ).exists()
                if duplicate:
                    return False
                pending = AutomaticRetry.objects.filter(
                    attempt__node_run__run=run, state__in=PENDING_RECOVERY_STATES
                )
                if recovery_note is not None:
                    pending = pending.exclude(attempt_id=target.attempt_id)
                if pending.update(state="canceled"):
                    _append_event(run, "run.recovery_canceled", EventSource.RUN, {})
                if not preserve_recovery_note:
                    _set_model_field(node, "recovery_instruction", recovery_note or "")
                    node.save(update_fields=("recovery_instruction",))
                if agent is not None or effort is not None or permission_mode is not None:
                    if _string(node, "node_type") != NodeType.AGENT.value:
                        message = "Retry configuration can only be changed for an agent step."
                        raise ConfigError(message)
                    options = (
                        agent.to_route() if agent is not None else _mapping(node, "retry_options")
                    )
                    if effort is not None:
                        options = {**options, "effort": effort.value}
                    if permission_mode is not None:
                        options = {**options, "permission_mode": permission_mode.value}
                    _set_model_field(node, "retry_options", options)
                    node.save(update_fields=("retry_options",))
                UsageRetry.objects.filter(run=run, state="scheduled").update(state="resumed")
                run_transition = transition_run(_string(run, "status"), "manual_rerun")
                _set_model_field(run, "status", run_transition.status)
                _set_model_field(run, "failure_code", None)
                _set_model_field(run, "failure_summary", None)
                _set_model_field(run, "ended_at", None)
                run.save(update_fields=("status", "failure_code", "failure_summary", "ended_at"))
                failed_nodes = sorted(
                    (
                        candidate
                        for candidate in NodeRun.objects.select_for_update()
                        .filter(
                            run=run,
                            status=NodeStatus.FAILED.value,
                        )
                        .distinct()
                        if scope_is_ancestor(_string(candidate, "scope_path"), target.scope_path)
                    ),
                    key=lambda candidate: (
                        len(parse_scope_path(_string(candidate, "scope_path"))),
                        _string(candidate, "scope_path"),
                    ),
                )
                for candidate in failed_nodes:
                    # Iteration rows summarize children without their own attempt.
                    # root.repeat#1 becomes running while its failed child is retried.
                    iteration = parse_scope_path(_string(candidate, "scope_path"))[-1].iteration
                    if _string(candidate, "node_type") == NodeType.LOOP.value and iteration:
                        status = NodeStatus.RUNNING.value
                        event = "node.running"
                    else:
                        node_transition = transition_node(_string(candidate, "status"), "rerun")
                        status = node_transition.status
                        event = node_transition.event
                    _set_model_field(candidate, "status", status)
                    candidate.save(update_fields=("status",))
                    _append_event(
                        run,
                        event,
                        EventSource.NODE,
                        {
                            "scope_path": _string(candidate, "scope_path"),
                            "node_type": _string(candidate, "node_type"),
                            "status": status,
                        },
                        node=candidate,
                    )
                canceled_nodes = list(
                    NodeRun.objects.select_for_update().filter(
                        run=run,
                        status=NodeStatus.CANCELED.value,
                    )
                )
                for candidate in canceled_nodes:
                    node_transition = transition_node(_string(candidate, "status"), "recompute")
                    _set_model_field(candidate, "status", node_transition.status)
                    candidate.save(update_fields=("status",))
                    _append_event(
                        run,
                        node_transition.event,
                        EventSource.NODE,
                        {
                            "scope_path": _string(candidate, "scope_path"),
                            "node_type": _string(candidate, "node_type"),
                            "status": node_transition.status,
                        },
                        node=candidate,
                    )
                _append_event(
                    run,
                    run_transition.event,
                    EventSource.RUN,
                    {
                        "status": run_transition.status,
                        "idempotency_key": idempotency_key,
                        "scope_path": target.scope_path,
                        "retry_options": _mapping(node, "retry_options"),
                    },
                    node=node,
                )
                return True
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not activate run recovery."
            raise PersistenceError(message, context={"run": target.run_id}) from None

    def activate_interrupted_run(self, run_id: str, idempotency_key: str) -> bool:
        """Reopen one run only after every interrupted checkout is prepared."""
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=run_id)
                if _string(run, "status") == RunStatus.RUNNING.value:
                    return False
                transition = transition_run(_string(run, "status"), "restart_reconcile")
                _set_model_field(run, "status", transition.status)
                _set_model_field(run, "failure_code", None)
                _set_model_field(run, "failure_summary", None)
                _set_model_field(run, "ended_at", None)
                run.save(update_fields=("status", "failure_code", "failure_summary", "ended_at"))
                _append_event(
                    run,
                    transition.event,
                    EventSource.RUN,
                    {"status": transition.status, "idempotency_key": idempotency_key},
                )
                return True
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not resume an interrupted run."
            raise PersistenceError(message, context={"run": run_id}) from None
