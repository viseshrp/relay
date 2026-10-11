"""Owner retry choices reach new attempts without rewriting launch evidence."""

from __future__ import annotations

from datetime import timedelta
import json

from django.db import connections
from django.test import Client
import pytest

from relay.agents.driver import RoutedAgentNodeDriver
from relay.agents.usage_limits import ProviderUsageLimit
from relay.constants import DEFAULT_RETRY_HANDOFF_PROMPT, RETRY_HANDOFF_MAX_BYTES
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
    database_threads: None,
) -> tuple[str, Client]:
    del registry_network, database_threads
    fake_agents.install("codex", mode="configuration")
    monkeypatch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    project.write_workflow(
        "retry-effort",
        "version: 1\nname: Retry effort\nmodel: m2\nagents: [codex]\nnodes:\n"
        "  first: {type: command, run: [git, status]}\n"
        "  review:\n    type: agent\n    needs: [first]\n    permission_profile: interactive\n"
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


def test_every_failed_agent_has_its_own_retry_choices(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    registry_network: RegistryNetwork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del registry_network
    fake_agents.install("codex", mode="configuration")
    monkeypatch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    project.write_workflow(
        "parallel-failures",
        "version: 1\nname: Parallel failures\nmodel: m2\nagents: [codex]\nnodes:\n"
        "  first: {type: agent, agent_options: {codex: {effort: low}}}\n"
        "  second: {type: agent, agent_options: {codex: {permission_mode: ask}}}\n",
    )
    run_id = engine.launch(project, "parallel-failures")
    claims = [
        engine.store.claim_dispatch(token, engine.worker_id).attempt
        for token in tuple(engine.tokens)
    ]
    assert len(claims) == 2
    for claim in claims:
        assert claim is not None
        engine.store.finish_attempt(
            claim.attempt_id,
            ExecutionOutcome(OutcomeKind.FAILED, error_code="agent_auth_error"),
            claim.starting_head,
        )
        engine.store.release_attempt_lock(claim.attempt_id)
    client = Client()
    client.post(
        "/api/auth/onboard",
        data=json.dumps({"username": "owner", "password": "Relay-Retry-Test-2026!"}),
        content_type="application/json",
    )
    detail = client.get(f"/api/runs/{run_id}").json()["run"]
    assert detail["status"] == "failed"
    assert detail["problem"]["scope_path"] == "root.first"
    choices = {node["scope_path"]: node["retry_settings"] for node in detail["nodes"]}
    assert (choices["root.first"]["effort"], choices["root.first"]["permission_mode"]) == (
        "low",
        None,
    )
    assert (choices["root.second"]["effort"], choices["root.second"]["permission_mode"]) == (
        None,
        "ask",
    )
    assert choices["root.second"]["default_handoff_prompt"] == DEFAULT_RETRY_HANDOFF_PROMPT
    # The second failure can be retried independently of the initiating notice.
    assert retry(client, run_id, {"scope_path": "root.second", "effort": "medium"})[0] == 202
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.second").retry_options == {
        "effort": "medium"
    }
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.first").status == "failed"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"effort": "medium"},
        {"effort": None},
        {"permission_mode": "ask"},
        {"permission_mode": None},
        {"effort": "medium", "permission_mode": "ask"},
    ],
)
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
    expected = [("model", "m2")]
    permission_mode = body.get("permission_mode", "auto")
    if permission_mode is not None:
        expected.append(("mode", permission_mode))
    effort = body.get("effort", "low")
    if effort is not None:
        expected.append(("reasoning_effort", effort))
    assert assignments[-len(expected) :] == expected
    event = RunEvent.objects.get(run_id=run_id, type="run.rerun")
    assert event.payload["retry_options"] == body
    assert DEFAULT_RETRY_HANDOFF_PROMPT not in json.dumps(prompt, ensure_ascii=False)


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


@pytest.mark.parametrize(
    "body",
    [
        {"agent_id": "claude", "model": "m1", "effort": "high", "permission_mode": "auto"},
        {"agent_id": "codex", "model": "m1"},
        {
            "agent_id": "antigravity",
            "model": "gemini-test-low",
            "effort": "low",
            "permission_mode": "auto_approve",
        },
    ],
)
def test_owner_handoff_executes_the_selected_provider_without_rewriting_completed_work(
    failed_agent: tuple[str, Client],
    engine: InlineEngine,
    fake_agents: FakeAgents,
    body: dict[str, str],
) -> None:
    run_id, client = failed_agent
    fake_agents.install(body["agent_id"], mode="configuration")
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    original = (snapshot.route_table, snapshot.hashes, snapshot.resolved_prompts)
    upstream = NodeRun.objects.get(run_id=run_id, scope_path="root.first")
    old_attempt = NodeAttempt.objects.get(
        node_run__run_id=run_id, node_run__scope_path="root.review"
    )
    head = Run.objects.get(pk=run_id).recorded_head
    assert retry(client, run_id, body) == (202, {"result": "accepted"})
    assert retry(client, run_id, {"agent_id": "codex", "model": "m2"}) == (
        202,
        {"result": "already_applied"},
    )
    connections.close_all()
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    token = DispatchClaim.objects.get(node_run__scope_path="root.review", state="dispatched")
    engine.run_token(token.claim_token)
    assert run_status(run_id) == "succeeded"
    new_attempt = NodeAttempt.objects.get(node_run=old_attempt.node_run, attempt_number=2)
    assert (new_attempt.agent_id, new_attempt.model_value) == (body["agent_id"], body["model"])
    old_attempt.refresh_from_db()
    assert (old_attempt.agent_id, old_attempt.model_value, old_attempt.error_code) == (
        "codex",
        "m2",
        "agent_auth_error",
    )
    snapshot.refresh_from_db()
    assert (snapshot.route_table, snapshot.hashes, snapshot.resolved_prompts) == original
    upstream.refresh_from_db()
    assert upstream.status == "succeeded"
    assert NodeAttempt.objects.filter(node_run=upstream).count() == 1
    assert Run.objects.get(pk=run_id).recorded_head == head
    event = RunEvent.objects.get(run_id=run_id, type="run.rerun")
    assert event.payload["retry_options"] == {
        "selected_agent": body["agent_id"],
        "model_value": body["model"],
        "effective_agent_order": [body["agent_id"]],
        "effort": body.get("effort"),
        "permission_mode": body.get("permission_mode"),
        "permission_profile": None,
        "handoff_prompt": DEFAULT_RETRY_HANDOFF_PROMPT,
    }
    if body["agent_id"] == "antigravity":
        argv = next(item["argv"] for item in fake_agents.messages() if "argv" in item)
        assert "--dangerously-skip-permissions" in argv
        prompt = next(
            item["input"]["message"]["content"]
            for item in fake_agents.messages()
            if "input" in item
        )
        assert DEFAULT_RETRY_HANDOFF_PROMPT in prompt
    else:
        assignments = [
            (item["params"]["configId"], item["params"]["value"])
            for item in fake_agents.messages()
            if item.get("method") == "session/set_config_option"
        ]
        expected = [("model", body["model"])]
        if "permission_mode" in body:
            expected.append(("mode", body["permission_mode"]))
        if "effort" in body:
            expected.append(("reasoning_effort", body["effort"]))
        assert assignments[-len(expected) :] == expected
        prompt = next(
            item for item in fake_agents.messages() if item.get("method") == "session/prompt"
        )
        assert DEFAULT_RETRY_HANDOFF_PROMPT in json.dumps(prompt, ensure_ascii=False)


@pytest.mark.parametrize(
    ("body", "expected_status"),
    [
        ({"agent_id": "claude"}, 400),
        ({"model": "m1"}, 400),
        ({"handoff_prompt": "Continue."}, 400),
        ({"agent_id": "claude", "model": "missing"}, 422),
        ({"agent_id": "claude", "model": "m1", "effort": "ultra"}, 422),
        ({"agent_id": "antigravity", "model": "gemini-test-low", "permission_mode": "auto"}, 422),
        ({"agent_id": "codex", "model": "m2", "handoff_prompt": "Continue."}, 400),
        (
            {
                "agent_id": "claude",
                "model": "m1",
                "handoff_prompt": "x" * (RETRY_HANDOFF_MAX_BYTES + 1),
            },
            400,
        ),
        (
            {
                "agent_id": "claude",
                "model": "m1",
                "handoff_prompt": "é" * (RETRY_HANDOFF_MAX_BYTES // 2 + 1),
            },
            400,
        ),
    ],
)
def test_invalid_handoff_keeps_the_failed_step_and_its_route_unchanged(
    failed_agent: tuple[str, Client],
    fake_agents: FakeAgents,
    body: dict[str, object],
    expected_status: int,
) -> None:
    run_id, client = failed_agent
    fake_agents.install("claude", mode="configuration")
    fake_agents.install("antigravity", mode="configuration")
    assert retry(client, run_id, body)[0] == expected_status
    assert run_status(run_id) == "failed"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.review").retry_options == {}
    assert (
        NodeAttempt.objects.filter(
            node_run__run_id=run_id, node_run__scope_path="root.review"
        ).count()
        == 1
    )


# Pytest exports case IDs in PYTEST_CURRENT_TEST, which Windows bounds in size.
@pytest.mark.parametrize(
    "instructions",
    [
        "Read REVIEW.md first.\nFinish only the remaining documentation. 🧭",
        "\x01" * RETRY_HANDOFF_MAX_BYTES,
    ],
    ids=["custom-text", "maximum-escaped-bytes"],
)
def test_custom_handoff_replaces_the_default_and_reaches_the_new_provider(
    failed_agent: tuple[str, Client],
    engine: InlineEngine,
    fake_agents: FakeAgents,
    instructions: str,
) -> None:
    run_id, client = failed_agent
    fake_agents.install("antigravity", mode="configuration")
    assert (
        retry(
            client,
            run_id,
            {
                "agent_id": "antigravity",
                "model": "gemini-test-low",
                "permission_mode": "auto_approve",
                "handoff_prompt": instructions,
            },
        )[0]
        == 202
    )
    token = DispatchClaim.objects.get(node_run__scope_path="root.review", state="dispatched")
    connections.close_all()
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    engine.run_token(token.claim_token)
    assert run_status(run_id) == "succeeded"
    prompt = next(
        item["input"]["message"]["content"] for item in fake_agents.messages() if "input" in item
    )
    assert instructions in prompt
    assert DEFAULT_RETRY_HANDOFF_PROMPT not in prompt
    assert (
        RunEvent.objects.get(run_id=run_id, type="run.rerun").payload["retry_options"][
            "handoff_prompt"
        ]
        == instructions
    )


def test_quota_recovery_and_later_effort_changes_keep_the_replacement_provider(
    failed_agent: tuple[str, Client],
    engine: InlineEngine,
    fake_agents: FakeAgents,
    clock: Clock,
) -> None:
    run_id, client = failed_agent
    fake_agents.install("claude", mode="configuration")
    assert (
        retry(client, run_id, {"agent_id": "claude", "model": "m1", "permission_mode": "auto"})[0]
        == 202
    )
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
    assert (recovered.route["selected_agent"], recovered.route["model_value"]) == ("claude", "m1")
    assert recovered.prompt_contents[-1] == DEFAULT_RETRY_HANDOFF_PROMPT
    engine.store.finish_attempt(
        recovered.attempt_id,
        ExecutionOutcome(OutcomeKind.FAILED, error_code="agent_auth_error"),
        recovered.starting_head,
    )
    engine.store.release_attempt_lock(recovered.attempt_id)
    assert (
        retry(
            client,
            run_id,
            {"idempotency_key": "retry-2", "effort": "high", "permission_mode": "ask"},
        )[0]
        == 202
    )
    token = DispatchClaim.objects.get(node_run__scope_path="root.review", state="dispatched")
    final = engine.store.claim_dispatch(token.claim_token, engine.worker_id).attempt
    assert final is not None
    assert (final.route["selected_agent"], final.route["model_value"], final.route["effort"]) == (
        "claude",
        "m1",
        "high",
    )
    assert final.route["permission_mode"] == "ask"
    assert final.prompt_contents[-1] == DEFAULT_RETRY_HANDOFF_PROMPT
