"""Repository cleanliness checks used before and after every attempt."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class RepositoryChange:
    """One Git status record and the shared launch exemption decision."""

    status: str
    path: str
    original_path: str | None
    allowed: bool
    reasons: tuple[str, ...]


def execution_status(
    repository: Path,
    *,
    snapshot_files: frozenset[str] = frozenset(),
    allow_initial_surface: bool = False,
) -> tuple[RepositoryChange, ...]:
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
    changes: list[RepositoryChange] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        state = record[:2].decode("ascii")
        name = os.fsdecode(record[3:])
        original_path = None
        # Rename/copy records carry another NUL field; neither is an allowed edit.
        if "R" in state or "C" in state:
            original_path = os.fsdecode(records[index]) if index < len(records) else None
            index += 1
        path = git_root / name
        allowed = name in documents or name in snapshot_files
        allowed_change = allowed and state in {"??", " M"}
        initial_change = state == "??" and name in initial_files
        allowed_reason = None
        if (allowed_change or initial_change) and path.is_file() and not path.is_symlink():
            if allowed_change:
                allowed_reason = (
                    "Root workflow report" if name in documents else "Captured workflow source"
                )
            if (
                allowed_reason is None
                and initial_change
                and path.resolve().is_relative_to(git_root)
            ):
                # Untracked, untouched init placeholders are safe to leave in place.
                # Read only enough to detect any owner edit, including appended bytes.
                try:
                    with path.open("rb") as stream:
                        expected = initial_files[name]
                        if stream.read(max(map(len, expected)) + 1) in expected:
                            allowed_reason = "Unchanged setup file"
                except OSError:
                    pass
        reasons = []
        if allowed_reason is not None:
            reasons.append(allowed_reason)
        else:
            if state == "??":
                reasons.append("untracked")
            elif state[0] != " ":
                reasons.append("staged")
            if "M" in state:
                reasons.append("modified")
            if "D" in state:
                reasons.append("deleted")
            if "R" in state:
                reasons.append("renamed")
            if "C" in state:
                reasons.append("copied")
            if "U" in state:
                reasons.append("Git conflict")
            if path.is_symlink():
                reasons.append("symlink")
            if not reasons:
                reasons.append("changed")
        changes.append(
            RepositoryChange(state, name, original_path, allowed_reason is not None, tuple(reasons))
        )
    return tuple(changes)


def execution_changes(
    repository: Path,
    *,
    snapshot_files: frozenset[str] = frozenset(),
    allow_initial_surface: bool = False,
) -> tuple[str, ...]:
    """Return blocking records without changing the existing error format."""
    return tuple(
        f"{change.status} {change.path}"
        for change in execution_status(
            repository, snapshot_files=snapshot_files, allow_initial_surface=allow_initial_surface
        )
        if not change.allowed
    )


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


__all__ = [
    "RepositoryChange",
    "execution_changes",
    "execution_status",
    "require_clean",
    "require_launch_clean",
    "status_porcelain",
]
