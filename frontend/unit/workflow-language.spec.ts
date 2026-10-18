import { expect, test } from "@playwright/test";
import { definitionAt, mappingProperties } from "../src/workflow-language";
import { manifest } from "./language-manifest";

test("definitionAt starts at the workflow root", () => {
  expect(definitionAt([], manifest)).toBe("workflow-root");
});

test("definitionAt reads a job as a job unless it uses a workflow", () => {
  expect(definitionAt(["jobs", "a"], manifest)).toBe("job-factory");
  expect(
    definitionAt(["jobs", "a"], manifest, [{}, {}, { uses: "./x.yaml" }]),
  ).toBe("workflow-job");
});

test("definitionAt chooses the step form from the step's own keys", () => {
  const path = ["jobs", "a", "steps", 0];
  expect(definitionAt(path, manifest, [{}, {}, {}, {}, { run: "echo" }])).toBe(
    "run-step",
  );
  expect(definitionAt(path, manifest, [{}, {}, {}, {}, { uses: "x" }])).toBe(
    "regular-step",
  );
  expect(definitionAt(path, manifest)).toBe("steps-item");
  const merged = mappingProperties("steps-item", manifest).map(
    (item) => item.key,
  );
  expect(merged).toEqual(expect.arrayContaining(["run", "shell", "uses"]));
  expect(new Set(merged).size).toBe(merged.length);
});

test("definitionAt follows mappings, one-of variants, and loose keys", () => {
  expect(definitionAt(["defaults", "run"], manifest)).toBe(
    "workflow-defaults-run",
  );
  expect(definitionAt(["on"], manifest)).toBe("on-mapping");
  expect(
    definitionAt(["on", "workflow_dispatch", "inputs", "task"], manifest),
  ).toBe("workflow-dispatch-input");
  expect(definitionAt(["on", "schedule", 0], manifest)).toBe("cron-mapping");
  expect(definitionAt(["jobs", "a", "unknown"], manifest)).toBeNull();
});
