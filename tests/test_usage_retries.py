"""Provider-confirmed resets resume the same current Actions job once."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from relay.agents.usage_limits import ProviderUsageLimit, claude_usage_limit
from relay.execution.nodes import node_executors
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.web.models import NodeAttempt, Run, RunEvent, RunSnapshot, UsageRetry
from relay.workflows.schema import AgentNode
from tests.support import Clock, FakeAgents, InlineEngine, RelayProject


@pytest.mark.parametrize("status", ["allowed", "allowed_warning", "unknown"])
def test_non_rejected_usage_never_authorizes_a_retry(status: str) -> None:
    assert claude_usage_limit({"_claude/rateLimit": {"status": status, "resetsAt": 4e9}}) is None


@pytest.mark.parametrize("reset", [None, True, "4e9", float("nan"), float("inf"), -1, 1e100])
def test_an_invalid_or_stale_provider_reset_keeps_the_limit_unscheduled(reset: object) -> None:
    result = claude_usage_limit({"_claude/rateLimit": {"status": "rejected", "resetsAt": reset}})
    assert result is not None and result.reset_at is None


def test_the_authoritative_reset_preserves_its_epoch() -> None:
    reset = datetime.now(timezone.utc) + timedelta(hours=1)
    result = claude_usage_limit(
        {
            "_claude/rateLimit": {
                "status": "rejected",
                "resetsAt": reset.timestamp(),
                "rateLimitType": "five_hour",
            }
        }
    )
    assert result == ProviderUsageLimit(reset, "five_hour")


@dataclass
class QuotaDriver:
    reset: datetime | None
    calls: list[AttemptContext] = field(default_factory=list)

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        del node
        self.calls.append(context)
        if len(self.calls) == 1:
            return ExecutionOutcome(
                OutcomeKind.FAILED,
                error_code="agent_usage_limit",
                usage_limit=ProviderUsageLimit(self.reset, "session"),
            )
        return ExecutionOutcome(OutcomeKind.SUCCEEDED)


def limited_run(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents, reset: datetime | None
) -> tuple[str, QuotaDriver]:
    fake_agents.install("codex")
    driver = QuotaDriver(reset)
    engine.executors = node_executors(agent_driver=driver)
    project.write_workflow(
        "limited",
        """jobs:
  first:
    steps: [{run: print('upstream'), shell: python}]
  limited:
    needs: first
    steps:
      - id: agent
        uses: relay/agent@v1
        with: {agent: codex, model: m1, prompt: Continue the exact captured task}
""",
    )
    run_id = engine.launch(project, "limited")
    engine.drain(run_id)
    return run_id, driver


def test_future_reset_keeps_the_current_job_waiting(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents, clock: Clock
) -> None:
    run_id, driver = limited_run(project, engine, fake_agents, clock.instant + timedelta(hours=1))
    assert Run.objects.get(pk=run_id).status == "running"
    assert engine.store.resume_usage_retries() == 0
    assert len(driver.calls) == 1
    assert NodeAttempt.objects.filter(node_run__run_id=run_id).count() == 4
    assert UsageRetry.objects.get(run_id=run_id).state == "scheduled"


def test_due_reset_wakes_once_and_preserves_completed_work(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents, clock: Clock
) -> None:
    run_id, driver = limited_run(project, engine, fake_agents, clock.instant + timedelta(hours=1))
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    original = (snapshot.hashes, snapshot.route_table, snapshot.resolved_prompts)
    completed = NodeAttempt.objects.get(node_run__scope_path="root.first.step_1").pk
    clock.advance(3601)
    assert engine.store.resume_usage_retries() == 1
    assert engine.store.resume_usage_retries() == 0
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert len(driver.calls) == 2
    assert driver.calls[0].attempt.route == driver.calls[1].attempt.route
    assert (
        "Continue after the provider-confirmed usage reset."
        in driver.calls[1].attempt.prompt_contents
    )
    assert driver.calls[1].attempt.prompt_contents[-1] == "Continue the exact captured task"
    assert NodeAttempt.objects.get(node_run__scope_path="root.first.step_1").pk == completed
    assert NodeAttempt.objects.filter(node_run__scope_path="root.limited").count() == 1
    assert UsageRetry.objects.get(run_id=run_id).state == "resumed"
    assert RunEvent.objects.filter(run_id=run_id, type="step.usage_ready").count() == 1
    snapshot.refresh_from_db()
    assert (snapshot.hashes, snapshot.route_table, snapshot.resolved_prompts) == original


def test_canceling_a_quota_wait_removes_its_schedule(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents, clock: Clock
) -> None:
    run_id, driver = limited_run(project, engine, fake_agents, clock.instant + timedelta(hours=1))
    engine.store.request_run_cancellation(run_id, "cancel-quota")
    engine.drain(run_id)
    clock.advance(3601)
    assert engine.store.resume_usage_retries() == 0
    assert UsageRetry.objects.get(run_id=run_id).state == "canceled"
    assert Run.objects.get(pk=run_id).status == "canceled"
    assert len(driver.calls) == 1


def test_unknown_reset_never_uses_generic_recovery(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents, clock: Clock
) -> None:
    run_id, driver = limited_run(project, engine, fake_agents, None)
    clock.advance(86400)
    assert engine.store.resume_usage_retries() == engine.store.resume_automatic_retries() == 0
    assert UsageRetry.objects.get(run_id=run_id).state == "blocked"
    assert Run.objects.get(pk=run_id).status == "failed"
    assert len(driver.calls) == 1


def test_owner_pause_keeps_a_due_reset_held_until_resume(
    project: RelayProject, engine: InlineEngine, fake_agents: FakeAgents, clock: Clock
) -> None:
    run_id, driver = limited_run(project, engine, fake_agents, clock.instant + timedelta(hours=1))
    engine.store.configure_dispatch_pause(run_id, True, "hold-reset")
    clock.advance(3601)
    assert engine.store.resume_usage_retries() == 0
    engine.drain(run_id)
    assert len(driver.calls) == 1
    engine.store.configure_dispatch_pause(run_id, False, "resume-reset")
    assert engine.store.resume_usage_retries() == 1
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert len(driver.calls) == 2
