import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";
import { post, currentWorkflow } from "./setup-helpers";

const option = "Merge into the active branch, then delete working copies";

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
});
test.afterEach(async ({ page }) => {
  await post(page, "/__test__/reset");
});

async function create(page: Page, key: string, wait = false) {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const response = await post(page, "/api/workflows", {
    key,
    holder,
    yaml: stringify(
      currentWorkflow({
        version: 1,
        name: "Merge result",
        nodes: {
          write: {
            type: "command",
            writes: true,
            run: ["git", "commit", "--allow-empty", "-q", "-m", "Run result"],
          },
          ...(wait
            ? {
                approve: {
                  type: "human_wait",
                  needs: ["write"],
                  prompt: "Continue?",
                },
              }
            : {}),
        },
      }),
    ),
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  await page.goto(`/?view=workflows&workflow=${key}.yaml`);
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
}

async function launchPanel(page: Page) {
  await page
    .getByRole("region", { name: "Workflow header" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const panel = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await panel.getByText("Advanced options", { exact: true }).click();
  await panel
    .getByRole("combobox", { name: "After a successful run", exact: true })
    .click();
  await page.getByRole("option", { name: option, exact: true }).click();
  return panel;
}

test("global and project merge defaults save and the launch preview blocks dirty sources", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.goto("/?view=settings");
  const global = page.getByRole("region", {
    name: "Global defaults",
    exact: true,
  });
  await global
    .getByRole("combobox", { name: "After a successful run", exact: true })
    .click();
  await page.getByRole("option", { name: option, exact: true }).click();
  await global
    .getByRole("button", { name: "Save global settings", exact: true })
    .click();
  await expect(
    global.getByText(
      "Global defaults saved. Future runs inherit these choices.",
    ),
  ).toBeVisible();
  await page.reload();
  await expect(
    global.getByRole("combobox", {
      name: "After a successful run",
      exact: true,
    }),
  ).toContainText(option);
  await global
    .getByRole("combobox", { name: "After a successful run", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("merge-settings.png"),
    animations: "disabled",
  });
  await page
    .getByRole("navigation", { name: "Settings sections" })
    .getByRole("button", { name: "Project defaults", exact: true })
    .click();
  const project = page.getByRole("region", {
    name: "Project defaults",
    exact: true,
  });
  await project
    .getByRole("switch", {
      name: "Override working-copy cleanup for this project",
      exact: true,
    })
    .check();
  await project
    .getByRole("combobox", { name: "After a successful run", exact: true })
    .click();
  await page
    .getByRole("option", { name: "Keep the working copy", exact: true })
    .click();
  await project
    .getByRole("button", { name: "Save project defaults", exact: true })
    .click();
  await expect(
    project.getByText(
      "Project defaults saved. Future runs inherit these choices.",
    ),
  ).toBeVisible();
  await create(page, "dirty-merge");
  const panel = await launchPanel(page);
  await expect(
    panel.getByRole("button", { name: "Run workflow", exact: true }),
  ).toBeDisabled();
  await expect(
    panel.getByRole("region", { name: "Launch file check" }),
  ).toContainText("A merge requires every changed file");
  await expect(panel).toContainText("delete the run working copies");
  await panel.press("Escape");
});

test("a successful run shows the merged branch and deleted working copies", async ({
  page,
}, info) => {
  await create(page, "complete-merge");
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const panel = await launchPanel(page);
  await expect(
    panel.getByRole("button", { name: "Run workflow", exact: true }),
  ).toBeEnabled();
  const launched = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await panel
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const response = await launched;
  expect(response.ok(), await response.text()).toBeTruthy();
  const { run_id: id } = await response.json();
  await expect(
    page.getByRole("alert").filter({ hasText: "Merged into main" }),
  ).toContainText("Run working copies deleted.");
  const run = (await (await page.request.get(`/api/runs/${id}`)).json()).run;
  expect(run.status).toBe("succeeded");
  expect(run.worktree_state).toBe("removed");
  expect(run.merged_commit).toMatch(/^[0-9a-f]{40}$/);
  await page.screenshot({
    path: info.outputPath("merged-run.png"),
    animations: "disabled",
  });
  await page.reload();
  await expect(
    page.getByRole("alert").filter({ hasText: "Merged into main" }),
  ).toContainText("Run working copies deleted.");
});

test("changes made while a run waits fail integration and remain untouched", async ({
  page,
}) => {
  await create(page, "blocked-merge", true);
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const response = await post(page, "/api/runs", {
    workflow_key: "blocked-merge",
    inputs: {},
    cleanup_policy: "merge_on_success",
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const { run_id: id } = await response.json();
  await page.goto(`/?view=runs&run=${id}`);
  const waiting = page.getByRole("region", {
    name: "Waiting for you",
    exact: true,
  });
  await expect(waiting).toBeVisible();
  const before = await (
    await post(page, "/__test__/launch-files", { mode: "race" })
  ).json();
  expect(before.status).toContain("racing code.py");
  await waiting.getByRole("button", { name: "Respond", exact: true }).click();
  await page.getByLabel("Your response", { exact: true }).fill("Continue");
  await page
    .getByRole("button", { name: "Send response and continue", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({
      hasText: "The Git worktree is not clean at merge into the active branch.",
    }),
  ).toBeVisible();
  const run = (await (await page.request.get(`/api/runs/${id}`)).json()).run;
  expect(run.status).toBe("failed");
  expect(run.worktree_state).toBe("created");
  expect(run.merged_commit).toBeNull();
  const after = await (
    await post(page, "/__test__/launch-files", { mode: "inspect" })
  ).json();
  expect(after).toEqual(before);
});
