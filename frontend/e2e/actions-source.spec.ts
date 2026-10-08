import { expect, test } from "@playwright/test";
import { editActions, moveActionStep, parseActions } from "../src/actions-workflow";

const source = `# Workflow comment
name: Source preservation
jobs:
  original:
    runs-on: self-hosted
    steps: &ordered
      # First step comment
      - id: first
        run: echo first # Inline comment
      # Second step comment
      - id: second
        run: echo second
  caller:
    runs-on: self-hosted
    steps: *ordered # Alias comment
`;

test("editing an aliased step preserves comments and leaves the original anchor unchanged", () => {
  const edited = editActions(source, ["jobs", "caller", "steps", 0, "run"], "echo changed");
  const parsed = parseActions(edited);
  expect(parsed.errors).toEqual([]);
  expect(parsed.value?.jobs.original.steps?.[0].run).toBe("echo first");
  expect(parsed.value?.jobs.caller.steps?.[0].run).toBe("echo changed");
  for (const comment of ["Workflow comment", "First step comment", "Inline comment", "Second step comment", "Alias comment"]) expect(edited).toContain(comment);
});

test("reordering an aliased sequence keeps step comments and detaches only that sequence", () => {
  const edited = moveActionStep(source, "caller", 1, 0);
  expect(parseActions(edited).value?.jobs.caller.steps?.map(step => step.id)).toEqual(["second", "first"]);
  expect(parseActions(edited).value?.jobs.original.steps?.map(step => step.id)).toEqual(["first", "second"]);
  expect(edited).toContain("Second step comment");
  expect(edited).toContain("Inline comment");
});

test("adding and removing a step preserves unrelated source and rejects invalid reordering", () => {
  const added = editActions(source, ["jobs", "original", "steps", 2], { run: "echo third" });
  const removed = editActions(added, ["jobs", "original", "steps", 2], undefined);
  expect(parseActions(removed).value?.jobs.original.steps).toHaveLength(2);
  expect(removed).toContain("# Workflow comment");
  expect(removed).toContain("*ordered # Alias comment");
  expect(() => moveActionStep(source, "original", -1, 0)).toThrow("Select a valid ordered step");
});
