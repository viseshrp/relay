"""Git repository and nearest-project discovery."""

from __future__ import annotations

import logging
from pathlib import Path

from relay.errors import GitError, ProjectDiscoveryError
from relay.vcs.git import run_git

LOGGER: logging.Logger = logging.getLogger(__name__)


def git_root(start: Path | None = None) -> Path:
    """Return the Git worktree root for an owner-selected directory."""
    location = start if start is not None else Path.cwd()
    try:
        result = run_git(location, ["rev-parse", "--show-toplevel"], check=False)
    except GitError as error:
        LOGGER.exception("Git project discovery failed", extra={"project": str(location)})
        raise ProjectDiscoveryError(
            error.message,
            next_action="Install Git and ensure it is available on PATH.",
        ) from None
    if result.returncode != 0:
        message = f"{location} is not inside a Git worktree."
        raise ProjectDiscoveryError(
            message,
            context={"project": str(location)},
            next_action="Run this command inside a Git repository.",
        )
    return Path(result.stdout.strip()).resolve()


def discover_relay_root(start: Path | None = None) -> Path:
    """Find the nearest parent containing a ``.relay`` directory."""
    location = (start or Path.cwd()).resolve()
    if location.is_file():
        location = location.parent
    repository = git_root(location)
    for candidate in (location, *location.parents):
        relay_root = candidate / ".relay"
        if relay_root.is_dir():
            return relay_root.resolve()
        if candidate == repository:
            break
    message = f"No .relay directory was found from {location} to {repository}."
    raise ProjectDiscoveryError(
        message,
        context={"project": str(repository)},
        next_action="Run relay init at the repository root.",
    )
