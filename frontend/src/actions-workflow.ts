import { Lexer, Parser } from "@actions/expressions";
import { isAlias, isMap, isScalar, isSeq, parseDocument, visit } from "yaml";
import type { Edge, Node } from "@xyflow/react";
import { actionLabel } from "./action-labels";
import { isBuiltin } from "./builtin-actions";
import { arrangeGraph } from "./graph";
import {
  isRecord,
  type LaunchWorkflow,
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

/** A step's name, else its ID, else its type, else its script's first line. */
export function stepLabel(step: ActionStep): string {
  if (step.name) return step.name;
  if (step.id) return step.id;
  if (step.uses) return actionLabel(step.uses);
  const line = step.run
    ?.split("\n")
    .find((text) => text.trim())
    ?.trim();
  return line ? line.slice(0, 40) : "Script";
}

/** The step lines a canvas card shows: at most five, then a count. */
const CARD_STEPS = 5;

export function cardSteps(steps: ActionStep[] | undefined): string[] {
  const labels = (steps ?? []).map(stepLabel);
  return labels.length > CARD_STEPS
    ? [...labels.slice(0, CARD_STEPS), `+${labels.length - CARD_STEPS} more`]
    : labels;
}

/** Card height in pixels for a job with this many step lines. */
export function cardHeight(lines: number, button = false): number {
  return Math.max(104, 72 + lines * 18) + (button ? 40 : 0);
}

export function actionsGraph(value: ActionWorkflow | null): {
  nodes: Node<WorkflowNodeData>[];
  edges: Edge[];
} {
  if (!value) return { nodes: [], edges: [] };
  const nodes = Object.entries(value.jobs).map(([id, job]) => {
    const steps = job.uses ? undefined : cardSteps(job.steps);
    return {
      id,
      type: "editorJob",
      position: { x: 0, y: 0 },
      data: {
        label: job.name || id,
        kind: "actions_job",
        childWorkflow:
          job.uses ??
          job.steps?.find((step) => isBuiltin(step.uses, "loop"))?.with
            ?.workflow,
        loopBody:
          job.steps?.some((step) => isBuiltin(step.uses, "loop")) ?? false,
        steps,
        detail: job.uses
          ? `Reusable workflow: ${job.uses.split("/").at(-1) ?? job.uses}`
          : undefined,
      },
    };
  });
  const edges = Object.entries(value.jobs).flatMap(([target, job]) =>
    (typeof job.needs === "string" ? [job.needs] : job.needs || []).map(
      (source) => ({ id: `${source}-${target}`, source, target }),
    ),
  );
  return {
    nodes: arrangeGraph(nodes, edges, (node) =>
      cardHeight(
        Array.isArray(node.data.steps) ? node.data.steps.length : 0,
        typeof node.data.childWorkflow === "string",
      ),
    ),
    edges,
  };
}

/** Whether a job ID can be written as a key that expressions can name. */
export const JOB_ID = /^[A-Za-z_][A-Za-z0-9_-]*$/;

/**
 * Rename one job in a single source edit: its key under `jobs` (keeping its
 * place), every `needs` that names it, declared start points, and its
 * `needs.<id>` and `jobs.<id>` references inside expressions.
 */
export function renameJob(text: string, from: string, to: string): string {
  const parsed = parseActions(text);
  if (parsed.errors.length || !parsed.value)
    throw new Error(parsed.errors.join("\n"));
  if (!JOB_ID.test(to) || (to !== from && to in parsed.value.jobs))
    throw new Error("Choose a new, unused job ID.");
  const document = parsed.document;
  detachAliases(document, ["jobs"]);
  const jobs = document.get("jobs", true);
  if (!isMap(jobs)) throw new Error("Use a jobs mapping with ordered steps.");
  for (const pair of jobs.items) {
    if (isScalar(pair.key) && pair.key.value === from) pair.key.value = to;
    if (!isMap(pair.value)) continue;
    const needs = pair.value.get("needs", true);
    if (isScalar(needs) && needs.value === from) needs.value = to;
    if (isSeq(needs))
      for (const item of needs.items)
        if (isScalar(item) && item.value === from) item.value = to;
  }
  const escaped = from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const reference = new RegExp(
    `(\\b(?:needs|jobs)\\.)${escaped}(?![A-Za-z0-9_-])`,
    "g",
  );
  const start = new RegExp(`^root\\.${escaped}(?=$|\\.)`);
  visit(document, {
    Pair(_, pair) {
      if (
        !isScalar(pair.key) ||
        !isScalar(pair.value) ||
        typeof pair.value.value !== "string"
      )
        return;
      if (pair.key.value === "scope_path")
        pair.value.value = pair.value.value.replace(start, `root.${to}`);
      // A condition is an expression even without ${{ }}.
      else if (pair.key.value === "if" && !pair.value.value.includes("${{"))
        pair.value.value = pair.value.value.replace(reference, `$1${to}`);
    },
    Scalar(_, node) {
      if (typeof node.value === "string" && node.value.includes("${{"))
        node.value = node.value.replace(/\$\{\{[\s\S]*?\}\}/g, (part) =>
          part.replace(reference, `$1${to}`),
        );
    },
  });
  return document.toString({ lineWidth: 80 });
}

export function launchView(
  value: ActionWorkflow | null,
  environments: string[] = [],
): LaunchWorkflow | null {
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
    name: value.name || "Workflow",
    jobs: Object.keys(value.jobs),
    entrypoints: value.entrypoints,
    inputs,
  };
}
