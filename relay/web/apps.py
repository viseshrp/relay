"""Django application configuration and SQLite connection policy."""

from __future__ import annotations

from django.apps import AppConfig


class RelayWebConfig(AppConfig):
    """Register Relay's persistence adapter."""

    default_auto_field: str = "django.db.models.BigAutoField"
    name: str = "relay.web"
    label: str = "relay_web"
