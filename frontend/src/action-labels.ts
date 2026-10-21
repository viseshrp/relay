import { parseBuiltin } from "./builtin-actions";

/** One kind of step, keyed by built-in action name; `script` is a run step. */
export interface ActionType {
  name: string;
  group: string;
  label: string;
  description: string;
}

// Keyed by action name so every version of an action shares its label.
export const ACTION_TYPES: readonly ActionType[] = [
  {
    group: "Agents",
    name: "agent",
    label: "Agent",
    description: "Ask a coding agent to do the work.",
  },
  {
    group: "Scripts and commands",
    name: "script",
    label: "Script",
    description: "Run commands in a shell.",
  },
  {
    group: "Scripts and commands",
    name: "command",
    label: "Command",
    description: "Run one program with exact arguments.",
  },
  {
    group: "Approvals",
    name: "human-wait",
    label: "Approval",
    description: "Pause until you answer.",
  },
  {
    group: "Reports and checks",
    name: "validate-report",
    label: "Check a report",
    description: "Read a report file and pass its verdict on.",
  },
  {
    group: "Reports and checks",
    name: "validate-input",
    label: "Check a value",
    description: "Stop when a value is not the expected type.",
  },
  {
    group: "Artifacts and caches",
    name: "upload-artifact",
    label: "Upload artifact",
    description: "Keep files from this run.",
  },
  {
    group: "Artifacts and caches",
    name: "download-artifact",
    label: "Download artifact",
    description: "Bring back files kept by a run.",
  },
  {
    group: "Artifacts and caches",
    name: "cache",
    label: "Cache",
    description: "Restore files now and save them after the job.",
  },
  {
    group: "Artifacts and caches",
    name: "restore-cache",
    label: "Restore cache",
    description: "Restore files saved earlier.",
  },
  {
    group: "Artifacts and caches",
    name: "save-cache",
    label: "Save cache",
    description: "Save files for later runs.",
  },
  {
    group: "Advanced",
    name: "loop",
    label: "Repeat a workflow",
    description: "Run another workflow until it reports done.",
  },
];

/** The step types offered first by Add step, in order. */
export const PRIMARY_STEP_TYPES = [
  "agent",
  "script",
  "command",
  "human-wait",
  "validate-report",
  "upload-artifact",
];

export const LOCAL_ACTION: ActionType = {
  group: "Advanced",
  name: "local",
  label: "Local action",
  description: "An action defined in this project under ./.relay/actions/.",
};

/** The step type name of a `uses` value: an action name, script, or local. */
export function actionName(reference: string | undefined): string {
  if (!reference) return "script";
  return parseBuiltin(reference)?.name ?? "local";
}

export function actionType(reference: string | undefined): ActionType | null {
  const name = actionName(reference);
  if (name === "local")
    return reference?.startsWith("./") ? LOCAL_ACTION : null;
  return ACTION_TYPES.find((item) => item.name === name) ?? null;
}

/** A plain label for the step type of a `uses` value; no value is a script. */
export function actionLabel(reference: string | undefined): string {
  return actionType(reference)?.label ?? reference ?? "Script";
}
