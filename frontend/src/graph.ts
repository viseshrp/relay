import { MarkerType, type Edge, type Node } from "@xyflow/react";
import { stageLabel, statusLabel } from "./navigation";
import type { RunNode } from "./types";
import type { WorkflowNodeData } from "./workflow";

export function arrangeGraph(nodes: Node<WorkflowNodeData>[], edges: Edge[]) {
  // Each stage follows its longest dependency path. Independent branches occupy separate columns.
  // A -> B -> C becomes rows 0, 1, 2; A -> D puts B and D next to each other in row 1.
  const outgoing = new Map<string, string[]>(nodes.map((node) => [node.id, []]));
  const incoming = new Map(nodes.map((node) => [node.id, 0]));
  const ranks = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    if (!outgoing.has(edge.source) || !incoming.has(edge.target)) continue;
    outgoing.get(edge.source)?.push(edge.target);
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1);
  }
  const ready = nodes.filter((node) => incoming.get(node.id) === 0).map((node) => node.id);
  for (let index = 0; index < ready.length; index += 1) {
    const source = ready[index];
    for (const target of outgoing.get(source) ?? []) {
      ranks.set(target, Math.max(ranks.get(target) ?? 0, (ranks.get(source) ?? 0) + 1));
      incoming.set(target, (incoming.get(target) ?? 0) - 1);
      if (incoming.get(target) === 0) ready.push(target);
    }
  }
  const columns = new Map<number, number>();
  return nodes.map((node) => {
    const row = ranks.get(node.id) ?? 0;
    const column = columns.get(row) ?? 0;
    columns.set(row, column + 1);
    return { ...node, position: { x: column * 290, y: row * 145 } };
  });
}

export function capturedRunGraph(records: RunNode[]): { nodes: Node<WorkflowNodeData>[]; edges: Edge[] } {
  const known = new Set(records.map((node) => node.scope_path));
  const connections = new Map<string, Edge>();
  const completionNodes: Node<WorkflowNodeData>[] = [];
  function connect(source: string, target: string, label?: string) {
    if (!known.has(source) || !known.has(target)) return;
    const id = `${source}:${target}`;
    const existing = connections.get(id);
    connections.set(id, {
      id, source, target, type: "smoothstep",
      ...(label || existing?.label ? { label: label ?? existing?.label, style: { strokeDasharray: "5 4" } } : {}),
      markerEnd: { type: MarkerType.ArrowClosed },
    });
  }
  const children = new Map<string, RunNode[]>();
  const successors = new Map<string, string[]>();
  const controlTargets = new Set<string>();
  for (const node of records) {
    for (const source of node.dependencies ?? []) {
      connect(source, node.scope_path);
      const next = successors.get(source) ?? [];
      next.push(node.scope_path);
      successors.set(source, next);
    }
    for (const control of node.controls ?? []) {
      connect(node.scope_path, control.target, control.label);
      controlTargets.add(control.target);
    }
    if (node.parent_scope) {
      const group = children.get(node.parent_scope) ?? [];
      group.push(node);
      children.set(node.parent_scope, group);
    }
  }
  const scopes = new Map<string, Array<[string, RunNode[]]>>();
  const scopeEnds = new Map<string, string>();
  const leafEnds: Array<[string, string]> = [];
  for (const [scope, group] of children) {
    // root.repeat#2 maps to root.repeat, ordered after root.repeat#1.
    const coordinator = scope.replace(/#\d+$/, "");
    const iterations = scopes.get(coordinator) ?? [];
    iterations.push([scope, group]);
    scopes.set(coordinator, iterations);
  }
  for (const [coordinator, iterations] of scopes) {
    iterations.sort(([left], [right]) => Number(left.match(/#(\d+)$/)?.[1] ?? 0) - Number(right.match(/#(\d+)$/)?.[1] ?? 0));
    let previous = coordinator;
    for (const [scope, group] of iterations) {
      const completion = `${scope}::complete`;
      known.add(completion);
      completionNodes.push({ id: completion, position: { x: 0, y: 0 }, data: { label: `${stageLabel(scope)}\nChild steps finish`, kind: "subworkflow" } });
      const sources = new Set(group.flatMap((node) => [...(node.dependencies ?? []), ...(node.controls ?? []).map((control) => node.scope_path)]));
      for (const node of group) {
        if ((node.dependencies ?? []).length === 0 && !controlTargets.has(node.scope_path)) connect(previous, node.scope_path, "Child steps");
        if (!sources.has(node.scope_path)) leafEnds.push([node.scope_path, completion]);
      }
      previous = completion;
    }
    scopeEnds.set(coordinator, previous);
    // One junction avoids connecting every leaf to every successor (quadratic fan-out).
    for (const successor of successors.get(coordinator) ?? []) connect(previous, successor, "Child complete");
  }
  for (const [source, target] of leafEnds) connect(scopeEnds.get(source) ?? source, target);
  const edges = Array.from(connections.values());
  const nodes: Node<WorkflowNodeData>[] = records.map((node) => ({
    id: node.scope_path, position: { x: 0, y: 0 },
    data: { label: `${stageLabel(node.scope_path)}\n${statusLabel(node.status)}`, kind: node.node_type, status: node.status },
    className: `node-status-${node.status}`,
  }));
  return { nodes: arrangeGraph([...nodes, ...completionNodes], edges), edges };
}
