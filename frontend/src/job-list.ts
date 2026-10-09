import { stageLabel } from "./navigation";
import type { RunNode } from "./types";

export interface JobListRow {
  node: RunNode;
  depth: number;
  context: string;
  attention: boolean;
}

export function jobListRows(nodes: RunNode[], repairOwners: Map<string, string>): JobListRow[] {
  const records = new Map(nodes.map((node) => [node.scope_path, node]));
  const children = new Map<string | null, RunNode[]>();
  for (const node of records.values()) {
    // Iteration markers are recorded after their children, so storage order
    // cannot establish the hierarchy. Missing markers can be on a later page.
    const iteration = node.node_type === "loop" && /#\d+$/.test(node.scope_path);
    const candidate = iteration ? node.scope_path.replace(/#\d+$/, "") : node.parent_scope;
    const coordinator = candidate?.replace(/#\d+$/, "");
    const parent = candidate && records.has(candidate) ? candidate
      : coordinator && records.has(coordinator) ? coordinator : null;
    const siblings = children.get(parent) ?? [];
    siblings.push(node);
    children.set(parent, siblings);
  }
  const rows: JobListRow[] = [];
  const seen = new Set<string>();
  function visit(node: RunNode, depth: number, ancestors: string[]): void {
    if (seen.has(node.scope_path)) return;
    seen.add(node.scope_path);
    const owner = repairOwners.get(node.scope_path);
    const context = [owner ? `Repair for ${stageLabel(owner)}` : "", ...ancestors].filter(Boolean).join(" › ");
    rows.push({ node, depth, context, attention: ["failed", "waiting", "repair_stopped"].includes(node.status) });
    for (const child of children.get(node.scope_path) ?? []) visit(child, depth + 1, [...ancestors, stageLabel(node.scope_path)]);
  }
  for (const node of children.get(null) ?? []) {
    const parent = node.parent_scope;
    visit(node, parent && parent !== "root" ? parent.split(".").length - 1 : 0,
      parent && parent !== "root" ? [stageLabel(parent)] : []);
  }
  // A partial page must retain every loaded job even if its parent is absent
  // or damaged historical metadata contains a cycle.
  for (const node of records.values()) if (!seen.has(node.scope_path)) visit(node, 0, []);
  return [...rows.filter((row) => row.attention), ...rows.filter((row) => !row.attention)];
}
