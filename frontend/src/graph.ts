import { MarkerType, type Edge, type Node } from "@xyflow/react";
import { stageLabel, statusLabel } from "./navigation";
import type { RunNode } from "./types";
import type { WorkflowNodeData } from "./workflow";

export function arrangeGraph(
  nodes: Node<WorkflowNodeData>[],
  edges: Edge[],
  height: (node: Node<WorkflowNodeData>) => number = () => 104,
) {
  // Each stage follows its longest dependency path. Independent branches occupy separate columns.
  // A -> B -> C becomes rows 0, 1, 2; A -> D puts B and D next to each other in row 1.
  const outgoing = new Map<string, string[]>(
    nodes.map((node) => [node.id, []]),
  );
  const incoming = new Map(nodes.map((node) => [node.id, 0]));
  const ranks = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    if (!outgoing.has(edge.source) || !incoming.has(edge.target)) continue;
    outgoing.get(edge.source)?.push(edge.target);
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1);
  }
  const ready = nodes
    .filter((node) => incoming.get(node.id) === 0)
    .map((node) => node.id);
  for (let index = 0; index < ready.length; index += 1) {
    const source = ready[index];
    for (const target of outgoing.get(source) ?? []) {
      ranks.set(
        target,
        Math.max(ranks.get(target) ?? 0, (ranks.get(source) ?? 0) + 1),
      );
      incoming.set(target, (incoming.get(target) ?? 0) - 1);
      if (incoming.get(target) === 0) ready.push(target);
    }
  }
  // Each row starts below the tallest card of the row above it.
  const tallest = new Map<number, number>();
  for (const node of nodes) {
    const row = ranks.get(node.id) ?? 0;
    tallest.set(row, Math.max(tallest.get(row) ?? 0, height(node)));
  }
  const tops = new Map<number, number>();
  for (let row = 0, top = 0; row <= Math.max(0, ...tallest.keys()); row++) {
    tops.set(row, top);
    top += (tallest.get(row) ?? 104) + 41;
  }
  const columns = new Map<number, number>();
  return nodes.map((node) => {
    const row = ranks.get(node.id) ?? 0;
    const column = columns.get(row) ?? 0;
    columns.set(row, column + 1);
    return { ...node, position: { x: column * 290, y: tops.get(row) ?? 0 } };
  });
}

export function capturedRunGraph(records: RunNode[]): {
  nodes: Node<WorkflowNodeData>[];
  edges: Edge[];
} {
  const known = new Set(records.map((node) => node.scope_path));
  const edges: Edge[] = records.flatMap((node) =>
    node.dependencies
      .filter((source) => known.has(source))
      .map((source) => ({
        id: `${source}:${node.scope_path}`,
        source,
        target: node.scope_path,
        markerEnd: { type: MarkerType.ArrowClosed },
      })),
  );
  const nodes: Node<WorkflowNodeData>[] = records.map((node) => ({
    id: node.scope_path,
    position: { x: 0, y: 0 },
    data: {
      label: `${stageLabel(node.scope_path)}\n${statusLabel(node.status)}`,
      kind: node.node_type,
      status: node.status,
    },
    className: `node-status-${node.status}`,
  }));
  return { nodes: arrangeGraph(nodes, edges), edges };
}
