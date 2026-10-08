import { expect, test } from "@playwright/test";
import { post, openSettings, currentWorkflow } from "./setup-helpers";
import { stringify } from "yaml";

test.use({ storageState: { cookies: [], origins: [] } });
test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});
test.afterEach(async ({ page }) => { await post(page, "/__test__/reset"); });

test("welcome navigation and keyboard controls introduce features, then a skipped tour stays dismissed", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1100, height: 800 });
  await page.goto("/");
  const welcome = page.getByRole("dialog", { name: "Welcome to Relay", exact: true });
  await expect(welcome).toBeVisible();
  await expect(welcome.getByRole("img", { name: /Repository folder is highlighted/ })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("welcome.png") });
  const image = await welcome.getByRole("img", { name: /Repository folder is highlighted/ }).boundingBox();
  if (!image) throw new Error("Expected a visible welcome illustration.");
  await page.mouse.move(image.x + image.width * 0.85, image.y + image.height / 2);
  await page.mouse.down();
  await page.mouse.move(image.x + image.width * 0.15, image.y + image.height / 2, { steps: 15 });
  await page.mouse.up();
  await expect(welcome.getByRole("status")).toHaveText("Slide 2 of 4");
  await welcome.getByRole("button", { name: "Next", exact: true }).press("ArrowRight");
  await expect(welcome.getByRole("status")).toHaveText("Slide 3 of 4");
  await welcome.getByRole("button", { name: /^Show slide 4/ }).click();
  await expect(welcome.getByRole("heading", { name: "Make Relay your own" })).toBeVisible();
  await welcome.getByRole("button", { name: "Show guided tour", exact: true }).click();
  const tour = page.locator(".relay-tour");
  await expect(tour).toBeVisible();
  await expect(tour).toContainText("Projects");
  await page.screenshot({ path: testInfo.outputPath("guided-tour.png") });
  await tour.getByRole("button", { name: "Skip tour", exact: true }).click();
  await expect(tour).toBeHidden();
  await expect(page.getByRole("button", { name: /^(Help|Account menu for owner)$/ })).toBeFocused();
  await page.reload();
  await expect(page.getByRole("main", { name: "Relay home", exact: true })).toBeVisible();
  await expect(welcome).toHaveCount(0);
  await expect(tour).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Welcome to Relay", exact: true })).toHaveCount(0);
});

test("the full spotlight tour reaches each settings control without changing saved defaults", async ({ page }) => {
  const initial = await (await page.request.get("/api/settings")).json();
  const configured = await post(page, "/api/settings", { revision: initial.revision, settings: { ...initial.settings, workflow_defaults: { ...initial.settings.workflow_defaults, providers: { codex: { model: "m1", effort: "high" } } } } });
  expect(configured.ok(), await configured.text()).toBeTruthy();
  const before = await configured.json();
  const mutations: string[] = [];
  page.on("request", (request) => { if (request.method() === "POST" && /\/api\/(settings|runs|projects\/defaults|agents\/.*configuration)/.test(request.url())) mutations.push(request.url()); });
  await page.goto("/?view=workflows");
  await page.getByRole("button", { name: "Skip introduction", exact: true }).click();
  const tour = page.locator(".relay-tour");
  const titles = ["Projects", "Workflows", "Runs", "Default agent order", "Shared default model", "Agent models and thinking", "Thinking effort", "Agent permissions", "Shared commands", "Environment variables", "Job timeout", "Automatic job retries", "Automatic recovery", "Maximum automatic retries", "After a successful run", "New repair rules", "Maximum repair rounds", "Fixer instructions", "Verifier instructions", "Project overrides", "Require login", "Loopback address", "Port", "Workers", "Desktop notifications", "Storage", "Welcome and guided tour"];
  for (const [index, title] of titles.entries()) {
    await expect(tour.locator(".driver-popover-title")).toHaveText(title);
    await expect(tour.locator(".driver-popover-progress-text")).toHaveText(`${index + 1} of ${titles.length}`);
    await expect(page.locator(".driver-active-element")).not.toHaveAttribute("id", "driver-dummy-element");
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest(".relay-tour")))).toBeTruthy();
    await tour.getByRole("button", { name: index === titles.length - 1 ? "Finish" : "Next", exact: true }).click();
  }
  await expect(tour).toBeHidden();
  await expect(page.getByRole("region", { name: "Workflow header" })).toBeVisible();
  expect(mutations).toEqual([]);
  expect((await (await page.request.get("/api/settings")).json()).revision).toBe(before.revision);
});

test("onboarding can replay separately and reset from Settings, with Escape remembered", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("dialog", { name: "Welcome to Relay", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".relay-tour")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".relay-tour")).toBeHidden();
  await openSettings(page);
  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name: "Welcome and guided tour", exact: true }).click();
  await page.getByRole("button", { name: "Replay welcome slides", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Welcome to Relay", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Skip introduction", exact: true }).click();
  await expect(page.locator(".relay-tour")).toHaveCount(0);
  await page.getByRole("button", { name: "Replay guided tour", exact: true }).click();
  await page.locator(".relay-tour").getByRole("button", { name: "Skip tour", exact: true }).click();
  await page.getByRole("button", { name: "Reset onboarding", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Onboarding reset." })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("dialog", { name: "Welcome to Relay", exact: true })).toBeVisible();
});

test("no projects shows a usable home and still offers global settings and onboarding", async ({ page }, testInfo) => {
  await page.route("**/api/projects/current", (route) => route.fulfill({ status: 404, json: { code: "project_not_found", message: "No project is open.", context: {} } }));
  await page.route("**/api/projects", (route) => route.fulfill({ json: { projects: [] } }));
  await page.route("**/api/dashboard?*", (route) => route.fulfill({ json: { counts: { projects: 0, waiting: 0, unfinished: 0, paused: 0 }, ...Object.fromEntries(["projects", "waiting", "active", "recent"].map((key) => [key, { items: [], next_cursor: null }])) } }));
  await page.goto("/");
  await page.getByRole("button", { name: "Skip introduction", exact: true }).click();
  await page.locator(".relay-tour").getByRole("button", { name: "Skip tour", exact: true }).click();
  const home = page.getByRole("region", { name: "Start using Relay", exact: true });
  await expect(home).toContainText("One working agent is enough");
  await page.screenshot({ path: testInfo.outputPath("no-project-home.png"), fullPage: true });
  await expect(page.getByRole("combobox", { name: "Project", exact: true })).toHaveCount(0);
  await home.getByRole("button", { name: "Open your first project", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Open a project", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await openSettings(page);
  await expect(page.getByRole("heading", { name: "Global defaults", exact: true })).toBeVisible();
});

test("touch-sized help works for disabled settings and closes with Escape without changing values", async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem("relay.welcome-seen", "true"); localStorage.setItem("relay.tour-seen", "true"); });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?view=settings");
  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name: "Project defaults", exact: true }).click();
  const about = page.getByRole("button", { name: "About Job timeout", exact: true });
  await expect(page.getByRole("textbox", { name: "Job timeout", exact: true })).toBeDisabled();
  await about.click();
  await expect(page.getByRole("tooltip")).toContainText("Human review deadlines");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toBeHidden();
  await expect(about).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("long workflow names fit the header and settings never overlap their save controls", async ({ page }, testInfo) => {
  await page.addInitScript(() => { localStorage.setItem("relay.welcome-seen", "true"); localStorage.setItem("relay.tour-seen", "true"); localStorage.setItem("relay.setup-dismissed", "true"); });
  await page.goto("/?view=workflows");
  await expect(page.getByRole("button", { name: "Add job", exact: true })).toBeEnabled();
  const name = "Automatic tab suspension: fresh build without size caps and independently verified results";
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const created = await post(page, "/api/workflows", { key: "long.yaml", holder, yaml: stringify(currentWorkflow({ version: 1, name, nodes: { test: { type: "command", run: ["python3", "-V"] } } })) });
  expect(created.ok(), await created.text()).toBeTruthy();
  await page.goto("/?view=workflows&workflow=long.yaml");
  const sidebar = page.getByRole("region", { name: "Workflow header" });
  const long = sidebar.getByRole("heading", { name, exact: true });
  await expect(long).toBeVisible();
  const icon = await sidebar.getByRole("combobox", { name: "Workflow", exact: true }).locator("..").locator("svg").boundingBox();
  expect(icon?.width).toBeGreaterThanOrEqual(18);
  const headerBox = await sidebar.boundingBox(); const titleBox = await long.boundingBox();
  if (!headerBox || !titleBox) throw new Error("Expected a visible workflow header.");
  expect(titleBox.x + titleBox.width).toBeLessThanOrEqual(headerBox.x + headerBox.width + 1);
  await long.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("workflow-sidebar.png") });
  await openSettings(page);
  const retries = await page.getByRole("switch", { name: "Automatic recovery for new runs", exact: true }).locator("..", { has: page.locator("input") }).boundingBox();
  const limit = await page.getByRole("spinbutton", { name: "Maximum automatic retries", exact: true }).boundingBox();
  if (!retries || !limit) throw new Error("Expected recovery controls to have layout boxes.");
  expect(limit.y - (retries.y + retries.height)).toBeGreaterThanOrEqual(12);
  await page.getByRole("button", { name: "Defaults for new repair rules", exact: true }).click();
  await expect.poll(async () => {
    const verifier = await page.getByRole("textbox", { name: "Verifier instructions", exact: true }).boundingBox();
    const save = await page.getByRole("button", { name: "Save global settings", exact: true }).boundingBox();
    return !!verifier && !!save && save.y > verifier.y + verifier.height;
  }).toBeTruthy();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("settings-spacing.png"), fullPage: true });
});

test("mobile welcome and tour remain usable and replay slides can start the tour again", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const welcome = page.getByRole("dialog", { name: "Welcome to Relay", exact: true });
  await expect(welcome).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await welcome.getByRole("button", { name: "Skip introduction", exact: true }).click();
  const tour = page.locator(".relay-tour");
  await tour.getByRole("button", { name: "Next", exact: true }).click();
  await expect(tour).toContainText("Workflows");
  await tour.getByRole("button", { name: "Back", exact: true }).click();
  await expect(tour.locator(".driver-popover-title")).toHaveText("Projects");
  const box = await tour.boundingBox();
  if (!box) throw new Error("Expected a visible tour popover.");
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(390);
  await tour.getByRole("button", { name: "Skip tour", exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.getByRole("button", { name: /^(Help|Account menu for owner)$/ }).click();
  await page.getByRole("menuitem", { name: "Welcome slides", exact: true }).click();
  await welcome.getByRole("button", { name: /^Show slide 4/ }).click();
  await welcome.getByRole("button", { name: "Show guided tour", exact: true }).click();
  await expect(tour).toBeVisible();
});

test("an unavailable workspace bundle offers explicit reload instead of a blank page", async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem("relay.welcome-seen", "true"); localStorage.setItem("relay.tour-seen", "true"); });
  await page.route("**/WorkflowWorkspace-*.js", (route) => route.abort());
  await page.goto("/?view=settings");
  await expect(page.getByRole("heading", { name: "Global defaults", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Workflows", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Relay could not open this workspace." })).toBeVisible();
  await page.unroute("**/WorkflowWorkspace-*.js");
  await page.getByRole("button", { name: "Reload Relay", exact: true }).click();
  await expect(page.getByRole("button", { name: "Add job", exact: true })).toBeEnabled();
});

test("blocked browser storage allows dismissal and explains why reset cannot persist", async ({ page }) => {
  await page.addInitScript(() => {
    const keys = ["relay.welcome-seen", "relay.tour-seen"];
    const read = Storage.prototype.getItem, write = Storage.prototype.setItem, remove = Storage.prototype.removeItem;
    const check = (key: string): void => { if (keys.includes(key)) throw new DOMException("Storage is blocked", "SecurityError"); };
    Object.defineProperties(Storage.prototype, {
      getItem: { value: function (this: Storage, key: string): string | null { check(key); return read.call(this, key); } },
      setItem: { value: function (this: Storage, key: string, value: string): void { check(key); write.call(this, key, value); } },
      removeItem: { value: function (this: Storage, key: string): void { check(key); remove.call(this, key); } },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Skip introduction", exact: true }).click();
  await page.locator(".relay-tour").getByRole("button", { name: "Skip tour", exact: true }).click();
  await openSettings(page);
  await page.getByRole("button", { name: "Welcome and guided tour", exact: true }).click();
  await page.getByRole("button", { name: "Reset onboarding", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("This browser cannot save onboarding preferences");
  await expect(page.getByRole("dialog", { name: "Welcome to Relay", exact: true })).toHaveCount(0);
});
