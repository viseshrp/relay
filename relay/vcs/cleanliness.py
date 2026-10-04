"""Repository cleanliness checks used before and after every attempt."""

from __future__ import annotations

import os
from pathlib import Path

from relay.constants import WORKFLOW_DOCUMENT_NAMES
from relay.errors import DirtyRepositoryError
from relay.projects.service import INITIAL_PROJECT_FILES

from .git import git_stdout, run_git_bytes


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


def execution_changes(
    repository: Path,
    *,
    snapshot_files: frozenset[str] = frozenset(),
    allow_initial_surface: bool = False,
) -> tuple[str, ...]:
    """Ignore unstaged workflow documents and exact snapshotted source files.

    ``?? REVIEW.md`` is allowed; ``?? src/review.py`` and staged ``A  REVIEW.md``
    remain changes. `` M .relay/workflows/check.yaml`` is allowed only when that
    exact file was validated and captured for this launch. NUL records preserve
    filenames such as ``my report.md`` without interpreting Git's quoted text.
    With ``allow_initial_surface``, an untracked, empty ``.relay/prompts/prompt.md``
    is allowed; one containing ``Owner notes`` still blocks launch.
    """
    raw = run_git_bytes(repository, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    git_root = Path(git_stdout(repository, ["rev-parse", "--show-toplevel"])).resolve()
    prefix = repository.resolve().relative_to(git_root)
    documents = {(prefix / name).as_posix() for name in WORKFLOW_DOCUMENT_NAMES}
    initial_files = (
        {
            # Native Windows initialization writes "version: 1\n" as
            # b"version: 1\r\n". Either complete starter encoding is unchanged.
            (prefix / ".relay" / relative).as_posix(): (
                text.encode("utf-8"),
                text.replace("\n", "\r\n").encode("utf-8"),
            )
            for relative, text in INITIAL_PROJECT_FILES
        }
        if allow_initial_surface
        else {}
    )
    records = raw.stdout.split(b"\0")
    changes = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        state = record[:2].decode("ascii")
        name = os.fsdecode(record[3:])
        # Rename/copy records carry another NUL field; neither is an allowed edit.
        if "R" in state or "C" in state:
            index += 1
        path = git_root / name
        allowed = name in documents or name in snapshot_files
        if path.is_file() and not path.is_symlink():
            if allowed and state in {"??", " M"}:
                continue
            if state == "??" and name in initial_files and path.resolve().is_relative_to(git_root):
                # Untracked, untouched init placeholders are safe to leave in place.
                # Read only enough to detect any owner edit, including appended bytes.
                try:
                    with path.open("rb") as stream:
                        expected = initial_files[name]
                        if stream.read(max(map(len, expected)) + 1) in expected:
                            continue
                except OSError:
                    pass
        changes.append(f"{state} {name}")
    return tuple(changes)


def require_launch_clean(repository: Path, snapshot_files: frozenset[str]) -> None:
    """Reject code/index changes while retaining owner documents in place."""
    changes = execution_changes(
        repository, snapshot_files=snapshot_files, allow_initial_surface=True
    )
    if changes:
        message = "The Git worktree has code or staged changes before starting this run."
        raise DirtyRepositoryError(
            message,
            context={"project": str(repository), "changes": "\n".join(changes)},
            next_action=(
                "Commit or set aside these code changes. Relay leaves workflow reports untouched."
            ),
        )


__all__ = ["execution_changes", "require_clean", "require_launch_clean", "status_porcelain"]
