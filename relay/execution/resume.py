"""Explicit failed-node rerun and orderly-interruption recovery."""

from __future__ import annotations

from _thread import LockType
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
import threading
from typing import Protocol

from relay.errors import PersistenceError
from relay.execution.control import ControlResult, valid_idempotency_key
from relay.manage import MigrationLock
from relay.paths import data_dir

_RERUN_GUARD: LockType = threading.Lock()
_ACTIVE_RERUNS: set[str] = set()


def _claim_local_rerun(run_id: str) -> bool:
    """Serialize workspace preparation in Relay's singleton web process."""
    with _RERUN_GUARD:
        if run_id in _ACTIVE_RERUNS:
            return False
        _ACTIVE_RERUNS.add(run_id)
        return True


def _release_local_rerun(run_id: str) -> None:
    with _RERUN_GUARD:
        _ACTIVE_RERUNS.discard(run_id)


@dataclass(frozen=True, slots=True)
class RetryEffort:
    """An explicit owner choice; None requests the provider's default effort."""

    value: str | None


@dataclass(frozen=True, slots=True)
class RecoveryTarget:
    """Durable workspace and attempt facts needed before reopening a node."""

    run_id: str
    node_run_id: str
    scope_path: str
    attempt_id: str | None
    project_path: str
    worktree_path: str
    starting_head: str
    protected_head: str
    uses_git: bool
    ephemeral_reader: bool
    interrupted: bool
    agent_id: str | None = None
    model_value: str | None = None


class ResumeStore(Protocol):
    def manual_rerun_target(
        self,
        run_id: str,
        scope_path: str,
        idempotency_key: str,
    ) -> RecoveryTarget | None: ...

    def interrupted_targets(self) -> tuple[RecoveryTarget, ...]: ...

    def interrupted_run_ids(self) -> tuple[str, ...]: ...

    def activate_recovery(
        self,
        target: RecoveryTarget,
        idempotency_key: str,
        *,
        effort: RetryEffort | None = None,
    ) -> bool: ...

    def activate_usage_recovery(self, target: RecoveryTarget, idempotency_key: str) -> bool: ...

    def activate_interrupted_run(self, run_id: str, idempotency_key: str) -> bool: ...


def rerun_failed_node(
    store: ResumeStore,
    run_id: str,
    scope_path: str,
    idempotency_key: str,
    prepare_workspace: Callable[[RecoveryTarget], None],
    *,
    usage_reset: bool = False,
    effort: RetryEffort | None = None,
) -> ControlResult:
    """Preserve/reset first, then reopen only the selected failed node."""
    if not valid_idempotency_key(idempotency_key):
        return ControlResult.INVALID
    if not _claim_local_rerun(run_id):
        # The first request has not committed its durable rerun event yet, so
        # reporting it as applied would make a failed preparation look successful.
        return ControlResult.STALE
    # The consumer's scheduled recovery and the web owner's manual retry share
    # this kernel lock. It is released by the OS even if either process crashes.
    # `../run` becomes a fixed hexadecimal filename, never a path component.
    filename = sha256(run_id.encode()).hexdigest()
    lock = MigrationLock(
        data_dir() / "recovery-locks" / f"{filename}.lock", timeout=0, purpose="run recovery"
    )
    try:
        try:
            lock.__enter__()
        except PersistenceError:
            return ControlResult.STALE
        target = store.manual_rerun_target(run_id, scope_path, idempotency_key)
        if target is None:
            return ControlResult.ALREADY_APPLIED
        prepare_workspace(target)
        if usage_reset:
            activated = store.activate_usage_recovery(target, idempotency_key)
        elif effort is not None:
            activated = store.activate_recovery(target, idempotency_key, effort=effort)
        else:
            activated = store.activate_recovery(target, idempotency_key)
        return ControlResult.ACCEPTED if activated else ControlResult.ALREADY_APPLIED
    finally:
        lock.__exit__(None, None, None)
        _release_local_rerun(run_id)


def resume_interrupted(
    store: ResumeStore,
    prepare_workspace: Callable[[RecoveryTarget], None],
) -> tuple[str, ...]:
    """Create fresh attempts for interrupted nodes after workspace recovery."""
    targets_by_run = {}
    for target in store.interrupted_targets():
        targets_by_run.setdefault(target.run_id, []).append(target)

    resumed = []
    for run_id in store.interrupted_run_ids():
        # Remove reader checkouts and restore the primary writer before a
        # structural parent verifies that the shared worktree is clean.
        targets = sorted(
            targets_by_run.get(run_id, []),
            key=lambda target: 0 if target.ephemeral_reader else 1 if target.uses_git else 2,
        )
        for target in targets:
            prepare_workspace(target)
        attempt_ids = ",".join(target.attempt_id or "none" for target in targets) or "none"
        digest = sha256(attempt_ids.encode()).hexdigest()
        # Hashing bounds the durable key even for a large graph. For example,
        # attempt list `4,9` hashes to `f9406f...e9bb5e1a`.
        key = f"restart:{run_id}:{digest}"
        if store.activate_interrupted_run(run_id, key):
            resumed.append(run_id)
    return tuple(resumed)


__all__ = [
    "RecoveryTarget",
    "ResumeStore",
    "RetryEffort",
    "rerun_failed_node",
    "resume_interrupted",
]
