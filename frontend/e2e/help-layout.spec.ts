import { expect, test, type Locator, type Page } from "./a11y-test";
import { openAdvanced, openJobSettings, post } from "./setup-helpers";

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

for (const width of [320, 390, 760, 1440])
  test(`help stays beside labels at ${width}px without changing settings`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/?view=settings");
    const shared = page.getByRole("textbox", {
      name: "Shared default model",
      exact: true,
    });
    await expect(shared).toBeVisible();
    const before = await (await page.request.get("/api/settings")).json();
    for (const field of await page
      .locator(".settings-content .help-field:visible")
      .all()) {
      await field.scrollIntoViewIfNeeded();
      const { label, about, input } = await field.evaluate((element) => {
        const box = (selector: string) => {
          const rect = element.querySelector(selector)?.getBoundingClientRect();
          return rect
            ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
            : null;
        };
        return {
          label: box("label"),
          about: box(".help-tip button"),
          input: box(".MuiInputBase-root"),
        };
      });
      if (!label || !about || !input)
        throw new Error("A help field is missing its label, button, or input.");
      expect(about.x - (label.x + label.width)).toBeGreaterThanOrEqual(3);
      expect(about.x - (label.x + label.width)).toBeLessThanOrEqual(8);
      expect(
        Math.abs(about.y + about.height / 2 - (label.y + label.height / 2)),
        await field.locator("label").innerText(),
      ).toBeLessThanOrEqual(1);
      expect(input.y - (about.y + about.height)).toBeGreaterThanOrEqual(5);
    }
    const button = page.getByRole("button", {
      name: "About Shared default model",
      exact: true,
    });
    await button.scrollIntoViewIfNeeded();
    await button.focus();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toContainText("case-sensitive");
    const box = await tooltip.boundingBox();
    if (!box) throw new Error("Expected a visible help tooltip.");
    expect(box.x).toBeGreaterThanOrEqual(10);
    expect(box.x + box.width).toBeLessThanOrEqual(width - 10);
    await button.press("Escape");
    await expect(tooltip).toBeHidden();
    await expect(button).toBeFocused();
    await page
      .getByRole("navigation", { name: "Settings sections" })
      .getByRole("button", { name: "Server and account", exact: true })
      .click();
    const port = await page
      .getByRole("spinbutton", { name: "Port", exact: true })
      .boundingBox();
    if (!port) throw new Error("Expected the server port field.");
    await expect(
      page.getByRole("spinbutton", { name: "Workers", exact: true }),
    ).toHaveCount(0);
    const login = page.getByRole("switch", {
      name: "Require login",
      exact: true,
    });
    await expect(login).toBeChecked();
    await page
      .getByRole("button", { name: "About Require login", exact: true })
      .click();
    await expect(tooltip).toBeVisible();
    await expect(login).toBeChecked();
    await page.keyboard.press("Escape");
    expect(
      (await (await page.request.get("/api/settings")).json()).revision,
    ).toBe(before.revision);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: info.outputPath(`help-${width}.png`),
      fullPage: true,
      animations: "disabled",
    });
  });

test("welcome screenshots are decoded, highlighted accurately, and use a desktop split", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Account menu for owner", exact: true })
    .click();
  await page
    .getByRole("menuitem", { name: "Welcome slides", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Welcome to Relay" });
  for (let index = 0; index < 4; index++) {
    await dialog
      .getByRole("button", { name: new RegExp(`^Show slide ${index + 1}:`) })
      .click();
    const slide = dialog.getByRole("group", {
      name: `${index + 1} of 4`,
      exact: true,
    });
    await expect(slide).toBeVisible();
    await expect
      .poll(async () => {
        const box = await slide.boundingBox();
        const viewport = await dialog
          .locator(".welcome-viewport")
          .boundingBox();
        return Boolean(box && viewport && Math.abs(box.x - viewport.x) < 1);
      })
      .toBeTruthy();
    const image = slide.getByRole("img");
    await expect
      .poll(() =>
        image.evaluate(
          (element: HTMLImageElement) =>
            element.complete && element.naturalWidth >= 1200,
        ),
      )
      .toBeTruthy();
    const frame = await slide.locator(".onboarding-screen").boundingBox();
    const focus = await slide.locator(".onboarding-highlight").boundingBox();
    const copy = await slide.locator(".welcome-slide-copy").boundingBox();
    if (!frame || !focus || !copy)
      throw new Error(
        "A welcome slide is missing its screenshot, highlight, or text.",
      );
    expect(focus.x).toBeGreaterThan(frame.x);
    expect(focus.y).toBeGreaterThan(frame.y);
    expect(focus.x + focus.width).toBeLessThan(frame.x + frame.width);
    expect(focus.y + focus.height).toBeLessThan(frame.y + frame.height);
    expect(copy.x).toBeGreaterThan(frame.x + frame.width);
    await page.screenshot({
      path: info.outputPath(`welcome-${index + 1}.png`),
      animations: "disabled",
    });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const selected = dialog.getByRole("group", { name: "4 of 4", exact: true });
  await expect
    .poll(async () => {
      const frame = await selected.locator(".onboarding-image").boundingBox();
      const copy = await selected.locator(".welcome-slide-copy").boundingBox();
      return Boolean(frame && copy && copy.y >= frame.y + frame.height);
    })
    .toBeTruthy();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: info.outputPath("welcome-mobile.png"),
    animations: "disabled",
  });
});

/** Visible fields in `area` that no help button covers. */
async function unhelped(area: Locator): Promise<string[]> {
  const fields = await area.evaluate(
    (root) =>
      [
        ...root.querySelectorAll(
          ".MuiFormControl-root, .MuiFormControlLabel-root, .MuiToggleButtonGroup-root",
        ),
      ].filter((field) => field.checkVisibility({ visibilityProperty: true }))
        .length,
  );
  // An empty tab would pass without checking anything.
  expect(fields).toBeGreaterThan(0);
  return area.evaluate((root) =>
    [
      ...root.querySelectorAll(
        ".MuiFormControl-root, .MuiFormControlLabel-root, .MuiToggleButtonGroup-root",
      ),
    ]
      .filter((field) => field.checkVisibility({ visibilityProperty: true }))
      .filter(
        (field) =>
          !field
            .closest(".help-field, .help-control, .help-group")
            ?.querySelector(".help-tip button"),
      )
      .map(
        (field) =>
          field.getAttribute("aria-label") ||
          field.textContent ||
          field.outerHTML.slice(0, 120),
      ),
  );
}

async function expectHelp(page: Page, title: string, description: string) {
  await page
    .getByRole("button", { name: `About ${title}`, exact: true })
    .click();
  await expect(
    page.getByRole("tooltip").locator(".help-tip-description"),
  ).toHaveText(description);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toBeHidden();
}

test("every job and step field has help", async ({ page }) => {
  const { property_descriptions: descriptions } = await (
    await page.request.get("/api/workflow-language")
  ).json();
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const samples: Array<[string, string, string]> = [
    ["General", "Job name", "job-factory.name"],
    ["Steps", "Step name", "regular-step.name"],
    ["Outputs", "Job outputs", "job-factory.outputs"],
    ["Environment", "Job environment variables", "job-factory.env"],
    [
      "When it fails",
      "Continue after this job fails",
      "job-factory.continue-on-error",
    ],
  ];
  for (const [tab, title, key] of samples) {
    await openJobSettings(page, tab);
    if (tab === "General" || tab === "Steps") await openAdvanced(page);
    // An empty outputs table has only its Add button.
    if (tab === "Outputs")
      await page
        .getByRole("button", { name: "Add Job outputs entry", exact: true })
        .click();
    const panel = page.getByRole("tabpanel");
    expect(await unhelped(panel), tab).toEqual([]);
    await expectHelp(page, title, descriptions[key]);
  }
});

test("every workflow settings field has help", async ({ page }) => {
  const { property_descriptions: descriptions } = await (
    await page.request.get("/api/workflow-language")
  ).json();
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Workflow settings", exact: true })
    .click();
  const source = page.getByRole("dialog", { name: "Workflow settings" });
  await source.getByRole("button", { name: "Add workflow input" }).click();
  await source.getByText("Advanced workflow schema fields").click();
  expect(await unhelped(source)).toEqual([]);
  await expectHelp(page, "Workflow name", descriptions["workflow-root.name"]);
  await source.getByRole("button", { name: "Done", exact: true }).click();
  await page
    .getByRole("button", {
      name: "Variables, secrets, environments and library",
      exact: true,
    })
    .click();
  const settings = page.getByRole("dialog", { name: "Workflow settings" });
  for (const tab of [
    "Variables and secrets",
    "Environments",
    "Workflow library",
  ]) {
    await settings.getByRole("tab", { name: tab, exact: true }).click();
    expect(await unhelped(settings), tab).toEqual([]);
  }
});
