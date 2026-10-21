import { expect, test } from "@playwright/test";
import { parse } from "yaml";
import { defaultStep } from "../src/action-defaults";
import { ACTION_TYPES, actionLabel } from "../src/action-labels";
import {
  cardSteps,
  renameJob,
  stepLabel,
  type ActionWorkflow,
} from "../src/actions-workflow";
import { currentBuiltin } from "../src/builtin-actions";
import { fieldExpressions } from "../src/workflow-language";
import { manifest } from "./language-manifest";

const reference = (name: string) => currentBuiltin(manifest, name);

test("every step type has one plain label for every version", () => {
  expect(actionLabel(undefined)).toBe("Script");
  expect(actionLabel(reference("human-wait"))).toBe("Approval");
  expect(actionLabel(reference("human-wait").replace(/1$/, "7"))).toBe(
    "Approval",
  );
  expect(actionLabel("./.relay/actions/lint")).toBe("Local action");
  for (const type of ACTION_TYPES) {
    expect(type.label).not.toMatch(/relay\/|@v/);
    expect(type.description).toMatch(/\.$/);
  }
});

test("new steps start with values that validate", () => {
  expect(defaultStep("")).toEqual({ run: "echo Ready" });
  expect(defaultStep(reference("command"))).toEqual({
    uses: reference("command"),
    with: { argv: '["echo","Ready"]' },
  });
  expect(defaultStep(reference("human-wait")).with).toEqual({
    prompt: "Review the work so far, then choose an answer.",
    options: '["Continue","Stop"]',
  });
  expect(defaultStep(reference("validate-report")).with).toEqual({
    path: "REPORT.md",
    format: "exists",
  });
  expect(defaultStep(reference("save-cache")).with).toEqual({
    key: "deps-${{ hashFiles('requirements.txt') }}",
    path: ".venv",
  });
  expect(defaultStep(reference("loop"), "body.yaml").with).toEqual({
    workflow: "./.relay/workflows/body.yaml",
    "max-iterations": "3",
  });
  // Each call returns its own inputs, so editing one step leaves the next.
  expect(defaultStep(reference("cache")).with).not.toBe(
    defaultStep(reference("cache")).with,
  );
});

test("a step is labelled by name, ID, type, then its first script line", () => {
  expect(stepLabel({ name: "Build", id: "b", run: "make" })).toBe("Build");
  expect(stepLabel({ id: "b", run: "make" })).toBe("b");
  expect(stepLabel({ uses: reference("agent") })).toBe("Agent");
  expect(stepLabel({ run: "\n  make all\nmake test" })).toBe("make all");
  expect(stepLabel({ run: "x".repeat(60) })).toBe("x".repeat(40));
  expect(stepLabel({})).toBe("Script");
});

test("canvas cards list five steps, then how many more", () => {
  const steps = Array.from({ length: 7 }, (_, index) => ({
    name: `Step ${index + 1}`,
  }));
  expect(cardSteps(steps.slice(0, 5))).toHaveLength(5);
  expect(cardSteps(steps)).toEqual([
    "Step 1",
    "Step 2",
    "Step 3",
    "Step 4",
    "Step 5",
    "+2 more",
  ]);
});

test("renaming a job moves every reference to it in one edit", () => {
  const source = [
    "name: Rename",
    "entrypoints:",
    "  - scope_path: root.check",
    "jobs:",
    "  check: # the first job",
    "    outputs: {x: ready}",
    "    steps: [{run: echo}]",
    "  check_2:",
    "    needs: check",
    "    if: needs.check.result == 'success'",
    "    steps:",
    "      - run: echo ${{ needs.check.outputs.x }} ${{ needs.check_2 }}",
    "  last:",
    "    needs: [check, check_2]",
    "    steps: [{run: echo check}]",
    "",
  ].join("\n");
  const renamed = renameJob(source, "check", "review");
  const value = parse(renamed);
  expect(Object.keys(value.jobs)).toEqual(["review", "check_2", "last"]);
  expect(renamed).toContain("# the first job");
  expect(value.jobs.check_2.needs).toBe("review");
  expect(value.jobs.check_2.if).toBe("needs.review.result == 'success'");
  expect(value.jobs.check_2.steps[0].run).toBe(
    "echo ${{ needs.review.outputs.x }} ${{ needs.check_2 }}",
  );
  expect(value.jobs.last.needs).toEqual(["review", "check_2"]);
  expect(value.jobs.last.steps[0].run).toBe("echo check");
  expect(value.entrypoints[0].scope_path).toBe("root.review");
  expect(() => renameJob(source, "check", "last")).toThrow();
  expect(() => renameJob(source, "check", "9lives")).toThrow();
});

test("condition helpers offer only names the field accepts", () => {
  const workflow: ActionWorkflow = {
    on: { workflow_dispatch: { inputs: { task: { type: "string" } } } },
    env: { MODE: "local" },
    jobs: {
      first: { outputs: { x: "1" }, steps: [{ id: "s", run: "echo" }] },
      second: { needs: ["first"], steps: [{ id: "t", run: "echo" }] },
    },
  };
  const scopes = [workflow, workflow.jobs, workflow.jobs.second] as Array<
    Record<string, unknown>
  >;
  const job = fieldExpressions(
    workflow,
    ["jobs", "second"],
    "if",
    manifest,
    scopes,
  );
  expect(job).toEqual(
    expect.arrayContaining([
      "${{ success() }}",
      "${{ inputs.task }}",
      "${{ needs.first.outputs.x }}",
      "${{ relay.run_id }}",
    ]),
  );
  // A job's condition cannot read steps, env, or the host.
  for (const item of job) expect(item).not.toMatch(/steps\.|env\.|host\./);
  expect(job).not.toContain("${{ relay.project_id }}");
  const step = fieldExpressions(
    workflow,
    ["jobs", "second", "steps", 0],
    "if",
    manifest,
    [...scopes, {}, workflow.jobs.second.steps![0] as Record<string, unknown>],
  );
  expect(step).toEqual(
    expect.arrayContaining([
      "${{ steps.t.outcome }}",
      "${{ env.MODE }}",
      "${{ host.os }}",
    ]),
  );
  // Run metadata comes only from the manifest's listed properties.
  for (const item of [...job, ...step]) {
    const [context, property] = item.slice(4, -3).split(".");
    const known = manifest.context_properties[context];
    if (known) expect(known, item).toContain(property);
  }
});
