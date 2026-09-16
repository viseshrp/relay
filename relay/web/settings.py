"""Django settings for Relay's loopback-only local application."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import time

from relay.constants import API_MAX_PAGE_BYTES, DB_BUSY_TIMEOUT_MS
from relay.paths import application_log_path, data_dir, database_path, log_dir

BASE_DIR = Path(__file__).resolve().parent


def _read_or_create_secret_key() -> str:
    """Persist one installation key without shipping a default credential."""
    root = data_dir(create=True)
    target = root / "django-secret-key"
    for _attempt in range(10):
        try:
            key = target.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            key = secrets.token_urlsafe(48)
            try:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
            return key
        if len(key) >= 48:
            return key
        # A concurrent first start may own the file but not have flushed it yet.
        time.sleep(0.01)
    message = f"Relay could not read a complete secret key at {target}."
    raise RuntimeError(message)


SECRET_KEY: str = os.environ.get("RELAY_DJANGO_SECRET_KEY") or _read_or_create_secret_key()
DEBUG = False
ALLOWED_HOSTS: list[str] = ["127.0.0.1", "localhost", "[::1]"]

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
        "OPTIONS": {"timeout": DB_BUSY_TIMEOUT_MS / 1_000},
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

log_override: str | None = os.environ.get("RELAY_LOG_PATH")
resolved_log_path = Path(log_override) if log_override else application_log_path()
resolved_log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
if log_override is None:
    log_dir(create=True)
LOGGING: dict[str, object] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "relay": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(resolved_log_path),
            "formatter": "relay",
            "maxBytes": 5_000_000,
            "backupCount": 3,
        }
    },
    "root": {"handlers": ["file"], "level": "INFO"},
}
