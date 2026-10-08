import { expect, test } from "@playwright/test";
import { stringify } from "yaml";
import { openSettings, post } from "./setup-helpers";
import type { DashboardData } from "../src/types";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("relay.editor-holder", "dashboard-test"));
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});
test.afterEach(async ({ page }) => { await post(page, "/__test__/reset"); });

test("Home recovers when its remembered project no longer exists", async ({ page }) => {
  const { project } = await (await page.request.get("/api/projects/current")).json();
  await page.addInitScript(() => localStorage.setItem("relay.location", "?view=workflows&project=00000000-0000-4000-8000-000000000001"));
  await page.goto("/");
  await expect(page).toHaveURL(new RegExp(`view=home&project=${project.id}`));
  await expect(page.getByRole("combobox", { name: "Project", exact: true })).toContainText(project.display_name);
  await openSettings(page);
  await expect(page.getByRole("heading", { name: "Global defaults", exact: true })).toBeVisible();
  await expect(page.getByText("The requested Relay project does not exist.", { exact: true })).toHaveCount(0);
});

test("Home shows real project results and logo navigation keeps workspace drafts", async ({ page }, info) => {
  const created = await post(page, "/api/workflows", { key: "dashboard-check", holder: "dashboard-test", yaml: stringify({ version: 1, name: "Dashboard check", nodes: { check: { type: "command", run: ["git", "status"] } } }) });
  expect(created.ok(), await created.text()).toBeTruthy();
  const launch = await post(page, "/api/runs", { workflow_key: "dashboard-check", inputs: {} });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const { run_id: run } = await launch.json();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${run}`)).json()).run.status).toBe("succeeded");
  await page.goto("/");
  const home = page.getByRole("main", { name: "Relay home", exact: true });
  await expect(home.getByRole("heading", { name: "Your work at a glance", exact: true })).toBeVisible();
  await expect(home.getByRole("region", { name: "Recent results", exact: true })).toContainText("Dashboard check");
  await expect(page.getByRole("tab", { name: "Settings", exact: true })).toHaveCount(0);
  await expect(page.getByText("Login disabled", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("dashboard.png"), fullPage: true, animations: "disabled" });
  await home.getByRole("region", { name: "Recent results", exact: true }).getByRole("button", { name: /^Dashboard check/ }).click();
  await expect(page).toHaveURL(new RegExp(`run=${run}`));
  await expect(page.locator(".run-header")).toContainText("Dashboard check");
  await page.getByRole("link", { name: "Relay home", exact: true }).click();
  await expect(home).toBeVisible();
  await page.getByRole("tab", { name: "Workflows", exact: true }).click();
  await page.getByRole("navigation", { name: "Workflow sidebar", exact: true }).getByRole("button", { name: "Dashboard check", exact: true }).click();
  await page.getByRole("button", { name: "Advanced workflow settings and YAML", exact: true }).click();
  const yaml = page.getByLabel("Workflow YAML editor", { exact: true }).locator(".cm-content");
  const changed = stringify({ version: 1, name: "Remember this draft", nodes: { check: { type: "command", run: ["git", "status"] } } });
  await expect(page.getByRole("region", { name: "Workflow header" })).toContainText("Dashboard check");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  await yaml.fill(changed);
  await page.getByRole("link", { name: "Relay home", exact: true }).click();
  await expect(home).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("region", { name: "Workflow header" })).toContainText("Remember this draft");
  await page.getByRole("button", { name: "Advanced workflow settings and YAML", exact: true }).click();
  await expect(yaml).toContainText("Remember this draft");
  await openSettings(page);
  await expect(page.getByRole("heading", { name: "Global defaults", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Account menu for owner", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "Welcome slides", exact: true })).toBeVisible();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
});

test("waiting cards open the exact human request and disappear after an answer", async ({ page }) => {
  expect((await post(page, "/api/workflows", { key: "dashboard-review", holder: "dashboard-review", yaml: stringify({ version: 1, name: "Review the change", nodes: { review: { type: "human_wait", prompt: "Review the change" } } }) })).ok()).toBeTruthy();
  const response = await post(page, "/api/runs", { workflow_key: "dashboard-review", inputs: {} });
  expect(response.ok(), await response.text()).toBeTruthy();
  const { run_id: id } = await response.json();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}?collection=interactions&pending=true`)).json()).run.interactions.length).toBe(1);
  await page.goto("/");
  const waiting = page.getByRole("region", { name: "Waiting for you", exact: true });
  const row = waiting.locator(".dashboard-run").filter({ hasText: "Review the change" });
  await expect(row.getByRole("button", { name: "Open request", exact: true })).toBeVisible();
  await row.getByRole("button", { name: "Open request", exact: true }).click();
  await expect(page).toHaveURL(/interaction=/);
  await expect(page.getByRole("heading", { name: "Your review is needed", exact: true })).toBeVisible();
  await page.getByLabel("Your response", { exact: true }).fill("Approved");
  await page.getByRole("button", { name: "Send response and continue", exact: true }).click();
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Relay home", exact: true }).click();
  await expect(waiting).not.toContainText("Review the change");
});

test("refresh failure retains results and hidden tabs do not poll", async ({ page }) => {
  await page.clock.install();
  await page.goto("/");
  const home = page.getByRole("main", { name: "Relay home", exact: true });
  await expect(home.getByRole("heading", { name: "Your projects", exact: true })).toBeVisible();
  await page.route("**/api/dashboard?*", (route) => route.fulfill({ status: 503, json: { code: "persistence_error", message: "Temporary read failure.", context: {} } }));
  await home.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(home.getByRole("alert")).toContainText("Showing the last successful refresh");
  await expect(home.getByRole("heading", { name: "Your projects", exact: true })).toBeVisible();
  await page.unroute("**/api/dashboard?*");
  await home.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(home.getByRole("alert")).toHaveCount(0);
  let requests = 0;
  page.on("request", (request) => { if (request.url().includes("/api/dashboard")) requests++; });
  await page.evaluate(() => Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true }));
  await page.clock.fastForward(15000);
  expect(requests).toBe(0);
  await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true }); document.dispatchEvent(new Event("visibilitychange")); });
  await expect.poll(() => requests).toBe(1);
});


test("compact recent results reveal loaded records and still page to older runs", async ({ page }) => {
  const launched = await post(page, "/api/runs", { workflow_key: "workflow.yaml", inputs: {} });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const body: { run_id: string } = await launched.json();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${body.run_id}`)).json()).run.status).toBe("succeeded");
  const data: DashboardData = await (await page.request.get("/api/dashboard")).json();
  const record = data.recent.items[0];
  if (!record) throw new Error("The completed fixture run must appear on Home.");
  await page.route("**/api/dashboard?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    expect(query.get("limit")).toBe("10");
    const older = query.has("cursor");
    return route.fulfill({ json: { ...data, recent: { items: Array.from({ length: older ? 1 : 10 }, (_, index) => {
      const number = older ? 11 : index + 1;
      return { ...record, id: `result-${number}`, number, title: `Completed result ${number}` };
    }), next_cursor: older ? null : "older-results" } } });
  });
  await page.goto("/?view=home");
  const results = page.getByRole("region", { name: "Recent results", exact: true });
  const rows = results.getByRole("button", { name: /^Completed result / });
  await expect(rows).toHaveCount(5);
  await results.getByRole("button", { name: "Show more recent results", exact: true }).click();
  await expect(rows).toHaveCount(10);
  await results.getByRole("button", { name: "Show more recent results", exact: true }).click();
  await expect(rows).toHaveCount(11);
  await expect(results.getByRole("button", { name: /^Completed result 11/ })).toBeVisible();
  await expect(results.getByRole("button", { name: "Show more recent results", exact: true })).toHaveCount(0);
});
