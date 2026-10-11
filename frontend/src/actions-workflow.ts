import { Lexer, Parser } from "@actions/expressions";
import { isAlias, isSeq, parseDocument } from "yaml";
import type { Edge, Node } from "@xyflow/react";
import { arrangeGraph } from "./graph";
import {
  isRecord,
  type WorkflowValue,
  type WorkflowNodeData,
  type InputDefinition,
} from "./workflow";

export interface ActionStep {
  id?: string;
  name?: string;
  run?: string;
  uses?: string;
  with?: Record<string, unknown>;
  env?: Record<string, unknown>;
  if?: string;
  shell?: string;
  "working-directory"?: string;
  "continue-on-error"?: boolean | string;
  "timeout-minutes"?: number | string;
}
export interface ActionJob {
  name?: string;
  needs?: string | string[];
  steps?: ActionStep[];
  uses?: string;
  with?: Record<string, unknown>;
  env?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  strategy?: Record<string, unknown>;
  environment?: string | Record<string, unknown>;
  if?: string;
  "timeout-minutes"?: number | string;
  "continue-on-error"?: boolean | string;
  concurrency?: unknown;
  secrets?: unknown;
  "cache-mode"?: string;
}
export interface ActionWorkflow {
  name?: string;
  "run-name"?: string;
  on?: unknown;
  jobs: Record<string, ActionJob>;
  env?: Record<string, unknown>;
  entrypoints?: Array<{
    scope_path: string;
    inputs?: string[];
    artifacts?: Record<string, unknown>;
  }>;
  recovery?: { enabled?: boolean; max_retries?: number };
  defaults?: unknown;
  concurrency?: unknown;
  "cache-mode"?: string;
}

export { readableWorkflowYaml as editorYaml } from "./source-format";

function editorSafeDefinitions(value: Record<string, unknown>): boolean {
  return Object.values(value).every((item) => {
    if (!isRecord(item)) return false;
    if (item.name != null && typeof item.name !== "string") return false;
    if (
      item.needs != null &&
      !(typeof item.needs === "string") &&
      !(
        Array.isArray(item.needs) &&
        item.needs.every((name) => typeof name === "string")
      )
    )
      return false;
    if (
      item.steps != null &&
      !(
        Array.isArray(item.steps) &&
        item.steps.every(
          (step) =>
            isRecord(step) &&
            ["name", "id", "uses"].every(
              (field) => step[field] == null || typeof step[field] === "string",
            ),
        )
      )
    )
      return false;
    return true;
  });
}

export function parseActions(text: string) {
  const document = parseDocument(text, {
    keepSourceTokens: true,
    prettyErrors: true,
    uniqueKeys: true,
  });
  const errors = document.errors.map((error) => error.message);
  let value: ActionWorkflow | null = null;
  if (errors.length) return { document, value, errors };
  try {
    const raw: unknown = document.toJS({ maxAliasCount: 100 });
    if (
      isRecord(raw) &&
      (raw.name == null || typeof raw.name === "string") &&
      isRecord(raw.jobs) &&
      editorSafeDefinitions(raw.jobs)
    )
      value = raw as unknown as ActionWorkflow;
    else if (!errors.length)
      errors.push("Use a jobs mapping with ordered steps.");
  } catch (error) {
    errors.push(String(error));
  }
  return { document, value, errors };
}

export function expressionDiagnostic(source: string): string | null {
  try {
    const tokens = new Lexer(source).lex().tokens;
    new Parser(
      tokens,
      [
        "relay",
        "inputs",
        "vars",
        "env",
        "secrets",
        "needs",
        "steps",
        "jobs",
        "job",
        "host",
        "matrix",
        "strategy",
      ],
      [
        { name: "hashFiles", minArgs: 1, maxArgs: 255 },
        { name: "case", minArgs: 3, maxArgs: 255 },
      ],
    ).parse();
    return null;
  } catch (error) {
    return String(error);
  }
}

function detachAliases(
  document: ReturnType<typeof parseDocument>,
  path: Array<string | number>,
): void {
  // Editing one alias detaches that occurrence before descending into it.
  for (let length = 1; length <= path.length; length++) {
    const prefix = path.slice(0, length);
    const node = document.getIn(prefix, true);
    if (isAlias(node)) {
      const resolved = node.resolve(document);
      if (!resolved) throw new Error("The YAML alias has no anchor.");
      const detached = resolved.clone();
      if ("anchor" in detached) detached.anchor = undefined;
      if (node.comment !== undefined) detached.comment = node.comment;
      if (node.commentBefore !== undefined)
        detached.commentBefore = node.commentBefore;
      document.setIn(prefix, detached);
    }
  }
}

export function editActions(
  text: string,
  path: Array<string | number>,
  value: unknown,
): string {
  const parsed = parseActions(text);
  if (parsed.errors.length || !parsed.value)
    throw new Error(parsed.errors.join("\n"));
  detachAliases(parsed.document, path);
  if (value === undefined) parsed.document.deleteIn(path);
  else parsed.document.setIn(path, JSON.parse(JSON.stringify(value)));
  return parsed.document.toString({ lineWidth: 80 });
}

export function moveActionStep(
  text: string,
  jobId: string,
  index: number,
  destination: number,
): string {
  const parsed = parseActions(text);
  if (parsed.errors.length || !parsed.value)
    throw new Error(parsed.errors.join("\n"));
  detachAliases(parsed.document, ["jobs", jobId, "steps"]);
  const steps = parsed.document.getIn(["jobs", jobId, "steps"], true);
  if (
    !isSeq(steps) ||
    index < 0 ||
    index >= steps.items.length ||
    destination < 0 ||
    destination >= steps.items.length
  )
    throw new Error("Select a valid ordered step.");
  const [selected] = steps.items.splice(index, 1);
  steps.items.splice(destination, 0, selected);
  return parsed.document.toString({ lineWidth: 80 });
}

export function actionsGraph(value: ActionWorkflow | null): {
  nodes: Node<WorkflowNodeData>[];
  edges: Edge[];
} {
  if (!value) return { nodes: [], edges: [] };
  const nodes = Object.entries(value.jobs).map(([id, job]) => ({
    id,
    type: "editorJob",
    position: { x: 0, y: 0 },
    data: {
      label: job.name || id,
      kind: "actions_job",
      childWorkflow:
        job.uses ??
        job.steps?.find((step) => step.uses === "relay/loop@v1")?.with
          ?.workflow,
      loopBody:
        job.steps?.some((step) => step.uses === "relay/loop@v1") ?? false,
      detail:
        job.uses ||
        job.steps
          ?.map((step) =>
            step.uses === "relay/agent@v1"
              ? `${String(step.with?.agent ?? "Agent")} · ${String(step.with?.model ?? "Saved model")}`
              : (step.uses ?? step.run?.split("\n")[0] ?? "Step"),
          )
          .join(" → "),
    },
  }));
  const edges = Object.entries(value.jobs).flatMap(([target, job]) =>
    (typeof job.needs === "string" ? [job.needs] : job.needs || []).map(
      (source) => ({ id: `${source}-${target}`, source, target }),
    ),
  );
  return { nodes: arrangeGraph(nodes, edges), edges };
}

export function launchView(
  value: ActionWorkflow | null,
  environments: string[] = [],
): WorkflowValue | null {
  if (!value) return null;
  const events = isRecord(value.on) ? value.on : {};
  const dispatch = isRecord(events.workflow_dispatch)
    ? events.workflow_dispatch
    : {};
  const definitions = isRecord(dispatch.inputs) ? dispatch.inputs : {};
  const inputs: Record<string, InputDefinition> = {};
  for (const [name, definition] of Object.entries(definitions)) {
    if (!isRecord(definition)) continue;
    if (definition.type === "environment") {
      inputs[name] = {
        ...definition,
        type: "enum",
        constraints: { values: environments },
      };
      continue;
    }
    inputs[name] = {
      ...definition,
      type:
        definition.type === "choice"
          ? "enum"
          : definition.type === "environment"
            ? "string"
            : (String(definition.type || "string") as InputDefinition["type"]),
      ...(definition.options
        ? { constraints: { values: definition.options } }
        : {}),
    };
  }
  return {
    version: 1,
    name: value.name || "Workflow",
    entrypoints: value.entrypoints,
    nodes: Object.fromEntries(
      Object.entries(value.jobs).map(([name, job]) => [
        name,
        {
          type: "actions_job",
          needs: typeof job.needs === "string" ? [job.needs] : job.needs,
        },
      ]),
    ),
    inputs,
  };
}
