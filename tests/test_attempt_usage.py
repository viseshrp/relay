"""Provider-reported tokens and cost stay diagnostic attempt data."""

from __future__ import annotations

import asyncio
import json

from django.db import connections
import pytest

from relay.agents.acp_driver import AcpDriver
from relay.agents.driver import RoutedAgentNodeDriver
from relay.agents.events import AgentEvent
from relay.agents.models import AgentExecutionContext, AgentResult
from relay.agents.profiles import PROFILES
from relay.agents.usage import AttemptUsage
from relay.execution.nodes import node_executors
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.web.models import NodeAttempt
from relay.web.repositories import DjangoReadStore, _attempt_usage_fields
from relay.workflows.schema import AgentNode
from tests.support import FakeAgents, InlineEngine, RelayProject


def _execute(driver: AcpDriver, context: AgentExecutionContext) -> AgentResult:
    async def collect() -> tuple[list[AgentEvent], AgentResult]:
        try:
            events = [event async for event in driver.start_attempt(context)]
            return events, await driver.finalize()
        finally:
            await asyncio.to_thread(connections.close_all)

    return asyncio.run(collect())[1]


def _usage_workflow(project: RelayProject) -> None:
    project.write_workflow(
        "usage",
        json.dumps(
            {
                "jobs": {
                    "work": {
                        "steps": [
                            {
                                "id": "agent",
                                "uses": "relay/agent@v1",
                                "with": {"agent": "codex", "model": "m1"},
                            }
                        ]
                    }
                }
            }
        ),
    )


def test_acp_attempt_reports_turn_tokens_and_session_cost(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ACP_USAGE", "1")
    result = _execute(AcpDriver(PROFILES["codex"], agent_context.command), agent_context)
    assert result.succeeded
    assert result.usage == AttemptUsage(
        input_tokens=100,
        output_tokens=20,
        thought_tokens=5,
        cached_read_tokens=30,
        cached_write_tokens=None,
        total_tokens=155,
        cost_amount=0.25,
        cost_currency="USD",
    )


def test_acp_feedback_turns_add_tokens_and_keep_the_latest_cumulative_cost(
    agent_context: AgentExecutionContext,
    fake_agents: FakeAgents,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_agent_controls import answer_when_requested

    monkeypatch.setenv("FAKE_ACP_USAGE", "1")
    fake_agents.install("codex", mode="feedback")
    answer_when_requested(
        agent_context,
        monkeypatch,
        "permission_answer",
        {"decision": "allow", "feedback": "Check the error paths."},
    )
    result = _execute(AcpDriver(PROFILES["codex"], agent_context.command), agent_context)
    assert result.succeeded
    assert result.usage is not None
    assert result.usage.input_tokens == 200
    assert result.usage.total_tokens == 310
    assert result.usage.cost_amount == 0.5


def test_acp_attempt_without_reported_usage_stays_unknown(
    agent_context: AgentExecutionContext,
) -> None:
    result = _execute(AcpDriver(PROFILES["codex"], agent_context.command), agent_context)
    assert result.succeeded
    assert result.usage is None


def test_reported_usage_reaches_the_attempt_record_and_run_totals(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_ACP_USAGE", "1")
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    fake_agents.install("codex")
    _usage_workflow(project)
    run_id = engine.launch(project, "usage")
    engine.drain(run_id)
    attempt = NodeAttempt.objects.get(
        node_run__run_id=run_id, node_run__scope_path="root.work.agent"
    )
    assert (attempt.input_tokens, attempt.cached_write_tokens) == (100, None)
    assert (attempt.cost_amount, attempt.cost_currency) == (0.25, "USD")
    reader = DjangoReadStore()
    job, _ = reader.run_job(run_id, "root.work.agent", since=0, limit=200)
    latest = job["latest_attempt"]
    assert isinstance(latest, dict)
    assert latest["usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "thought_tokens": 5,
        "cached_read_tokens": 30,
        "cached_write_tokens": None,
        "total_tokens": 155,
        "cost": {"amount": 0.25, "currency": "USD"},
    }
    run = reader.monitor(run_id)["run"]
    assert isinstance(run, dict)
    usage = run["usage"]
    assert isinstance(usage, dict)
    assert usage["input_tokens"] == 100
    assert usage["cached_write_tokens"] is None
    assert usage["costs"] == [{"currency": "USD", "amount": 0.25}]
    assert usage["attempts_reported"] >= 1


def test_run_totals_skip_unreported_attempts_and_separate_currencies(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents
) -> None:
    engine.executors = node_executors(agent_driver=RoutedAgentNodeDriver())
    fake_agents.install("codex")
    _usage_workflow(project)
    run_id = engine.launch(project, "usage")
    engine.drain(run_id)
    attempts = NodeAttempt.objects.filter(node_run__run_id=run_id)
    silent = attempts.count()
    first = attempts.get(node_run__scope_path="root.work.agent")
    reader = DjangoReadStore()
    job, _ = reader.run_job(run_id, "root.work.agent", since=0, limit=200)
    latest = job["latest_attempt"]
    assert isinstance(latest, dict)
    assert latest["usage"] is None
    first.output_tokens = 7
    first.cost_amount = 1.5
    first.cost_currency = "EUR"
    first.save(update_fields=("output_tokens", "cost_amount", "cost_currency"))
    other = attempts.exclude(pk=first.pk).first()
    assert other is not None
    other.output_tokens = 3
    other.cost_amount = 0.5
    other.cost_currency = "USD"
    other.save(update_fields=("output_tokens", "cost_amount", "cost_currency"))
    run = reader.monitor(run_id)["run"]
    assert isinstance(run, dict)
    usage = run["usage"]
    assert isinstance(usage, dict)
    assert usage["attempts"] == silent
    assert usage["attempts_reported"] == 2
    assert usage["output_tokens"] == 10
    assert usage["input_tokens"] is None
    assert usage["costs"] == [
        {"currency": "EUR", "amount": 1.5},
        {"currency": "USD", "amount": 0.5},
    ]


@pytest.mark.parametrize(
    "usage,expected",
    [
        (None, {"input_tokens": None, "cost_amount": None, "cost_currency": None}),
        (
            AttemptUsage(cost_amount=float("inf"), cost_currency="USD"),
            {"cost_amount": None, "cost_currency": None},
        ),
        (
            AttemptUsage(cost_amount=1.0, cost_currency="X" * 17),
            {"cost_amount": None, "cost_currency": None},
        ),
        (AttemptUsage(cost_amount=1.0), {"cost_amount": None, "cost_currency": None}),
        (
            AttemptUsage(input_tokens=-1, output_tokens=4),
            {"input_tokens": None, "output_tokens": 4},
        ),
        (
            AttemptUsage(cost_amount=0.0, cost_currency="USD"),
            {"cost_amount": 0.0, "cost_currency": "USD"},
        ),
    ],
)
def test_attempt_usage_fields_store_only_valid_reported_values(
    usage: AttemptUsage | None, expected: dict[str, object]
) -> None:
    fields = _attempt_usage_fields(usage)
    assert {name: fields[name] for name in expected} == expected


class _RejectedReportDriver:
    """Spend reported tokens, then leave a report that fails its label check."""

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        del node
        (context.worktree / "PLAN_CRITIQUE.md").write_text("Ready: No\n", encoding="utf-8")
        return ExecutionOutcome(
            OutcomeKind.SUCCEEDED,
            usage=AttemptUsage(output_tokens=42, cost_amount=0.1, cost_currency="USD"),
        )


def test_usage_survives_a_rejected_report(project: RelayProject, fake_agents: FakeAgents) -> None:
    from relay.paths import artifacts_dir

    fake_agents.install("codex")
    project.write_workflow(
        "rejected",
        json.dumps(
            {
                "jobs": {
                    "critique": {
                        "steps": [
                            {
                                "id": "review",
                                "uses": "relay/agent@v1",
                                "with": {
                                    "agent": "codex",
                                    "model": "m1",
                                    "report": "PLAN_CRITIQUE.md",
                                    "label": "Created by",
                                },
                            }
                        ]
                    }
                }
            }
        ),
    )
    engine = InlineEngine(node_executors(agent_driver=_RejectedReportDriver()), artifacts_dir())
    run_id = engine.launch(project, "rejected")
    engine.drain(run_id)
    attempt = NodeAttempt.objects.get(
        node_run__run_id=run_id, node_run__scope_path="root.critique.review"
    )
    assert attempt.error_code == "output_validation_error"
    assert (attempt.output_tokens, attempt.cost_amount) == (42, 0.1)
