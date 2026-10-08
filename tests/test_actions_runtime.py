"""Exercise Actions jobs through durable claims and disposable Git worktrees."""

from pathlib import Path

import pytest

from relay.execution.launch import LaunchRequest, launch_workflow
from relay.execution.nodes import node_executors
from relay.web.models import NodeRun, Run, RunEvent, RunSnapshot
from relay.workflows.defaults import validate_defaults
from tests.support import FakeAgents, InlineEngine, RelayProject, git


@pytest.mark.parametrize(
    ("declaration", "effort", "executed"),
    [
        ("", "low", "low"),
        ("effort: null", None, "high"),
        ("effort: ''", None, "high"),
        ("effort: high", "high", "high"),
    ],
)
def test_agent_effort_inherits_or_explicitly_preserves_provider_defaults(
    declaration: str,
    effort: str | None,
    executed: str,
    project: RelayProject,
    tmp_path: Path,
    fake_agents: FakeAgents,
) -> None:
    fake_agents.install("codex", mode="configuration")
    defaults = validate_defaults({"providers": {"codex": {"model": "m1", "effort": "low"}}})
    project.write_workflow(
        "effort",
        "jobs:\n  main:\n    runs-on: self-hosted\n    steps:\n"
        "      - id: check\n        uses: relay/agent@v1\n        with:\n"
        f"          agent: codex\n          model: m1\n          {declaration}\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    request = LaunchRequest("effort", {}, None, "retain", None, (), "owner", defaults=defaults)
    run_id = launch_workflow(
        engine.store, project.relay_root, project.project_id, request, engine.tokens.append
    ).run_id
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    route = RunSnapshot.objects.get(run_id=run_id).route_table["root.main.check"]
    assert route.get("effort") == effort
    texts = RunEvent.objects.filter(run_id=run_id).values_list("payload", flat=True)
    assert any(row.get("text") == f"config: model=m1;effort={executed};mode=ask" for row in texts)


def test_ordered_steps_share_edits_until_job_commit(project, tmp_path):
    project.write_workflow(
        "jobs",
        """name: Shared workspace
on: workflow_dispatch
jobs:
  build:
    runs-on: self-hosted
    steps:
      - run: echo accepted > result.txt
      - run: test "$(cat result.txt)" = accepted
      - run: git add result.txt && git commit -m result
      - id: answer
        run: echo "value=42" >> "$GITHUB_OUTPUT"
    outputs:
      value: ${{ steps.answer.outputs.value }}
  followup:
    needs: build
    runs-on: self-hosted
    steps:
      - run: test "$(cat result.txt)" = accepted
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "jobs")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "succeeded"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.build").outputs == {"value": "42"}
    assert git(project.repository, "rev-parse", "HEAD") == run.source_commit


def test_failed_step_allows_failure_followup_and_tolerance(project, tmp_path):
    project.write_workflow(
        "failure",
        """on: workflow_dispatch
jobs:
  check:
    runs-on: self-hosted
    steps:
      - id: tolerated
        continue-on-error: true
        run: exit 2
      - run: test '${{ steps.tolerated.outcome }}' = failure
      - run: exit 1
      - if: failure()
        run: echo recovered
  audit:
    needs: check
    if: failure()
    runs-on: self-hosted
    steps:
      - run: echo audit
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "failure")
    engine.drain(run_id)
    states = dict(NodeRun.objects.filter(run_id=run_id).values_list("scope_path", "status"))
    assert states["root.check.step_4"] == "succeeded"
    assert states["root.audit"] == "succeeded"
    assert Run.objects.get(pk=run_id).status == "failed"


def test_reusable_workflow_and_serial_matrix_export_strings(project, tmp_path):
    project.write_workflow(
        "called",
        """on:
  workflow_call:
    inputs:
      value: {type: string, required: true}
    outputs:
      answer:
        value: ${{ jobs.echo.outputs.answer }}
jobs:
  echo:
    runs-on: self-hosted
    outputs:
      answer: ${{ steps.answer.outputs.answer }}
    steps:
      - id: answer
        env:
          VALUE: ${{ inputs.value }}
        run: echo "answer=$VALUE" >> "$GITHUB_OUTPUT"
""",
    )
    project.write_workflow(
        "matrix",
        """on: workflow_dispatch
jobs:
  variants:
    strategy:
      matrix:
        value: [a, b]
    uses: ./.relay/workflows/called.yaml
    with:
      value: ${{ matrix.value }}
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "matrix")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.variants").outputs == {"answer": "b"}


def test_secret_refs_freeze_without_bytes_and_logs_mask_split_values(
    project, tmp_path, monkeypatch
):
    from relay.web.actions_bindings import put_binding
    from relay.web.models import RunEvent, RunSnapshot

    put_binding(
        f"project:{project.project_id}",
        "KEY",
        "secret",
        source="environment",
        reference="RELAY_TEST_SECRET",
    )
    monkeypatch.setenv("RELAY_TEST_SECRET", "test-secret")
    project.write_workflow(
        "secrets",
        """on: workflow_dispatch
jobs:
  check:
    runs-on: self-hosted
    env:
      KEY: ${{ secrets.KEY }}
    steps:
      - id: output
        run: echo "$KEY"; echo "value=$KEY" >> "$GITHUB_OUTPUT"
    outputs:
      value: ${{ steps.output.outputs.value }}
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "secrets")
    engine.drain(run_id)
    import json

    assert "test-secret" not in json.dumps(RunSnapshot.objects.get(run_id=run_id).launch_defaults)
    assert "test-secret" not in json.dumps(
        list(RunEvent.objects.filter(run_id=run_id).values_list("payload", flat=True))
    )
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.check").outputs == {}
