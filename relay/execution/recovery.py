"""Verify the shared job workspace before an owner retry or restart."""

from pathlib import Path

from relay.errors import DirtyRepositoryError, WorktreeError
from relay.vcs.artifacts import validate_attempt_evidence
from relay.vcs.cleanliness import execution_changes
from relay.vcs.commits import current_head

from .resume import RecoveryTarget


def prepare_recovery_workspace(target: RecoveryTarget) -> None:
    """Keep partial job bytes; refuse missing, dirty, or moved workspaces."""
    worktree = Path(target.worktree_path)
    if not worktree.exists():
        message = "The interrupted run's primary worktree is missing."
        raise WorktreeError(
            message,
            context={"project": target.project_path},
            next_action="Restore or explicitly clean the retained run before restarting it.",
        )
    # Root reports keep the same exemptions as a successful job boundary.
    # Code changes and staged reports require an owner decision before recovery.
    changes = execution_changes(worktree)
    if changes:
        message = "The Git worktree is not clean at interrupted run recovery."
        raise DirtyRepositoryError(
            message,
            context={"project": str(worktree), "changes": "\n".join(changes)},
            next_action="Commit or set aside the listed code changes before continuing.",
        )
    if current_head(worktree) != target.protected_head:
        message = "The interrupted run worktree moved away from its protected commit."
        raise WorktreeError(message, context={"project": target.project_path})
    if target.attempt_id is not None and not target.interrupted:
        validate_attempt_evidence(
            Path(target.project_path), target.run_id, target.attempt_id, target.starting_head
        )
