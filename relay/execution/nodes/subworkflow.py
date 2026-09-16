"""Synchronous subworkflow execution inside the owning run."""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from relay.errors import NodeExecutionError, WorkflowValidationError
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.state import AttemptStopReason
from relay.workflows.expressions import evaluate_expression
from relay.workflows.schema import SubworkflowNode, WorkflowDefinition
from relay.workflows.validation import resolve_inputs

from .base import NestedScopeRunner, expression_context, parse_node


def _snapshot_key(reference: str) -> str:
    path = PurePosixPath(reference)
    return path.as_posix() if path.suffix in {".yaml", ".yml"} else f"{path.as_posix()}.yaml"


def _child_definition(context: AttemptContext, reference: str) -> WorkflowDefinition:
    record = context.attempt.subworkflows.get(_snapshot_key(reference))
    if not isinstance(record, dict) or not isinstance(record.get("yaml"), str):
        message = f"Subworkflow {reference!r} is missing from the run snapshot."
        raise NodeExecutionError(message, context={"node": context.attempt.scope_path})
    try:
        raw = YAML(typ="safe").load(record["yaml"])
        return WorkflowDefinition.model_validate(raw)
    except (TypeError, ValidationError, YAMLError):
        message = f"Snapshotted subworkflow {reference!r} is invalid."
        raise NodeExecutionError(message, context={"node": context.attempt.scope_path}) from None


def _input_value(value: object, context: AttemptContext) -> object:
    if isinstance(value, str) and value.startswith("${{") and value.endswith("}}"):
        return evaluate_expression(value, expression_context(context))
    return value


class SubworkflowExecutor:
    """Execute one captured child graph and expose only declared child outputs."""

    def __init__(self, scopes: NestedScopeRunner) -> None:
        self.scopes: NestedScopeRunner = scopes

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, SubworkflowNode)
        definition = _child_definition(context, node.workflow)
        supplied = {name: _input_value(value, context) for name, value in node.inputs.items()}
        try:
            inputs = resolve_inputs(definition, supplied)
        except WorkflowValidationError as error:
            message = f"Subworkflow {node.workflow!r} received invalid inputs: {error.message}"
            raise NodeExecutionError(
                message,
                context={"node": context.attempt.scope_path},
            ) from None
        result = self.scopes.execute_scope(
            context,
            definition.nodes,
            parent_scope=context.attempt.scope_path,
            inputs=inputs,
        )
        if result.kind is not OutcomeKind.SUCCEEDED:
            timed_out = context.timed_out() or result.error_code == "node_timeout"
            if timed_out:
                return ExecutionOutcome(
                    OutcomeKind.FAILED,
                    stop_reason=AttemptStopReason.TIMEOUT,
                    error_code="node_timeout",
                )
            return ExecutionOutcome(
                result.kind,
                stop_reason=(
                    None if result.kind is OutcomeKind.WAITING else AttemptStopReason.FAILED
                ),
                error_code=result.error_code,
            )
        outputs: dict[str, object] = {}
        for name, child_reference in node.outputs.items():
            child_id, separator, output_name = child_reference.partition(".")
            child_outputs = result.node_outputs.get(child_id)
            if not separator or child_outputs is None or output_name not in child_outputs:
                message = f"Child output {child_reference!r} was not produced."
                raise NodeExecutionError(message, context={"node": context.attempt.scope_path})
            outputs[name] = child_outputs[output_name]
        return ExecutionOutcome(OutcomeKind.SUCCEEDED, outputs=outputs)


__all__ = ["SubworkflowExecutor"]
