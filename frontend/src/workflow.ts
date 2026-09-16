import type { Edge, Node } from "@xyflow/react";
import { type Document, parseDocument } from "yaml";

export interface WorkflowNodeValue {
  type: string;
  needs?: string[];
  writes?: boolean;
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
  inputs?: Record<string, InputDefinition>;
  nodes: Record<string, WorkflowNodeValue>;
  entrypoints?: Array<{ scope_path: string }>;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseWorkflow(text: string): ParsedWorkflow {
  const document = parseDocument(text, { keepSourceTokens: true, prettyErrors: true });
  const errors = document.errors.map((error) => error.message);
  if (errors.length > 0) return { document, value: null, errors };
  const value: unknown = document.toJS({ maxAliasCount: 100 });
  if (!isRecord(value) || !isRecord(value.nodes)) {
    return { document, value: null, errors: ["The workflow must contain a nodes mapping."] };
  }
  return { document, value: value as unknown as WorkflowValue, errors: [] };
}

export function canonicalYaml(text: string): string {
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
      label: id,
      kind: definition.type,
      status: statuses.get(`root.${id}`),
    },
    className: statuses.get(`root.${id}`) ? `node-status-${statuses.get(`root.${id}`)}` : "",
  }));
  const nodeIds = new Set(entries.map(([id]) => id));
  const edges = entries.flatMap(([target, definition]) =>
    (definition.needs ?? [])
      .filter((source) => nodeIds.has(source))
      .map((source) => ({ id: `${source}-${target}`, source, target, animated: true })),
  );
  return { nodes, edges };
}

export function nextNodeId(value: WorkflowValue | null): string {
  const ids = new Set(Object.keys(value?.nodes ?? {}));
  if (!ids.has("node")) return "node";
  let index = 2;
  while (ids.has(`node_${index}`)) index += 1;
  return `node_${index}`;
}

export function nodeDefaults(type: string): WorkflowNodeValue {
  switch (type) {
    case "agent":
      return { type, writes: false, prompts: [] };
    case "human_wait":
      return { type, prompt: "Continue?" };
    case "condition":
      return { type, expr: "true", branches: { true: "" } };
    case "loop":
      return { type, body: {}, max_iterations: 1, exhausted: "" };
    case "subworkflow":
      return { type, workflow: "workflow" };
    default:
      return { type: "command", writes: false, run: ["git", "status", "--short"] };
  }
}
