"""Workspace preparation shared by manual reruns and orderly restart."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from relay.errors import WorktreeError
from relay.paths import artifacts_dir
from relay.vcs.artifacts import PreservationResult, preserve_then_reset
from relay.vcs.cleanliness import require_clean
from relay.vcs.commits import current_head
from relay.vcs.worktree import remove_worktree, reset_worktree

from .resume import RecoveryTarget


class RecoveryEvidenceStore(Protocol):
    """Persistence boundary for newly retained attempt evidence."""

    def record_preservation(
        self,
        attempt_id: str,
        preservation: PreservationResult,
    ) -> None: ...


def prepare_recovery_workspace(
    store: RecoveryEvidenceStore,
    target: RecoveryTarget,
) -> None:
    """Preserve once, then restore or remove only the interrupted checkout."""
    repository = Path(target.project_path)
    worktree = Path(target.worktree_path)
    if not worktree.exists() and target.ephemeral_reader:
        return
    if not worktree.exists():
        message = "The interrupted run's primary worktree is missing."
        raise WorktreeError(
            message,
            context={"project": target.project_path},
            next_action="Restore or explicitly clean the retained run before restarting it.",
        )
    if not target.uses_git or target.attempt_id is None:
        require_clean(worktree, stage="interrupted run recovery")
        if current_head(worktree) != target.protected_head:
            message = "The interrupted run worktree moved away from its protected commit."
            raise WorktreeError(message, context={"project": target.project_path})
        return

    retained = artifacts_dir() / target.run_id / target.attempt_id
    if target.ephemeral_reader:
        if not retained.is_dir():
            preservation = preserve_then_reset(
                repository,
                worktree,
                target.run_id,
                target.attempt_id,
                target.starting_head,
                protected_head=target.protected_head,
            )
            store.record_preservation(target.attempt_id, preservation)
        remove_worktree(repository, worktree)
        return

    if retained.is_dir():
        reset_worktree(
            worktree,
            target.starting_head,
            protected_head=target.protected_head,
        )
        return
    preservation = preserve_then_reset(
        repository,
        worktree,
        target.run_id,
        target.attempt_id,
        target.starting_head,
        protected_head=target.protected_head,
    )
    store.record_preservation(target.attempt_id, preservation)


__all__ = ["RecoveryEvidenceStore", "prepare_recovery_workspace"]
