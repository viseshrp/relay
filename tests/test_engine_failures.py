"""Worker loss, executor faults, and cleanup errors preserve durable outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

import pytest

from relay.errors import AgentProtocolError
from relay.execution.runner import AttemptContext, ExecutionOutcome
from relay.web.models import Artifact, NodeAttempt, Run, RunEvent
from tests.support import InlineEngine, RelayProject

COMMAND = "version: 1\nname: Command\nnodes:\n  work: {type: command, run: [git, status]}\n"


def refuse_removal(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make Git refuse removal of this checkout while other Git operations remain real."""
    run = subprocess.run

    def fail(
        arguments: list[str], **options: object
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        if "worktree" in arguments and "remove" in arguments and arguments[-1] == str(target):
            return subprocess.CompletedProcess(arguments, 128, stdout="", stderr="checkout in use")
        return run(arguments, **options)

    monkeypatch.setattr(subprocess, "run", fail)


def test_clean_on_success_removes_the_worktree_after_preserving_attempt_evidence(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("clean", COMMAND)
    run_id = engine.launch(project, "clean", cleanup_policy="clean_on_success")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert (run.status, run.worktree_state) == ("succeeded", "removed")
    assert not Path(run.worktree_path).exists()
    assert Artifact.objects.filter(attempt__node_run__run_id=run_id).exists()


def test_a_failed_success_cleanup_keeps_the_success_and_reports_the_retained_checkout(
    project: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.write_workflow("clean", COMMAND)
    run_id = engine.launch(project, "clean", cleanup_policy="clean_on_success")
    checkout = Path(Run.objects.get(pk=run_id).worktree_path)
    refuse_removal(checkout, monkeypatch)

    engine.drain(run_id)

    run = Run.objects.get(pk=run_id)
    assert (run.status, run.worktree_state) == ("succeeded", "cleanup_failed")
    assert checkout.exists()
    assert (
        RunEvent.objects.get(run_id=run_id, type="run.cleanup_failed").payload["code"]
        == "worktree_error"
    )


def test_reader_removal_failure_keeps_evidence_and_fails_the_attempt(
    project: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.vcs.worktree import reader_worktree_path

    project.write_workflow("reader", COMMAND)
    run_id = engine.launch(project, "reader")
    token = engine.tokens.popleft()
    claim = engine.store.claim_dispatch(token, engine.worker_id)
    assert claim.attempt is not None
    checkout = reader_worktree_path(Path(claim.attempt.primary_worktree), claim.attempt.attempt_id)
    refuse_removal(checkout, monkeypatch)
    from relay.execution.runner import execute_attempt

    execute_attempt(
        engine.store,
        claim.attempt,
        engine.executors["command"],
        artifact_root=engine.artifact_root,
    )

    assert Run.objects.get(pk=run_id).failure_code == "worktree_error"
    assert Artifact.objects.filter(attempt_id=claim.attempt.attempt_id).exists()
    assert checkout.exists()


def test_a_worker_exit_does_not_classify_a_workerless_human_wait_as_worker_lost(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "loss",
        "version: 1\nname: Worker loss\nnodes:\n"
        "  approve: {type: human_wait, prompt: Continue?}\n"
        "  work: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(project, "loss")
    engine.run_token(engine.tokens.popleft())
    assert engine.store.claim_dispatch(engine.tokens.popleft(), "lost-worker").attempt is not None

    stopped = engine.store.fail_worker_attempts()

    assert stopped == 1
    assert list(
        NodeAttempt.objects.filter(node_run__run_id=run_id, stop_reason="worker_lost").values_list(
            "node_run__node_id", flat=True
        )
    ) == ["work"]


@dataclass
class FailingExecutor:
    """The node-provider boundary can fail; the runner still owns settlement."""

    error: Exception

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        del context
        raise self.error


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (RuntimeError("internal details"), "node_execution_error"),
        (AgentProtocolError("provider failed"), "agent_protocol_error"),
    ],
)
def test_executor_faults_settle_the_run_with_relay_error_codes(
    project: RelayProject, engine: InlineEngine, failure: Exception, code: str
) -> None:
    project.write_workflow("fault", COMMAND)
    run_id = engine.launch(project, "fault")
    engine.executors = {"command": FailingExecutor(failure)}
    engine.drain(run_id)
    assert (Run.objects.get(pk=run_id).status, NodeAttempt.objects.get().error_code) == (
        "failed",
        code,
    )
    expected = (
        failure.message
        if isinstance(failure, AgentProtocolError)
        else ("The node executor failed unexpectedly.")
    )
    assert Run.objects.get(pk=run_id).failure_summary == expected
    assert (
        RunEvent.objects.get(run_id=run_id, type="attempt.ended").payload["error_message"]
        == expected
    )


def test_an_unregistered_node_executor_fails_its_claim_instead_of_leaving_it_running(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("unknown", COMMAND)
    run_id = engine.launch(project, "unknown")
    engine.executors = {}
    engine.drain(run_id)
    assert (Run.objects.get(pk=run_id).status, NodeAttempt.objects.get().error_code) == (
        "failed",
        "node_execution_error",
    )
