"""Explicit, materialized read snapshots on the same authoritative database."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, NoReturn

from django.db import DatabaseError, connections, models, transaction

_SNAPSHOT: ContextVar[bool] = ContextVar("relay_snapshot_reads", default=False)


class SnapshotRouter:
    def db_for_read(self, model: type[models.Model], **hints: object) -> str | None:
        del model, hints
        return "snapshot" if _SNAPSHOT.get() else None

    def db_for_write(self, model: type[models.Model], **hints: object) -> None:
        del model, hints
        if _SNAPSHOT.get():
            message = "Writes are forbidden inside a Relay read snapshot."
            raise DatabaseError(message)

    def allow_relation(self, obj1: models.Model, obj2: models.Model, **hints: object) -> bool:
        del obj1, obj2, hints
        return True

    def allow_migrate(
        self, db: str, app_label: str, model_name: str | None = None, **hints: object
    ) -> bool:
        del app_label, model_name, hints
        return db == "default"


@contextmanager
def read_snapshot() -> Iterator[None]:
    """Materialize reads before leaving this deferred, query-only WAL transaction."""
    token = _SNAPSHOT.set(True)
    try:
        with (
            connections["default"].execute_wrapper(_reject_default_query),
            transaction.atomic(using="snapshot"),
        ):
            yield
    finally:
        _SNAPSHOT.reset(token)


def _reject_default_query(
    execute: Callable[..., Any], sql: str, params: object, many: bool, context: object
) -> NoReturn:
    """An explicit `.using('default')` must not escape the read-only context."""
    del execute, sql, params, many, context
    message = "The default connection is forbidden inside a Relay read snapshot."
    raise DatabaseError(message)
