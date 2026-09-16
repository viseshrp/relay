"""Canonical project identity independent of a process working directory."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .discovery import git_root


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    """Stable identity and display fields for one Git worktree."""

    canonical_path: str
    display_name: str
    git_root: str


def canonical_path(path: Path) -> str:
    """Normalize a real path for identity comparison.

    ``C:\\Code\\Relay`` and ``c:\\code\\relay`` both become the platform's
    normalized-case real path on Windows. POSIX case remains unchanged.
    """
    return os.path.normcase(os.path.realpath(path))


def identify_project(start: Path | None = None) -> ProjectIdentity:
    """Build canonical identity fields for the containing Git worktree."""
    root = git_root(start)
    return ProjectIdentity(
        canonical_path=canonical_path(root),
        display_name=root.name,
        git_root=canonical_path(root),
    )
