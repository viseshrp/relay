"""Real SQLite lock gates and transaction measurements for isolated tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any
from unittest.mock import patch

from django.db.backends.sqlite3.base import DatabaseWrapper, SQLiteCursorWrapper


@contextmanager
def hold_write_lock(database: Path) -> Iterator[None]:
    """Reserve the actual writer lock until the caller releases its gate."""
    connection = sqlite3.connect(database, isolation_level=None, timeout=0)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield
        connection.execute("COMMIT")
    finally:
        connection.close()


@dataclass
class SqliteWriteProbe:
    """Measure explicit transaction waits separately from time holding the lock."""

    transactions: int = 0
    empty_transactions: int = 0
    autocommit_writes: int = 0
    failed_begins: int = 0
    lock_waits: list[float] = field(default_factory=list)
    lock_holds: list[float] = field(default_factory=list)
    _active: dict[int, tuple[float, bool]] = field(default_factory=dict)
    _guard: Any = field(default_factory=threading.Lock)
    _patches: ExitStack = field(default_factory=ExitStack)

    def __enter__(self) -> SqliteWriteProbe:
        execute = SQLiteCursorWrapper.execute
        executemany = SQLiteCursorWrapper.executemany
        commit = DatabaseWrapper._commit
        rollback = DatabaseWrapper._rollback

        def statement(cursor: Any, sql: str, parameters: Any = None) -> Any:
            return self._execute(cursor, sql, parameters, execute)

        def statements(cursor: Any, sql: str, parameters: Any) -> Any:
            return self._execute(cursor, sql, parameters, executemany)

        def finish(connection: Any) -> None:
            try:
                commit(connection)
            finally:
                self._finish(connection, committed=True)

        def abort(connection: Any) -> None:
            try:
                rollback(connection)
            finally:
                self._finish(connection, committed=False)

        self._patches.enter_context(patch.object(SQLiteCursorWrapper, "execute", statement))
        self._patches.enter_context(patch.object(SQLiteCursorWrapper, "executemany", statements))
        self._patches.enter_context(patch.object(DatabaseWrapper, "_commit", finish))
        self._patches.enter_context(patch.object(DatabaseWrapper, "_rollback", abort))
        return self

    def __exit__(self, *args: object) -> None:
        self._patches.close()

    def _execute(self, cursor: Any, sql: str, parameters: Any, operation: Any) -> Any:
        command = sql.strip().upper()
        beginning = command.startswith("BEGIN IMMEDIATE")
        writing = command.split(maxsplit=1)[0] in {"INSERT", "UPDATE", "DELETE", "REPLACE"}
        key = id(cursor.connection)
        started = time.monotonic()
        try:
            result = operation(cursor, sql, parameters)
        except sqlite3.Error:
            if beginning:
                with self._guard:
                    self.failed_begins += 1
                    self.lock_waits.append(time.monotonic() - started)
            raise
        with self._guard:
            if beginning:
                acquired = time.monotonic()
                self.transactions += 1
                self.lock_waits.append(acquired - started)
                self._active[key] = (acquired, False)
            elif writing:
                if key in self._active:
                    acquired, _ = self._active[key]
                    self._active[key] = (acquired, True)
                else:
                    self.autocommit_writes += 1
        return result

    def _finish(self, connection: Any, *, committed: bool) -> None:
        with self._guard:
            current = self._active.pop(id(connection.connection), None)
            if current is not None:
                acquired, written = current
                self.lock_holds.append(time.monotonic() - acquired)
                if committed and not written:
                    self.empty_transactions += 1

    def report(self) -> dict[str, int | float]:
        """Return small serializable measurements for pytest evidence."""
        return {
            "transactions": self.transactions,
            "empty_transactions": self.empty_transactions,
            "autocommit_writes": self.autocommit_writes,
            "failed_begins": self.failed_begins,
            "max_lock_wait": max(self.lock_waits, default=0.0),
            "max_lock_hold": max(self.lock_holds, default=0.0),
        }
