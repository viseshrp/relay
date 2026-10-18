import type { ActionStep } from "./actions-workflow";
import { parseBuiltin } from "./builtin-actions";

// Each new step starts valid; `with` values are strings, as YAML writes them.
const CACHE = {
  key: "deps-${{ hashFiles('requirements.txt') }}",
  path: ".venv",
};
const INPUTS: Record<string, Record<string, string>> = {
  agent: { prompt: "Describe the change you want." },
  command: { argv: '["echo","Ready"]' },
  "human-wait": {
    prompt: "Review the work so far, then choose an answer.",
    options: '["Continue","Stop"]',
  },
  "validate-report": { path: "REPORT.md", format: "exists" },
  "validate-input": { value: "ready", type: "string" },
  "upload-artifact": { name: "report", path: "REPORT.md" },
  "download-artifact": { name: "report" },
  cache: CACHE,
  "restore-cache": CACHE,
  "save-cache": CACHE,
};

/** The project-relative `workflow` input that repeats the workflow `key`. */
export function loopWorkflow(key: string): string {
  return `./.relay/workflows/${key}`;
}

/**
 * A step that validates as soon as it is added. An empty reference is a
 * script step. A loop needs the key of the workflow it repeats.
 */
export function defaultStep(reference: string, workflow?: string): ActionStep {
  if (!reference) return { run: "echo Ready" };
  const name = parseBuiltin(reference)?.name;
  if (name === "loop")
    return {
      uses: reference,
      with: {
        workflow: workflow ? loopWorkflow(workflow) : "",
        "max-iterations": "3",
      },
    };
  const inputs = name ? INPUTS[name] : undefined;
  return inputs
    ? { uses: reference, with: { ...inputs } }
    : { uses: reference };
}
