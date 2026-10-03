"""Shell-free Git subprocess adapter with Relay-owned failures."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import BinaryIO

from relay.errors import GitError


@dataclass(frozen=True, slots=True)
class GitResult:
    """Captured text and status from one Git invocation."""

    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True, slots=True)
class GitBytesResult:
    """Captured byte streams from a path-sensitive Git invocation."""

    stdout: bytes
    stderr: bytes
    returncode: int


def git_executable() -> str:
    """Resolve Git once per invocation through the inherited PATH."""
    executable = shutil.which("git")
    if executable is None:
        message = "Git could not be found on PATH."
        raise GitError(message, next_action="Install Git and make it available on PATH.")
    return executable


def _argv(repository: Path, arguments: Sequence[str]) -> list[str]:
    return [git_executable(), "-C", str(repository.resolve()), *arguments]


def run_git(
    repository: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
) -> GitResult:
    """Run Git as an argument vector and capture UTF-8-compatible output."""
    try:
        process = subprocess.run(  # noqa: S603
            _argv(repository, arguments),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        message = "Git could not be started."
        raise GitError(message, context={"project": str(repository)}) from None
    result = GitResult(process.stdout, process.stderr, process.returncode)
    if check and result.returncode != 0:
        message = "Git could not complete the requested repository operation."
        raise GitError(
            message,
            context={"project": str(repository)},
            next_action="Inspect the local Relay log and repository state.",
        )
    return result


def run_git_bytes(
    repository: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
) -> GitBytesResult:
    """Capture raw bytes when Git emits NUL-separated filesystem paths."""
    try:
        process = subprocess.run(  # noqa: S603
            _argv(repository, arguments),
            check=False,
            capture_output=True,
        )
    except OSError:
        message = "Git could not be started."
        raise GitError(message, context={"project": str(repository)}) from None
    result = GitBytesResult(process.stdout, process.stderr, process.returncode)
    if check and result.returncode != 0:
        message = "Git could not complete the requested repository operation."
        raise GitError(message, context={"project": str(repository)})
    return result


def run_git_to_file(
    repository: Path,
    arguments: Sequence[str],
    output: BinaryIO,
) -> None:
    """Stream potentially large Git output to a file instead of memory."""
    try:
        process = subprocess.run(  # noqa: S603
            _argv(repository, arguments),
            check=False,
            stdout=output,
            stderr=subprocess.PIPE,
        )
    except OSError:
        message = "Git could not be started while preserving attempt evidence."
        raise GitError(message, context={"project": str(repository)}) from None
    if process.returncode != 0:
        message = "Git could not produce retained attempt evidence."
        raise GitError(
            message,
            context={"project": str(repository)},
            next_action="Inspect the local Relay log before changing the worktree.",
        )


def git_stdout(repository: Path, arguments: Sequence[str]) -> str:
    """Return captured stdout with only Git's trailing line ending removed."""
    return run_git(repository, arguments).stdout.rstrip("\r\n")


__all__ = [
    "GitBytesResult",
    "GitResult",
    "git_executable",
    "git_stdout",
    "run_git",
    "run_git_bytes",
    "run_git_to_file",
]
