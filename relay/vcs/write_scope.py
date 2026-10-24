"""Check that one agent step changed only the paths its workflow allows."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import re
import shutil
import tempfile

from relay.constants import WORKFLOW_DOCUMENT_NAMES
from relay.errors import NodeExecutionError, OutputValidationError

from .artifacts import retained_attempt_ref
from .git import git_stdout, run_git_bytes

VIOLATIONS_SHOWN = 20


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """`**` crosses folders, `*` and `?` stay within one, and `dir/` means everything below."""
    if pattern.endswith("/"):
        pattern += "**"
    result = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            result.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            result.append(".*")
            index += 2
        elif pattern[index] == "*":
            result.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            result.append("[^/]")
            index += 1
        else:
            result.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(result) + r"\Z")


def path_allowed(path: str, patterns: Sequence[str]) -> bool:
    """Match exactly and case-sensitively, so every platform gives the same answer."""
    return any(_pattern_regex(pattern).match(path) for pattern in patterns)


def capture_worktree(worktree: Path) -> str:
    """Record tracked and untracked worktree content as a tree, outside the real index.

    The worktree's index is copied to a private file so Git can reuse its stat
    cache; HEAD, branches, the real index, and files are never changed.
    """
    # A relative answer is relative to the worktree; joining keeps absolute ones.
    index = worktree / git_stdout(worktree, ["rev-parse", "--git-path", "index"])
    directory = Path(tempfile.mkdtemp(prefix="relay-scope-"))
    try:
        private = directory / "index"
        if index.is_file():
            shutil.copyfile(index, private)
        env = {"GIT_INDEX_FILE": str(private)}
        if not index.is_file():
            run_git_bytes(worktree, ["read-tree", "HEAD"], env=env)
        # `:/` covers the whole checkout, including paths outside the project folder.
        run_git_bytes(worktree, ["add", "--all", "--", ":/"], env=env)
        return run_git_bytes(worktree, ["write-tree"], env=env).stdout.decode("ascii").strip()
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def baseline_ref(run_id: str, node_run_id: str) -> str:
    """Name the ref for run `abc` step `7`: `refs/relay/attempts/abc/scope-7`.

    It lives in the run's retained-ref namespace, so confirmed run cleanup
    removes it together with the run's attempt refs.
    """
    return f"{retained_attempt_ref(run_id, 'scope-' + node_run_id)}"


def is_baseline_ref(reference: str) -> bool:
    """True for `refs/relay/attempts/<run>/scope-<step>`, not for an attempt's own ref."""
    return reference.rsplit("/", 1)[-1].startswith("scope-")


def protect_baseline(worktree: Path, tree: str, reference: str) -> None:
    """Keep a captured tree reachable so Git garbage collection cannot drop it."""
    commit = git_stdout(worktree, ["commit-tree", tree, "-m", "Relay write-scope baseline"])
    run_git_bytes(worktree, ["update-ref", reference, commit])


def changed_paths(worktree: Path, before: str, after: str) -> tuple[str, ...]:
    """List repository-relative paths that differ between two captured trees."""
    raw = run_git_bytes(
        worktree, ["diff", "--name-only", "--no-renames", "-z", before, after]
    ).stdout
    return tuple(os.fsdecode(item) for item in raw.split(b"\0") if item)


def require_allowed_changes(
    worktree: Path,
    before: str,
    patterns: Sequence[str],
    *,
    report: str | None = None,
) -> None:
    """Reject a step that changed anything outside its declared patterns.

    Root workflow reports such as `REVIEW.md` and the step's own report stay
    allowed, so a scoped reviewer can still deliver its handoff. Changes
    outside the project folder are always violations.
    """
    if run_git_bytes(worktree, ["cat-file", "-e", f"{before}^{{tree}}"], check=False).returncode:
        message = "Relay can no longer read this step's starting snapshot."
        raise NodeExecutionError(
            message,
            next_action="Re-run the job so the step records a new starting snapshot.",
        )
    after = capture_worktree(worktree)
    prefix = git_stdout(worktree, ["rev-parse", "--show-prefix"])
    exempt = set(WORKFLOW_DOCUMENT_NAMES) | ({report} if report else set())
    violations = []
    for path in changed_paths(worktree, before, after):
        relative = path[len(prefix) :] if path.startswith(prefix) else None
        if relative is None or not (relative in exempt or path_allowed(relative, patterns)):
            violations.append(relative if relative is not None else path)
    if violations:
        shown = ", ".join(violations[:VIOLATIONS_SHOWN])
        more = len(violations) - VIOLATIONS_SHOWN
        message = (
            "The step changed paths outside its allowed-paths: "
            + shown
            + (f", and {more} more" if more > 0 else "")
            + ". Revert those changes or keep the work within: "
            + ", ".join(patterns)
            + "."
            + case_hint(violations, patterns)
        )
        raise OutputValidationError(message, context={"violations": str(len(violations))})


def case_hint(violations: Sequence[str], patterns: Sequence[str]) -> str:
    """Explain a pattern that misses only because of letter case.

    Matching stays case-sensitive so macOS, Linux, and Windows agree. For
    example, `Docs/**` does not allow `docs/guide.md`; this names that pair so
    the owner can correct the pattern instead of guessing.
    """
    for path in violations:
        for pattern in patterns:
            if path_allowed(path.casefold(), (pattern.casefold(),)):
                return (
                    f" Pattern {pattern} would allow {path} if letter case were ignored;"
                    " allowed-paths patterns match letter case exactly."
                )
    return ""


__all__ = [
    "baseline_ref",
    "capture_worktree",
    "case_hint",
    "changed_paths",
    "is_baseline_ref",
    "path_allowed",
    "protect_baseline",
    "require_allowed_changes",
]
