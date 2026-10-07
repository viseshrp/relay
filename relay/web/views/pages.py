"""Authenticated bounded reads for projects, workflows, agents, and runs."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict

from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from relay.agents.discovery import discover_agents
from relay.agents.registry import load_registry
from relay.config import load_config
from relay.constants import (
    API_MAX_PAGE,
    DATABASE_INTEGER_MAX,
    DEFAULT_FIX_INSTRUCTION,
    DEFAULT_REPAIR_ROUNDS,
    DEFAULT_VERIFY_INSTRUCTION,
    MAX_LOOP_ITERATIONS,
    REVIEW_PREVIEW_MAX_BYTES,
)
from relay.errors import ConfigError, RelayError
from relay.execution.state import RunStatus
from relay.projects.service import list_registered_projects
from relay.workflows.editor import (
    list_workflow_documents,
    read_workflow_document,
    workflow_handoff_warnings,
)
from relay.workflows.loader import load_workflow_text, load_workflow_tree
from relay.workflows.starters import starter_inventory

from ..auth import owner_required
from ..repositories import (
    DjangoAgentStore,
    DjangoProjectStore,
    DjangoReadStore,
    DjangoWorkflowStore,
)
from . import api_errors, canonical_record_id, canonical_uuid, current_project


def _nonnegative_int(
    value: str | None,
    *,
    field: str,
    default: int,
    maximum: int | None = None,
) -> int:
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
    if maximum is not None and parsed > maximum:
        message = f"{field} exceeds Relay's database integer range."
        raise ConfigError(message)
    return parsed


def _page_limit(request: HttpRequest) -> int:
    limit = _nonnegative_int(request.GET.get("limit"), field="limit", default=API_MAX_PAGE)
    if limit == 0:
        message = "limit must be at least 1."
        raise ConfigError(message)
    return limit


def _page_parameters(request: HttpRequest) -> tuple[int, int]:
    since = _nonnegative_int(
        request.GET.get("since"), field="since", default=0, maximum=DATABASE_INTEGER_MAX
    )
    return since, _page_limit(request)


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
def project_context(request: HttpRequest) -> HttpResponse:
    _root, project = current_project(request)
    return JsonResponse({"project": asdict(project)})


@api_errors
@owner_required
@require_GET
def workflow_templates(request: HttpRequest) -> HttpResponse:
    del request
    return JsonResponse({"templates": starter_inventory()})


@api_errors
@owner_required
@require_GET
def workflows(request: HttpRequest) -> HttpResponse:
    relay_root, project = current_project(request)
    return JsonResponse(
        {"workflows": list_workflow_documents(relay_root), "project": asdict(project)}
    )


@api_errors
@owner_required
@require_GET
def workflow(request: HttpRequest, key: str) -> HttpResponse:
    relay_root, project = current_project(request)
    document = read_workflow_document(DjangoWorkflowStore(), relay_root, project.id, key)
    try:
        loaded = load_workflow_text(document.yaml, source=relay_root / "workflows" / key)
        warnings = workflow_handoff_warnings(loaded.definition.nodes)
        # Child files are loaded once, even when the workflow invokes them repeatedly.
        with suppress(RelayError):
            for child_key, child in load_workflow_tree(loaded, relay_root / "workflows").items():
                warnings.extend(
                    {**warning, "workflow_key": child_key}
                    for warning in workflow_handoff_warnings(child.definition.nodes)
                )
    except RelayError:
        warnings = []
    return JsonResponse(
        {
            "yaml": document.yaml,
            "draft": document.draft,
            "base_hash": document.base_hash,
            "project": asdict(project),
            "warnings": warnings,
            "repair_defaults": {
                "max_rounds": DEFAULT_REPAIR_ROUNDS,
                "max_allowed_rounds": MAX_LOOP_ITERATIONS,
                "fix_instruction": DEFAULT_FIX_INSTRUCTION,
                "verify_instruction": DEFAULT_VERIFY_INSTRUCTION,
            },
        }
    )


@api_errors
@owner_required
@require_GET
def agents(request: HttpRequest) -> HttpResponse:
    del request
    registry = load_registry()
    observations = DjangoAgentStore().list_model_observations()
    grouped = {}
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
    rows = []
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
            "preferences": list(load_config().agent_preferences),
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
    limit = _page_limit(request)
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
    collection = request.GET.get("collection", "nodes")
    if collection not in {"nodes", "interactions"}:
        message = "collection must be nodes or interactions."
        raise ConfigError(message)
    since, limit = _page_parameters(request)
    target = request.GET.get("interaction")
    run, next_value = DjangoReadStore().run_detail(
        canonical_uuid(run_id, resource="run"),
        collection=collection,
        since=since,
        limit=limit,
        pending_only=request.GET.get("pending") == "true",
        interaction_id=canonical_record_id(target, resource="interaction")
        if target is not None
        else None,
    )
    return JsonResponse({"run": run, "next": next_value})


@api_errors
@owner_required
@require_GET
def run_events(request: HttpRequest, run_id: str) -> HttpResponse:
    run_id = canonical_uuid(run_id, resource="run")
    since, limit = _page_parameters(request)
    events, next_value = DjangoReadStore().page_events(run_id, since, limit)
    return JsonResponse({"events": events, "next": next_value})


@api_errors
@owner_required
@require_GET
def run_artifacts(request: HttpRequest, run_id: str) -> HttpResponse:
    since, limit = _page_parameters(request)
    artifacts, next_value = DjangoReadStore().page_artifacts(
        canonical_uuid(run_id, resource="run"),
        since,
        limit,
    )
    return JsonResponse({"artifacts": artifacts, "next": next_value})


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
@owner_required
@require_GET
def artifact_preview(request: HttpRequest, artifact_id: str) -> HttpResponse:
    del request
    path, name, _media_type = DjangoReadStore().artifact_file(
        canonical_record_id(artifact_id, resource="artifact")
    )
    try:
        with path.open("rb") as stream:
            content = stream.read(REVIEW_PREVIEW_MAX_BYTES + 1)
        # Decode an incomplete final UTF-8 character only when the preview was bounded.
        text = content[:REVIEW_PREVIEW_MAX_BYTES].decode(
            "utf-8", errors="ignore" if len(content) > REVIEW_PREVIEW_MAX_BYTES else "strict"
        )
        previewable = "\0" not in text
    except UnicodeError:
        text, previewable = "", False
    except OSError:
        message = "The retained document could not be opened."
        raise ConfigError(message) from None
    return JsonResponse(
        {
            "name": name,
            "text": text if previewable else "",
            "previewable": previewable,
            "truncated": len(content) > REVIEW_PREVIEW_MAX_BYTES,
        }
    )


@api_errors
@owner_required
@require_GET
def run_changes(request: HttpRequest, run_id: str) -> HttpResponse:
    del request
    return JsonResponse(DjangoReadStore().run_changes(canonical_uuid(run_id, resource="run")))


@api_errors
@owner_required
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
