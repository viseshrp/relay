"""Workflow loading and execution accept only the current jobs/steps language."""

from pathlib import Path

import pytest

from relay.errors import PersistenceError, WorkflowValidationError
from relay.execution.nodes import node_executors
from relay.web.models import RunSnapshot
from relay.web.repositories import _compiled_run_graph
from relay.workflows.loader import load_workflow_text
from tests.support import InlineEngine, RelayProject


@pytest.mark.parametrize(
    "source",
    [
        "version: 1\nname: Old\nnodes: {}\n",
        "version: 1\nname: Old\nnodes: {work: {type: command, run: [git, status]}}\n",
        "name: Old\nnodes: {work: {type: agent}}\n",
        "version: 1\nname: Mixed\njobs: {work: {steps: [{run: echo ready}]}}\n",
    ],
    ids=["empty-nodes", "command-node", "unversioned-nodes", "mixed-version"],
)
def test_workflow_loader_rejects_the_removed_nodes_format(source: str) -> None:
    with pytest.raises(WorkflowValidationError):
        load_workflow_text(source, source=Path("workflow.yaml"))


def test_worker_registers_only_job_and_step_executors() -> None:
    assert set(node_executors()) == {"actions_job", "actions_step"}


def test_a_missing_frozen_plan_does_not_reparse_snapshot_yaml(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "current", "name: Current\njobs: {work: {steps: [{run: print('ready'), shell: python}]}}\n"
    )
    run_id = engine.launch(project, "current")
    RunSnapshot.objects.filter(run_id=run_id).update(resolved_definition={})
    _compiled_run_graph.cache_clear()

    with pytest.raises(PersistenceError):
        engine.store.run_graph(run_id)


@pytest.mark.parametrize("corruption", ["old-semantics", "old-node"])
def test_queued_removed_runs_cannot_start_or_recover(
    project: RelayProject, engine: InlineEngine, corruption: str
) -> None:
    from relay.execution.dispatch import ClaimDisposition
    from relay.web.models import NodeAttempt, NodeRun, Run

    project.write_workflow("queued", "jobs: {work: {steps: [{run: print(1), shell: python}]}}\n")
    run_id = engine.launch(project, "queued")
    token = engine.tokens.popleft()
    if corruption == "old-semantics":
        RunSnapshot.objects.filter(run_id=run_id).update(semantics_revision="removed-format")
    else:
        snapshot = RunSnapshot.objects.get(run_id=run_id)
        plan = snapshot.resolved_definition
        plan["nodes"]["work"] = {"type": "command", "run": ["git", "status"]}
        RunSnapshot.objects.filter(run_id=run_id).update(resolved_definition=plan)
        NodeRun.objects.filter(run_id=run_id).update(node_type="command")
    _compiled_run_graph.cache_clear()

    assert (
        engine.store.claim_dispatch(token, engine.worker_id).disposition is ClaimDisposition.IGNORED
    )
    assert not NodeAttempt.objects.filter(node_run__run_id=run_id).exists()
    Run.objects.filter(pk=run_id).update(status="failed")
    with pytest.raises(PersistenceError):
        engine.store.manual_rerun_target(run_id, "root.work", "unsupported-retry")
    if corruption == "old-semantics":
        assert run_id not in engine.store.active_run_ids()
        Run.objects.filter(pk=run_id).update(status="interrupted")
        assert run_id not in engine.store.interrupted_run_ids()
