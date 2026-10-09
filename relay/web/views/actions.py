"""Authenticated JSON action endpoints for the local browser application."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
import re

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET, require_POST

from relay.agents.configuration import require_choice
from relay.agents.driver import probe_agent_configuration, probe_agent_models
from relay.agents.readiness import check_agent_readiness
from relay.errors import ConfigError, PermissionFlowError
from relay.execution.cancellation import request_cancellation
from relay.execution.control import ControlResult, submit_control
from relay.execution.launch import LaunchRequest, launch_workflow
from relay.execution.recovery import prepare_recovery_workspace
from relay.execution.resume import (
    RecoveryTarget,
    RetryAgent,
    RetryEffort,
    RetryPermissionMode,
    rerun_failed_node,
)
from relay.execution.scheduler import dispatch_ready_nodes
from relay.execution.state import CleanupPolicy, ControlKind
from relay.execution.step_settings import UnstartedAgentTarget, change_unstarted_agent_settings
from relay.owner_settings import effective_config
from relay.projects.service import initialize_project, register_current_project, relink_project
from relay.workflows.editor import (
    autosave_workflow_draft,
    create_workflow_document,
    read_prompt_document,
    read_workflow_document,
    save_prompt_document,
)
from relay.workflows.loader import workflow_key_parts
from relay.workflows.scope import parse_scope_path
from relay.workflows.starters import create_starter_workflow

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
from ..settings_repository import DjangoSettingsStore
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
def agent_readiness(request: HttpRequest) -> HttpResponse:
    root, _project = current_project(request)
    rows = check_agent_readiness(root.parent, observation_store=DjangoAgentStore())
    return JsonResponse({"agents": [asdict(row) for row in rows]})


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


def _requested_agent_settings(
    body: dict[str, object],
) -> tuple[RetryAgent | None, RetryEffort | None, RetryPermissionMode | None]:
    """Parse the same optional choices for a retry or an unstarted step."""
    agent = None
    if "agent_id" in body or "model" in body:
        agent = RetryAgent(
            required_text(body, "agent_id"),
            required_text(body, "model"),
            effort=optional_text(body, "effort"),
            permission_mode=optional_text(body, "permission_mode"),
            handoff_prompt=optional_text(body, "handoff_prompt"),
        )
    elif "handoff_prompt" in body:
        message = "A handoff prompt requires an explicit agent_id and model."
        raise ConfigError(message)
    effort = (
        RetryEffort(optional_text(body, "effort")) if "effort" in body and agent is None else None
    )
    mode = (
        RetryPermissionMode(optional_text(body, "permission_mode"))
        if "permission_mode" in body and agent is None
        else None
    )
    return agent, effort, mode


def _validate_agent_choices(
    agent_id: str,
    model: str,
    project_path: Path,
    effort: str | None,
    permission_mode: str | None,
) -> None:
    configuration = probe_agent_configuration(
        agent_id, model, project_path, observation_store=DjangoAgentStore()
    )
    if effort is not None:
        require_choice(configuration, "effort", effort)
    if permission_mode is not None:
        require_choice(configuration, "permission_mode", permission_mode)


@api_errors
@owner_required
@require_POST
def configure_repair_groups(request: HttpRequest, run_id: str) -> HttpResponse:
    run_id = canonical_uuid(run_id, resource="run")
    body = json_body(request)
    groups = {}
    for coordinator, source in required_object(body, "groups").items():
        if not isinstance(source, str):
            message = "groups must map repair-loop scopes to stage scopes."
            raise ConfigError(message)
        parse_scope_path(coordinator)
        parse_scope_path(source)
        groups[coordinator] = source
    result = DjangoExecutionStore().configure_repair_groups(
        run_id, groups, required_text(body, "idempotency_key")
    )
    return _control_response(result)


@api_errors
@owner_required
@require_POST
def configure_dispatch_pause(request: HttpRequest, run_id: str) -> HttpResponse:
    run_id = canonical_uuid(run_id, resource="run")
    body = json_body(request)
    paused = body.get("paused")
    if not isinstance(paused, bool):
        message = "paused must be a boolean."
        raise ConfigError(message)
    store = DjangoExecutionStore()
    result = store.configure_dispatch_pause(run_id, paused, required_text(body, "idempotency_key"))
    if result is ControlResult.ACCEPTED and not paused:
        dispatch_ready_nodes(store, run_id, _enqueue_claim)
        for token in store.pending_dispatch_tokens(run_id):
            _enqueue_claim(token)
    return _control_response(result)


@api_errors
@owner_required
@require_POST
def configure_pending_step(request: HttpRequest, run_id: str) -> HttpResponse:
    run_id = canonical_uuid(run_id, resource="run")
    body = json_body(request)
    agent, effort, mode = _requested_agent_settings(body)

    def validate(target: UnstartedAgentTarget, route: Mapping[str, object]) -> None:
        agent_id, model = route.get("selected_agent"), route.get("model_value")
        selected_effort, permission_mode = route.get("effort"), route.get("permission_mode")
        if (
            not isinstance(agent_id, str)
            or not isinstance(model, str)
            or (selected_effort is not None and not isinstance(selected_effort, str))
            or (permission_mode is not None and not isinstance(permission_mode, str))
        ):
            message = "The agent configuration is invalid."
            raise ConfigError(message)
        _validate_agent_choices(
            agent_id, model, Path(target.project_path), selected_effort, permission_mode
        )

    result = change_unstarted_agent_settings(
        DjangoExecutionStore(),
        run_id,
        required_text(body, "scope_path"),
        required_text(body, "idempotency_key"),
        validate,
        agent=agent,
        effort=effort,
        permission_mode=mode,
    )
    return _control_response(result)


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
    return JsonResponse({"authenticated": not settings.RELAY_LOGIN_REQUIRED})


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
    from relay.workflows.source_bundle import prompt_edits

    relay_root, project = current_project(request)
    body = json_body(request)
    store = DjangoWorkflowStore()
    store.require_lease(project.id, key, _lease_holder(body))
    edits = prompt_edits(body.get("prompts", {}), relay_root)
    draft = autosave_workflow_draft(
        store,
        relay_root,
        project.id,
        key,
        _yaml_text(body),
        _base_hash(body),
        prompts=dict(edits),
    )
    return JsonResponse({"draft": draft})


@api_errors
@owner_required
@require_POST
def save_workflow(request: HttpRequest, key: str) -> HttpResponse:
    from relay.workflows.source_bundle import prompt_edits, save_source_bundle

    relay_root, project = current_project(request)
    body = json_body(request)
    store = DjangoWorkflowStore()
    store.require_lease(project.id, key, _lease_holder(body))
    save_source_bundle(
        store,
        relay_root,
        project.id,
        key,
        _yaml_text(body),
        _base_hash(body),
        prompt_edits(body.get("prompts", {}), relay_root),
    )
    return JsonResponse({"ok": True})


@api_errors
@owner_required
def publish_workflow_sources(request: HttpRequest, key: str) -> HttpResponse:
    from relay.workflows.publication import commit_workflow_sources, preview_workflow_commit

    relay_root, _project = current_project(request)
    if request.method == "GET":
        return JsonResponse(preview_workflow_commit(relay_root, key))
    if request.method != "POST":
        return JsonResponse({"message": "Use GET or POST."}, status=405)
    body = json_body(request)
    hashes = required_object(body, "hashes")
    if body.get("confirmed") is not True or any(
        not isinstance(value, str) or not _SHA256.fullmatch(value) for value in hashes.values()
    ):
        message = "Confirm the reviewed workflow files and their hashes."
        raise ConfigError(message)
    head = commit_workflow_sources(
        relay_root,
        key,
        required_text(body, "head"),
        {name: str(value) for name, value in hashes.items()},
    )
    return JsonResponse({"head": head})


@api_errors
@owner_required
@require_POST
def acquire_workflow_lease(request: HttpRequest, key: str) -> HttpResponse:
    relay_root, project = current_project(request)
    body = json_body(request)
    holder = _lease_holder(body)
    read_workflow_document(DjangoWorkflowStore(), relay_root, project.id, key)
    if "takeover" in body and not isinstance(body["takeover"], bool):
        message = "takeover must be a boolean."
        raise ConfigError(message)
    try:
        lease = DjangoWorkflowStore().acquire_lease(
            project.id, key, holder, takeover=body.get("takeover") is True
        )
    except PermissionFlowError as error:
        if body.get("soft_conflict") is True:
            return JsonResponse({"lease": None, "conflict": error.to_envelope()})
        raise
    return JsonResponse({"lease": lease})


@api_errors
@owner_required
@require_POST
def release_workflow_lease(request: HttpRequest, key: str) -> HttpResponse:
    """Accept CSRF-protected form beacons as well as ordinary JSON writes."""
    _relay_root, project = current_project(request)
    body = (
        request.POST.dict()
        if request.content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}
        else json_body(request)
    )
    DjangoWorkflowStore().release_lease(project.id, key, _lease_holder(body))
    return JsonResponse({"ok": True})


@api_errors
@owner_required
@require_POST
def discard_workflow_draft(request: HttpRequest, key: str) -> HttpResponse:
    relay_root, project = current_project(request)
    body = json_body(request)
    store = DjangoWorkflowStore()
    read_workflow_document(store, relay_root, project.id, key)
    store.discard_recovery_draft(project.id, key, required_text(body, "updated_at"))
    return JsonResponse({"ok": True})


@api_errors
@owner_required
@require_POST
def manage_workflow(request: HttpRequest, key: str) -> HttpResponse:
    from relay.workflows.management import manage_workflow_document

    relay_root, project = current_project(request)
    key = "/".join(workflow_key_parts(key))
    body = json_body(request)
    store = DjangoWorkflowStore()
    store.require_lease(project.id, key, _lease_holder(body))
    action = required_text(body, "action")
    if action in {"disable", "enable"}:
        read_workflow_document(store, relay_root, project.id, key)
        store.set_disabled(project.id, key, action == "disable")
        return JsonResponse({"key": key, "disabled": action == "disable"})
    if action == "delete" and body.get("confirmed") is not True:
        message = (
            "Confirm deletion of this saved workflow. Run history and prompt files are retained."
        )
        raise ConfigError(message)
    result = manage_workflow_document(
        store,
        relay_root,
        project.id,
        key,
        action,
        _base_hash(body),
        new_key=optional_text(body, "new_key"),
        name=optional_text(body, "name"),
    )
    if action == "rename" and result and result != key:
        store.move_editor_state(project.id, key, result)
    return JsonResponse({"key": result})


@api_errors
@owner_required
@require_POST
def create_workflow(request: HttpRequest) -> HttpResponse:
    relay_root, project = current_project(request)
    body = json_body(request)
    # "nested/review" becomes "nested/review.yaml", matching the inventory and its lease.
    key = "/".join(workflow_key_parts(required_text(body, "key")))
    store = DjangoWorkflowStore()
    holder = _lease_holder(body)
    template_id = optional_text(body, "template_id")
    if template_id is not None:
        if "yaml" in body:
            message = "Choose a template or supply YAML, rather than both."
            raise ConfigError(message)
        document = create_starter_workflow(store, relay_root, project.id, key, template_id)
    else:
        document = create_workflow_document(
            store,
            relay_root,
            project.id,
            key,
            _yaml_text(body) if "yaml" in body else None,
            optional_text(body, "name") or "New workflow",
        )
    store.acquire_lease(project.id, key, holder)
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
    if reference.startswith("global:"):
        from relay.workflows.prompts import resolve_prompt
        from relay.workflows.schema import GlobalPrompt

        prompt = resolve_prompt(GlobalPrompt(global_=reference[7:]), relay_root)
        if len(prompt.content.encode()) > 1_048_576:
            message = "These instructions exceed the editor’s size limit."
            raise ConfigError(message)
        return JsonResponse(
            {
                "reference": reference,
                "text": prompt.content,
                "base_hash": prompt.sha256,
                "readonly": True,
            }
        )
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
    DjangoWorkflowStore().require_enabled(project.id, required_text(body, "workflow_key"))
    expected = body.get("project_id")
    if expected is not None and expected != project.id:
        message = "The workflow is bound to a different project than the one selected for this run."
        raise ConfigError(
            message, next_action="Reload the workflow in the selected project before starting."
        )
    config = effective_config(DjangoSettingsStore(), project.id)
    cleanup_value = body.get("cleanup_policy", config.cleanup_policy)
    if not isinstance(cleanup_value, str):
        message = "cleanup_policy must be a string."
        raise ConfigError(message)
    if cleanup_value not in {item.value for item in CleanupPolicy}:
        message = "cleanup_policy must be clean_on_success, retain, or merge_on_success."
        raise ConfigError(message)
    launcher = owner_username(request)
    from relay.workflows.actions.language import load as load_actions
    from relay.workflows.loader import load_workflow, resolve_workflow_path

    source = resolve_workflow_path(relay_root / "workflows", required_text(body, "workflow_key"))
    load_actions(load_workflow(source).text, source=source)
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
            defaults=config.workflow_defaults,
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


@api_errors
@owner_required
@require_POST
def configure_run_recovery(request: HttpRequest, run_id: str) -> HttpResponse:
    run_id = canonical_uuid(run_id, resource="run")
    body = json_body(request)
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        message = "enabled must be a boolean."
        raise ConfigError(message)
    result = DjangoExecutionStore().configure_recovery(
        run_id, enabled, required_text(body, "idempotency_key")
    )
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
    agent, effort, permission_mode = _requested_agent_settings(body)

    def prepare(target: RecoveryTarget) -> None:
        if agent is not None or effort is not None or permission_mode is not None:
            if target.agent_id is None or target.model_value is None:
                message = "Retry configuration can only be changed for an agent step."
                raise ConfigError(message)
            if agent is not None:
                effort_choice = agent.effort
                mode_choice = agent.permission_mode
            else:
                effort_choice = effort.value if effort is not None else None
                mode_choice = permission_mode.value if permission_mode is not None else None
            _validate_agent_choices(
                agent.agent_id if agent is not None else target.agent_id,
                agent.model_value if agent is not None else target.model_value,
                Path(target.project_path),
                effort_choice,
                mode_choice,
            )
        prepare_recovery_workspace(store, target)

    result = rerun_failed_node(
        store,
        run_id,
        required_text(body, "scope_path"),
        required_text(body, "idempotency_key"),
        prepare,
        effort=effort,
        agent=agent,
        permission_mode=permission_mode,
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
    # A supplied null or malformed selector must not widen deletion to the project.
    selected_run = (
        canonical_uuid(required_text(body, "run_id"), resource="run") if "run_id" in body else None
    )
    deleted = DjangoExecutionStore().clean_project_data(
        project.id,
        required_text(body, "scope"),
        run_id=selected_run,
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
