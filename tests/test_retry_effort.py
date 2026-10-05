"""Owner retry choices reach new attempts without rewriting launch evidence."""

from __future__ import annotations

from datetime import timedelta
import json

from django.db import connections
from django.test import Client
import pytest

from relay.agents.driver import RoutedAgentNodeDriver
from relay.agents.usage_limits import ProviderUsageLimit
from relay.execution.nodes import node_executors
from relay.execution.runner import ExecutionOutcome, OutcomeKind
from relay.execution.scheduler import dispatch_ready_nodes
from relay.web.models import DispatchClaim, NodeAttempt, NodeRun, Run, RunEvent, RunSnapshot
from tests.support import Clock, FakeAgents, InlineEngine, RegistryNetwork, RelayProject, run_status


@pytest.fixture
def failed_agent(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    registry_network: RegistryNetwork,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, Client]:
    del registry_network
    fake_agents.install("codex", mode="configuration")
    monkeypatch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    project.write_workflow(
        "retry-effort",
        "version: 1\nname: Retry effort\nmodel: m2\nagents: [codex]\nnodes:\n"
        "  first: {type: command, run: [git, status]}\n"
        "  review:\n    type: agent\n    needs: [first]\n"
        "    agent_options:\n      codex: {effort: low, permission_mode: auto}\n",
    )
    run_id = engine.launch(project, "retry-effort")
    engine.run_token(engine.tokens.popleft())
    dispatch_ready_nodes(engine.store, run_id, engine.tokens.append)
    claimed = engine.store.claim_dispatch(engine.tokens.popleft(), engine.worker_id).attempt
    if claimed is None:
        pytest.fail("The agent step was not claimed")
    engine.store.finish_attempt(
        claimed.attempt_id,
        ExecutionOutcome(OutcomeKind.FAILED, error_code="agent_auth_error"),
        claimed.starting_head,
    )
    engine.store.release_attempt_lock(claimed.attempt_id)
    client = Client()
    response = client.post(
        "/api/auth/onboard",
        data=json.dumps({"username": "owner", "password": "Relay-Retry-Test-2026!"}),
        content_type="application/json",
    )
    if response.status_code != 201:
        pytest.fail("The test owner was not created")
    return run_id, client


def retry(client: Client, run_id: str, body: dict[str, object]) -> tuple[int, dict[str, object]]:
    response = client.post(
        f"/api/runs/{run_id}/rerun-node",
        data=json.dumps({"scope_path": "root.review", "idempotency_key": "retry-1", **body}),
        content_type="application/json",
    )
    return response.status_code, response.json()


@pytest.mark.parametrize("body", [{}, {"effort": "medium"}, {"effort": None}])
def test_a_retry_applies_only_the_requested_effort_and_preserves_prior_evidence(
    failed_agent: tuple[str, Client],
    engine: InlineEngine,
    fake_agents: FakeAgents,
    body: dict[str, object],
) -> None:
    run_id, client = failed_agent
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    original_route = snapshot.route_table
    hashes = snapshot.hashes
    prior_attempts = list(NodeAttempt.objects.values_list("id", "node_run__scope_path", "status"))
    head = Run.objects.get(pk=run_id).recorded_head
    assert retry(client, run_id, body) == (202, {"result": "accepted"})
    # A duplicate request cannot replace the first choice or create a second attempt.
    assert retry(client, run_id, {"effort": "low"}) == (202, {"result": "already_applied"})
    connections.close_all()
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    token = DispatchClaim.objects.get(node_run__scope_path="root.review", state="dispatched")
    engine.run_token(token.claim_token)
    assert run_status(run_id) == "succeeded"
    snapshot.refresh_from_db()
    assert (snapshot.route_table, snapshot.hashes) == (original_route, hashes)
    assert Run.objects.get(pk=run_id).recorded_head == head
    assert (
        list(
            NodeAttempt.objects.filter(pk__in=[item[0] for item in prior_attempts]).values_list(
                "id", "node_run__scope_path", "status"
            )
        )
        == prior_attempts
    )
    prompt = [item for item in fake_agents.messages() if item.get("method") == "session/prompt"]
    assert len(prompt) == 1
    assignments = [
        (item["params"]["configId"], item["params"]["value"])
        for item in fake_agents.messages()
        if item.get("method") == "session/set_config_option"
    ]
    expected = [("model", "m2"), ("mode", "auto")]
    effort = body.get("effort", "low")
    if effort is not None:
        expected.append(("reasoning_effort", effort))
    assert assignments[-len(expected) :] == expected
    event = RunEvent.objects.get(run_id=run_id, type="run.rerun")
    assert event.payload["retry_options"] == body


@pytest.mark.parametrize(("effort", "expected_status"), [("ultra", 422), ("", 400), (3, 400)])
def test_invalid_effort_does_not_reopen_or_modify_a_failed_step(
    failed_agent: tuple[str, Client], effort: object, expected_status: int
) -> None:
    run_id, client = failed_agent
    status, _body = retry(client, run_id, {"effort": effort})
    assert status == expected_status
    assert run_status(run_id) == "failed"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.review").retry_options == {}
    assert not RunEvent.objects.filter(run_id=run_id, type="run.rerun").exists()


def test_native_quota_recovery_preserves_the_owners_retry_effort(
    failed_agent: tuple[str, Client], engine: InlineEngine, clock: Clock
) -> None:
    run_id, client = failed_agent
    assert retry(client, run_id, {"effort": "medium"})[0] == 202
    token = DispatchClaim.objects.get(node_run__scope_path="root.review", state="dispatched")
    claimed = engine.store.claim_dispatch(token.claim_token, engine.worker_id).attempt
    assert claimed is not None
    engine.store.finish_attempt(
        claimed.attempt_id,
        ExecutionOutcome(
            OutcomeKind.FAILED,
            error_code="agent_usage_limit",
            usage_limit=ProviderUsageLimit(clock.instant + timedelta(minutes=10), "session"),
        ),
        claimed.starting_head,
    )
    engine.store.release_attempt_lock(claimed.attempt_id)
    clock.advance(601)
    connections.close_all()
    assert engine.store.resume_usage_retries() == 1
    token = engine.store.create_dispatch(str(claimed.node_run_id))
    assert token is not None
    recovered = engine.store.claim_dispatch(token, engine.worker_id).attempt
    assert recovered is not None
    assert recovered.route["effort"] == "medium"
    assert RunSnapshot.objects.get(run_id=run_id).route_table["root.review"]["effort"] == "low"


def test_a_command_failure_rejects_an_effort_override(
    project: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    project.write_workflow(
        "command-failure",
        "version: 1\nname: Command failure\nnodes:\n"
        "  review: {type: command, run: [git, not-a-command]}\n",
    )
    run_id = engine.launch(project, "command-failure")
    engine.drain(run_id)
    client = Client()
    client.post(
        "/api/auth/onboard",
        data=json.dumps({"username": "owner", "password": "Relay-Retry-Test-2026!"}),
        content_type="application/json",
    )
    status, _body = retry(client, run_id, {"effort": "medium"})
    assert status == 400
    assert run_status(run_id) == "failed"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.review").retry_options == {}
