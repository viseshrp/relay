import { expect, test, type Page } from "./a11y-test";
import { stringify } from "yaml";

import {
  post,
  currentWorkflow,
  openJobSettings,
  closeJobSettings,
} from "./setup-helpers";

import type { WorkflowNodeValue } from "../src/workflow";

async function createWorkflow(
  page: Page,
  key: string,
  name: string,
  nodes: Record<string, WorkflowNodeValue>,
) {
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const response = await post(page, "/api/workflows", {
    key,
    holder,
    yaml: stringify(
      currentWorkflow({
        version: 1,
        name,
        model: "m1",
        agents: ["codex"],
        nodes,
      }),
    ),
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

function longWorkflow(): Record<string, WorkflowNodeValue> {
  const ids = [
    "prepare",
    ...Array.from({ length: 21 }, (_, index) => `step_${index + 1}`),
    "review",
  ];
  return Object.fromEntries(
    ids.map((id, index) => [
      id,
      {
        type: "command",
        run: ["git", "status"],
        ...(index > 0 ? { needs: [ids[index - 1]] } : {}),
      },
    ]),
  );
}

async function expectCenteredStage(page: Page, id: string) {
  const canvas = page.locator(".flow-canvas");
  const node = canvas.locator(`.react-flow__node[data-id="${id}"]`);
  await canvas.scrollIntoViewIfNeeded();
  await expect(node).toBeInViewport();
  await expect
    .poll(async () => {
      const outer = await canvas.boundingBox();
      const inner = await node.boundingBox();
      if (!outer || !inner || inner.width < 120) return false;
      return (
        Math.abs(inner.x + inner.width / 2 - (outer.x + outer.width / 2)) < 2 &&
        Math.abs(inner.y + inner.height / 2 - (outer.y + outer.height / 2)) < 2
      );
    })
    .toBeTruthy();
}

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect(
    (
      await post(page, "/api/auth/login", {
        username: "owner",
        password: "Relay-Test-Passphrase-2026!",
      })
    ).ok(),
  ).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await expect(
    page.getByRole("button", { name: "Add job", exact: true }),
  ).toBeEnabled();
});

test("switching workflows resets the canvas and shows the first stage at a readable scale", async ({
  page,
}) => {
  await createWorkflow(page, "canvas-short", "Canvas short", {
    prepare: { type: "command", run: ["git", "status"] },
  });
  await createWorkflow(page, "canvas-long", "Canvas long", longWorkflow());
  await page.goto("/?view=author&workflow=canvas-short.yaml");
  await expectCenteredStage(page, "prepare");
  await page.getByRole("button", { name: "Zoom In" }).click();
  await page.getByRole("combobox", { name: "Workflow", exact: true }).click();
  await page.getByRole("option", { name: "Canvas long", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(23);
  await expectCenteredStage(page, "prepare");
  const navigation = page.getByRole("navigation", {
    name: "Workflow job navigation",
  });
  await navigation.getByRole("button", { name: "Review", exact: true }).click();
  await expectCenteredStage(page, "review");
  await closeJobSettings(page);
  await page.getByLabel("Find a job", { exact: true }).fill("REVIEW");
  await page.getByRole("combobox", { name: "Workflow", exact: true }).click();
  await page.getByRole("option", { name: "Canvas short", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
  await expectCenteredStage(page, "prepare");
  await expect(page.getByLabel("Find a job", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Find a job")).toHaveValue("");
});

test("search and keyboard selection restore an off-screen stage without changing the workflow", async ({
  page,
}) => {
  await createWorkflow(page, "canvas-search", "Canvas search", longWorkflow());
  await page.goto("/?view=author&workflow=canvas-search.yaml");
  await expect(page.locator(".react-flow__node")).toHaveCount(23);
  const before = await (
    await page.request.get("/api/workflows/canvas-search.yaml")
  ).json();
  const navigation = page.getByRole("navigation", {
    name: "Workflow job navigation",
  });
  await navigation.getByLabel("Find a job", { exact: true }).fill("REVIEW");
  await expect(navigation.getByRole("button")).toHaveCount(1);
  const review = navigation.getByRole("button", {
    name: "Review",
    exact: true,
  });
  await review.focus();
  await review.press("Enter");
  await expectCenteredStage(page, "review");
  await expect(page.getByLabel("Job name", { exact: true })).toHaveValue("");
  await closeJobSettings(page);
  await expect(review).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Fit View" }).click();
  await review.click();
  await expectCenteredStage(page, "review");
  await closeJobSettings(page);
  await page.setViewportSize({ width: 760, height: 900 });
  await review.click();
  await expectCenteredStage(page, "review");
  await closeJobSettings(page);
  await navigation
    .getByLabel("Find a job", { exact: true })
    .fill("not a stage");
  await expect(
    navigation.getByText("No jobs match. Try another name."),
  ).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(23);
  const after = await (
    await page.request.get("/api/workflows/canvas-search.yaml")
  ).json();
  expect(after.yaml).toBe(before.yaml);
  expect(after.base_hash).toBe(before.base_hash);
  expect(after.draft).toEqual(before.draft);
});

test("unsaved agent instructions persist as a draft across workflow navigation", async ({
  page,
}) => {
  await createWorkflow(page, "navigation-agent", "Navigation agent", {
    work: { type: "agent" },
  });
  await page.goto("/?view=author&workflow=navigation-agent.yaml");
  await openJobSettings(page);
  await page
    .getByLabel("Agent prompt", { exact: true })
    .fill("Keep these instructions in this workflow.");
  await closeJobSettings(page);
  await page.getByRole("combobox", { name: "Workflow", exact: true }).click();
  await page
    .getByRole("option", { name: "Configuration", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get("/api/workflows/navigation-agent.yaml")
          ).json()
        ).draft?.yaml,
    )
    .toContain("Keep these instructions");
  await page.getByRole("combobox", { name: "Workflow", exact: true }).click();
  await page
    .getByRole("option", { name: "Navigation agent", exact: true })
    .click();
  await openJobSettings(page);
  await expect(page.getByLabel("Agent prompt", { exact: true })).toContainText(
    "Keep these instructions in this workflow.",
  );
  const document = await (
    await page.request.get("/api/workflows/navigation-agent.yaml")
  ).json();
  expect(document.yaml).not.toContain("Keep these instructions");
});
