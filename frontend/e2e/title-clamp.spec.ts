import { test, expect } from "./a11y-test";
import { post } from "./setup-helpers";

for (const width of [320, 375, 1440])
  test(`long run titles clamp to two lines at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 960 });
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
    const response = await post(page, "/__test__/worst-case", {
      enabled: true,
    });
    expect(response.ok()).toBeTruthy();
    const fixture = await response.json();
    await page.goto(
      `/?view=runs&project=${fixture.project}&run=${fixture.run}`,
    );
    await expect(
      page.getByRole("region", { name: "Step progress" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: "Visual <script> ** &amp; workflow",
        exact: true,
      }),
    ).toBeVisible();
    const title = page.locator(".run-heading-row .run-title");
    const geometry = await title.evaluate((element) => ({
      height: element.getBoundingClientRect().height,
      line: Number.parseFloat(getComputedStyle(element).lineHeight),
    }));
    expect(geometry.height).toBeLessThanOrEqual(geometry.line * 2 + 1);
    const number = await page
      .getByRole("heading", { level: 1 })
      .getByText("#1", { exact: true })
      .boundingBox();
    expect(
      number && number.x >= 0 && number.x + number.width <= width,
    ).toBeTruthy();
    const text = await title.textContent();
    await page
      .getByRole("button", { name: "Show full title", exact: true })
      .click();
    await expect(
      page.getByRole("dialog", { name: "Run title", exact: true }),
    ).toContainText(text ?? "");
  });
