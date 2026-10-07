import { expect, test, type Page } from "@playwright/test";
import { parse, stringify } from "yaml";
import { post } from "./setup-helpers";

async function document(page: Page, key = "workflow.yaml") {
  return (await page.request.get(`/api/workflows/${key}`)).json();
}
async function create(page: Page, key: string, name: string, nodes: object) {
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const response = await post(page, "/api/workflows", { key, holder, yaml: stringify({ version: 1, name, nodes }) });
  expect(response.ok(), await response.text()).toBeTruthy();
}
async function launch(page: Page, key: string): Promise<string> {
  const response = await post(page, "/api/runs", { workflow_key: key, inputs: {} });
  expect(response.ok(), await response.text()).toBeTruthy();
  const result: { run_id: string } = await response.json();
  return result.run_id;
}
async function settled(page: Page, id: string, status: string) {
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}`)).json()).run.status).toBe(status);
}

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
});

test("repair inspection and Cancel leave exact YAML untouched; Discard clears the recovery draft", async ({ page }) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  const original = await document(page);
  await page.getByRole("button", { name: "Work", exact: true }).click();
  const repairs = page.getByRole("button", { name: "Repairs", exact: true });
  const dialog = page.getByRole("dialog", { name: "Repairs for Work", exact: true });
  await repairs.click();
  await expect(dialog.getByRole("switch", { name: "Enable automatic repairs", exact: true })).not.toBeChecked();
  await expect(page.getByRole("button", { name: "Save", exact: true, includeHidden: true })).toBeDisabled();
  await dialog.press("Escape");
  await expect(repairs).toBeFocused();
  await repairs.click();
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  expect((await document(page)).draft).toEqual(original.draft);
  await repairs.click();
  await dialog.getByRole("switch", { name: "Enable automatic repairs", exact: true }).check();
  await dialog.getByLabel("Maximum repair rounds", { exact: true }).fill("5");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  expect((await document(page)).yaml).toBe(original.yaml);
  expect((await document(page)).draft).toEqual(original.draft);
  await repairs.click();
  await dialog.getByRole("switch", { name: "Enable automatic repairs", exact: true }).check();
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.getByRole("button", { name: "Discard changes", exact: true })).toBeEnabled();
  await expect.poll(async () => (await document(page)).draft?.yaml).not.toBe(original.yaml);
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();
  await expect(page.getByText("Changes discarded. The saved workflow is unchanged.", { exact: true })).toBeVisible();
  const restored = await document(page);
  expect(restored.yaml).toBe(original.yaml);
  expect(restored.base_hash).toBe(original.base_hash);
  expect(restored.draft.yaml).toBe(original.yaml);
  await page.reload();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
});

test("restoring the saved YAML also replaces a previously stored recovery draft", async ({ page }) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  const original = await document(page);
  await page.getByRole("button", { name: "Advanced workflow settings and YAML", exact: true }).click();
  const editor = page.locator(".cm-content");
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.insertText(original.yaml.replace("name:", "name: Changed #"));
  await expect.poll(async () => (await document(page)).draft?.yaml).toContain("Changed");
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.insertText(original.yaml);
  await expect.poll(async () => (await document(page)).draft?.yaml).toBe(original.yaml);
  await page.reload();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
});

test("workflow history filters persist in the URL and Back restores run and job views", async ({ page }) => {
  await create(page, "audit-a", "Audit A", { check: { type: "command", run: ["git", "status"] } });
  await create(page, "audit-b", "Audit B", { check: { type: "command", run: ["git", "status"] } });
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const id = await launch(page, "audit-a");
  await settled(page, id, "succeeded");
  await page.goto("/?view=runs&workflow=audit-a.yaml");
  await expect(page.getByRole("heading", { name: "Audit A", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Audit A", exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "Workflow sidebar" }).getByRole("button", { name: "All workflows", exact: true }).click();
  await expect(page).not.toHaveURL(/workflow=/);
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Audit A", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Global defaults", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Audit A", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Audit.a #/i }).click();
  await expect(page).toHaveURL(new RegExp(`run=${id}`));
  await page.getByRole("navigation", { name: "Jobs", exact: true }).getByRole("button", { name: /^Check / }).click();
  await expect(page).toHaveURL(/job=root/);
  await page.goBack();
  await expect(page.getByRole("region", { name: "Job log", exact: true })).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`run=${id}`));
  await page.goForward();
  await expect(page.getByRole("region", { name: "Job log", exact: true })).toBeVisible();
});

test("human reviews and unstarted jobs have accurate log labels and empty states", async ({ page }) => {
  await create(page, "audit-wait", "Audit waiting", {
    approval: { type: "human_wait", prompt: "Review the result." },
    later: { type: "command", needs: ["approval"], run: ["git", "status"] },
  });
  const id = await launch(page, "audit-wait");
  await settled(page, id, "paused_wait");
  await page.goto(`/?view=runs&run=${id}&job=root.approval`);
  const log = page.getByRole("region", { name: "Job log", exact: true });
  await expect(log.getByRole("button", { name: "Human review", exact: true })).toBeVisible();
  await expect(log.getByRole("button", { name: "Agent conversation", exact: true })).toHaveCount(0);
  await page.getByRole("navigation", { name: "Jobs", exact: true }).getByRole("button", { name: /^Later / }).click();
  await log.getByRole("button", { name: "Command output", exact: true }).click();
  await expect(log.getByText("No attempt has started yet.", { exact: true })).toBeVisible();
  await expect(log.getByText(/Incomplete/)).toHaveCount(0);
  await expect(log.getByRole("button", { name: "Retry log history", exact: true })).toHaveCount(0);
  await expect(log.getByRole("button", { name: "Stop following", exact: true })).toHaveCount(0);
  expect((await post(page, `/api/runs/${id}/cancel`, { idempotency_key: "audit-cleanup" })).ok()).toBeTruthy();
});

test("Workflow file shows frozen source; artifact downloads identify job and attempt", async ({ page }) => {
  await create(page, "audit-frozen", "Original source", { check: { type: "command", run: ["git", "status"] } });
  const id = await launch(page, "audit-frozen");
  await settled(page, id, "succeeded");
  const original = await document(page, "audit-frozen.yaml");
  const saved = await post(page, "/api/workflows/audit-frozen.yaml/save", {
    holder: await page.evaluate(() => sessionStorage.getItem("relay.editor-holder")), base_hash: original.base_hash, yaml: original.yaml.replace("Original source", "Edited source"),
  });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  await page.goto(`/?view=runs&run=${id}`);
  await page.getByRole("button", { name: "Workflow file", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Workflow file", exact: true });
  await expect(dialog.getByLabel("Captured workflow YAML", { exact: true })).toContainText("Original source");
  await expect(dialog.getByLabel("Captured workflow YAML", { exact: true })).not.toContainText("Edited source");
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.getByRole("button", { name: "Workflow file", exact: true })).toBeFocused();
  const artifacts = page.getByRole("table", { name: "Retained artifacts", exact: true });
  await expect(artifacts.getByRole("columnheader", { name: "Job", exact: true })).toBeVisible();
  await expect(artifacts.getByRole("row").filter({ hasText: "commits" })).toContainText("Check");
  await expect(artifacts.getByRole("link", { name: "Download commits, Check, attempt 1", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Workflow file", exact: true }).click();
  await dialog.getByRole("button", { name: "Edit current workflow", exact: true }).click();
  await expect(page.getByRole("region", { name: "Workflow header", exact: true })).toContainText("Edited source");
});


test("the project dialog browses isolated directories and selects a repository", async ({ page }) => {
  await page.goto("/?view=workflows");
  await page.getByRole("button", { name: "Open another project", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Open a project", exact: true });
  const browser = dialog.getByRole("region", { name: "Browse repository folders", exact: true });
  await expect(browser.getByRole("button", { name: "repo Git repository", exact: true })).toBeEnabled();
  await browser.getByRole("button", { name: "repo Git repository", exact: true }).click();
  await expect(browser.getByRole("button", { name: "Use this folder", exact: true })).toBeEnabled();
  await browser.getByRole("button", { name: "Use this folder", exact: true }).click();
  await expect(dialog.getByRole("textbox", { name: "Repository folder", exact: true })).toHaveValue(/repo$/);
  await expect(dialog.getByRole("button", { name: "Open project", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "Open project", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("region", { name: "Workflow header", exact: true })).toBeVisible();
});

for (const [type, label] of [["condition", "Check a result"], ["loop", "Repeat stages"], ["subworkflow", "Run another workflow"]] as const) {
  test(`Add a stage creates and runs a valid ${type} job`, async ({ page }) => {
    await create(page, `audit-child-${type}`, `Child for audit ${type}`, { check: { type: "command", run: ["git", "status"] } });
    const key = `audit-add-${type}`;
    await create(page, key, `Create ${type}`, { base: { type: "command", run: ["git", "status"] } });
    await page.goto(`/?view=workflows&workflow=${key}.yaml`);
    await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Add stage", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Add a stage", exact: true });
    await dialog.getByRole("textbox", { name: "Stage name", exact: true }).fill("New job");
    await dialog.getByRole("combobox", { name: "Stage action", exact: true }).click();
    await expect(page.getByRole("option")).toHaveCount(6);
    await page.getByRole("option", { name: label, exact: true }).click();
    if (type === "subworkflow") {
      await dialog.getByRole("combobox", { name: "Workflow to run", exact: true }).click();
      await page.getByRole("option", { name: `Child for audit ${type}`, exact: true }).click();
    }
    await dialog.getByRole("button", { name: "Add stage", exact: true }).click();
    if (type === "condition") {
      await expect(page.getByRole("textbox", { name: "Expression", exact: true })).toHaveValue("${{ \"true\" }}");
      await expect(page.getByRole("combobox", { name: "Next job", exact: true })).toHaveText("New job continue");
    }
    if (type === "loop") await expect(page.getByRole("textbox", { name: "Stop repeating when", exact: true })).toHaveValue("${{ loop.index >= 1 }}");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const canonical = page.getByRole("button", { name: "Save canonical YAML", exact: true });
    if (await canonical.isVisible()) await canonical.click();
    await expect(page.getByText("Workflow saved and validated.", { exact: true })).toBeVisible();
    const saved = parse((await document(page, `${key}.yaml`)).yaml);
    expect(saved.nodes.new_job.type).toBe(type);
    expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
    const id = await launch(page, key);
    await settled(page, id, "succeeded");
  });
}
