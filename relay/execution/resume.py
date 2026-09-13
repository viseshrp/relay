"""Explicit failed-node rerun and orderly-interruption recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


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
    interrupted: bool


class ResumeStore(Protocol):
    def manual_rerun_target(self, run_id: str, scope_path: str) -> RecoveryTarget: ...

    def interrupted_targets(self) -> tuple[RecoveryTarget, ...]: ...

    def activate_recovery(self, target: RecoveryTarget, idempotency_key: str) -> bool: ...


def rerun_failed_node(
    store: ResumeStore,
    run_id: str,
    scope_path: str,
    idempotency_key: str,
    prepare_workspace: Callable[[RecoveryTarget], None],
) -> bool:
    """Preserve/reset first, then reopen only the selected failed node."""
    target = store.manual_rerun_target(run_id, scope_path)
    prepare_workspace(target)
    return store.activate_recovery(target, idempotency_key)


def resume_interrupted(
    store: ResumeStore,
    prepare_workspace: Callable[[RecoveryTarget], None],
) -> tuple[str, ...]:
    """Create fresh attempts for interrupted nodes after workspace recovery."""
    resumed: list[str] = []
    for target in store.interrupted_targets():
        prepare_workspace(target)
        key = f"restart:{target.run_id}:{target.node_run_id}:{target.attempt_id or 'none'}"
        if store.activate_recovery(target, key):
            resumed.append(target.run_id)
    return tuple(dict.fromkeys(resumed))


__all__ = ["RecoveryTarget", "ResumeStore", "rerun_failed_node", "resume_interrupted"]
