"""Authenticated bounded reads for projects, workflows, agents, and runs."""

from __future__ import annotations

from dataclasses import asdict

from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from relay.agents.discovery import discover_agents
from relay.agents.registry import load_registry
from relay.constants import API_MAX_PAGE
from relay.errors import ConfigError
from relay.execution.state import RunStatus
from relay.projects.service import list_registered_projects
from relay.workflows.editor import read_workflow_document

from ..auth import owner_required
from ..repositories import (
    DjangoAgentStore,
    DjangoProjectStore,
    DjangoReadStore,
    DjangoWorkflowStore,
)
from . import api_errors, canonical_record_id, canonical_uuid, current_project


def _nonnegative_int(value: str | None, *, field: str, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        message = f"{field} must be an integer."
        raise ConfigError(message) from None
    if parsed < 0:
        message = f"{field} must not be negative."
        raise ConfigError(message)
    return parsed


@api_errors
@owner_required
@require_GET
def projects(request: HttpRequest) -> HttpResponse:
    del request
    records = list_registered_projects(DjangoProjectStore())
    return JsonResponse({"projects": [asdict(record) for record in records]})


@api_errors
@owner_required
@require_GET
def workflow(request: HttpRequest, key: str) -> HttpResponse:
    del request
    relay_root, project = current_project()
    document = read_workflow_document(DjangoWorkflowStore(), relay_root, project.id, key)
    return JsonResponse(
        {
            "yaml": document.yaml,
            "draft": document.draft,
            "base_hash": document.base_hash,
        }
    )


@api_errors
@owner_required
@require_GET
def agents(request: HttpRequest) -> HttpResponse:
    del request
    registry = load_registry()
    observations = DjangoAgentStore().list_model_observations()
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in observations:
        grouped.setdefault(item.agent_id, []).append(
            {
                "value": item.model_value,
                "name": item.model_name,
                "config_id": item.config_id,
                "agent_version": item.agent_version,
                "observed_at": item.observed_at.isoformat(),
            }
        )
    rows: list[dict[str, object]] = []
    for discovered in discover_agents(registry):
        metadata = (
            registry.agents.get(discovered.profile.registry_id)
            if discovered.profile.registry_id is not None
            else None
        )
        rows.append(
            {
                "id": discovered.profile.agent_id,
                "display_name": discovered.profile.display_name,
                "driver": discovered.profile.driver,
                "installed": discovered.installed,
                "detected_version": discovered.detected_version,
                "reason": discovered.reason,
                "install_url": discovered.profile.install_url,
                "models": grouped.get(discovered.profile.agent_id, []),
                "registry": (
                    {
                        "version": metadata.version,
                        "distributions": [
                            {
                                "manager": item.manager,
                                "package": item.package,
                                "version": item.version,
                                "args": list(item.args),
                            }
                            for item in metadata.distributions
                        ],
                    }
                    if metadata is not None
                    else None
                ),
            }
        )
    return JsonResponse(
        {
            "agents": rows,
            "registry": {
                "source_url": registry.source_url,
                "fetched_at": registry.fetched_at.isoformat(),
                "cache_age_seconds": round(registry.cache_age_seconds, 3),
                "stale": registry.stale,
                "warning": registry.warning,
            },
        }
    )


@api_errors
@owner_required
@require_GET
def runs(request: HttpRequest) -> HttpResponse:
    limit = _nonnegative_int(request.GET.get("limit"), field="limit", default=API_MAX_PAGE)
    if limit == 0:
        message = "limit must be at least 1."
        raise ConfigError(message)
    status = request.GET.get("status")
    if status is not None and status not in {item.value for item in RunStatus}:
        message = "status is not a recognized run state."
        raise ConfigError(message)
    project_id = request.GET.get("project")
    if project_id is not None:
        project_id = canonical_uuid(project_id, resource="project")
    since = request.GET.get("since")
    if since is not None:
        since = canonical_uuid(since, resource="run")
    records, next_value = DjangoReadStore().list_runs(
        project_id=project_id,
        status=status,
        since=since,
        limit=limit,
    )
    return JsonResponse({"runs": records, "next": next_value})


@api_errors
@owner_required
@require_GET
def run_detail(request: HttpRequest, run_id: str) -> HttpResponse:
    del request
    return JsonResponse(
        {"run": DjangoReadStore().run_detail(canonical_uuid(run_id, resource="run"))}
    )


@api_errors
@owner_required
@require_GET
def run_events(request: HttpRequest, run_id: str) -> HttpResponse:
    run_id = canonical_uuid(run_id, resource="run")
    since = _nonnegative_int(request.GET.get("since"), field="since", default=0)
    limit = _nonnegative_int(request.GET.get("limit"), field="limit", default=API_MAX_PAGE)
    if limit == 0:
        message = "limit must be at least 1."
        raise ConfigError(message)
    events, next_value = DjangoReadStore().page_events(run_id, since, limit)
    return JsonResponse({"events": events, "next": next_value})


@api_errors
@owner_required
@require_GET
def run_artifacts(request: HttpRequest, run_id: str) -> HttpResponse:
    del request
    return JsonResponse(
        {"artifacts": DjangoReadStore().list_artifacts(canonical_uuid(run_id, resource="run"))}
    )


@api_errors
@owner_required
@require_GET
def artifact(request: HttpRequest, artifact_id: str) -> FileResponse:
    del request
    path, name, media_type = DjangoReadStore().artifact_file(
        canonical_record_id(artifact_id, resource="artifact")
    )
    return FileResponse(path.open("rb"), as_attachment=True, filename=name, content_type=media_type)


@api_errors
def api_not_found(request: HttpRequest, path: str = "") -> HttpResponse:
    del request, path
    return JsonResponse(
        {
            "code": "not_found",
            "message": "The requested Relay API route does not exist.",
            "context": {},
        },
        status=404,
    )


__all__ = [
    "agents",
    "api_not_found",
    "artifact",
    "projects",
    "run_artifacts",
    "run_detail",
    "run_events",
    "runs",
    "workflow",
]
