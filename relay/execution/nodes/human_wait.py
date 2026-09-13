"""Durable human-wait node execution."""

from __future__ import annotations

from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.workflows.schema import HumanWaitNode

from .base import duration_seconds, parse_node


class HumanWaitExecutor:
    """Pause without holding a process; reconciliation handles answer or deadline."""

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, HumanWaitNode)
        candidates = [
            seconds
            for seconds in (duration_seconds(node.deadline), duration_seconds(node.timeout))
            if seconds is not None
        ]
        timeout = min(candidates) if candidates else None
        return ExecutionOutcome(OutcomeKind.WAITING, wait_timeout_seconds=timeout)


__all__ = ["HumanWaitExecutor"]
