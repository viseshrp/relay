import { expect, test } from "./a11y-test";
import { post } from "./setup-helpers";

test("workflow management and the shared sidebar stay in sync", async ({
  page,
}) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  async function choose(action: string) {
    await page
      .getByRole("button", { name: "Manage workflow", exact: true })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: action, exact: true })
      .click();
  }
  await choose("Duplicate");
  await page
    .getByRole("textbox", { name: "Workflow display name" })
    .fill("Copy workflow");
  await page.getByRole("button", { name: "Confirm duplicate" }).click();
  await expect(
    page
      .getByRole("navigation", { name: "Workflow sidebar" })
      .getByRole("link", { name: /Copy workflow/ }),
  ).toBeVisible();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await choose("Rename");
  await page
    .getByRole("textbox", { name: "Workflow file name" })
    .fill("renamed.yaml");
  await page.getByRole("button", { name: "Confirm rename" }).click();
  await expect(
    page.getByRole("navigation", { name: "Workflow sidebar" }),
  ).toContainText("renamed.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await choose("Disable");
  await page.getByRole("button", { name: "Confirm disable" }).click();
  await expect(
    page.getByRole("button", { name: "Run workflow", exact: true }),
  ).toHaveCount(0);
  await choose("Enable");
  await page.getByRole("button", { name: "Confirm enable" }).click();
  await expect(
    page.getByRole("button", { name: "Run workflow", exact: true }),
  ).toBeVisible();
  await choose("Delete");
  await expect(page.getByRole("dialog")).toContainText(
    "Run history and shared prompt files stay available",
  );
  await page.getByRole("button", { name: "Confirm delete" }).click();
  await expect(
    page.getByRole("navigation", { name: "Workflow sidebar" }),
  ).not.toContainText("renamed.yaml");
});

test("a management refresh cannot reselect a workflow after browser Back", async ({
  page,
}) => {
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
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Manage workflow", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Duplicate", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Workflow display name" })
    .fill("Copy workflow");
  await page.getByRole("button", { name: "Confirm duplicate" }).click();
  await expect(
    page.getByRole("combobox", { name: "Workflow", exact: true }),
  ).toHaveText("Copy workflow");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const sidebar = page.getByRole("navigation", { name: "Workflow sidebar" });
  await sidebar
    .getByRole("link")
    .filter({ has: page.getByText("workflow.yaml", { exact: true }) })
    .click();
  await expect(page).toHaveURL(/workflow=workflow\.yaml/);
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Manage workflow", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Disable", exact: true })
    .click();

  let release = () => {};
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  let markHeld = () => {};
  const held = new Promise<void>((resolve) => {
    markHeld = resolve;
  });
  let holdNext = true;
  await page.route(/\/api\/workflows(?:\?.*)?$/, async (route) => {
    const response = await route.fetch();
    if (holdNext) {
      holdNext = false;
      markHeld();
      await pending;
    }
    await route.fulfill({ response });
  });
  try {
    await page.getByRole("button", { name: "Confirm disable" }).click();
    await held;
    await page.goBack();
    await expect(page).toHaveURL(/workflow=workflow-copy\.yaml/);
    await expect(page.locator("h1 .run-title")).toHaveText("Copy workflow");
  } finally {
    release();
  }
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("combobox", { name: "Workflow", exact: true }),
  ).toHaveText("Copy workflow");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
});
