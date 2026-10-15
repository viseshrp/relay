"""Linear-time dependency indexes for compiled jobs and steps."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from relay.errors import WorkflowValidationError

from .schema import NodeDefinition


@dataclass(frozen=True, slots=True)
class CompiledGraph:
    """Deterministic dependency indexes for one finite execution graph."""

    nodes: Mapping[str, NodeDefinition]
    topological_order: tuple[str, ...]
    dependencies: Mapping[str, tuple[str, ...]]
    downstream: Mapping[str, tuple[str, ...]]


def compile_graph(nodes: Mapping[str, NodeDefinition], *, location: str = "root") -> CompiledGraph:
    """Validate dependencies and index a graph in O(V+E) time."""
    downstream = {node_id: [] for node_id in nodes}
    indegree = dict.fromkeys(nodes, 0)
    errors = []
    for node_id, node in nodes.items():
        for needed in node.needs:
            if needed not in nodes:
                errors.append(f"job {location}.{node_id}.needs references unknown job {needed!r}")
                continue
            downstream[needed].append(node_id)
            indegree[node_id] += 1
    ready = deque(node_id for node_id in nodes if indegree[node_id] == 0)
    order = []
    while ready:
        node_id = ready.popleft()
        order.append(node_id)
        for child in downstream[node_id]:
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
        downstream={node_id: tuple(children) for node_id, children in downstream.items()},
    )


__all__ = ["CompiledGraph", "compile_graph"]
