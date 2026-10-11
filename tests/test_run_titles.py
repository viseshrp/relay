"""Rendered titles remain bounded without losing launch inputs or grapheme clusters."""

import pytest

from relay.errors import WorkflowValidationError
from relay.web.models import Run, RunSnapshot
from relay.workflows.actions.language import load
from tests.support import InlineEngine, RelayProject


@pytest.mark.parametrize("cluster", ["👩‍💻", "e\u0301", "🇺🇸", "👍🏽", "क्‍ष"])
def test_rendered_titles_truncate_before_a_grapheme_and_retain_inputs(
    project: RelayProject, engine: InlineEngine, cluster: str
) -> None:
    project.write_workflow(
        "check",
        "name: Check\nrun-name: ${{ inputs.task }}\non:\n  workflow_dispatch:\n"
        "    inputs:\n      task: {type: string, required: true}\n"
        "jobs: {check: {steps: [{run: echo Ready}]}}\n",
    )
    task = "x" * 998 + cluster + " remaining task" * 100
    run_id = engine.launch(project, "check", inputs={"task": task})
    run = Run.objects.get(pk=run_id)
    snapshot = RunSnapshot.objects.get(run=run)
    assert run.title == "x" * 998 + "…"
    assert len(run.title) <= 1000
    assert snapshot.typed_inputs["task"] == task


def test_literal_title_limit_is_still_validated_on_save() -> None:
    with pytest.raises(WorkflowValidationError):
        load("run-name: " + "x" * 1001 + "\njobs: {check: {steps: [{run: echo Ready}]}}\n")
