import { historicalPost, currentWorkflow } from "./setup-helpers";
import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

async function post(page: Page, path: string, data: object = {}) {
  return historicalPost(page, path, data);
}

async function save(page: Page) {
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const confirmation = page.getByRole("button", {
    name: "Save canonical YAML",
    exact: true,
  });
  if (await confirmation.isVisible()) await confirmation.click();
  await expect(page.getByText("Workflow saved and validated.")).toBeVisible();
}

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
  await page.goto("/?view=workflows");
  await expect(
    page.getByRole("button", { name: "Add job", exact: true }),
  ).toBeEnabled();
});

test("create a workflow, inspect connected progress, reload its review, and explicitly continue", async ({
  page,
}, testInfo) => {
  await page
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  await page.getByLabel("Workflow name").fill("Guided browser flow");
  await page
    .getByRole("dialog", { name: "Choose a workflow" })
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Guided browser flow", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.getByLabel("Job name", { exact: true }).fill("Check project");
  await page.getByLabel("Script", { exact: true }).fill("git status --short");
  await page.getByRole("button", { name: "Add job", exact: true }).click();
  await page.getByLabel("Job name", { exact: true }).fill("Owner review");
  await page.getByLabel("Needs (comma separated)").fill("check");
  await page.getByLabel("Action reference").fill("relay/human-wait@v1");
  const input = page.getByLabel("Action inputs", { exact: true });
  await input.fill(
    JSON.stringify({
      prompt: "Review the command result. Type AGREE to continue.",
    }),
  );
  await input.blur();
  await page.getByLabel("Step name", { exact: true }).fill("Owner review");
  await save(page);
  const launch = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("region", { name: "Workflow header" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Run workflow" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const created = await launch;
  expect(created.status()).toBe(201);
  const { run_id: runId } = await created.json();
  await page
    .getByRole("region", { name: "Waiting for you", exact: true })
    .getByRole("button", { name: "Respond", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your review is needed" }),
  ).toBeVisible();
  await expect(
    page.getByText("Choose Respond above to continue this job."),
  ).toBeVisible();
  await expect(
    page.locator('.react-flow__edge[data-id="root.check:root.job_1"]'),
  ).toHaveCount(1);
  await expect(page.locator(".react-flow__edge")).toHaveCount(6);
  await expect(
    page.getByRole("button", { name: "Send response and continue" }),
  ).toBeDisabled();
  const href = await page
    .getByRole("link", { name: "Link to request" })
    .getAttribute("href");
  expect(href).toContain(`run=${runId}`);
  expect(href).toContain("interaction=");
  await page.goto(href!);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Your review is needed" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Jobs", exact: true })
      .getByRole("button", { name: /^Owner review Waiting/ })
      .first(),
  ).toBeVisible();
  const detail = (
    await (
      await page.request.get(
        `/api/runs/${runId}?collection=interactions&pending=true`,
      )
    ).json()
  ).run;
  expect(detail.status).toBe("paused_wait");
  expect(detail.interactions).toHaveLength(1);
  const stream = `**/api/runs/${runId}/stream?since=*`;
  const scope = detail.interactions[0].scope_path;
  const frames = [
    {
      id: detail.event_cursor - 3,
      type: "node.running",
      payload: { scope_path: scope, status: "running" },
    },
    {
      id: detail.event_cursor - 2,
      type: "run.failed",
      payload: { status: "failed" },
    },
    {
      id: detail.event_cursor + 1,
      type: "run.failed",
      payload: { status: "failed" },
    },
    {
      id: detail.event_cursor + 2,
      type: "command.stdout",
      payload: {
        scope_path: scope,
        attempt_number: 1,
        chunk: "New output after an old failed attempt.\n",
      },
    },
  ].map((item) => ({
    ...item,
    version: 1,
    source: "system",
    ts: new Date().toISOString(),
  }));
  await page.route(stream, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: frames
        .map(
          (item) =>
            `id: ${item.id}\nevent: ${item.type}\ndata: ${JSON.stringify(item)}\n\n`,
        )
        .join(""),
    }),
  );
  await page.reload();
  await expect(
    page.getByText("New output after an old failed attempt.", { exact: false }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Jobs", exact: true })
      .getByRole("button", { name: /^Owner review Waiting/ })
      .first(),
  ).toBeVisible();
  await page.unroute(stream);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Your review is needed" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("guided-review.png"),
    fullPage: true,
  });
  await page.getByLabel("Your response", { exact: true }).fill("AGREE");
  await page
    .getByRole("button", { name: "Send response and continue" })
    .click();
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /Guided browser flow #/ }),
  ).toBeVisible();
  await expect(
    page.getByText("Complete", { exact: true }).first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Open changes and documents" })
    .click();
  await expect(page.getByText("No committed code changes yet.")).toBeVisible();
  await page
    .getByText("Advanced diagnostics and saved files", { exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: /^(Retry temporary resource cleanup|Clean data|Review deletion)$/i,
    }),
  ).toHaveCount(0);
});

test("report handoffs explain retention and review material is readable beside the response", async ({
  page,
}) => {
  expect((await post(page, "/__test__/report")).ok()).toBeTruthy();
  const yaml = stringify({
    name: "Retained review",
    jobs: {
      report: {
        steps: [
          {
            id: "retained",
            uses: "relay/validate-report@v1",
            with: { path: "REVIEW.md", format: "label", label: "Ready" },
          },
          {
            uses: "relay/human-wait@v1",
            with: {
              prompt: "Read REVIEW.md, inspect changes, and respond REVIEWED.",
            },
          },
        ],
      },
    },
  });
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const created = await post(page, "/api/workflows", {
    key: "retained-review",
    holder,
    yaml,
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  await page.goto("/?view=workflows&workflow=retained-review.yaml");
  await expect(
    page.getByLabel("Action reference", { exact: true }),
  ).toHaveValue("relay/validate-report@v1");
  await expect(page.getByLabel("Action inputs", { exact: true })).toContainText(
    "REVIEW.md",
  );
  await page
    .getByRole("region", { name: "Workflow header" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Run workflow" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  await page
    .getByRole("region", { name: "Waiting for you", exact: true })
    .getByRole("button", { name: "Respond", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your review is needed" }),
  ).toBeVisible();
  await page.getByRole("combobox", { name: "Review material" }).click();
  await page.getByRole("option", { name: "REVIEW.md", exact: true }).click();
  await expect(page.locator(".review-preview")).toContainText("Ready: Yes");
  await expect(page.locator(".review-preview")).toContainText(
    "Read this report before approving.",
  );
  await expect(
    page.getByRole("button", { name: "Send response and continue" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Cancel run", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel run", exact: true })
    .click();
  await expect(
    page.getByText(
      "Work stopped. Finished jobs and their changes remain available for review.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /Retained review #/ }),
  ).toBeVisible();
  await expect(
    page.getByText("Stopped", { exact: true }).first(),
  ).toBeVisible();
});

test("permission requests send owner feedback through the same agent session", async ({
  page,
}) => {
  expect((await post(page, "/__test__/feedback-provider")).ok()).toBeTruthy();
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const created = await post(page, "/api/workflows", {
    key: "agent-feedback",
    holder,
    yaml: stringify(
      currentWorkflow({
        version: 1,
        name: "Feedback",
        model: "m1",
        agents: ["codex"],
        nodes: { work: { type: "agent" } },
      }),
    ),
  });
  expect(created.ok()).toBeTruthy();
  await page.goto("/?view=author&workflow=agent-feedback.yaml");
  await page
    .getByRole("region", { name: "Workflow header" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Run workflow" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  await page
    .getByRole("region", { name: "Waiting for you", exact: true })
    .getByRole("button", { name: "Respond", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "A tool needs your permission" }),
  ).toBeVisible();
  await page.getByRole("combobox", { name: "Your decision" }).click();
  await page.getByRole("option", { name: "Allow once", exact: true }).click();
  await page
    .getByLabel("Feedback for the agent (optional)")
    .fill("Also check the selected project.");
  await page
    .getByRole("button", { name: "Send response and continue" })
    .click();
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
    ),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Activity feed", exact: true })
      .getByText("ready", { exact: true }),
  ).toBeVisible();
});

test("a review completed during initial loading updates progress before the stream opens", async ({
  page,
}) => {
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  expect(
    (
      await post(page, "/api/workflows", {
        key: "loading-review",
        holder,
        yaml: stringify({
          version: 1,
          name: "Loading review",
          nodes: {
            review: { type: "human_wait", prompt: "Respond REVIEWED." },
          },
        }),
      })
    ).ok(),
  ).toBeTruthy();
  const launched = await post(page, "/api/runs", {
    workflow_key: "loading-review",
    inputs: {},
  });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  let pending: { id: string; attempt_id: string } | undefined;
  await expect
    .poll(async () => {
      const response = await page.request.get(
        `/api/runs/${runId}?collection=interactions&pending=true`,
      );
      pending = (await response.json()).run.interactions[0];
      return pending !== undefined;
    })
    .toBeTruthy();
  let releaseDetails!: () => void;
  let capturedDetails!: () => void;
  const released = new Promise<void>((resolve) => {
    releaseDetails = resolve;
  });
  const captured = new Promise<void>((resolve) => {
    capturedDetails = resolve;
  });
  let snapshots = 0;
  await page.route(`**/api/runs/${runId}?collection=*`, async (route) => {
    if (snapshots >= 2) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const body = await response.json();
    snapshots += 1;
    if (snapshots === 2) capturedDetails();
    await released;
    await route.fulfill({ response, json: body });
  });
  await page.route(`**/api/runs/${runId}/events?*`, async (route) => {
    await captured;
    expect(
      (
        await post(page, `/api/attempts/${pending!.attempt_id}/wait`, {
          interaction_id: pending!.id,
          idempotency_key: "loading-review-answer",
          value: "REVIEWED",
        })
      ).ok(),
    ).toBeTruthy();
    await expect
      .poll(
        async () =>
          (await (await page.request.get(`/api/runs/${runId}`)).json()).run
            .status,
      )
      .toBe("succeeded");
    releaseDetails();
    await route.continue();
  });
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
    ),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Jobs", exact: true })
      .locator('[data-job-scope="root.review"]'),
  ).toContainText("Complete");
  await expect(
    page.getByRole("heading", { name: "Your review is needed" }),
  ).toBeHidden();
});
