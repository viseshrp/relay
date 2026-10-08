import { expect, test, type Locator, type Page } from "@playwright/test";
import { parse, stringify } from "yaml";
import { post } from "./setup-helpers";
import type { SettingsResponse, StorageUsage } from "../src/types";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("relay.editor-holder", "layout-test"));
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});
test.afterEach(async ({ page }) => { await post(page, "/__test__/reset"); });

async function bounds(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("The control must have visible bounds.");
  return box;
}
async function containedMenu(page: Page, width: number) {
  const menu = await bounds(page.getByRole("listbox"));
  expect(menu.x).toBeGreaterThanOrEqual(0);
  expect(menu.x + menu.width).toBeLessThanOrEqual(width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
}

for (const width of [320, 390, 760, 1440]) test(`Storage distinguishes data and controls fit at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("/?view=settings");
  await expect(page.getByRole("heading", { name: "Global defaults", exact: true })).toBeVisible();
  const retries = await bounds(page.getByRole("spinbutton", { name: "Maximum automatic retries", exact: true }));
  expect(retries.width).toBeLessThanOrEqual(144);
  expect(retries.height).toBeLessThanOrEqual(40);
  const add = await bounds(page.getByRole("button", { name: "Add shared command", exact: true }));
  expect(add.width).toBeLessThan(220);
  const after = page.getByRole("combobox", { name: "After a successful run", exact: true });
  await after.click();
  await containedMenu(page, width);
  await page.getByRole("option", { name: "Merge into the active branch, then delete working copies", exact: true }).click();
  expect((await bounds(after)).height).toBeLessThanOrEqual(40);
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();
  const usage: StorageUsage = await (await page.request.get("/api/data/usage")).json();
  await page.route("**/api/runs?**", (route) => route.fulfill({ json: { runs: [], next: null } }));
  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name: "Storage", exact: true }).click();
  const storage = page.getByRole("region", { name: "Storage", exact: true });
  await expect(storage.locator(".storage-metrics dt")).toHaveText(["Working copies", "Saved reports and evidence", "Run history", "Run references"]);
  await expect(storage.locator(".storage-total")).toHaveText([`${usage.working_copies.directories} ${usage.working_copies.directories === 1 ? "folder" : "folders"}`, `${usage.artifacts} ${usage.artifacts === 1 ? "file" : "files"}`, `${usage.runs} ${usage.runs === 1 ? "run" : "runs"}`, `${usage.branches} ${usage.branches === 1 ? "branch" : "branches"}`]);
  await expect(storage.getByRole("combobox", { name: "Data to delete", exact: true })).toHaveText("Choose data to delete");
  await expect(storage.getByRole("combobox", { name: "Completed run", exact: true })).toHaveText("No completed runs");
  await expect(storage.getByRole("combobox", { name: "Completed run", exact: true })).toBeDisabled();
  const folders = storage.getByRole("region", { name: "Installation folders", exact: true });
  const paths: { paths: Record<string, string> } = await (await page.request.get("/api/settings")).json();
  await expect(folders.locator(".path-details").first()).toBeHidden();
  await folders.getByRole("button", { name: "Full path for Config", exact: true }).click();
  await expect(folders.locator(".path-details").first()).toContainText(paths.paths.config);
  await folders.getByRole("button", { name: "Full path for Config", exact: true }).press("Enter");
  await expect(folders.locator(".path-details").first()).toBeHidden();
  const deleteButton = await bounds(storage.getByRole("button", { name: "Review deletion", exact: true }));
  expect(deleteButton.width).toBeLessThan(200);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: info.outputPath(`storage-${width}.png`), fullPage: true, animations: "disabled" });
});

test("long dropdown names stay within the screen and selected labels stay compact", async ({ page }, info) => {
  const title = "Publish an independently verified feature with integration checks and a retained review report";
  expect((await post(page, "/api/workflows", { key: "long-control", holder: "layout-test", yaml: stringify({ version: 1, name: title, nodes: { check: { type: "command", run: ["git", "status"] } } }) })).ok()).toBeTruthy();
  for (const width of [320, 760, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/?view=workflows&workflow=long-control.yaml");
    const welcome = page.getByRole("region", { name: "Welcome to Relay", exact: true });
    await expect(welcome).toBeVisible();
    if (width <= 600) {
      const message = await bounds(welcome.locator(".MuiAlert-message"));
      const actions = await bounds(welcome.locator(".MuiAlert-action"));
      expect(message.width).toBeGreaterThan(180);
      expect(actions.y).toBeGreaterThanOrEqual(message.y + message.height);
    }
    const picker = page.getByRole("combobox", { name: "Workflow", exact: true });
    await expect(picker).toContainText(title);
    await picker.click();
    await containedMenu(page, width);
    await expect(page.getByRole("option", { name: title, exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`menu-${width}.png`), animations: "disabled" });
    await page.keyboard.press("Escape");
    await expect(picker).toBeFocused();
    expect((await bounds(picker)).height).toBeLessThanOrEqual(40);
    const projects = page.getByRole("combobox", { name: "Project", exact: true });
    expect((await bounds(projects)).width).toBeGreaterThanOrEqual(150);
  }
});

test("composite stage forms use the row and long command arguments remain exact", async ({ page }, info) => {
  const argv = ["git", ...Array.from({ length: 50 }, (_, index) => `argument ${index}`)];
  const source = stringify({ version: 1, name: "Command layout", nodes: { check: { type: "command", run: argv } } });
  expect((await post(page, "/api/workflows", { key: "command-layout", holder: "layout-test", yaml: source })).ok()).toBeTruthy();
  for (const width of [390, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/?view=workflows&workflow=command-layout.yaml");
    await page.getByRole("button", { name: "Check", exact: true }).click();
    const stage = page.getByRole("region", { name: "Stage settings", exact: true });
    await expect(stage.getByRole("combobox", { name: "Start after", exact: true })).toHaveText("No dependencies");
    const argumentsField = stage.getByRole("textbox", { name: "Arguments (one per line)", exact: true });
    await expect(argumentsField).toHaveValue(argv.slice(1).join("\n"));
    const area = await bounds(argumentsField);
    expect(area.height).toBeLessThan(210);
    if (width >= 1440) expect(area.width).toBeGreaterThan(600);
    await stage.getByRole("button", { name: "Advanced command arguments", exact: true }).click();
    await expect(stage.getByRole("textbox", { name: "Argument vector as JSON", exact: true })).toHaveValue(JSON.stringify(argv));
    expect(parse((await (await page.request.get("/api/workflows/command-layout")).json()).yaml).nodes.check.run).toEqual(argv);
    await page.screenshot({ path: info.outputPath(`command-${width}.png`), fullPage: true, animations: "disabled" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
});

test("empty model and repair choices explain inheritance without changing YAML", async ({ page }) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await page.getByRole("button", { name: "Work", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Model", exact: true })).toHaveText("Use workflow model");
  await page.getByRole("button", { name: "Repairs", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Repairs for Work", exact: true });
  await expect(dialog.getByRole("combobox", { name: "Agent tools", exact: true })).toHaveText("Workflow and owner preferences");
  await expect(dialog.getByRole("combobox", { name: "Model", exact: true })).toHaveText("Use workflow model");
  expect((await bounds(dialog.getByRole("spinbutton", { name: "Maximum repair rounds", exact: true }))).width).toBeLessThanOrEqual(144);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  const launch = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await launch.getByRole("button", { name: "Advanced options", exact: true }).click();
  await expect(launch.getByRole("combobox", { name: "After a successful run", exact: true })).toHaveText("Use project and global defaults");
  await expect(launch.getByRole("combobox", { name: "Start from job", exact: true })).toHaveText("Start at the beginning");
});

test("run graph headings stay above jobs and empty history filters remain readable", async ({ page }, info) => {
  const nodes = Object.fromEntries(Array.from({ length: 12 }, (_, index) => [`job_${index}`, { type: "command", run: ["git", "status"], ...(index ? { needs: [`job_${index - 1}`] } : {}) }]));
  expect((await post(page, "/api/workflows", { key: "graph-layout", holder: "layout-test", yaml: stringify({ version: 1, name: "Graph layout", nodes }) })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const launched = await post(page, "/api/runs", { workflow_key: "graph-layout", inputs: {} });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const id = (await launched.json()).run_id;
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}`)).json()).run.status).toBe("succeeded");
  await page.goto(`/?view=runs&run=${id}`);
  const graph = page.getByRole("region", { name: "Step progress", exact: true });
  const heading = await bounds(graph.getByRole("heading", { name: "graph-layout", exact: true }));
  await expect(graph.locator('.react-flow__node[data-id="root.job_0"]')).toBeVisible();
  const first = await bounds(graph.locator('.react-flow__node[data-id="root.job_0"]'));
  expect(first.y).toBeGreaterThan(heading.y + heading.height);
  await page.screenshot({ path: info.outputPath("run-graph-layout.png"), animations: "disabled" });
  await page.getByRole("region", { name: "Workflow run history", exact: true }).getByRole("button", { name: "Graph layout", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Status", exact: true })).toHaveText("All statuses");
});

test("full paths retain exact bytes and copy failures keep a selectable fallback", async ({ page }) => {
  const settings: SettingsResponse = await (await page.request.get("/api/settings")).json();
  const path = "C:\\Users\\you\\AppData\\Local\\Relay\\data";
  await page.route("**/api/settings", (route) => route.fulfill({ json: { ...settings, paths: { ...settings.paths, data: path } } }));
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (text: string) => { sessionStorage.setItem("copied-path", text); } } }));
  await page.goto("/?view=settings");
  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name: "Storage", exact: true }).click();
  const folders = page.getByRole("region", { name: "Installation folders", exact: true });
  await expect(folders.getByRole("button", { name: "Full path for Data", exact: true })).toContainText("…/Relay/data");
  await folders.getByRole("button", { name: "Full path for Data", exact: true }).click();
  await folders.getByRole("button", { name: "Copy full path for Data", exact: true }).click();
  await expect(folders.getByRole("status")).toHaveText("Path copied.");
  expect(await page.evaluate(() => sessionStorage.getItem("copied-path"))).toBe(path);
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => { throw new Error("Clipboard unavailable"); } } }));
  await folders.getByRole("button", { name: "Copy full path for Data", exact: true }).click();
  await expect(folders.getByRole("status")).toHaveText("Could not copy. Select the full path below to copy it.");
  await expect(folders.locator(".path-details code").filter({ hasText: path })).toHaveText(path);
});

test("all six stage forms remain contained on narrow and wide screens", async ({ page }, info) => {
  const forms = [
    ["Agent work", "Exact model override"], ["Run a command", "Program"],
    ["Human review", "Review instructions and expected response"],
    ["Check a result", "Expression"], ["Repeat stages", "Maximum iterations"],
    ["Run another workflow", "Workflow key"],
  ] as const;
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/?view=workflows&workflow=workflow.yaml");
    await page.getByRole("button", { name: "Work", exact: true }).click();
    const stage = page.getByRole("region", { name: "Stage settings", exact: true });
    for (const [kind, label] of forms) {
      await stage.getByRole("combobox", { name: "What this stage does", exact: true }).click();
      await containedMenu(page, width);
      await page.getByRole("option", { name: kind, exact: true }).click();
      const field = stage.getByRole(kind === "Repeat stages" ? "spinbutton" : "textbox", { name: label, exact: true });
      await expect(field).toBeVisible();
      expect((await bounds(field)).height).toBeLessThan(210);
      if (kind === "Check a result") {
        await stage.getByRole("button", { name: "Add result branch", exact: true }).click();
        await expect(stage.getByRole("textbox", { name: "Result value", exact: true })).toHaveCount(2);
        await expect(stage.getByRole("textbox", { name: "Result value", exact: true }).last()).toHaveValue("result_2");
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      await page.screenshot({ path: info.outputPath(`stage-${kind}-${width}.png`), fullPage: true, animations: "disabled" });
    }
    await stage.getByRole("button", { name: "Remove stage", exact: true }).click();
    await expect(page.getByRole("region", { name: "Stage settings", exact: true })).toHaveCount(0);
    await expect(page.getByText("Your workflow is empty. Add a command, agent task, or review step to begin.", { exact: true })).toBeVisible();
  }
});
