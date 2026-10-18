"""Sizes shown on starter and template gallery cards."""

from __future__ import annotations

from .actions.builtins import is_builtin
from .schema import WorkflowDefinition


def workflow_size(definition: WorkflowDefinition) -> dict[str, int]:
    """Count top-level jobs and owner approvals for a gallery card."""
    approvals = 0
    for node in definition.nodes.values():
        job = getattr(node, "job", None)
        steps = job.get("steps") if isinstance(job, dict) else None
        if isinstance(steps, list):
            approvals += sum(
                isinstance(step, dict) and is_builtin(step.get("uses"), "human-wait")
                for step in steps
            )
    return {"job_count": len(definition.nodes), "approval_count": approvals}
