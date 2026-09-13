"""Git repository and nearest-project discovery."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from relay.errors import ProjectDiscoveryError


def git_root(start: Path | None = None) -> Path:
    """Return the containing Git worktree root without invoking a shell."""
    location = (start or Path.cwd()).resolve()
    if location.is_file():
        location = location.parent
    executable = shutil.which("git")
    if executable is None:
        message = "Git could not be found on PATH."
        raise ProjectDiscoveryError(
            message,
            next_action="Install Git and ensure it is available on PATH.",
        )
    try:
        # The executable is resolved by PATH, arguments are isolated, and no shell is used.
        result = subprocess.run(  # noqa: S603
            [executable, "-C", str(location), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        message = "Git could not be started."
        raise ProjectDiscoveryError(
            message,
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
