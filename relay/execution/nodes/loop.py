"""Bounded loop-node execution over scoped child graphs."""

from __future__ import annotations

from relay.errors import NodeExecutionError
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.state import AttemptStopReason
from relay.workflows.expressions import evaluate_expression
from relay.workflows.repairs import accepted_verdict
from relay.workflows.schema import LoopNode
from relay.workflows.scope import enclosing_scope, loop_iteration_scope

from .base import NestedScopeRunner, expression_context, parse_node


class LoopExecutor:
    """Run at most the declared number of iterations and select exhaustion."""

    scopes: NestedScopeRunner

    def __init__(self, scopes: NestedScopeRunner) -> None:
        self.scopes = scopes

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, LoopNode)
        parent = enclosing_scope(context.attempt.scope_path)
        repair = node.repair_rule
        if repair is not None:
            original = context.attempt.upstream_outputs.get(repair.source, {})
            if accepted_verdict(original, repair.accepted_output, repair.accepted_value):
                return ExecutionOutcome(OutcomeKind.SUCCEEDED, outputs=dict(original))
        combined_outputs = {}
        first_iteration = 1
        entry_point = context.attempt.run_metadata.get("entry_point")
        prefix = f"{context.attempt.scope_path}#"
        if isinstance(entry_point, str) and entry_point.startswith(prefix):
            raw_iteration = entry_point[len(prefix) :].split(".", maxsplit=1)[0]
            if raw_iteration.isdigit():
                first_iteration = int(raw_iteration)
        if not 1 <= first_iteration <= node.max_iterations:
            message = "The declared loop entry point is outside its iteration bound."
            raise NodeExecutionError(message, context={"node": context.attempt.scope_path})
        for iteration in range(first_iteration, node.max_iterations + 1):
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
            if context.timed_out() or result.error_code == "node_timeout":
                return ExecutionOutcome(
                    OutcomeKind.FAILED,
                    stop_reason=AttemptStopReason.TIMEOUT,
                    error_code="node_timeout",
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
            if repair is not None:
                verified = combined_outputs.get("verify", {})
                if accepted_verdict(verified, repair.accepted_output, repair.accepted_value):
                    return ExecutionOutcome(OutcomeKind.SUCCEEDED, outputs=verified)
                continue
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
        if repair is not None:
            return ExecutionOutcome(
                OutcomeKind.FAILED,
                stop_reason=AttemptStopReason.FAILED,
                error_code="repair_exhausted",
                outputs=combined_outputs.get("verify", {}),
            )
        return ExecutionOutcome(
            OutcomeKind.SUCCEEDED,
            selected_branch=node.exhausted,
        )


__all__ = ["LoopExecutor"]
