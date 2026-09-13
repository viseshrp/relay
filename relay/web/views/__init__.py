"""Shared HTTP parsing and Relay-owned error rendering."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
import json
import logging
import os
from pathlib import Path
from typing import Concatenate, ParamSpec

from django.core.exceptions import RequestDataTooBig
from django.http import HttpRequest, JsonResponse
from django.http.response import HttpResponseBase

from relay.errors import ConfigError, RelayError
from relay.projects.discovery import discover_relay_root
from relay.projects.service import ProjectRecord, register_current_project

P = ParamSpec("P")
LOGGER = logging.getLogger(__name__)


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
        raise ConfigError("This endpoint requires an application/json request body.")
    try:
        value: object = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ConfigError("The request body is not valid JSON.") from None
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigError("The request body must be a JSON object.")
    return value


def required_text(body: dict[str, object], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty string.")
    return value


def optional_text(body: dict[str, object], field: str) -> str | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty string when supplied.")
    return value


def required_object(body: dict[str, object], field: str) -> dict[str, object]:
    value = body.get(field)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigError(f"{field} must be a JSON object.")
    return value


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
    "current_project",
    "json_body",
    "optional_text",
    "required_object",
    "required_text",
]
