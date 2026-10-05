"""Provider resets resume only the original failed step, once and durably."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.db import connections
import pytest

from relay.agents.usage_limits import ProviderUsageLimit, claude_usage_limit
from relay.errors import AgentUsageLimitError
from relay.execution.control import ControlResult
from relay.execution.reconcile import reconcile_once
from relay.execution.recovery import prepare_recovery_workspace
from relay.execution.resume import RecoveryTarget, rerun_failed_node
from relay.execution.runner import ExecutionOutcome, OutcomeKind
from relay.execution.scheduler import dispatch_ready_nodes
from relay.web.models import NodeAttempt, Run, RunEvent, RunSnapshot, UsageRetry
from relay.web.repositories import DjangoExecutionStore
from tests.support import Clock, InlineEngine, RelayProject


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


def limited_run(project: RelayProject, engine: InlineEngine, reset: datetime | None) -> str:
    project.write_workflow(
        "limited",
        "version: 1\nname: Limited\nnodes:\n"
        "  first: {type: command, run: [git, status]}\n"
        "  limited: {type: command, needs: [first], run: [git, status], "
        "writes: true, allow_no_commit: true}\n",
    )
    run_id = engine.launch(project, "limited")
    engine.run_token(engine.tokens.popleft())
    dispatch_ready_nodes(engine.store, run_id, engine.tokens.append)
    claim = engine.store.claim_dispatch(engine.tokens.popleft(), "quota-worker").attempt
    assert claim is not None
    engine.store.finish_attempt(
        claim.attempt_id,
        ExecutionOutcome(
            OutcomeKind.FAILED,
            error_code=AgentUsageLimitError.error_code,
            usage_limit=ProviderUsageLimit(reset, "five_hour"),
        ),
        claim.starting_head,
    )
    engine.store.release_attempt_lock(claim.attempt_id)
    assert Run.objects.get(pk=run_id).status == "failed"
    return run_id


def test_a_future_reset_does_not_start_an_attempt(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    run_id = limited_run(project, engine, clock.instant + timedelta(hours=1))
    result = reconcile_once(engine.store, engine.tokens.append, orderly_shutdown=False)
    assert result.usage_retries_resumed == 0
    assert Run.objects.get(pk=run_id).status == "failed"
    assert NodeAttempt.objects.filter(node_run__run_id=run_id).count() == 2


def test_a_due_reset_survives_new_connections_and_preserves_completed_steps_and_snapshot(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    run_id = limited_run(project, engine, clock.instant + timedelta(hours=1))
    snapshot = RunSnapshot.objects.get(run_id=run_id).hashes
    completed = NodeAttempt.objects.get(node_run__run_id=run_id, node_run__node_id="first").pk
    head = Run.objects.get(pk=run_id).recorded_head
    connections.close_all()
    clock.advance(3601)
    store = DjangoExecutionStore()
    assert store.resume_usage_retries() == 1
    assert store.resume_usage_retries() == 0
    dispatch_ready_nodes(store, run_id, engine.tokens.append)
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert Run.objects.get(pk=run_id).recorded_head == head
    assert RunSnapshot.objects.get(run_id=run_id).hashes == snapshot
    assert (
        NodeAttempt.objects.filter(node_run__run_id=run_id, node_run__node_id="first").get().pk
        == completed
    )
    assert UsageRetry.objects.get(run_id=run_id).state == "resumed"
    assert RunEvent.objects.filter(run_id=run_id, type="run.rerun").count() == 1


def test_owner_cancellation_removes_the_schedule_without_reopening_the_run(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    run_id = limited_run(project, engine, clock.instant + timedelta(hours=1))
    assert (
        engine.store.request_run_cancellation(run_id, "cancel-schedule") is ControlResult.ACCEPTED
    )
    clock.advance(3601)
    assert engine.store.resume_usage_retries() == 0
    assert UsageRetry.objects.get(run_id=run_id).state == "canceled"
    assert Run.objects.get(pk=run_id).status == "failed"


def test_an_unknown_reset_is_visible_and_never_retried(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    run_id = limited_run(project, engine, None)
    clock.advance(86400)
    assert engine.store.resume_usage_retries() == 0
    assert UsageRetry.objects.get(run_id=run_id).state == "blocked"
    assert RunEvent.objects.filter(run_id=run_id, type="run.retry_blocked").exists()


def test_owner_retry_supersedes_the_schedule(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    run_id = limited_run(project, engine, clock.instant + timedelta(hours=1))
    assert (
        rerun_failed_node(
            engine.store,
            run_id,
            "root.limited",
            "owner-retry",
            lambda target: prepare_recovery_workspace(engine.store, target),
        )
        is ControlResult.ACCEPTED
    )
    clock.advance(3601)
    assert engine.store.resume_usage_retries() == 0
    assert UsageRetry.objects.get(run_id=run_id).state == "resumed"


def test_cancellation_during_workspace_recovery_prevents_automatic_activation(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    run_id = limited_run(project, engine, clock.instant + timedelta(hours=1))
    retry = UsageRetry.objects.get(run_id=run_id)
    clock.advance(3601)

    def cancel_during_preparation(target: RecoveryTarget) -> None:
        engine.store.request_run_cancellation(run_id, "cancel-during-recovery")
        prepare_recovery_workspace(engine.store, target)

    rerun_failed_node(
        engine.store,
        run_id,
        "root.limited",
        f"quota:{retry.attempt_id}",
        cancel_during_preparation,
        usage_reset=True,
    )
    assert Run.objects.get(pk=run_id).status == "failed"
    assert UsageRetry.objects.get(run_id=run_id).state == "canceled"
    assert not RunEvent.objects.filter(run_id=run_id, type="run.rerun").exists()


def test_workspace_failure_blocks_the_retry_instead_of_repeatedly_starting_the_provider(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    run_id = limited_run(project, engine, clock.instant + timedelta(hours=1))
    checkout = Path(Run.objects.get(pk=run_id).worktree_path)
    checkout.rename(checkout.with_name("missing-checkout"))
    clock.advance(3601)
    assert engine.store.resume_usage_retries() == 0
    retry = UsageRetry.objects.get(run_id=run_id)
    assert retry.state == "blocked" and retry.error_message is not None
    assert engine.store.resume_usage_retries() == 0
    assert NodeAttempt.objects.filter(node_run__run_id=run_id).count() == 2
