"""Event-driven node eligibility over precompiled dependency indexes."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from relay.errors import WorkflowValidationError
from relay.execution.dispatch import DispatchStore, dispatch_node
from relay.workflows.expressions import evaluate_expression
from relay.workflows.graph import CompiledGraph, compile_graph
from relay.workflows.schema import ConditionNode, LoopNode, NodeDefinition
from relay.workflows.scope import node_scope, parse_scope_path

from .state import NodeStatus


@dataclass(frozen=True, slots=True)
class Eligibility:
    """One pending node's deterministic next transition."""

    action: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class ScheduledNode:
    """Current durable state for one top-level node."""

    node_run_id: str
    node_id: str
    definition: NodeDefinition
    status: str
    outputs: Mapping[str, object]
    selected_branch: str | None


@dataclass(frozen=True, slots=True)
class RunSchedule:
    """Immutable inputs and current node rows needed for one scheduling pass."""

    run_id: str
    nodes: Mapping[str, ScheduledNode]
    inputs: Mapping[str, object]
    run_metadata: Mapping[str, object]
    entry_point: str | None


class SchedulingStore(DispatchStore, Protocol):
    """Persistence operations used by event-driven top-level scheduling."""

    def load_run_schedule(self, run_id: str) -> RunSchedule: ...

    def transition_scope_node(self, node_run_id: str, action: str) -> None: ...

    def settle_run(self, run_id: str) -> None: ...


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


def _control_targets(node: NodeDefinition) -> tuple[str, ...]:
    targets = [node.on_timeout] if node.on_timeout is not None else []
    if isinstance(node, ConditionNode):
        targets.extend(node.branches.values())
    if isinstance(node, LoopNode):
        targets.append(node.exhausted)
    return tuple(targets)


def activation_sources(
    nodes: Mapping[str, NodeDefinition],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Index condition, loop-exhaustion, and timeout control edges in O(V+E)."""
    incoming_lists: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    outgoing_lists: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for source_id, node in nodes.items():
        for target in _control_targets(node):
            incoming_lists[target].append(source_id)
            outgoing_lists[source_id].append(target)
    return (
        {node_id: tuple(values) for node_id, values in incoming_lists.items()},
        {node_id: tuple(values) for node_id, values in outgoing_lists.items()},
    )


def entry_node_for_scope(entry_point: str | None, parent_scope: str | None) -> str | None:
    """Return the direct child selected by a declared entry point in this scope."""
    if entry_point is None:
        return None
    normalized = entry_point if entry_point.startswith("root.") else f"root.{entry_point}"
    segments = parse_scope_path(normalized)
    if parent_scope is None:
        return segments[0].node_id
    prefix = f"{parent_scope}."
    if not normalized.startswith(prefix):
        return None
    direct = normalized[len(prefix) :].split(".", maxsplit=1)[0]
    return direct.partition("#")[0]


def reachable_node_ids(
    start: str,
    graph: CompiledGraph,
    control_downstream: Mapping[str, tuple[str, ...]],
) -> frozenset[str]:
    reachable: set[str] = set()
    queue = deque((start,))
    while queue:
        node_id = queue.popleft()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        queue.extend(graph.downstream[node_id])
        queue.extend(control_downstream[node_id])
    return frozenset(reachable)


def advance_run_schedule(store: SchedulingStore, run_id: str) -> tuple[str, ...]:
    """Derive top-level readiness until stable, then return ready row ids."""
    while True:
        schedule = store.load_run_schedule(run_id)
        definitions = {node_id: row.definition for node_id, row in schedule.nodes.items()}
        graph = compile_graph(definitions)
        incoming, control_downstream = activation_sources(definitions)
        entry_root = entry_node_for_scope(schedule.entry_point, None)
        reachable = (
            reachable_node_ids(entry_root, graph, control_downstream)
            if entry_root is not None
            else frozenset(definitions)
        )
        changed = False
        for node_id in graph.topological_order:
            row = schedule.nodes[node_id]
            if row.status != NodeStatus.PENDING.value:
                continue
            if node_id not in reachable:
                store.transition_scope_node(row.node_run_id, "dependencies_unreachable")
                changed = True
                break
            if node_id == entry_root:
                # Declared entry-point inputs and artifacts were proven before this run row existed.
                store.transition_scope_node(row.node_run_id, "dependencies_satisfied")
                changed = True
                break
            activators = incoming[node_id]
            if activators:
                source_rows = [schedule.nodes[source] for source in activators]
                selected = any(item.selected_branch == node_id for item in source_rows)
                complete = all(
                    item.status
                    in {
                        NodeStatus.SUCCEEDED.value,
                        NodeStatus.SKIPPED.value,
                        NodeStatus.FAILED.value,
                        NodeStatus.CANCELED.value,
                    }
                    for item in source_rows
                )
                if complete and not selected:
                    store.transition_scope_node(row.node_run_id, "dependencies_unreachable")
                    changed = True
                    break
                if not selected:
                    continue
            dependencies = {
                needed: schedule.nodes[needed] for needed in graph.dependencies[node_id]
            }
            eligibility = evaluate_eligibility(
                row.definition,
                {needed: item.status for needed, item in dependencies.items()},
                {
                    "inputs": dict(schedule.inputs),
                    "needs": {
                        needed: {"outputs": dict(item.outputs)}
                        for needed, item in dependencies.items()
                    },
                    "run": dict(schedule.run_metadata),
                    "loop": {},
                },
            )
            if eligibility.action is not None:
                store.transition_scope_node(row.node_run_id, eligibility.action)
                changed = True
                break
        if not changed:
            ready = tuple(
                row.node_run_id
                for node_id in graph.topological_order
                if (row := schedule.nodes[node_id]).status == NodeStatus.READY.value
            )
            store.settle_run(run_id)
            return ready


def dispatch_ready_nodes(
    store: SchedulingStore,
    run_id: str,
    enqueue: Callable[[str], object],
) -> tuple[str, ...]:
    """Commit and enqueue each newly ready node without waiting for execution."""
    return tuple(
        dispatch_node(store, node_run_id, enqueue)
        for node_run_id in advance_run_schedule(store, run_id)
    )


__all__ = [
    "Eligibility",
    "RunSchedule",
    "ScheduledNode",
    "SchedulingStore",
    "activation_sources",
    "advance_run_schedule",
    "dispatch_ready_nodes",
    "downstream_scope_candidates",
    "entry_node_for_scope",
    "evaluate_eligibility",
    "initial_scope_candidates",
    "reachable_node_ids",
]
