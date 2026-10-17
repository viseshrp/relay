"""Agent-node execution against Relay's provider-independent driver port."""

from __future__ import annotations

from typing import Protocol

from relay.execution.runner import AttemptContext, ExecutionOutcome
from relay.workflows.schema import AgentNode


class AgentNodeDriver(Protocol):
    """Narrow adapter used by the node layer; provider details stay outside it."""

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome: ...


__all__ = ["AgentNodeDriver"]
