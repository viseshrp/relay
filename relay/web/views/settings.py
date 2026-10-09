"""Owner settings HTTP adapters; validation and resolution live in services."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET, require_POST

from relay.owner_settings import (
    effective_config,
    read_project_settings,
    read_settings,
    save_project_settings,
    save_settings,
)
from relay.paths import config_dir, data_dir, global_prompts_dir, log_dir
from relay.web.auth import owner_required, owner_username
from relay.web.settings_repository import DjangoSettingsStore

from . import api_errors, current_project, json_body, required_object, required_text


def _context(request: HttpRequest) -> dict[str, object]:
    return {
        "active_login_required": settings.RELAY_LOGIN_REQUIRED,
        "username": owner_username(request),
        "paths": {
            "config": str(config_dir()),
            "data": str(data_dir()),
            "logs": str(log_dir()),
            "prompts": str(global_prompts_dir()),
        },
    }


@api_errors
@owner_required
@require_GET
def read_owner_settings(request: HttpRequest) -> HttpResponse:
    return JsonResponse({**read_settings(), **_context(request)})


@api_errors
@owner_required
@require_POST
def write_owner_settings(request: HttpRequest) -> HttpResponse:
    body = json_body(request)
    return JsonResponse(
        {
            **save_settings(body.get("settings"), required_text(body, "revision")),
            **_context(request),
        }
    )


def owner_settings(request: HttpRequest) -> HttpResponseBase:
    return (
        write_owner_settings(request) if request.method == "POST" else read_owner_settings(request)
    )


@api_errors
@owner_required
@require_GET
def read_project_defaults(request: HttpRequest) -> HttpResponse:
    _root, project = current_project(request)
    return JsonResponse(read_project_settings(DjangoSettingsStore(), project.id))


@api_errors
@owner_required
@require_POST
def write_project_defaults(request: HttpRequest) -> HttpResponse:
    _root, project = current_project(request)
    body = json_body(request)
    if body.get("preview") is True:
        config = effective_config(
            DjangoSettingsStore(), project.id, required_object(body, "overrides")
        )
        return JsonResponse(
            {
                "effective": {
                    **config.to_dict(),
                    "workflow_defaults": config.workflow_defaults.model_dump(mode="json"),
                }
            }
        )
    return JsonResponse(
        save_project_settings(
            DjangoSettingsStore(),
            project.id,
            body.get("overrides"),
            required_text(body, "revision"),
        )
    )


def project_defaults(request: HttpRequest) -> HttpResponseBase:
    return (
        write_project_defaults(request)
        if request.method == "POST"
        else read_project_defaults(request)
    )


@api_errors
@owner_required
@require_GET
def storage_usage(request: HttpRequest) -> HttpResponse:
    _root, project = current_project(request)
    return JsonResponse(DjangoSettingsStore().storage_usage(project.id))
