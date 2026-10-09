import { expect, test } from "@playwright/test";
import { post } from "./setup-helpers";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});

test("opening current JSON displays YAML without creating a recovery draft", async ({ page }) => {
  await page.goto("/?view=workflows");
  await expect(page.getByRole("button", { name: "Add job", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const json = JSON.stringify({ name: "Current JSON", jobs: { work: { steps: [{ run: "git status" }] } } }, null, 2);
  expect((await post(page, "/api/workflows", { key: "current-json", holder, yaml: json })).ok()).toBeTruthy();
  const before = await (await page.request.get("/api/workflows/current-json.yaml")).json();
  await page.goto("/?view=workflows&workflow=current-json.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await expect(page.locator('.cm-content')).toContainText("name: Current JSON");
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await expect(page.locator(".app-header").getByRole("button", { name: "About Projects", exact: true })).toHaveCSS("color", "rgb(49, 86, 211)");
  await page.getByRole("tab", { name: "Runs", exact: true }).click();
  const after = await (await page.request.get("/api/workflows/current-json.yaml")).json();
  expect(after.yaml).toBe(before.yaml);
  expect(after.draft).toEqual(before.draft);
});


test("malformed source retains validation errors", async ({ page }) => {
  await page.goto("/?view=workflows");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.locator(".cm-content").fill("jobs: [\n");
  await expect(page.locator(".MuiAlert-colorError")).not.toHaveCount(0);
});

test("new workflows and added jobs use the local language without runner fields", async ({ page }) => {
  await page.goto("/?view=workflows");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await expect(page.locator(".cm-content")).not.toContainText("runs-on");
  await page.getByRole("button", { name: "Add job", exact: true }).click();
  await expect(page.locator(".cm-content")).toContainText("job_1:");
  await expect(page.locator(".cm-content")).not.toContainText("runs-on");
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
  await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
});

test("removed platform syntax blocks saving and clears when removed", async ({ page }) => {
  await page.goto("/?view=workflows");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.locator(".cm-content").fill("jobs: {check: {runs-on: self-hosted, steps: [{run: echo Ready}]}}\n");
  await expect(page.getByText(/runs-on: Unknown workflow field/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await page.locator(".cm-content").fill("jobs: {check: {steps: [{run: echo Ready}]}}\n");
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
  await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
});
