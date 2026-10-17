"""Durable run ownership, explicit recovery, and the public Huey dispatch path."""

from __future__ import annotations

from collections.abc import Iterator
import json
import os
from pathlib import Path

from huey.api import TaskWrapper
import pytest

from relay.errors import ArtifactPreservationError, ConfigError, PathSafetyError, PersistenceError
from relay.execution import huey_app, runner
from relay.execution.control import ControlResult
from relay.execution.reconcile import reconcile_once
from relay.execution.recovery import prepare_recovery_workspace
from relay.execution.resources import AttemptResources
from relay.execution.resume import RecoveryTarget, rerun_failed_node, resume_interrupted
from relay.execution.runner import ExecutionOutcome, OutcomeKind
from relay.execution.scheduler import dispatch_ready_nodes
from relay.execution.state import AttemptStopReason
from relay.paths import artifacts_dir, shutdown_marker_path
from relay.web.models import Instance, NodeAttempt, NodeRun, Run
from relay.web.repositories import DjangoExecutionStore
from tests.support import PYTHON, Clock, InlineEngine, RelayProject, node_statuses, run_status

APPROVAL = (
    "name: Approval\n"
    "jobs:\n"
    "  approve:\n"
    "    steps:\n"
    "    - id: work\n"
    "      uses: relay/human-wait@v1\n"
    "      with:\n"
    "        prompt: Continue?\n"
    "  ship:\n"
    "    needs:\n"
    "    - approve\n"
    "    steps:\n"
    "    - id: work\n"
    "      uses: relay/command@v1\n"
    "      with:\n"
    '        argv: \'["git", "status"]\'\n'
)

CHAIN = (
    "name: Chain\n"
    "jobs:\n"
    "  first:\n"
    "    steps:\n"
    "    - id: work\n"
    "      uses: relay/command@v1\n"
    "      with:\n"
    '        argv: \'["git", "status"]\'\n'
    "  second:\n"
    "    needs:\n"
    "    - first\n"
    "    steps:\n"
    "    - id: work\n"
    "      uses: relay/command@v1\n"
    "      with:\n"
    '        argv: \'["git", "status"]\'\n'
)


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
    engine.drain(run_id)

    assert run_status(run_id) == "canceled"
    assert node_statuses(run_id) == {
        "root.approve": "canceled",
        "root.approve.work": "canceled",
        "root.ship": "canceled",
    }


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
        json.dumps(
            {
                "jobs": {
                    "retry": {
                        "env": {"MARKER": marker},
                        "steps": [
                            {
                                "id": "work",
                                "uses": "relay/command@v1",
                                "with": {"argv": json.dumps([PYTHON, "-c", script])},
                            }
                        ],
                    },
                    "after": {
                        "needs": ["retry"],
                        "steps": [{"run": "print(1)", "shell": "python"}],
                    },
                }
            }
        ),
    )
    run_id = engine.launch(project, "rerun")
    engine.drain(run_id)
    store = engine.store

    result = rerun_failed_node(
        store, run_id, "root.retry", "r1", lambda target: prepare_recovery_workspace(target, store)
    )
    dispatch_ready_nodes(store, run_id, engine.tokens.append)
    engine.drain(run_id)

    assert result is ControlResult.ACCEPTED
    assert run_status(run_id) == "succeeded"
    assert (
        NodeAttempt.objects.filter(node_run__run_id=run_id, node_run__node_id="retry").count() == 2
    )


@pytest.fixture(params=["worker_loss", "job_allocation", "step_allocation"])
def failed_without_evidence(
    project: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> tuple[str, str]:
    project.write_workflow("missing-evidence", CHAIN)
    run_id = engine.launch(project, "missing-evidence")
    if request.param == "worker_loss":
        claim = engine.store.claim_dispatch(engine.tokens.popleft(), engine.worker_id)
        assert claim.attempt is not None
        attempt_id = claim.attempt.attempt_id
        assert engine.store.fail_worker_attempts() == 1
        engine.drain(run_id)
    else:
        allocate = runner.allocate_attempt_resources
        allocations = 0
        fail_at = 0 if request.param == "job_allocation" else 1

        def fail_once(run_id: str, attempt_id: str) -> AttemptResources:
            nonlocal allocations
            current = allocations
            allocations += 1
            if current == fail_at:
                message = "Temporary allocation unavailable."
                raise PathSafetyError(message)
            return allocate(run_id, attempt_id)

        monkeypatch.setattr(runner, "allocate_attempt_resources", fail_once)
        engine.drain(run_id)
        attempt_id = str(NodeAttempt.objects.get(error_code="path_safety_error").pk)
    assert run_status(run_id) == "failed"
    assert not (artifacts_dir() / run_id / attempt_id).exists()
    return run_id, attempt_id


def test_owner_retry_preserves_attempts_that_failed_without_evidence(
    project: RelayProject, engine: InlineEngine, failed_without_evidence: tuple[str, str]
) -> None:
    run_id, attempt_id = failed_without_evidence
    store = engine.store
    result = rerun_failed_node(
        store,
        run_id,
        "root.first",
        "retry-missing",
        lambda target: prepare_recovery_workspace(target, store),
    )
    assert result is ControlResult.ACCEPTED
    assert (artifacts_dir() / run_id / attempt_id / "manifest.json").is_file()
    engine.drain(run_id)
    assert run_status(run_id) == "succeeded"


def test_confirmed_cleanup_preserves_attempts_that_failed_without_evidence(
    project: RelayProject, engine: InlineEngine, failed_without_evidence: tuple[str, str]
) -> None:
    run_id, attempt_id = failed_without_evidence
    worktree = Path(Run.objects.get(pk=run_id).worktree_path)
    result = engine.store.clean_project_data(project.project_id, "worktrees", run_id=run_id)
    assert result["worktrees"] == 1
    assert not worktree.exists()
    assert (artifacts_dir() / run_id / attempt_id / "manifest.json").is_file()


@pytest.mark.parametrize("operation", ["retry", "cleanup"])
def test_damaged_retained_manifest_still_refuses_retry_and_cleanup(
    project: RelayProject, engine: InlineEngine, operation: str
) -> None:
    project.write_workflow(
        "damaged-evidence", "jobs: {first: {steps: [{id: work, run: exit(1), shell: python}]}}\n"
    )
    run_id = engine.launch(project, "damaged-evidence")
    engine.drain(run_id)
    attempt = NodeAttempt.objects.get(
        node_run__run_id=run_id, node_run__scope_path="root.first.work"
    )
    manifest = artifacts_dir() / run_id / str(attempt.pk) / "manifest.json"
    manifest.write_bytes(b"{}\n")
    store = engine.store
    expected = ArtifactPreservationError if operation == "retry" else PersistenceError
    with pytest.raises(expected):
        if operation == "retry":
            rerun_failed_node(
                store,
                run_id,
                "root.first",
                "damaged",
                lambda target: prepare_recovery_workspace(target, store),
            )
        else:
            store.clean_project_data(project.project_id, "worktrees", run_id=run_id)
    assert manifest.read_bytes() == b"{}\n"
    assert Path(Run.objects.get(pk=run_id).worktree_path).exists()
    assert run_status(run_id) == "failed"


def test_a_rerun_in_preparation_rejects_a_concurrent_request(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "failed",
        (
            f"name: Failed\n"
            f"jobs:\n"
            f"  a:\n"
            f"    steps:\n"
            f"    - id: work\n"
            f"      uses: relay/command@v1\n"
            f"      with:\n"
            f'        argv: \'["{PYTHON}", "-c", "exit(1)"]\'\n'
        ),
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
                lambda target: prepare_recovery_workspace(target, store),
            )
        )
        prepare_recovery_workspace(target, store)

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

    resumed = resume_interrupted(store, lambda target: prepare_recovery_workspace(target, store))
    dispatch_ready_nodes(store, run_id, engine.tokens.append)
    engine.drain(run_id)

    assert resumed == (run_id,)
    assert run_status(run_id) == "succeeded"
    assert list(
        NodeAttempt.objects.filter(node_run__run_id=run_id, node_run__node_id="first")
        .order_by("attempt_number")
        .values_list("stop_reason", flat=True)
    ) == ["interrupted", "completed"]


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

    assert run_status(run_id) == "canceled"


@pytest.mark.parametrize("paused", [False, True])
def test_reconciliation_repairs_lost_delivery_in_active_runs(
    project: RelayProject, engine: InlineEngine, clock: Clock, paused: bool
) -> None:
    workflow = (
        (
            "name: Waiting sibling\n"
            "jobs:\n"
            "  approve:\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/human-wait@v1\n"
            "      with:\n"
            "        prompt: Continue?\n"
            "  independent:\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/command@v1\n"
            "      with:\n"
            '        argv: \'["git", "status"]\'\n'
        )
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


def test_reconciliation_preserves_a_worker_with_an_old_heartbeat(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    project.write_workflow("one", CHAIN)
    run_id = engine.launch(project, "one")
    engine.store.claim_dispatch(engine.tokens.popleft(), "worker")
    clock.advance(3_600)

    reconcile_once(engine.store, engine.tokens.append, orderly_shutdown=False)

    run = Run.objects.get(pk=run_id)
    assert (run.status, run.failure_code) == ("running", None)


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
