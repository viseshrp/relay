import { expect, test } from "@playwright/test";
import { post } from "./setup-helpers";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});

test("a second tab can discard an invalid draft, take over editing, and release on close", async ({ page, context }) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.locator(".cm-content").fill("jobs: [");
  await expect.poll(async () => (await (await page.request.get("/api/workflows/workflow.yaml")).json()).draft?.validation_state).toBe("invalid");
  const other = await context.newPage();
  await other.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(other.getByRole("button", { name: "Edit here instead" })).toBeVisible();
  await expect(other.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
  await other.getByRole("button", { name: "Restore saved source" }).click();
  await expect.poll(async () => (await (await page.request.get("/api/workflows/workflow.yaml")).json()).draft).toBeNull();
  await other.getByRole("button", { name: "Edit here instead" }).click();
  await expect(other.getByText("Ready to edit", { exact: true })).toBeVisible();
  await other.close();
  await page.reload();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
});

test("invalid drafts retain the graph and the valid saved file can still run", async ({ page }) => {
  await page.goto("/?view=workflows");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const nodeCount = await page.locator(".react-flow__node").count();
  await page.locator(".cm-content").fill('jobs:\n  check:\n    steps:\n      - run: echo "Task: example"\n');
  await expect(page.getByText(/Quote a value that contains a colon/)).toBeVisible();
  await expect(page.getByText("Showing the last valid version", { exact: true })).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(nodeCount);
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await expect(dialog).toContainText("Your unsaved draft is not included");
  await expect(dialog.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
});

test("reviewed workflow-source commits unblock another workflow and required inputs have inline errors", async ({ page }) => {
  expect((await post(page, "/api/workflows", { key: "required", holder: "fixture", yaml: "name: Required workflow\non:\n  workflow_dispatch:\n    inputs:\n      task: {type: string, required: true}\njobs: {check: {steps: [{run: 'echo ${{ inputs.task }}'}]}}\n" })).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  await page.getByRole("button", { name: "Commit workflow files", exact: true }).click();
  const review = page.getByRole("dialog", { name: "Review workflow files to commit" });
  await expect(review).toContainText(".relay/workflows/required.yaml");
  await expect(review.getByRole("button", { name: "Confirm commit" })).toBeDisabled();
  await review.getByRole("checkbox", { name: "Commit these 1 reviewed files" }).check();
  await review.getByRole("button", { name: "Confirm commit" }).click();
  await expect(review).toBeHidden();
  const launch = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await expect(launch.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
  await launch.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.goto("/?view=workflows&workflow=required.yaml");
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(launch.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
  await launch.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(launch.getByText("Enter a value for this required input.")).toBeVisible();
  await expect(launch.getByRole("textbox", { name: "Task" })).toBeFocused();
  await launch.getByRole("textbox", { name: "Task" }).fill("ready");
  await launch.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.", { exact: true })).toBeVisible();
});
