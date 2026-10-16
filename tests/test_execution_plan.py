"""Execution uses frozen job and step plans without reparsing workflow source."""

import pytest

from relay.errors import PersistenceError
from relay.execution.nodes import node_executors
from relay.web.models import RunSnapshot
from relay.web.repositories import _compiled_run_graph
from tests.support import InlineEngine, RelayProject


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


def test_invalid_execution_nodes_cannot_start_or_retry(
    project: RelayProject, engine: InlineEngine
) -> None:
    from relay.execution.dispatch import ClaimDisposition
    from relay.web.models import NodeAttempt, NodeRun, Run

    project.write_workflow("queued", "jobs: {work: {steps: [{run: print(1), shell: python}]}}\n")
    run_id = engine.launch(project, "queued")
    token = engine.tokens.popleft()
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    plan = snapshot.resolved_definition
    plan["nodes"]["work"] = {"type": "invalid"}
    RunSnapshot.objects.filter(run_id=run_id).update(resolved_definition=plan)
    NodeRun.objects.filter(run_id=run_id).update(node_type="invalid")
    _compiled_run_graph.cache_clear()

    assert (
        engine.store.claim_dispatch(token, engine.worker_id).disposition is ClaimDisposition.IGNORED
    )
    assert not NodeAttempt.objects.filter(node_run__run_id=run_id).exists()
    Run.objects.filter(pk=run_id).update(status="failed")
    with pytest.raises(PersistenceError):
        engine.store.manual_rerun_target(run_id, "root.work", "invalid-plan-retry")
