import { stageLabel } from "./navigation";
import type { RunNode } from "./types";

export interface JobListRow {
  node: RunNode;
  depth: number;
  context: string;
  attention: boolean;
}

export function jobListRows(nodes: RunNode[]): JobListRow[] {
  const records = new Map(
    runJobs(nodes).map((node) => [node.scope_path, node]),
  );
  const children = new Map<string | null, RunNode[]>();
  for (const node of records.values()) {
    const candidate = node.parent_scope;
    const parent = candidate && records.has(candidate) ? candidate : null;
    const siblings = children.get(parent) ?? [];
    siblings.push(node);
    children.set(parent, siblings);
  }
  const rows: JobListRow[] = [];
  const seen = new Set<string>();
  function visit(node: RunNode, depth: number, ancestors: string[]): void {
    if (seen.has(node.scope_path)) return;
    seen.add(node.scope_path);
    const context = ancestors.join(" › ");
    rows.push({
      node,
      depth,
      context,
      attention: ["failed", "waiting"].includes(node.status),
    });
    for (const child of children.get(node.scope_path) ?? [])
      visit(child, depth + 1, [...ancestors, stageLabel(node.scope_path)]);
  }
  for (const node of children.get(null) ?? []) {
    const parent = node.parent_scope;
    visit(
      node,
      parent && parent !== "root" ? parent.split(".").length - 1 : 0,
      parent && parent !== "root" ? [stageLabel(parent)] : [],
    );
  }
  // A partial page must retain every loaded job even if its parent is absent
  // or stored metadata contains a cycle.
  for (const node of records.values())
    if (!seen.has(node.scope_path)) visit(node, 0, []);
  return [
    ...rows.filter((row) => row.attention),
    ...rows.filter((row) => !row.attention),
  ];
}

export function runJobs(nodes: RunNode[]): RunNode[] {
  // Ordered steps belong inside their captured job, including composite steps.
  // A partial page can temporarily lack its coordinator: keep steps out of the
  // summary regardless, while their deep links remain usable.
  return nodes.filter((node) => node.node_type === "actions_job");
}
