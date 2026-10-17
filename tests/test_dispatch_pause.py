"""Owner holds preserve active work and allow validated settings before admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path

from django.db import connections
from django.test import Client
import pytest

from relay.agents.driver import AgentObservationStore, RoutedAgentNodeDriver
from relay.agents.models import AgentConfiguration
from relay.constants import DEFAULT_UNSTARTED_HANDOFF_PROMPT
from relay.execution.control import ControlResult
from relay.execution.nodes import node_executors
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.web.models import (
    Artifact,
    DispatchClaim,
    NodeAttempt,
    NodeRun,
    Run,
    RunSnapshot,
)
from relay.web.repositories import DjangoExecutionStore
from relay.workflows.schema import AgentNode
from tests.support import FakeAgents, InlineEngine, RegistryNetwork, RelayProject


def post(client: Client, run_id: str, action: str, body: dict[str, object]) -> tuple[int, object]:
    response = client.post(
        f"/api/runs/{run_id}/{action}", data=json.dumps(body), content_type="application/json"
    )
    return response.status_code, response.json()


@pytest.fixture
def paused_review(
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
    project.write(".relay/prompts/review.md", "Review the committed implementation.\n")
    project.write_workflow(
        "pause",
        json.dumps(
            {
                "jobs": {
                    "main": {
                        "steps": [
                            {
                                "id": "first",
                                "uses": "relay/agent@v1",
                                "with": {"agent": "codex", "model": "m2"},
                            },
                            {
                                "id": "review",
                                "uses": "relay/agent@v1",
                                "with": {
                                    "agent": "codex",
                                    "model": "m2",
                                    "effort": "low",
                                    "prompt-files": "prompts/review.md",
                                },
                            },
                        ]
                    }
                }
            }
        ),
    )
    original = engine.executors
    engine.executors = node_executors(agent_driver=PausingWriter(writes=False))
    run_id = engine.launch(project, "pause")
    engine.drain(run_id)
    engine.executors = original
    client = Client()
    assert (
        client.post(
            "/api/auth/onboard",
            data=json.dumps({"username": "owner", "password": "Relay-Pause-Test-2026!"}),
            content_type="application/json",
        ).status_code
        == 201
    )
    assert post(client, run_id, "pause", {"paused": True, "idempotency_key": "pause-1"}) == (
        202,
        {"result": "accepted"},
    )
    return run_id, client


@dataclass
class PausingWriter:
    """A provider finishes its committed work after the owner holds new steps."""

    writes: bool = True

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        del node
        store = DjangoExecutionStore()
        assert store.configure_dispatch_pause(context.attempt.run_id, True, "pause-writer") is (
            ControlResult.ACCEPTED
        )
        assert NodeAttempt.objects.get(pk=context.attempt.attempt_id).status == "running"
        if self.writes:
            (context.worktree / "implementation.txt").write_bytes(b"State: Finished\n")
        return ExecutionOutcome(OutcomeKind.SUCCEEDED)


def test_pause_preserves_a_running_writers_commit_and_outputs(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    registry_network: RegistryNetwork,
) -> None:
    del registry_network
    fake_agents.install("codex", mode="configuration")
    project.write_workflow(
        "writer",
        (
            "name: Writer\n"
            "jobs:\n"
            "  work:\n"
            "    outputs:\n"
            "      report: ${{ steps.work.outputs.value }}\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/agent@v1\n"
            "      with:\n"
            "        agent: codex\n"
            "        model: m2\n"
            "        report: implementation.txt\n"
            "        label: State\n"
            "  review:\n"
            "    needs:\n"
            "    - work\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/agent@v1\n"
            "      with:\n"
            "        agent: codex\n"
            "        model: m2\n"
        ),
    )
    engine.executors = node_executors(agent_driver=PausingWriter())
    run_id = engine.launch(project, "writer")
    old_head = Run.objects.get(pk=run_id).recorded_head
    engine.drain(run_id)
    work = NodeRun.objects.get(run_id=run_id, scope_path="root.work")
    assert work.status == "succeeded"
    assert work.outputs == {"report": "Finished"}
    artifact = Artifact.objects.get(
        attempt__node_run__scope_path="root.work.work", declared_name="report"
    )
    assert Path(str(artifact.retained_path)).read_bytes() == b"State: Finished\n"
    assert Run.objects.get(pk=run_id).recorded_head != old_head
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.review").status == "pending"
    assert NodeAttempt.objects.filter(node_run=work).count() == 1
    connections.close_all()
    assert Run.objects.get(pk=run_id).dispatch_paused is True


def test_queued_delivery_is_held_and_resume_does_not_duplicate_attempts(
    paused_review: tuple[str, Client], engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.web.views import actions

    run_id, client = paused_review
    claim = DispatchClaim.objects.get(node_run__scope_path="root.main.review")
    assert engine.run_token(claim.claim_token) is None
    assert not NodeAttempt.objects.filter(node_run=claim.node_run).exists()
    claim.refresh_from_db()
    assert claim.state == "dispatched"
    monkeypatch.setattr(actions, "_enqueue_claim", engine.tokens.append)
    assert post(client, run_id, "pause", {"paused": False, "idempotency_key": "resume-1"}) == (
        202,
        {"result": "accepted"},
    )
    engine.advance(run_id)
    engine.drain(run_id)
    assert NodeAttempt.objects.filter(node_run=claim.node_run).count() == 1
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert post(client, run_id, "pause", {"paused": True, "idempotency_key": "resume-1"}) == (
        202,
        {"result": "already_applied"},
    )
    assert Run.objects.get(pk=run_id).dispatch_paused is False


def test_pause_inside_a_scope_yields_and_resume_keeps_the_parent_attempt(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    registry_network: RegistryNetwork,
) -> None:
    del registry_network
    fake_agents.install("codex", mode="configuration")
    project.write_workflow(
        "child",
        (
            "name: Child\n"
            "on: workflow_call\n"
            "jobs:\n"
            "  work:\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/agent@v1\n"
            "      with:\n"
            "        agent: codex\n"
            "        model: m2\n"
            "  after:\n"
            "    needs:\n"
            "    - work\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/command@v1\n"
            "      with:\n"
            '        argv: \'["git", "status"]\'\n'
        ),
    )
    project.write_workflow(
        "parent",
        "jobs: {scope: {uses: ./.relay/workflows/child.yaml}}\n",
    )
    engine.executors = node_executors(agent_driver=PausingWriter(writes=False))
    run_id = engine.launch(project, "parent")
    engine.drain(run_id)
    parent = NodeRun.objects.get(run_id=run_id, scope_path="root.scope")
    assert parent.status == "waiting"
    assert NodeAttempt.objects.filter(node_run=parent).count() == 1
    assert not NodeAttempt.objects.filter(node_run__scope_path="root.scope.after").exists()
    engine.store.configure_dispatch_pause(run_id, False, "resume-scope")
    engine.tokens.extend(engine.store.pending_dispatch_tokens(run_id))
    engine.drain(run_id)
    parent.refresh_from_db()
    assert parent.status == "succeeded"
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert NodeAttempt.objects.filter(node_run=parent).count() == 1


@pytest.mark.parametrize(
    "choices",
    [
        {"effort": "medium", "permission_mode": None},
        {"agent_id": "claude", "model": "m1", "effort": "high", "permission_mode": "auto"},
        {"agent_id": "antigravity", "model": "gemini-test-low", "permission_mode": "auto_approve"},
        {"agent_id": "codex", "model": "m1", "handoff_prompt": "Use the saved implementation."},
    ],
)
def test_pending_settings_reach_the_new_provider_without_repeating_completed_work(
    paused_review: tuple[str, Client],
    engine: InlineEngine,
    fake_agents: FakeAgents,
    choices: dict[str, object],
) -> None:
    run_id, client = paused_review
    provider = choices.get("agent_id", "codex")
    assert isinstance(provider, str)
    fake_agents.install(provider, mode="configuration")
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    frozen = (snapshot.route_table, snapshot.resolved_prompts, snapshot.hashes)
    head = Run.objects.get(pk=run_id).recorded_head
    body = {"scope_path": "root.main.review", "idempotency_key": "settings-1", **choices}
    assert post(client, run_id, "step-settings", body) == (202, {"result": "accepted"})
    assert post(client, run_id, "step-settings", {**body, "effort": "low"}) == (
        202,
        {"result": "already_applied"},
    )
    connections.close_all()
    detail = client.get(f"/api/runs/{run_id}").json()["run"]
    assert detail["dispatch_paused"] is True
    review = next(node for node in detail["nodes"] if node["scope_path"] == "root.main.review")
    settings = review["pending_settings"]
    assert settings["agent_id"] == provider
    assert settings["model_value"] == choices.get("model", "m2")
    assert not NodeAttempt.objects.filter(node_run__scope_path="root.main.review").exists()
    assert (
        engine.store.configure_dispatch_pause(run_id, False, "resume-1") is ControlResult.ACCEPTED
    )
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    attempt = NodeAttempt.objects.get(node_run__scope_path="root.main.review")
    assert (attempt.agent_id, attempt.model_value) == (provider, choices.get("model", "m2"))
    assert NodeAttempt.objects.filter(node_run__scope_path="root.main.first").count() == 1
    assert Run.objects.get(pk=run_id).recorded_head == head
    snapshot.refresh_from_db()
    assert (snapshot.route_table, snapshot.resolved_prompts, snapshot.hashes) == frozen
    transcript = json.dumps(fake_agents.messages(), ensure_ascii=False)
    assert "Review the committed implementation." in transcript
    if "model" in choices:
        assert choices.get("handoff_prompt", DEFAULT_UNSTARTED_HANDOFF_PROMPT) in transcript
    else:
        assert DEFAULT_UNSTARTED_HANDOFF_PROMPT not in transcript


@pytest.mark.parametrize(
    ("changes", "status"),
    [({}, 400), ({"effort": "unsupported"}, 422), ({"handoff_prompt": "Text"}, 400)],
)
def test_invalid_pending_choices_preserve_the_held_step(
    paused_review: tuple[str, Client], changes: dict[str, object], status: int
) -> None:
    run_id, client = paused_review
    response = post(
        client,
        run_id,
        "step-settings",
        {
            "scope_path": "root.main.review",
            "idempotency_key": "settings-1",
            **changes,
        },
    )
    assert response[0] == status
    assert Run.objects.get(pk=run_id).dispatch_paused is True
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main.review").retry_options == {}
    assert not NodeAttempt.objects.filter(node_run__scope_path="root.main.review").exists()


@pytest.mark.parametrize("target", ["root.main.first", "root.missing"])
def test_completed_or_missing_steps_cannot_receive_pending_settings(
    paused_review: tuple[str, Client], target: str
) -> None:
    run_id, client = paused_review
    assert (
        post(
            client,
            run_id,
            "step-settings",
            {
                "scope_path": target,
                "idempotency_key": "settings-1",
                "effort": "medium",
            },
        )[0]
        == 409
    )


def test_probe_race_with_owner_resume_rejects_the_stale_choice(
    paused_review: tuple[str, Client], engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.web.views import actions

    run_id, client = paused_review
    probe = actions.probe_agent_configuration

    def resume_during_probe(
        agent_id: str,
        model_value: str,
        cwd: Path,
        *,
        observation_store: AgentObservationStore | None = None,
    ) -> AgentConfiguration:
        result = probe(agent_id, model_value, cwd, observation_store=observation_store)
        engine.store.configure_dispatch_pause(run_id, False, "resume-during-probe")
        return result

    monkeypatch.setattr(actions, "probe_agent_configuration", resume_during_probe)
    assert post(
        client,
        run_id,
        "step-settings",
        {
            "scope_path": "root.main.review",
            "idempotency_key": "settings-1",
            "effort": "medium",
        },
    ) == (409, {"result": "stale"})
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main.review").retry_options == {}


def test_active_and_interrupted_attempts_keep_their_selection(
    paused_review: tuple[str, Client],
    engine: InlineEngine,
) -> None:
    run_id, client = paused_review
    engine.store.configure_dispatch_pause(run_id, False, "resume-1")
    claim = DispatchClaim.objects.get(node_run__scope_path="root.main.review")
    attempt = engine.store.claim_dispatch(claim.claim_token, engine.worker_id).attempt
    assert attempt is not None
    engine.store.configure_dispatch_pause(run_id, True, "pause-active")
    body = {"scope_path": "root.main.review", "idempotency_key": "settings-1", "effort": "medium"}
    assert post(client, run_id, "step-settings", body)[0] == 409
    assert NodeAttempt.objects.get(pk=attempt.attempt_id).status == "running"
    engine.store.interrupt_active_attempts()
    assert NodeRun.objects.get(pk=attempt.node_run_id).status == "pending"
    assert post(client, run_id, "step-settings", body)[0] == 409
    assert NodeRun.objects.get(pk=attempt.node_run_id).retry_options == {}


def test_dispatch_hold_duration_is_durable_and_idempotent(
    paused_review: tuple[str, Client], engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.utils import timezone

    run_id, _client = paused_review
    run = Run.objects.get(pk=run_id)
    start = run.dispatch_paused_at
    assert start is not None
    later = start + timedelta(minutes=5)
    monkeypatch.setattr(timezone, "now", lambda: later)
    assert (
        engine.store.configure_dispatch_pause(run_id, True, "same-hold") is ControlResult.ACCEPTED
    )
    assert Run.objects.get(pk=run_id).dispatch_paused_at == start
    assert (
        engine.store.configure_dispatch_pause(run_id, False, "resume-timing")
        is ControlResult.ACCEPTED
    )
    assert (
        engine.store.configure_dispatch_pause(run_id, False, "resume-timing")
        is ControlResult.ALREADY_APPLIED
    )
    run.refresh_from_db()
    assert run.dispatch_paused_seconds == 300
    assert run.dispatch_paused_at is None
