import { expect, type Page, type TestInfo } from "@playwright/test";
import { readFile } from "node:fs/promises";

export async function post(page: Page, path: string, data: object = {}) {
  const token = (await page.context().cookies()).find(
    (cookie) => cookie.name === "relay_csrftoken",
  );
  return page.request.post(path, {
    data,
    headers: { "X-CSRFToken": token?.value ?? "" },
  });
}

export async function expectRunStatus(
  page: Page,
  id: string,
  status: string,
  timeout = 20_000,
): Promise<void> {
  let run: { status: string; problem?: unknown } = { status: "pending" };
  // Nested workflows start real Git and shell processes before the UI can settle.
  await expect
    .poll(
      async () => {
        const response = await page.request.get(`/api/runs/${id}`);
        expect(response.ok(), await response.text()).toBeTruthy();
        run = (await response.json()).run;
        return (
          run.status === status ||
          ["succeeded", "failed", "canceled"].includes(run.status)
        );
      },
      { timeout },
    )
    .toBe(true);
  expect(run).toMatchObject({ status });
}

export async function closeJobSettings(page: Page) {
  const close = page.getByRole("button", {
    name: "Close job settings",
    exact: true,
  });
  if (await close.isVisible()) {
    await close.click();
    await expect(close).toHaveCount(0);
  }
}

export async function openJobSettings(page: Page, tab = "Steps") {
  if (!(await page.locator(".react-flow__node").count())) {
    const mode = page.getByRole("combobox", {
      name: "Editor mode",
      exact: true,
    });
    if (await mode.isVisible()) {
      await mode.click();
      await page.getByRole("option", { name: "Split", exact: true }).click();
    }
  }
  if (
    !(await page
      .getByRole("button", { name: "Close job settings", exact: true })
      .isVisible())
  )
    await page
      .getByRole("navigation", { name: "Workflow job navigation" })
      .getByRole("button")
      .first()
      .click();
  const dialog = page.getByRole("dialog", { name: /^Job settings: / });
  // Target the tab after the drawer reaches its final position.
  await dialog.evaluate(async (element) => {
    await Promise.all(
      element
        .getAnimations({ subtree: true })
        .filter(
          (animation) =>
            animation.effect?.getComputedTiming().iterations !== Infinity,
        )
        .map((animation) => animation.finished.catch(() => undefined)),
    );
  });
  await dialog.getByRole("tab", { name: tab, exact: true }).click();
  await expect(
    dialog.getByRole("tabpanel", { name: tab, exact: true }),
  ).toBeVisible();
}

/** Expand the open job tab's Advanced section, where rarer fields live. */
export async function openAdvanced(page: Page) {
  const toggle = page
    .getByRole("tabpanel")
    .getByRole("button", { name: "Advanced", exact: true });
  if ((await toggle.getAttribute("aria-expanded")) !== "true")
    await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
}

/** The step's raw action reference, under Advanced. */
export async function actionReference(page: Page) {
  await openAdvanced(page);
  return page.getByLabel("Action reference", { exact: true });
}

/** Run the open agent step on one agent. */
export async function chooseAgent(page: Page, name: string) {
  const one = page.getByRole("button", { name: "One agent", exact: true });
  if ((await one.getAttribute("aria-pressed")) !== "true") await one.click();
  const agent = page.getByRole("combobox", { name: "Agent", exact: true });
  if ((await agent.textContent()) !== name) {
    await agent.click();
    await page.getByRole("option", { name: new RegExp(`^${name} `) }).click();
  }
  await expect(agent).toHaveText(name);
}

export async function advancedField(page: Page, label: string, tab = "Steps") {
  await openJobSettings(page, tab);
  const toggle = page.getByRole("button", {
    name: `Advanced JSON: ${label}`,
    exact: true,
  });
  if (!(await toggle.isVisible())) await openAdvanced(page);
  const accordion = toggle.locator(
    "xpath=ancestor::*[contains(@class, 'MuiAccordion-root')][1]",
  );
  const field = accordion.getByRole("textbox", { name: label, exact: true });
  if (!(await field.isVisible())) await toggle.click();
  return field;
}

export async function openSettings(page: Page): Promise<void> {
  await expect(
    page.getByRole("button", { name: /^(Help|Account menu for .+)$/ }),
  ).toBeVisible();
  const account = page.getByRole("button", { name: /^Account menu for / });
  if (await account.count()) {
    await account.click();
    await page.getByRole("menuitem", { name: "Settings", exact: true }).click();
  } else
    await page.getByRole("link", { name: "Settings", exact: true }).click();
}

export async function runStarter(
  page: Page,
  id: string,
  name: string,
  testInfo: TestInfo,
  freshOwner = false,
  approval = "Approve",
): Promise<string> {
  expect(
    (
      await post(page, "/__test__/starter-project", { fresh_owner: freshOwner })
    ).ok(),
  ).toBeTruthy();
  await page.route("**/api/runs?*status=succeeded*", (route) =>
    route.fulfill({ json: { runs: [], next: null } }),
  );
  await page.goto("/?view=workflows");
  if (freshOwner) {
    await page.getByRole("textbox", { name: "Username" }).fill("owner");
    await page.getByLabel(/^Password/).fill("Relay-Test-Passphrase-2026!");
    await page
      .getByRole("button", { name: "Create password", exact: true })
      .click();
  }
  await page.getByRole("button", { name: "Get started", exact: true }).click();
  const setup = page.getByRole("dialog", { name: "Get started", exact: true });
  await expect(
    setup.getByRole("article", { name: "Codex", exact: true }),
  ).toContainText("Ready to connect");
  await expect(
    setup.getByRole("article", { name: "Claude Code", exact: true }),
  ).toContainText("Not installed");
  await setup
    .getByRole("button", { name: "Start from a template", exact: true })
    .click();
  const gallery = page.getByRole("dialog", { name: "Choose a workflow" });
  await expect(gallery.getByRole("button", { name: /^Use / })).toHaveCount(7);
  await gallery
    .getByRole("button", { name: `Use ${name}`, exact: true })
    .click();
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/workflows") &&
      response.request().method() === "POST",
  );
  await gallery
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  const created = await saved;
  expect(created.status(), await created.text()).toBe(201);
  const document: { key: string; yaml: string } = await created.json();
  const source = await readFile(
    new URL(`../../relay/workflows/starters/${id}.yaml`, import.meta.url),
    "utf8",
  );
  expect(document.yaml).toBe(source);
  await expect(gallery).toBeHidden();
  await expect(
    setup.getByRole("button", { name: "Start from a template", exact: true }),
  ).toBeFocused();
  await expect(
    setup.getByRole("button", { name: "Run workflow", exact: true }),
  ).toBeEnabled();
  const launched = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await setup
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const response = await launched;
  expect(response.status(), await response.text()).toBe(201);
  const { run_id: runId } = await response.json();
  if (id === "plan-approve-implement") {
    await page
      .getByRole("region", { name: "Waiting for you", exact: true })
      .getByRole("button", { name: "Respond", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Your review is needed" }),
    ).toBeVisible();
    const request = page.locator(".interaction-card");
    // Declared answers are buttons; no free-text answer can fail the run.
    await expect(
      request.getByLabel("Your response", { exact: true }),
    ).toHaveCount(0);
    await request.getByRole("button", { name: approval, exact: true }).click();
  }
  await expectRunStatus(page, runId, "succeeded");
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(setup).toHaveCount(0);
  if (id === "ask-agent")
    await page.screenshot({ path: testInfo.outputPath("run-page.png") });
  await page
    .getByRole("button", { name: /^(Help|Account menu for owner)$/ })
    .click();
  const checked = page.waitForResponse((response) =>
    response.url().includes("/api/agents/check"),
  );
  await page
    .getByRole("menuitem", { name: "Get started", exact: true })
    .click();
  await expect(
    setup.getByText(
      "Your first run completed. You can use this checklist again for another workflow.",
    ),
  ).toBeVisible();
  await checked;
  await setup
    .getByRole("button", { name: "Close checklist", exact: true })
    .click();
  await expect(setup).toHaveCount(0);
  return runId;
}
