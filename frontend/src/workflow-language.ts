import type { ActionWorkflow } from "./actions-workflow";
import { isRecord } from "./workflow";

export interface LanguageDefinition {
  description?: string;
  string?: { constant?: string };
  boolean?: unknown;
  number?: unknown;
  "one-of"?: string[];
  sequence?: { "item-type": string };
  mapping?: {
    properties?: Record<string, string | { type: string; required?: boolean }>;
    "loose-value-type"?: string;
  };
}
export interface LanguageManifest {
  host_scripts?: Record<
    string,
    { shell: string; argv: string[]; installed: boolean }
  >;
  definitions: Record<string, LanguageDefinition>;
  builtins: string[];
  builtin_inputs: Record<string, { allowed: string[]; required: string[] }>;
  contexts: string[];
  context_properties: Record<string, string[]>;
}

export function expressionSuggestions(
  workflow: ActionWorkflow | null,
  jobId?: string,
): string[] {
  const on = isRecord(workflow?.on) ? workflow.on : {};
  const dispatch = isRecord(on.workflow_dispatch) ? on.workflow_dispatch : {};
  const inputs = isRecord(dispatch.inputs) ? dispatch.inputs : {};
  const needs = jobId ? workflow?.jobs[jobId]?.needs : undefined;
  const upstream = typeof needs === "string" ? [needs] : needs;
  return [
    "${{ success() }}",
    "${{ failure() }}",
    "${{ always() }}",
    "${{ relay.run_id }}",
    "${{ relay.project_id }}",
    "${{ job.status }}",
    ...Object.keys(workflow?.env ?? {}).map((key) => `\${{ env.${key} }}`),
    ...Object.keys(jobId ? (workflow?.jobs[jobId]?.env ?? {}) : {}).map(
      (key) => `\${{ env.${key} }}`,
    ),
    ...Object.keys(
      jobId && typeof workflow?.jobs[jobId]?.strategy?.matrix === "object"
        ? (workflow.jobs[jobId].strategy!.matrix as object)
        : {},
    )
      .filter((key) => !["include", "exclude"].includes(key))
      .map((key) => `\${{ matrix.${key} }}`),
    ...Object.keys(inputs).map((key) => `\${{ inputs.${key} }}`),
    ...Object.entries(workflow?.jobs ?? {})
      .filter(([id]) => !jobId || upstream?.includes(id))
      .flatMap(([key, job]) => [
        `\${{ needs.${key}.result }}`,
        ...Object.keys(job.outputs ?? {}).map(
          (output) => `\${{ needs.${key}.outputs.${output} }}`,
        ),
      ]),
    ...Object.values(
      jobId && workflow?.jobs[jobId]
        ? { [jobId]: workflow.jobs[jobId] }
        : (workflow?.jobs ?? {}),
    ).flatMap((job) =>
      (job.steps ?? [])
        .filter((step) => step.id)
        .flatMap((step) => [
          `\${{ steps.${step.id}.outcome }}`,
          `\${{ steps.${step.id}.conclusion }}`,
          ...(step.uses === "relay/human-wait@v1"
            ? [`\${{ steps.${step.id}.outputs.answer }}`]
            : []),
        ]),
    ),
  ];
}

export function schemaKind(
  type: string,
  definitions: LanguageManifest["definitions"],
  value?: unknown,
  seen = new Set<string>(),
): string {
  if (seen.has(type)) return "text";
  const definition = definitions[type];
  if (!definition) return "text";
  if (definition.mapping) return "table";
  if (definition.sequence) return "list";
  if (definition.boolean !== undefined) return "boolean";
  if (definition.number !== undefined) return "number";
  if (definition["one-of"]) {
    const candidates = definition["one-of"].map((child) =>
      schemaKind(child, definitions, value, new Set([...seen, type])),
    );
    const actual = isRecord(value)
      ? "table"
      : Array.isArray(value)
        ? "list"
        : typeof value;
    return candidates.find((kind) => kind === actual) ?? candidates[0];
  }
  return "text";
}
