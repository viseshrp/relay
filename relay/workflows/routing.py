"""Deterministic per-node exact-model route compilation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field

from relay.errors import WorkflowValidationError

from .schema import (
    AgentOptions,
)
from .scope import node_scope
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


def compile_route_requirements(
    workflow: ValidatedWorkflow,
    *,
    launch_model: str | None = None,
    owner_agents: Sequence[str] = (),
) -> tuple[RouteRequirement, ...]:
    """Freeze exact routes for the bound agent steps of current workflow jobs."""
    requirements = []
    definition = workflow.root.definition
    for job_id, job in definition.nodes.items():
        for step_scope, agent in job.bound_agents.items():
            scope = node_scope(None, job_id) + "." + step_scope
            model = agent.model or launch_model
            agents = effective_agent_order(agent.agents, owner_agents)
            if not model or not agents:
                message = f"Agent step {scope} requires an exact model and provider."
                raise WorkflowValidationError(message)
            requirements.append(
                RouteRequirement(scope, model, agents, agent_options=agent.agent_options)
            )
    scopes = [item.scope_path for item in requirements]
    if len(scopes) != len(set(scopes)):
        message = "Route compilation produced a duplicate scope path."
        raise WorkflowValidationError(message)
    return tuple(requirements)


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
