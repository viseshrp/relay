import { expect, test } from "./a11y-test";
import { post, runStarter, openSettings } from "./setup-helpers";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});

test("setup completes a starter run without login", async ({
  page,
}, testInfo) => {
  await page.request.get("/api/auth");
  await runStarter(page, "ask-agent", "Ask an agent", testInfo);
  await expect(page.getByText("Login disabled", { exact: true })).toHaveCount(
    0,
  );
});

test("header navigation stays reachable on phones and desktops without login", async ({
  page,
}, info) => {
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/?view=settings");
    await expect(
      page.getByRole("heading", { name: "Global defaults", exact: true }),
    ).toBeVisible();
    const header = page.locator(".app-header");
    for (const fallbackFont of [false, true]) {
      if (fallbackFont)
        await page.addStyleTag({
          content:
            ".app-header .MuiButtonBase-root { font-family: Arial, sans-serif; letter-spacing: 0.08em; }",
        });
      if (width < 480) {
        const navigate = header.getByRole("button", {
          name: "Navigate",
          exact: true,
        });
        await expect(navigate).toBeVisible();
        const bounds = await navigate.boundingBox();
        expect(
          bounds && bounds.x >= 0 && bounds.x + bounds.width <= width,
        ).toBeTruthy();
        await navigate.click();
        const menu = page.getByRole("menu");
        for (const name of ["Workflows", "Runs", "Settings"])
          await expect(
            menu.getByRole("menuitem", { name, exact: true }),
          ).toBeVisible();
        await page.keyboard.press("Escape");
      } else {
        const navigation = header.getByRole("navigation", {
          name: "Main navigation",
          exact: true,
        });
        const bounds = await navigation.boundingBox();
        if (!bounds) throw new Error("Navigation must have visible bounds.");
        for (const name of ["Workflows", "Runs", "Settings"]) {
          const control = navigation.getByRole("link", { name, exact: true });
          await expect(control).toBeEnabled();
          await expect(control).toHaveCSS("opacity", "1");
          const link = await control.boundingBox();
          if (!link)
            throw new Error(`The ${name} link must have visible bounds.`);
          expect(link.x).toBeGreaterThanOrEqual(bounds.x - 1);
          expect(link.x + link.width).toBeLessThanOrEqual(
            bounds.x + bounds.width + 1,
          );
          expect(link.width).toBeGreaterThanOrEqual(44);
        }
      }
    }
    await header.screenshot({
      path: info.outputPath(`header-local-${width}.png`),
      animations: "disabled",
    });
  }
});

test("a fresh local app opens and runs a workflow without an owner login", async ({
  page,
}) => {
  await page.goto("/?view=workflows");
  await expect(page.getByText("Login disabled", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("textbox", { name: "Password", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Add job", exact: true }),
  ).toBeEnabled();
  expect(await (await page.request.get("/api/auth")).json()).toMatchObject({
    owner_created: false,
    authenticated: true,
    username: "local",
    login_required: false,
  });
  expect(
    (await page.context().cookies()).some(
      (cookie) => cookie.name === "relay_sessionid",
    ),
  ).toBeFalsy();

  const token = (await page.context().cookies()).find(
    (cookie) => cookie.name === "relay_csrftoken",
  );
  const headers = { "X-CSRFToken": token?.value ?? "" };
  const workflow = await page.request.post("/api/workflows", {
    headers,
    data: {
      key: "local-run",
      holder: "local-browser",
      yaml: "name: Local run\njobs: {work: {steps: [{run: git status}]}}\n",
    },
  });
  expect(workflow.ok(), await workflow.text()).toBeTruthy();
  expect(
    (await page.request.post("/__test__/commit", { headers })).ok(),
  ).toBeTruthy();
  const launched = await page.request.post("/api/runs", {
    headers,
    data: { workflow_key: "local-run", inputs: {} },
  });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(
    page.locator(".run-header").getByRole("heading", { name: /Local run #/ }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText("Login disabled", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.locator(".run-header").getByRole("heading", { name: /Local run #/ }),
  ).toBeVisible();
});

test.describe("First-use introduction without login", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test("welcome and tour can be skipped once without creating an owner account", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(
      page.getByRole("dialog", { name: "Welcome to Relay", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Skip introduction", exact: true })
      .click();
    await expect(page.locator(".relay-tour")).toHaveCount(0);
    await page.reload();
    await expect(
      page.getByRole("main", { name: "Relay home", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("dialog", { name: "Welcome to Relay", exact: true }),
    ).toHaveCount(0);
    await expect(page.locator(".relay-tour")).toHaveCount(0);
    await openSettings(page);
    await page
      .getByRole("button", { name: "Server and account", exact: true })
      .click();
    await expect(
      page.getByText(
        "Login is disabled. This browser uses local access without signing in.",
        { exact: true },
      ),
    ).toBeVisible();
    expect(
      (await (await page.request.get("/api/auth")).json()).owner_created,
    ).toBe(false);
  });
});
