"""Run branch and isolated primary/reader worktree lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import time

from relay.constants import CLEANUP_BACKOFF_SECONDS, RUN_BRANCH_PREFIX
from relay.errors import GitError, WorktreeError
from relay.paths import ensure_private_dir, worktrees_dir

from .commits import is_ancestor
from .git import git_stdout, run_git

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _component(value: str, *, label: str) -> str:
    if _COMPONENT.fullmatch(value) is None or value in {".", ".."}:
        message = f"The {label} is not safe for a worktree path."
        raise WorktreeError(message)
    return value


def run_branch(run_id: str) -> str:
    """Transform run `abc-123` into retained branch `relay/run/abc-123`."""
    return f"{RUN_BRANCH_PREFIX}{_component(run_id, label='run id')}"


def run_worktree_path(run_id: str, *, root: Path | None = None) -> Path:
    """Return `<worktrees>/<run-id>` for the run's primary checkout."""
    base = ensure_private_dir(root) if root is not None else worktrees_dir(create=True)
    return base / _component(run_id, label="run id")


def reader_worktree_path(primary: Path, attempt_id: str) -> Path:
    """Return the plan-defined nested `r-<attempt>` reader checkout path."""
    return primary / f"r-{_component(attempt_id, label='attempt id')}"


def _resolve_commit(repository: Path, commit: str) -> str:
    return git_stdout(repository, ["rev-parse", "--verify", f"{commit}^{{commit}}"])


def create_primary_worktree(
    repository: Path,
    run_id: str,
    source_commit: str,
    *,
    root: Path | None = None,
) -> tuple[str, Path, str]:
    """Create a retained run branch and its primary worktree."""
    branch = run_branch(run_id)
    target = run_worktree_path(run_id, root=root)
    resolved_commit = _resolve_commit(repository, source_commit)
    existing = run_git(
        repository,
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        check=False,
    )
    if existing.returncode == 0:
        message = f"Run branch {branch} already exists."
        raise WorktreeError(message, context={"project": str(repository)})
    if existing.returncode not in {0, 1}:
        message = "Git could not check the run branch namespace."
        raise WorktreeError(message, context={"project": str(repository)})
    if target.exists():
        message = f"Run worktree path {target} already exists."
        raise WorktreeError(message, context={"project": str(repository)})
    try:
        run_git(repository, ["branch", branch, resolved_commit])
        run_git(repository, ["worktree", "add", str(target), branch])
    except GitError:
        # The branch is retained as launch evidence; only a partial checkout is removed.
        run_git(repository, ["worktree", "remove", "--force", str(target)], check=False)
        if target.exists():
            shutil.rmtree(target)
        message = "Relay could not create the run's primary Git worktree."
        raise WorktreeError(message, context={"project": str(repository)}) from None
    return branch, target, resolved_commit


def create_reader_worktree(
    repository: Path,
    primary: Path,
    attempt_id: str,
    commit: str,
) -> tuple[Path, str]:
    """Create a detached reader checkout at the recorded committed HEAD."""
    target = reader_worktree_path(primary, attempt_id)
    resolved_commit = _resolve_commit(repository, commit)
    if target.exists():
        message = f"Reader worktree path {target} already exists."
        raise WorktreeError(message, context={"project": str(repository)})
    try:
        run_git(
            repository,
            ["worktree", "add", "--detach", str(target), resolved_commit],
        )
    except GitError:
        message = "Relay could not create an isolated reader worktree."
        raise WorktreeError(message, context={"project": str(repository)}) from None
    return target, resolved_commit


def remove_worktree(repository: Path, worktree: Path) -> None:
    """Force-remove a known worktree with Windows-only bounded backoff."""
    delays = CLEANUP_BACKOFF_SECONDS if os.name == "nt" else ()
    attempts = len(delays) + 1
    for attempt in range(attempts):
        result = run_git(
            repository,
            ["worktree", "remove", "--force", str(worktree)],
            check=False,
        )
        if result.returncode == 0:
            return
        if attempt < len(delays):
            time.sleep(delays[attempt])
    message = f"Git could not remove worktree {worktree}."
    raise WorktreeError(
        message,
        context={"project": str(repository)},
        next_action=(
            "Retained evidence is intact; close processes using the path and clean it later."
        ),
    )


def reset_worktree(
    worktree: Path,
    target_head: str,
    *,
    protected_head: str,
) -> str:
    """Reset only after proving the target keeps every successful writer commit."""
    resolved_target = _resolve_commit(worktree, target_head)
    resolved_protected = _resolve_commit(worktree, protected_head)
    if not is_ancestor(worktree, resolved_protected, resolved_target):
        message = "The requested reset would discard a protected successful-writer commit."
        raise WorktreeError(message, context={"project": str(worktree)})
    try:
        run_git(worktree, ["reset", "--hard", resolved_target])
        run_git(worktree, ["clean", "-fd"])
    except GitError:
        message = "Relay could not restore the worktree after preserving attempt evidence."
        raise WorktreeError(message, context={"project": str(worktree)}) from None
    return resolved_target


def cleanup_worktrees(
    repository: Path,
    paths: tuple[Path, ...],
    *,
    evidence_preserved: bool,
) -> None:
    """Remove deepest worktrees first only after the caller proves preservation."""
    if not evidence_preserved:
        message = "Relay refused worktree cleanup before evidence preservation."
        raise WorktreeError(message, context={"project": str(repository)})
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        if path.exists():
            remove_worktree(repository, path)


__all__ = [
    "cleanup_worktrees",
    "create_primary_worktree",
    "create_reader_worktree",
    "reader_worktree_path",
    "remove_worktree",
    "reset_worktree",
    "run_branch",
    "run_worktree_path",
]
