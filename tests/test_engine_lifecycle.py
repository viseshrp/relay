"""Durable run ownership, explicit recovery, and the public Huey dispatch path."""

from __future__ import annotations

from collections.abc import Iterator
from functools import partial
import json
import os
from pathlib import Path

from huey.api import TaskWrapper
import pytest

from relay.errors import ConfigError, PersistenceError
from relay.execution import huey_app
from relay.execution.control import ControlResult
from relay.execution.reconcile import reconcile_once
from relay.execution.recovery import prepare_recovery_workspace
from relay.execution.resume import RecoveryTarget, rerun_failed_node, resume_interrupted
from relay.execution.runner import ExecutionOutcome, OutcomeKind
from relay.execution.scheduler import dispatch_ready_nodes
from relay.execution.state import AttemptStopReason
from relay.paths import shutdown_marker_path
from relay.web.models import Instance, NodeAttempt, NodeRun, Run
from relay.web.repositories import DjangoExecutionStore
from tests.support import PYTHON, Clock, InlineEngine, RelayProject, git, node_statuses, run_status

APPROVAL = """version: 1
name: Approval
nodes:
  approve: {type: human_wait, prompt: Continue?}
  ship: {type: command, needs: [approve], run: [git, status]}
"""

CHAIN = """version: 1
name: Chain
nodes:
  first: {type: command, run: [git, status]}
  second: {type: command, needs: [first], run: [git, status]}
"""


def test_a_live_supervisor_lease_rejects_another_owner() -> None:
    store = DjangoExecutionStore()
    store.acquire_instance(100, "host-a")

    with pytest.raises(ConfigError):
        store.acquire_instance(200, "host-b")


def test_a_stale_lease_can_be_replaced(clock: Clock) -> None:
    store = DjangoExecutionStore()
    old = store.acquire_instance(100, "host-a")
    clock.advance(3_600)

    current = store.acquire_instance(200, "host-b")

    assert current != old
    assert not store.heartbeat_instance(old)


def test_releasing_the_lease_removes_its_owner() -> None:
    store = DjangoExecutionStore()
    instance = store.acquire_instance(100, "host-a")

    store.release_instance(instance)

    assert not Instance.objects.exists()


def test_shutdown_requires_the_current_instance_lease() -> None:
    with pytest.raises(PersistenceError):
        DjangoExecutionStore().request_orderly_shutdown("00000000-0000-0000-0000-000000000000")


def test_canceling_a_paused_run_settles_it_as_canceled(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("approval", APPROVAL)
    run_id = engine.launch(project, "approval")
    engine.drain(run_id)

    engine.store.request_run_cancellation(run_id, "cancel-1")
    engine.store.resolve_human_wait_controls()

    assert run_status(run_id) == "canceled"
    assert node_statuses(run_id) == {"root.approve": "canceled", "root.ship": "canceled"}


def test_repeating_a_cancel_is_idempotent(project: RelayProject, engine: InlineEngine) -> None:
    project.write_workflow("approval", APPROVAL)
    run_id = engine.launch(project, "approval")
    engine.drain(run_id)
    engine.store.request_run_cancellation(run_id, "cancel-1")

    result = engine.store.request_run_cancellation(run_id, "cancel-1")

    assert result is ControlResult.ALREADY_APPLIED


def test_a_failed_node_can_be_rerun_as_a_new_attempt(
    project: RelayProject, engine: InlineEngine, tmp_path: Path
) -> None:
    marker = str(tmp_path / "second-try")
    script = (
        "from pathlib import Path; import os,sys; p=Path(os.environ['MARKER']); "
        "existed=p.exists(); p.touch(); sys.exit(0 if existed else 1)"
    )
    project.write_workflow(
        "rerun",
        f"""version: 1
name: Rerun
nodes:
  retry:
    type: command
    run: ["{PYTHON}", -c, {json.dumps(script)}]
    env: {{MARKER: {json.dumps(marker)}}}
  after: {{type: command, needs: [retry], run: [git, status]}}
""",
    )
    run_id = engine.launch(project, "rerun")
    engine.drain(run_id)
    store = engine.store

    result = rerun_failed_node(
        store, run_id, "root.retry", "r1", partial(prepare_recovery_workspace, store)
    )
    dispatch_ready_nodes(store, run_id, engine.tokens.append)
    engine.drain(run_id)

    assert result is ControlResult.ACCEPTED
    assert run_status(run_id) == "succeeded"
    assert (
        NodeAttempt.objects.filter(node_run__run_id=run_id, node_run__node_id="retry").count() == 2
    )


def test_a_rerun_in_preparation_rejects_a_concurrent_request(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "failed",
        f"version: 1\nname: Failed\nnodes:\n"
        f'  a: {{type: command, run: ["{PYTHON}", -c, "exit(1)"]}}\n',
    )
    run_id = engine.launch(project, "failed")
    engine.drain(run_id)
    store = engine.store
    duplicate = []

    def prepare(target: RecoveryTarget) -> None:
        duplicate.append(
            rerun_failed_node(
                store,
                run_id,
                "root.a",
                "other",
                partial(prepare_recovery_workspace, store),
            )
        )
        prepare_recovery_workspace(store, target)

    rerun_failed_node(store, run_id, "root.a", "first", prepare)

    assert duplicate == [ControlResult.STALE]


def test_orderly_shutdown_interrupts_attempts_and_restart_resumes_them(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("resume", CHAIN)
    run_id = engine.launch(project, "resume")
    store = engine.store
    claim = store.claim_dispatch(engine.tokens.popleft(), "worker-1")
    assert claim.attempt is not None
    instance = store.acquire_instance(os.getpid(), "host")
    store.request_orderly_shutdown(instance)
    store.interrupt_active_attempts()
    store.release_instance(instance)

    resumed = resume_interrupted(store, partial(prepare_recovery_workspace, store))
    dispatch_ready_nodes(store, run_id, engine.tokens.append)
    engine.drain(run_id)

    assert resumed == (run_id,)
    assert run_status(run_id) == "succeeded"
    assert list(
        NodeAttempt.objects.filter(node_run__run_id=run_id, node_run__node_id="first")
        .order_by("attempt_number")
        .values_list("stop_reason", flat=True)
    ) == ["interrupted", "completed"]


@pytest.mark.parametrize("intent", ["owner", "fail_fast"])
def test_cancel_and_shutdown_keep_a_completed_writers_outputs_and_commit(
    project: RelayProject, engine: InlineEngine, intent: str
) -> None:
    project.write_workflow(
        "drain",
        """version: 1
name: Drain
nodes:
  writer: {type: command, writes: true, run: [git, status]}
  sibling: {type: human_wait, prompt: Wait}
""",
    )
    run_id = engine.launch(project, "drain")
    store = engine.store
    claims = [store.claim_dispatch(token, "worker") for token in engine.tokens]
    writer, sibling = [item.attempt for item in claims]
    assert writer is not None and sibling is not None
    if intent == "owner":
        store.request_run_cancellation(run_id, "cancel")
    else:
        store.finish_attempt(
            sibling.attempt_id,
            ExecutionOutcome(
                OutcomeKind.FAILED,
                stop_reason=AttemptStopReason.FAILED,
                error_code="output_invalid",
                exit_code=3,
            ),
            sibling.starting_head,
        )
    worktree = Path(writer.primary_worktree)
    git(worktree, "commit", "--allow-empty", "-q", "-m", "Finished writer")
    completed_head = git(worktree, "rev-parse", "HEAD")

    store.finish_attempt(
        writer.attempt_id,
        ExecutionOutcome(OutcomeKind.SUCCEEDED, outputs={"ready": "Yes"}, exit_code=0),
        completed_head,
    )
    instance = store.acquire_instance(os.getpid(), "host")
    store.request_orderly_shutdown(instance)
    store.interrupt_active_attempts()
    store.release_instance(instance)

    assert NodeRun.objects.get(pk=writer.node_run_id).outputs == {"ready": "Yes"}
    run = Run.objects.get(pk=run_id)
    assert run.recorded_head == completed_head
    assert run.status == ("canceled" if intent == "owner" else "failed")
    assert resume_interrupted(store, partial(prepare_recovery_workspace, store)) == ()


def test_a_failure_during_owner_cancel_keeps_its_own_diagnostic(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("one", CHAIN)
    run_id = engine.launch(project, "one")
    store = engine.store
    attempt = store.claim_dispatch(engine.tokens.popleft(), "worker").attempt
    assert attempt is not None
    store.request_run_cancellation(run_id, "cancel")

    store.finish_attempt(
        attempt.attempt_id,
        ExecutionOutcome(
            OutcomeKind.FAILED,
            stop_reason=AttemptStopReason.FAILED,
            error_code="output_invalid",
            exit_code=3,
        ),
        attempt.starting_head,
    )

    recorded = NodeAttempt.objects.get(pk=attempt.attempt_id)
    assert (recorded.stop_reason, recorded.error_code, recorded.exit_code) == (
        "failed",
        "output_invalid",
        3,
    )


def test_a_canceled_node_cannot_satisfy_the_runs_success_guard(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("guard", CHAIN)
    run_id = engine.launch(project, "guard")
    # Reproduce a retained canceled row while another attempt is still completing.
    NodeRun.objects.filter(run_id=run_id, node_id="second").update(status="canceled")

    engine.run_token(engine.tokens.popleft())

    assert run_status(run_id) == "running"


@pytest.mark.parametrize("paused", [False, True])
def test_reconciliation_repairs_lost_delivery_in_active_runs(
    project: RelayProject, engine: InlineEngine, clock: Clock, paused: bool
) -> None:
    workflow = (
        "version: 1\nname: Waiting sibling\nnodes:\n"
        "  approve: {type: human_wait, prompt: Continue?}\n"
        "  independent: {type: command, run: [git, status]}\n"
        if paused
        else CHAIN
    )
    project.write_workflow("one", workflow)
    run_id = engine.launch(project, "one")
    if paused:
        engine.run_token(engine.tokens.popleft())
        assert run_status(run_id) == "paused_wait"
    token = engine.tokens.popleft()
    clock.advance(3_600)
    repaired = []

    reconcile_once(engine.store, repaired.append, orderly_shutdown=False)

    assert repaired == [token]


def test_reconciliation_reaps_a_lost_worker(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    project.write_workflow("one", CHAIN)
    run_id = engine.launch(project, "one")
    engine.store.claim_dispatch(engine.tokens.popleft(), "worker")
    clock.advance(3_600)

    reconcile_once(engine.store, engine.tokens.append, orderly_shutdown=False)

    run = Run.objects.get(pk=run_id)
    assert (run.status, run.failure_code) == ("failed", "worker_lost")


def test_a_failing_enqueue_leaves_the_claim_available_for_repair(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    project.write_workflow("one", CHAIN)
    engine.launch(project, "one")
    token = engine.tokens.popleft()
    clock.advance(3_600)

    def broken(claim_token: str) -> None:
        raise RuntimeError(claim_token)

    result = reconcile_once(engine.store, broken, orderly_shutdown=False)

    assert result.dispatch_enqueue_failures == 1
    assert engine.store.orphaned_dispatch_tokens() == (token,)


def test_the_huey_task_claims_runs_and_schedules_successors(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("chain", CHAIN)
    run_id = engine.launch(project, "chain")
    huey_app.enqueue_claim(engine.tokens.popleft())

    first = huey_app.huey.dequeue()
    assert first is not None
    huey_app.huey.execute(first)
    second = huey_app.huey.dequeue()
    assert second is not None
    huey_app.huey.execute(second)

    assert run_status(run_id) == "succeeded"


def test_enqueue_claim_stores_only_the_token_in_huey() -> None:
    huey_app.enqueue_claim("claim-token-1")

    task = huey_app.huey.dequeue()

    assert task is not None
    assert task.args == ("claim-token-1",)


@pytest.fixture
def signal_task(request: pytest.FixtureRequest) -> Iterator[TaskWrapper]:
    exception = request.param

    @huey_app.huey.task(retries=0)
    def stopped(claim_token: str) -> None:
        del claim_token
        raise exception()

    yield stopped
    stopped.unregister()


@pytest.mark.parametrize(
    ("signal_task", "shutdown", "reason", "error"),
    [
        (RuntimeError, False, "failed", "dispatch_error"),
        (KeyboardInterrupt, False, "failed", "dispatch_error"),
        (KeyboardInterrupt, True, "interrupted", "interrupted"),
    ],
    indirect=["signal_task"],
)
def test_huey_signals_settle_a_claimed_attempt(
    project: RelayProject,
    engine: InlineEngine,
    signal_task: TaskWrapper,
    shutdown: bool,
    reason: str,
    error: str,
) -> None:
    project.write_workflow("one", CHAIN)
    engine.launch(project, "one")
    token = engine.tokens.popleft()
    attempt = engine.store.claim_dispatch(token, "worker").attempt
    assert attempt is not None
    if shutdown:
        marker = shutdown_marker_path()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")

    huey_app.huey.execute(signal_task.s(token))

    recorded = NodeAttempt.objects.get(pk=attempt.attempt_id)
    assert (recorded.stop_reason, recorded.error_code) == (reason, error)
