"""One-attempt orchestration across durable state, executors, Git, and evidence."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import logging
from pathlib import Path
import threading
import time
from typing import Protocol, TypeAlias

from relay.constants import ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
from relay.errors import NodeExecutionError, RelayError
from relay.vcs.artifacts import PreservationResult, preserve_attempt_evidence
from relay.vcs.commits import current_head, validate_reader_result, validate_writer_result
from relay.vcs.worktree import create_reader_worktree, remove_worktree, require_project_worktree

from .control import ClaimedControl
from .dispatch import ClaimDisposition, ClaimedAttempt, DispatchStore, claim_node_attempt
from .resources import AttemptResources, allocate_attempt_resources
from .state import AttemptStopReason, EventSensitivity, EventSource, NodeType
from .timing import attempt_deadline, remaining_seconds

LOGGER = logging.getLogger(__name__)
HeartbeatOwners: TypeAlias = tuple[tuple[str, str], ...]


class OutcomeKind(str, Enum):
    SUCCEEDED = "succeeded"
    WAITING = "waiting"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AttemptContext:
    """Frozen attempt facts and the checkout assigned to one executor."""

    attempt: ClaimedAttempt
    worktree: Path
    runtime: RunnerStore
    heartbeat_owners: HeartbeatOwners = ()
    deadline_at: float | None = None
    resources: AttemptResources | None = None

    def heartbeat(self) -> bool:
        """Renew this attempt and every enclosing synchronous-scope owner."""
        owners = (
            (self.attempt.attempt_id, self.attempt.worker_id),
            *self.heartbeat_owners,
        )
        return all(
            self.runtime.heartbeat_attempt(attempt_id, worker_id)
            for attempt_id, worker_id in owners
        )

    def remaining_seconds(self) -> float | None:
        """Return the time left under this node and all enclosing attempts."""
        return remaining_seconds(self.deadline_at)

    def timed_out(self) -> bool:
        """Report whether the monotonic attempt deadline has elapsed."""
        return self.deadline_at is not None and time.monotonic() >= self.deadline_at


@dataclass(frozen=True, slots=True)
class ScopeNodeRecord:
    """Minimal durable child-node state needed by event-driven scheduling."""

    node_run_id: str
    node_id: str
    status: str
    outputs: Mapping[str, object]
    selected_branch: str | None


class AttemptRuntime(DispatchStore, Protocol):
    """Durable callbacks an executor may use without knowing Django or Huey."""

    def append_attempt_event(
        self,
        attempt_id: str,
        event_type: str,
        source: EventSource,
        payload: Mapping[str, object],
        *,
        sensitivity: EventSensitivity = EventSensitivity.NORMAL,
    ) -> None: ...

    def heartbeat_attempt(self, attempt_id: str, worker_id: str) -> bool: ...

    def record_attempt_process(self, attempt_id: str, process_id: int | None) -> None: ...

    def claim_next_control(
        self,
        attempt_id: str,
        worker_id: str,
        kinds: tuple[str, ...] | None = None,
    ) -> ClaimedControl | None: ...

    def apply_control(self, request_id: str, worker_id: str) -> bool: ...

    def record_agent_session(
        self,
        attempt_id: str,
        *,
        process_id: int | None,
        session_id: str | None,
        agent_version: str,
        config_ids: Mapping[str, object],
    ) -> None: ...

    def request_agent_interaction(
        self,
        attempt_id: str,
        kind: str,
        prompt: str,
        options: tuple[Mapping[str, object], ...],
    ) -> str: ...

    def ensure_scope_nodes(
        self,
        run_id: str,
        parent_scope: str,
        nodes: Mapping[str, Mapping[str, object]],
        inputs: Mapping[str, object],
        loop_index: int | None,
    ) -> None: ...

    def scope_node_records(
        self,
        run_id: str,
        parent_scope: str,
        node_ids: tuple[str, ...],
    ) -> Mapping[str, ScopeNodeRecord]: ...

    def scope_node_record(self, run_id: str, node_run_id: str) -> ScopeNodeRecord: ...

    def transition_scope_node(
        self, node_run_id: str, action: str, *, expected_status: str | None = None
    ) -> str: ...

    def record_loop_iteration(
        self,
        coordinator_node_run_id: str,
        scope_path: str,
        iteration: int,
        kind: OutcomeKind,
        outputs: Mapping[str, Mapping[str, object]],
    ) -> None: ...

    def resolve_human_wait_controls(self) -> int: ...

    def expire_human_waits(self) -> int: ...


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Provider-independent result returned by every node executor."""

    kind: OutcomeKind
    stop_reason: AttemptStopReason | None = None
    outputs: Mapping[str, object] = field(default_factory=dict)
    declared_artifacts: Mapping[str, str] = field(default_factory=dict)
    selected_branch: str | None = None
    exit_code: int | None = None
    error_code: str | None = None
    wait_timeout_seconds: float | None = None
    error_message: str | None = None


class AttemptExecutor(Protocol):
    def execute(self, context: AttemptContext) -> ExecutionOutcome: ...


class RunnerStore(AttemptRuntime, Protocol):
    def heartbeat_attempt(self, attempt_id: str, worker_id: str) -> bool: ...

    def mark_attempt_waiting(self, attempt_id: str, timeout_seconds: float | None) -> None: ...

    def record_preservation(self, attempt_id: str, preservation: PreservationResult) -> None: ...

    def finish_attempt(
        self,
        attempt_id: str,
        outcome: ExecutionOutcome,
        ending_head: str,
    ) -> None: ...

    def release_attempt_lock(self, attempt_id: str) -> None: ...

    def close_heartbeat_connections(self) -> None: ...


@contextmanager
def _heartbeat_lease(
    store: RunnerStore, claim: ClaimedAttempt, owners: HeartbeatOwners
) -> Iterator[None]:
    """Renew ownership while subprocess, output, Git, and preservation work runs."""
    stop = threading.Event()

    def renew() -> None:
        try:
            while not stop.wait(ATTEMPT_HEARTBEAT_INTERVAL_SECONDS):
                for attempt_id, worker_id in ((claim.attempt_id, claim.worker_id), *owners):
                    if not store.heartbeat_attempt(attempt_id, worker_id):
                        return
        except Exception:
            LOGGER.exception(
                "Attempt heartbeat renewal failed", extra={"attempt_id": claim.attempt_id}
            )
        finally:
            store.close_heartbeat_connections()

    thread = threading.Thread(target=renew, name="relay-attempt-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def _uses_git(node_type: str) -> bool:
    return node_type in {NodeType.AGENT.value, NodeType.COMMAND.value}


def _assigned_worktree(claim: ClaimedAttempt) -> tuple[Path, bool]:
    primary = Path(claim.primary_worktree)
    require_project_worktree(Path(claim.project_path), primary)
    if not _uses_git(claim.node_type) or claim.writes:
        return primary, False
    reader, _commit = create_reader_worktree(
        Path(claim.project_path),
        primary,
        claim.attempt_id,
        claim.recorded_head,
    )
    return reader, True


def _failure(error: RelayError) -> ExecutionOutcome:
    reason = (
        AttemptStopReason.OUTPUT_INVALID
        if error.error_code == "output_validation_error"
        else AttemptStopReason.FAILED
    )
    return ExecutionOutcome(
        OutcomeKind.FAILED,
        stop_reason=reason,
        error_code=error.error_code,
        error_message=error.message,
    )


def _timeout_failure() -> ExecutionOutcome:
    return ExecutionOutcome(
        OutcomeKind.FAILED,
        stop_reason=AttemptStopReason.TIMEOUT,
        error_code="node_timeout",
    )


def _preserve(
    claim: ClaimedAttempt,
    worktree: Path,
    outcome: ExecutionOutcome,
    *,
    artifact_root: Path | None,
) -> PreservationResult:
    return preserve_attempt_evidence(
        Path(claim.project_path),
        worktree,
        claim.run_id,
        claim.attempt_id,
        claim.starting_head,
        declared_artifacts=dict(outcome.declared_artifacts),
        root=artifact_root,
    )


def execute_attempt(
    store: RunnerStore,
    claim: ClaimedAttempt,
    executor: AttemptExecutor,
    *,
    artifact_root: Path | None = None,
    heartbeat_owners: HeartbeatOwners = (),
    inherited_deadline: float | None = None,
) -> ExecutionOutcome:
    """Execute once, preserve evidence, persist terminal state, then release admission."""
    with _heartbeat_lease(store, claim, heartbeat_owners):
        try:
            resources = (
                allocate_attempt_resources(claim.run_id, claim.attempt_id)
                if _uses_git(claim.node_type)
                else None
            )
        except RelayError as error:
            # Allocation failures finish the claimed attempt instead of leaving it running.
            outcome = _failure(error)
            store.finish_attempt(claim.attempt_id, outcome, claim.starting_head)
            store.mark_dispatch_consumed(claim.claim_token)
            store.release_attempt_lock(claim.attempt_id)
            return outcome
        if resources is not None:
            claim = replace(
                claim,
                run_metadata={
                    **claim.run_metadata,
                    "temporary_directory": str(resources.directory / "temp"),
                    "browser_profile_directory": str(resources.directory / "browser-profiles"),
                },
            )
        try:
            return _execute_attempt(
                store,
                claim,
                executor,
                artifact_root=artifact_root,
                heartbeat_owners=heartbeat_owners,
                inherited_deadline=inherited_deadline,
                resources=resources,
            )
        finally:
            if resources is not None:
                try:
                    resources.cleanup()
                except RelayError:
                    LOGGER.exception(
                        "Temporary run resource cleanup failed",
                        extra={"run": claim.run_id, "attempt": claim.attempt_id},
                    )
                    # A diagnostic write must not replace the already persisted outcome.
                    with suppress(RelayError):
                        store.append_attempt_event(
                            claim.attempt_id,
                            "resource.cleanup_failed",
                            EventSource.SYSTEM,
                            {
                                "message": "Temporary resources were retained. "
                                "Retry their cleanup after this run finishes."
                            },
                        )


def _execute_attempt(
    store: RunnerStore,
    claim: ClaimedAttempt,
    executor: AttemptExecutor,
    *,
    artifact_root: Path | None,
    heartbeat_owners: HeartbeatOwners,
    inherited_deadline: float | None,
    resources: AttemptResources | None,
) -> ExecutionOutcome:
    worktree = Path(claim.primary_worktree)
    ephemeral_reader = False
    worktree_assigned = False
    try:
        worktree, ephemeral_reader = _assigned_worktree(claim)
        worktree_assigned = True
        timeout_value = claim.frozen_def.get("timeout")
        deadline = attempt_deadline(
            timeout_value if isinstance(timeout_value, str) else None,
            inherited_deadline,
        )
        if claim.deadline_at is not None:
            durable_deadline = time.monotonic() + max(
                0.0, (claim.deadline_at - datetime.now(timezone.utc)).total_seconds()
            )
            deadline = min(deadline, durable_deadline) if deadline is not None else durable_deadline
        context = AttemptContext(
            claim,
            worktree,
            store,
            heartbeat_owners=heartbeat_owners,
            deadline_at=deadline,
            resources=resources,
        )
        if context.timed_out() and claim.node_type != NodeType.HUMAN_WAIT.value:
            outcome = _timeout_failure()
        else:
            outcome = executor.execute(context)
            if outcome.kind is OutcomeKind.SUCCEEDED and context.timed_out():
                outcome = _timeout_failure()
    except RelayError as error:
        outcome = _failure(error)
    except Exception:
        LOGGER.exception("Node executor failed", extra={"attempt_id": claim.attempt_id})
        message = "The node executor failed unexpectedly."
        outcome = _failure(NodeExecutionError(message))

    ending_head = claim.starting_head
    preservation = None
    if outcome.kind is OutcomeKind.WAITING:
        store.mark_attempt_waiting(claim.attempt_id, outcome.wait_timeout_seconds)
        store.mark_dispatch_consumed(claim.claim_token)
        store.release_attempt_lock(claim.attempt_id)
        return outcome
    if _uses_git(claim.node_type) and worktree_assigned:
        try:
            if outcome.kind is OutcomeKind.SUCCEEDED:
                if claim.writes:
                    allow_no_commit = claim.frozen_def.get("allow_no_commit") is True
                    commit = validate_writer_result(
                        worktree,
                        claim.starting_head,
                        allow_no_commit=allow_no_commit,
                    )
                    ending_head = commit.ending_head
                else:
                    validate_reader_result(worktree, claim.starting_head)
                    ending_head = current_head(worktree)
            else:
                ending_head = current_head(worktree)
            preservation = _preserve(claim, worktree, outcome, artifact_root=artifact_root)
            store.record_preservation(claim.attempt_id, preservation)
        except RelayError as error:
            outcome = _failure(error)
            LOGGER.exception(
                "Attempt validation or preservation failed",
                extra={"attempt_id": claim.attempt_id},
            )

    # A reader checkout must disappear before its node can unlock downstream work.
    try:
        if ephemeral_reader and preservation is not None:
            remove_worktree(Path(claim.project_path), worktree)
    except RelayError as error:
        outcome = _failure(error)
        LOGGER.exception(
            "Reader worktree removal failed",
            extra={"attempt_id": claim.attempt_id},
        )

    terminal_persisted = False
    try:
        store.finish_attempt(claim.attempt_id, outcome, ending_head)
        terminal_persisted = True
        store.mark_dispatch_consumed(claim.claim_token)
    finally:
        if terminal_persisted:
            store.release_attempt_lock(claim.attempt_id)
    return outcome


def run_claim_token(
    store: RunnerStore,
    claim_token: str,
    worker_id: str,
    executor_for: Mapping[str, AttemptExecutor],
    *,
    artifact_root: Path | None = None,
    heartbeat_owners: HeartbeatOwners = (),
    inherited_deadline: float | None = None,
) -> ExecutionOutcome | None:
    """Claim a Huey token once and dispatch to the node-type executor."""
    result = claim_node_attempt(store, claim_token, worker_id)
    if result.disposition is not ClaimDisposition.CLAIMED or result.attempt is None:
        return None
    claim = result.attempt
    executor = executor_for.get(claim.node_type)
    if executor is None:
        message = f"No executor is registered for node type {claim.node_type!r}."
        outcome = _failure(NodeExecutionError(message))
        terminal_persisted = False
        try:
            store.finish_attempt(claim.attempt_id, outcome, claim.starting_head)
            terminal_persisted = True
            store.mark_dispatch_consumed(claim.claim_token)
        finally:
            if terminal_persisted:
                store.release_attempt_lock(claim.attempt_id)
        return outcome
    return execute_attempt(
        store,
        claim,
        executor,
        artifact_root=artifact_root,
        heartbeat_owners=heartbeat_owners,
        inherited_deadline=inherited_deadline,
    )


__all__ = [
    "AttemptContext",
    "AttemptExecutor",
    "AttemptRuntime",
    "ExecutionOutcome",
    "HeartbeatOwners",
    "OutcomeKind",
    "RunnerStore",
    "ScopeNodeRecord",
    "execute_attempt",
    "run_claim_token",
]
