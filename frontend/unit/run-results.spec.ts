import { expect, test } from "@playwright/test";
import { artifactPath, defaultReviewSelection } from "../src/artifacts";
import { jobListRows, jobScopeLabel } from "../src/job-list";
import type { ArtifactRecord, RunNode } from "../src/types";

function artifact(id: string, path: string): ArtifactRecord {
  return {
    scope_path: "root.plan.step_1",
    attempt_number: 1,
    id,
    attempt_id: "attempt",
    name: path.split("/").at(-1)!,
    source_path: `/data/worktrees/run-1/r-${id}/${path}`,
    sha256: "0".repeat(64),
    bytes: 10,
    media_type: "text/markdown",
    preservation_state: "preserved",
  };
}

function node(
  scope_path: string,
  node_type: string,
  parent_scope: string | null,
  display_name?: string,
): RunNode {
  return {
    id: scope_path,
    scope_path,
    node_id: scope_path.split(".").at(-1)!,
    node_type,
    status: "succeeded",
    writes: true,
    parent_scope,
    dependencies: [],
    ...(display_name ? { display_name } : {}),
  };
}

test("review material starts with a named document, then changes, then the newest", () => {
  const documents = [
    artifact("3", "INITIAL_OPUS_PLANNING_PROMPT.md"),
    artifact("9", "EXECUTION_PROMPT.md"),
    artifact("7", "docs/REVIEW.md"),
  ].map((item) => ({ label: artifactPath("run-1", item), artifact: item }));
  expect(documents.map((item) => item.label)).toEqual([
    "INITIAL_OPUS_PLANNING_PROMPT.md",
    "EXECUTION_PROMPT.md",
    "docs/REVIEW.md",
  ]);
  expect(
    defaultReviewSelection(documents, true, "Read EXECUTION_PROMPT.md first."),
  ).toBe("9");
  expect(defaultReviewSelection(documents, true, "Read the plan.")).toBe(
    "changes",
  );
  expect(defaultReviewSelection(documents, false, null)).toBe("9");
  expect(defaultReviewSelection([], false, null)).toBeUndefined();
});

test("job context uses display names for loop rounds and their jobs", () => {
  const nodes = [
    node("root.refine_plan", "actions_job", null, "Critique and revise"),
    node("root.refine_plan.step_1", "actions_step", "root.refine_plan"),
    node(
      "root.refine_plan.step_1.iteration_1",
      "actions_job",
      "root.refine_plan.step_1",
      "Round 1",
    ),
    node(
      "root.refine_plan.step_1.iteration_1.cycle",
      "actions_job",
      "root.refine_plan.step_1.iteration_1",
      "Plan round",
    ),
  ];
  const label = jobScopeLabel(nodes);
  expect(label("root.refine_plan.step_1")).toBe("Critique and revise");
  expect(label("root.unknown_job")).toBe("Unknown job");
  const contexts = Object.fromEntries(
    jobListRows(nodes).map((row) => [row.node.scope_path, row.context]),
  );
  expect(contexts["root.refine_plan.step_1.iteration_1"]).toBe(
    "Critique and revise",
  );
  expect(contexts["root.refine_plan.step_1.iteration_1.cycle"]).toBe(
    "Critique and revise › Round 1",
  );
});
