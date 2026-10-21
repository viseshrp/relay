"""Gallery cards count top-level jobs and owner approvals."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from relay.workflows.gallery import workflow_size
from relay.workflows.schema import WorkflowDefinition


def test_workflow_size_counts_approvals_and_jobs_without_steps() -> None:
    definition = SimpleNamespace(
        nodes={
            "call": SimpleNamespace(job={"uses": "./.relay/workflows/child.yaml"}),
            "plain": SimpleNamespace(),
            "review": SimpleNamespace(
                job={
                    "steps": [
                        {"uses": "relay/human-wait@v1", "with": {"prompt": "Go?"}},
                        {"run": "echo done"},
                        "not a step",
                    ]
                }
            ),
        }
    )
    size = workflow_size(cast(WorkflowDefinition, definition))
    assert size == {"job_count": 3, "approval_count": 1}
