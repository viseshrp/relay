"""Event-driven node eligibility over precompiled dependency indexes."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from relay.errors import WorkflowValidationError
from relay.execution.dispatch import DispatchStore, dispatch_node
from relay.workflows.expressions import evaluate_expression
from relay.workflows.graph import CompiledGraph
from relay.workflows.repairs import effective_dependency_outputs
from relay.workflows.schema import NodeDefinition
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


@dataclass(frozen=True, slots=True)
class SchedulingChange:
    """A committed event affecting one run's eligibility."""

    run_id: str
    node_id: str | None


class SchedulingStore(DispatchStore, Protocol):
    """Persistence operations used by event-driven top-level scheduling."""

    def run_graph(self, run_id: str) -> CompiledGraph: ...

    def reachable_run_nodes(self, run_id: str, entry_root: str | None) -> frozenset[str]: ...

    def load_run_schedule(
        self, run_id: str, node_ids: tuple[str, ...] | None = None
    ) -> RunSchedule: ...

    def transition_scope_node(
        self, node_run_id: str, action: str, *, expected_status: str | None = None
    ) -> str: ...

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


def activation_sources(
    graph: CompiledGraph,
) -> tuple[Mapping[str, tuple[str, ...]], Mapping[str, tuple[str, ...]]]:
    """Reuse the control indexes compiled with the dependency graph."""
    return graph.activators, graph.control_downstream


def entry_node_for_scope(entry_point: str | None, parent_scope: str | None) -> str | None:
    """``root.loop#2.check`` -> ``loop`` at root, or ``check`` under ``root.loop#2``."""
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
    reachable = set()
    queue = deque((start,))
    while queue:
        node_id = queue.popleft()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        queue.extend(graph.downstream[node_id])
        queue.extend(control_downstream[node_id])
    return frozenset(reachable)


def advance_run_schedule(
    store: SchedulingStore, run_id: str, changed_node_ids: tuple[str, ...] | None = None
) -> tuple[str, ...]:
    """Initialize once, then evaluate only changed nodes and direct successors."""
    graph = store.run_graph(run_id)
    incoming, control_downstream = activation_sources(graph)
    seeds = None
    if changed_node_ids is not None:
        seeds = tuple(
            dict.fromkeys(
                candidate
                for node_id in changed_node_ids
                if node_id in graph.nodes
                for candidate in (
                    node_id,
                    *(
                        path.removeprefix("root.")
                        for path in downstream_scope_candidates(graph, None, node_id)
                    ),
                    *control_downstream[node_id],
                )
            )
        )
    schedule = store.load_run_schedule(run_id, seeds)
    if (
        schedule.run_metadata.get("status") not in {"running", "paused_wait"}
        or schedule.run_metadata.get("dispatch_paused") is True
    ):
        return ()
    rows = dict(schedule.nodes)
    entry_root = entry_node_for_scope(schedule.entry_point, None)
    reachable = store.reachable_run_nodes(run_id, entry_root)
    statuses = {node_id: row.status for node_id, row in schedule.nodes.items()}
    terminal = {
        NodeStatus.SUCCEEDED.value,
        NodeStatus.SKIPPED.value,
        NodeStatus.FAILED.value,
        NodeStatus.CANCELED.value,
    }
    if seeds is None:
        seeds = tuple(
            dict.fromkeys(
                (
                    *(path.removeprefix("root.") for path in initial_scope_candidates(graph, None)),
                    *(
                        node_id
                        for node_id, row in rows.items()
                        if row.status == NodeStatus.READY.value or node_id not in reachable
                    ),
                )
            )
        )
    queue = deque(seeds)
    queued = set(seeds)
    ready_ids = []
    propagated = set()

    def enqueue_candidates(node_id: str) -> None:
        # Every terminal node can wake only its direct data and control successors.
        for candidate in (*graph.downstream[node_id], *control_downstream[node_id]):
            if candidate not in queued and candidate not in propagated:
                queue.append(candidate)
                queued.add(candidate)

    while queue:
        node_id = queue.popleft()
        queued.remove(node_id)
        required = (*graph.dependencies[node_id], *incoming[node_id], node_id)
        if any(name not in rows for name in required):
            extra = store.load_run_schedule(run_id, (node_id,))
            rows.update(extra.nodes)
            statuses.update({name: item.status for name, item in extra.nodes.items()})
        row = rows[node_id]
        if statuses[node_id] == NodeStatus.READY.value:
            ready_ids.append(row.node_run_id)
            continue
        if statuses[node_id] != NodeStatus.PENDING.value:
            if statuses[node_id] in terminal and node_id not in propagated:
                propagated.add(node_id)
                enqueue_candidates(node_id)
            continue
        action = None
        if node_id not in reachable:
            action = "dependencies_unreachable"
        elif node_id == entry_root:
            # Declared entry-point inputs and artifacts were proven before this run row existed.
            action = "dependencies_satisfied"
        else:
            activators = incoming[node_id]
            if activators:
                selected = any(rows[source].selected_branch == node_id for source in activators)
                complete = all(statuses[source] in terminal for source in activators)
                if complete and not selected:
                    action = "dependencies_unreachable"
                elif not selected:
                    continue
            if action is None:
                dependencies = {needed: rows[needed] for needed in graph.dependencies[node_id]}
                eligibility = evaluate_eligibility(
                    row.definition,
                    {needed: statuses[needed] for needed in dependencies},
                    {
                        "inputs": dict(schedule.inputs),
                        "needs": {
                            needed: {"outputs": dict(outputs)}
                            for needed, outputs in effective_dependency_outputs(
                                graph.nodes,
                                {needed: item.outputs for needed, item in dependencies.items()},
                            ).items()
                        },
                        "run": dict(schedule.run_metadata),
                        "loop": {},
                    },
                )
                action = eligibility.action
        if action is None:
            continue
        status = store.transition_scope_node(
            row.node_run_id, action, expected_status=NodeStatus.PENDING.value
        )
        statuses[node_id] = status
        if status == NodeStatus.SUCCEEDED.value:
            # A concurrent worker may have completed this stale pending row.
            # Load its committed outputs before evaluating its successors.
            rows.update(store.load_run_schedule(run_id, (node_id,)).nodes)
        if status == NodeStatus.READY.value:
            ready_ids.append(row.node_run_id)
        if status in terminal:
            enqueue_candidates(node_id)

    store.settle_run(run_id)
    return tuple(dict.fromkeys(ready_ids))


def dispatch_ready_nodes(
    store: SchedulingStore,
    run_id: str,
    enqueue: Callable[[str], object],
    changed_node_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Commit and enqueue each newly ready node without waiting for execution."""
    return tuple(
        token
        for node_run_id in advance_run_schedule(store, run_id, changed_node_ids)
        if (token := dispatch_node(store, node_run_id, enqueue)) is not None
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
