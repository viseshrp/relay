import { expect, type Page, type TestInfo } from "@playwright/test";
import { readFile } from "node:fs/promises";

export async function post(page: Page, path: string, data: object = {}) {
  const token = (await page.context().cookies()).find((cookie) => cookie.name === "relay_csrftoken");
  return page.request.post(path, { data, headers: { "X-CSRFToken": token?.value ?? "" } });
}

export async function runStarter(page: Page, id: string, name: string, testInfo: TestInfo, freshOwner = false) {
  expect((await post(page, "/__test__/starter-project", { fresh_owner: freshOwner })).ok()).toBeTruthy();
  await page.route("**/api/runs?*status=succeeded*", (route) => route.fulfill({ json: { runs: [], next: null } }));
  await page.goto("/");
  if (freshOwner) {
    await page.getByRole("textbox", { name: "Username" }).fill("owner");
    await page.getByLabel(/^Password/).fill("Relay-Test-Passphrase-2026!");
    await page.getByRole("button", { name: "Create password", exact: true }).click();
  }
  await page.getByRole("button", { name: "Get started", exact: true }).click();
  const setup = page.getByRole("region", { name: "Get started", exact: true });
  await expect(setup.getByRole("article", { name: "Codex", exact: true })).toContainText("Ready to connect");
  await expect(setup.getByRole("article", { name: "Claude Code", exact: true })).toContainText("Not installed");
  await setup.getByRole("button", { name: "Start from a template", exact: true }).click();
  const gallery = page.getByRole("dialog", { name: "Choose a workflow" });
  await expect(gallery.getByRole("button", { name: /^Use / })).toHaveCount(6);
  await gallery.getByRole("button", { name: `Use ${name}`, exact: true }).click();
  const saved = page.waitForResponse((response) => response.url().endsWith("/api/workflows") && response.request().method() === "POST");
  await gallery.getByRole("button", { name: "Create workflow", exact: true }).click();
  const created = await saved;
  expect(created.status(), await created.text()).toBe(201);
  const document: { key: string; yaml: string } = await created.json();
  const source = await readFile(new URL(`../../relay/workflows/starters/${id}.yaml`, import.meta.url), "utf8");
  expect(document.yaml).toBe(source);
  await expect(gallery).toBeHidden();
  await expect(setup.getByRole("button", { name: "Start from a template", exact: true })).toBeFocused();
  await expect(setup.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
  const launched = page.waitForResponse((response) => response.url().endsWith("/api/runs") && response.request().method() === "POST");
  await setup.getByRole("button", { name: "Run workflow", exact: true }).click();
  const response = await launched;
  expect(response.status(), await response.text()).toBe(201);
  if (id === "plan-approve-implement") {
    await page.getByRole("region", { name: "Waiting for you", exact: true }).getByRole("button", { name: "Respond", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Your review is needed" })).toBeVisible();
    await page.getByLabel("Your response", { exact: true }).fill("Approved");
    await page.getByRole("button", { name: "Send response and continue", exact: true }).click();
  }
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.", { exact: true })).toBeVisible();
  await expect(setup).toHaveCount(0);
  if (id === "ask-agent") await page.screenshot({ path: testInfo.outputPath("run-page.png") });
  await page.getByRole("button", { name: "Help", exact: true }).click();
  const checked = page.waitForResponse((response) => response.url().includes("/api/agents/check"));
  await page.getByRole("menuitem", { name: "Get started", exact: true }).click();
  await expect(setup.getByText("Your first run completed. You can use this checklist again for another workflow.")).toBeVisible();
  await checked;
  await setup.getByRole("button", { name: "Close checklist", exact: true }).click();
  await expect(setup).toHaveCount(0);
}
