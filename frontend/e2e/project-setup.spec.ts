import { expect, test } from "@playwright/test";
import { post, openSettings } from "./setup-helpers";
import type { AgentsResponse, ProjectRecord } from "../src/types";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", {
    username: "owner", password: "Relay-Test-Passphrase-2026!",
  })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});

test("switching to an empty project keeps the workspace and does not reopen setup", async ({ page }, info) => {
  const created = await post(page, "/__test__/storage-project");
  expect(created.ok()).toBeTruthy();
  const { project_id: emptyId }: { project_id: string } = await created.json();
  expect((await (await page.request.get(`/api/workflows?project=${emptyId}`)).json()).workflows).toEqual([]);
  const { projects }: { projects: ProjectRecord[] } = await (await page.request.get("/api/projects")).json();
  const empty = projects.find((project) => project.id === emptyId);
  if (!empty) throw new Error("The disposable project was not registered.");
  let checks = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/agents/check") checks += 1;
  });
  await page.goto("/?view=workflows");
  const setup = page.getByRole("dialog", { name: "Get started", exact: true });
  const sidebar = page.getByRole("region", { name: "Workflow header", exact: true });
  await expect(sidebar).toBeVisible();
  await expect(setup).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Welcome to Relay", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dismiss welcome", exact: true }).click();
  const original = await sidebar.boundingBox();
  expect(original).not.toBeNull();
  await page.getByRole("combobox", { name: "Project", exact: true }).click();
  await page.getByRole("option", { name: empty.display_name, exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Project", exact: true })).toHaveText(empty.display_name);
  await expect(page.getByRole("region", { name: "Workflow header", exact: true })).toContainText("Choose a workflow");
  await expect(sidebar.getByRole("button", { name: "Create workflow", exact: true })).toBeEnabled();
  await expect(setup).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "No workflows yet", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run workflow", exact: true })).toBeDisabled();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("Editing unavailable", { exact: true })).toHaveCount(0);
  if (original) {
    const switched = await sidebar.boundingBox();
    expect(switched).toMatchObject({ x: original.x, width: original.width });
    if (switched) expect(Math.abs(switched.y - original.y)).toBeLessThanOrEqual(2);
  }
  await expect(page.getByRole("button", { name: "Dismiss welcome", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(sidebar).toBeVisible();
  await expect(page.getByRole("heading", { name: "No workflows yet", exact: true })).toBeVisible();
  await expect(setup).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Dismiss welcome", exact: true })).toHaveCount(0);
  expect(checks).toBe(0);
  await page.screenshot({ path: info.outputPath("empty-project-workspace.png"), fullPage: true });
  await page.getByRole("button", { name: /^(Help|Account menu for owner)$/ }).click();
  await page.getByRole("menuitem", { name: "Get started", exact: true }).click();
  await expect(setup.getByText(empty.display_name, { exact: true })).toBeVisible();
  await setup.getByRole("button", { name: "Close checklist", exact: true }).click();
  await expect(page.getByRole("button", { name: /^(Help|Account menu for owner)$/ })).toBeFocused();
});

test("the checklist can close before a run and reopen from settings with keyboard focus restored", async ({ page }, info) => {
  await page.goto("/?view=workflows");
  await page.getByRole("button", { name: "Get started", exact: true }).click();
  const setup = page.getByRole("dialog", { name: "Get started", exact: true });
  await expect(setup).toBeVisible();
  await expect(setup.getByRole("button", { name: "Close checklist", exact: true })).toBeEnabled();
  await setup.getByRole("button", { name: "Close checklist", exact: true }).click();
  const help = page.getByRole("button", { name: /^(Help|Account menu for owner)$/ });
  await expect(help).toBeFocused();
  await expect(setup).toHaveCount(0);
  await openSettings(page);
  await expect(page.getByRole("heading", { name: "Global defaults", exact: true })).toBeVisible();
  await help.click();
  const checked = page.waitForResponse("**/api/agents/check");
  await page.getByRole("menuitem", { name: "Get started", exact: true }).click();
  await expect(setup).toBeVisible();
  const response = await checked;
  expect(response.ok(), await response.text()).toBeTruthy();
  await expect(setup.getByRole("article", { name: "Codex", exact: true })).toContainText("Ready to connect");
  await page.screenshot({ path: info.outputPath("optional-checklist.png"), animations: "disabled" });
  await page.keyboard.press("Escape");
  await expect(setup).toHaveCount(0);
  await expect(help).toBeFocused();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Global defaults", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Dismiss welcome", exact: true })).toHaveCount(0);
});

test("a failed connection check never traps the owner in setup", async ({ page }) => {
  await page.route("**/api/agents/check", (route) => route.fulfill({
    status: 503, json: { code: "agent_protocol_error", message: "Agent checks are unavailable.", context: {} },
  }));
  await page.goto("/?view=workflows");
  await page.getByRole("button", { name: "Get started", exact: true }).click();
  const setup = page.getByRole("dialog", { name: "Get started", exact: true });
  await expect(setup.getByRole("alert").filter({ hasText: "Agent checks are unavailable." })).toBeVisible();
  await setup.getByRole("button", { name: "Close checklist", exact: true }).click();
  await expect(setup).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^(Help|Account menu for owner)$/ })).toBeFocused();
  await expect(page.getByRole("region", { name: "Workflow header", exact: true })).toBeVisible();
});

test("closing setup before inventory arrives prevents a later connection probe", async ({ page }) => {
  await page.goto("/?view=workflows");
  await expect(page.getByRole("button", { name: "Add job", exact: true })).toBeEnabled();
  const inventory: AgentsResponse = await (await page.request.get("/api/agents")).json();
  let releaseInventory: (() => void) | undefined;
  const blocked = new Promise<void>((resolve) => { releaseInventory = resolve; });
  let first = true;
  await page.route("**/api/agents", async (route) => {
    if (first) { first = false; await blocked; }
    await route.fulfill({ json: inventory });
  });
  let checks = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/agents/check") checks += 1;
  });
  const requested = page.waitForRequest("**/api/agents");
  await page.getByRole("button", { name: "Get started", exact: true }).click();
  await requested;
  const setup = page.getByRole("dialog", { name: "Get started", exact: true });
  await setup.getByRole("button", { name: "Close checklist", exact: true }).click();
  const responded = page.waitForResponse("**/api/agents");
  if (!releaseInventory) throw new Error("The inventory response could not be released.");
  releaseInventory();
  await (await responded).finished();
  await page.getByRole("button", { name: /^(Help|Account menu for owner)$/ }).click();
  const checked = page.waitForResponse("**/api/agents/check");
  await page.getByRole("menuitem", { name: "Get started", exact: true }).click();
  const response = await checked;
  expect(response.ok(), await response.text()).toBeTruthy();
  await expect(setup.getByRole("article", { name: "Codex", exact: true })).toContainText("Ready to connect");
  expect(checks).toBe(1);
});

test("editing another project acquires and renews its lease before autosaving", async ({ page }) => {
  const holder = "cross-project-editor";
  await page.addInitScript((value) => {
    sessionStorage.setItem("relay.editor-holder", value);
    const interval = window.setInterval.bind(window);
    window.setInterval = ((handler: TimerHandler, delay?: number, ...args: unknown[]) => interval(handler, delay === 30000 ? 1000 : delay, ...args)) as typeof window.setInterval;
  }, holder);
  const { project_id: projectId }: { project_id: string } = await (await post(page, "/__test__/storage-project")).json();
  const source = "name: Cross project\njobs: {main: {steps: [{run: echo original}]}}\n";
  const created = await post(page, `/api/workflows?project=${projectId}`, { key: "cross-project", holder, yaml: source });
  expect(created.status(), await created.text()).toBe(201);
  const leases: number[] = [];
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname === "/api/workflows/cross-project.yaml/lease" && url.searchParams.get("project") === projectId && response.request().method() === "POST") leases.push(response.status());
  });
  await page.goto(`/?view=workflows&project=${projectId}&workflow=cross-project.yaml`);
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Script", exact: true }).fill("echo edited");
  await expect.poll(async () => (await (await page.request.get(`/api/workflows/cross-project.yaml?project=${projectId}`)).json()).draft?.yaml).toContain("echo edited");
  await expect.poll(() => leases.length).toBeGreaterThanOrEqual(2);
  expect(leases.every((status) => status === 200)).toBeTruthy();
  expect((await (await page.request.get(`/api/workflows/cross-project.yaml?project=${projectId}`)).json()).yaml).toBe(source);
  await expect(page.getByRole("alert").filter({ hasText: /HTTP 405|Editing unavailable|lease is unavailable/ })).toHaveCount(0);
});
