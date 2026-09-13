"""Django persistence adapters used by Relay application services."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
import json
from typing import NoReturn, TypeVar
import uuid

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, IntegrityError, models, transaction
from django.db.models import Max
from django.utils import timezone

from relay.agents.models import ModelObservation
from relay.constants import (
    ATTEMPT_STALE_AFTER_SECONDS,
    CONTROL_CLAIM_STALE_AFTER_SECONDS,
    CONTROL_REQUEST_TTL_SECONDS,
    DISPATCH_ORPHAN_AFTER_SECONDS,
    EVENT_MAX_PAYLOAD_BYTES,
    RECONCILE_MAX_ITEMS,
)
from relay.errors import PersistenceError, ProjectRelinkError
from relay.execution.control import ClaimedControl, ControlRecovery, ControlResult
from relay.execution.dispatch import (
    ClaimDisposition,
    ClaimedAttempt,
    ClaimResult,
)
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
from relay.execution.state import (
    TERMINAL_NODE_STATUSES,
    AttemptStatus,
    AttemptStopReason,
    ControlKind,
    ControlState,
    DispatchState,
    DriverKind,
    EventSensitivity,
    EventSource,
    InteractionKind,
    InteractionStatus,
    NodeStatus,
    NodeType,
    PreservationState,
    RunStatus,
)
from relay.projects.identity import ProjectIdentity
from relay.projects.service import ProjectRecord
from relay.vcs.artifacts import PreservationResult
from relay.workflows.scope import enclosing_scope, node_scope, sibling_scope

from .models import (
    AgentModelObservation,
    Artifact,
    ControlRequest,
    DispatchClaim,
    HumanInteraction,
    NodeAttempt,
    NodeRun,
    Project,
    ProjectRelink,
    Run,
    RunEvent,
    RunLock,
    RunSnapshot,
)

ModelT = TypeVar("ModelT", bound=models.Model)


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
        raise PersistenceError(message, context={"run": run_id})
    message = "Only the failed node can be selected for rerun."
    raise PersistenceError(message, context={"run": run_id, "node": scope_path})


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


class DjangoExecutionStore:
    """Short-transaction adapter for execution, dispatch, controls, and recovery."""

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
                        stop_reason=AttemptStopReason.CANCELED,
                        error_code="canceled",
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

    def request_run_cancellation(self, run_id: str, idempotency_key: str) -> tuple[str, ...]:
        try:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=run_id)
                status = _string(run, "status")
                if status in {
                    RunStatus.SUCCEEDED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELED.value,
                }:
                    return ()
                if status != RunStatus.CANCELING.value:
                    transition = transition_run(status, "owner_cancel")
                    if transition.changed:
                        _set_model_field(run, "status", transition.status)
                        run.save(update_fields=("status",))
                        _append_event(
                            run,
                            transition.event,
                            EventSource.RUN,
                            {"status": transition.status},
                        )
                self._cancel_not_started(run)
                expires = timezone.now() + timedelta(seconds=CONTROL_REQUEST_TTL_SECONDS)
                request_ids: list[str] = []
                attempts = NodeAttempt.objects.filter(
                    node_run__run=run,
                    status__in=(AttemptStatus.RUNNING.value, AttemptStatus.WAITING.value),
                )
                for attempt in attempts:
                    request, _created = ControlRequest.objects.get_or_create(
                        attempt=attempt,
                        idempotency_key=f"{idempotency_key}:{_identifier(attempt)}",
                        defaults={
                            "kind": ControlKind.CANCEL.value,
                            "payload": {"reason": "owner_cancel"},
                            "state": ControlState.PENDING.value,
                            "expires_at": expires,
                        },
                    )
                    request_ids.append(_identifier(request))
                self._finish_run_if_terminal(run)
                return tuple(request_ids)
        except PersistenceError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not persist run cancellation."
            raise PersistenceError(message, context={"run": run_id}) from None

    def manual_rerun_target(self, run_id: str, scope_path: str) -> RecoveryTarget:
        try:
            run = Run.objects.select_related("project").get(pk=run_id)
            if _string(run, "status") != RunStatus.FAILED.value:
                _invalid_rerun_target(run_id)
            node = NodeRun.objects.get(run=run, scope_path=scope_path)
            if _string(node, "status") != NodeStatus.FAILED.value:
                _invalid_rerun_target(run_id, scope_path)
            attempt = NodeAttempt.objects.filter(node_run=node).order_by("-attempt_number").first()
            project = _related(run, "project", Project)
            return RecoveryTarget(
                run_id=run_id,
                node_run_id=_identifier(node),
                scope_path=scope_path,
                attempt_id=_identifier(attempt) if attempt is not None else None,
                project_path=_string(project, "git_root"),
                worktree_path=_string(run, "worktree_path"),
                starting_head=(
                    _string(attempt, "starting_head")
                    if attempt is not None
                    else _string(run, "recorded_head")
                ),
                protected_head=_string(run, "recorded_head"),
                interrupted=False,
            )
        except PersistenceError:
            raise
        except (DatabaseError, ObjectDoesNotExist):
            message = "Relay could not find the requested failed-node rerun target."
            raise PersistenceError(message, context={"run": run_id, "node": scope_path}) from None

    def interrupted_targets(self) -> tuple[RecoveryTarget, ...]:
        try:
            targets: list[RecoveryTarget] = []
            nodes = NodeRun.objects.select_related("run__project").filter(
                run__status=RunStatus.INTERRUPTED.value,
                status=NodeStatus.PENDING.value,
            )[:RECONCILE_MAX_ITEMS]
            for node in nodes:
                run = _related(node, "run", Run)
                project = _related(run, "project", Project)
                attempt = (
                    NodeAttempt.objects.filter(
                        node_run=node, stop_reason=AttemptStopReason.INTERRUPTED.value
                    )
                    .order_by("-attempt_number")
                    .first()
                )
                targets.append(
                    RecoveryTarget(
                        run_id=_identifier(run),
                        node_run_id=_identifier(node),
                        scope_path=_string(node, "scope_path"),
                        attempt_id=_identifier(attempt) if attempt is not None else None,
                        project_path=_string(project, "git_root"),
                        worktree_path=_string(run, "worktree_path"),
                        starting_head=(
                            _string(attempt, "starting_head")
                            if attempt is not None
                            else _string(run, "recorded_head")
                        ),
                        protected_head=_string(run, "recorded_head"),
                        interrupted=True,
                    )
                )
            return tuple(targets)
        except DatabaseError:
            message = "Relay could not load interrupted run targets."
            raise PersistenceError(message) from None

    def activate_recovery(self, target: RecoveryTarget, idempotency_key: str) -> bool:
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
                action = "restart_reconcile" if target.interrupted else "manual_rerun"
                run_transition = transition_run(_string(run, "status"), action)
                _set_model_field(run, "status", run_transition.status)
                _set_model_field(run, "failure_code", None)
                _set_model_field(run, "failure_summary", None)
                _set_model_field(run, "ended_at", None)
                run.save(update_fields=("status", "failure_code", "failure_summary", "ended_at"))
                if not target.interrupted:
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
