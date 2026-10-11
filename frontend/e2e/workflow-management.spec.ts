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
