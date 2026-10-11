"""Exercise Actions jobs through durable claims and disposable Git worktrees."""

from pathlib import Path

import pytest

from relay.execution.launch import LaunchRequest, launch_workflow
from relay.execution.nodes import node_executors
from relay.web.models import NodeRun, Run, RunEvent, RunSnapshot
from relay.workflows.defaults import validate_defaults
from tests.support import FakeAgents, InlineEngine, RelayProject, git


def test_local_contexts_and_command_files_expose_real_host_and_run_facts(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "local-facts",
        """on:
  workflow_dispatch:
    inputs:
      enabled: {type: boolean, default: true}
defaults: {run: {shell: python}}
jobs:
  check:
    steps:
      - id: facts
        env:
          RUN_FACTS: ${{ toJSON(relay) }}
          HOST_FACTS: ${{ toJSON(host) }}
        run: |
          import json, os
          from pathlib import Path
          run = json.loads(os.environ['RUN_FACTS'])
          host = json.loads(os.environ['HOST_FACTS'])
          assert run['run_id'] == os.environ['RELAY_RUN_ID']
          assert run['sha'] == os.environ['RELAY_SHA']
          assert run['event']['inputs']['enabled'] is True
          assert run['attempt_number'] == 1
          assert host['os'] == os.environ['RELAY_HOST_OS']
          assert Path(host['temp']).is_dir()
          assert set(host) == {'os', 'arch', 'name', 'temp'}
          assert not {'token', 'api_url', 'server_url', 'repository_owner'} & run.keys()
          Path(os.environ['RELAY_OUTPUT']).write_text('value=local\\n')
    outputs: {value: '${{ steps.facts.outputs.value }}'}
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "local-facts")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.check").outputs == {"value": "local"}


def test_matrix_fail_fast_expression_false_continues_local_variants(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "matrix-policy",
        """defaults: {run: {shell: python}}
jobs:
  check:
    strategy:
      fail-fast: ${{ false }}
      matrix: {target: [fail, pass]}
    steps:
      - env:
          TARGET: ${{ matrix.target }}
          INDEX: ${{ strategy.job-index }}
          TOTAL: ${{ strategy.job-total }}
        run: |
          import os, sys
          assert os.environ['TOTAL'] == '2'
          assert os.environ['INDEX'] == ('0' if os.environ['TARGET'] == 'fail' else '1')
          sys.exit(1 if os.environ['TARGET'] == 'fail' else 0)
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "matrix-policy")
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "failed"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.check.variant_1").status == "failed"
    assert (
        NodeRun.objects.get(run_id=run_id, scope_path="root.check.variant_2").status == "succeeded"
    )


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
    database_threads: None,
) -> None:
    del database_threads
    fake_agents.install("codex", mode="configuration")
    defaults = validate_defaults({"providers": {"codex": {"model": "m1", "effort": "low"}}})
    project.write_workflow(
        "effort",
        "defaults: {run: {shell: bash}}\n" + "jobs:\n  main:\n    steps:\n"
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


def test_ordered_steps_share_edits_until_job_commit(project: RelayProject, tmp_path: Path) -> None:
    project.write_workflow(
        "jobs",
        "defaults: {run: {shell: bash}}\n"
        + """name: Shared workspace
on: workflow_dispatch
jobs:
  build:
    steps:
      - run: echo accepted > result.txt
      - run: test "$(cat result.txt)" = accepted
      - run: git add result.txt && git commit -m result
      - id: answer
        run: echo "value=42" >> "$RELAY_OUTPUT"
    outputs:
      value: ${{ steps.answer.outputs.value }}
  followup:
    needs: build
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


def test_failed_step_allows_failure_followup_and_tolerance(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "failure",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  check:
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


def test_reusable_workflow_and_serial_matrix_export_strings(
    project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "called",
        "defaults: {run: {shell: bash}}\n"
        + """on:
  workflow_call:
    inputs:
      value: {type: string, required: true}
    outputs:
      answer:
        value: ${{ jobs.echo.outputs.answer }}
jobs:
  echo:
    outputs:
      answer: ${{ steps.answer.outputs.answer }}
    steps:
      - id: answer
        env:
          VALUE: ${{ inputs.value }}
        run: echo "answer=$VALUE" >> "$RELAY_OUTPUT"
""",
    )
    project.write_workflow(
        "matrix",
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
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
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        "defaults: {run: {shell: bash}}\n"
        + """on: workflow_dispatch
jobs:
  check:
    env:
      KEY: ${{ secrets.KEY }}
    steps:
      - id: output
        run: echo "$KEY"; echo "value=$KEY" >> "$RELAY_OUTPUT"
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
