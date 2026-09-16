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


def is_clean(repository: Path) -> bool:
    """Return whether the worktree has no porcelain records."""
    return not status_porcelain(repository)


__all__ = ["is_clean", "require_clean", "status_porcelain"]
