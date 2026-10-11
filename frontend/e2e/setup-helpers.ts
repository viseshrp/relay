import { expect, type Page, type TestInfo } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { parse } from "yaml";

export async function post(page: Page, path: string, data: object = {}) {
  const token = (await page.context().cookies()).find(
    (cookie) => cookie.name === "relay_csrftoken",
  );
  return page.request.post(path, {
    data,
    headers: { "X-CSRFToken": token?.value ?? "" },
  });
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
  await page.getByRole("tab", { name: tab, exact: true }).click();
}

export async function advancedField(page: Page, label: string, tab = "Steps") {
  await openJobSettings(page, tab);
  const toggle = page.getByRole("button", {
    name: `Advanced JSON: ${label}`,
    exact: true,
  });
  const accordion = toggle.locator(
    "xpath=ancestor::*[contains(@class, 'MuiAccordion-root')][1]",
  );
  const field = accordion.getByRole("textbox", { name: label, exact: true });
  if (!(await field.isVisible())) await toggle.click();
  return field;
}

// Historical fixtures exercise monitoring and recovery of retained v1 snapshots.
// Current authoring and launch tests use post() and the public jobs/steps API.
export async function historicalPost(
  page: Page,
  path: string,
  data: object = {},
) {
  const body = data as Record<string, unknown>;
  let target = path;
  if (
    path.split("?")[0] === "/api/workflows" &&
    typeof body.yaml === "string" &&
    parse(body.yaml)?.version === 1
  ) {
    target = path.replace("/api/workflows", "/__test__/historical-workflows");
  } else if (
    path.split("?")[0] === "/api/runs" &&
    typeof body.workflow_key === "string"
  ) {
    const source = await page.request.get(
      `/api/workflows/${body.workflow_key}${path.includes("?") ? path.slice(path.indexOf("?")) : ""}`,
    );
    if (source.ok() && parse((await source.json()).yaml)?.version === 1)
      target = path.replace("/api/runs", "/__test__/historical-runs");
  }
  return post(page, target, data);
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
) {
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
  if (id === "plan-approve-implement") {
    await page
      .getByRole("region", { name: "Waiting for you", exact: true })
      .getByRole("button", { name: "Respond", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Your review is needed" }),
    ).toBeVisible();
    await page.getByLabel("Your response", { exact: true }).fill("Approved");
    await page
      .getByRole("button", { name: "Send response and continue", exact: true })
      .click();
  }
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
}

// Current editor fixtures use jobs/steps. The convenience shape below keeps
// argv and dispatch-input test data readable; historical fixtures use a
// separate, explicitly named helper above.
export function currentWorkflow(value: Record<string, any>) {
  const definitions: Record<string, any> = {};
  for (const [name, item] of Object.entries<any>(value.inputs || {}))
    definitions[name] = {
      type:
        item.type === "enum"
          ? "choice"
          : item.type === "integer"
            ? "number"
            : item.type,
      ...(item.type === "enum"
        ? { options: item.constraints.values.map(String) }
        : {}),
      ...(item.description ? { description: item.description } : {}),
      ...(item.required ? { required: true } : {}),
      ...(item.default !== undefined
        ? {
            default: item.type === "enum" ? String(item.default) : item.default,
          }
        : {}),
    };
  const jobs: Record<string, any> = {};
  for (const [id, node] of Object.entries<any>(value.nodes || {})) {
    let step: Record<string, any>;
    if (node.type === "command")
      step = {
        uses: "relay/command@v1",
        with: Array.isArray(node.run)
          ? { argv: JSON.stringify(node.run) }
          : { command: node.run.command },
      };
    else if (node.type === "agent")
      step = {
        uses: "relay/agent@v1",
        with: {
          agent: node.agents?.[0] || value.agents?.[0] || "codex",
          model: node.model || value.model || "m1",
        },
      };
    else if (node.type === "human_wait")
      step = { uses: "relay/human-wait@v1", with: { prompt: node.prompt } };
    else
      throw new Error(
        "Use explicit Actions source for this fixture's control flow.",
      );
    jobs[id] = {
      ...(node.needs?.length ? { needs: node.needs } : {}),
      ...(node.env ? { env: node.env } : {}),
      steps: [step],
    };
  }
  return {
    name: value.name,
    on: { workflow_dispatch: { inputs: definitions } },
    ...(value.env ? { env: value.env } : {}),
    jobs,
  };
}
