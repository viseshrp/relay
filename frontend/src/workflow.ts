import type { Edge, Node } from "@xyflow/react";
import { type Document, parseDocument } from "yaml";

import type { AgentOptions } from "./types";
import { arrangeGraph } from "./graph";
import { stageLabel } from "./navigation";

export interface WorkflowNodeValue {
  type: string;
  run?: string[] | { command: string };
  env?: Record<string, string>;
  inherit_env?: boolean;
  needs?: string[];
  writes?: boolean;
  agents?: string[];
  agent_options?: Record<string, AgentOptions>;
  auto_retry?: boolean;
  prompts?: Array<{ local?: string; global?: string }>;
  outputs?: Record<string, unknown>;
  branches?: Record<string, string>;
  body?: Record<string, WorkflowNodeValue>;
  max_iterations?: number;
  until?: string | null;
  exhausted?: string;
  workflow?: string;
  [key: string]: unknown;
}

export interface InputDefinition {
  type: "string" | "integer" | "number" | "boolean" | "enum";
  description?: string;
  required?: boolean;
  default?: unknown;
  constraints?: Record<string, unknown>;
}

export interface WorkflowValue {
  version: number;
  name: string;
  model?: string;
  agents?: string[];
  env?: Record<string, string>;
  inherit_env?: boolean;
  inputs?: Record<string, InputDefinition>;
  nodes: Record<string, WorkflowNodeValue>;
  entrypoints?: Array<{ scope_path: string }>;
  recovery?: { enabled: boolean; max_retries?: number };
  repairs?: Record<string, RepairRuleValue>;
}

export interface RepairRuleValue {
  enabled?: boolean;
  max_rounds?: number;
  accepted_output: string;
  accepted_value?: string | number | boolean | null;
  fix: WorkflowNodeValue;
  verify: WorkflowNodeValue;
  fix_instruction?: string;
  verify_instruction?: string;
}

export interface WorkflowNodeData extends Record<string, unknown> {
  label: string;
  kind: string;
  status?: string;
}

export interface ParsedWorkflow {
  document: Document.Parsed;
  value: WorkflowValue | null;
  errors: string[];
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseWorkflow(text: string): ParsedWorkflow {
  const document = parseDocument(text, { keepSourceTokens: true, prettyErrors: true });
  const errors = document.errors.map((error) => error.message);
  if (errors.length > 0) return { document, value: null, errors };
  let value: unknown;
  try { value = document.toJS({ maxAliasCount: 100 }); }
  catch (error) { return { document, value: null, errors: [String(error)] }; }
  if (isRecord(value) && isRecord(value.jobs)) {
    const jobs = Object.fromEntries(Object.entries(value.jobs).map(([name, job]) => [name, isRecord(job) ? { ...job, type: "actions_job", needs: typeof job.needs === "string" ? [job.needs] : job.needs } : { type: "actions_job" }]));
    return { document, value: { ...value, name: String(value.name || "Workflow"), nodes: jobs } as unknown as WorkflowValue, errors: [] };
  }
  if (!isRecord(value) || !isRecord(value.nodes)) {
    return { document, value: null, errors: ["The workflow must contain a nodes mapping."] };
  }
  return { document, value: value as unknown as WorkflowValue, errors: [] };
}

export function canonicalYaml(text: string): string {
  // "version: 1\nname: A\nnodes: {}" -> the same YAML with a final newline.
  const parsed = parseWorkflow(text);
  if (parsed.errors.length > 0) throw new Error(parsed.errors.join("\n"));
  return parsed.document.toString({ lineWidth: 100 });
}

export function mutateWorkflow(
  text: string,
  mutate: (document: Document.Parsed, value: WorkflowValue) => void,
): string {
  const parsed = parseWorkflow(text);
  if (parsed.value === null) throw new Error(parsed.errors.join("\n"));
  mutate(parsed.document, parsed.value);
  return parsed.document.toString({ lineWidth: 100 });
}

export function flowElements(
  value: WorkflowValue | null,
  statuses: ReadonlyMap<string, string> = new Map(),
): { nodes: Node<WorkflowNodeData>[]; edges: Edge[] } {
  if (value === null) return { nodes: [], edges: [] };
  const entries = Object.entries(value.nodes);
  const nodes = entries.map(([id, definition], index) => ({
    id,
    position: { x: (index % 3) * 250, y: Math.floor(index / 3) * 150 },
    data: {
      label: stageLabel(id),
      kind: definition.type,
      status: statuses.get(`root.${id}`),
    },
    className: statuses.get(`root.${id}`) ? `node-status-${statuses.get(`root.${id}`)}` : "",
  }));
  const nodeIds = new Set(entries.map(([id]) => id));
  const edges: Edge[] = entries.flatMap(([target, definition]) =>
    (definition.needs ?? [])
      .filter((source) => nodeIds.has(source))
      .map((source) => ({ id: `${source}-${target}`, source, target, animated: true })),
  );
  for (const [source, definition] of entries) {
    const branches = isRecord(definition.branches) ? definition.branches : {};
    for (const [label, target] of Object.entries(branches)) {
      if (typeof target === "string" && nodeIds.has(target)) edges.push({ id: `branch:${source}:${target}`, source, target, label, type: "smoothstep", animated: false });
    }
    for (const field of ["on_timeout", "exhausted"]) {
      const target = definition[field];
      if (typeof target === "string" && nodeIds.has(target)) edges.push({ id: `${field}:${source}:${target}`, source, target, label: field === "on_timeout" ? "Time limit" : "Iteration limit", type: "smoothstep", animated: false });
    }
  }
  return { nodes: arrangeGraph(nodes, edges), edges };
}

export function nextNodeId(value: WorkflowValue | null, prefix = "node"): string {
  // Existing IDs "node", "node_2" -> "node_3"; an empty map -> "node".
  const ids = new Set(Object.keys(value?.nodes ?? {}));
  if (!ids.has(prefix)) return prefix;
  let index = 2;
  while (ids.has(`${prefix}_${index}`)) index += 1;
  return `${prefix}_${index}`;
}

export function nodeDefaults(type: string): WorkflowNodeValue {
  switch (type) {
    case "agent":
      return { type, writes: false, prompts: [] };
    case "human_wait":
      return { type, prompt: "Continue?" };
    case "condition":
      return { type, expr: "${{ \"true\" }}", branches: { true: "" } };
    case "loop":
      return { type, body: {}, max_iterations: 1, exhausted: "" };
    case "subworkflow":
      return { type, workflow: "workflow" };
    default:
      return { type: "command", writes: false, run: ["git", "status", "--short"] };
  }
}
