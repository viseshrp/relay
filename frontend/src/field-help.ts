import { parseBuiltin } from "./builtin-actions";
import type { HelpSource } from "./components/HelpTip";
import type { LanguageManifest } from "./workflow-language";

// Sections of the Workflows guide, by the anchor the guide's headings produce.
export const GUIDE = {
  jobs: "jobs-and-ordered-steps",
  scripts: "scripts-and-command-actions",
  inputs: "inputs",
  expressions: "expressions-and-conditions",
  agents: "agent-nodes",
  recovery: "automatic-recovery",
  approvals: "human-waits",
  outputs: "outputs-and-file-commands",
  artifacts: "artifacts-and-caches",
  matrix: "matrix-jobs",
  reusable: "reusable-workflows-and-local-actions",
  variables: "variables-secrets-and-environments",
  concurrency: "concurrency-queues",
} as const;

const ACTION_GUIDES: Record<string, string> = {
  agent: GUIDE.agents,
  command: GUIDE.scripts,
  "human-wait": GUIDE.approvals,
  "validate-report": GUIDE.outputs,
  "validate-input": GUIDE.inputs,
  "upload-artifact": GUIDE.artifacts,
  "download-artifact": GUIDE.artifacts,
  cache: GUIDE.artifacts,
  "restore-cache": GUIDE.artifacts,
  "save-cache": GUIDE.artifacts,
  loop: GUIDE.reusable,
};

/** Help for a schema field, keyed "<definition>.<property>" (F3). */
export function propertyHelp(
  manifest: LanguageManifest,
  key: string,
  title: string,
  guide: string = GUIDE.jobs,
): HelpSource {
  return {
    title,
    description: manifest.property_descriptions[key] ?? "",
    guide,
  };
}

/** Help for one input of the action a step uses. */
export function inputHelp(
  manifest: LanguageManifest,
  reference: string | undefined,
  input: string,
  title: string,
): HelpSource {
  const name = parseBuiltin(reference)?.name;
  return {
    title,
    description:
      manifest.builtin_inputs[reference ?? ""]?.descriptions[input] ??
      "An input passed to this action as text.",
    guide: (name && ACTION_GUIDES[name]) || GUIDE.reusable,
  };
}

/** Help for a step field: script steps and action steps describe it apart. */
export function stepHelp(
  manifest: LanguageManifest,
  uses: string | undefined,
  property: string,
  title: string,
): HelpSource {
  return propertyHelp(
    manifest,
    `${uses ? "regular-step" : "run-step"}.${property}`,
    title,
  );
}
