"""Workspace preparation shared by manual reruns and orderly restart."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from relay.errors import WorktreeError
from relay.paths import artifacts_dir
from relay.vcs.artifacts import (
    PreservationResult,
    RecoveryReport,
    preserve_attempt_evidence,
    restore_recovery_reports,
    validate_attempt_evidence,
    validate_recovery_reports,
)
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

    def capture_recovery_reports(self, target: RecoveryTarget) -> None: ...

    def recovery_reports(self, target: RecoveryTarget) -> tuple[RecoveryReport, ...]: ...


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
    if not retained.is_dir():
        preservation = preserve_attempt_evidence(
            repository, worktree, target.run_id, target.attempt_id, target.starting_head
        )
        store.record_preservation(target.attempt_id, preservation)
    # Previously captured evidence can be damaged later. Verify all archived
    # bytes and the retained commit before removing the current partial work.
    validate_attempt_evidence(repository, target.run_id, target.attempt_id, target.starting_head)
    # Retain ignored/rejected reports from older attempts before any reset.
    # The database then selects the failed report and successful handoffs.
    store.capture_recovery_reports(target)
    reports = store.recovery_reports(target)
    validate_recovery_reports(reports)
    if target.ephemeral_reader:
        remove_worktree(repository, worktree)
        return
    reset_worktree(
        worktree,
        target.starting_head,
        protected_head=target.protected_head,
    )
    restore_recovery_reports(worktree, reports)


__all__ = ["RecoveryEvidenceStore", "prepare_recovery_workspace"]
