import type { ActionWorkflow } from "./actions-workflow";
import { isBuiltin } from "./builtin-actions";
import { isRecord } from "./workflow";
import type { YamlSegment } from "./yaml-path";

type PropertyDescriptor =
  string | { type: string; required?: boolean; description?: string };

export interface LanguageDefinition {
  description?: string;
  /** Expression contexts and functions a field of this type may use. */
  context?: string[];
  string?: { constant?: string };
  boolean?: unknown;
  number?: unknown;
  "one-of"?: string[];
  "allowed-values"?: string[];
  sequence?: { "item-type": string };
  mapping?: {
    properties?: Record<string, PropertyDescriptor>;
    "loose-value-type"?: string;
  };
}
export interface BuiltinInputs {
  allowed: string[];
  required: string[];
  /** One sentence saying what the action does. */
  summary: string;
  /** Help text for each allowed input. */
  descriptions: Record<string, string>;
  /** Fixed values that some inputs accept, in the order to offer them. */
  values: Record<string, string[]>;
}
export interface LanguageManifest {
  host_scripts?: Record<
    string,
    { shell: string; argv: string[]; installed: boolean }
  >;
  definitions: Record<string, LanguageDefinition>;
  /** Help text keyed "<definition>.<property>". */
  property_descriptions: Record<string, string>;
  builtins: string[];
  builtin_inputs: Record<string, BuiltinInputs>;
  /** Every registered version; deprecated_in names the release that deprecated it. */
  builtin_versions: Record<
    string,
    {
      name: string;
      major: number;
      status: "current" | "deprecated";
      deprecated_in: string;
    }
  >;
  cache_modes: string[];
  value_hints: { shell: string[] };
  /** Relay's expression names for properties written with another root. */
  platform_names: Record<string, Record<string, string>>;
  contexts: string[];
  context_properties: Record<string, string[]>;
}

export function descriptorType(descriptor: PropertyDescriptor): string {
  return typeof descriptor === "string" ? descriptor : descriptor.type;
}

/** The definitions whose mapping a node of this type can be: itself, or one-of variants. */
function mappingVariants(
  name: string,
  definitions: LanguageManifest["definitions"],
): string[] {
  const definition = definitions[name];
  if (definition?.mapping) return [name];
  return (definition?.["one-of"] ?? []).filter(
    (variant) => definitions[variant]?.mapping,
  );
}

/** Every property a mapping of this type accepts, with the definition that owns it. */
export function mappingProperties(
  name: string,
  manifest: LanguageManifest,
): Array<{ key: string; owner: string; type: string }> {
  const seen = new Set<string>();
  return mappingVariants(name, manifest.definitions).flatMap((owner) =>
    Object.entries(
      manifest.definitions[owner].mapping?.properties ?? {},
    ).flatMap(([key, descriptor]) => {
      if (seen.has(key)) return [];
      seen.add(key);
      return [{ key, owner, type: descriptorType(descriptor) }];
    }),
  );
}

/** The type of one property, or of a loose key, of a mapping of this type. */
export function propertyType(
  name: string,
  key: string,
  manifest: LanguageManifest,
): { owner: string | null; type: string } | null {
  const property = mappingProperties(name, manifest).find(
    (item) => item.key === key,
  );
  if (property) return property;
  const loose = mappingVariants(name, manifest.definitions)
    .map((owner) => manifest.definitions[owner].mapping?.["loose-value-type"])
    .find(Boolean);
  return loose ? { owner: null, type: loose } : null;
}

function variant(
  name: string,
  next: YamlSegment | undefined,
  keys: Record<string, unknown> | undefined,
  definitions: LanguageManifest["definitions"],
): string {
  if (name === "job")
    return keys && "uses" in keys ? "workflow-job" : "job-factory";
  if (name === "steps-item")
    return keys && "uses" in keys
      ? "regular-step"
      : keys && "run" in keys
        ? "run-step"
        : name;
  const options = (definitions[name]?.["one-of"] ?? []).filter(
    (option) => definitions[option]?.mapping || definitions[option]?.sequence,
  );
  if (!options.length) return name;
  const wanted = typeof next === "number" ? "sequence" : "mapping";
  return options.find((option) => definitions[option]?.[wanted]) ?? options[0];
}

/** Every definition met on the way to a path, ending with the node's own. */
function definitionChain(
  path: YamlSegment[],
  manifest: LanguageManifest,
  scopes: ReadonlyArray<Record<string, unknown>>,
): string[] | null {
  const { definitions } = manifest;
  let name = variant("workflow-root", path[0], scopes[0], definitions);
  const chain = [name];
  for (const [index, segment] of path.entries()) {
    const next =
      typeof segment === "number"
        ? (definitions[name]?.sequence?.["item-type"] ??
          (definitions[name]?.["one-of"] ?? [])
            .map((option) => definitions[option]?.sequence?.["item-type"])
            .find(Boolean))
        : propertyType(name, segment, manifest)?.type;
    if (!next) return null;
    name = variant(next, path[index + 1], scopes[index + 1], definitions);
    chain.push(next, name);
  }
  return chain;
}

/**
 * The schema definition of the node at a YAML path. `scopes[i]` lists the keys
 * already written in the node at `path.slice(0, i)`, which decides between a
 * job and a reusable job, and between a script step and an action step. A step
 * with neither run nor uses resolves to steps-item, whose variants together
 * give its properties.
 */
export function definitionAt(
  path: YamlSegment[],
  manifest: LanguageManifest,
  scopes: ReadonlyArray<Record<string, unknown>> = [],
): string | null {
  return definitionChain(path, manifest, scopes)?.at(-1) ?? null;
}

/**
 * Expression contexts and functions available in the value of `key` at a
 * path. Like validation, a field inherits those of every definition above it.
 */
export function contextsAt(
  path: YamlSegment[],
  key: string | null,
  manifest: LanguageManifest,
  scopes: ReadonlyArray<Record<string, unknown>> = [],
): string[] {
  const { definitions } = manifest;
  const chain = definitionChain(path, manifest, scopes) ?? [];
  const owner = chain.at(-1);
  const type = key && owner ? propertyType(owner, key, manifest)?.type : null;
  const scalars = (definitions[type ?? ""]?.["one-of"] ?? []).filter(
    (option) => !definitions[option]?.mapping && !definitions[option]?.sequence,
  );
  return [
    ...new Set(
      [...chain, ...(type ? [type, ...scalars] : [])].flatMap(
        (name) => definitions[name]?.context ?? [],
      ),
    ),
  ];
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
  // Run metadata names come from the manifest; see fieldExpressions.
  return [
    "${{ success() }}",
    "${{ failure() }}",
    "${{ always() }}",
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
          ...(isBuiltin(step.uses, "human-wait")
            ? [`\${{ steps.${step.id}.outputs.answer }}`]
            : []),
        ]),
    ),
  ];
}

/**
 * Whether validation accepts an expression name, such as `relay.sha` or
 * `success()`, where these contexts and functions are available.
 */
export function expressionAllowed(
  name: string,
  available: ReadonlySet<string>,
  manifest: LanguageManifest,
): boolean {
  const [context, property] = name.split(".");
  const known = manifest.context_properties[context];
  return (
    available.has(name.split(/[.(]/)[0].toLowerCase()) &&
    !(known && property !== undefined && !known.includes(property))
  );
}

/** The contexts and function names usable in the value of `key` at a path. */
export function availableContexts(
  path: YamlSegment[],
  key: string | null,
  manifest: LanguageManifest,
  scopes: ReadonlyArray<Record<string, unknown>> = [],
): Set<string> {
  return new Set(
    contextsAt(path, key, manifest, scopes).map((item) =>
      item.replace(/\(.*$/, "").toLowerCase(),
    ),
  );
}

/**
 * Every expression, as `${{ name }}`, that validation accepts in the value of
 * `key` at a path: names from this workflow and the manifest's run metadata.
 */
export function fieldExpressions(
  workflow: ActionWorkflow | null,
  path: YamlSegment[],
  key: string,
  manifest: LanguageManifest,
  scopes: ReadonlyArray<Record<string, unknown>> = [],
): string[] {
  const job =
    path[0] === "jobs" && typeof path[1] === "string" ? path[1] : undefined;
  const available = availableContexts(path, key, manifest, scopes);
  const names = [
    ...expressionSuggestions(workflow, job).map((item) =>
      item.replace(/^\$\{\{\s*/, "").replace(/\s*\}\}$/, ""),
    ),
    ...Object.entries(manifest.context_properties).flatMap(
      ([context, properties]) =>
        properties.map((property) => `${context}.${property}`),
    ),
  ];
  return [
    ...new Set(
      names.filter((name) => expressionAllowed(name, available, manifest)),
    ),
  ].map((name) => `\${{ ${name} }}`);
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
