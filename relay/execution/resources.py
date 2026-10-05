"""Private attempt scratch space with exact ownership checks for cleanup."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid

from relay.constants import EVENT_MAX_PAYLOAD_BYTES
from relay.errors import PathSafetyError, PersistenceError
from relay.paths import data_dir, ensure_private_dir

_MARKER = ".relay-resource-owner.json"
_VERSION = 1


def _linked(path: Path) -> bool:
    """Treat Windows junctions and symlinks as links, including on Python 3.10."""
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    except OSError:
        message = "Relay could not verify ownership of a temporary resource path."
        raise PathSafetyError(message) from None
    return path.is_symlink() or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _root(run_id: str) -> Path:
    try:
        canonical = str(uuid.UUID(run_id))
    except ValueError:
        message = "The run resource identifier is invalid."
        raise PathSafetyError(message) from None
    return data_dir() / "resources" / canonical


@dataclass(frozen=True, slots=True)
class AttemptResources:
    """Folders created by Relay, separate from code, evidence, and personal profiles."""

    directory: Path
    run_id: str
    attempt_id: str
    token: str

    def environment(self) -> dict[str, str]:
        """Point child temporary storage at this attempt, preserving other environment values."""
        result = os.environ.copy()
        result.update(
            {
                "TMPDIR": str(self.directory / "temp"),
                "TMP": str(self.directory / "temp"),
                "TEMP": str(self.directory / "temp"),
                "RELAY_BROWSER_PROFILE_DIR": str(self.directory / "browser-profiles"),
                "RELAY_RUN_ID": self.run_id,
                "RELAY_ATTEMPT_ID": self.attempt_id,
            }
        )
        return result

    def cleanup(self) -> None:
        """Delete only this allocation; a replaced or linked directory is never followed."""
        _remove_owned(self.directory, self.run_id, expected_token=self.token)
        # Another attempt, or an unowned file, may still need the run directory.
        with contextlib.suppress(OSError):
            self.directory.parent.rmdir()


def allocate_attempt_resources(run_id: str, attempt_id: str) -> AttemptResources:
    """Allocate new scratch/profile folders without accepting an owner-supplied path."""
    root = _root(run_id)
    if _linked(root) or _linked(root.parent):
        message = "The run resource directory was replaced by a link."
        raise PathSafetyError(message)
    directory = None
    try:
        ensure_private_dir(root)
        directory = Path(tempfile.mkdtemp(prefix="attempt-", dir=root))
        token = str(uuid.uuid4())
        (directory / _MARKER).write_text(
            json.dumps(
                {
                    "version": _VERSION,
                    "run": run_id,
                    "attempt": attempt_id,
                    "token": token,
                }
            ),
            encoding="utf-8",
        )
        ensure_private_dir(directory / "temp")
        ensure_private_dir(directory / "browser-profiles")
    except OSError:
        if directory is not None and not _linked(directory):
            with contextlib.suppress(OSError):
                shutil.rmtree(directory)
        message = "Relay could not allocate private run resources."
        raise PersistenceError(message) from None
    return AttemptResources(directory, run_id, attempt_id, token)


def _remove_owned(
    path: Path,
    run_id: str,
    *,
    expected_token: str | None = None,
    eligible_attempts: frozenset[str] | None = None,
) -> bool:
    root = _root(run_id)
    if _linked(root) or _linked(root.parent) or _linked(path) or path.parent != root:
        message = "Relay refused cleanup because a resource path no longer matches its allocation."
        raise PathSafetyError(message)
    if not path.exists():
        return False
    marker = path / _MARKER
    if _linked(marker) or not marker.is_file():
        return False
    try:
        # A marker is a small identity record, never a user document or arbitrary manifest path.
        with marker.open("r", encoding="utf-8") as stream:
            owner = json.loads(stream.read(EVENT_MAX_PAYLOAD_BYTES))
        if (
            not isinstance(owner, dict)
            or owner.get("version") != _VERSION
            or owner.get("run") != run_id
        ):
            return False
        if eligible_attempts is not None and owner.get("attempt") not in eligible_attempts:
            return False
        if not isinstance(owner.get("token"), str) or (
            expected_token is not None and owner["token"] != expected_token
        ):
            return False
        uuid.UUID(owner["token"])
        # rmtree removes inner symlinks themselves; it does not traverse their targets.
        shutil.rmtree(path)
    except (ValueError, UnicodeError):
        return False
    except OSError:
        message = "Relay could not remove its temporary run resources."
        raise PersistenceError(message, context={"run": run_id}) from None
    return True


def cleanup_run_resources(run_id: str, *, eligible_attempts: frozenset[str] | None = None) -> int:
    """Remove marked allocations for one finished run, leaving every unmarked file alone."""
    root = _root(run_id)
    if not root.exists() and not root.is_symlink():
        return 0
    if _linked(root) or _linked(root.parent):
        message = "Relay refused cleanup of a linked run resource directory."
        raise PathSafetyError(message)
    try:
        removed = sum(
            _remove_owned(path, run_id, eligible_attempts=eligible_attempts)
            for path in root.iterdir()
            if path.is_dir()
        )
        with contextlib.suppress(OSError):
            root.rmdir()
    except OSError:
        message = "Relay could not inspect the run's temporary resources."
        raise PersistenceError(message) from None
    return removed
