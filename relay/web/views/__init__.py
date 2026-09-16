"""Shared HTTP parsing and Relay-owned error rendering."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
import json
import logging
import os
from pathlib import Path
from typing import Concatenate, ParamSpec
import uuid

from django.core.exceptions import RequestDataTooBig
from django.http import HttpRequest, JsonResponse
from django.http.response import HttpResponseBase

from relay.errors import ConfigError, ProjectDiscoveryError, RelayError
from relay.projects.discovery import discover_relay_root
from relay.projects.service import ProjectRecord, register_current_project

P = ParamSpec("P")
LOGGER = logging.getLogger(__name__)
_MAX_BIGINT_ID = (1 << 63) - 1


def api_errors(
    view: Callable[Concatenate[HttpRequest, P], HttpResponseBase],
) -> Callable[Concatenate[HttpRequest, P], HttpResponseBase]:
    """Map all public failures to a stable envelope without leaking internals."""

    @wraps(view)
    def wrapped(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> HttpResponseBase:
        try:
            return view(request, *args, **kwargs)
        except RelayError as error:
            return JsonResponse(error.to_envelope(), status=error.http_status)
        except RequestDataTooBig:
            error = ConfigError("The request body exceeds Relay's byte limit.")
            return JsonResponse(error.to_envelope(), status=error.http_status)
        except Exception:
            LOGGER.exception("Unhandled Relay HTTP endpoint failure", extra={"path": request.path})
            return JsonResponse(
                {
                    "code": "internal_error",
                    "message": "Relay could not complete the request.",
                    "context": {},
                },
                status=500,
            )

    return wrapped


def json_body(request: HttpRequest) -> dict[str, object]:
    """Decode one JSON object without coercing field values."""
    if request.content_type != "application/json":
        message = "This endpoint requires an application/json request body."
        raise ConfigError(message)
    try:
        value: object = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        message = "The request body is not valid JSON."
        raise ConfigError(message) from None
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        message = "The request body must be a JSON object."
        raise ConfigError(message)
    return value


def required_text(body: dict[str, object], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value:
        message = f"{field} must be a non-empty string."
        raise ConfigError(message)
    return value


def optional_text(body: dict[str, object], field: str) -> str | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        message = f"{field} must be a non-empty string when supplied."
        raise ConfigError(message)
    return value


def required_object(body: dict[str, object], field: str) -> dict[str, object]:
    value = body.get(field)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        message = f"{field} must be a JSON object."
        raise ConfigError(message)
    return value


def canonical_uuid(value: str, *, resource: str) -> str:
    """Normalize public UUIDs before ORM use.

    For example, ``550E8400E29B41D4A716446655440000`` becomes
    ``550e8400-e29b-41d4-a716-446655440000``. Non-UUID text returns the same
    resource-not-found contract as an unknown canonical identifier.
    """
    try:
        return str(uuid.UUID(value))
    except ValueError:
        message = f"The requested {resource} does not exist."
        raise ProjectDiscoveryError(message, context={resource: value}) from None


def canonical_record_id(value: str, *, resource: str) -> str:
    """Normalize a public database ID without allowing numeric coercion.

    For example, ``00042`` becomes ``42``. Signs, decimals, zero, and values
    above SQLite's signed 64-bit integer range use the not-found contract.
    """
    valid_digits = value.isascii() and value.isdigit()
    parsed = int(value) if valid_digits and len(value) <= 19 else 0
    if parsed < 1 or parsed > _MAX_BIGINT_ID:
        message = f"The requested {resource} does not exist."
        raise ProjectDiscoveryError(message, context={resource: value})
    return str(parsed)


def current_project() -> tuple[Path, ProjectRecord]:
    """Resolve the one repository owned by this `relay up` process."""
    from relay.web.repositories import DjangoProjectStore

    start_override = os.environ.get("RELAY_PROJECT_ROOT")
    start = Path(start_override) if start_override is not None else Path.cwd()
    relay_root = discover_relay_root(start)
    record = register_current_project(DjangoProjectStore(), relay_root.parent)
    return relay_root, record


__all__ = [
    "api_errors",
    "canonical_record_id",
    "canonical_uuid",
    "current_project",
    "json_body",
    "optional_text",
    "required_object",
    "required_text",
]
