import { assertAccessible, expect, test } from "./a11y-test";
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

test("browser theme-color meta tags honor active theme across OS and preference combinations", async ({
  page,
}) => {
  await page.goto("/?view=home");
  await expect(page.getByRole("main")).toBeVisible();

  const getEffectiveThemeColor = async () => {
    return page.evaluate(() => {
      const metas = Array.from(
        document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'),
      );
      for (const meta of metas) {
        const media = meta.getAttribute("media");
        if (!media || window.matchMedia(media).matches) {
          return meta.getAttribute("content");
        }
      }
      return null;
    });
  };

  const cases = [
    { os: "light" as const, pref: "system", expected: "#f4f6fb" },
    { os: "dark" as const, pref: "system", expected: "#0f172a" },
    { os: "light" as const, pref: "dark", expected: "#0f172a" },
    { os: "dark" as const, pref: "dark", expected: "#0f172a" },
    { os: "light" as const, pref: "light", expected: "#f4f6fb" },
    { os: "dark" as const, pref: "light", expected: "#f4f6fb" },
  ];

  for (const { os, pref, expected } of cases) {
    await page.emulateMedia({ colorScheme: os });
    if (pref === "system") {
      await page.evaluate(() =>
        localStorage.removeItem("relay-theme-preference"),
      );
    } else {
      await page.evaluate(
        (p) => localStorage.setItem("relay-theme-preference", p),
        pref,
      );
    }
    await page.reload();
    await expect(page.getByRole("main")).toBeVisible();
    const color = await getEffectiveThemeColor();
    expect(color).toBe(expected);
  }
});

async function verifyInputContrast(page: Page): Promise<void> {
  await expect(
    page.locator(".MuiOutlinedInput-notchedOutline").first(),
  ).toBeVisible();
  const contrastResults = await page.evaluate(() => {
    function parseRgb(color: string): [number, number, number] {
      const m = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      if (!m) return [0, 0, 0];
      return [parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10)];
    }

    function luminance([r, g, b]: [number, number, number]): number {
      const srgb = [r, g, b].map((c) => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * srgb[0] + 0.7152 * srgb[1] + 0.0722 * srgb[2];
    }

    function contrastRatio(c1: string, c2: string): number {
      const l1 = luminance(parseRgb(c1));
      const l2 = luminance(parseRgb(c2));
      const brightest = Math.max(l1, l2);
      const darkest = Math.min(l1, l2);
      return (brightest + 0.05) / (darkest + 0.05);
    }

    function getEffectiveBg(el: HTMLElement): string {
      let current: HTMLElement | null = el;
      while (current) {
        const bg = window.getComputedStyle(current).backgroundColor;
        if (bg && bg !== "transparent" && !bg.startsWith("rgba(0, 0, 0, 0)")) {
          return bg;
        }
        current = current.parentElement;
      }
      return "rgb(255, 255, 255)";
    }

    const outlines = Array.from(
      document.querySelectorAll(".MuiOutlinedInput-notchedOutline"),
    );
    return outlines.map((outline) => {
      const style = window.getComputedStyle(outline);
      const borderColor = style.borderColor || style.borderTopColor;
      const surfaceColor = getEffectiveBg(outline as HTMLElement);
      return {
        borderColor,
        surfaceColor,
        ratio: contrastRatio(borderColor, surfaceColor),
      };
    });
  });

  expect(contrastResults.length).toBeGreaterThan(0);
  for (const result of contrastResults) {
    expect(result.ratio).toBeGreaterThanOrEqual(3.0);
  }
}

test("form inputs maintain WCAG 1.4.11 boundary contrast >= 3:1 in both light and dark modes", async ({
  page,
}) => {
  // Check Settings inputs in light mode
  await page.goto("/?view=settings");
  await expect(page.getByRole("main")).toBeVisible();
  await page.evaluate(() =>
    localStorage.setItem("relay-theme-preference", "light"),
  );
  await page.reload();
  await expect(page.getByRole("main")).toBeVisible();
  await verifyInputContrast(page);

  // Check Settings inputs in dark mode
  await page.evaluate(() =>
    localStorage.setItem("relay-theme-preference", "dark"),
  );
  await page.reload();
  await expect(page.getByRole("main")).toBeVisible();
  await verifyInputContrast(page);
});

test("guided tour passes accessibility audits in both light and dark themes", async ({
  page,
}) => {
  // Check tour in dark mode
  await page.goto("/?view=home");
  await expect(page.getByRole("main")).toBeVisible();
  await page.evaluate(() =>
    localStorage.setItem("relay-theme-preference", "dark"),
  );
  await page.reload();
  await expect(page.getByRole("main")).toBeVisible();

  // Open Help menu and trigger Guided Tour
  await page
    .getByRole("button", { name: /^(Help|Account menu for owner)$/ })
    .click();
  await page.getByRole("menuitem", { name: "Guided tour" }).click();

  const tourPopover = page.locator(".relay-tour.driver-popover");
  await expect(tourPopover).toBeVisible();

  // Skip and Next buttons have compliant contrast
  const skipBtn = tourPopover.locator(".driver-popover-close-btn");
  await expect(skipBtn).toBeVisible();
  const nextBtn = tourPopover.locator(".driver-popover-next-btn");
  await expect(nextBtn).toBeVisible();

  await assertAccessible(page);

  // Close tour
  await skipBtn.click();
  await expect(tourPopover).toBeHidden();

  // Check tour in light mode
  await page.goto("/?view=home");
  await expect(page.getByRole("main")).toBeVisible();
  await page.evaluate(() =>
    localStorage.setItem("relay-theme-preference", "light"),
  );
  await page.reload();
  await expect(page.getByRole("main")).toBeVisible();

  await page
    .getByRole("button", { name: /^(Help|Account menu for owner)$/ })
    .click();
  await page.getByRole("menuitem", { name: "Guided tour" }).click();
  await expect(tourPopover).toBeVisible();
  await assertAccessible(page);
  await tourPopover.locator(".driver-popover-close-btn").click();
  await expect(tourPopover).toBeHidden();
});

for (const view of ["home", "workflows", "runs", "settings"] as const) {
  test(`${view} view passes accessibility audits in dark mode`, async ({
    page,
  }) => {
    await page.goto(`/?view=${view}`);
    await expect(page.getByRole("main")).toBeVisible();
    await page.evaluate(() =>
      localStorage.setItem("relay-theme-preference", "dark"),
    );
    await page.reload();
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    if (view === "workflows") {
      await expect(
        page.getByText("Ready to edit", { exact: true }),
      ).toBeVisible();
    }
    if (view === "settings") {
      await expect(
        page.getByRole("heading", { name: "Global defaults", exact: true }),
      ).toBeVisible();
    }
    await assertAccessible(page);
  });
}

for (const mode of ["light", "dark"] as const) {
  for (const width of [320, 1440] as const) {
    test(`worst-case screens in ${mode} theme at ${width}px stay contained, accessible, and have valid inputs`, async ({
      page,
    }) => {
      test.setTimeout(90_000);
      await page.setViewportSize({ width, height: 960 });
      await page.addInitScript(
        (pref) => localStorage.setItem("relay-theme-preference", pref),
        mode,
      );
      const response = await post(page, "/__test__/worst-case", {
        enabled: true,
      });
      expect(response.ok()).toBeTruthy();
      const fixture = await response.json();

      const screens = ["home", "workflows", "runs", "settings"] as const;
      for (const screen of screens) {
        const query = new URLSearchParams({
          view: screen,
          project: fixture.project,
        });
        if (screen === "workflows") query.set("workflow", fixture.workflow);
        if (screen === "runs") query.set("run", fixture.run);
        await page.goto(`/?${query}`);
        await expect(page.getByRole("main")).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute("data-theme", mode);

        // Fail on horizontal scroll
        const scrollWidth = await page.evaluate(
          () => document.documentElement.scrollWidth,
        );
        expect(scrollWidth).toBeLessThanOrEqual(width);

        // Fail on clipped primary actions
        const outside = await page
          .getByRole("main")
          .locator("button:visible, a.MuiButton-root:visible")
          .evaluateAll((items) =>
            items
              .filter((item) => {
                const rect = item.getBoundingClientRect();
                return (
                  rect.width > 0 &&
                  (rect.left < -1 || rect.right > window.innerWidth + 1)
                );
              })
              .map((item) => item.textContent),
          );
        expect(outside).toEqual([]);

        // Fail on input outlines below 3:1 on screens with inputs
        if (screen === "settings") {
          await verifyInputContrast(page);
        }

        await assertAccessible(page);
      }
    });
  }
}
