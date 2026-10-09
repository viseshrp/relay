"""Owner-authenticated language, scope, environment, and local trigger APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from django.http import FileResponse, HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from relay.errors import ConfigError, RelayError
from relay.workflows.actions.language import capture_sources, load, support_manifest

from ..actions_bindings import put_binding, scopes
from ..actions_repository import approve_environment
from ..auth import owner_required
from ..models import (
    ActionsArtifact,
    ActionsQueue,
    Run,
    TriggerDelivery,
    WorkflowBinding,
    WorkflowEnvironment,
    WorkflowTrigger,
)
from . import api_errors, current_project, json_body, required_text


@api_errors
@owner_required
@require_GET
def manifest(request: HttpRequest) -> JsonResponse:
    return JsonResponse(support_manifest())


@api_errors
@owner_required
def library(request: HttpRequest) -> JsonResponse:
    from relay.workflows.library import export_template, import_template, inventory

    if request.method == "POST":
        bundle = json_body(request, max_bytes=10 * 1_048_576)
        if bundle.pop("include_project_sources", False):
            from relay.workflows.actions.patterns import select_paths

            root, _ = current_project(request)
            sources = capture_sources(load(required_text(bundle, "yaml")), root.parent)
            prompts = root / "prompts"
            if prompts.exists():
                for path in select_paths(prompts, ["**"], files_only=True):
                    if path.stat().st_size > 1_048_576:
                        message = "A library prompt exceeds 1 MiB."
                        raise ConfigError(message)
                    sources[path.relative_to(root.parent).as_posix()] = path.read_text("utf-8")
            bundle["sources"] = sources
        return JsonResponse({"id": import_template(bundle)}, status=201)
    if request.method != "GET":
        return JsonResponse({"message": "Use GET or POST."}, status=405)
    identity = request.GET.get("id")
    return JsonResponse(export_template(identity) if identity else {"templates": inventory()})


@api_errors
@owner_required
@require_POST
def validate(request: HttpRequest) -> JsonResponse:
    body = json_body(request)
    root, _ = current_project(request)
    try:
        document = load(
            required_text(body, "yaml"), source=Path(str(body.get("source", "workflow.yml")))
        )
        sources = capture_sources(document, root.parent)
        return JsonResponse(
            {
                "valid": True,
                "diagnostics": [],
                "definition": document.value,
                "sources": list(sources),
            }
        )
    except RelayError as error:
        return JsonResponse({"valid": False, "diagnostics": [error.to_envelope()]})


def _scope(request: HttpRequest, body: dict[str, Any]) -> str:
    _, project = current_project(request)
    name = str(body.get("scope", "project"))
    if name not in {"installation", "project", "environment"}:
        message = "Select installation, project, or environment scope."
        raise ConfigError(message)
    allowed = scopes(project.id, str(body["environment"]) if body.get("environment") else None)
    scope = (
        allowed[0]
        if name == "installation"
        else allowed[-1]
        if name == "environment"
        else allowed[1]
    )
    if (
        name == "environment"
        and not WorkflowEnvironment.objects.filter(
            project_id=project.id, name=body.get("environment")
        ).exists()
    ):
        message = "Select a configured environment."
        raise ConfigError(message)
    return scope


@api_errors
@owner_required
def bindings(request: HttpRequest) -> JsonResponse:
    root, project = current_project(request)
    del root
    if request.method == "POST":
        body = json_body(request)
        scope = _scope(request, body)
        name, kind = required_text(body, "name"), required_text(body, "kind")
        if any(
            not isinstance(body.get(field, ""), str) for field in ("source", "reference", "value")
        ):
            message = "Binding values and references must be strings."
            raise ConfigError(message)
        if body.get("delete"):
            WorkflowBinding.objects.filter(scope=scope, name=name.upper(), kind=kind).delete()
        else:
            put_binding(
                scope,
                name,
                kind,
                source=str(body.get("source", "")),
                reference=str(body.get("reference", "")),
                value=str(body.get("value", "")),
            )
    elif request.method != "GET":
        return JsonResponse({"message": "Use GET or POST."}, status=405)
    allowed = [
        *scopes(project.id),
        *(
            f"environment:{project.id}:{name}"
            for name in WorkflowEnvironment.objects.filter(project_id=project.id).values_list(
                "name", flat=True
            )
        ),
    ]
    return JsonResponse(
        {
            "bindings": [
                {
                    **row,
                    "value": row["value"] if row["kind"] == "variable" else "",
                    "revision": str(row["revision"]),
                }
                for row in WorkflowBinding.objects.filter(scope__in=allowed).values(
                    "scope", "name", "kind", "value", "source", "reference", "revision"
                )
            ]
        }
    )


@api_errors
@owner_required
def environments(request: HttpRequest) -> JsonResponse:
    _, project = current_project(request)
    if request.method == "POST":
        body = json_body(request)
        name = required_text(body, "name")
        branches = body.get("branches", [])
        wait = body.get("wait_minutes", 0)
        approval = body.get("approval_required", False)
        url = body.get("url", "")
        if (
            len(name) > 255
            or not isinstance(branches, list)
            or any(not isinstance(item, str) for item in branches)
            or len(branches) > 100
            or any(len(item) > 256 for item in branches)
            or not isinstance(wait, int)
            or isinstance(wait, bool)
            or not 0 <= wait <= 43200
            or not isinstance(approval, bool)
            or not isinstance(url, str)
            or len(url) > 2048
            or (url and not url.startswith(("http://", "https://")))
        ):
            message = "Invalid environment configuration."
            raise ConfigError(message)
        from relay.workflows.actions.patterns import pattern_regex

        for branch in branches:
            pattern_regex(branch.removeprefix("!"))
        if (
            not WorkflowEnvironment.objects.filter(project_id=project.id, name=name).exists()
            and WorkflowEnvironment.objects.filter(project_id=project.id).count() >= 100
        ):
            message = "Each project is limited to 100 environments."
            raise ConfigError(message)
        WorkflowEnvironment.objects.update_or_create(
            project_id=project.id,
            name=name,
            defaults={
                "approval_required": approval,
                "wait_minutes": wait,
                "branches": branches,
                "url": url,
            },
        )
    elif request.method != "GET":
        return JsonResponse({"message": "Use GET or POST."}, status=405)
    return JsonResponse(
        {
            "environments": [
                {**row, "id": str(row["id"])}
                for row in WorkflowEnvironment.objects.filter(project_id=project.id).values(
                    "id", "name", "approval_required", "wait_minutes", "branches", "url"
                )
            ]
        }
    )


@api_errors
@owner_required
@require_POST
def approve(request: HttpRequest, attempt_id: str) -> JsonResponse:
    from ..models import NodeAttempt
    from . import canonical_record_id

    attempt_id = canonical_record_id(attempt_id, resource="attempt")

    _, project = current_project(request)
    if not NodeAttempt.objects.filter(pk=attempt_id, node_run__run__project_id=project.id).exists():
        message = "The environment attempt is unavailable."
        raise ConfigError(message)
    return JsonResponse({"approved": approve_environment(attempt_id)})


@api_errors
@owner_required
def triggers(request: HttpRequest) -> JsonResponse:
    from ..actions_automation import activate

    root, project = current_project(request)
    if request.method == "POST":
        body = json_body(request)
        if not isinstance(body.get("enabled"), bool) or not isinstance(
            body.get("allow_writers"), bool
        ):
            message = "Activation requires explicit enabled and allow_writers choices."
            raise ConfigError(message)
        activate(
            project.id,
            root,
            required_text(body, "key"),
            required_text(body, "event"),
            cast(bool, body["enabled"]),
            cast(bool, body["allow_writers"]),
        )
    elif request.method != "GET":
        return JsonResponse({"message": "Use GET or POST."}, status=405)
    return JsonResponse(
        {
            "triggers": [
                {**row, "id": str(row["id"])}
                for row in WorkflowTrigger.objects.filter(project_id=project.id).values(
                    "id", "workflow_key", "event", "enabled", "allow_writers", "source_hash"
                )
            ],
            "deliveries": [
                {
                    **row,
                    "id": str(row["id"]),
                    "run_id": str(row["run_id"]) if row["run_id"] else None,
                }
                for row in TriggerDelivery.objects.filter(trigger__project_id=project.id)
                .order_by("-created_at")
                .values("id", "occurrence", "state", "reason", "run_id")[:100]
            ],
        }
    )


@api_errors
@owner_required
@require_POST
def dispatch(request: HttpRequest) -> JsonResponse:
    from ..actions_automation import repository_dispatch

    _, project = current_project(request)
    body = json_body(request)
    payload = body.get("client_payload", {})
    if not isinstance(payload, dict):
        message = "client_payload must be an object."
        raise ConfigError(message)
    repository_dispatch(
        project.id,
        required_text(body, "event_type"),
        payload,
        required_text(body, "idempotency_key"),
    )
    return JsonResponse({"accepted": True})


@api_errors
@owner_required
@require_GET
def products(request: HttpRequest, run_id: str) -> JsonResponse:
    from . import canonical_uuid

    run_id = canonical_uuid(run_id, resource="run")
    _, project = current_project(request)
    run = Run.objects.filter(pk=run_id, project_id=project.id).first()
    if run is None:
        return JsonResponse(
            {"code": "run_not_found", "message": "The run is unavailable.", "context": {}},
            status=404,
        )
    return JsonResponse(
        {
            "artifacts": [
                {**row, "id": str(row["id"])}
                for row in ActionsArtifact.objects.filter(
                    run_id=run_id, run__project_id=project.id
                ).values("id", "name", "digest", "bytes", "manifest", "expires_at")
            ],
            "queues": list(
                ActionsQueue.objects.filter(run_id=run_id, run__project_id=project.id).values(
                    "scope", "group", "mode", "state"
                )
            ),
            "environments": run.actions_state.get("environment_links", {}),
        }
    )


@api_errors
@owner_required
@require_GET
def download_product(request: HttpRequest, artifact_id: str) -> FileResponse:
    import tempfile
    from zipfile import ZIP_DEFLATED, ZipFile

    from django.utils import timezone

    from relay.execution.action_products import checked_path, verify

    from . import canonical_uuid

    artifact_id = canonical_uuid(artifact_id, resource="artifact")

    _, project = current_project(request)
    artifact = ActionsArtifact.objects.filter(pk=artifact_id, run__project_id=project.id).first()
    if artifact is None or (
        artifact.expires_at is not None and artifact.expires_at <= timezone.now()
    ):
        message = "The named artifact is unavailable."
        raise ConfigError(message)
    directory = Path(cast(str, artifact.directory))
    manifest = cast(list[dict[str, Any]], artifact.manifest)
    verify(directory, manifest, "artifacts", str(artifact.run_id))
    stream = tempfile.TemporaryFile()  # noqa: SIM115 - FileResponse owns and closes the stream
    try:
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            for item in manifest:
                archive.write(checked_path(directory, item["path"]), item["path"])
        stream.seek(0)
        return FileResponse(stream, as_attachment=True, filename=f"{artifact.name}.zip")
    except Exception:
        stream.close()
        raise
