"""Django application configuration and SQLite connection policy."""

from __future__ import annotations

from django.apps import AppConfig
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.signals import connection_created

from relay.constants import DB_BUSY_TIMEOUT_MS


def _configure_sqlite(
    sender: type[BaseDatabaseWrapper],
    connection: BaseDatabaseWrapper,
    **kwargs: object,
) -> None:
    """Enable WAL, foreign keys, and the bounded busy timeout per connection."""
    del sender, kwargs
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")


class RelayWebConfig(AppConfig):
    """Register Relay's persistence adapter and connection initialization."""

    default_auto_field: str = "django.db.models.BigAutoField"
    name: str = "relay.web"
    label: str = "relay_web"

    def ready(self) -> None:
        """Attach one idempotent SQLite configuration receiver."""
        connection_created.connect(
            _configure_sqlite,
            dispatch_uid="relay.configure_sqlite",
            weak=False,
        )
