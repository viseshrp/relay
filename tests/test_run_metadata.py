"""Run metadata comes from the immutable launch source."""

from tests.support import InlineEngine, RelayProject


def test_run_detail_uses_the_captured_workflow_name_after_source_changes(
    project: RelayProject, engine: InlineEngine
) -> None:
    from relay.web.repositories import DjangoReadStore

    project.write_workflow(
        "file-label", "name: Captured name\njobs: {check: {steps: [{run: echo Ready}]}}\n"
    )
    run_id = engine.launch(project, "file-label")
    project.write(".relay/workflows/file-label.yaml", "name: Owner changed this\njobs: {}\n")
    detail, _ = DjangoReadStore().run_detail(run_id, collection="nodes", since=0, limit=200)
    assert detail["workflow_name"] == "Captured name"
