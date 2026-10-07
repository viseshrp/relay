import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

async function post(page: Page, path: string, data: object = {}) {
  const csrf = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  return page.request.post(path, { data, headers: { "X-CSRFToken": csrf?.value ?? "" } });
}

async function save(page: Page) {
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const confirmation = page.getByRole("button", { name: "Save canonical YAML", exact: true });
  if (await confirmation.isVisible()) await confirmation.click();
  await expect(page.getByText("Workflow saved and validated.")).toBeVisible();
}

async function addStage(page: Page, name: string, action: string) {
  await page.getByRole("button", { name: "Add stage", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add a stage" });
  await dialog.getByLabel("Stage name").fill(name);
  await dialog.getByRole("combobox", { name: "Stage action" }).click();
  await page.getByRole("option", { name: action, exact: true }).click();
  await dialog.getByRole("button", { name: "Add stage", exact: true }).click();
  await expect(dialog).toBeHidden();
}

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
});

test("create a workflow, inspect connected progress, reload its review, and explicitly continue", async ({ page }, testInfo) => {
  await page.getByRole("button", { name: "New workflow" }).click();
  await page.getByLabel("Workflow name").fill("Guided browser flow");
  await page.getByRole("button", { name: "Create workflow", exact: true }).click();
  await expect(page.getByText("Your workflow is empty.", { exact: false })).toBeVisible();
  await addStage(page, "Check project", "Run a command");
  await page.getByLabel("Arguments (one per line)").fill("status\n--short");
  await addStage(page, "Owner review", "Ask for human review");
  await page.getByLabel("Review instructions and expected response").fill("Review the command result. Type AGREE to continue.");
  await save(page);
  const launch = page.waitForResponse((response) => response.url().endsWith("/api/runs") && response.request().method() === "POST");
  await page.getByRole("region", { name: "Workflow header" }).getByRole("button", { name: "Run workflow" }).click();
  await page.getByRole("dialog", { name: "Run workflow" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  const created = await launch;
  expect(created.status()).toBe(201);
  const { run_id: runId } = await created.json();
  await page.getByRole("region", { name: "Waiting for you", exact: true }).getByRole("button", { name: "Respond", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your review is needed" })).toBeVisible();
  await expect(page.getByText("Choose Respond above to continue this job.")).toBeVisible();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Send response and continue" })).toBeDisabled();
  const href = await page.getByRole("link", { name: "Link to request" }).getAttribute("href");
  expect(href).toContain(`run=${runId}`);
  expect(href).toContain("interaction=");
  await page.goto(href!);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Your review is needed" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Jobs", exact: true }).getByRole("button", { name: /^Owner review Waiting/ })).toBeVisible();
  const detail = (await (await page.request.get(`/api/runs/${runId}?collection=interactions&pending=true`)).json()).run;
  expect(detail.status).toBe("paused_wait");
  expect(detail.interactions).toHaveLength(1);
  const stream = `**/api/runs/${runId}/stream?since=*`;
  const scope = detail.interactions[0].scope_path;
  const frames = [
    { id: detail.event_cursor - 3, type: "node.running", payload: { scope_path: scope, status: "running" } },
    { id: detail.event_cursor - 2, type: "run.failed", payload: { status: "failed" } },
    { id: detail.event_cursor + 1, type: "run.failed", payload: { status: "failed" } },
    { id: detail.event_cursor + 2, type: "command.stdout", payload: { scope_path: scope, attempt_number: 1, chunk: "New output after an old failed attempt.\n" } },
  ].map((item) => ({ ...item, version: 1, source: "system", ts: new Date().toISOString() }));
  await page.route(stream, (route) => route.fulfill({ contentType: "text/event-stream", body: frames.map((item) => `id: ${item.id}\nevent: ${item.type}\ndata: ${JSON.stringify(item)}\n\n`).join("") }));
  await page.reload();
  await expect(page.getByText("New output after an old failed attempt.", { exact: false })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Jobs", exact: true }).getByRole("button", { name: /^Owner review Waiting/ })).toBeVisible();
  await page.unroute(stream);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Your review is needed" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("guided-review.png"), fullPage: true });
  await page.getByLabel("Your response", { exact: true }).fill("AGREE");
  await page.getByRole("button", { name: "Send response and continue" }).click();
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Guided browser flow Complete ·/ })).toBeVisible();
  await page.getByRole("button", { name: "Open changes and documents" }).click();
  await expect(page.getByText("No committed code changes yet.")).toBeVisible();
  await page.getByText("Advanced diagnostics and saved files", { exact: true }).click();
  await page.getByRole("button", { name: "Retry temporary resource cleanup" }).click();
});

test("report handoffs explain retention and review material is readable beside the response", async ({ page }) => {
  expect((await post(page, "/__test__/report")).ok()).toBeTruthy();
  const config = {
    version: 1, name: "Retained review",
    nodes: {
      report: { type: "command", run: ["git", "status"], outputs: { verdict: { label: { artifact: "REVIEW.md", label: "Ready" } }, ready: { exists: "REVIEW.md" } } },
      review: { type: "human_wait", needs: ["report"], prompt: "Read REVIEW.md, inspect changes, and respond REVIEWED." },
    },
  };
  const source = await page.request.get("/api/projects/current");
  const project = (await source.json()).project;
  const yaml = stringify(config);
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const created = await post(page, "/api/workflows", { key: "retained-review", name: "Retained review", holder });
  expect(created.ok()).toBeTruthy();
  const document = await page.request.get("/api/workflows/retained-review.yaml");
  const saved = await post(page, "/api/workflows/retained-review.yaml/save", { holder, yaml, base_hash: (await document.json()).base_hash });
  expect(saved.ok()).toBeTruthy();
  await page.goto(`/?view=author&project=${project.id}&workflow=retained-review.yaml`);
  await expect(page.getByRole("button", { name: "Retain the report" })).toBeVisible();
  await page.getByRole("button", { name: "Retain the report" }).click();
  await expect(page.getByRole("dialog", { name: "Keep a report for the next stage" })).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("region", { name: "Workflow header" }).getByRole("button", { name: "Run workflow" }).click();
  await page.getByRole("dialog", { name: "Run workflow" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  await page.getByRole("region", { name: "Waiting for you", exact: true }).getByRole("button", { name: "Respond", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your review is needed" })).toBeVisible();
  await page.getByRole("combobox", { name: "Review material" }).click();
  await page.getByRole("option", { name: "REVIEW.md", exact: true }).click();
  await expect(page.locator(".review-preview")).toContainText("Ready: Yes");
  await expect(page.locator(".review-preview")).toContainText("Read this report before approving.");
  await expect(page.getByRole("button", { name: "Send response and continue" })).toBeDisabled();
  await page.getByRole("button", { name: "Cancel run" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel run" }).click();
  await expect(page.getByText("Work stopped. Finished steps and their changes remain available for review.")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Retained review Stopped ·/ })).toBeVisible();
});

test("permission requests send owner feedback through the same agent session", async ({ page }) => {
  expect((await post(page, "/__test__/feedback-provider")).ok()).toBeTruthy();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const created = await post(page, "/api/workflows", { key: "agent-feedback", holder, yaml: stringify({ version: 1, name: "Feedback", model: "m1", agents: ["codex"], nodes: { work: { type: "agent" } } }) });
  expect(created.ok()).toBeTruthy();
  await page.goto("/?view=author&workflow=agent-feedback.yaml");
  await page.getByRole("region", { name: "Workflow header" }).getByRole("button", { name: "Run workflow" }).click();
  await page.getByRole("dialog", { name: "Run workflow" }).getByRole("button", { name: "Run workflow", exact: true }).click();
  await page.getByRole("region", { name: "Waiting for you", exact: true }).getByRole("button", { name: "Respond", exact: true }).click();
  await expect(page.getByRole("heading", { name: "A tool needs your permission" })).toBeVisible();
  await page.getByRole("combobox", { name: "Your decision" }).click();
  await page.getByRole("option", { name: "Allow once", exact: true }).click();
  await page.getByLabel("Feedback for the agent (optional)").fill("Also check the selected project.");
  await page.getByRole("button", { name: "Send response and continue" }).click();
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.")).toBeVisible();
  await expect(page.locator(".activity-text").filter({ hasText: "ready" })).toBeVisible();
});

test("a review completed during initial loading updates progress before the stream opens", async ({ page }) => {
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  expect((await post(page, "/api/workflows", {
    key: "loading-review", holder,
    yaml: stringify({ version: 1, name: "Loading review", nodes: { review: { type: "human_wait", prompt: "Respond REVIEWED." } } }),
  })).ok()).toBeTruthy();
  const launched = await post(page, "/api/runs", { workflow_key: "loading-review", inputs: {} });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  let pending: { id: string; attempt_id: string } | undefined;
  await expect.poll(async () => {
    const response = await page.request.get(`/api/runs/${runId}?collection=interactions&pending=true`);
    pending = (await response.json()).run.interactions[0];
    return pending !== undefined;
  }).toBeTruthy();
  let releaseDetails!: () => void;
  let capturedDetails!: () => void;
  const released = new Promise<void>((resolve) => { releaseDetails = resolve; });
  const captured = new Promise<void>((resolve) => { capturedDetails = resolve; });
  let snapshots = 0;
  await page.route(`**/api/runs/${runId}?collection=*`, async (route) => {
    if (snapshots >= 2) { await route.continue(); return; }
    const response = await route.fetch();
    const body = await response.json();
    snapshots += 1;
    if (snapshots === 2) capturedDetails();
    await released;
    await route.fulfill({ response, json: body });
  });
  await page.route(`**/api/runs/${runId}/events?*`, async (route) => {
    await captured;
    expect((await post(page, `/api/attempts/${pending!.attempt_id}/wait`, {
      interaction_id: pending!.id, idempotency_key: "loading-review-answer", value: "REVIEWED",
    })).ok()).toBeTruthy();
    await expect.poll(async () => (await (await page.request.get(`/api/runs/${runId}`)).json()).run.status).toBe("succeeded");
    releaseDetails();
    await route.continue();
  });
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Jobs", exact: true }).locator('[data-job-scope="root.review"]')).toContainText("Complete");
  await expect(page.getByRole("heading", { name: "Your review is needed" })).toBeHidden();
});
