"""Linear-time compilation and validation of workflow dependency graphs."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from relay.errors import WorkflowValidationError

from .expressions import validate_expression
from .schema import ConditionNode, HumanWaitNode, LoopNode, NodeDefinition


@dataclass(frozen=True, slots=True)
class CompiledGraph:
    """Deterministic dependency indexes for one workflow or loop body."""

    nodes: Mapping[str, NodeDefinition]
    topological_order: tuple[str, ...]
    dependencies: Mapping[str, tuple[str, ...]]
    downstream: Mapping[str, tuple[str, ...]]
    loop_bodies: Mapping[str, CompiledGraph]
    activators: Mapping[str, tuple[str, ...]]
    control_downstream: Mapping[str, tuple[str, ...]]


def _expression_errors(node_id: str, node: NodeDefinition) -> list[str]:
    expressions = []
    if node.condition is not None:
        expressions.append(("if", node.condition))
    if isinstance(node, ConditionNode):
        expressions.append(("expr", node.expr))
    if isinstance(node, LoopNode) and node.until is not None:
        expressions.append(("until", node.until))
    errors = []
    for field, expression in expressions:
        try:
            validate_expression(expression)
        except WorkflowValidationError as error:
            errors.append(f"node {node_id}.{field}: {error.message}")
    return errors


def control_targets(node: NodeDefinition) -> tuple[str, ...]:
    targets = []
    if node.on_timeout is not None:
        targets.append(node.on_timeout)
    if isinstance(node, ConditionNode):
        targets.extend(node.branches.values())
    if isinstance(node, LoopNode) and node.repair_rule is None:
        targets.append(node.exhausted)
    return tuple(targets)


def compile_graph(nodes: Mapping[str, NodeDefinition], *, location: str = "root") -> CompiledGraph:
    """Validate and index a graph in O(V+E) time."""
    errors = []
    downstream_lists = {node_id: [] for node_id in nodes}
    cycle_edges = {node_id: [] for node_id in nodes}
    indegree = dict.fromkeys(nodes, 0)
    loop_bodies = {}
    incoming = {node_id: [] for node_id in nodes}
    controls = {node_id: [] for node_id in nodes}

    for node_id, node in nodes.items():
        errors.extend(_expression_errors(f"{location}.{node_id}", node))
        timeout_declared = node.timeout is not None or (
            isinstance(node, HumanWaitNode) and node.deadline is not None
        )
        if node.on_timeout is not None and not timeout_declared:
            errors.append(f"node {location}.{node_id}.on_timeout requires timeout or deadline")
        for needed in node.needs:
            if needed not in nodes:
                errors.append(f"node {location}.{node_id}.needs references unknown node {needed!r}")
                continue
            downstream_lists[needed].append(node_id)
            cycle_edges[needed].append(node_id)
        for target in control_targets(node):
            if target not in nodes:
                errors.append(
                    f"node {location}.{node_id} references unknown control target {target!r}"
                )
            else:
                cycle_edges[node_id].append(target)
                incoming[target].append(node_id)
                controls[node_id].append(target)
        if isinstance(node, LoopNode):
            try:
                loop_bodies[node_id] = compile_graph(
                    node.body, location=f"{location}.{node_id}.body"
                )
            except WorkflowValidationError as error:
                errors.append(error.message)

    # Data and control edges both order execution; a branch back upstream deadlocks.
    for children in cycle_edges.values():
        for child in children:
            indegree[child] += 1
    ready = deque(node_id for node_id in nodes if indegree[node_id] == 0)
    order = []
    while ready:
        node_id = ready.popleft()
        order.append(node_id)
        for child in cycle_edges[node_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(order) != len(nodes):
        cyclic = [node_id for node_id in nodes if indegree[node_id] > 0]
        errors.append(f"dependency cycle detected at {location}: {', '.join(cyclic)}")

    if errors:
        raise WorkflowValidationError("Workflow graph validation failed:\n- " + "\n- ".join(errors))
    return CompiledGraph(
        nodes=dict(nodes),
        topological_order=tuple(order),
        dependencies={node_id: tuple(node.needs) for node_id, node in nodes.items()},
        downstream={node_id: tuple(children) for node_id, children in downstream_lists.items()},
        loop_bodies=loop_bodies,
        activators={node_id: tuple(values) for node_id, values in incoming.items()},
        control_downstream={node_id: tuple(values) for node_id, values in controls.items()},
    )


__all__ = ["CompiledGraph", "compile_graph", "control_targets"]
