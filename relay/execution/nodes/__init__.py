"""Worker executors for the current job and step execution records."""

from __future__ import annotations

from relay.execution.runner import AttemptExecutor
from relay.execution.state import NodeType

from .actions import ActionsJobExecutor, ActionsStepExecutor
from .agent import AgentNodeDriver


def node_executors(
    *,
    agent_driver: AgentNodeDriver | None = None,
) -> dict[str, AttemptExecutor]:
    """Build one registry keyed by the stable persisted node-type values."""
    if agent_driver is None:
        # Agent modules load only when the worker builds its executor registry.
        from relay.agents.driver import RoutedAgentNodeDriver

        driver = RoutedAgentNodeDriver()
    else:
        driver = agent_driver
    return {
        NodeType.ACTIONS_JOB.value: ActionsJobExecutor(driver),
        NodeType.ACTIONS_STEP.value: ActionsStepExecutor(driver),
    }


__all__ = ["node_executors"]
