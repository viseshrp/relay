"""End-to-end runs through launch, dispatch, claims, executors, and settlement."""

from __future__ import annotations

from relay.web.models import Run
from tests.support import (
    PYTHON,
    InlineEngine,
    RelayProject,
    event_types,
    git,
    node_statuses,
    run_status,
)


def test_command_chain_succeeds_and_records_events(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "chain",
        f"""version: 1
name: Chain
nodes:
  first:
    type: command
    run: ["{PYTHON}", -c, "print('first')"]
  second:
    type: command
    needs: [first]
    run: [git, status, --short]
""",
    )

    run_id = engine.launch(project, "chain")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert node_statuses(run_id) == {"root.first": "succeeded", "root.second": "succeeded"}
    assert event_types(run_id, "run.")[-1] == "run.succeeded"
    assert "command.stdout" in event_types(run_id, "command.")


def test_writer_commit_advances_the_recorded_head(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "writer",
        """version: 1
name: Writer
nodes:
  change:
    type: command
    writes: true
    run: [git, commit, --allow-empty, -q, -m, "writer change"]
""",
    )
    source = git(project.repository, "rev-parse", "HEAD")

    run_id = engine.launch(project, "writer")
    engine.drain(run_id)

    run = Run.objects.get(pk=run_id)
    assert run.status == "succeeded"
    assert run.recorded_head != source
    assert git(project.repository, "rev-parse", f"{run.recorded_head}^") == source
