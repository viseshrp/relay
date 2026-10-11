"""Bounded directory discovery within the local owner's home folder."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from heapq import nsmallest
import json
from pathlib import Path

from relay.constants import API_MAX_PAGE, API_MAX_PAGE_BYTES
from relay.errors import ConfigError, PathSafetyError
from relay.paths import safe_resolve


@dataclass(frozen=True, slots=True)
class FolderEntry:
    name: str
    path: str
    repository: bool


@dataclass(frozen=True, slots=True)
class FolderListing:
    root: str
    path: str
    parent: str | None
    folders: list[FolderEntry]
    next: str | None


def _home_directory() -> Path:
    return Path.home()


def browse_folders(
    path: str | None = None, *, since: str = "", limit: int = API_MAX_PAGE
) -> FolderListing:
    """List directories after resolving symlinks, without reading file contents."""
    if len(path or "") > 4096 or len(since) > 1024:
        message = "The folder path or cursor is too long."
        raise ConfigError(message)
    root = _home_directory().resolve()
    try:
        directory = safe_resolve(root, Path(path).expanduser() if path else root)
    except RuntimeError:
        message = "Relay cannot resolve this folder. Choose another directory."
        raise ConfigError(message) from None
    if not directory.is_dir():
        message = "Choose an existing directory inside your home folder."
        raise ConfigError(message)
    bounded = min(max(limit, 1), API_MAX_PAGE)

    def entries() -> Iterator[FolderEntry]:
        try:
            for candidate in directory.iterdir():
                if (candidate.name.casefold(), candidate.name) <= (since.casefold(), since):
                    continue
                try:
                    resolved = safe_resolve(root, candidate)
                    if resolved.is_dir():
                        yield FolderEntry(
                            candidate.name, str(resolved), (resolved / ".git").exists()
                        )
                except (PathSafetyError, OSError, RuntimeError):
                    continue
        except OSError:
            message = "Relay cannot list this folder. Choose another directory."
            raise ConfigError(message) from None

    candidates = nsmallest(
        bounded + 1, entries(), key=lambda entry: (entry.name.casefold(), entry.name)
    )
    folders: list[FolderEntry] = []
    used = 0
    for entry in candidates[:bounded]:
        size = len(json.dumps(asdict(entry)).encode("utf-8"))
        if used + size > API_MAX_PAGE_BYTES // 2:
            break
        used += size
        folders.append(entry)
    more = len(candidates) > len(folders)
    return FolderListing(
        str(root),
        str(directory),
        None if directory == root else str(directory.parent),
        folders,
        folders[-1].name if more and folders else None,
    )


def inspect_folder(path: str) -> dict[str, object]:
    """Validate a candidate under the same boundary as the folder browser."""
    from relay.vcs.git import run_git

    directory = Path(browse_folders(path, limit=1).path)
    result = run_git(directory, ["rev-parse", "--show-toplevel"], check=False)
    repository = result.returncode == 0
    return {
        "path": str(directory),
        "repository": repository,
        "git_root": result.stdout.strip() if repository else None,
        "message": "Git repository ready to open."
        if repository
        else "This folder is not a Git repository. Initialize Git here to open it.",
    }


def initialize_git_folder(path: str) -> dict[str, object]:
    """Initialize Git only after an explicit owner action, preserving existing files."""
    from relay.vcs.git import run_git

    candidate = inspect_folder(path)
    if not candidate["repository"]:
        run_git(Path(str(candidate["path"])), ["init"])
    return inspect_folder(path)


def common_repositories() -> list[FolderEntry]:
    """Discover at most 100 immediate repositories in common development folders."""
    root = _home_directory().resolve()
    found: dict[str, FolderEntry] = {}
    for relative in ("Documents/GitHub", "GitHub", "Code", "Projects", "Developer", "src"):
        try:
            listing = browse_folders(str(root / relative), limit=25)
        except (ConfigError, PathSafetyError, OSError):
            continue
        for entry in listing.folders:
            if entry.repository and len(found) < 100:
                found[entry.path] = entry
    return sorted(found.values(), key=lambda entry: (entry.name.casefold(), entry.path))
