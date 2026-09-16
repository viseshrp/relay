"""Deterministic condition-node execution."""

from __future__ import annotations

from relay.errors import NodeExecutionError
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.workflows.expressions import evaluate_expression
from relay.workflows.schema import ConditionNode

from .base import expression_context, parse_node


class ConditionExecutor:
    """Evaluate one whitelisted expression and select one declared target."""

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, ConditionNode)
        result = evaluate_expression(node.expr, expression_context(context))
        if not isinstance(result, str) or result not in node.branches:
            message = f"Condition result {result!r} is not a declared branch label."
            raise NodeExecutionError(message, context={"node": context.attempt.scope_path})
        return ExecutionOutcome(
            OutcomeKind.SUCCEEDED,
            selected_branch=node.branches[result],
        )


__all__ = ["ConditionExecutor"]
