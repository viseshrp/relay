import { assertAccessible, test, expect, type Page } from "./a11y-test";
import { post } from "./setup-helpers";

type Fixture = {
  project: string;
  run: string;
  approval: string;
  job: string;
  workflow: string;
};
const screens = [
  "home",
  "workflows",
  "runs",
  "summary",
  "job",
  "approval",
  "settings",
] as const;
type Screen = (typeof screens)[number];

async function seed(page: Page, worst: boolean): Promise<Fixture> {
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
  const response = await post(page, "/__test__/worst-case", { enabled: worst });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

async function open(page: Page, fixture: Fixture, screen: Screen) {
  const query = new URLSearchParams({
    view: ["summary", "job", "approval"].includes(screen) ? "runs" : screen,
    project: fixture.project,
  });
  if (screen === "workflows") query.set("workflow", fixture.workflow);
  if (screen === "summary" || screen === "job") query.set("run", fixture.run);
  if (screen === "job") query.set("job", fixture.job);
  if (screen === "approval") query.set("run", fixture.approval);
  await page.goto(`/?${query}`);
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  if (screen === "workflows")
    await expect(
      page.getByText("Ready to edit", { exact: true }),
    ).toBeVisible();
  if (screen === "workflows")
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
  if (screen === "home")
    await expect(
      page.getByRole("heading", { name: "Your projects", exact: true }),
    ).toBeVisible();
  if (screen === "settings")
    await expect(
      page.getByRole("heading", { name: "Global defaults", exact: true }),
    ).toBeVisible();
  if (screen === "summary")
    await expect(
      page.getByRole("region", { name: "Step progress" }),
    ).toBeVisible();
  if (screen === "job") {
    await expect(
      page.getByRole("region", { name: "Job log", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: /Verify/ })
      .first()
      .click();
    await expect(page.getByRole("region", { name: "Step log" })).toBeVisible();
  }
  if (screen === "approval") {
    await page.getByRole("button", { name: "Respond", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Approve", exact: true }),
    ).toBeVisible();
    const heading = await page
      .getByRole("heading", { name: "Your review is needed", exact: true })
      .boundingBox();
    const header = await page.getByRole("banner").boundingBox();
    expect(
      heading && header && heading.y >= header.y + header.height,
    ).toBeTruthy();
  }
  await page.evaluate(() => document.fonts.ready);
}

async function contained(page: Page) {
  const overflow = await page.evaluate(() => ({
    width: innerWidth,
    scroll: document.documentElement.scrollWidth,
    elements: [...document.querySelectorAll("main *")]
      .filter((item) => {
        const r = item.getBoundingClientRect();
        return r.left < -1 || r.right > innerWidth + 1;
      })
      .slice(0, 8)
      .map((item) => ({
        tag: item.tagName,
        cls: item.className,
        text: item.textContent?.slice(0, 80),
      })),
  }));
  expect(overflow.scroll, JSON.stringify(overflow)).toBeLessThanOrEqual(
    overflow.width,
  );
  const outside = await page
    .getByRole("main")
    .locator("button:visible, a.MuiButton-root:visible")
    .evaluateAll((items) =>
      items
        .filter((item) => {
          const rect = item.getBoundingClientRect();
          return (
            rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1)
          );
        })
        .map((item) => item.textContent),
    );
  expect(outside).toEqual([]);
}

for (const width of [375, 768, 1440])
  for (const screen of screens) {
    test(`visual ${screen} at ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 960 });
      await page.clock.setFixedTime(new Date("2026-10-09T12:00:00Z"));
      const fixture = await seed(page, false);
      await open(page, fixture, screen);
      await contained(page);
      await assertAccessible(page);
      if (screen === "runs") {
        const typography = await page
          .locator(".run-history")
          .evaluate((root) => {
            const walker = document.createTreeWalker(
              root,
              NodeFilter.SHOW_TEXT,
            );
            const invalid: string[] = [];
            for (let text = walker.nextNode(); text; text = walker.nextNode()) {
              const element = text.parentElement;
              if (
                !text.textContent?.trim() ||
                !element?.checkVisibility({
                  checkOpacity: true,
                  checkVisibilityCSS: true,
                })
              )
                continue;
              const style = getComputedStyle(element);
              const scale =
                style.transform === "none"
                  ? 1
                  : new DOMMatrixReadOnly(style.transform).a;
              if (
                Number.parseFloat(style.fontSize) * scale < 12 ||
                !["400", "500", "600"].includes(style.fontWeight)
              )
                invalid.push(
                  `${text.textContent}: ${style.fontSize} / ${scale} / ${style.fontWeight}`,
                );
            }
            return invalid;
          });
        expect(typography).toEqual([]);
      }

      await expect(page).toHaveScreenshot(`${screen}-${width}.png`, {
        animations: "disabled",
        fullPage: false,
        mask: [
          page.locator(".path-display"),
          page.locator(".run-summary-metadata code"),
          page.locator(".history-run-title code"),
          page.locator(".history-run-time"),
        ],
        maxDiffPixelRatio: 0.01,
      });
    });
  }

for (const width of [320, 768, 1024, 1440])
  test(`worst-case screens stay contained at ${width}`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height: 960 });
    const fixture = await seed(page, true);
    for (const screen of screens) {
      await open(page, fixture, screen);
      await contained(page);
      await assertAccessible(page);
      if (screen === "runs") {
        const typography = await page
          .locator(".run-history")
          .evaluate((root) => {
            const walker = document.createTreeWalker(
              root,
              NodeFilter.SHOW_TEXT,
            );
            const invalid: string[] = [];
            for (let text = walker.nextNode(); text; text = walker.nextNode()) {
              const element = text.parentElement;
              if (
                !text.textContent?.trim() ||
                !element?.checkVisibility({
                  checkOpacity: true,
                  checkVisibilityCSS: true,
                })
              )
                continue;
              const style = getComputedStyle(element);
              const scale =
                style.transform === "none"
                  ? 1
                  : new DOMMatrixReadOnly(style.transform).a;
              if (
                Number.parseFloat(style.fontSize) * scale < 12 ||
                !["400", "500", "600"].includes(style.fontWeight)
              )
                invalid.push(
                  `${text.textContent}: ${style.fontSize} / ${scale} / ${style.fontWeight}`,
                );
            }
            return invalid;
          });
        expect(typography).toEqual([]);
      }
    }
    await open(page, fixture, "summary");
    await expect(
      page.getByRole("button", { name: "Show full title" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Show full title" }).click();
    await expect(page.getByRole("dialog")).toContainText("owner@example.test");
  });

test("project controls reserve their geometry before inventory arrives", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 960 });
  const fixture = await seed(page, true);
  let releaseInventory: () => void = () => undefined;
  let inventoryStarted: () => void = () => undefined;
  const held = new Promise<void>((resolve) => {
    releaseInventory = resolve;
  });
  const started = new Promise<void>((resolve) => {
    inventoryStarted = resolve;
  });
  await page.route("**/api/projects", async (route) => {
    inventoryStarted();
    await held;
    await route.continue();
  });
  try {
    await page.goto(`/?view=home&project=${fixture.project}`);
    await started;
    const button = page.locator(".app-header .project-context > button");
    await expect(button).toBeVisible();
    await page.addStyleTag({
      content:
        ".app-header .project-context > button { font-family: monospace; }",
    });
    await expect(page.locator(".app-header .project-picker")).toBeVisible();
    await expect(button).toHaveText("Open another project");
    await expect(button).toBeDisabled();
    const before = await button.boundingBox();
    const headerBefore = await page.getByRole("banner").boundingBox();
    releaseInventory();
    await expect(button).toBeEnabled();
    await expect(
      page.getByRole("heading", { name: "Your projects", exact: true }),
    ).toBeVisible();
    expect(await button.boundingBox()).toEqual(before);
    expect(await page.getByRole("banner").boundingBox()).toEqual(headerBefore);
  } finally {
    releaseInventory();
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
});

for (const width of [320, 375, 1440])
  test(`loading reserves space and CLS stays below 0.1 at ${width}`, async ({
    page,
  }, info) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height: 960 });
    const fixture = await seed(page, true);
    const measurements: Array<{
      screen: Screen;
      cls: number;
      shifts: object[];
    }> = [];
    await page.addInitScript(() => {
      localStorage.removeItem("relay.setup-dismissed");
      (
        window as typeof window & { testCLS: number; testShifts: object[] }
      ).testCLS = 0;
      (window as typeof window & { testShifts: object[] }).testShifts = [];
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const shift = entry as PerformanceEntry & {
            value: number;
            hadRecentInput: boolean;
            sources: Array<{
              node?: Element;
              previousRect: DOMRectReadOnly;
              currentRect: DOMRectReadOnly;
            }>;
          };
          if (!shift.hadRecentInput) {
            (
              window as typeof window & { testShifts: object[] }
            ).testShifts.push({
              value: shift.value,
              sources: shift.sources.map((source) => ({
                node: source.node?.outerHTML.slice(0, 160),
                from: source.previousRect.toJSON(),
                to: source.currentRect.toJSON(),
              })),
            });
            (window as typeof window & { testCLS: number }).testCLS +=
              shift.value;
          }
        }
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.route("**/api/**", async (route) => {
      if (
        (route.request().headers().accept ?? "").includes("text/event-stream")
      )
        return route.continue();
      const response = await route.fetch();
      const body = await response.body();
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      );
      await route.fulfill({
        status: response.status(),
        headers: response.headers(),
        body,
      });
    });
    try {
      for (const screen of screens) {
        await open(page, fixture, screen);
        await expect
          .poll(() => page.locator('[aria-busy="true"]').count())
          .toBe(0);
        await page.evaluate(
          () =>
            new Promise((resolve) =>
              requestAnimationFrame(() => requestAnimationFrame(resolve)),
            ),
        );
        const cls = await page.evaluate(
          () => (window as typeof window & { testCLS: number }).testCLS,
        );
        const shifts = await page.evaluate(
          () => (window as typeof window & { testShifts: object[] }).testShifts,
        );
        measurements.push({ screen, cls, shifts });
        expect(
          cls,
          `${screen} at ${width}: ${JSON.stringify(shifts)}`,
        ).toBeLessThan(0.1);
      }
    } finally {
      await info.attach(`layout-shifts-${width}`, {
        body: JSON.stringify(measurements, null, 2),
        contentType: "application/json",
      });
      await page.unrouteAll({ behavior: "ignoreErrors" });
    }
  });
