import type { ActionWorkflow } from "./actions-workflow";
import { isRecord } from "./workflow";

export interface LanguageDefinition {
  description?: string; string?: { constant?: string }; boolean?: unknown; number?: unknown;
  "one-of"?: string[]; sequence?: { "item-type": string };
  mapping?: { properties?: Record<string, string | { type: string; required?: boolean }>; "loose-value-type"?: string };
}
export interface LanguageManifest {
  definitions: Record<string, LanguageDefinition>; builtins: string[];
  builtin_inputs: Record<string, { allowed: string[]; required: string[] }>;
  contexts: string[]; context_properties: Record<string, string[]>;
}

export function expressionSuggestions(workflow: ActionWorkflow | null): string[] {
  const on = isRecord(workflow?.on) ? workflow.on : {};
  const dispatch = isRecord(on.workflow_dispatch) ? on.workflow_dispatch : {};
  const inputs = isRecord(dispatch.inputs) ? dispatch.inputs : {};
  return ["${{ success() }}", "${{ failure() }}", "${{ always() }}", ...Object.keys(inputs).map(key => `\${{ inputs.${key} }}`),
    ...Object.entries(workflow?.jobs ?? {}).flatMap(([key, job]) => [`\${{ needs.${key}.result }}`, ...Object.keys(job.outputs ?? {}).map(output => `\${{ needs.${key}.outputs.${output} }}`)])];
}

export function schemaKind(type: string, definitions: LanguageManifest["definitions"], value?: unknown, seen = new Set<string>()): string {
  if (seen.has(type)) return "text";
  const definition = definitions[type]; if (!definition) return "text";
  if (definition.mapping) return "table";
  if (definition.sequence) return "list";
  if (definition.boolean !== undefined) return "boolean";
  if (definition.number !== undefined) return "number";
  if (definition["one-of"]) {
    const candidates = definition["one-of"].map(child => schemaKind(child, definitions, value, new Set([...seen, type])));
    const actual = isRecord(value) ? "table" : Array.isArray(value) ? "list" : typeof value;
    return candidates.find(kind => kind === actual) ?? candidates[0];
  }
  return "text";
}
