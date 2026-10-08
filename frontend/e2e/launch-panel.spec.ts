import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

import type { WorkflowValue } from "../src/workflow";
import { post } from "./setup-helpers";

const longTask = "Describe the intended result and check its behavior. ".repeat(4);
const inputs: WorkflowValue["inputs"] = {
  task: { type: "string", required: true, default: longTask, description: "The result you want." },
  count: { type: "integer", default: 3, description: "How many checks to run." },
  ratio: { type: "number", default: 0.5, description: "The fraction to inspect." },
  approved: { type: "boolean", default: true, description: "Whether the work is approved." },
  mode: { type: "enum", default: "safe", constraints: { values: [1, "safe", false] }, description: "Choose the review mode." },
  optional: { type: "string", description: "An optional note." },
};

async function create(page: Page, key: string, value: Partial<WorkflowValue> = {}): Promise<void> {
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const response = await post(page, "/api/workflows", { key, holder, yaml: stringify({
    version: 1, name: key, nodes: { check: { type: "command", run: ["git", "status"] } }, ...value,
  }) });
  expect(response.ok(), await response.text()).toBeTruthy();
  await page.goto(`/?view=author&workflow=${key}.yaml`);
  await expect(page.getByRole("region", { name: "Workflow header" }).getByRole("heading", { name: key, exact: true })).toBeVisible();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
}

async function open(page: Page) {
  await page.getByRole("region", { name: "Workflow header" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await expect(panel.getByText("Runs on a new branch from", { exact: false })).toBeVisible();
  return panel;
}

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const baseline = await post(page, "/api/runs", { workflow_key: "workflow", inputs: {} });
  expect(baseline.ok(), await baseline.text()).toBeTruthy();
  const { run_id: id } = await baseline.json();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}`)).json()).run.status).toBe("succeeded");
  await page.goto("/?view=author&workflow=workflow");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
});

test("the header is reachable on a long workflow and Escape returns focus", async ({ page }) => {
  await create(page, "long-launch", { nodes: Object.fromEntries(Array.from({ length: 24 }, (_, i) => [`check_${i}`, { type: "command", run: ["git", "status"] }])) });
  const trigger = page.getByRole("region", { name: "Workflow header" }).getByRole("button", { name: "Run workflow", exact: true });
  await expect(trigger).toBeInViewport();
  const source = (await (await page.request.get("/api/projects/current")).json()).launch_source;
  const panel = await open(page);
  await expect(panel).toContainText(`Runs on a new branch from ${source.branch}.`);
  await panel.press("Escape");
  await expect(panel).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("typed defaults and descriptions stay visible and untouched inputs are omitted", async ({ page }) => {
  await create(page, "default-launch", { inputs });
  const panel = await open(page);
  await expect(panel.getByRole("textbox", { name: "Task" })).toHaveValue(longTask);
  await expect(panel.locator("textarea").first()).toBeVisible();
  await expect(panel.getByRole("spinbutton", { name: "Count" })).toHaveValue("3");
  await expect(panel.getByRole("spinbutton", { name: "Ratio" })).toHaveValue("0.5");
  await expect(panel.getByRole("checkbox", { name: "Approved" })).toBeChecked();
  await expect(panel.getByRole("combobox", { name: "Mode" })).toHaveText("safe");
  for (const definition of Object.values(inputs ?? {})) await expect(panel.getByText(definition.description ?? "", { exact: true })).toBeVisible();
  const created = page.waitForResponse((r) => r.url().endsWith("/api/runs") && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Run workflow", exact: true }).click();
  const response = await created;
  expect(response.request().postDataJSON().inputs).toEqual({});
  expect(response.status(), await response.text()).toBe(201);
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.")).toBeVisible();
});

test("edited inputs preserve JSON types and advanced options use declared start points", async ({ page }) => {
  await create(page, "typed-launch", { inputs, entrypoints: [{ scope_path: "root.check" }] });
  const panel = await open(page);
  await panel.getByRole("textbox", { name: "Task" }).fill("First line\nSecond line");
  await panel.getByRole("spinbutton", { name: "Count" }).fill("0");
  await panel.getByRole("spinbutton", { name: "Ratio" }).fill("0.25");
  await panel.getByRole("checkbox", { name: "Approved" }).uncheck();
  await panel.getByRole("combobox", { name: "Mode" }).click();
  await page.getByRole("option", { name: "false", exact: true }).click();
  await panel.getByText("Advanced options", { exact: true }).click();
  await panel.getByLabel("Override model for this run", { exact: true }).fill("m1");
  await panel.getByRole("combobox", { name: "After a successful run", exact: true }).click();
  await page.getByRole("option", { name: "Keep the working copy", exact: true }).click();
  await panel.getByRole("combobox", { name: "Start from job", exact: true }).click();
  await expect(page.getByRole("option")).toHaveCount(2);
  await page.getByRole("option", { name: "Check", exact: true }).click();
  const created = page.waitForResponse((r) => r.url().endsWith("/api/runs") && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Run workflow", exact: true }).click();
  const response = await created;
  expect(response.request().postDataJSON()).toMatchObject({
    workflow_key: "typed-launch.yaml", model: "m1", cleanup_policy: "retain", entry_point: "root.check",
    inputs: { task: "First line\nSecond line", count: 0, ratio: 0.25, approved: false, mode: false },
  });
  expect(response.status(), await response.text()).toBe(201);
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.")).toBeVisible();
  await page.getByRole("region", { name: "Workflow run history" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  const reopened = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await expect(reopened.getByRole("heading", { name: "typed-launch", exact: true })).toBeVisible();
  await expect(reopened.getByRole("textbox", { name: "Task" })).toHaveValue(longTask);
  await expect(reopened.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
});

test("unsaved workflow changes have a Save action in the panel", async ({ page }) => {
  await create(page, "save-launch");
  await page.getByRole("navigation", { name: "Workflow stage navigation" }).getByRole("button", { name: "Check", exact: true }).click();
  await page.getByLabel("Arguments (one per line)").fill("status\n--short");
  const panel = await open(page);
  await expect(panel.getByText("Save your changes first.", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
  await panel.getByRole("button", { name: "Save", exact: true }).click();
  const confirmation = page.getByRole("button", { name: "Save canonical YAML", exact: true });
  if (await confirmation.isVisible()) await confirmation.click();
  await expect(panel.getByText("Save your changes first.", { exact: true })).toBeHidden();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
  const saved = (await (await page.request.get("/api/workflows/save-launch.yaml")).json()).yaml;
  expect(saved).toContain("--short");
});

test("dirty instructions and empty or invalid workflows explain their blockers", async ({ page }) => {
  await page.getByRole("navigation", { name: "Workflow stage navigation" }).getByRole("button", { name: "Work", exact: true }).click();
  await page.getByLabel("What should the agent do?", { exact: true }).fill("Unsaved instructions");
  let panel = await open(page);
  await expect(panel.getByText("Save the job's instructions in the editor first.", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
  await panel.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByLabel("What should the agent do?", { exact: true }).fill("");
  await create(page, "empty-launch", { nodes: {} });
  panel = await open(page);
  await expect(panel.getByText("Add a job to this empty workflow before running it.", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
  await panel.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByText("Advanced workflow settings and YAML", { exact: true }).click();
  await page.locator(".cm-content").click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.insertText("nodes: [");
  await expect(page.getByRole("alert").filter({ hasText: "Flow sequence" })).toBeVisible();
  await page.getByRole("region", { name: "Workflow header" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(panel.getByText("Fix the YAML errors in the editor before running this workflow.", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
});

test("an unavailable Git source can be checked again and an unborn branch explains the required commit", async ({ page }) => {
  await create(page, "source-launch");
  await page.route("**/api/projects/current", (route) => route.fulfill({ status: 503, json: { code: "git_error", message: "Git is unavailable.", context: {} } }));
  await page.getByRole("region", { name: "Workflow header" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await expect(panel.getByText("Relay could not check the current branch. Check again before running.", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
  await page.unroute("**/api/projects/current");
  await panel.getByRole("button", { name: "Check again", exact: true }).click();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
  await panel.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.route("**/api/projects/current", (route) => route.fulfill({ json: { launch_source: { branch: "main", commit: null } } }));
  await page.getByRole("region", { name: "Workflow header" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(panel.getByText("Create the first Git commit in this project before running a workflow.", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
});

test("launch errors stay in the panel and failed requests can be retried", async ({ page }) => {
  await create(page, "failed-launch");
  await page.route("**/api/runs", (route) => route.request().method() === "POST"
    ? route.fulfill({ status: 409, json: { code: "git_dirty", message: "Commit unrelated changes before running.", context: {} } }) : route.continue());
  const panel = await open(page);
  await panel.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(panel.getByText("Commit unrelated changes before running.", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
  await page.unroute("**/api/runs");
  await panel.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(panel).toBeHidden();
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.")).toBeVisible();
});

test("file blockers and exemptions appear before launch and copied fixes leave Git unchanged", async ({ page, context }) => {
  await create(page, "file-launch");
  const before = await (await post(page, "/__test__/launch-files", { mode: "blockers" })).json();
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const panel = await open(page);
  const files = panel.getByRole("region", { name: "Launch file check" });
  await expect(files).toContainText("2 files block this run.");
  await expect(files).toContainText("README.md");
  await expect(files).toContainText("staged, modified");
  await expect(files).toContainText("untracked code.py");
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
  await files.locator("summary").first().click();
  await expect(files).toContainText("REVIEW.md");
  await expect(files).toContainText("Root workflow report");
  await expect(files).toContainText(".relay/workflows/file-launch.yaml");
  await expect(files).toContainText("Captured workflow source");
  await files.getByText("How to resolve these changes", { exact: true }).click();
  for (const command of ["git commit", "git stash -u"]) {
    await files.getByRole("button", { name: `Copy ${command}`, exact: true }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(command);
    await expect(files.getByRole("status")).toHaveText(`Copied ${command}.`);
  }
  const after = await (await post(page, "/__test__/launch-files", { mode: "inspect" })).json();
  expect(after).toEqual(before);
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  await files.getByRole("button", { name: "Check files again" }).click();
  await expect(files).toContainText("Project files are ready to run.");
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
});

test("file check failures can be refreshed and later changes still block the launch", async ({ page }) => {
  await create(page, "racing-launch");
  await page.route("**/api/workflows/racing-launch.yaml/preflight*", (route) => route.fulfill({
    status: 503, json: { code: "git_error", message: "Git file check failed.", context: {} },
  }));
  const panel = await open(page);
  const files = panel.getByRole("region", { name: "Launch file check" });
  await expect(files.getByRole("alert")).toHaveText("Git file check failed.");
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
  await page.unroute("**/api/workflows/racing-launch.yaml/preflight*");
  await files.getByRole("button", { name: "Check files again" }).click();
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
  expect((await post(page, "/__test__/launch-files", { mode: "race" })).ok()).toBeTruthy();
  const launched = page.waitForResponse((response) => response.url().endsWith("/api/runs") && response.request().method() === "POST");
  await panel.getByRole("button", { name: "Run workflow", exact: true }).click();
  const response = await launched;
  expect(response.status()).toBe(409);
  expect((await response.json()).context.changes).toBe("?? racing code.py");
  await expect(panel.getByRole("alert").filter({ hasText: "The Git worktree has code or staged changes before starting this run." })).toBeVisible();
  await files.getByRole("button", { name: "Check files again" }).click();
  await expect(files).toContainText("racing code.py");
  await expect(panel.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
});
