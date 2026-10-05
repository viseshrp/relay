import { expect, test } from "@playwright/test";
import { stringify } from "yaml";

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
  await page.getByRole("button", { name: "Retry step", exact: true }).click();
  await page.unroute(`**/api/runs/${runId}?collection=*`);
  releaseRetry();
  await expect(page.getByText("You've hit your session limit · resets 1:50pm (UTC)", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText("The tool exited with code 1.");
});
