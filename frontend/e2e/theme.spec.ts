import { expect, test } from "./a11y-test";
import { post } from "./setup-helpers";

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

test("theme toggle switches between modes and persists preference across page reload", async ({
  page,
}) => {
  await page.goto("/?view=home");
  await expect(page.getByRole("main")).toBeVisible();
  await page.evaluate(() => localStorage.removeItem("relay-theme-preference"));

  const toggleButton = page.getByRole("button", { name: /^Theme mode:/i });
  await expect(toggleButton).toBeVisible();

  await toggleButton.click();
  const darkOption = page.getByRole("menuitem", { name: "Dark" });
  await expect(darkOption).toBeVisible();
  await darkOption.click();

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const storedDark = await page.evaluate(() =>
    localStorage.getItem("relay-theme-preference"),
  );
  expect(storedDark).toBe("dark");

  await page.reload();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.getByRole("button", { name: /^Theme mode:/i }).click();
  const lightOption = page.getByRole("menuitem", { name: "Light" });
  await expect(lightOption).toBeVisible();
  await lightOption.click();

  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const storedLight = await page.evaluate(() =>
    localStorage.getItem("relay-theme-preference"),
  );
  expect(storedLight).toBe("light");
});

test("system color scheme preference is reflected when mode is set to system", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/?view=home");
  await expect(page.getByRole("main")).toBeVisible();
  await page.evaluate(() => localStorage.removeItem("relay-theme-preference"));
  await page.reload();

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("button", { name: /^Theme mode: System \(dark\)/i }),
  ).toBeVisible();

  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(
    page.getByRole("button", { name: /^Theme mode: System \(light\)/i }),
  ).toBeVisible();
});

test("workflow editor stays mounted and adapts when theme is toggled", async ({
  page,
}) => {
  await page.goto("/?view=workflows");
  await expect(page.getByRole("main")).toBeVisible();
  const editor = page.locator(".cm-editor");
  await expect(editor.first()).toBeVisible();

  await page.getByRole("button", { name: /^Theme mode:/i }).click();
  await page.getByRole("menuitem", { name: "Dark" }).click();

  await expect(editor.first()).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
