import { expect, test, type Page } from "@playwright/test";
import { parse } from "yaml";

async function post(page: Page, path: string, body: object = {}) {
  const cookie = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  return page.request.post(path, { data: body, headers: { "X-CSRFToken": cookie?.value ?? "" } });
}

async function workflow(page: Page) {
  const response = await page.request.get("/api/workflows/workflow");
  expect(response.ok()).toBeTruthy();
  return parse((await response.json()).yaml);
}

async function save(page: Page) {
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const confirmation = page.getByRole("button", { name: "Save canonical YAML", exact: true });
  if (await confirmation.isVisible()) await confirmation.click();
  await expect(page.getByText("Workflow saved and validated.")).toBeVisible();
}

async function choose(page: Page, tool: string, label: string, value: string) {
  const region = page.getByRole("region", { name: `${tool} configuration` });
  await region.getByRole("combobox", { name: label, exact: true }).click();
  await page.getByRole("option", { name: value, exact: true }).click();
}

async function launch(page: Page) {
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const created = page.waitForResponse((response) => response.url().endsWith("/api/runs") && response.request().method() === "POST");
  await page.getByRole("region", { name: "Workflow header" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  await page.getByRole("dialog", { name: "Run workflow" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const { run_id: runId } = await response.json();
  await expect.poll(async () => {
    const detail = await page.request.get(`/api/runs/${runId}`);
    return (await detail.json()).run.status;
  }).toBe("succeeded");
  const events = await page.request.get(`/api/runs/${runId}/events`);
  return (await events.json()).events;
}

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  const login = await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" });
  expect(login.status()).toBe(200);
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await page.locator(".react-flow__node").filter({ hasText: "work" }).click();
  await page.getByRole("combobox", { name: "Agent", exact: true }).click();
  await page.getByRole("option", { name: "Codex", exact: true }).click();
  await expect(page.getByRole("region", { name: "Codex configuration" }).getByRole("combobox", { name: "Effort", exact: true })).toBeEnabled();
});

test("provider defaults remain absent and reach the worker unchanged", async ({ page }) => {
  for (const tool of ["Codex"]) {
    const region = page.getByRole("region", { name: `${tool} configuration` });
    await expect(region.getByRole("combobox", { name: "Effort", exact: true })).toHaveText("Provider default");
    await expect(region.getByRole("combobox", { name: "Permission mode", exact: true })).toHaveCount(0);
  }
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBeUndefined();
  const events = await launch(page);
  expect(events.some((event: { payload: { text?: string } }) => event.payload.text === "config: model=m1;effort=high;mode=ask")).toBeTruthy();
});

test("explicit effort choices survive save, reload, and execution", async ({ page }, testInfo) => {
  await choose(page, "Codex", "Effort", "Low");
  await save(page);
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBe("low");
  await page.reload();
  await page.locator(".react-flow__node").filter({ hasText: "work" }).click();
  await expect(page.getByRole("region", { name: "Codex configuration" }).getByRole("combobox", { name: "Effort", exact: true })).toHaveText("Low");
  await page.screenshot({ path: testInfo.outputPath("agent-configuration.png"), fullPage: true });
  const events = await launch(page);
  expect(events.some((event: { payload: { text?: string } }) => event.payload.text === "config: model=m1;effort=low;mode=ask")).toBeTruthy();
});

test("tools without an effort selector show provider default without an override", async ({ page }) => {
  await page.route("**/api/agents/codex/configuration", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, effort: null } });
  });
  await page.getByLabel("Exact model override", { exact: true }).fill("m2");
  const region = page.getByRole("region", { name: "Codex configuration" });
  await expect(region.getByText("This tool does not expose a separate effort selector.")).toBeVisible();
  await expect(region.getByRole("combobox", { name: "Effort", exact: true })).toHaveText("Provider default");
  await expect(region.getByRole("combobox", { name: "Effort", exact: true })).toBeDisabled();
  await save(page);
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBeUndefined();
});

test("returning to provider default removes the saved overrides", async ({ page }) => {
  await choose(page, "Codex", "Effort", "Low");
  await choose(page, "Codex", "Effort", "Provider default");
  await save(page);
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBeUndefined();
  const events = await launch(page);
  expect(events.some((event: { payload: { text?: string } }) => event.payload.text === "config: model=m1;effort=high;mode=ask")).toBeTruthy();
});

test("changing the model refreshes its choices and resets effort", async ({ page }) => {
  await choose(page, "Codex", "Effort", "High");
  await page.getByLabel("Exact model override", { exact: true }).fill("m2");
  const effort = page.getByRole("region", { name: "Codex configuration" }).getByRole("combobox", { name: "Effort", exact: true });
  await expect(effort).toBeEnabled();
  await expect(effort).toHaveText("Provider default");
  await effort.click();
  await expect(page.getByRole("option", { name: "Medium", exact: true })).toBeVisible();
  await expect(page.getByRole("option", { name: "High", exact: true })).toHaveCount(0);
  await page.getByRole("option", { name: "Medium", exact: true }).click();
  await save(page);
  const events = await launch(page);
  expect(events.some((event: { payload: { text?: string } }) => event.payload.text === "config: model=m2;effort=medium;mode=ask")).toBeTruthy();
});

test("failed capability reads offer retry without writing an override", async ({ page }) => {
  await page.route("**/api/agents/codex/configuration", (route) => route.fulfill({ status: 502, json: { code: "agent_protocol_error", message: "Probe failed.", context: {} } }));
  await page.getByLabel("Exact model override", { exact: true }).fill("m2");
  const region = page.getByRole("region", { name: "Codex configuration" });
  await expect(region.getByText("Probe failed.")).toBeVisible();
  await page.unroute("**/api/agents/codex/configuration");
  await region.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(region.getByRole("combobox", { name: "Effort", exact: true })).toBeEnabled();
  await expect(region.getByRole("combobox", { name: "Effort", exact: true })).toHaveText("Provider default");
  await save(page);
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBeUndefined();
});
