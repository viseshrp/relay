"""Bounded disk metadata reads for project storage controls."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from relay.errors import PathSafetyError
from relay.paths import safe_resolve, worktrees_dir


@dataclass(frozen=True, slots=True)
class DirectoryUsage:
    bytes: int
    files: int
    directories: int
    truncated: bool


def measure_working_copies(
    paths: tuple[str, ...], *, maximum_entries: int = 50000
) -> DirectoryUsage:
    """Count metadata under retained roots without following inner symlinks."""
    size = files = directories = visited = 0
    seen: set[Path] = set()
    stack: list[Path] = []
    for value in paths:
        if not value:
            continue
        path = safe_resolve(worktrees_dir(), value)
        if path == worktrees_dir().resolve():
            continue
        if path.is_dir() and path not in seen:
            stack.append(path)
            seen.add(path)
            directories += 1
    while stack:
        path = stack.pop()
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if visited >= maximum_entries:
                        return DirectoryUsage(size, files, directories, True)
                    visited += 1
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            child = safe_resolve(worktrees_dir(), entry.path)
                        except PathSafetyError:
                            continue
                        # Windows junctions are directories, not ordinary symlinks.
                        if child != Path(entry.path):
                            continue
                        if child not in seen:
                            stack.append(child)
                            seen.add(child)
                    elif entry.is_file(follow_symlinks=False):
                        size += entry.stat(follow_symlinks=False).st_size
                        files += 1
        except OSError:
            return DirectoryUsage(size, files, directories, True)
    return DirectoryUsage(size, files, directories, False)
