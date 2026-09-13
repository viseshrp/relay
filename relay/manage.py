"""Django management entry point and cross-platform migration serialization."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import socket
import sys
import time
from types import TracebackType
from typing import BinaryIO

from relay.constants import MIGRATION_LOCK_POLL_SECONDS, MIGRATION_LOCK_WAIT_SECONDS
from relay.errors import PersistenceError
from relay.paths import data_dir, migration_lock_path


class MigrationLock:
    """Serialize migrations with a kernel lock that dies with its process."""

    path: Path
    timeout: float
    _stream: BinaryIO | None

    def __init__(self, path: Path, *, timeout: float = MIGRATION_LOCK_WAIT_SECONDS) -> None:
        self.path = path
        self.timeout = timeout
        self._stream = None

    def __enter__(self) -> MigrationLock:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._acquire(stream)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    stream.close()
                    raise
                if time.monotonic() >= deadline:
                    stream.close()
                    message = "Timed out waiting for Relay's migration lock."
                    raise PersistenceError(
                        message,
                        next_action="Wait for the other Relay instance to finish starting.",
                    ) from None
                time.sleep(MIGRATION_LOCK_POLL_SECONDS)
        metadata = json.dumps(
            {"pid": os.getpid(), "host": socket.gethostname(), "acquired_at": time.time()}
        ).encode("utf-8")
        stream.seek(0)
        stream.truncate()
        stream.write(metadata)
        stream.flush()
        os.fsync(stream.fileno())
        self._stream = stream
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._stream is None:
            return
        self._release(self._stream)
        self._stream.close()
        self._stream = None

    @staticmethod
    def _acquire(stream: BinaryIO) -> None:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release(stream: BinaryIO) -> None:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def apply_migrations(*, verbosity: int = 0) -> None:
    """Apply all migrations while no other Relay process can migrate."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "relay.web.settings")
    database_override = os.environ.get("RELAY_DATABASE_PATH")
    lock_override = os.environ.get("RELAY_MIGRATION_LOCK_PATH")
    if database_override is None:
        data_dir(create=True)
    lock_path = Path(lock_override) if lock_override else migration_lock_path()
    try:
        import django
        from django.core.management import call_command

        django.setup()
        with MigrationLock(lock_path):
            call_command("migrate", interactive=False, verbosity=verbosity)
    except PersistenceError:
        raise
    except Exception:
        message = "Relay could not prepare its local database."
        raise PersistenceError(
            message,
            next_action="Inspect the local Relay log and verify the data directory is writable.",
        ) from None


def main(argv: list[str] | None = None) -> None:
    """Run a Django management command against Relay's settings."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "relay.web.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(argv or sys.argv)


if __name__ == "__main__":
    main()
