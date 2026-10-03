"""Repository cleanliness checks used before and after every attempt."""

from __future__ import annotations

from pathlib import Path

from relay.errors import DirtyRepositoryError

from .git import git_stdout


def status_porcelain(repository: Path) -> tuple[str, ...]:
    """Return stable porcelain-v1 records, including untracked files."""
    output = git_stdout(
        repository,
        ["status", "--porcelain=v1", "--untracked-files=all"],
    )
    return tuple(output.splitlines()) if output else ()


def require_clean(repository: Path, *, stage: str) -> None:
    """Reject any tracked, staged, or untracked change at a safety boundary."""
    changes = status_porcelain(repository)
    if changes:
        message = f"The Git worktree is not clean at {stage}."
        raise DirtyRepositoryError(
            message,
            context={"project": str(repository)},
            next_action="Commit, move, or remove the listed worktree changes before continuing.",
        )


__all__ = ["require_clean", "status_porcelain"]
