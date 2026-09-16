"""The six provider-independent Relay node executors."""

from __future__ import annotations

from relay.execution.runner import AttemptExecutor
from relay.execution.state import NodeType

from .agent import AgentExecutor, AgentNodeDriver
from .base import NestedScopeRunner, SynchronousScopeRunner
from .command import CommandExecutor
from .condition import ConditionExecutor
from .human_wait import HumanWaitExecutor
from .loop import LoopExecutor
from .subworkflow import SubworkflowExecutor


def node_executors(
    *,
    agent_driver: AgentNodeDriver | None = None,
    scope_runner: NestedScopeRunner | None = None,
) -> dict[str, AttemptExecutor]:
    """Build one registry keyed by the stable persisted node-type values."""
    if agent_driver is None:
        # Agent modules load only when the worker builds its executor registry.
        from relay.agents.driver import RoutedAgentNodeDriver

        driver = RoutedAgentNodeDriver()
    else:
        driver = agent_driver
    scopes = scope_runner if scope_runner is not None else SynchronousScopeRunner(driver)
    return {
        NodeType.AGENT.value: AgentExecutor(driver),
        NodeType.COMMAND.value: CommandExecutor(),
        NodeType.HUMAN_WAIT.value: HumanWaitExecutor(),
        NodeType.CONDITION.value: ConditionExecutor(),
        NodeType.LOOP.value: LoopExecutor(scopes),
        NodeType.SUBWORKFLOW.value: SubworkflowExecutor(scopes),
    }


__all__ = [
    "AgentExecutor",
    "CommandExecutor",
    "ConditionExecutor",
    "HumanWaitExecutor",
    "LoopExecutor",
    "SubworkflowExecutor",
    "node_executors",
]
