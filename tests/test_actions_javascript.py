"""Real local JavaScript main/post execution when the declared runtime is available."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from relay.execution.nodes import node_executors
from relay.paths import safe_resolve, worktrees_dir
from relay.web.actions_automation import cancel_queue_owner
from relay.web.models import NodeAttempt, Run
from tests.support import InlineEngine, RelayProject, git


def node_runtime(major: int, monkeypatch: pytest.MonkeyPatch) -> None:
    configured = os.environ.get(f"RELAY_TEST_NODE_{major}")
    executable = configured or shutil.which(f"node{major}") or shutil.which("node")
    if executable is None:
        pytest.skip(f"Node.js {major} is not installed for this optional integration check.")
    version = subprocess.run(  # noqa: S603 - explicitly selected local test runtime
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        shell=False,
    ).stdout.strip()
    if not version.startswith(f"v{major}."):
        pytest.skip(f"Node.js {major} is not installed for this optional integration check.")
    original = shutil.which
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name, **kwargs: executable if name == f"node{major}" else original(name, **kwargs),
    )


def action(project: RelayProject, major: int) -> None:
    project.write(
        ".relay/actions/stateful/action.yml",
        f"""name: Stateful local action
description: Prove input, output, saved state and cleanup behavior.
inputs:
  marker-name:
    description: A marker for main and post.
    required: true
runs:
  using: node{major}
  main: main.js
  post: post.js
""",
    )
    project.write(
        ".relay/actions/stateful/main.js",
        "const fs = require('node:fs');\n"
        "const marker = process.env['INPUT_MARKER-NAME'];\n"
        "if (!marker) throw new Error('missing exact input');\n"
        "fs.appendFileSync('main.txt', marker + '\\n');\n"
        "fs.appendFileSync(process.env.RELAY_OUTPUT, 'marker=' + marker + '\\n');\n"
        "fs.appendFileSync(process.env.RELAY_STATE, 'marker=' + marker + '\\n');\n",
    )
    project.write(
        ".relay/actions/stateful/post.js",
        "const fs = require('node:fs');\n"
        "if (!process.env.STATE_marker) throw new Error('missing saved state');\n"
        "fs.appendFileSync('cleanup.txt', process.env.STATE_marker + '\\n');\n",
    )
    project.commit("Add local JavaScript action")


@pytest.mark.parametrize("major", [20, 24])
def test_javascript_state_outputs_and_lifo_cleanup(
    major: int, project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node_runtime(major, monkeypatch)
    action(project, major)
    project.write_workflow(
        "javascript",
        """jobs:
  main:
    outputs:
      result: ${{ steps.first.outputs.marker }}-${{ steps.second.outputs.marker }}
    steps:
      - id: first
        uses: ./.relay/actions/stateful
        with: {marker-name: first}
      - id: second
        uses: ./.relay/actions/stateful
        with: {marker-name: second}
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "javascript")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "succeeded", run.failure_summary
    workspace = safe_resolve(worktrees_dir(), run.worktree_path)
    assert (workspace / "main.txt").read_text() == "first\nsecond\n"
    assert (workspace / "cleanup.txt").read_text() == "second\nfirst\n"
    assert git(workspace, "rev-list", "--count", f"{run.source_commit}..HEAD") == "1"
    assert NodeAttempt.objects.filter(node_run__run_id=run_id).count() == 3


@pytest.mark.parametrize("major", [20, 24])
@pytest.mark.parametrize("whole_workflow", [False, True])
def test_javascript_cleanup_runs_after_a_waiting_job_is_canceled(
    major: int,
    whole_workflow: bool,
    project: RelayProject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_runtime(major, monkeypatch)
    action(project, major)
    project.write_workflow(
        "javascript-cancel",
        """jobs:
  main:
    steps:
      - uses: ./.relay/actions/stateful
        with: {marker-name: canceled}
      - uses: relay/human-wait@v1
        with: {prompt: Continue?}
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "javascript-cancel")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "paused_wait"
    if whole_workflow:
        from relay.execution.cancellation import request_cancellation

        request_cancellation(engine.store, run_id, "javascript-cleanup-test")
    else:
        cancel_queue_owner(run_id, "root.main", "javascript-cleanup-test")
    engine.store.resolve_human_wait_controls()
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "canceled"
    workspace = safe_resolve(worktrees_dir(), run.worktree_path)
    assert (workspace / "cleanup.txt").read_text() == "canceled\n"


@pytest.mark.parametrize("major", [20, 24])
def test_failed_javascript_post_retains_summary_and_fails_job(
    major: int, project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.web.models import NodeRun, RunEvent

    node_runtime(major, monkeypatch)
    action(project, major)
    project.write(
        ".relay/actions/stateful/post.js",
        "const fs = require('node:fs');\n"
        "fs.appendFileSync(process.env.RELAY_STEP_SUMMARY, 'Cleanup failed\\n');\n"
        "fs.writeFileSync('cleanup.txt', 'retained failure');\n"
        "process.exitCode = 1;\n",
    )
    project.commit("Add rejected cleanup proof")
    project.write_workflow(
        "javascript-post-failure",
        "jobs: {main: {steps: [{uses: ./.relay/actions/stateful, with: {marker-name: first}}]}}\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "javascript-post-failure")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "failed"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main").outcome == "failure"
    assert RunEvent.objects.filter(run_id=run_id, type="actions.post_failed").exists()
    assert RunEvent.objects.get(run_id=run_id, type="actions.summary").payload["markdown"] == (
        "Cleanup failed\n"
    )
    workspace = safe_resolve(worktrees_dir(), run.worktree_path)
    assert (workspace / "cleanup.txt").read_text() == "retained failure"
    assert git(workspace, "rev-parse", "HEAD") == run.source_commit


@pytest.mark.parametrize("major", [20, 24])
def test_javascript_post_condition_uses_the_job_result_and_action_inputs(
    major: int, project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node_runtime(major, monkeypatch)
    action(project, major)
    path = project.relay_root / "actions/stateful/action.yml"
    path.write_text(path.read_text() + "  post-if: failure() && inputs.marker-name == 'first'\n")
    project.commit("Add conditional cleanup")
    project.write_workflow(
        "javascript-condition",
        "jobs: {main: {steps: [{uses: ./.relay/actions/stateful, "
        "with: {marker-name: first}}, {run: exit 1}]}}\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "javascript-condition")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "failed"
    workspace = safe_resolve(worktrees_dir(), run.worktree_path)
    assert (workspace / "cleanup.txt").read_text() == "first\n"


@pytest.mark.parametrize("major", [20, 24])
def test_expired_job_wait_runs_registered_cleanup_without_starting_new_steps(
    major: int, project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from django.utils import timezone

    from relay.web.models import HumanInteraction, NodeRun

    node_runtime(major, monkeypatch)
    action(project, major)
    project.write_workflow(
        "javascript-expired",
        "jobs: {main: {timeout-minutes: 5, steps: "
        "[{uses: ./.relay/actions/stateful, with: {marker-name: expired}}, "
        "{uses: relay/human-wait@v1, with: {prompt: Continue?}}, "
        "{run: echo never > never.txt}]}}\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "javascript-expired")
    engine.drain(run_id)
    job = NodeRun.objects.get(run_id=run_id, scope_path="root.main")
    parent = NodeAttempt.objects.get(node_run=job)
    interaction = HumanInteraction.objects.get(run_id=run_id)
    assert interaction.deadline == parent.deadline_at
    elapsed = timezone.now() - timedelta(seconds=1)
    NodeAttempt.objects.filter(pk=parent.pk).update(deadline_at=elapsed)
    HumanInteraction.objects.filter(pk=interaction.pk).update(deadline=elapsed)
    assert engine.store.expire_human_waits() == 1
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "failed"
    workspace = safe_resolve(worktrees_dir(), run.worktree_path)
    assert (workspace / "cleanup.txt").read_text() == "expired\n"
    assert not (workspace / "never.txt").exists()
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main.step_3").status == "canceled"
