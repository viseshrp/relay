import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";
import { runActions } from "../src/components/RunActions";
import { historicalPost as post, currentWorkflow } from "./setup-helpers";

async function launch(page: Page, key: string, value: object, inputs: object = {}): Promise<string> {
  const created = await post(page, "/api/workflows", { key, holder: `actions-${key}`, yaml: stringify({ version: 1, name: key, ...value }) });
  expect(created.ok(), await created.text()).toBeTruthy();
  const response = await post(page, "/api/runs", { workflow_key: key, inputs });
  expect(response.ok(), await response.text()).toBeTruthy();
  const result: { run_id: string } = await response.json();
  return result.run_id;
}

async function settled(page: Page, id: string, status: string): Promise<void> {
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}`)).json()).run.status).toBe(status);
}

test("actions follow every durable run state", () => {
  for (const status of ["running", "paused_wait"]) expect(runActions(status)).toEqual({ pause: true, cancel: true, rerunAll: false, rerunFailed: false });
  expect(runActions("pending")).toEqual({ pause: true, cancel: false, rerunAll: false, rerunFailed: false });
  expect(runActions("failed")).toEqual({ pause: false, cancel: false, rerunAll: true, rerunFailed: true });
  for (const status of ["succeeded", "canceled"]) expect(runActions(status)).toEqual({ pause: false, cancel: false, rerunAll: true, rerunFailed: false });
  for (const status of ["canceling", "interrupted", "unknown"]) expect(runActions(status)).toEqual({ pause: false, cancel: false, rerunAll: false, rerunFailed: false });
});

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});

test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: "wait" }); });

test("Pause, Resume, and Cancel run work from the job log and finished controls disappear", async ({ page }) => {
  const id = await launch(page, "active-actions", { nodes: { approval: { type: "human_wait", prompt: "Approve this change." } } });
  await settled(page, id, "paused_wait");
  await page.goto(`/?view=runs&run=${id}&job=root.approval`);
  await expect(page.getByRole("region", { name: "Job log" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Re-run jobs", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(page.getByRole("button", { name: "Resume", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Resume", exact: true }).click();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
  const cancel = page.getByRole("button", { name: "Cancel run", exact: true });
  await cancel.click();
  const dialog = page.getByRole("dialog", { name: "Cancel this run?" });
  await dialog.getByRole("button", { name: "Keep working", exact: true }).click();
  await expect(cancel).toBeFocused();
  await cancel.click();
  await dialog.getByRole("button", { name: "Cancel run", exact: true }).click();
  await settled(page, id, "canceled");
  await expect(page.getByRole("button", { name: "Cancel run", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Re-run jobs", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Re-run job", exact: true })).toHaveCount(0);
});

test("Re-run all jobs prefills previous values and creates a fresh run from edited source", async ({ page }) => {
  const definition = { inputs: { task: { type: "string", default: "Initial default" }, approved: { type: "boolean", default: true }, count: { type: "integer", default: 5 } }, nodes: { check: { type: "command", run: ["git", "status"] } } };
  const id = await launch(page, "repeat-actions", definition, { task: "Previous task", approved: false, count: 0 });
  await settled(page, id, "succeeded");
  const before = (await (await page.request.get(`/api/runs/${id}`)).json()).run;
  expect((await post(page, "/api/workflows/repeat-actions.yaml/lease", { holder: "actions-repeat-actions" })).ok()).toBeTruthy();
  const document = await page.request.get("/api/workflows/repeat-actions.yaml");
  const saved = await post(page, "/api/workflows/repeat-actions.yaml/save", { holder: "actions-repeat-actions", base_hash: (await document.json()).base_hash,
    yaml: stringify(currentWorkflow({ version: 1, name: "Updated source", ...definition, nodes: { updated: { type: "command", run: ["git", "status", "--short"] } } })) });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  await page.goto(`/?view=runs&run=${id}`);
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel run", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Re-run jobs", exact: true }).click();
  await page.getByRole("menuitem", { name: "Re-run all jobs", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await expect(panel.getByRole("heading", { name: "Updated source", exact: true })).toBeVisible();
  await expect(panel.getByRole("textbox", { name: "Task" })).toHaveValue("Previous task");
  await expect(panel.getByRole("checkbox", { name: "Approved" })).not.toBeChecked();
  await expect(panel.getByRole("spinbutton", { name: "Count" })).toHaveValue("0");
  await panel.press("Escape");
  await expect(panel).toBeHidden();
  await expect(page.getByRole("button", { name: "Re-run jobs", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Re-run jobs", exact: true }).click();
  await page.getByRole("menuitem", { name: "Re-run all jobs", exact: true }).click();
  await expect(panel.getByRole("textbox", { name: "Task" })).toHaveValue("Previous task");
  const created = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/runs" && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Run workflow", exact: true }).click();
  const response = await created;
  expect(response.status(), await response.text()).toBe(201);
  expect(response.request().postDataJSON().inputs).toEqual({ task: "Previous task", approved: false, count: 0 });
  const { run_id: next } = await response.json();
  expect(next).not.toBe(id);
  await settled(page, next, "succeeded");
  const after = (await (await page.request.get(`/api/runs/${next}`)).json()).run;
  expect(after.nodes.filter((job: { parent_scope: string | null }) => job.parent_scope === null).map((job: { node_id: string }) => job.node_id)).toEqual(["updated"]);
  expect(after.snapshot).not.toEqual(before.snapshot);
  expect((await (await page.request.get(`/api/runs/${id}`)).json()).run.snapshot).toEqual(before.snapshot);
});

test("failed runs hide pause and cancel, and per-job retry appears only in the job log", async ({ page }) => {
  const id = await launch(page, "failed-actions", { nodes: { check: { type: "command", run: ["git", "relay-no-such-command"] } } });
  await settled(page, id, "failed");
  await page.goto(`/?view=runs&run=${id}`);
  await expect(page.getByRole("button", { name: "Re-run jobs", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel run", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Re-run job", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Open job log", exact: true }).click();
  await page.getByRole("button", { name: "Re-run job", exact: true }).click();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}/job?job=root.check`)).json()).job.latest_attempt?.number).toBe(2);
  await settled(page, id, "failed");
});

test("a stale re-run request shows an error and creates no run", async ({ page }) => {
  const id = await launch(page, "stale-actions", { nodes: { check: { type: "command", run: ["git", "status"] } } });
  await settled(page, id, "succeeded");
  await page.goto(`/?view=runs&run=${id}`);
  await page.route(`**/api/runs/${id}/launch-inputs`, (route) => route.fulfill({ status: 400, json: { code: "config_error", message: "Wait for this run to finish before running all jobs again.", context: {} } }));
  const before = (await (await page.request.get("/api/runs")).json()).runs.length;
  await page.getByRole("button", { name: "Re-run jobs", exact: true }).click();
  await page.getByRole("menuitem", { name: "Re-run all jobs", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Wait for this run to finish before running all jobs again.");
  await expect(page.getByRole("dialog", { name: "Run workflow", exact: true })).toHaveCount(0);
  expect((await (await page.request.get("/api/runs")).json()).runs.length).toBe(before);
});

test("switching runs while repeat options load drops the previous request", async ({ page }) => {
  const definition = { nodes: { check: { type: "command", run: ["git", "status"] } } };
  const first = await launch(page, "pending-options", definition);
  await settled(page, first, "succeeded");
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const other = await launch(page, "other-actions", definition);
  await settled(page, other, "succeeded");
  await page.goto(`/?view=runs&run=${first}`);
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route(`**/api/runs/${first}/launch-inputs`, async (route) => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  try {
    const requested = page.waitForRequest(`**/api/runs/${first}/launch-inputs`);
    await page.getByRole("button", { name: "Re-run jobs", exact: true }).click();
    await page.getByRole("menuitem", { name: "Re-run all jobs", exact: true }).click();
    await requested;
    await page.getByRole("button", { name: "Run history", exact: true }).click();
    await page.getByRole("button", { name: /^other-actions #/ }).click();
    await expect(page).toHaveURL(new RegExp(`run=${other}`));
  } finally { release?.(); }
  await page.unrouteAll({ behavior: "wait" });
  await expect(page.getByRole("dialog", { name: "Run workflow", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Re-run jobs", exact: true })).toBeEnabled();
});
