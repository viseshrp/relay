import { expect, test } from "@playwright/test";
import { stringify } from "yaml";

test.afterEach(async ({ page }) => {
  // Finish route.fetch callbacks before the test runner closes their page.
  await page.unrouteAll({ behavior: "wait" });
});

for (const automatic of [false, true]) test(`a failed run ${automatic ? "shows and cancels its scheduled retry" : "shows its provider limit and clears it on retry"}`, async ({ page }, testInfo) => {
  await page.request.get("/api/auth");
  const csrf = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  expect((await page.request.post("/api/auth/login", {
    headers: { "X-CSRFToken": csrf?.value ?? "" }, data: { username: "owner", password: "Relay-Test-Passphrase-2026!" },
  })).ok()).toBeTruthy();
  const token = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  const headers = { "X-CSRFToken": token?.value ?? "" };
  expect((await page.request.post("/__test__/reset", { headers })).ok()).toBeTruthy();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const workflowKey = automatic ? "scheduled-review" : "limited-review";
  const created = await page.request.post("/api/workflows", {
    headers, data: { key: workflowKey, holder, yaml: stringify({
      version: 1, name: "Limited review",
      nodes: { review: { type: "command", run: ["git", "unknown-command"] } },
    }) },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const launched = await page.request.post("/api/runs", {
    headers, data: { workflow_key: workflowKey, inputs: {} },
  });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${runId}`)).json()).run.status).toBe("failed");
  // Inject a native provider response while the real failed command run
  // continues to own state transitions and retry behavior.
  let retryState = "scheduled";
  await page.route(`**/api/runs/${runId}?collection=*`, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (body.run.status === "failed") body.run.problem = {
      scope_path: "root.review", attempt_number: 1, agent_id: "claude", model_value: "opus",
      error_code: "agent_protocol_error", stop_reason: "failed", exit_code: null,
      message: null, provider_message: "You've hit your session limit · resets 1:50pm (UTC)",
      provider_message_truncated: false,
      retry: automatic ? {
        state: retryState, reset_at: new Date(Date.now() + 3_600_000).toISOString(), error_message: null,
      } : null,
    };
    await route.fulfill({ response, json: body });
  });
  await page.goto(`/?view=runs&run=${runId}`);
  const notice = page.getByRole("alert").filter({ has: page.getByRole("heading", { name: "Review stopped" }) });
  await expect(notice).toContainText("You've hit your session limit · resets 1:50pm (UTC)");
  await expect(notice).toContainText("Claude message");
  await expect(notice).toContainText("Completed steps are saved.");
  await page.reload();
  await expect(notice).toBeVisible();
  if (!automatic) {
    await notice.getByRole("button", { name: "Show stopped step", exact: true }).click();
    const log = page.getByRole("region", { name: "Job log", exact: true });
    await expect(log.getByRole("heading", { name: "Review", exact: true })).toBeFocused();
    await expect(log.getByRole("alert")).toContainText("unknown-command");
    await expect(page).toHaveURL(/job=root.review/);
    await page.getByRole("navigation", { name: "Jobs" }).getByRole("button", { name: "Summary", exact: true }).click();
    await page.getByRole("button", { name: "Open job log", exact: true }).click();
    await expect(log.getByRole("alert")).toBeInViewport();
    await page.getByRole("navigation", { name: "Jobs" }).getByRole("button", { name: "Summary", exact: true }).click();
  }
  if (automatic) {
    await expect(page.getByText("Relay is waiting for the provider's reset. It will retry automatically.", { exact: true })).toBeVisible();
    await expect(notice).toContainText("Relay will retry this step after");
    await expect(notice).toContainText("using the same model and settings");
    await page.route(`**/api/runs/${runId}/cancel`, async (route) => {
      retryState = "canceled";
      await route.continue();
    });
    await notice.getByRole("button", { name: "Cancel automatic retry", exact: true }).click();
    await expect(notice).toContainText("Automatic retry is canceled.");
    await expect(notice.getByRole("button", { name: "Cancel automatic retry", exact: true })).toHaveCount(0);
  }
  await page.screenshot({ path: testInfo.outputPath("provider-limit-notice.png"), fullPage: true });
  // Hold the actual retry response so the test can observe the active state
  // before the deliberately failing command settles again.
  let releaseRetry!: () => void;
  const retryGate = new Promise<void>((resolve) => { releaseRetry = resolve; });
  await page.route(`**/api/runs/${runId}/rerun-node`, async (route) => {
    await retryGate;
    await route.continue();
  });
  await page.getByRole("button", { name: "Open job log", exact: true }).click();
  await page.getByRole("button", { name: "Re-run job", exact: true }).click();
  await page.unroute(`**/api/runs/${runId}?collection=*`);
  releaseRetry();
  await expect(page.getByText("You've hit your session limit · resets 1:50pm (UTC)", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Job log", exact: true }).getByRole("alert")).toContainText("Job failed with exit code 1.");
});

test("an owner can retry an agent with advertised effort while keeping its snapshot", async ({ page }, testInfo) => {
  await page.request.get("/api/auth");
  const csrf = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  expect((await page.request.post("/api/auth/login", {
    headers: { "X-CSRFToken": csrf?.value ?? "" },
    data: { username: "owner", password: "Relay-Test-Passphrase-2026!" },
  })).ok()).toBeTruthy();
  const token = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  const headers = { "X-CSRFToken": token?.value ?? "" };
  expect((await page.request.post("/__test__/reset", { headers })).ok()).toBeTruthy();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const created = await page.request.post("/api/workflows", {
    headers, data: { key: "retry-effort", holder, yaml: stringify({
      version: 1, name: "Retry effort", model: "m2", agents: ["claude"],
      nodes: { review: {
        type: "agent", agent_options: { claude: { effort: "low", permission_mode: "auto" } },
        // The wire-level fake writes no artifact, so validation fails after its turn.
        outputs: { verdict: { json_path: { artifact: "result.json", path: "verdict" } } },
      } },
    }) },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const launched = await page.request.post("/api/runs", {
    headers, data: { workflow_key: "retry-effort", inputs: {}, cleanup_policy: "retain" },
  });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${runId}`)).json()).run.status).toBe("failed");
  const before = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  await page.goto(`/?view=runs&run=${runId}`);
  await page.getByRole("button", { name: "Open job log", exact: true }).click();
  await page.getByRole("button", { name: "Re-run with settings", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("combobox", { name: "Effort", exact: true })).toBeEnabled();
  await expect(dialog).toContainText("Keep current effort (Low)");
  await expect(dialog).toContainText("Keep current permission mode (Auto)");
  await expect(dialog.getByRole("textbox", { name: "Handoff instructions", exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("combobox", { name: "Model", exact: true })).toBeEnabled();
  await dialog.getByRole("combobox", { name: "Model", exact: true }).click();
  await page.getByRole("option", { name: "Model One", exact: true }).click();
  await expect(dialog.getByRole("textbox", { name: "Handoff instructions", exact: true })).toHaveValue(before.problem.default_handoff_prompt);
  await dialog.getByRole("combobox", { name: "Model", exact: true }).click();
  await page.getByRole("option", { name: "Model Two", exact: true }).click();
  await expect(dialog.getByRole("textbox", { name: "Handoff instructions", exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("combobox", { name: "Effort", exact: true })).toBeEnabled();
  await dialog.getByRole("combobox", { name: "Effort", exact: true }).click();
  await page.getByRole("option", { name: "Medium", exact: true }).click();
  await dialog.getByRole("combobox", { name: "Permission mode", exact: true }).click();
  await page.getByRole("option", { name: "Ask", exact: true }).click();
  await expect(dialog.getByRole("textbox", { name: "Handoff instructions", exact: true })).toHaveCount(0);
  const submitted = page.waitForResponse((response) => response.url().endsWith(`/api/runs/${runId}/rerun-node`));
  await dialog.getByRole("button", { name: "Retry with settings", exact: true }).click();
  const response = await submitted;
  expect(response.status(), await response.text()).toBe(202);
  expect(response.request().postDataJSON().effort).toBe("medium");
  expect(response.request().postDataJSON().permission_mode).toBe("ask");
  expect(response.request().postDataJSON().handoff_prompt).toBeUndefined();
  await expect(dialog).toHaveCount(0);
  await expect.poll(async () => {
    const run = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
    return [run.status, run.problem?.attempt_number, run.problem?.effort];
  }).toEqual(["failed", 2, "medium"]);
  const after = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  expect(after.snapshot).toEqual(before.snapshot);
  const events = (await (await page.request.get(`/api/runs/${runId}/events?since=${before.event_cursor}`)).json()).events;
  expect(events.some((event: { payload: { text?: string } }) => event.payload.text === "config: model=m2;effort=medium;mode=ask")).toBeTruthy();
  // A different owner client can retry while this browser's terminal stream is closed.
  const external = await page.request.post(`/api/runs/${runId}/rerun-node`, {
    headers, data: { scope_path: "root.review", idempotency_key: "external-retry", effort: "low" },
  });
  expect(external.ok(), await external.text()).toBeTruthy();
  await expect.poll(async () => {
    const run = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
    return [run.status, run.problem?.attempt_number];
  }).toEqual(["failed", 3]);
  // Hold the refreshed state so this race does not depend on request timing.
  let markRefreshStarted!: () => void;
  const refreshStarted = new Promise<void>((resolve) => { markRefreshStarted = resolve; });
  let releaseRefresh!: () => void;
  const refreshGate = new Promise<void>((resolve) => { releaseRefresh = resolve; });
  await page.route(`**/api/runs/${runId}?collection=*`, async (route) => {
    const response = await route.fetch();
    markRefreshStarted();
    await refreshGate;
    await route.fulfill({ response });
  });
  try {
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await refreshStarted;
    await expect(page.getByRole("button", { name: "Re-run with settings", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Re-run job", exact: true })).toBeDisabled();
  } finally {
    releaseRefresh();
  }
  await page.getByRole("button", { name: "Re-run with settings", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Keep current effort (Low)");
  await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("retry-effort.png"), fullPage: true });
});

for (const native of [false, true]) test(`an owner can hand a failed Claude step to ${native ? "Antigravity" : "Codex"}`, async ({ page }, testInfo) => {
  await page.request.get("/api/auth");
  const csrf = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  expect((await page.request.post("/api/auth/login", {
    headers: { "X-CSRFToken": csrf?.value ?? "" },
    data: { username: "owner", password: "Relay-Test-Passphrase-2026!" },
  })).ok()).toBeTruthy();
  const token = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  const headers = { "X-CSRFToken": token?.value ?? "" };
  expect((await page.request.post("/__test__/reset", { headers })).ok()).toBeTruthy();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const key = native ? "handoff-native" : "handoff-acp";
  const created = await page.request.post("/api/workflows", {
    headers, data: { key, holder, yaml: stringify({
      version: 1, name: "Provider handoff", model: "m2", agents: ["claude"],
      nodes: {
        first: { type: "command", run: ["git", "status"] },
        review: {
          type: "agent", needs: ["first"], permission_profile: "interactive",
          agent_options: { claude: { effort: "low", permission_mode: "auto" } },
          outputs: { verdict: { json_path: { artifact: "result.json", path: "verdict" } } },
        },
      },
    }) },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const launched = await page.request.post("/api/runs", {
    headers, data: { workflow_key: key, inputs: {}, cleanup_policy: "retain" },
  });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${runId}`)).json()).run.status).toBe("failed");
  const beforeResponse = await (await page.request.get(`/api/runs/${runId}`)).json();
  const before = beforeResponse.run;
  if (!native) {
    // The first problem notice can describe a different concurrent failure.
    // Retry settings must still come from the selected failed step's own route.
    // Fulfill the captured state directly so aborted reads cannot outlive route.fetch.
    await page.route(`**/api/runs/${runId}?collection=*`, (route) => route.fulfill({
      json: { ...beforeResponse, run: {
        ...before, problem: { ...before.problem, scope_path: "root.other" },
      } },
    }));
  }
  await page.goto(`/?view=runs&run=${runId}`);
  if (!native) await expect(page.getByRole("heading", { name: "Other stopped", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Open job log", exact: true }).click();
  await page.getByRole("button", { name: "Re-run with settings", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("combobox", { name: "Tool", exact: true })).toBeEnabled();
  await dialog.getByRole("combobox", { name: "Tool", exact: true }).click();
  await page.getByRole("option", { name: native ? "Antigravity" : "Codex", exact: true }).click();
  await expect(dialog.getByRole("combobox", { name: "Model", exact: true })).toBeEnabled();
  await dialog.getByRole("combobox", { name: "Model", exact: true }).click();
  await page.getByRole("option", { name: native ? "Gemini Test (Low)" : "Model One", exact: true }).click();
  const permission = dialog.getByRole("combobox", { name: "Permission mode", exact: true });
  await expect(permission).toBeEnabled();
  await expect(permission).toHaveText("Provider default");
  const handoff = dialog.getByRole("textbox", { name: "Handoff instructions", exact: true });
  await expect(handoff).toHaveValue(before.problem.default_handoff_prompt);
  if (native) {
    await handoff.fill("Keep the completed work. Finish the remaining document refresh.");
    await dialog.getByRole("button", { name: "Use default handoff", exact: true }).click();
    await expect(handoff).toHaveValue(before.problem.default_handoff_prompt);
    await handoff.fill("Keep the completed work. Finish the remaining document refresh.");
  }
  if (native) {
    await expect(dialog).toContainText("Effort is low, included in this model.");
  } else {
    await dialog.getByRole("combobox", { name: "Effort", exact: true }).click();
    await page.getByRole("option", { name: "High", exact: true }).click();
  }
  await permission.click();
  await page.getByRole("option", { name: native ? "Auto approve" : "Auto", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("handoff-settings.png"), fullPage: true });
  // Finish simulated reads before retrying; the new attempt uses the real API.
  if (!native) await page.unrouteAll({ behavior: "wait" });
  const submitted = page.waitForResponse((response) => response.url().endsWith(`/api/runs/${runId}/rerun-node`));
  await dialog.getByRole("button", { name: "Retry with settings", exact: true }).click();
  const response = await submitted;
  expect(response.status(), await response.text()).toBe(202);
  const agent = native ? "antigravity" : "codex";
  const model = native ? "gemini-test-low" : "m1";
  expect(response.request().postDataJSON()).toMatchObject({
    agent_id: agent, model, effort: native ? null : "high", permission_mode: native ? "auto_approve" : "auto",
    handoff_prompt: native ? "Keep the completed work. Finish the remaining document refresh." : before.problem.default_handoff_prompt,
  });
  await expect(dialog).toHaveCount(0);
  await expect.poll(async () => {
    const run = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
    return [run.status, run.problem?.attempt_number, run.problem?.agent_id, run.problem?.model_value];
  }).toEqual(["failed", 2, agent, model]);
  const after = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  expect(after.snapshot).toEqual(before.snapshot);
  expect(after.nodes.find((node: { scope_path: string }) => node.scope_path === "root.first").status).toBe("succeeded");
});
