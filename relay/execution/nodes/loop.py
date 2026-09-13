"""Bounded loop-node execution over scoped child graphs."""

from __future__ import annotations

from relay.errors import NodeExecutionError
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.state import AttemptStopReason
from relay.workflows.expressions import evaluate_expression
from relay.workflows.schema import LoopNode
from relay.workflows.scope import enclosing_scope, loop_iteration_scope

from .base import NestedScopeRunner, expression_context, parse_node


class LoopExecutor:
    """Run at most the declared number of iterations and select exhaustion."""

    def __init__(self, scopes: NestedScopeRunner) -> None:
        self.scopes: NestedScopeRunner = scopes

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, LoopNode)
        parent = enclosing_scope(context.attempt.scope_path)
        combined_outputs: dict[str, dict[str, object]] = {}
        for iteration in range(1, node.max_iterations + 1):
            iteration_scope = loop_iteration_scope(parent, context.attempt.node_id, iteration)
            result = self.scopes.execute_scope(
                context,
                node.body,
                parent_scope=iteration_scope,
                inputs=context.attempt.inputs,
                loop_index=iteration,
            )
            context.runtime.record_loop_iteration(
                context.attempt.node_run_id,
                iteration_scope,
                iteration,
                result.kind,
                result.node_outputs,
            )
            if result.kind is OutcomeKind.WAITING:
                return ExecutionOutcome(OutcomeKind.WAITING)
            if result.kind is OutcomeKind.FAILED:
                return ExecutionOutcome(
                    OutcomeKind.FAILED,
                    stop_reason=AttemptStopReason.FAILED,
                    error_code=result.error_code or NodeExecutionError.error_code,
                )
            combined_outputs = {
                node_id: dict(outputs) for node_id, outputs in result.node_outputs.items()
            }
            if node.until is not None:
                context_values = expression_context(context)
                context_values["needs"] = {
                    node_id: {"outputs": outputs} for node_id, outputs in combined_outputs.items()
                }
                context_values["loop"] = {"index": iteration}
                complete = evaluate_expression(node.until, context_values)
                if not isinstance(complete, bool):
                    message = "A loop `until` expression must return a boolean."
                    raise NodeExecutionError(message, context={"node": context.attempt.scope_path})
                if complete:
                    return ExecutionOutcome(OutcomeKind.SUCCEEDED)
        return ExecutionOutcome(
            OutcomeKind.SUCCEEDED,
            selected_branch=node.exhausted,
        )


__all__ = ["LoopExecutor"]
