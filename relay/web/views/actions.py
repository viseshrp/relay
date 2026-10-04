"""Authenticated JSON action endpoints for the local browser application."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import re

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET, require_POST

from relay.agents.driver import probe_agent_configuration, probe_agent_models
from relay.config import load_config
from relay.errors import ConfigError, PermissionFlowError
from relay.execution.cancellation import request_cancellation
from relay.execution.control import ControlResult, submit_control
from relay.execution.launch import LaunchRequest, launch_workflow
from relay.execution.recovery import prepare_recovery_workspace
from relay.execution.resume import rerun_failed_node
from relay.execution.scheduler import dispatch_ready_nodes
from relay.execution.state import CleanupPolicy, ControlKind
from relay.projects.service import initialize_project, register_current_project, relink_project
from relay.workflows.editor import (
    autosave_workflow_draft,
    create_workflow_document,
    read_prompt_document,
    read_workflow_document,
    save_prompt_document,
    save_workflow_document,
)
from relay.workflows.loader import workflow_key_parts

from ..auth import (
    auth_state,
    create_owner,
    login_owner,
    logout_owner,
    owner_required,
    owner_username,
)
from ..repositories import (
    DjangoAgentStore,
    DjangoExecutionStore,
    DjangoProjectStore,
    DjangoWorkflowStore,
)
from . import (
    api_errors,
    canonical_record_id,
    canonical_uuid,
    current_project,
    json_body,
    optional_text,
    required_object,
    required_text,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@api_errors
@owner_required
@require_POST
def agent_configuration(request: HttpRequest, agent_id: str) -> HttpResponse:
    body = json_body(request)
    relay_root, _project = current_project(request)
    configuration = probe_agent_configuration(
        agent_id,
        required_text(body, "model"),
        relay_root.parent,
        observation_store=DjangoAgentStore(),
    )
    return JsonResponse(asdict(configuration))


@api_errors
@owner_required
@require_POST
def agent_models(request: HttpRequest, agent_id: str) -> HttpResponse:
    root, _project = current_project(request)
    observations = probe_agent_models(agent_id, root.parent, observation_store=DjangoAgentStore())
    return JsonResponse(
        {"models": [{"value": item.model_value, "name": item.model_name} for item in observations]}
    )


def csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    """Keep CSRF failures inside Relay's public JSON error shape."""
    del request, reason
    return JsonResponse(
        {
            "code": "csrf_failed",
            "message": "The CSRF token is missing or no longer valid.",
            "context": {},
            "next_action": "Reload the Relay page and submit the action again.",
        },
        status=403,
    )


def _yaml_text(body: dict[str, object]) -> str:
    value = body.get("yaml")
    if not isinstance(value, str):
        message = "yaml must be a string."
        raise ConfigError(message)
    return value


def _base_hash(body: dict[str, object]) -> str:
    value = required_text(body, "base_hash")
    if _SHA256.fullmatch(value) is None:
        message = "base_hash must contain 64 lowercase hexadecimal characters."
        raise ConfigError(message)
    return value


def _lease_holder(body: dict[str, object]) -> str:
    holder = required_text(body, "holder")
    if len(holder) > 200:
        message = "holder must contain at most 200 characters."
        raise ConfigError(message)
    return holder


def _control_response(result: ControlResult) -> JsonResponse:
    status = {
        ControlResult.ACCEPTED: 202,
        ControlResult.ALREADY_APPLIED: 202,
        ControlResult.STALE: 409,
        ControlResult.INVALID: 422,
    }[result]
    return JsonResponse({"result": result.value}, status=status)


@api_errors
@require_GET
def authentication_state(request: HttpRequest) -> HttpResponse:
    return JsonResponse(auth_state(request))


@api_errors
@require_POST
def onboard(request: HttpRequest) -> HttpResponse:
    body = json_body(request)
    owner = create_owner(
        request,
        required_text(body, "username"),
        required_text(body, "password"),
    )
    return JsonResponse({"authenticated": True, "username": owner.get_username()}, status=201)


@api_errors
@require_POST
def sign_in(request: HttpRequest) -> HttpResponse:
    body = json_body(request)
    owner = login_owner(
        request,
        required_text(body, "username"),
        required_text(body, "password"),
    )
    if owner is None:
        return JsonResponse(
            {
                "code": "authentication_failed",
                "message": "The username or password is not valid.",
                "context": {},
            },
            status=401,
        )
    return JsonResponse({"authenticated": True, "username": owner.get_username()})


@api_errors
@owner_required
@require_POST
def sign_out(request: HttpRequest) -> HttpResponse:
    logout_owner(request)
    return JsonResponse({"authenticated": False})


@api_errors
@owner_required
@require_POST
def open_project(request: HttpRequest) -> HttpResponse:
    body = json_body(request)
    location = Path(required_text(body, "path"))
    if body.get("initialize") is True:
        initialize_project(location)
    record = register_current_project(DjangoProjectStore(), location)
    return JsonResponse({"project": asdict(record)})


@api_errors
@owner_required
@require_POST
def relink_registered_project(request: HttpRequest) -> HttpResponse:
    body = json_body(request)
    record = relink_project(
        DjangoProjectStore(),
        Path(required_text(body, "old")),
        Path(required_text(body, "new")),
    )
    return JsonResponse({"project": asdict(record)})


@api_errors
@owner_required
@require_POST
def autosave_draft(request: HttpRequest, key: str) -> HttpResponse:
    relay_root, project = current_project(request)
    body = json_body(request)
    store = DjangoWorkflowStore()
    store.require_lease(project.id, key, _lease_holder(body))
    draft = autosave_workflow_draft(
        store,
        relay_root,
        project.id,
        key,
        _yaml_text(body),
        _base_hash(body),
    )
    return JsonResponse({"draft": draft})


@api_errors
@owner_required
@require_POST
def save_workflow(request: HttpRequest, key: str) -> HttpResponse:
    relay_root, project = current_project(request)
    body = json_body(request)
    store = DjangoWorkflowStore()
    store.require_lease(project.id, key, _lease_holder(body))
    save_workflow_document(
        store,
        relay_root,
        project.id,
        key,
        _yaml_text(body),
        _base_hash(body),
    )
    return JsonResponse({"ok": True})


@api_errors
@owner_required
@require_POST
def acquire_workflow_lease(request: HttpRequest, key: str) -> HttpResponse:
    _relay_root, project = current_project(request)
    body = json_body(request)
    holder = _lease_holder(body)
    lease = DjangoWorkflowStore().acquire_lease(project.id, key, holder)
    return JsonResponse({"lease": lease})


@api_errors
@owner_required
@require_POST
def create_workflow(request: HttpRequest) -> HttpResponse:
    relay_root, project = current_project(request)
    body = json_body(request)
    # "nested/review" becomes "nested/review.yaml", matching the inventory and its lease.
    key = "/".join(workflow_key_parts(required_text(body, "key")))
    store = DjangoWorkflowStore()
    store.acquire_lease(project.id, key, _lease_holder(body))
    document = create_workflow_document(
        store,
        relay_root,
        project.id,
        key,
        _yaml_text(body) if "yaml" in body else None,
        optional_text(body, "name") or "New workflow",
    )
    return JsonResponse(
        {"key": key, "yaml": document.yaml, "base_hash": document.base_hash}, status=201
    )


@api_errors
@owner_required
@require_GET
def read_workflow_prompt(request: HttpRequest, key: str) -> HttpResponse:
    relay_root, project = current_project(request)
    read_workflow_document(DjangoWorkflowStore(), relay_root, project.id, key)
    reference = request.GET.get("reference")
    if reference is None:
        message = "reference is required."
        raise ConfigError(message)
    return JsonResponse(read_prompt_document(relay_root, reference))


@api_errors
@owner_required
@require_POST
def save_workflow_prompt(request: HttpRequest, key: str) -> HttpResponse:
    relay_root, project = current_project(request)
    body = json_body(request)
    DjangoWorkflowStore().require_lease(project.id, key, _lease_holder(body))
    read_workflow_document(DjangoWorkflowStore(), relay_root, project.id, key)
    return JsonResponse(
        save_prompt_document(
            relay_root,
            required_text(body, "reference"),
            required_text(body, "text"),
            _base_hash(body) if body.get("base_hash") is not None else None,
        )
    )


def workflow_prompt(request: HttpRequest, key: str) -> HttpResponseBase:
    """Route instruction reads and lease-protected edits by HTTP method."""
    if request.method == "POST":
        return save_workflow_prompt(request, key)
    return read_workflow_prompt(request, key)


def workflows_collection(request: HttpRequest) -> HttpResponseBase:
    """List workflows on GET and create a workflow on POST."""
    if request.method == "POST":
        return create_workflow(request)
    from .pages import workflows

    return workflows(request)


@api_errors
@owner_required
@require_POST
def launch_run(request: HttpRequest) -> HttpResponse:
    relay_root, project = current_project(request)
    body = json_body(request)
    expected = body.get("project_id")
    if expected is not None and expected != project.id:
        message = "The workflow is bound to a different project than the one selected for this run."
        raise ConfigError(
            message, next_action="Reload the workflow in the selected project before starting."
        )
    config = load_config()
    cleanup_value = body.get("cleanup_policy", config.cleanup_policy)
    if not isinstance(cleanup_value, str):
        message = "cleanup_policy must be a string."
        raise ConfigError(message)
    if cleanup_value not in {item.value for item in CleanupPolicy}:
        message = "cleanup_policy must be clean_on_success or retain."
        raise ConfigError(message)
    launcher = owner_username(request)
    result = launch_workflow(
        DjangoExecutionStore(),
        relay_root,
        project.id,
        LaunchRequest(
            workflow_key=required_text(body, "workflow_key"),
            inputs=required_object(body, "inputs"),
            model=optional_text(body, "model"),
            cleanup_policy=cleanup_value,
            entry_point=optional_text(body, "entry_point"),
            owner_agents=config.agent_preferences,
            launcher=launcher,
        ),
        _enqueue_claim,
    )
    return JsonResponse({"run_id": result.run_id}, status=201)


def runs_collection(request: HttpRequest) -> HttpResponseBase:
    """Route the shared `/api/runs` path by its documented HTTP method."""
    if request.method == "POST":
        return launch_run(request)
    from .pages import runs

    return runs(request)


def _enqueue_claim(claim_token: str) -> object:
    from relay.execution.huey_app import enqueue_claim

    return enqueue_claim(claim_token)


@api_errors
@owner_required
@require_POST
def cancel_run(request: HttpRequest, run_id: str) -> HttpResponse:
    run_id = canonical_uuid(run_id, resource="run")
    body = json_body(request)
    key = required_text(body, "idempotency_key")
    result = request_cancellation(DjangoExecutionStore(), run_id, key)
    return _control_response(result)


def _answer_control(
    request: HttpRequest,
    attempt_id: str,
    kind: ControlKind,
    value_field: str,
) -> JsonResponse:
    attempt_id = canonical_record_id(attempt_id, resource="attempt")
    body = json_body(request)
    if value_field not in body:
        message = f"{value_field} is required."
        raise ConfigError(message)
    payload = {value_field: body[value_field]}
    if "interaction_id" in body:
        payload["interaction_id"] = canonical_record_id(
            required_text(body, "interaction_id"), resource="interaction"
        )
    if kind == ControlKind.ELICITATION_ANSWER and "feedback" in body:
        payload["feedback"] = required_text(body, "feedback")
    result = submit_control(
        DjangoExecutionStore(),
        attempt_id,
        kind,
        required_text(body, "idempotency_key"),
        payload,
    )
    return _control_response(result)


@api_errors
@owner_required
@require_POST
def answer_permission(request: HttpRequest, attempt_id: str) -> HttpResponse:
    attempt_id = canonical_record_id(attempt_id, resource="attempt")
    body = json_body(request)
    decision = required_text(body, "decision")
    payload = {"decision": decision}
    if "interaction_id" in body:
        payload["interaction_id"] = canonical_record_id(
            required_text(body, "interaction_id"), resource="interaction"
        )
    if "feedback" in body:
        payload["feedback"] = required_text(body, "feedback")
    result = submit_control(
        DjangoExecutionStore(),
        attempt_id,
        ControlKind.PERMISSION_ANSWER,
        required_text(body, "idempotency_key"),
        payload,
    )
    return _control_response(result)


@api_errors
@owner_required
@require_POST
def answer_elicitation(request: HttpRequest, attempt_id: str) -> HttpResponse:
    return _answer_control(request, attempt_id, ControlKind.ELICITATION_ANSWER, "value")


@api_errors
@owner_required
@require_POST
def answer_wait(request: HttpRequest, attempt_id: str) -> HttpResponse:
    return _answer_control(request, attempt_id, ControlKind.WAIT_ANSWER, "value")


@api_errors
@owner_required
@require_POST
def rerun_node(request: HttpRequest, run_id: str) -> HttpResponse:
    run_id = canonical_uuid(run_id, resource="run")
    body = json_body(request)
    store = DjangoExecutionStore()
    result = rerun_failed_node(
        store,
        run_id,
        required_text(body, "scope_path"),
        required_text(body, "idempotency_key"),
        lambda target: prepare_recovery_workspace(store, target),
    )
    if result is ControlResult.ACCEPTED:
        dispatch_ready_nodes(store, run_id, _enqueue_claim)
    return _control_response(result)


@api_errors
@owner_required
@require_POST
def clean_data(request: HttpRequest) -> HttpResponse:
    body = json_body(request)
    if body.get("confirm") is not True:
        message = "Data cleanup requires an explicit true confirmation."
        raise PermissionFlowError(
            message,
            next_action="Review the selected scope before confirming deletion.",
        )
    _relay_root, project = current_project(request)
    deleted = DjangoExecutionStore().clean_project_data(
        project.id,
        required_text(body, "scope"),
    )
    return JsonResponse({"deleted": deleted})


@api_errors
@owner_required
@require_POST
def clean_run_resources(request: HttpRequest, run_id: str) -> HttpResponse:
    if json_body(request).get("confirm") is not True:
        message = "Temporary resource cleanup requires an explicit true confirmation."
        raise PermissionFlowError(message)
    removed = DjangoExecutionStore().clean_run_resources(canonical_uuid(run_id, resource="run"))
    return JsonResponse({"removed": removed})


__all__ = [
    "acquire_workflow_lease",
    "answer_elicitation",
    "answer_permission",
    "answer_wait",
    "authentication_state",
    "autosave_draft",
    "cancel_run",
    "clean_data",
    "csrf_failure",
    "launch_run",
    "onboard",
    "open_project",
    "relink_registered_project",
    "rerun_node",
    "runs_collection",
    "save_workflow",
    "sign_in",
    "sign_out",
]
