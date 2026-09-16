"""Django persistence adapters used by Relay application services."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
import shutil
from typing import NoReturn, TypeVar
import uuid

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, IntegrityError, models, transaction
from django.db.models import Max
from django.utils import timezone

from relay.agents.models import ModelObservation
from relay.constants import (
    API_MAX_PAGE,
    API_MAX_PAGE_BYTES,
    ATTEMPT_STALE_AFTER_SECONDS,
    CONTROL_CLAIM_STALE_AFTER_SECONDS,
    CONTROL_REQUEST_TTL_SECONDS,
    DISPATCH_ORPHAN_AFTER_SECONDS,
    EDITOR_LEASE_TTL_SECONDS,
    EVENT_MAX_PAYLOAD_BYTES,
    INSTANCE_STALE_AFTER_SECONDS,
    RECONCILE_MAX_ITEMS,
)
from relay.errors import (
    ConfigError,
    PermissionFlowError,
    PersistenceError,
    ProjectDiscoveryError,
    ProjectRelinkError,
    RelayError,
)
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
)
from relay.execution.launch import LaunchRequest
from relay.execution.locks import decide_admission
from relay.execution.machine import (
    transition_control,
    transition_interaction,
    transition_node,
    transition_run,
)
from relay.execution.reconcile import AttemptRecovery
from relay.execution.resume import RecoveryTarget
from relay.execution.runner import ExecutionOutcome, OutcomeKind, ScopeNodeRecord
from relay.execution.scheduler import RunSchedule, ScheduledNode
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
from relay.paths import (
    application_log_path,
    artifacts_dir,
    safe_resolve,
    shutdown_marker_path,
    worktrees_dir,
)
from relay.projects.identity import ProjectIdentity
from relay.projects.service import ProjectRecord
from relay.vcs.artifacts import PreservationResult
from relay.vcs.git import git_stdout, run_git
from relay.vcs.worktree import (
    reader_worktree_path,
    remove_worktree,
    run_branch,
    run_worktree_path,
)
from relay.workflows.loader import load_workflow_text
from relay.workflows.schema import NodeDefinition
from relay.workflows.scope import enclosing_scope, node_scope, sibling_scope
from relay.workflows.snapshot import SnapshotBundle

from .models import (
    AgentModelObservation,
    Artifact,
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
    WorkflowDraft,
)

ModelT = TypeVar("ModelT", bound=models.Model)
LOGGER = logging.getLogger(__name__)


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


def _text_field(project: Project, name: str) -> str:
    value = getattr(project, name)
    if not isinstance(value, str):
        message = f"Stored project field {name} is not text."
        raise PersistenceError(message)
    return value


def _set_field(project: Project, name: str, value: object) -> None:
    """Assign through a Django descriptor after application-level validation."""
    setattr(project, name, value)


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
        canonical_path=_text_field(project, "canonical_path"),
        display_name=_text_field(project, "display_name"),
        git_root=_text_field(project, "git_root"),
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

    def relink(self, old_path: str, identity: ProjectIdentity) -> ProjectRecord:
        try:
            with transaction.atomic():
                project = _require_project(
                    Project.objects.select_for_update().filter(canonical_path=old_path).first(),
                    old_path,
                )
                _reject_duplicate(project, identity.canonical_path)
                previous = _text_field(project, "canonical_path")
                _set_field(project, "canonical_path", identity.canonical_path)
                _set_field(project, "display_name", identity.display_name)
                _set_field(project, "git_root", identity.git_root)
                _set_field(project, "last_opened_at", timezone.now())
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
        "status": _string(run, "status"),
        "source_commit": _string(run, "source_commit"),
        "run_branch": _string(run, "run_branch"),
        "worktree_state": _string(run, "worktree_state"),
        "cleanup_policy": _string(run, "cleanup_policy"),
        "launcher": _string(run, "launcher"),
        "started_at": _datetime_text(_datetime_field(run, "started_at")),
        "ended_at": _datetime_text(_datetime_field(run, "ended_at")),
        "failure_code": run.failure_code,
        "failure_summary": run.failure_summary,
        "entry_point": run.entry_point,
    }


class DjangoReadStore:
    """Bounded, presentation-neutral reads for the authenticated browser."""

    def list_runs(
        self,
        *,
        project_id: str | None,
        status: str | None,
        since: str | None,
        limit: int,
    ) -> tuple[list[dict[str, object]], str | None]:
        bounded = min(max(limit, 1), API_MAX_PAGE)
        try:
            query = Run.objects.order_by("-started_at", "-pk")
            if project_id is not None:
                query = query.filter(project_id=project_id)
            if status is not None:
                query = query.filter(status=status)
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
            more = len(rows) > bounded
            rows = rows[:bounded]
            records: list[dict[str, object]] = []
            byte_count = 0
            for row in rows:
                record = _run_record(row)
                encoded = json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode(
                    "utf-8"
                )
                if records and byte_count + len(encoded) > API_MAX_PAGE_BYTES:
                    more = True
                    break
                records.append(record)
                byte_count += len(encoded)
            next_value = str(records[-1]["id"]) if more and records else None
        except ProjectDiscoveryError:
            raise
        except DatabaseError:
            message = "Relay could not read run history."
            raise PersistenceError(message) from None
        else:
            return records, next_value

    def run_detail(self, run_id: str) -> dict[str, object]:
        try:
            run = _require_run(
                Run.objects.select_related("snapshot").filter(pk=run_id).first(), run_id
            )
            snapshot = _related(run, "snapshot", RunSnapshot)
            result = _run_record(run)
            result["snapshot"] = {
                "relay_version": _string(snapshot, "relay_version"),
                "runtime_versions": _mapping(snapshot, "runtime_versions"),
                "hashes": _mapping(snapshot, "hashes"),
                "route_table": _mapping(snapshot, "route_table"),
                "created_at": _datetime_text(_datetime_field(snapshot, "created_at")),
            }
            result["nodes"] = [
                {
                    "id": _identifier(node),
                    "scope_path": _string(node, "scope_path"),
                    "node_id": _string(node, "node_id"),
                    "node_type": _string(node, "node_type"),
                    "status": _string(node, "status"),
                    "writes": _boolean(node, "writes"),
                    "outputs": _mapping(node, "outputs"),
                    "selected_branch": node.selected_branch,
                    "loop_index": node.loop_index,
                }
                for node in NodeRun.objects.filter(run=run).order_by("scope_path")
            ]
            result["attempts"] = [
                {
                    "id": _identifier(attempt),
                    "node_run_id": _foreign_key_text(attempt, "node_run"),
                    "scope_path": _string(_related(attempt, "node_run", NodeRun), "scope_path"),
                    "attempt_number": _integer(attempt, "attempt_number"),
                    "status": _string(attempt, "status"),
                    "driver_kind": attempt.driver_kind,
                    "agent_id": _string(attempt, "agent_id"),
                    "agent_version": _string(attempt, "agent_version"),
                    "model_value": _string(attempt, "model_value"),
                    "starting_head": _string(attempt, "starting_head"),
                    "ending_head": attempt.ending_head,
                    "started_at": _datetime_text(_datetime_field(attempt, "started_at")),
                    "ended_at": _datetime_text(_datetime_field(attempt, "ended_at")),
                    "stop_reason": attempt.stop_reason,
                    "exit_code": attempt.exit_code,
                    "error_code": attempt.error_code,
                }
                for attempt in NodeAttempt.objects.select_related("node_run")
                .filter(node_run__run=run)
                .order_by("node_run__scope_path", "attempt_number")
            ]
            result["interactions"] = [
                {
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
                    "deadline": _datetime_text(_datetime_field(interaction, "deadline")),
                    "created_at": _datetime_text(_datetime_field(interaction, "created_at")),
                    "answered_at": _datetime_text(_datetime_field(interaction, "answered_at")),
                }
                for interaction in HumanInteraction.objects.select_related("node_run", "attempt")
                .filter(run=run)
                .order_by("created_at", "pk")
            ]
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except DatabaseError:
            message = "Relay could not read run detail."
            raise PersistenceError(message, context={"run": run_id}) from None
        else:
            return result

    def page_events(
        self,
        run_id: str,
        since: int,
        limit: int,
    ) -> tuple[list[dict[str, object]], int | None]:
        bounded = min(max(limit, 1), API_MAX_PAGE)
        try:
            _require_run(Run.objects.filter(pk=run_id).first(), run_id)
            query = RunEvent.objects.filter(run_id=run_id, id__gt=since).order_by("id")
            rows = list(query[: bounded + 1])
            more = len(rows) > bounded
            events: list[dict[str, object]] = []
            byte_count = 0
            for row in rows[:bounded]:
                event = {
                    "id": row.id,
                    "type": _string(row, "type"),
                    "version": _integer(row, "version"),
                    "source": _string(row, "source"),
                    "ts": _datetime_text(row.ts),
                    "payload": _mapping(row, "payload"),
                }
                encoded = json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode(
                    "utf-8"
                )
                if events and byte_count + len(encoded) > API_MAX_PAGE_BYTES:
                    more = True
                    break
                events.append(event)
                byte_count += len(encoded)
            next_value = rows[len(events) - 1].id if more and events else None
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except DatabaseError:
            message = "Relay could not read the run event page."
            raise PersistenceError(message, context={"run": run_id}) from None
        else:
            return events, next_value

    def list_artifacts(self, run_id: str) -> list[dict[str, object]]:
        try:
            _require_run(Run.objects.filter(pk=run_id).first(), run_id)
            rows = Artifact.objects.filter(attempt__node_run__run_id=run_id).order_by("pk")
            return [
                {
                    "id": _identifier(row),
                    "attempt_id": str(row.attempt_id),
                    "name": _string(row, "declared_name"),
                    "source_path": _string(row, "source_path"),
                    "sha256": _string(row, "sha256"),
                    "bytes": _integer(row, "bytes"),
                    "media_type": _string(row, "media_type"),
                    "preservation_state": _string(row, "preservation_state"),
                }
                for row in rows
            ]
        except (ProjectDiscoveryError, PersistenceError):
            raise
        except DatabaseError:
            message = "Relay could not list retained run artifacts."
            raise PersistenceError(message, context={"run": run_id}) from None

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
    return RunEvent.objects.create(
        run=run,
        node_run=node,
        attempt=attempt,
        type=event_type,
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
    payload: dict[str, object] = {
        "prompt": _truncate_utf8(prompt, EVENT_MAX_PAYLOAD_BYTES // 2),
        "options": [],
    }
    retained: list[dict[str, object]] = []
    for option in options:
        candidate = [*retained, dict(option)]
        encoded = json.dumps(
            {**payload, "options": candidate}, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        if len(encoded) > EVENT_MAX_PAYLOAD_BYTES // 2:
            payload["options_truncated"] = True
            break
        retained = candidate
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
    contents: list[str] = []
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
                            RunStatus.CANCELING.value,
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

    def interrupt_active_attempts(self) -> int:
        """Force any attempt left after child exit into the resumable terminal state."""
        try:
            attempt_ids = list(
                NodeAttempt.objects.filter(
                    status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value)
                )
                .order_by("started_at", "pk")
                .values_list("pk", flat=True)
            )
            interrupted = 0
            for attempt_id in attempt_ids:
                with transaction.atomic():
                    attempt = (
                        NodeAttempt.objects.select_for_update()
                        .filter(
                            pk=attempt_id,
                            status__in=(
                                AttemptStatus.RUNNING.value,
                                AttemptStatus.WAITING.value,
                            ),
                        )
                        .first()
                    )
                    if attempt is None:
                        continue
                    self._discard_attempt_mailbox(attempt)
                    self.finish_attempt(
                        _identifier(attempt),
                        ExecutionOutcome(
                            OutcomeKind.FAILED,
                            stop_reason=AttemptStopReason.INTERRUPTED,
                            error_code=AttemptStopReason.INTERRUPTED.value,
                        ),
                        _string(attempt, "starting_head"),
                    )
                    DispatchClaim.objects.filter(attempt=attempt).update(
                        state=DispatchState.CONSUMED.value,
                        consumed_at=timezone.now(),
                    )
                    self.release_attempt_lock(_identifier(attempt))
                    interrupted += 1
        except PersistenceError:
            raise
        except DatabaseError:
            message = "Relay could not reconcile attempts after supervisor shutdown."
            raise PersistenceError(message) from None
        else:
            return interrupted

    def fail_worker_attempts(self) -> int:
        """Fail attempts whose worker process exited without orderly-shutdown intent."""
        try:
            attempt_ids = list(
                NodeAttempt.objects.exclude(node_run__node_type=NodeType.HUMAN_WAIT.value)
                .filter(status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value))
                .order_by("started_at", "pk")
                .values_list("pk", flat=True)
            )
            failed = 0
            for attempt_id in attempt_ids:
                with transaction.atomic():
                    attempt = (
                        NodeAttempt.objects.select_for_update()
                        .filter(
                            pk=attempt_id,
                            status__in=(
                                AttemptStatus.RUNNING.value,
                                AttemptStatus.WAITING.value,
                            ),
                        )
                        .first()
                    )
                    if attempt is None:
                        continue
                    self._discard_attempt_mailbox(attempt)
                    self.finish_attempt(
                        _identifier(attempt),
                        ExecutionOutcome(
                            OutcomeKind.FAILED,
                            stop_reason=AttemptStopReason.WORKER_LOST,
                            error_code=AttemptStopReason.WORKER_LOST.value,
                        ),
                        _string(attempt, "starting_head"),
                    )
                    DispatchClaim.objects.filter(attempt=attempt).update(
                        state=DispatchState.CONSUMED.value,
                        consumed_at=timezone.now(),
                    )
                    self.release_attempt_lock(_identifier(attempt))
                    failed += 1
        except PersistenceError:
            raise
        except DatabaseError:
            message = "Relay could not record attempts lost with the worker process."
            raise PersistenceError(message) from None
        else:
            return failed

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
                run_transition = transition_run(None, "launch")
                run = Run.objects.create(
                    id=run_id,
                    project=project,
                    workflow_key=request.workflow_key,
                    status=run_transition.status,
                    source_commit=source_commit,
                    run_branch=branch,
                    worktree_path=str(worktree),
                    worktree_state=WorktreeState.NONE.value,
                    cleanup_policy=request.cleanup_policy,
                    launcher=request.launcher,
                    entry_point=request.entry_point,
                    recorded_head=source_commit,
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

    def load_run_schedule(self, run_id: str) -> RunSchedule:
        try:
            run = Run.objects.select_related("snapshot").get(pk=run_id)
            snapshot = _related(run, "snapshot", RunSnapshot)
            loaded = load_workflow_text(
                _string(snapshot, "workflow_yaml"),
                source=Path(f"snapshot:{run_id}"),
            )
            rows = {
                _string(node, "node_id"): node
                for node in NodeRun.objects.filter(run=run, parent_scope_path__isnull=True)
            }
            if set(rows) != set(loaded.definition.nodes):
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
                for node_id, definition in loaded.definition.nodes.items()
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
                },
                run.entry_point if isinstance(run.entry_point, str) else None,
            )
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not load durable scheduling state."
            raise PersistenceError(message, context={"run": run_id}) from None

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

    def clean_project_data(self, project_id: str, scope: str) -> dict[str, int]:
        """Delete one confirmed category for the current project in preservation order."""
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
            runs = list(Run.objects.filter(project=project).order_by("started_at", "pk"))
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
                root = worktrees_dir()
                for run in runs:
                    path = safe_resolve(root, _string(run, "worktree_path"))
                    if path.exists():
                        remove_worktree(repository, path)
                        deleted["worktrees"] += 1
                    if _string(run, "worktree_state") != WorktreeState.REMOVED.value:
                        _set_model_field(run, "worktree_state", WorktreeState.REMOVED.value)
                        run.save(update_fields=("worktree_state",))
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
                        worktree = safe_resolve(
                            worktrees_dir(),
                            _string(run, "worktree_path"),
                        )
                        branch = _string(run, "run_branch")
                        retained_refs = _retained_attempt_refs(repository, _identifier(run))
                        if (
                            worktree.exists()
                            or _retained_branch_exists(repository, branch)
                            or retained_refs
                        ):
                            _reject_run_with_git_state(_identifier(run))
                artifact_root = artifacts_dir()
                for run in runs:
                    directory = safe_resolve(artifact_root, _identifier(run))
                    if directory.is_dir():
                        shutil.rmtree(directory)
                        deleted["artifact_roots"] += 1
                deleted["runs"] = len(runs)
                Run.objects.filter(pk__in=[run.pk for run in runs]).delete()
            if scope == "all":
                log = application_log_path()
                for path in (log, *(log.parent.glob(f"{log.name}.*"))):
                    if path.is_file():
                        path.unlink()
                        deleted["logs"] += 1
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
    ) -> tuple[
        dict[str, object],
        dict[str, dict[str, object]],
        dict[str, object],
        tuple[str, ...],
        dict[str, object],
        dict[str, object],
    ]:
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
        upstream: dict[str, dict[str, object]] = {}
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
        metadata: dict[str, object] = {
            "run_id": _identifier(run),
            "workflow_key": _string(run, "workflow_key"),
            "source_commit": _string(run, "source_commit"),
            "run_branch": _string(run, "run_branch"),
            "scope_path": scope_path,
        }
        if isinstance(run.entry_point, str):
            metadata["entry_point"] = run.entry_point
        loop_index = node.loop_index
        if loop_index is not None:
            if not isinstance(loop_index, int) or isinstance(loop_index, bool):
                message = "The stored loop iteration is invalid."
                raise PersistenceError(message, context={"node": scope_path})
            metadata["loop_index"] = loop_index
        route_table = _mapping(snapshot, "route_table")
        route_value = route_table.get(scope_path, {})
        if not isinstance(route_value, dict):
            message = "The snapshotted route entry is invalid."
            raise PersistenceError(message, context={"node": scope_path})
        return (
            inputs,
            upstream,
            metadata,
            _resolved_prompt_contents(snapshot, frozen),
            dict(route_value),
            _mapping(snapshot, "subworkflows"),
        )

    def create_dispatch(self, node_run_id: str) -> str:
        try:
            with transaction.atomic():
                node = NodeRun.objects.select_for_update().select_related("run").get(pk=node_run_id)
                run = _related(node, "run", Run)
                transition = transition_node(_string(node, "status"), "dispatch")
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
                token = uuid.uuid4().hex
                _set_model_field(node, "status", transition.status)
                node.save(update_fields=("status",))
                DispatchClaim.objects.create(
                    node_run=node,
                    claim_token=token,
                    state=DispatchState.DISPATCHED.value,
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
                    return ClaimResult(ClaimDisposition.BUSY)

                scope_path = _string(node, "scope_path")
                frozen = _mapping(node, "frozen_def")
                (
                    inputs,
                    upstream_outputs,
                    run_metadata,
                    prompt_contents,
                    route,
                    subworkflows,
                ) = self._claim_context(run, node, snapshot, frozen)
                selected_agent = route.get("selected_agent", "")
                model_value = route.get("model_value", "")
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

                maximum = NodeAttempt.objects.filter(node_run=node).aggregate(
                    value=Max("attempt_number")
                )["value"]
                attempt_number = (maximum if isinstance(maximum, int) else 0) + 1
                now = timezone.now()
                starting_head = _string(run, "recorded_head")
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
                    inputs=inputs,
                    upstream_outputs=upstream_outputs,
                    run_metadata=run_metadata,
                    prompt_contents=prompt_contents,
                    route=route,
                    subworkflows=subworkflows,
                    writes=writes,
                    starting_head=starting_head,
                    recorded_head=starting_head,
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

    def record_attempt_process(self, attempt_id: str, process_id: int | None) -> None:
        try:
            NodeAttempt.objects.filter(
                pk=attempt_id,
                status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
            ).update(process_pid=process_id)
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
        try:
            NodeAttempt.objects.filter(
                pk=attempt_id,
                status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
            ).update(
                process_pid=process_id,
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

    def transition_scope_node(self, node_run_id: str, action: str) -> None:
        try:
            with transaction.atomic():
                node = NodeRun.objects.select_for_update().select_related("run").get(pk=node_run_id)
                run = _related(node, "run", Run)
                transition = transition_node(_string(node, "status"), action)
                if not transition.changed:
                    return
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
                if _string(marker, "status") != status:
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
                transition = transition_node(_string(node, "status"), "interaction_requested")
                _set_model_field(attempt, "status", AttemptStatus.WAITING.value)
                attempt.save(update_fields=("status",))
                _set_model_field(node, "status", transition.status)
                node.save(update_fields=("status",))
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
            failed = NodeRun.objects.filter(run=run, status=NodeStatus.FAILED.value).exists()
            if failed:
                return
            action = "all_succeeded"
        else:
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
                node_status, node_event, stop_reason = self._finish_node_transition(node, outcome)
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
                            run.save(update_fields=("status", "failure_code"))
                            _append_event(
                                run,
                                run_transition.event,
                                EventSource.RUN,
                                {
                                    "status": run_transition.status,
                                    "failure_code": outcome.error_code or stop_reason,
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
                self._finish_run_if_terminal(run)
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not finish the node attempt transaction."
            raise PersistenceError(message, context={"node": attempt_id}) from None

    def release_attempt_lock(self, attempt_id: str) -> None:
        try:
            RunLock.objects.filter(attempt_id=attempt_id).delete()
        except DatabaseError:
            message = "Relay could not release the attempt's worktree lock."
            raise PersistenceError(message, context={"node": attempt_id}) from None

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
                expected_interaction = {
                    ControlKind.PERMISSION_ANSWER.value: InteractionKind.PERMISSION.value,
                    ControlKind.ELICITATION_ANSWER.value: InteractionKind.ELICITATION.value,
                    ControlKind.WAIT_ANSWER.value: InteractionKind.WAIT.value,
                }.get(kind)
                if (
                    state == ControlState.PENDING.value
                    and expected_interaction is not None
                    and not HumanInteraction.objects.filter(
                        attempt=attempt,
                        kind=expected_interaction,
                        status=InteractionStatus.PENDING.value,
                    ).exists()
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

    def heartbeat_control(self, request_id: str, worker_id: str) -> bool:
        try:
            updated = ControlRequest.objects.filter(
                pk=request_id,
                state=ControlState.CLAIMED.value,
                claim_owner=worker_id,
            ).update(claim_heartbeat_at=timezone.now())
        except DatabaseError:
            message = "Relay could not update the control-request heartbeat."
            raise PersistenceError(message) from None
        else:
            return updated == 1

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
                interaction_kind = {
                    ControlKind.PERMISSION_ANSWER.value: InteractionKind.PERMISSION.value,
                    ControlKind.ELICITATION_ANSWER.value: InteractionKind.ELICITATION.value,
                    ControlKind.WAIT_ANSWER.value: InteractionKind.WAIT.value,
                }.get(kind)
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
                        blocked = NodeRun.objects.filter(
                            run=run,
                            status__in=(NodeStatus.WAITING.value, NodeStatus.FAILED.value),
                        ).exists()
                        if not blocked and _string(run, "status") == RunStatus.PAUSED_WAIT.value:
                            run_transition = transition_run(_string(run, "status"), "wait_answered")
                            _set_model_field(run, "status", run_transition.status)
                            run.save(update_fields=("status",))
                            _append_event(
                                run,
                                run_transition.event,
                                EventSource.RUN,
                                {"status": run_transition.status},
                            )
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
                    attempt__node_run__node_type=NodeType.HUMAN_WAIT.value,
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
                    if (
                        isinstance(on_timeout, str)
                        and _string(run, "status") == RunStatus.PAUSED_WAIT.value
                    ):
                        run_transition = transition_run(_string(run, "status"), "wait_answered")
                        _set_model_field(run, "status", run_transition.status)
                        run.save(update_fields=("status",))
                        _append_event(
                            run,
                            run_transition.event,
                            EventSource.RUN,
                            {"status": run_transition.status},
                        )
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

    def orphaned_dispatch_tokens(self) -> tuple[str, ...]:
        cutoff = timezone.now() - timedelta(seconds=DISPATCH_ORPHAN_AFTER_SECONDS)
        try:
            tokens = (
                DispatchClaim.objects.filter(
                    state=DispatchState.DISPATCHED.value,
                    attempt__isnull=True,
                    node_run__status=NodeStatus.DISPATCHED.value,
                    node_run__run__status=RunStatus.RUNNING.value,
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
                and _string(node, "node_type") == NodeType.HUMAN_WAIT.value
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
                    payload__idempotency_key=idempotency_key,
                ).exists()
                if duplicate:
                    return ControlResult.ALREADY_APPLIED
                status = _string(run, "status")
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
                        idempotency_key=f"{idempotency_key}:{_identifier(attempt)}",
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
        )

    def manual_rerun_target(self, run_id: str, scope_path: str) -> RecoveryTarget:
        try:
            run = Run.objects.select_related("project").get(pk=run_id)
            if _string(run, "status") != RunStatus.FAILED.value:
                _invalid_rerun_target(run_id)
            node = NodeRun.objects.get(run=run, scope_path=scope_path)
            if _string(node, "status") != NodeStatus.FAILED.value:
                _invalid_rerun_target(run_id, scope_path)
            attempt = NodeAttempt.objects.filter(node_run=node).order_by("-attempt_number").first()
            return self._recovery_target(run, node, attempt, interrupted=False)
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not find the requested failed-node rerun target."
            raise PersistenceError(message, context={"run": run_id, "node": scope_path}) from None

    def interrupted_targets(self) -> tuple[RecoveryTarget, ...]:
        try:
            targets: list[RecoveryTarget] = []
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

    def activate_recovery(self, target: RecoveryTarget, idempotency_key: str) -> bool:
        if target.interrupted:
            return self.activate_interrupted_run(target.run_id, idempotency_key)
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=target.run_id)
                node = NodeRun.objects.select_for_update().get(pk=target.node_run_id, run=run)
                duplicate = RunEvent.objects.filter(
                    run=run,
                    type__in=("run.rerun", "run.resumed"),
                    payload__idempotency_key=idempotency_key,
                ).exists()
                if duplicate:
                    return False
                run_transition = transition_run(_string(run, "status"), "manual_rerun")
                _set_model_field(run, "status", run_transition.status)
                _set_model_field(run, "failure_code", None)
                _set_model_field(run, "failure_summary", None)
                _set_model_field(run, "ended_at", None)
                run.save(update_fields=("status", "failure_code", "failure_summary", "ended_at"))
                node_transition = transition_node(_string(node, "status"), "rerun")
                _set_model_field(node, "status", node_transition.status)
                node.save(update_fields=("status",))
                NodeRun.objects.filter(run=run, status=NodeStatus.CANCELED.value).update(
                    status=NodeStatus.PENDING.value
                )
                _append_event(
                    run,
                    run_transition.event,
                    EventSource.RUN,
                    {
                        "status": run_transition.status,
                        "idempotency_key": idempotency_key,
                        "scope_path": target.scope_path,
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
