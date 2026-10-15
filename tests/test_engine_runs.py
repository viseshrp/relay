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
        (
            f"name: Chain\n"
            f"jobs:\n"
            f"  first:\n"
            f"    steps:\n"
            f"    - id: work\n"
            f"      uses: relay/command@v1\n"
            f"      with:\n"
            f'        argv: "[\\"{PYTHON}\\", \\"-c\\", \\"print(\'first\')\\"]"\n'
            f"  second:\n"
            f"    needs:\n"
            f"    - first\n"
            f"    steps:\n"
            f"    - id: work\n"
            f"      uses: relay/command@v1\n"
            f"      with:\n"
            f'        argv: \'["git", "status", "--short"]\'\n'
        ),
    )

    run_id = engine.launch(project, "chain")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert node_statuses(run_id) == {
        "root.first": "succeeded",
        "root.first.work": "succeeded",
        "root.second": "succeeded",
        "root.second.work": "succeeded",
    }
    assert event_types(run_id, "run.")[-1] == "run.succeeded"
    assert "command.stdout" in event_types(run_id, "command.")


def test_writer_commit_advances_the_recorded_head(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "writer",
        (
            "name: Writer\n"
            "jobs:\n"
            "  change:\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/command@v1\n"
            "      with:\n"
            '        argv: \'["git", "commit", "--allow-empty", "-q", "-m", "writer '
            "change\"]'\n"
        ),
    )
    source = git(project.repository, "rev-parse", "HEAD")

    run_id = engine.launch(project, "writer")
    engine.drain(run_id)

    run = Run.objects.get(pk=run_id)
    assert run.status == "succeeded"
    assert run.recorded_head != source
    assert git(project.repository, "rev-parse", f"{run.recorded_head}^") == source
