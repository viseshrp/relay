"""Deterministic per-node exact-model route compilation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from relay.errors import WorkflowValidationError

from .loader import LoadedWorkflow, resolve_workflow_path
from .schema import (
    ActionsJobNode,
    AgentNode,
    AgentOptions,
    LoopNode,
    NodeDefinition,
    SubworkflowNode,
    WorkflowDefinition,
)
from .scope import loop_iteration_scope, node_scope
from .validation import ValidatedWorkflow


@dataclass(frozen=True, slots=True)
class RouteRequirement:
    """Exact model and ordered candidates required by one runtime node."""

    scope_path: str
    model_value: str
    effective_agent_order: tuple[str, ...]
    permission_profile: str | None = field(default=None, kw_only=True)
    agent_options: Mapping[str, AgentOptions] = field(default_factory=dict, kw_only=True)

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result.pop("permission_profile")
        result.pop("agent_options")
        for name in ("effort", "permission_mode"):
            if result.get(name) is None:
                result.pop(name, None)
        return result


@dataclass(frozen=True, slots=True)
class RouteEntry(RouteRequirement):
    """A preflight-proven agent selection persisted in a run snapshot."""

    selected_agent: str
    effort: str | None = field(default=None, kw_only=True)
    permission_mode: str | None = field(default=None, kw_only=True)


def effective_agent_order(*preference_lists: Sequence[str]) -> tuple[str, ...]:
    """Concatenate node, workflow, then owner preferences without duplicates."""
    result = []
    seen = set()
    for preferences in preference_lists:
        for agent_id in preferences:
            if agent_id not in seen:
                result.append(agent_id)
                seen.add(agent_id)
    return tuple(result)


def _child_workflow(
    reference: str,
    workflows_root: Path,
    subworkflows: Mapping[str, LoadedWorkflow],
) -> LoadedWorkflow:
    path = resolve_workflow_path(workflows_root, reference)
    key = path.relative_to(workflows_root.resolve()).as_posix()
    try:
        return subworkflows[key]
    except KeyError:
        message = f"Subworkflow {reference!r} was not captured."
        raise WorkflowValidationError(message) from None


def _routes_for_nodes(
    nodes: Mapping[str, NodeDefinition],
    definition: WorkflowDefinition,
    *,
    parent_scope: str | None,
    launch_model: str | None,
    owner_agents: Sequence[str],
    workflows_root: Path,
    subworkflows: Mapping[str, LoadedWorkflow],
) -> Iterable[RouteRequirement]:
    for node_id, node in nodes.items():
        if isinstance(node, ActionsJobNode):
            for step_scope, agent in node.bound_agents.items():
                scope = node_scope(parent_scope, node_id) + "." + step_scope
                model = agent.model or launch_model or definition.model
                agents = effective_agent_order(agent.agents, definition.agents, owner_agents)
                if not model or not agents:
                    message = f"Agent step {scope} requires an exact model and provider."
                    raise WorkflowValidationError(message)
                yield RouteRequirement(scope, model, agents, agent_options=agent.agent_options)
            continue
        if isinstance(node, AgentNode):
            model = node.model or launch_model or definition.model
            agents = effective_agent_order(node.agents, definition.agents, owner_agents)
            scope = node_scope(parent_scope, node_id)
            if model is None:
                message = f"Agent node {scope} has no exact model value."
                raise WorkflowValidationError(message, context={"node": scope})
            if not agents:
                message = f"Agent node {scope} has no candidate agents."
                raise WorkflowValidationError(message, context={"node": scope})
            yield RouteRequirement(
                scope,
                model,
                agents,
                permission_profile=node.permission_profile,
                agent_options=node.agent_options,
            )
        elif isinstance(node, LoopNode):
            for iteration in range(1, node.max_iterations + 1):
                loop_scope = loop_iteration_scope(parent_scope, node_id, iteration)
                yield from _routes_for_nodes(
                    node.body,
                    definition,
                    parent_scope=loop_scope,
                    launch_model=launch_model,
                    owner_agents=owner_agents,
                    workflows_root=workflows_root,
                    subworkflows=subworkflows,
                )
        elif isinstance(node, SubworkflowNode):
            child = _child_workflow(node.workflow, workflows_root, subworkflows)
            child_scope = node_scope(parent_scope, node_id)
            yield from _routes_for_nodes(
                child.definition.nodes,
                child.definition,
                parent_scope=child_scope,
                launch_model=launch_model,
                owner_agents=owner_agents,
                workflows_root=workflows_root,
                subworkflows=subworkflows,
            )


def compile_route_requirements(
    workflow: ValidatedWorkflow,
    *,
    launch_model: str | None = None,
    owner_agents: Sequence[str] = (),
) -> tuple[RouteRequirement, ...]:
    """Eagerly key all bounded runtime agent instances by scope path."""
    workflows_root = workflow.root.path.parent.resolve()
    requirements = tuple(
        _routes_for_nodes(
            workflow.root.definition.nodes,
            workflow.root.definition,
            parent_scope=None,
            launch_model=launch_model,
            owner_agents=owner_agents,
            workflows_root=workflows_root,
            subworkflows=workflow.subworkflows,
        )
    )
    scopes = [item.scope_path for item in requirements]
    if len(scopes) != len(set(scopes)):
        message = "Route compilation produced a duplicate scope path."
        raise WorkflowValidationError(message)
    return requirements


def serialize_route_table(entries: Iterable[RouteRequirement]) -> dict[str, dict[str, object]]:
    """Serialize routes under their unique runtime scope paths."""
    return {
        entry.scope_path: {
            "model_value": entry.model_value,
            "effective_agent_order": list(entry.effective_agent_order),
            **({"selected_agent": entry.selected_agent} if isinstance(entry, RouteEntry) else {}),
            **(
                {
                    name: value
                    for name in ("effort", "permission_mode")
                    if (value := getattr(entry, name, None)) is not None
                }
                if isinstance(entry, RouteEntry)
                else {}
            ),
        }
        for entry in entries
    }


__all__ = [
    "RouteEntry",
    "RouteRequirement",
    "compile_route_requirements",
    "effective_agent_order",
    "serialize_route_table",
]
