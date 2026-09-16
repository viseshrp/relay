"""Agent-node execution against Relay's provider-independent driver port."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from relay.errors import AgentLaunchError
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.workflows.schema import AgentNode


class AgentNodeDriver(Protocol):
    """Narrow adapter used by the node layer; provider details stay outside it."""

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome: ...


class MissingAgentDriver:
    """Fail closed until agent discovery supplies a preflight-proven route."""

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        del node
        message = "No certified agent driver is available for this route."
        raise AgentLaunchError(message, context={"node": context.attempt.scope_path})


class AgentExecutor:
    """Run one fresh agent session, then validate its declared handoff."""

    def __init__(self, driver: AgentNodeDriver) -> None:
        self.driver: AgentNodeDriver = driver

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        # Load shared helpers after package initialization to avoid an import cycle.
        from .base import parse_node, validated_outputs

        node = parse_node(context, AgentNode)
        outcome = self.driver.execute(context, node)
        if outcome.kind is not OutcomeKind.SUCCEEDED:
            return outcome
        outputs, artifacts = validated_outputs(context.worktree, node.outputs)
        return replace(
            outcome,
            outputs=outputs,
            declared_artifacts={**outcome.declared_artifacts, **artifacts},
        )


__all__ = ["AgentExecutor", "AgentNodeDriver", "MissingAgentDriver"]
