"""Bounded retries for explicitly selected, rollback-only database operations."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from functools import wraps
import sqlite3
import time
from typing import ParamSpec, TypeVar

from django.db import DatabaseError, connection

from relay.constants import DB_BUSY_TIMEOUT_MS

P = ParamSpec("P")
T = TypeVar("T")


def sqlite_busy(error: BaseException) -> bool:
    """Accept SQLite lock contention, preserving unrelated database failures."""
    seen: set[int] = set()
    while id(error) not in seen:
        seen.add(id(error))
        code = getattr(error, "sqlite_errorcode", None)
        if isinstance(code, int) and (code & 0xFF) == 5:  # SQLITE_BUSY, including extended codes.
            return True
        if (
            isinstance(error, sqlite3.OperationalError)
            and str(error).lower() == "database is locked"
        ):
            return True
        cause = error.__cause__ or error.__context__
        if cause is None:
            break
        error = cause
    return False


def retry_database_busy(
    operation: Callable[P, T], *, budget: float = DB_BUSY_TIMEOUT_MS / 1000
) -> Callable[P, T]:
    """Retry one DB transaction, never a provider, filesystem or Git operation.

    Callers must contain exactly one transaction and no post-commit side
    effects. A surrounding transaction owns its retries and is never replayed
    here. The SQLite busy wait is capped to the remaining total budget.
    """

    @wraps(operation)
    def retried(*args: P.args, **kwargs: P.kwargs) -> T:
        if connection.in_atomic_block:
            return operation(*args, **kwargs)
        deadline = time.monotonic() + budget
        try:
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA busy_timeout")
                original_timeout = int(cursor.fetchone()[0])
        except DatabaseError:
            # The selected adapter still owns public mapping of a database
            # outage. No business transaction has run at this point.
            return operation(*args, **kwargs)
        delay = 0.01
        try:
            while True:
                remaining = max(0.0, deadline - time.monotonic())
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"PRAGMA busy_timeout={min(original_timeout, int(remaining * 1000))}"
                    )
                try:
                    return operation(*args, **kwargs)
                except Exception as error:
                    remaining = deadline - time.monotonic()
                    if (
                        not sqlite_busy(error)
                        or connection.in_atomic_block
                        or connection.needs_rollback
                        or remaining <= 0
                    ):
                        raise
                    time.sleep(min(delay, remaining))
                    delay = min(delay * 2, 0.1)
        finally:
            with suppress(DatabaseError), connection.cursor() as cursor:
                cursor.execute(f"PRAGMA busy_timeout={original_timeout}")

    return retried
