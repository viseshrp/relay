"""Authenticated JSON action endpoints for the local browser application."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import re

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET, require_POST

from relay.config import load_config
from relay.errors import ConfigError, PermissionFlowError
from relay.execution.control import ControlResult, submit_control
from relay.execution.launch import LaunchRequest, launch_workflow
from relay.execution.resume import RecoveryTarget, rerun_failed_node
from relay.execution.scheduler import dispatch_ready_nodes
from relay.execution.state import CleanupPolicy, ControlKind
from relay.paths import artifacts_dir
from relay.projects.service import register_current_project, relink_project
from relay.vcs.artifacts import preserve_then_reset
from relay.vcs.worktree import reset_worktree
from relay.workflows.editor import autosave_workflow_draft, save_workflow_document

from ..auth import (
    auth_state,
    create_owner,
    login_owner,
    logout_owner,
    owner_required,
    owner_username,
)
from ..repositories import DjangoExecutionStore, DjangoProjectStore, DjangoWorkflowStore
from . import (
    api_errors,
    current_project,
    json_body,
    optional_text,
    required_object,
    required_text,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
    record = register_current_project(DjangoProjectStore(), Path(required_text(body, "path")))
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
    relay_root, project = current_project()
    body = json_body(request)
    draft = autosave_workflow_draft(
        DjangoWorkflowStore(),
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
    relay_root, project = current_project()
    body = json_body(request)
    save_workflow_document(
        DjangoWorkflowStore(),
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
    _relay_root, project = current_project()
    body = json_body(request)
    holder = required_text(body, "holder")
    if len(holder) > 200:
        message = "holder must contain at most 200 characters."
        raise ConfigError(message)
    lease = DjangoWorkflowStore().acquire_lease(project.id, key, holder)
    return JsonResponse({"lease": lease})


@api_errors
@owner_required
@require_POST
def launch_run(request: HttpRequest) -> HttpResponse:
    relay_root, project = current_project()
    body = json_body(request)
    cleanup_value = body.get("cleanup_policy", load_config().cleanup_policy)
    if not isinstance(cleanup_value, str):
        message = "cleanup_policy must be a string."
        raise ConfigError(message)
    if cleanup_value not in {item.value for item in CleanupPolicy}:
        message = "cleanup_policy must be clean_on_success or retain."
        raise ConfigError(message)
    config = load_config()
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
    body = json_body(request)
    key = required_text(body, "idempotency_key")
    result = DjangoExecutionStore().request_run_cancellation(run_id, key)
    return _control_response(result)


def _answer_control(
    request: HttpRequest,
    attempt_id: str,
    kind: ControlKind,
    value_field: str,
) -> JsonResponse:
    body = json_body(request)
    if value_field not in body:
        message = f"{value_field} is required."
        raise ConfigError(message)
    result = submit_control(
        DjangoExecutionStore(),
        attempt_id,
        kind,
        required_text(body, "idempotency_key"),
        {value_field: body[value_field]},
    )
    return _control_response(result)


@api_errors
@owner_required
@require_POST
def answer_permission(request: HttpRequest, attempt_id: str) -> HttpResponse:
    body = json_body(request)
    decision = required_text(body, "decision")
    result = submit_control(
        DjangoExecutionStore(),
        attempt_id,
        ControlKind.PERMISSION_ANSWER,
        required_text(body, "idempotency_key"),
        {"decision": decision},
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


def _prepare_recovery(target: RecoveryTarget) -> None:
    repository = Path(target.project_path)
    worktree = Path(target.worktree_path)
    if target.attempt_id is None:
        reset_worktree(
            worktree,
            target.starting_head,
            protected_head=target.protected_head,
        )
        return
    retained = artifacts_dir() / target.run_id / target.attempt_id
    if retained.is_dir():
        reset_worktree(
            worktree,
            target.starting_head,
            protected_head=target.protected_head,
        )
        return
    preserve_then_reset(
        repository,
        worktree,
        target.run_id,
        target.attempt_id,
        target.starting_head,
        protected_head=target.protected_head,
    )


@api_errors
@owner_required
@require_POST
def rerun_node(request: HttpRequest, run_id: str) -> HttpResponse:
    body = json_body(request)
    store = DjangoExecutionStore()
    activated = rerun_failed_node(
        store,
        run_id,
        required_text(body, "scope_path"),
        required_text(body, "idempotency_key"),
        _prepare_recovery,
    )
    if activated:
        dispatch_ready_nodes(store, run_id, _enqueue_claim)
    return _control_response(ControlResult.ACCEPTED if activated else ControlResult.ALREADY_APPLIED)


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
    _relay_root, project = current_project()
    deleted = DjangoExecutionStore().clean_project_data(
        project.id,
        required_text(body, "scope"),
    )
    return JsonResponse({"deleted": deleted})


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
