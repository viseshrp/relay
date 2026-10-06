"""Agent-node execution against Relay's provider-independent driver port."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from relay.errors import OutputValidationError
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.state import AttemptStopReason
from relay.paths import safe_resolve
from relay.workflows.schema import AgentNode

from .base import declared_output_artifacts, parse_node, validated_outputs


class AgentNodeDriver(Protocol):
    """Narrow adapter used by the node layer; provider details stay outside it."""

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome: ...


class AgentExecutor:
    """Run one fresh agent session, then validate its declared handoff."""

    driver: AgentNodeDriver

    def __init__(self, driver: AgentNodeDriver) -> None:
        self.driver = driver

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, AgentNode)
        outcome = self.driver.execute(context, node)
        # Retain a rejected report as evidence even when its labels cannot be read.
        # Missing files remain validation errors; escaping paths stop recovery.
        artifacts = {
            name: reference
            for name, reference in declared_output_artifacts(node.outputs).items()
            if safe_resolve(context.worktree, reference).is_file()
        }
        outcome = replace(outcome, declared_artifacts={**outcome.declared_artifacts, **artifacts})
        if outcome.kind is not OutcomeKind.SUCCEEDED:
            return outcome
        try:
            outputs, artifacts = validated_outputs(context.worktree, node.outputs)
        except OutputValidationError as error:
            return replace(
                outcome,
                kind=OutcomeKind.FAILED,
                stop_reason=AttemptStopReason.OUTPUT_INVALID,
                error_code=error.error_code,
                error_message=error.message,
            )
        return replace(
            outcome,
            outputs=outputs,
            declared_artifacts={**outcome.declared_artifacts, **artifacts},
        )


__all__ = ["AgentExecutor", "AgentNodeDriver"]
