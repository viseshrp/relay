import { expect, test, type Page } from "./a11y-test";
import { parse } from "yaml";
import {
  chooseAgent,
  closeJobSettings,
  expectRunStatus,
  openJobSettings,
} from "./setup-helpers";

async function post(page: Page, path: string, body: object = {}) {
  const cookie = (await page.context().cookies()).find(
    (item) => item.name === "relay_csrftoken",
  );
  return page.request.post(path, {
    data: body,
    headers: { "X-CSRFToken": cookie?.value ?? "" },
  });
}

async function workflow(page: Page) {
  const response = await page.request.get("/api/workflows/workflow");
  expect(response.ok()).toBeTruthy();
  return parse((await response.json()).yaml);
}

async function save(page: Page) {
  await closeJobSettings(page);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const confirmation = page.getByRole("button", {
    name: "Save canonical YAML",
    exact: true,
  });
  if (await confirmation.isVisible()) await confirmation.click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
}

async function choose(page: Page, tool: string, label: string, value: string) {
  const region = page.getByRole("region", { name: `${tool} configuration` });
  await region.getByRole("combobox", { name: label, exact: true }).click();
  await page.getByRole("option", { name: value, exact: true }).click();
}

async function launch(page: Page) {
  await closeJobSettings(page);
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("region", { name: "Workflow header" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Run workflow" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const response = await created;
  expect(response.status()).toBe(201);
  const { run_id: runId } = await response.json();
  await expectRunStatus(page, runId, "succeeded");
  const events = await page.request.get(`/api/runs/${runId}/events`);
  return (await events.json()).events;
}

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  const login = await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  expect(login.status()).toBe(200);
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await page.locator(".react-flow__node").filter({ hasText: "work" }).click();
  await page.getByRole("tab", { name: "Steps", exact: true }).click();
  await chooseAgent(page, "Codex");
  await expect(
    page
      .getByRole("region", { name: "Codex configuration" })
      .getByRole("combobox", { name: "Effort", exact: true }),
  ).toBeEnabled();
});

test("provider defaults remain absent and reach the worker unchanged", async ({
  page,
}) => {
  for (const tool of ["Codex"]) {
    const region = page.getByRole("region", { name: `${tool} configuration` });
    await expect(
      region.getByRole("combobox", { name: "Effort", exact: true }),
    ).toHaveText("Use project and global defaults");
    await expect(
      region.getByRole("combobox", { name: "Permission mode", exact: true }),
    ).toHaveCount(0);
  }
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBeUndefined();
  const events = await launch(page);
  expect(
    events.some(
      (event: { payload: { text?: string } }) =>
        event.payload.text === "config: model=m1;effort=high;mode=ask",
    ),
  ).toBeTruthy();
});

test("explicit effort choices survive save, reload, and execution", async ({
  page,
}, testInfo) => {
  await choose(page, "Codex", "Effort", "Low");
  await save(page);
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBe("low");
  await page.reload();
  await page.locator(".react-flow__node").filter({ hasText: "work" }).click();
  await page.getByRole("tab", { name: "Steps", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "Codex configuration" })
      .getByRole("combobox", { name: "Effort", exact: true }),
  ).toHaveText("Low");
  await page.screenshot({
    path: testInfo.outputPath("agent-configuration.png"),
    fullPage: true,
  });
  const events = await launch(page);
  expect(
    events.some(
      (event: { payload: { text?: string } }) =>
        event.payload.text === "config: model=m1;effort=low;mode=ask",
    ),
  ).toBeTruthy();
});

test("tools without an effort selector show provider default without an override", async ({
  page,
}) => {
  await page.route("**/api/agents/codex/configuration", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, effort: null } });
  });
  await page.getByRole("combobox", { name: "Model", exact: true }).fill("m2");
  const region = page.getByRole("region", { name: "Codex configuration" });
  await expect(
    region.getByText("This tool does not expose a separate effort selector."),
  ).toBeVisible();
  await expect(
    region.getByRole("combobox", { name: "Effort", exact: true }),
  ).toHaveText("Use project and global defaults");
  await expect(
    region.getByRole("combobox", { name: "Effort", exact: true }),
  ).toBeDisabled();
  await save(page);
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBeUndefined();
});

test("returning to inherited defaults removes the saved overrides", async ({
  page,
}) => {
  await choose(page, "Codex", "Effort", "Low");
  await choose(page, "Codex", "Effort", "Use project and global defaults");
  await save(page);
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBeUndefined();
  const events = await launch(page);
  expect(
    events.some(
      (event: { payload: { text?: string } }) =>
        event.payload.text === "config: model=m1;effort=high;mode=ask",
    ),
  ).toBeTruthy();
});

test("changing the model refreshes its choices and resets effort", async ({
  page,
}) => {
  await choose(page, "Codex", "Effort", "High");
  await page.getByRole("combobox", { name: "Model", exact: true }).fill("m2");
  const effort = page
    .getByRole("region", { name: "Codex configuration" })
    .getByRole("combobox", { name: "Effort", exact: true });
  await expect(effort).toBeEnabled();
  await expect(effort).toHaveText("Use project and global defaults");
  await effort.click();
  await expect(
    page.getByRole("option", { name: "Medium", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("option", { name: "High", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("option", { name: "Medium", exact: true }).click();
  await save(page);
  const events = await launch(page);
  expect(
    events.some(
      (event: { payload: { text?: string } }) =>
        event.payload.text === "config: model=m2;effort=medium;mode=ask",
    ),
  ).toBeTruthy();
});

test("failed capability reads offer retry without writing an override", async ({
  page,
}) => {
  await page.route("**/api/agents/codex/configuration", (route) =>
    route.fulfill({
      status: 502,
      json: {
        code: "agent_protocol_error",
        message: "Probe failed.",
        context: {},
      },
    }),
  );
  await page.getByRole("combobox", { name: "Model", exact: true }).fill("m2");
  const region = page.getByRole("region", { name: "Codex configuration" });
  await expect(region.getByText("Probe failed.")).toBeVisible();
  await page.unroute("**/api/agents/codex/configuration");
  await region.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(
    region.getByRole("combobox", { name: "Effort", exact: true }),
  ).toBeEnabled();
  await expect(
    region.getByRole("combobox", { name: "Effort", exact: true }),
  ).toHaveText("Use project and global defaults");
  await save(page);
  expect((await workflow(page)).jobs.work.steps[0].with.effort).toBeUndefined();
});

/** Create the Ask an agent starter, whose step tries five agents in order. */
async function askAnAgent(page: Page) {
  expect((await post(page, "/__test__/starter-project")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await page.getByRole("button", { name: "New workflow", exact: true }).click();
  const gallery = page.getByRole("dialog", { name: "Choose a workflow" });
  await gallery
    .getByRole("button", { name: "Use Ask an agent", exact: true })
    .click();
  await gallery
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  await expect(gallery).toBeHidden();
  await expect(
    page
      .getByRole("navigation", { name: "Workflow job navigation" })
      .getByRole("button", { name: "Main", exact: true }),
  ).toBeVisible();
  await openJobSettings(page);
}

test("Runs on shows the effective agents in one place", async ({ page }) => {
  await askAnAgent(page);
  await expect(
    page.getByRole("button", { name: "Try in order", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  const order = page.getByRole("list", { name: "Agents to try in order" });
  await expect(order.getByRole("listitem")).toHaveCount(5);
  await expect(order.getByRole("listitem").first()).toContainText("1. Codex");
  await expect(
    page.getByRole("combobox", { name: "Agent", exact: true }),
  ).toHaveCount(0);
  await chooseAgent(page, "Codex");
  await closeJobSettings(page);
  const yaml = page.locator('[aria-label="Workflow YAML"]');
  await expect(yaml).toContainText("agent: codex");
  await expect(yaml).not.toContainText("agents:");
});

test("agent choices show installation status", async ({ page }) => {
  await askAnAgent(page);
  await chooseAgent(page, "Codex");
  await page.getByRole("combobox", { name: "Agent", exact: true }).click();
  const codex = page.getByRole("option", { name: /^Codex / });
  await expect(codex).toHaveText("CodexInstalled");
  await expect(codex).not.toHaveAttribute("aria-disabled", "true");
  const copilot = page.getByRole("option", { name: /^GitHub Copilot CLI / });
  await expect(copilot).toHaveText("GitHub Copilot CLINot installed");
  await expect(copilot).toHaveAttribute("aria-disabled", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Open Get started", exact: true }),
  ).toBeVisible();
});
