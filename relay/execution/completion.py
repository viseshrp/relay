"""Durable opt-in run integration after every job has finished successfully."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
import logging
from pathlib import Path
from typing import Protocol

from relay.errors import PersistenceError, RelayError, RunMergeError
from relay.manage import MigrationLock
from relay.paths import data_dir
from relay.vcs.cleanliness import execution_changes
from relay.vcs.commits import current_head, is_ancestor
from relay.vcs.git import git_stdout
from relay.vcs.merge import merge_run_branch, require_merge_target
from relay.vcs.worktree import remove_worktree, require_project_worktree

from .resume import recovery_workspace_lock

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MergeTarget:
    repository: Path
    worktree: Path
    branch: str | None
    run_branch: str
    head: str
    merged_commit: str | None


class CompletionStore(Protocol):
    def run_merge_target(self, run_id: str) -> MergeTarget | None: ...

    def require_completion_evidence(self, run_id: str) -> None: ...

    def record_run_merge(self, run_id: str, commit: str) -> None: ...

    def finish_run_completion(self, run_id: str, error: RelayError | None) -> None: ...


def complete_run_merge(store: CompletionStore, run_id: str) -> None:
    """Serialize repository integration and retain the workspace on any failure."""
    target = store.run_merge_target(run_id)
    if target is None:
        return
    try:
        common = git_stdout(target.repository, ["rev-parse", "--git-common-dir"])
        lock_key = sha256(str((target.repository / common).resolve()).encode()).hexdigest()
        with ExitStack() as locks:
            try:
                locks.enter_context(recovery_workspace_lock(run_id))
                locks.enter_context(
                    MigrationLock(
                        data_dir() / "merge-locks" / f"{lock_key}.lock",
                        timeout=0,
                        purpose="run merge",
                    )
                )
            except PersistenceError:
                # Another process owns the workspace; reconciliation resumes the durable intent.
                return
            target = store.run_merge_target(run_id)
            if target is None:
                return
            store.require_completion_evidence(run_id)
            if target.worktree.exists():
                require_project_worktree(target.repository, target.worktree)
                if current_head(target.worktree) != target.head:
                    message = "The run working copy changed after validation. Merge was stopped."
                    raise RunMergeError(message, context={"run": run_id})
                if execution_changes(target.worktree):
                    message = "The run working copy has new changes. Merge was stopped."
                    raise RunMergeError(message, context={"run": run_id})
            elif target.merged_commit is None:
                message = "The run working copy is missing. Merge was stopped."
                raise RunMergeError(message, context={"run": run_id})
            if target.merged_commit is None:
                commit = merge_run_branch(
                    target.repository, target.branch, target.run_branch, target.head
                )
                store.record_run_merge(run_id, commit)
            else:
                active_head = require_merge_target(target.repository, target.branch)
                if not is_ancestor(target.repository, target.head, active_head):
                    message = (
                        "The active branch no longer contains the merged run. Cleanup was stopped."
                    )
                    raise RunMergeError(message, context={"run": run_id})
            if target.worktree.exists():
                remove_worktree(target.repository, target.worktree)
            store.finish_run_completion(run_id, None)
    except RelayError as error:
        LOGGER.exception("Run integration failed", extra={"run": run_id})
        store.finish_run_completion(run_id, error)
    except OSError:
        LOGGER.exception("Run integration filesystem failure", extra={"run": run_id})
        store.finish_run_completion(
            run_id,
            RunMergeError("Relay could not finish merging and removing the working copy."),
        )
