"""Opt-in fast-forward integration into an unchanged, clean launch checkout."""

from __future__ import annotations

from pathlib import Path
import tempfile

from relay.errors import RunMergeError

from .cleanliness import require_clean
from .commits import current_head, is_ancestor
from .git import git_stdout, run_git


def require_merge_target(repository: Path, branch: str | None) -> str:
    """Require the captured branch and a strictly clean, idle owner checkout."""
    active = run_git(repository, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    if branch is None or active.returncode != 0 or active.stdout.strip() != branch:
        message = "The active branch changed or is detached. Relay kept the run working copy."
        raise RunMergeError(
            message,
            context={"project": str(repository), "branch": branch},
            next_action="Switch back to the branch selected at launch before merging the run.",
        )
    require_clean(repository, stage="merge into the active branch")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        path = Path(git_stdout(repository, ["rev-parse", "--git-path", marker]))
        if (repository / path).exists():
            message = "Finish the existing Git operation before merging the run."
            raise RunMergeError(message, context={"project": str(repository), "branch": branch})
    return current_head(repository)


def merge_run_branch(repository: Path, branch: str | None, run_branch: str, head: str) -> str:
    """Fast-forward without stashing, resolving conflicts, or running Git hooks."""
    starting_head = require_merge_target(repository, branch)
    run_head = git_stdout(repository, ["rev-parse", "--verify", f"refs/heads/{run_branch}"])
    if run_head != head:
        message = "The run branch changed after validation. Relay kept its working copy."
        raise RunMergeError(message, context={"project": str(repository), "branch": branch})
    # A restart after Git completed but before the database write must not merge twice.
    if is_ancestor(repository, head, starting_head):
        return starting_head
    if not is_ancestor(repository, starting_head, head):
        message = "The active branch has diverged. Merge the retained run branch manually."
        raise RunMergeError(message, context={"project": str(repository), "branch": branch})
    with tempfile.TemporaryDirectory(prefix="relay-merge-hooks-") as hooks:
        result = run_git(
            repository,
            ["-c", f"core.hooksPath={hooks}", "merge", "--ff-only", "--no-autostash", head],
            check=False,
        )
    if result.returncode != 0:
        message = "Git could not merge the run. Relay kept its working copy and commits."
        raise RunMergeError(message, context={"project": str(repository), "branch": branch})
    ending_head = require_merge_target(repository, branch)
    if ending_head != head:
        message = "The active branch changed during the merge. Relay kept the run working copy."
        raise RunMergeError(message, context={"project": str(repository), "branch": branch})
    return ending_head
