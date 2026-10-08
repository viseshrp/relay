import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

import type { WorkflowNodeValue } from "../src/workflow";

async function post(page: Page, path: string, data: object = {}) {
  const csrf = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  return page.request.post(path, { data, headers: { "X-CSRFToken": csrf?.value ?? "" } });
}

async function createWorkflow(page: Page, key: string, name: string, nodes: Record<string, WorkflowNodeValue>) {
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const response = await post(page, "/api/workflows", {
    key, holder, yaml: stringify({ version: 1, name, model: "m1", agents: ["codex"], nodes }),
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

function longWorkflow(): Record<string, WorkflowNodeValue> {
  const ids = ["prepare", ...Array.from({ length: 21 }, (_, index) => `step_${index + 1}`), "review"];
  return Object.fromEntries(ids.map((id, index) => [id, {
    type: "command", run: ["git", "status"], ...(index > 0 ? { needs: [ids[index - 1]] } : {}),
  }]));
}

async function expectCenteredStage(page: Page, id: string) {
  const canvas = page.getByRole("region", { name: "Workflow canvas", exact: true });
  const node = canvas.locator(`.react-flow__node[data-id="${id}"]`);
  await canvas.scrollIntoViewIfNeeded();
  await expect(node).toBeInViewport();
  await expect.poll(async () => {
    const outer = await canvas.boundingBox();
    const inner = await node.boundingBox();
    if (!outer || !inner || inner.width < 120) return false;
    return Math.abs((inner.x + inner.width / 2) - (outer.x + outer.width / 2)) < 2
      && Math.abs((inner.y + inner.height / 2) - (outer.y + outer.height / 2)) < 2;
  }).toBeTruthy();
}

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
});

test("switching workflows resets the canvas and shows the first stage at a readable scale", async ({ page }) => {
  await createWorkflow(page, "canvas-short", "Canvas short", { prepare: { type: "command", run: ["git", "status"] } });
  await createWorkflow(page, "canvas-long", "Canvas long", longWorkflow());
  await page.goto("/?view=author&workflow=canvas-short.yaml");
  await expectCenteredStage(page, "prepare");
  await page.getByRole("button", { name: "Zoom In" }).click();
  await page.getByRole("combobox", { name: "Workflow", exact: true }).click();
  await page.getByRole("option", { name: "Canvas long", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(23);
  await expectCenteredStage(page, "prepare");
  const navigation = page.getByRole("navigation", { name: "Workflow stage navigation" });
  await navigation.getByRole("button", { name: "Review", exact: true }).click();
  await expectCenteredStage(page, "review");
  await page.getByLabel("Find a stage", { exact: true }).fill("REVIEW");
  await page.getByRole("combobox", { name: "Workflow", exact: true }).click();
  await page.getByRole("option", { name: "Canvas short", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
  await expectCenteredStage(page, "prepare");
  await expect(page.getByLabel("Find a stage", { exact: true })).toHaveValue("");
  await expect(page.getByRole("region", { name: "Stage settings", exact: true })).toHaveCount(0);
});

test("search and keyboard selection restore an off-screen stage without changing the workflow", async ({ page }) => {
  await createWorkflow(page, "canvas-search", "Canvas search", longWorkflow());
  await page.goto("/?view=author&workflow=canvas-search.yaml");
  await expect(page.locator(".react-flow__node")).toHaveCount(23);
  const before = await (await page.request.get("/api/workflows/canvas-search.yaml")).json();
  const navigation = page.getByRole("navigation", { name: "Workflow stage navigation" });
  await navigation.getByLabel("Find a stage", { exact: true }).fill("REVIEW");
  await expect(navigation.getByRole("button")).toHaveCount(1);
  const review = navigation.getByRole("button", { name: "Review", exact: true });
  await review.focus();
  await review.press("Enter");
  await expectCenteredStage(page, "review");
  await expect(page.getByRole("region", { name: "Stage settings", exact: true })).toBeFocused();
  await expect(review).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("region", { name: "Stage settings", exact: true }).getByRole("heading", { name: "Review", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Fit View" }).click();
  await review.click();
  await expectCenteredStage(page, "review");
  await page.setViewportSize({ width: 760, height: 900 });
  await review.click();
  await expectCenteredStage(page, "review");
  await navigation.getByLabel("Find a stage", { exact: true }).fill("not a stage");
  await expect(navigation.getByText("No stages match. Try another name.")).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(23);
  const after = await (await page.request.get("/api/workflows/canvas-search.yaml")).json();
  expect(after.yaml).toBe(before.yaml);
  expect(after.base_hash).toBe(before.base_hash);
  expect(after.draft).toEqual(before.draft);
});

test("stage navigation keeps unsaved agent instructions in their current stage", async ({ page }) => {
  await createWorkflow(page, "canvas-instructions", "Canvas instructions", {
    write: { type: "agent" }, review: { type: "command", run: ["git", "status"], needs: ["write"] },
  });
  await page.goto("/?view=author&workflow=canvas-instructions.yaml");
  const navigation = page.getByRole("navigation", { name: "Workflow stage navigation" });
  await navigation.getByRole("button", { name: "Write", exact: true }).click();
  await page.getByLabel("What should the agent do?", { exact: true }).fill("Keep this unsaved instruction.");
  await navigation.getByRole("button", { name: "Review", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Save the agent's instructions before selecting another stage." })).toBeVisible();
  await expect(page.getByLabel("What should the agent do?", { exact: true })).toHaveValue("Keep this unsaved instruction.");
  await expect(navigation.getByRole("button", { name: "Write", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(navigation.getByRole("button", { name: "Review", exact: true })).toHaveAttribute("aria-pressed", "false");
});
