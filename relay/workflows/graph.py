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


def _expression_errors(node_id: str, node: NodeDefinition) -> list[str]:
    expressions: list[tuple[str, str]] = []
    if node.condition is not None:
        expressions.append(("if", node.condition))
    if isinstance(node, ConditionNode):
        expressions.append(("expr", node.expr))
    if isinstance(node, LoopNode) and node.until is not None:
        expressions.append(("until", node.until))
    errors: list[str] = []
    for field, expression in expressions:
        try:
            validate_expression(expression)
        except WorkflowValidationError as error:
            errors.append(f"node {node_id}.{field}: {error.message}")
    return errors


def _control_targets(node: NodeDefinition) -> tuple[str, ...]:
    targets: list[str] = []
    if node.on_timeout is not None:
        targets.append(node.on_timeout)
    if isinstance(node, ConditionNode):
        targets.extend(node.branches.values())
    if isinstance(node, LoopNode):
        targets.append(node.exhausted)
    return tuple(targets)


def compile_graph(nodes: Mapping[str, NodeDefinition], *, location: str = "root") -> CompiledGraph:
    """Validate and index a graph in O(V+E) time."""
    errors: list[str] = []
    downstream_lists: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree: dict[str, int] = dict.fromkeys(nodes, 0)
    loop_bodies: dict[str, CompiledGraph] = {}

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
            indegree[node_id] += 1
        for target in _control_targets(node):
            if target not in nodes:
                errors.append(
                    f"node {location}.{node_id} references unknown control target {target!r}"
                )
        if isinstance(node, ConditionNode) and len(node.branches) != len(set(node.branches)):
            errors.append(f"node {location}.{node_id} has duplicate branch labels")
        if isinstance(node, LoopNode):
            try:
                loop_bodies[node_id] = compile_graph(
                    node.body, location=f"{location}.{node_id}.body"
                )
            except WorkflowValidationError as error:
                errors.append(error.message)

    ready = deque(node_id for node_id in nodes if indegree[node_id] == 0)
    order: list[str] = []
    while ready:
        node_id = ready.popleft()
        order.append(node_id)
        for child in downstream_lists[node_id]:
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
    )


__all__ = ["CompiledGraph", "compile_graph"]
