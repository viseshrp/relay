import type { Edge, Node } from "@xyflow/react";
import { arrangeGraph, capturedRunGraph } from "./graph";
import { jobDuration } from "./job";
import type { RunNode } from "./types";
import type { WorkflowNodeData } from "./workflow";

export function runSummaryGraph(records: RunNode[], now: number): { nodes: Node<WorkflowNodeData>[]; edges: Edge[] } {
  const graph = capturedRunGraph(records);
  const byScope = new Map(records.map((record) => [record.scope_path, record]));
  const groups = new Map<string, Node<WorkflowNodeData>[]>();
  for (const node of graph.nodes) {
    const incoming = graph.edges.filter((edge) => edge.target === node.id).map((edge) => edge.source).sort();
    const outgoing = graph.edges.filter((edge) => edge.source === node.id).map((edge) => edge.target).sort();
    const key = JSON.stringify([incoming, outgoing, byScope.get(node.id)?.parent_scope ?? "root"]);
    const group = groups.get(key) ?? []; group.push(node); groups.set(key, group);
  }
  const replacements = new Map<string, string>();
  const nodes: Node<WorkflowNodeData>[] = [];
  for (const group of groups.values()) {
    if (group.length > 5 && group.every((node) => byScope.has(node.id))) {
      const id = `parallel:${group[0].id}`;
      for (const node of group) replacements.set(node.id, id);
      const statuses = group.map((node) => node.data.status ?? "pending");
      const status = ["failed", "repair_stopped", "waiting", "running", "repairing", "pending", "dispatched", "ready", "canceled", "skipped"].find((value) => statuses.includes(value)) ?? "succeeded";
      nodes.push({ id, type: "runJob", position: { x: 0, y: 0 }, data: { label: `${group.length} parallel jobs`, kind: "group", status, members: group.map((node) => node.id), duration: `${statuses.filter((value) => value === "succeeded").length} completed` } });
    } else for (const node of group) {
      const record = byScope.get(node.id);
      nodes.push({ ...node, type: "runJob", className: undefined, data: { ...node.data, duration: record ? jobDuration(record.started_at, record.ended_at, now) : "" } });
    }
  }
  const edges = Array.from(new Map(graph.edges.map((edge) => {
    const source = replacements.get(edge.source) ?? edge.source;
    const target = replacements.get(edge.target) ?? edge.target;
    return [`${source}:${target}`, { ...edge, id: `${source}:${target}`, source, target, markerEnd: undefined, style: { ...edge.style, strokeWidth: 2, stroke: "#9da8bc" } }];
  })).values());
  return { nodes: arrangeGraph(nodes, edges).map((node) => ({ ...node, position: { x: node.position.y / 145 * 370, y: node.position.x / 290 * 100 } })), edges };
}
