"""Owner permission and form answers across the ACP and durable mailbox boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from acp import RequestError, schema
import pytest

from relay.agents.acp_driver import RelayAcpClient
from relay.agents.models import AgentExecutionContext
from relay.agents.profiles import PROFILES
from relay.constants import CONTROL_CLAIM_STALE_AFTER_SECONDS, EVENT_MAX_PAYLOAD_BYTES
from relay.errors import PersistenceError
from relay.execution.control import ControlResult
from relay.web.models import ControlRequest, HumanInteraction, NodeRun, RunEvent
from relay.web.repositories import DjangoExecutionStore
from tests.support import Clock, run_status


def permission_options() -> list[schema.PermissionOption]:
    return [schema.PermissionOption(optionId="allow", name="Allow once", kind="allow_once")]


def tool_call() -> schema.ToolCallUpdate:
    return schema.ToolCallUpdate(toolCallId="write-report", title="Write report")


def answer_when_requested(
    context: AgentExecutionContext,
    monkeypatch: pytest.MonkeyPatch,
    control_kind: str,
    payload: Mapping[str, object],
) -> None:
    """Stand in for the owner UI, answering after the real store persists the request."""
    runtime = context.attempt.runtime
    persist = runtime.request_agent_interaction

    def request(
        attempt_id: str, kind: str, prompt: str, options: tuple[Mapping[str, object], ...]
    ) -> str:
        interaction = persist(attempt_id, kind, prompt, options)
        result = DjangoExecutionStore().submit_control(
            attempt_id, control_kind, "owner-answer", payload, 600.0
        )
        assert result is ControlResult.ACCEPTED
        return interaction

    monkeypatch.setattr(runtime, "request_agent_interaction", request)


@pytest.mark.parametrize("cancel", [False, True])
def test_acp_permissions_wait_for_the_offered_owner_decision(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    answer_when_requested(
        agent_context,
        monkeypatch,
        "cancel" if cancel else "permission_answer",
        {} if cancel else {"decision": "allow"},
    )
    client = RelayAcpClient(agent_context, PROFILES["codex"])
    client.session_id = "session"

    response = asyncio.run(client.request_permission("session", tool_call(), permission_options()))

    assert response.outcome.outcome == ("cancelled" if cancel else "selected")
    if not cancel:
        assert response.outcome.option_id == "allow"
        assert HumanInteraction.objects.get().status == "answered"
        assert NodeRun.objects.get().status == "running"


@pytest.mark.parametrize(("answer", "action"), [(None, "decline"), ({"ready": True}, "accept")])
def test_acp_form_elicitation_returns_the_owners_form_answer(
    agent_context: AgentExecutionContext,
    monkeypatch: pytest.MonkeyPatch,
    answer: dict[str, object] | None,
    action: str,
) -> None:
    answer_when_requested(agent_context, monkeypatch, "elicitation_answer", {"value": answer})
    client = RelayAcpClient(agent_context, PROFILES["codex"])
    mode = schema.ElicitationFormRequestMode(
        requestId=1, requestedSchema=schema.ElicitationSchema(type="object", properties={})
    )

    response = asyncio.run(client.create_elicitation("Release approval", mode))

    assert response.action == action
    assert HumanInteraction.objects.get().response_payload == {"value": answer}


def test_canceling_a_form_elicitation_returns_the_protocol_cancel_action(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer_when_requested(agent_context, monkeypatch, "cancel", {})
    client = RelayAcpClient(agent_context, PROFILES["codex"])
    mode = schema.ElicitationFormRequestMode(
        requestId=1, requestedSchema=schema.ElicitationSchema(type="object", properties={})
    )
    assert asyncio.run(client.create_elicitation("Release approval", mode)).action == "cancel"


def test_permission_requests_need_an_active_attempt() -> None:
    client = RelayAcpClient(None, PROFILES["codex"])
    client.session_id = "session"
    with pytest.raises(RequestError) as raised:
        asyncio.run(client.request_permission("session", tool_call(), permission_options()))
    assert raised.value.code == -32600


def test_permission_requests_cannot_use_another_attempts_session(
    agent_context: AgentExecutionContext,
) -> None:
    client = RelayAcpClient(agent_context, PROFILES["codex"])
    client.session_id = "session"
    with pytest.raises(RequestError) as raised:
        asyncio.run(client.request_permission("different", tool_call(), permission_options()))
    assert raised.value.code == -32600


@pytest.mark.parametrize(
    ("method", "arguments"),
    [
        ("read_text_file", ("session", "report.txt")),
        ("write_text_file", ("session", "report.txt", "report")),
        ("create_terminal", ("session", "git")),
        ("terminal_output", ("session", "terminal")),
        ("release_terminal", ("session", "terminal")),
        ("wait_for_terminal_exit", ("session", "terminal")),
        ("kill_terminal", ("session", "terminal")),
        ("ext_method", ("custom/method", {})),
    ],
)
def test_unadvertised_acp_filesystem_terminal_and_extension_capabilities_are_rejected(
    method: str, arguments: tuple[object, ...]
) -> None:
    client = RelayAcpClient(None, PROFILES["codex"])
    with pytest.raises(RequestError) as raised:
        asyncio.run(getattr(client, method)(*arguments))
    assert raised.value.code == -32601


@pytest.fixture
def permission_attempt(agent_context: AgentExecutionContext) -> AgentExecutionContext:
    agent_context.attempt.runtime.request_agent_interaction(
        agent_context.attempt.attempt.attempt_id,
        "permission",
        "Write a report?",
        ({"id": "allow", "name": "Allow once", "kind": "allow_once"},),
    )
    return agent_context


@pytest.mark.parametrize(
    "payload", [{"decision": "not-offered"}, {"decision": 1}, {}, {"value": "allow"}]
)
def test_permission_mailboxes_reject_answers_that_do_not_name_an_offered_option(
    permission_attempt: AgentExecutionContext, payload: dict[str, object]
) -> None:
    result = DjangoExecutionStore().submit_control(
        permission_attempt.attempt.attempt.attempt_id,
        "permission_answer",
        "invalid-option",
        payload,
        600.0,
    )
    assert result is ControlResult.INVALID


def test_an_agent_cannot_open_two_pending_owner_interactions(
    permission_attempt: AgentExecutionContext,
) -> None:
    with pytest.raises(PersistenceError):
        permission_attempt.attempt.runtime.request_agent_interaction(
            permission_attempt.attempt.attempt.attempt_id, "elicitation", "Another answer?", ()
        )


def submit_permission(context: AgentExecutionContext, *, ttl: float = 600.0) -> None:
    result = DjangoExecutionStore().submit_control(
        context.attempt.attempt.attempt_id,
        "permission_answer",
        "permission-answer",
        {"decision": "allow"},
        ttl,
    )
    assert result is ControlResult.ACCEPTED


def test_only_the_owning_worker_can_claim_an_attempts_answer(
    permission_attempt: AgentExecutionContext,
) -> None:
    submit_permission(permission_attempt)
    assert (
        DjangoExecutionStore().claim_next_control(
            permission_attempt.attempt.attempt.attempt_id, "different-worker"
        )
        is None
    )


def test_expired_answers_are_discarded_instead_of_replayed(
    permission_attempt: AgentExecutionContext, clock: Clock
) -> None:
    submit_permission(permission_attempt, ttl=1.0)
    clock.advance(2)
    attempt = permission_attempt.attempt.attempt
    assert DjangoExecutionStore().claim_next_control(attempt.attempt_id, attempt.worker_id) is None
    assert ControlRequest.objects.get().state == "stale"


def test_a_lost_mailbox_lease_is_recoverable_while_its_worker_is_alive(
    permission_attempt: AgentExecutionContext, clock: Clock
) -> None:
    submit_permission(permission_attempt)
    store = DjangoExecutionStore()
    attempt = permission_attempt.attempt.attempt
    control = store.claim_next_control(attempt.attempt_id, attempt.worker_id)
    assert control is not None
    clock.advance(CONTROL_CLAIM_STALE_AFTER_SECONDS + 1)
    store.heartbeat_attempt(attempt.attempt_id, attempt.worker_id)

    recovered = store.recover_control_claims()

    assert (recovered.returned_to_pending, recovered.marked_stale) == (1, 0)
    replay = store.claim_next_control(attempt.attempt_id, attempt.worker_id)
    assert replay is not None and replay.request_id == control.request_id


def test_an_expired_claim_is_marked_stale_by_reconciliation(
    permission_attempt: AgentExecutionContext, clock: Clock
) -> None:
    submit_permission(permission_attempt, ttl=1.0)
    attempt = permission_attempt.attempt.attempt
    store = DjangoExecutionStore()
    assert store.claim_next_control(attempt.attempt_id, attempt.worker_id) is not None
    clock.advance(2)
    recovered = store.recover_control_claims()
    assert (recovered.returned_to_pending, recovered.marked_stale) == (0, 1)


def test_an_answer_cannot_be_applied_by_another_worker(
    permission_attempt: AgentExecutionContext,
) -> None:
    submit_permission(permission_attempt)
    attempt = permission_attempt.attempt.attempt
    store = DjangoExecutionStore()
    control = store.claim_next_control(attempt.attempt_id, attempt.worker_id)
    assert control is not None
    assert not store.apply_control(control.request_id, "different-worker")
    assert HumanInteraction.objects.get().status == "pending"


def test_an_applied_owner_answer_resumes_the_run_and_cannot_be_applied_twice(
    permission_attempt: AgentExecutionContext,
) -> None:
    submit_permission(permission_attempt)
    attempt = permission_attempt.attempt.attempt
    store = DjangoExecutionStore()
    control = store.claim_next_control(attempt.attempt_id, attempt.worker_id)
    assert control is not None
    assert store.apply_control(control.request_id, attempt.worker_id)
    assert not store.apply_control(control.request_id, attempt.worker_id)
    assert run_status(attempt.run_id) == "running"


def test_large_owner_interactions_remain_bounded_in_the_browser_event_stream(
    agent_context: AgentExecutionContext,
) -> None:
    import json

    store = DjangoExecutionStore()
    store.request_agent_interaction(
        agent_context.attempt.attempt.attempt_id,
        "permission",
        "😀\\" * EVENT_MAX_PAYLOAD_BYTES,
        tuple({"id": str(index), "name": "x" * 1000} for index in range(100)),
    )
    event = RunEvent.objects.get(type="permission.requested")
    assert (
        len(json.dumps(event.payload, ensure_ascii=False).encode("utf-8"))
        <= EVENT_MAX_PAYLOAD_BYTES
    )
    assert event.payload["options_truncated"] is True
