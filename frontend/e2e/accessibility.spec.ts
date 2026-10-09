import { expect, test } from "./a11y-test";
import AxeBuilder from "@axe-core/playwright";
import { post } from "./setup-helpers";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
});

for (const view of ["home", "workflows", "runs", "settings"])
  test(`${view} has labelled controls, landmarks, and accessible contrast`, async ({
    page,
  }) => {
    await page.goto(`/?view=${view}`);
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    if (view === "workflows")
      await expect(
        page.getByText("Ready to edit", { exact: true }),
      ).toBeVisible();
    if (view === "settings")
      await expect(
        page.getByRole("heading", { name: "Global defaults", exact: true }),
      ).toBeVisible();
    const scan = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "best-practice"])
      .analyze();
    expect(
      scan.violations.map(({ id, impact, nodes }) => ({
        id,
        impact,
        nodes: nodes.map((node) => ({
          target: node.target,
          summary: node.failureSummary,
        })),
      })),
    ).toEqual([]);
  });

test("invalid settings cannot save, section changes require discard, and Escape ends welcome", async ({
  page,
}) => {
  await page.goto("/?view=settings");
  const field = page.getByRole("textbox", { name: "Job timeout", exact: true });
  await field.fill("soon");
  await expect(field).toHaveAttribute("aria-invalid", "true");
  await expect(
    page.getByRole("button", { name: "Save global settings" }),
  ).toBeDisabled();
  await page
    .getByRole("navigation", { name: "Settings sections" })
    .getByText("Storage", { exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Unsaved settings" }),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Storage", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Invalid workflow defaults/)).toHaveCount(0);
  await page.getByRole("button", { name: "Account menu for owner" }).click();
  await page
    .getByRole("menuitem", { name: "Welcome slides", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".driver-popover")).toHaveCount(0);
});
