export interface InputDefinition {
  type: "string" | "integer" | "number" | "boolean" | "enum";
  description?: string;
  required?: boolean;
  default?: unknown;
  constraints?: Record<string, unknown>;
}

export interface LaunchWorkflow {
  name: string;
  jobs: string[];
  inputs?: Record<string, InputDefinition>;
  entrypoints?: Array<{ scope_path: string }>;
}

export interface WorkflowNodeData extends Record<string, unknown> {
  label: string;
  kind: string;
  status?: string;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
