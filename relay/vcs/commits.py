"""Successful job commits and protected Git ancestry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from relay.constants import WORKFLOW_DOCUMENT_NAMES
from relay.errors import CommitValidationError, GitError

from .cleanliness import execution_changes, execution_status
from .git import git_stdout, run_git


@dataclass(frozen=True, slots=True)
class CommitResult:
    """Validated job movement from one immutable Git commit to another."""

    starting_head: str
    ending_head: str
    commit_count: int


def current_head(repository: Path) -> str:
    """Return the full object ID checked out in a worktree."""
    return git_stdout(repository, ["rev-parse", "HEAD"])


def is_ancestor(repository: Path, ancestor: str, descendant: str) -> bool:
    """Return true only when Git proves the requested ancestry relation."""
    result = run_git(
        repository,
        ["merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
    )
    if result.returncode not in {0, 1}:
        message = "Git could not validate commit ancestry."
        raise GitError(message, context={"project": str(repository)})
    return result.returncode == 0


def commits_between(repository: Path, starting_head: str, ending_head: str) -> tuple[str, ...]:
    """List accepted commits oldest first for durable attempt metadata."""
    output = git_stdout(
        repository,
        # Avoid Git's ambiguous filename probe for long SHA ranges on Windows.
        ["rev-list", "--reverse", f"{starting_head}..{ending_head}", "--"],
    )
    return tuple(output.splitlines()) if output else ()


def accept_job_result(
    worktree: Path,
    starting_head: str,
    job_id: str,
    *,
    snapshot_files: frozenset[str] = frozenset(),
    display_name: str | None = None,
) -> CommitResult:
    """Commit changed code at a successful Actions job boundary, or accept a no-op."""
    if not is_ancestor(worktree, starting_head, current_head(worktree)):
        message = "A job moved HEAD outside its starting commit ancestry."
        raise CommitValidationError(message)
    changes = [
        change
        for change in execution_status(worktree, snapshot_files=snapshot_files)
        if not change.allowed
    ]
    if any(
        change.path in WORKFLOW_DOCUMENT_NAMES
        or change.path in snapshot_files
        or "U" in change.status
        for change in changes
    ):
        message = "Staged workflow evidence or unresolved conflicts block job acceptance."
        raise CommitValidationError(message)
    if changes:
        paths = sorted(
            {path for change in changes for path in (change.path, change.original_path) if path}
        )
        run_git(worktree, ["add", "--all", "--", *paths])
        label = f"{display_name} ({job_id})" if display_name else job_id
        run_git(worktree, ["commit", "-m", f"Relay: complete job {label}"])
    # Retained report and captured source exemptions remain unstaged.
    if execution_changes(worktree, snapshot_files=snapshot_files):
        message = "A job left uncommitted code after its checkpoint."
        raise CommitValidationError(message)
    ending_head = current_head(worktree)
    if not is_ancestor(worktree, starting_head, ending_head):
        message = "A job moved HEAD outside its starting commit ancestry during acceptance."
        raise CommitValidationError(message)
    return CommitResult(
        starting_head, ending_head, len(commits_between(worktree, starting_head, ending_head))
    )


__all__ = [
    "CommitResult",
    "accept_job_result",
    "commits_between",
    "current_head",
    "is_ancestor",
]
