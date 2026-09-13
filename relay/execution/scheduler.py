"""Event-driven node eligibility over precompiled dependency indexes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from relay.errors import WorkflowValidationError
from relay.workflows.expressions import evaluate_expression
from relay.workflows.graph import CompiledGraph
from relay.workflows.schema import NodeDefinition
from relay.workflows.scope import node_scope

from .state import NodeStatus


@dataclass(frozen=True, slots=True)
class Eligibility:
    """One pending node's deterministic next transition."""

    action: str | None
    reason: str


def evaluate_eligibility(
    node: NodeDefinition,
    dependency_statuses: Mapping[str, str],
    expression_context: Mapping[str, object],
) -> Eligibility:
    """Decide readiness from named dependencies without scanning other nodes."""
    unavailable = {
        NodeStatus.FAILED.value,
        NodeStatus.CANCELED.value,
        NodeStatus.SKIPPED.value,
    }
    if any(dependency_statuses.get(item) in unavailable for item in node.needs):
        return Eligibility("dependencies_unreachable", "an upstream dependency is unreachable")
    if any(dependency_statuses.get(item) != NodeStatus.SUCCEEDED.value for item in node.needs):
        return Eligibility(None, "dependencies are still active")
    if node.condition is not None:
        result = evaluate_expression(node.condition, expression_context)
        if not isinstance(result, bool):
            message = "A node `if` expression must return a boolean."
            raise WorkflowValidationError(message)
        if not result:
            return Eligibility("guard_false", "the node guard evaluated false")
    return Eligibility("dependencies_satisfied", "all dependencies and the guard passed")


def initial_scope_candidates(graph: CompiledGraph, parent_scope: str | None) -> tuple[str, ...]:
    """Return only root nodes from the one-time O(V+E) initialization pass."""
    return tuple(
        node_scope(parent_scope, node_id)
        for node_id in graph.topological_order
        if not graph.dependencies[node_id]
    )


def downstream_scope_candidates(
    graph: CompiledGraph,
    parent_scope: str | None,
    completed_node_id: str,
) -> tuple[str, ...]:
    """Return direct dependents in O(outdegree) after a terminal event."""
    return tuple(
        node_scope(parent_scope, node_id) for node_id in graph.downstream[completed_node_id]
    )


__all__ = [
    "Eligibility",
    "downstream_scope_candidates",
    "evaluate_eligibility",
    "initial_scope_candidates",
]
