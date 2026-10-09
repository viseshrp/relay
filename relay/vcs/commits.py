"""Writer commit and reader attribution invariants."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from relay.constants import WORKFLOW_DOCUMENT_NAMES
from relay.errors import CommitValidationError, GitError

from .cleanliness import execution_changes, execution_status, status_porcelain
from .git import git_stdout, run_git


@dataclass(frozen=True, slots=True)
class CommitResult:
    """Validated writer movement from one immutable Git commit to another."""

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
        ["rev-list", "--reverse", f"{starting_head}..{ending_head}"],
    )
    return tuple(output.splitlines()) if output else ()


def validate_writer_result(
    worktree: Path,
    starting_head: str,
    *,
    allow_no_commit: bool = False,
) -> CommitResult:
    """Require a clean descendant HEAD, or an explicitly allowed no-op."""
    changes = execution_changes(worktree)
    if changes:
        message = "A writing node finished with uncommitted worktree changes."
        raise CommitValidationError(
            message,
            context={"project": str(worktree)},
            next_action="Inspect the retained attempt evidence before rerunning the node.",
        )
    ending_head = current_head(worktree)
    if not is_ancestor(worktree, starting_head, ending_head):
        message = "A writing node moved HEAD outside its starting commit ancestry."
        raise CommitValidationError(message, context={"project": str(worktree)})
    commits = commits_between(worktree, starting_head, ending_head)
    if not commits and not allow_no_commit:
        message = "A writing node produced no commit."
        raise CommitValidationError(
            message,
            context={"project": str(worktree)},
            next_action=(
                "Commit the node's work or declare allow_no_commit for an intentional no-op."
            ),
        )
    return CommitResult(starting_head, ending_head, len(commits))


def accept_job_result(
    worktree: Path, starting_head: str, job_id: str, *, snapshot_files: frozenset[str] = frozenset()
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
        run_git(worktree, ["commit", "-m", f"Relay: complete job {job_id}"])
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


def validate_reader_result(worktree: Path, starting_head: str) -> None:
    """Reject any read-only diff or HEAD movement for exact attribution."""
    ending_head = current_head(worktree)
    if ending_head != starting_head or status_porcelain(worktree):
        message = "A read-only node changed its isolated worktree."
        raise CommitValidationError(
            message,
            context={"project": str(worktree)},
            next_action=(
                "Inspect the retained reader evidence; mark the node as writing if intended."
            ),
        )


__all__ = [
    "CommitResult",
    "commits_between",
    "current_head",
    "is_ancestor",
    "validate_reader_result",
    "validate_writer_result",
]
