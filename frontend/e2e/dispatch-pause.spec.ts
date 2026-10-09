import { historicalPost } from "./setup-helpers";
import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

async function post(page: Page, path: string, data: object = {}) {
  return historicalPost(page, path, data);
}

test("pause active work, save a new reviewer, reload, and explicitly resume", async ({ page }, testInfo) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", {
    username: "owner", password: "Relay-Test-Passphrase-2026!",
  })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  expect((await post(page, "/__test__/feedback-provider")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await expect(page.getByRole("button", { name: "Add job", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const created = await post(page, "/api/workflows", { key: "pause-review", holder, yaml: stringify({
    version: 1, name: "Pause review", model: "m1", agents: ["codex"],
    nodes: { work: { type: "agent" }, review: { type: "agent", needs: ["work"] } },
  }) });
  expect(created.ok(), await created.text()).toBeTruthy();
  const launch = await post(page, "/api/runs", { workflow_key: "pause-review", inputs: {}, cleanup_policy: "retain" });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const { run_id: runId } = await launch.json();
  await page.goto(`/?view=runs&run=${runId}`);
  await page.getByRole("region", { name: "Waiting for you", exact: true }).getByRole("button", { name: "Respond", exact: true }).click();
  await expect(page.getByRole("heading", { name: "A tool needs your permission" })).toBeVisible();
  const before = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(page.getByRole("button", { name: "Resume", exact: true })).toBeVisible();
  // The provider is still awaiting its own permission answer in the same attempt.
  await page.getByRole("combobox", { name: "Your decision" }).click();
  await page.getByRole("option", { name: "Allow once", exact: true }).click();
  await page.getByLabel("Feedback for the agent (optional)").fill("Finish the current step.");
  await page.getByRole("button", { name: "Send response and continue" }).click();
  await expect.poll(async () => {
    const run = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
    return run.nodes.find((node: { scope_path: string }) => node.scope_path === "root.work").status;
  }).toBe("succeeded");
  await expect(page.getByRole("region", { name: "Waiting for you", exact: true })).toHaveCount(0);
  await expect(page.getByText(/needs (your )?input/i)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Pause review #/ })).toBeVisible();
  await expect(page.getByText("New jobs paused", { exact: true })).toBeVisible();
  const pausedMessage = "Paused. Running jobs will finish; nothing new will start until you resume.";
  await expect(page.getByText(pausedMessage, { exact: true })).toHaveCount(1);
  await expect(page.getByText("Unstarted agent steps", { exact: true })).toHaveCount(0);
  const edit = page.getByRole("navigation", { name: "Jobs", exact: true }).getByRole("button", { name: "Edit Review settings", exact: true });
  await expect(edit).toBeEnabled();
  let probes = 0;
  const countProbe = (request: { method: () => string; url: () => string }) => {
    if (request.method() === "POST" && /\/api\/agents\/codex\/(models|configuration)/.test(request.url())) probes++;
  };
  page.on("request", countProbe);
  await edit.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("combobox", { name: "Tool", exact: true })).toBeEnabled();
  await expect(dialog.getByRole("combobox", { name: "Model", exact: true })).toBeEnabled();
  await expect(dialog.getByRole("combobox", { name: "Permission mode", exact: true })).toContainText("Keep current permission mode (Provider default)");
  await expect(dialog.getByRole("progressbar")).toHaveCount(0);
  expect(probes).toBe(0);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(edit).toBeFocused();
  await edit.click();
  expect(probes).toBe(0);
  page.off("request", countProbe);
  await expect(dialog.getByRole("textbox", { name: "Handoff instructions", exact: true })).toHaveCount(0);
  await dialog.getByRole("combobox", { name: "Tool", exact: true }).click();
  await page.getByRole("option", { name: "Antigravity", exact: true }).click();
  await expect(dialog.getByRole("combobox", { name: "Model", exact: true })).toBeEnabled();
  await dialog.getByRole("combobox", { name: "Model", exact: true }).click();
  await page.getByRole("option", { name: "Gemini Test (Low)", exact: true }).click();
  await expect(dialog).toContainText("Effort is low, included in this model.");
  const handoff = dialog.getByRole("textbox", { name: "Handoff instructions", exact: true });
  await expect(handoff).toHaveValue(/Perform this unstarted step/);
  await handoff.fill("Review the saved implementation. Preserve the completed step.");
  await dialog.getByRole("combobox", { name: "Permission mode", exact: true }).click();
  await page.getByRole("option", { name: "Auto approve", exact: true }).click();
  await dialog.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Resume", exact: true })).toBeVisible();
  const held = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  expect(held.snapshot).toEqual(before.snapshot);
  const review = held.nodes.find((node: { scope_path: string }) => node.scope_path === "root.review");
  expect(review.status).toBe("pending");
  expect(review.pending_settings).toMatchObject({ agent_id: "antigravity", model_value: "gemini-test-low" });
  await expect(edit).toBeEnabled();
  await edit.click();
  await expect(page.getByRole("dialog").getByRole("combobox", { name: "Permission mode", exact: true })).toContainText("Keep current permission mode (Auto approve)");
  await page.getByRole("dialog").press("Escape");
  await page.screenshot({ path: testInfo.outputPath("reviewer-saved-run-paused.png"), fullPage: true });
  await page.getByRole("button", { name: "Resume", exact: true }).click();
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Resume", exact: true })).toHaveCount(0);
  const after = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  expect(after.snapshot).toEqual(before.snapshot);
  const events = (await (await page.request.get(`/api/runs/${runId}/events?limit=200`)).json()).events;
  expect(events.filter((event: { type: string; payload: { scope_path?: string } }) =>
    event.type === "node.running" && event.payload.scope_path === "root.work")).toHaveLength(1);
});

test("upcoming job choices are shared, failures retry before opening, and Resume drops the edit controls", async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", {
    username: "owner", password: "Relay-Test-Passphrase-2026!",
  })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  expect((await post(page, "/__test__/feedback-provider")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await expect(page.getByRole("button", { name: "Add job", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  expect((await post(page, "/api/workflows", { key: "pause-choices", holder, yaml: stringify({
    version: 1, name: "Pause choices", model: "m1", agents: ["codex"],
    nodes: {
      work: { type: "agent" },
      review: { type: "agent", needs: ["work"], agents: ["claude"] },
      docs: { type: "agent", needs: ["work"], agents: ["claude"] },
    },
  }) })).ok()).toBeTruthy();
  const launch = await post(page, "/api/runs", { workflow_key: "pause-choices", inputs: {}, cleanup_policy: "retain" });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const { run_id: runId } = await launch.json();
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(page.getByRole("region", { name: "Waiting for you", exact: true })).toBeVisible();
  let modelProbes = 0, configurationProbes = 0;
  await page.route("**/api/agents/claude/models?**", async (route) => { modelProbes++; await route.continue(); });
  await page.route("**/api/agents/claude/configuration?**", async (route) => {
    configurationProbes++;
    await route.fulfill({ status: 503, json: { code: "agent_configuration_error", message: "The provider is unavailable.", context: {} } });
  });
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  await expect(jobs.getByRole("button", { name: "Edit Review settings" })).toBeDisabled();
  await expect(jobs.getByRole("button", { name: "Edit Docs settings" })).toBeDisabled();
  await expect(jobs.getByRole("alert")).toHaveCount(2);
  expect(modelProbes).toBe(1);
  expect(configurationProbes).toBe(1);
  await page.unroute("**/api/agents/claude/configuration?**");
  await jobs.getByRole("button", { name: "Check Review settings again" }).click();
  const edit = jobs.getByRole("button", { name: "Edit Review settings" });
  await expect(edit).toBeEnabled();
  await expect(jobs.getByRole("button", { name: "Edit Docs settings" })).toBeEnabled();
  expect(modelProbes).toBe(2);
  await jobs.locator('[data-job-scope="root.review"]').click();
  await expect(page).toHaveURL(/job=root.review/);
  await expect(page.getByText("Paused. Running jobs will finish; nothing new will start until you resume.", { exact: true })).toHaveCount(1);
  await edit.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("combobox", { name: "Permission mode", exact: true })).toContainText("Keep current permission mode (Provider default)");
  await expect(dialog.getByRole("progressbar")).toHaveCount(0);
  await dialog.press("Escape");
  await expect(edit).toBeFocused();
  await page.getByRole("button", { name: "Resume", exact: true }).click();
  await expect(jobs.getByRole("button", { name: /^Edit .* settings$/ })).toHaveCount(0);
  await expect(page.getByText("Paused. Running jobs will finish; nothing new will start until you resume.", { exact: true })).toHaveCount(0);
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/agents/claude/configuration?**", async (route) => {
    await held;
    await route.abort();
  });
  const pendingProbe = page.waitForRequest((request) => request.url().includes("/api/agents/claude/configuration"));
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  const probe = await pendingProbe;
  await expect(jobs.getByRole("status").filter({ hasText: "Loading Review settings" })).toBeVisible();
  const aborted = page.waitForEvent("requestfailed", { predicate: (request) => request === probe });
  await page.getByRole("button", { name: "Resume", exact: true }).click();
  release();
  await aborted;
  await expect(jobs.getByRole("button", { name: /^Edit .* settings$/ })).toHaveCount(0);
  await expect(jobs.getByRole("alert")).toHaveCount(0);
  expect((await post(page, `/api/runs/${runId}/cancel`, { idempotency_key: "stop-pause-choices" })).ok()).toBeTruthy();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${runId}`)).json()).run.status).toBe("canceled");
});
