"""Engine scenarios through the real store: scheduling, failures, waits, and scopes."""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

from relay.execution.scheduler import dispatch_ready_nodes
from relay.web.models import HumanInteraction, NodeAttempt, NodeRun, Run
from tests.support import (
    PYTHON,
    Clock,
    InlineEngine,
    RelayProject,
    answer_wait,
    node_statuses,
    run_status,
)


def test_condition_runs_the_selected_branch_and_skips_the_other(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "branch",
        """version: 1
name: Branch
inputs:
  mode: {type: enum, default: review, constraints: {values: [review, implement]}}
nodes:
  choose:
    type: condition
    expr: "${{ inputs.mode }}"
    branches: {review: review_path, implement: implement_path}
  review_path: {type: command, needs: [choose], run: [git, status]}
  implement_path: {type: command, needs: [choose], run: [git, status]}
""",
    )

    run_id = engine.launch(project, "branch", inputs={"mode": "implement"})
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert node_statuses(run_id) == {
        "root.choose": "succeeded",
        "root.review_path": "skipped",
        "root.implement_path": "succeeded",
    }


def test_false_guards_skip_nodes_and_their_dependents(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "guard",
        """version: 1
name: Guard
inputs:
  enabled: {type: boolean, default: false}
nodes:
  maybe: {type: command, run: [git, status], if: "${{ inputs.enabled }}"}
  after: {type: command, needs: [maybe], run: [git, status]}
  always: {type: command, run: [git, status]}
""",
    )

    run_id = engine.launch(project, "guard")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert node_statuses(run_id) == {
        "root.maybe": "skipped",
        "root.after": "skipped",
        "root.always": "succeeded",
    }


def test_a_failed_command_fails_fast_and_cancels_unstarted_work(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "fail",
        f"""version: 1
name: Fail
nodes:
  broken: {{type: command, run: ["{PYTHON}", -c, "import sys; sys.exit(3)"]}}
  sibling: {{type: command, run: [git, status]}}
  later: {{type: command, needs: [broken], run: [git, status]}}
""",
    )

    run_id = engine.launch(project, "fail")
    engine.drain(run_id)

    run = Run.objects.get(pk=run_id)
    assert (run.status, run.failure_code) == ("failed", "node_execution_error")
    statuses = node_statuses(run_id)
    assert statuses["root.broken"] == "failed"
    assert statuses["root.sibling"] == "canceled"
    assert statuses["root.later"] == "canceled"
    attempt = NodeAttempt.objects.get(node_run__scope_path="root.broken")
    assert (attempt.exit_code, attempt.stop_reason) == (3, "failed")


def test_a_command_past_its_timeout_is_stopped(
    project: RelayProject, engine: InlineEngine, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.execution import cancellation
    from relay.execution.nodes import command

    class PendingProcess:
        pid: int = 31_415
        returncode: int | None = None

        def poll(self) -> int | None:
            clock.advance(1)
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                raise subprocess.TimeoutExpired("pending-command", timeout)
            return self.returncode

    process = PendingProcess()

    def launch(*args: object, **kwargs: object) -> PendingProcess:
        del args, kwargs
        return process

    def stop(pid: int, signal_value: int) -> None:
        del pid, signal_value
        process.returncode = -1

    # Replace the OS process boundary, leaving command deadlines and tree stopping real.
    monkeypatch.setattr(
        command,
        "subprocess",
        SimpleNamespace(
            Popen=launch,
            DEVNULL=subprocess.DEVNULL,
            TimeoutExpired=subprocess.TimeoutExpired,
            CREATE_NEW_PROCESS_GROUP=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        ),
    )
    monkeypatch.setattr(cancellation.os, "kill" if os.name == "nt" else "killpg", stop)
    project.write_workflow(
        "slow",
        f"""version: 1
name: Slow
nodes:
  wait:
    type: command
    timeout: 300ms
    run: ["{PYTHON}", -c, "print('pending')"]
""",
    )

    run_id = engine.launch(project, "slow")
    engine.drain(run_id)

    attempt = NodeAttempt.objects.get(node_run__run_id=run_id)
    assert (attempt.stop_reason, attempt.error_code) == ("timeout", "node_timeout")
    assert Run.objects.get(pk=run_id).failure_code == "node_timeout"
    assert process.returncode is not None


def test_writer_outputs_feed_downstream_expressions(
    project: RelayProject, engine: InlineEngine
) -> None:
    script = (
        "import pathlib, subprocess; "
        "pathlib.Path('report.txt').write_text('Ready: Yes'); "
        "subprocess.run(['git', 'add', 'report.txt'], check=True); "
        "subprocess.run(['git', 'commit', '-q', '-m', 'report'], check=True)"
    )
    project.write_workflow(
        "outputs",
        f"""version: 1
name: Outputs
nodes:
  produce:
    type: command
    writes: true
    run: ["{PYTHON}", -c, "{script}"]
    outputs:
      ready: {{label: {{artifact: report.txt, label: Ready}}}}
  gate:
    type: command
    needs: [produce]
    if: "${{{{ needs.produce.outputs.ready == 'Yes' }}}}"
    run: [git, status]
""",
    )

    run_id = engine.launch(project, "outputs")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert NodeRun.objects.get(run_id=run_id, node_id="produce").outputs == {"ready": "Yes"}
    assert node_statuses(run_id)["root.gate"] == "succeeded"


def test_a_reader_that_changes_its_worktree_fails_attribution(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "dirty",
        f"""version: 1
name: Dirty reader
nodes:
  scribble:
    type: command
    run: ["{PYTHON}", -c, "open('scratch.txt', 'w').write('x')"]
""",
    )

    run_id = engine.launch(project, "dirty")
    engine.drain(run_id)

    attempt = NodeAttempt.objects.get(node_run__run_id=run_id)
    assert attempt.error_code == "commit_validation_error"
    assert run_status(run_id) == "failed"


def test_human_wait_pauses_until_answered(project: RelayProject, engine: InlineEngine) -> None:
    project.write_workflow(
        "approval",
        """version: 1
name: Approval
nodes:
  approve: {type: human_wait, prompt: Continue?}
  ship: {type: command, needs: [approve], run: [git, status]}
""",
    )

    run_id = engine.launch(project, "approval")
    engine.drain(run_id)
    assert run_status(run_id) == "paused_wait"
    assert node_statuses(run_id)["root.approve"] == "waiting"

    assert answer_wait(engine, run_id) == "accepted"

    assert run_status(run_id) == "succeeded"
    assert HumanInteraction.objects.get(run_id=run_id).status == "answered"


def test_an_expired_wait_takes_its_timeout_edge(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    project.write_workflow(
        "routed",
        """version: 1
name: Routed timeout
nodes:
  approve: {type: human_wait, prompt: Continue?, deadline: 15m, on_timeout: stop}
  stop: {type: command, needs: [approve], run: [git, status]}
""",
    )
    run_id = engine.launch(project, "routed")
    engine.drain(run_id)

    clock.advance(901)
    assert engine.store.expire_human_waits() == 1
    dispatch_ready_nodes(engine.store, run_id, engine.tokens.append)
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert node_statuses(run_id) == {"root.approve": "succeeded", "root.stop": "succeeded"}
    assert HumanInteraction.objects.get(run_id=run_id).status == "expired"


def test_an_expired_wait_without_a_timeout_edge_fails_the_run(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    project.write_workflow(
        "deadline",
        """version: 1
name: Deadline
nodes:
  approve: {type: human_wait, prompt: Continue?, deadline: 15m}
""",
    )
    run_id = engine.launch(project, "deadline")
    engine.drain(run_id)

    clock.advance(901)
    engine.store.expire_human_waits()

    run = Run.objects.get(pk=run_id)
    assert (run.status, run.failure_code) == ("failed", "node_timeout")


@pytest.mark.parametrize(
    ("until", "iterations", "fallback"),
    [('    until: "${{ loop.index >= 2 }}"\n', 2, "skipped"), ("", 3, "succeeded")],
)
def test_a_loop_routes_according_to_why_it_stopped(
    project: RelayProject, engine: InlineEngine, until: str, iterations: int, fallback: str
) -> None:
    project.write_workflow(
        "loops",
        f"""version: 1
name: Loops
nodes:
  repeat:
    type: loop
    max_iterations: 3
{until}    exhausted: fallback
    body:
      step: {{type: command, run: [git, status]}}
  fallback: {{type: command, needs: [repeat], run: [git, status]}}
""",
    )

    run_id = engine.launch(project, "loops")
    engine.drain(run_id)

    statuses = node_statuses(run_id)
    assert run_status(run_id) == "succeeded"
    assert NodeRun.objects.filter(run_id=run_id, node_id="step").count() == iterations
    assert statuses[f"root.repeat#{iterations}.step"] == "succeeded"
    assert statuses["root.fallback"] == fallback


def test_a_subworkflow_maps_declared_child_outputs(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write("status.md", "State: green\n")
    project.write_workflow(
        "child",
        """version: 1
name: Child
inputs:
  target: {type: string, required: true}
nodes:
  check:
    type: command
    run: [git, status]
    outputs:
      present: {exists: status.md}
      state: {label: {artifact: status.md, label: State}}
""",
    )
    project.write_workflow(
        "parent",
        """version: 1
name: Parent
nodes:
  verify:
    type: subworkflow
    workflow: child
    inputs: {target: "${{ run.run_id }}"}
    outputs: {present: check.present, state: check.state}
  after:
    type: command
    needs: [verify]
    if: "${{ needs.verify.outputs.state == 'green' }}"
    run: [git, status]
""",
    )

    run_id = engine.launch(project, "parent")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    verify = NodeRun.objects.get(run_id=run_id, scope_path="root.verify")
    assert verify.outputs == {"present": True, "state": "green"}
    assert node_statuses(run_id)["root.verify.check"] == "succeeded"
    assert node_statuses(run_id)["root.after"] == "succeeded"


def test_a_nested_wait_yields_and_resumes_the_same_parent_attempt(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "approve_child",
        """version: 1
name: Approval child
nodes:
  approve: {type: human_wait, prompt: Ship it?}
  ship: {type: command, needs: [approve], run: [git, status]}
""",
    )
    project.write_workflow(
        "nested",
        """version: 1
name: Nested wait
nodes:
  release: {type: subworkflow, workflow: approve_child}
  independent: {type: command, run: [git, status]}
""",
    )

    run_id = engine.launch(project, "nested")
    engine.drain(run_id)
    assert run_status(run_id) == "paused_wait"
    statuses = node_statuses(run_id)
    assert statuses["root.release"] == "waiting"
    assert statuses["root.independent"] == "succeeded"
    parent_attempts = NodeAttempt.objects.filter(node_run__scope_path="root.release")
    assert parent_attempts.count() == 1

    answer_wait(engine, run_id)

    assert run_status(run_id) == "succeeded"
    assert node_statuses(run_id)["root.release.ship"] == "succeeded"
    assert NodeAttempt.objects.filter(node_run__scope_path="root.release").count() == 1


def test_a_suspended_scope_keeps_its_timeout_without_holding_a_worker(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    project.write_workflow(
        "child_wait",
        "version: 1\nname: Wait\nnodes:\n  wait: {type: human_wait, prompt: Continue?}\n",
    )
    project.write_workflow(
        "scope_timeout",
        """version: 1
name: Scope timeout
nodes:
  release: {type: subworkflow, workflow: child_wait, timeout: 2s}
""",
    )
    run_id = engine.launch(project, "scope_timeout")
    engine.drain(run_id)
    clock.advance(3)

    engine.store.expire_scope_waits()
    engine.store.resolve_human_wait_controls()

    parent = NodeAttempt.objects.get(node_run__run_id=run_id, node_run__node_id="release")
    assert (parent.stop_reason, parent.error_code) == ("timeout", "node_timeout")
    assert run_status(run_id) == "failed"


def test_a_timeout_edge_runs_while_a_second_human_wait_remains_pending(
    project: RelayProject, engine: InlineEngine, clock: Clock
) -> None:
    project.write_workflow(
        "two_waits",
        """version: 1
name: Two waits
nodes:
  bounded: {type: human_wait, prompt: Continue?, deadline: 1s, on_timeout: stop}
  other: {type: human_wait, prompt: Other?}
  stop: {type: command, needs: [bounded], run: [git, status]}
""",
    )
    run_id = engine.launch(project, "two_waits")
    engine.drain(run_id)
    clock.advance(2)

    engine.store.expire_human_waits()
    dispatch_ready_nodes(engine.store, run_id, engine.tokens.append)
    engine.drain(run_id)

    statuses = node_statuses(run_id)
    assert statuses["root.stop"] == "succeeded"
    assert statuses["root.other"] == "waiting"
