"""Cross-platform central storage paths and containment checks."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import PlatformDirs

from .constants import APP_NAME
from .errors import PathSafetyError

_DIRS = PlatformDirs(appname=APP_NAME, appauthor=False, roaming=False)


def ensure_private_dir(path: Path) -> Path:
    """Create a central Relay directory with owner-only POSIX permissions."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def config_dir(*, create: bool = False) -> Path:
    """Return the owner configuration directory."""
    path = Path(_DIRS.user_config_dir)
    return ensure_private_dir(path) if create else path


def data_dir(*, create: bool = False) -> Path:
    """Return the durable database, snapshot, artifact, and worktree directory."""
    path = Path(_DIRS.user_data_dir)
    return ensure_private_dir(path) if create else path


def log_dir(*, create: bool = False) -> Path:
    """Return the local application and supervisor log directory."""
    path = Path(_DIRS.user_log_dir)
    return ensure_private_dir(path) if create else path


def global_prompts_dir(*, create: bool = False) -> Path:
    """Return the root allowed for owner-global prompt files."""
    path = config_dir(create=create) / "prompts"
    return ensure_private_dir(path) if create else path


def settings_path() -> Path:
    """Return the owner-controlled JSON settings path."""
    return config_dir() / "settings.json"


def database_path() -> Path:
    """Return the authoritative Relay SQLite database path."""
    return data_dir() / "relay.db"


def huey_database_path() -> Path:
    """Return the separate Huey dispatch database path."""
    return data_dir() / "huey.db"


def snapshots_dir(*, create: bool = False) -> Path:
    """Return the immutable snapshot support directory."""
    path = data_dir(create=create) / "snapshots"
    return ensure_private_dir(path) if create else path


def artifacts_dir(*, create: bool = False) -> Path:
    """Return the retained artifact and attempt-evidence directory."""
    path = data_dir(create=create) / "artifacts"
    return ensure_private_dir(path) if create else path


def worktrees_dir(*, create: bool = False) -> Path:
    """Return the isolated Git worktree directory."""
    path = data_dir(create=create) / "worktrees"
    return ensure_private_dir(path) if create else path


def registry_cache_dir(*, create: bool = False) -> Path:
    """Return the validated ACP registry cache directory."""
    path = data_dir(create=create) / "registry-cache"
    return ensure_private_dir(path) if create else path


def application_log_path() -> Path:
    """Return the main local log path."""
    return log_dir() / "relay.log"


def shutdown_marker_path() -> Path:
    """Return the durable graceful-shutdown marker path."""
    return data_dir() / "shutdown.requested"


def migration_lock_path() -> Path:
    """Return the exclusive first-use migration lock path."""
    return data_dir() / "migrate.lock"


def safe_resolve(root: Path, candidate: str | os.PathLike[str]) -> Path:
    """Resolve a path and reject escapes after symlink traversal.

    For example, resolving ``prompts/review.md`` under ``/repo/.relay`` may
    produce ``/repo/.relay/prompts/review.md``. A candidate such as
    ``../secret.md`` resolves outside that root and is rejected.
    """
    resolved_root = Path(os.path.realpath(root))
    resolved_candidate = Path(os.path.realpath(resolved_root / candidate))
    try:
        contained = os.path.commonpath((resolved_root, resolved_candidate)) == str(resolved_root)
    except ValueError:
        # Windows paths on different drives have no common path.
        contained = False
    if not contained:
        message = "The requested path escapes its allowed Relay directory."
        raise PathSafetyError(
            message,
            context={"root": str(resolved_root)},
            next_action="Choose a path inside the allowed directory.",
        )
    return resolved_candidate
