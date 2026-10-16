"""Provider terminal results settle through the pipeline without repair attempts."""

import json

import pytest

from relay.agents.driver import RoutedAgentNodeDriver
from relay.execution.nodes import node_executors
from relay.web.models import AutomaticRetry, NodeAttempt, Run, RunEvent, UsageRetry
from relay.web.repositories import DjangoReadStore
from tests.support import FakeAgents, InlineEngine, RelayProject


@pytest.mark.parametrize(
    "agent,mode,provider_reason",
    [
        ("codex", "stop-refusal", "refusal"),
        ("codex", "stop-max_tokens", "max_tokens"),
        ("codex", "stop-max_turn_requests", "max_turn_requests"),
        ("codex", "stop-cancelled", "cancelled"),
        ("antigravity", "timeout", "ERROR"),
        ("antigravity", "error-text", "ERROR"),
        ("antigravity", "canceled", "CANCELED"),
        ("antigravity", "interrupted", "INTERRUPTED"),
        ("antigravity", "nonzero-success", "SUCCESS"),
    ],
)
def test_provider_failures_stop_once_with_recovery_enabled(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    agent: str,
    mode: str,
    provider_reason: str,
) -> None:
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    fake_agents.install(agent, mode=mode)
    project.write_workflow(
        "provider-result",
        json.dumps(
            {
                "recovery": {"enabled": True, "max_retries": 2},
                "jobs": {
                    "work": {
                        "steps": [
                            {
                                "id": "agent",
                                "uses": "relay/agent@v1",
                                "with": {"agent": agent, "model": "m1", "auto-retry": True},
                            }
                        ]
                    }
                },
            }
        ),
    )
    run_id = engine.launch(project, "provider-result")
    engine.drain(run_id)
    assert engine.store.resume_automatic_retries() == 0
    assert engine.store.resume_usage_retries() == 0
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "failed"
    attempts = NodeAttempt.objects.filter(
        node_run__run_id=run_id, node_run__scope_path="root.work.agent"
    )
    attempt = attempts.get()
    assert attempt.stop_reason == "failed"
    assert attempt.error_code == "agent_execution_error"
    assert not AutomaticRetry.objects.filter(attempt__node_run__run_id=run_id).exists()
    assert not UsageRetry.objects.filter(run_id=run_id).exists()
    ended = RunEvent.objects.get(attempt=attempt, type="attempt.ended")
    assert ended.payload["provider_stop_reason"] == provider_reason
    assert provider_reason in ended.payload["error_message"]
    assert not RunEvent.objects.filter(run_id=run_id, type="run.interrupted").exists()
    reader = DjangoReadStore()
    run = reader.monitor(run_id)["run"]
    assert isinstance(run, dict)
    problem = run["problem"]
    assert isinstance(problem, dict)
    assert problem["provider_stop_reason"] == provider_reason
    job, _ = reader.run_job(run_id, "root.work.agent", since=0, limit=200)
    latest = job["latest_attempt"]
    assert isinstance(latest, dict)
    assert latest["provider_stop_reason"] == provider_reason
