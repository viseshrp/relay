"""Django settings for Relay's loopback-only local application."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import secrets
import tempfile

from relay.constants import (
    API_MAX_PAGE_BYTES,
    APPLICATION_LOG_BACKUP_COUNT,
    APPLICATION_LOG_MAX_BYTES,
    DB_BUSY_TIMEOUT_MS,
    LOOPBACK_HOSTS,
    SECRET_KEY_TOKEN_BYTES,
)
from relay.errors import PersistenceError
from relay.paths import (
    application_log_path,
    data_dir,
    database_path,
    log_dir,
    prune_application_logs,
)

BASE_DIR = Path(__file__).resolve().parent


def _read_or_create_secret_key() -> str:
    """Publish a complete key atomically; a stored `key + '\n'` reads as `key`."""
    temporary = None
    try:
        root = data_dir(create=True)
        target = root / "django-secret-key"
        try:
            key = target.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            # Same-directory hard linking publishes a fully flushed file without
            # replacing another process's winner or exposing a partially written key.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=root, prefix=".django-secret-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(secrets.token_urlsafe(SECRET_KEY_TOKEN_BYTES))
                stream.flush()
                os.fsync(stream.fileno())
            with contextlib.suppress(FileExistsError):
                os.link(temporary, target)
            key = target.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        message = "Relay could not prepare its installation secret key."
        raise PersistenceError(
            message, next_action="Check the Relay data directory permissions."
        ) from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                message = "Relay could not remove its temporary secret-key file."
                raise PersistenceError(
                    message, next_action="Inspect the Relay data directory."
                ) from None
    if len(key) < SECRET_KEY_TOKEN_BYTES:
        message = f"Relay could not read a complete secret key at {target}."
        raise PersistenceError(
            message, next_action="Inspect the stored secret key before restarting."
        )
    return key


SECRET_KEY: str = os.environ.get("RELAY_DJANGO_SECRET_KEY") or _read_or_create_secret_key()
DEBUG = False
# Django host validation expects brackets around IPv6, e.g. `::1` -> `[::1]`.
ALLOWED_HOSTS: list[str] = [f"[{host}]" if ":" in host else host for host in sorted(LOOPBACK_HOSTS)]

INSTALLED_APPS: list[str] = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "relay.web.apps.RelayWebConfig",
]

MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "relay.web.urls"
ASGI_APPLICATION = "relay.web.asgi.application"
TEMPLATES: list[dict[str, object]] = []

database_override: str | None = os.environ.get("RELAY_DATABASE_PATH")
DATABASES: dict[str, dict[str, object]] = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": database_override or str(database_path()),
        "OPTIONS": {
            "timeout": DB_BUSY_TIMEOUT_MS / 1_000,
            # Reserve the write lock before reads so writers honor the timeout.
            "transaction_mode": "IMMEDIATE",
            "init_command": (
                "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; "
                f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};"
            ),
        },
    }
}

AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_NAME = "relay_sessionid"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_NAME = "relay_csrftoken"
CSRF_FAILURE_VIEW = "relay.web.views.actions.csrf_failure"
DATA_UPLOAD_MAX_MEMORY_SIZE = API_MAX_PAGE_BYTES
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
CONN_MAX_AGE = 0

resolved_log_path = application_log_path()
resolved_log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
if os.environ.get("RELAY_LOG_PATH") is None:
    log_dir(create=True)
prune_application_logs()
LOGGING: dict[str, object] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "relay": {
            "()": "relay.web.logging.ContextFormatter",
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "file": {
            "class": "relay.web.logging.OwnedRotatingFileHandler",
            "filename": str(resolved_log_path),
            "formatter": "relay",
            "maxBytes": APPLICATION_LOG_MAX_BYTES,
            "backupCount": APPLICATION_LOG_BACKUP_COUNT,
            "delay": True,
        }
    },
    "root": {"handlers": ["file"], "level": "INFO"},
}
