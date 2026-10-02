"""Cross-platform central storage paths and containment checks."""

from __future__ import annotations

import heapq
import os
from pathlib import Path
import re
import sys

from platformdirs import PlatformDirs

from .constants import (
    APP_NAME,
    APPLICATION_LOG_RETAINED_PROCESSES,
    WINDOWS_ERROR_INVALID_PARAMETER,
    WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION,
    WINDOWS_PROCESS_STILL_ACTIVE,
)
from .errors import PathSafetyError

_DIRS: PlatformDirs = PlatformDirs(appname=APP_NAME, appauthor=False, roaming=False)


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


def _application_log_base() -> Path:
    override = os.environ.get("RELAY_LOG_PATH")
    return Path(override) if override else log_dir() / "relay.log"


def application_log_path() -> Path:
    """Give each process its own file: `relay.log`, PID 42 -> `relay-42.log`."""
    base = _application_log_base()
    return base.with_name(f"{base.stem}-{os.getpid()}{base.suffix}")


def application_log_files() -> tuple[Path, ...]:
    """Include process files, rotations, and the former shared log for cleanup."""
    base = _application_log_base()
    return tuple(
        dict.fromkeys(
            (
                base,
                *base.parent.glob(f"{base.name}.*"),
                *base.parent.glob(f"{base.stem}-*{base.suffix}*"),
            )
        )
    )


def _windows_process_alive(pid: int) -> bool:
    """Query process state without sending a Windows termination signal."""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    exit_status = kernel.GetExitCodeProcess
    exit_status.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    exit_status.restype = wintypes.BOOL
    close_handle = kernel.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = open_process(WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denial or an unknown query failure cannot prove the PID is dead.
        return ctypes.get_last_error() != WINDOWS_ERROR_INVALID_PARAMETER
    try:
        code = wintypes.DWORD()
        if not exit_status(handle, ctypes.byref(code)):
            return True
        return code.value == WINDOWS_PROCESS_STILL_ACTIVE
    finally:
        close_handle(handle)


def _process_alive(pid: int) -> bool:
    """Keep files for live or unverifiable PIDs; never terminate a process."""
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):
        return True
    return True


def prune_application_logs() -> None:
    """Keep recent inactive groups; `relay-42.log.1` belongs to PID 42.

    The former shared `relay.log` and names such as `relay-other.log` are left
    alone. Live or unverifiable PIDs retain all their current files.
    """
    base = _application_log_base()
    pattern = re.compile(rf"{re.escape(base.stem)}-([1-9]\d*){re.escape(base.suffix)}(?:\.\d+)?")
    groups = {}
    for path in application_log_files():
        match = pattern.fullmatch(path.name)
        if match is not None:
            groups.setdefault(int(match.group(1)), []).append(path)
    inactive = {}
    for pid, paths in groups.items():
        if _process_alive(pid):
            continue
        try:
            metadata = [path.stat() for path in paths]
        except OSError:
            continue
        inactive[pid] = (
            max(info.st_mtime_ns for info in metadata),
            paths,
            any(info.st_size for info in metadata),
        )
    # A fixed-size heap selects retained groups in linear time in the file count.
    retained = set(
        heapq.nlargest(
            APPLICATION_LOG_RETAINED_PROCESSES,
            (pid for pid, (_modified, _paths, nonempty) in inactive.items() if nonempty),
            key=lambda pid: inactive[pid][0],
        )
    )
    for pid, (_modified, paths, _nonempty) in inactive.items():
        if pid in retained or _process_alive(pid):
            continue
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # Retention must not prevent commands from running on a locked file.
                continue


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
