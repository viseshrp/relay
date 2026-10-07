import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

async function post(page: Page, path: string, data: object = {}) {
  const csrf = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  return page.request.post(path, { data, headers: { "X-CSRFToken": csrf?.value ?? "" } });
}

test("pause active work, save a new reviewer, reload, and explicitly resume", async ({ page }, testInfo) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", {
    username: "owner", password: "Relay-Test-Passphrase-2026!",
  })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  expect((await post(page, "/__test__/feedback-provider")).ok()).toBeTruthy();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
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
  await expect(page.getByRole("button", { name: /^Pause review New jobs paused/ })).toBeVisible();
  await page.getByRole("button", { name: "Change settings", exact: true }).click();
  const dialog = page.getByRole("dialog");
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
