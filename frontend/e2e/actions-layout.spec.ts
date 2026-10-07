import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { stringify } from "yaml";
import { jobDuration } from "../src/job";
import { logMatches, logRows, rawLog } from "../src/log";
import { runSummaryGraph } from "../src/run-graph";
import type { RunEvent, RunNode } from "../src/types";
import { post } from "./setup-helpers";

function event(id: number, type: string, chunk: string): RunEvent {
  return { id, type, source: "command", version: 1, ts: "2026-10-07T12:00:00Z", payload: { chunk } };
}
function node(scope: string, dependencies: string[] = []): RunNode {
  return { id: scope, scope_path: scope, node_id: scope, node_type: "command", status: "succeeded", writes: false, loop_index: null, dependencies, controls: [], parent_scope: null, selected_branch: null };
}

test("logs join partial chunks, search across ANSI styles, and export exact bytes", () => {
  const events = [event(1, "command.stdout", "\x1b[31mhel"), event(2, "command.stdout", "lo\x1b[0m world\n\nagain"), event(3, "command.stderr", "error\n"), event(4, "command.stdout", "HELLO\n")];
  const rows = logRows(events, true);
  expect(rows.map((row) => row.text)).toEqual(["hello world", "", "again", "error", "HELLO"]);
  expect(rows[0].timestamp).toBe(events[0].ts);
  expect(rows[0].spans?.[0].color).toBe("#f87171");
  expect(logMatches(rows, "Lo wo")).toEqual([{ row: 0, start: 3, end: 8 }]);
  expect(logMatches(rows, "hello")).toEqual([{ row: 0, start: 0, end: 5 }, { row: 4, start: 0, end: 5 }]);
  expect(logMatches(rows, "")).toEqual([]);
  expect(rawLog(events, true)).toBe(events.map((value) => value.payload.chunk).join(""));
});

test("durations include hours, running time, and invalid or missing timestamps", () => {
  expect(jobDuration("2026-10-07T12:00:00Z", "2026-10-07T13:02:03Z")).toBe("1h 2m 3s");
  expect(jobDuration("2026-10-07T12:00:00Z", null, Date.parse("2026-10-07T12:01:09Z"))).toBe("1m 9s");
  expect(jobDuration(null)).toBe("Not started");
  expect(jobDuration("invalid")).toBe("Duration unavailable");
  expect(jobDuration("2026-10-07T12:00:00Z", "2026-10-07T11:00:00Z")).toBe("0s");
});

test("parallel groups retain dependencies and repair state in the horizontal graph", () => {
  const jobs = Array.from({ length: 20 }, (_, index) => node(`root.check_${index}`, ["root.prepare"]));
  const graph = runSummaryGraph([node("root.prepare"), ...jobs, node("root.finish", jobs.map((job) => job.scope_path))], 0);
  expect(graph.nodes).toHaveLength(3);
  expect(graph.edges).toHaveLength(2);
  const group = graph.nodes.find((value) => value.data.members);
  expect(group?.data.members).toEqual(jobs.map((job) => job.scope_path));
  expect(graph.nodes.find((value) => value.id === "root.finish")?.position.x).toBeGreaterThan(group?.position.x ?? Infinity);
  const repair = runSummaryGraph([node("root.work"), { ...node("root.repair"), status: "running", repair_for: "root.work", repair_settings: { legacy: false, max_rounds: 2, accepted_output: null, accepted_value: true, fix_instruction: null, verify_instruction: null, roles: {} } }], 0);
  expect(repair.nodes).toHaveLength(1);
  expect(repair.nodes[0].data.status).toBe("repairing");
});

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});
async function launch(page: Page, key: string, nodes: object, name = key): Promise<string> {
  const created = await post(page, "/api/workflows", { key, holder: key, yaml: stringify({ version: 1, name, nodes }) });
  expect(created.ok(), await created.text()).toBeTruthy();
  const response = await post(page, "/api/runs", { workflow_key: key, inputs: {} });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).run_id;
}
async function append(page: Page, id: string, text: string, type = "agent.message"): Promise<void> {
  const response = await post(page, "/__test__/activity", { run_id: id, scope: "root.review", type, payload: { text, message_id: text } });
  expect(response.ok(), await response.text()).toBeTruthy();
}

test("long command logs stay searchable and downloadable with numbered virtual rows", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const { python } = await (await post(page, "/__test__/reset")).json();
  const output = Array.from({ length: 3000 }, (_, index) => `row ${index}${index === 2999 ? " target" : ""}\n`).join("");
  const id = await launch(page, "long-log", { check: { type: "command", run: [python, "-c", "for i in range(3000): print(f'row {i}' + (' target' if i == 2999 else ''))"] } });
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}`)).json()).run.status).toBe("succeeded");
  const history = `**/api/runs/${id}/events?job=root.check&limit=200&attempt=1&latest=true`;
  await page.route(history, (route) => route.fulfill({ status: 503, json: { code: "persistence_error", message: "This log could not be read.", context: {} } }));
  await page.goto(`/?view=runs&run=${id}&job=root.check`);
  const log = page.locator(".job-log");
  await expect(page.getByRole("alert").filter({ hasText: "This log could not be read." })).toBeVisible();
  await log.getByRole("button", { name: "Log options" }).click();
  await expect(page.getByRole("menuitem", { name: "Download logs", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await page.unroute(history);
  await log.getByRole("button", { name: "Retry log history" }).click();
  await expect(log.getByText("All logs received · 3,000 lines", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "This log could not be read." })).toHaveCount(0);
  expect(await log.locator(".terminal-log-row").count()).toBeLessThan(70);
  await log.getByRole("textbox", { name: "Search logs" }).fill("2999 TARGET");
  await expect(log.locator("mark")).toHaveText("2999 target");
  await expect(log.locator(".active-match .log-line-number")).toHaveText("3000");
  await log.getByRole("button", { name: "Next match" }).click();
  await expect(log.getByText("1/1", { exact: true })).toBeVisible();
  await log.getByRole("button", { name: "Log options" }).click();
  await page.getByRole("menuitem", { name: "Show timestamps" }).click();
  await expect(log.locator("time").first()).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath("actions-job-log.png"), animations: "disabled" });
  await log.getByRole("button", { name: "Log options" }).click();
  await page.screenshot({ path: info.outputPath("actions-log-options.png"), animations: "disabled" });
  await page.getByRole("menuitem", { name: "Show full screen (Shift+F)", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Job logs" })).toBeVisible();
  await expect(dialog.locator(".active-match")).toContainText("2999 target");
  const fullscreenSearch = dialog.getByRole("textbox", { name: "Search logs" });
  await fullscreenSearch.focus();
  await fullscreenSearch.press("End");
  await fullscreenSearch.press("Shift+F");
  await expect(fullscreenSearch).toHaveValue("2999 TARGETF");
  await expect(dialog).toBeVisible();
  await fullscreenSearch.fill("2999 TARGET");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(log).toBeFocused();
  await log.getByRole("button", { name: "Log options" }).click();
  const downloading = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "Download logs", exact: true }).click();
  const download = await downloading;
  const path = info.outputPath("complete.log");
  await download.saveAs(path);
  expect(await readFile(path, "utf8")).toBe(output);
  await log.getByRole("button", { name: "Log options" }).click();
  await page.getByRole("menuitem", { name: "View raw logs" }).click();
  await expect(page.getByRole("dialog").locator("pre")).toHaveText(output);
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await expect(log.getByRole("button", { name: "Log options" })).toBeFocused();
});

test("agent logs load every page, recover a failed read, and keep streaming while search is paused", async ({ page }) => {
  const id = await launch(page, "endless-log", { review: { type: "human_wait", prompt: "Review this run." } });
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}`)).json()).run.status).toBe("paused_wait");
  for (let index = 0; index < 215; index += 1) await append(page, id, `Saved message ${index}`);
  await append(page, id, "Hidden searchable thought", "agent.thought");
  const pages: string[] = [];
  let failing = true;
  const pattern = `**/api/runs/${id}/events?job=root.review&limit=200&attempt=1&latest=true&before=*`;
  await page.route(pattern, async (route) => {
    pages.push(route.request().url());
    if (failing) await route.fulfill({ status: 503, json: { code: "persistence_error", message: "The saved log page could not be read.", context: {} } });
    else await route.continue();
  });
  await page.goto(`/?view=runs&run=${id}&job=root.review`);
  await page.getByRole("button", { name: "Human review", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The saved log page could not be read." })).toBeVisible();
  failing = false;
  await page.getByRole("button", { name: "Refresh logs" }).click();
  const log = page.locator(".job-log");
  await expect(log.getByText("Live logs · 216 messages", { exact: true })).toBeVisible();
  expect(pages.length).toBeGreaterThanOrEqual(2);
  await expect(log.getByText("Saved message 0", { exact: true })).toBeAttached();
  await log.getByRole("textbox", { name: "Search logs" }).fill("hidden searchable");
  await expect(log.getByText("Hidden searchable thought", { exact: true })).toBeVisible();
  const viewport = log.getByRole("region", { name: "Human review log" });
  const top = await viewport.evaluate((element) => element.scrollTop);
  await append(page, id, "New streamed message");
  await expect(log.getByText("New streamed message", { exact: true })).toBeAttached();
  expect(await viewport.evaluate((element) => element.scrollTop)).toBe(top);
  await log.getByRole("button", { name: "Jump to latest" }).click();
  await expect(log.getByText("New streamed message", { exact: true })).toBeInViewport();
  await append(page, id, "Following the live tail");
  await expect(log.getByText("Following the live tail", { exact: true })).toBeInViewport();
  await viewport.evaluate((element) => { element.scrollTop = 0; });
  await expect(log.getByRole("button", { name: "Jump to latest" })).toBeVisible();
  expect((await post(page, `/api/runs/${id}/cancel`, { idempotency_key: "stop-live-log-test" })).ok()).toBeTruthy();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}`)).json()).run.status).toBe("canceled");
});

test("workflow history filters numbered runs and opens grouped jobs without wheel zoom", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const checks = Object.fromEntries(Array.from({ length: 8 }, (_, index) => [`check_${index}`, { type: "command", run: ["git", "status"], needs: ["prepare"] }]));
  const id = await launch(page, "actions-layout", { prepare: { type: "command", run: ["git", "status"] }, ...checks, finish: { type: "command", needs: Object.keys(checks), run: ["git", "status"] } }, "Build and verify");
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}`)).json()).run.status).toBe("succeeded");
  const detail = (await (await page.request.get(`/api/runs/${id}`)).json()).run;
  await page.goto("/?view=runs");
  await page.getByRole("navigation", { name: "Workflow sidebar" }).getByRole("button", { name: "Build and verify" }).click();
  await expect(page.getByRole("heading", { name: "Build and verify", exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Filter workflow runs" }).fill("no matching run");
  await expect(page.getByText("No runs match these filters.", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Filter workflow runs" }).fill(detail.source_commit.slice(0, 7));
  await expect(page.getByRole("button", { name: `Build and verify #${detail.number} · Complete`, exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("actions-history.png"), animations: "disabled" });
  await page.getByRole("button", { name: `Build and verify #${detail.number} · Complete`, exact: true }).click();
  const graph = page.getByRole("region", { name: "Step progress", exact: true });
  await expect(graph.locator(".react-flow__node")).toHaveCount(3);
  await expect(graph.locator(".react-flow__edge")).toHaveCount(2);
  await page.screenshot({ path: info.outputPath("actions-summary.png"), animations: "disabled" });
  const transform = await graph.locator(".react-flow__viewport").getAttribute("style");
  await graph.hover();
  await page.mouse.wheel(0, 200);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  expect(await graph.locator(".react-flow__viewport").getAttribute("style")).toBe(transform);
  await graph.locator(".react-flow__node").filter({ hasText: "8 parallel jobs" }).press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Parallel jobs" })).toBeVisible();
  await expect(dialog.getByRole("button").filter({ hasText: /^Check/ })).toHaveCount(8);
  await dialog.getByRole("button").filter({ hasText: "Check 0" }).click();
  await expect(page).toHaveURL(/job=root%2Echeck_0|job=root.check_0/);
  for (const width of [900, 1440, 700]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await page.getByRole("button", { name: "Artifacts", exact: true }).click();
  await expect(page.locator("#run-artifacts")).toBeInViewport();
});
