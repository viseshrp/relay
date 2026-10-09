import { expect, test } from "./a11y-test";
import { parseActions } from "../src/actions-workflow";
import { readableWorkflowYaml } from "../src/source-format";
import {
  post,
  advancedField,
  openJobSettings,
  closeJobSettings,
} from "./setup-helpers";

test("JSON display retains typed current workflow values and multiline scripts", () => {
  const source =
    '{"name":"Current","jobs":{"work":{"steps":[{"run":"echo hello\\necho world"}]}},"env":{"BIG":9223372036854775807,"TEXT":"true"}}';
  const displayed = readableWorkflowYaml(source);
  expect(displayed).toContain("9223372036854775807");
  expect(displayed).toContain("|-");
  expect(parseActions(displayed).document.getIn(["env", "TEXT"])).toBe("true");
});

for (const source of [
  "jobs: {work: null}",
  "jobs: {work: {steps: {run: echo}}}",
  "jobs: {work: {name: {bad: value}}}",
  "jobs: {work: {needs: [1]}}",
  "jobs: {work: {steps: [null]}}",
]) {
  test(`malformed job shapes are excluded from the graph: ${source}`, () => {
    expect(parseActions(source).value).toBeNull();
  });
}

test.describe("workspace request and form consistency", () => {
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

  test("focusing unchanged mapping fields neither changes source nor creates a draft", async ({
    page,
  }) => {
    let writes = 0;
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        /\/workflows\/.*\/(draft|save)(?:\?|$)/.test(request.url())
      )
        writes++;
    });
    await page.goto("/?view=workflows");
    await expect(
      page.getByText("Ready to edit", { exact: true }),
    ).toBeVisible();
    for (const [label, tab] of [
      ["Matrix axes", "General"],
      ["Job outputs", "Outputs"],
      ["Job environment variables", "Environment"],
      ["Step environment variables", "Steps"],
    ]) {
      const field = await advancedField(page, label, tab);
      await field.fill(" { } ");
      await field.press("Tab");
    }
    await closeJobSettings(page);
    await page.getByRole("link", { name: "Runs", exact: true }).click();
    expect(writes).toBe(0);
    expect(
      (await (await page.request.get("/api/workflows/workflow.yaml")).json())
        .draft,
    ).toBeNull();
    await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
  });

  test("leaving an edited mapping blank removes the field", async ({
    page,
  }) => {
    await page.goto("/?view=workflows");
    await expect(
      page.getByText("Ready to edit", { exact: true }),
    ).toBeVisible();
    const environment = await advancedField(page, "Environment", "Environment");
    await environment.fill('"production"');
    await environment.press("Tab");
    await expect(page.locator(".cm-content")).toContainText(
      "environment: production",
    );
    await environment.fill("");
    await environment.press("Tab");
    await expect(page.locator(".cm-content")).not.toContainText(
      "environment: production",
    );
  });

  test("a newer frontend offers a reload and saves the current edit first", async ({
    page,
  }) => {
    await page.route(/^http:\/\/[^/]+\/$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: '<html><script type="module" src="/assets/new-version.js"></script></html>',
      }),
    );
    await page.goto("/?view=workflows");
    await expect(
      page.getByText("Ready to edit", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Reload Relay", exact: true }),
    ).toBeVisible();
    await openJobSettings(page, "General");
    await page
      .getByRole("textbox", { name: "Job name", exact: true })
      .fill("Current edit");
    await closeJobSettings(page);
    await page
      .getByRole("button", { name: "Reload Relay", exact: true })
      .click();
    await expect(page.locator(".cm-content")).toContainText("Current edit");
    const document = await (
      await page.request.get("/api/workflows/workflow.yaml")
    ).json();
    expect(document.draft.yaml).toContain("Current edit");
  });

  test("optional update discovery failure does not create a startup error", async ({
    page,
  }) => {
    await page.route(/^http:\/\/[^/]+\/$/, (route) =>
      route.fulfill({ status: 503, body: "Unavailable" }),
    );
    await page.goto("/?view=workflows");
    await expect(
      page.getByText("Ready to edit", { exact: true }),
    ).toBeVisible();
    await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
  });
  test("a canceled lease failure cannot appear in the next workflow", async ({
    page,
  }) => {
    await page.addInitScript(() =>
      sessionStorage.setItem("relay.editor-holder", "fixture"),
    );
    expect(
      (
        await post(page, "/api/workflows", {
          key: "next",
          holder: "fixture",
          yaml: "name: Next workflow\njobs: {check: {steps: [{run: echo next}]}}\n",
        })
      ).ok(),
    ).toBeTruthy();
    let release!: () => void;
    let received = false;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      /\/api\/workflows\/workflow\.yaml\/lease(?:\?|$)/,
      async (route) => {
        received = true;
        await gate;
        await route
          .fulfill({
            status: 405,
            json: {
              code: "method_not_allowed",
              message: "Stale lease failure",
              context: {},
            },
          })
          .catch(() => undefined);
      },
    );
    try {
      await page.goto("/?view=workflows&workflow=workflow.yaml");
      await expect.poll(() => received).toBe(true);
      await page
        .getByRole("combobox", { name: "Workflow", exact: true })
        .click();
      await page
        .getByRole("option", { name: "Next workflow", exact: true })
        .click();
      await expect(
        page.getByText("Ready to edit", { exact: true }),
      ).toBeVisible();
      release();
      await page.unrouteAll({ behavior: "wait" });
      await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
      await expect(page.locator(".cm-content")).toContainText("Next workflow");
    } finally {
      release();
    }
  });

  test("a canceled settings read cannot overwrite a reopened dialog", async ({
    page,
  }) => {
    await page.goto("/?view=workflows");
    await expect(
      page.getByText("Ready to edit", { exact: true }),
    ).toBeVisible();
    let release!: () => void;
    let reads = 0;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(/\/api\/workflow-bindings(?:\?|$)/, async (route) => {
      if (++reads !== 1) {
        await route.continue();
        return;
      }
      await gate;
      await route
        .fulfill({
          status: 405,
          json: {
            code: "method_not_allowed",
            message: "Stale settings failure",
            context: {},
          },
        })
        .catch(() => undefined);
    });
    try {
      await page
        .getByRole("button", {
          name: "Variables, secrets, environments and library",
          exact: true,
        })
        .click();
      await expect.poll(() => reads).toBe(1);
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Close", exact: true })
        .click();
      await page
        .getByRole("button", {
          name: "Variables, secrets, environments and library",
          exact: true,
        })
        .click();
      await expect.poll(() => reads).toBe(2);
      release();
      await page.unrouteAll({ behavior: "wait" });
      await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
    } finally {
      release();
    }
  });

  test("the captured workflow viewer displays current JSON as YAML", async ({
    page,
  }) => {
    const source = JSON.stringify({
      name: "Captured current source",
      jobs: { check: { steps: [{ run: "echo current" }] } },
    });
    expect(
      (
        await post(page, "/api/workflows", {
          key: "capture",
          holder: "fixture",
          yaml: source,
        })
      ).ok(),
    ).toBeTruthy();
    expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
    const launched = await post(page, "/api/runs", {
      workflow_key: "capture",
      inputs: {},
    });
    expect(launched.ok(), await launched.text()).toBeTruthy();
    const { run_id } = await launched.json();
    await page.goto(`/?view=runs&run=${run_id}`);
    await page
      .getByRole("button", { name: "Workflow file", exact: true })
      .click();
    const preview = page
      .getByRole("dialog", { name: "Workflow file", exact: true })
      .getByLabel("Captured workflow YAML", { exact: true });
    await expect(preview).toContainText("name: Captured current source");
    await expect(preview).not.toContainText('"jobs"');
  });

  test("a late save failure cannot appear in another workflow", async ({
    page,
  }) => {
    await page.addInitScript(() =>
      sessionStorage.setItem("relay.editor-holder", "fixture"),
    );
    expect(
      (
        await post(page, "/api/workflows", {
          key: "save-destination",
          holder: "fixture",
          yaml: "name: Save destination\njobs: {check: {steps: [{run: echo next}]}}\n",
        })
      ).ok(),
    ).toBeTruthy();
    let release!: () => void;
    let received = false;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      /\/api\/workflows\/workflow\.yaml\/save(?:\?|$)/,
      async (route) => {
        received = true;
        await gate;
        await route.fulfill({
          status: 409,
          json: {
            code: "conflict",
            message: "Previous workflow save failed",
            context: {},
          },
        });
      },
    );
    try {
      await page.goto("/?view=workflows&workflow=workflow.yaml");
      await expect(
        page.getByText("Ready to edit", { exact: true }),
      ).toBeVisible();
      await openJobSettings(page, "General");
      await page
        .getByRole("textbox", { name: "Job name", exact: true })
        .fill("Changed first workflow");
      await closeJobSettings(page);
      await expect(
        page.getByRole("button", { name: "Save", exact: true }),
      ).toBeEnabled();
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect.poll(() => received).toBe(true);
      await page
        .getByRole("combobox", { name: "Workflow", exact: true })
        .click();
      await page
        .getByRole("option", { name: "Save destination", exact: true })
        .click();
      await expect(page.locator(".cm-content")).toContainText(
        "Save destination",
      );
      release();
      await page.unrouteAll({ behavior: "wait" });
      await expect(
        page.getByText("Ready to edit", { exact: true }),
      ).toBeVisible();
      await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "Save", exact: true }),
      ).toBeDisabled();
    } finally {
      release();
    }
  });
});
