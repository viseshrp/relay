import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { stringify } from "yaml";
import { post } from "./setup-helpers";
import { ansiSpans, commandLines, jobDuration } from "../src/job";
import type { RunEvent } from "../src/types";
import type { AnsiStyle } from "../src/job";

async function create(page: Page, key: string, nodes: object, extra: object = {}) {
  const response = await post(page, "/api/workflows", { key, holder: `job-log-${key}`, yaml: stringify({ version: 1, name: key, nodes, ...extra }) });
  expect(response.status(), await response.text()).toBe(201);
}
async function launch(page: Page, key: string) {
  const response = await post(page, "/api/runs", { workflow_key: key, inputs: {} });
  expect(response.status(), await response.text()).toBe(201);
  const value: { run_id: string } = await response.json();
  return value.run_id;
}
async function settled(page: Page, id: string, status: string) {
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}`)).json()).run.status).toBe(status);
}

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});

test("a failed command opens its late error, exact attempt, and downloadable output in one click", async ({ page }, info) => {
  const reset: { python: string } = await (await post(page, "/__test__/reset")).json();
  await create(page, "late-error", {
    before: { type: "command", run: [reset.python, "-c", "print('Earlier output\\n' * 20000)"] },
    check: { type: "command", needs: ["before"], run: [reset.python, "-c", "import sys; print('Command stdout'); sys.stderr.write('\\x1b[31mFinal command error\\x1b[0m\\n'); sys.exit(5)"] },
  });
  const id = await launch(page, "late-error");
  await settled(page, id, "failed");
  await page.goto(`/?view=runs&run=${id}`);
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  await jobs.getByRole("button", { name: /^Check / }).click();
  const log = page.getByRole("region", { name: "Job log", exact: true });
  await expect(log.getByRole("alert")).toContainText("Final command error");
  await expect(log.getByRole("alert")).toBeInViewport();
  await page.screenshot({ path: info.outputPath("job-error.png") });
  await expect(page).toHaveURL(/job=root%2Echeck|job=root.check/);
  const terminal = log.getByRole("list", { name: "Command output lines" });
  await expect(terminal).toContainText("Command stdout");
  await expect(terminal).toContainText("stdout");
  await expect(terminal).toContainText("stderr");
  await expect(terminal.getByText("Final command error", { exact: true })).toHaveCSS("color", "rgb(248, 113, 113)");
  const downloading = page.waitForEvent("download");
  await log.getByRole("button", { name: "Download output", exact: true }).click();
  const download = await downloading;
  const path = info.outputPath("command.log");
  await download.saveAs(path);
  expect(await readFile(path, "utf8")).toContain("Final command error");
  await page.reload();
  await expect(log.getByRole("alert")).toContainText("Final command error");
  await log.getByRole("button", { name: "Re-run job", exact: true }).click();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${id}/job?job=root.check`)).json()).job.latest_attempt?.number).toBe(2);
  await settled(page, id, "failed");
  await expect(log.getByRole("combobox", { name: "Attempt", exact: true })).toContainText("Attempt 2");
  await log.getByRole("combobox", { name: "Attempt", exact: true }).click();
  await page.getByRole("option", { name: "Attempt 1 · Failed", exact: true }).click();
  await expect(log.getByRole("alert")).toContainText("Final command error");
  await jobs.getByRole("button", { name: "Summary", exact: true }).click();
  await expect(log).toHaveCount(0);
  await expect(page).not.toHaveURL(/job=/);
  await page.locator('.react-flow__node[data-id="root.check"]').click();
  await expect(log.getByRole("alert")).toContainText("Final command error");
});

test("a failed agent shows its captured instruction and error without loading the run feed", async ({ page }) => {
  await create(page, "agent-log", { inspect: { type: "agent", prompts: [{ local: "prompts/prompt.md" }], outputs: { verdict: { label: { artifact: "REVIEW.md", label: "JobHistoryMissing" } } } } }, { model: "m1", agents: ["codex"] });
  const id = await launch(page, "agent-log");
  await settled(page, id, "failed");
  const detail = (await (await page.request.get(`/api/runs/${id}/job?job=root.inspect`)).json()).job;
  await page.goto(`/?view=runs&run=${id}`);
  await page.getByRole("navigation", { name: "Jobs" }).getByRole("button", { name: /^Inspect / }).click();
  const log = page.getByRole("region", { name: "Job log" });
  await expect(log.getByRole("alert")).toContainText(detail.latest_attempt.error_message);
  await expect(log.getByRole("alert")).toBeInViewport();
  await expect(log).toContainText("Runs on Codex · m1");
  await log.getByRole("button", { name: "Instructions", exact: true }).click();
  await expect(log.getByText("prompts/prompt.md", { exact: true })).toBeVisible();
  await expect(log.getByRole("button", { name: "Agent conversation", exact: true })).toHaveAttribute("aria-expanded", "true");
});

test("loop iterations and nested workflow jobs have individual logs and stable links", async ({ page }) => {
  await create(page, "child-log", { check: { type: "command", run: ["git", "status", "--short"] } });
  await create(page, "nested-log", {
    repeats: { type: "loop", max_iterations: 2, exhausted: "fallback", until: "${{ loop.index >= 2 }}", body: { check: { type: "command", run: ["git", "status", "--short"] } } },
    fallback: { type: "command", needs: ["repeats"], run: ["git", "status", "--short"] },
    child: { type: "subworkflow", needs: ["repeats"], workflow: "child-log" },
  });
  const id = await launch(page, "nested-log");
  await settled(page, id, "succeeded");
  await page.goto(`/?view=runs&run=${id}&job=${encodeURIComponent("root.repeats#2.check")}`);
  const log = page.getByRole("region", { name: "Job log" });
  await expect(log.getByRole("heading", { name: "Check (iteration 2)", exact: true })).toBeVisible();
  const jobs = page.getByRole("navigation", { name: "Jobs" });
  await expect(jobs).toContainText("Repeats (iteration 1)");
  await expect(jobs).toContainText("Repeats (iteration 2)");
  await jobs.getByRole("button", { name: /^Check Complete/ }).click();
  await expect(page).toHaveURL(/job=root.child.check/);
  await expect(log.getByRole("heading", { name: "Check", exact: true })).toBeVisible();
  await page.reload();
  await expect(log.getByRole("heading", { name: "Check", exact: true })).toBeVisible();
});

test("terminal text keeps stream boundaries, ANSI colors, and inert escape sequences", () => {
  const event = (id: number, type: string, chunk: string): RunEvent => ({ id, type, version: 1, source: "command", ts: "2026-10-07T12:00:00Z", payload: { chunk } });
  expect(commandLines([event(1, "command.stdout", "one"), event(2, "command.stdout", " line\n"), event(3, "command.stderr", "error\n"), event(4, "node.succeeded", "ignored")])).toEqual([{ stream: "stdout", text: "one line" }, { stream: "stderr", text: "error" }]);
  expect(ansiSpans("\x1b[31merror\x1b[0m <script>alert(1)</script>\x1b[2J")).toEqual([
    { text: "error", color: "#f87171", bold: false }, { text: " <script>alert(1)</script>", color: undefined, bold: false },
  ]);
  expect(ansiSpans("\x1b]8;;https://example.test\x07Link\x1b]8;;\x07").map((span) => span.text).join("")).toBe("Link");
  expect(ansiSpans("\x1b]8;;https://example.test\x1b\\Link\x1b]8;;\x1b\\ tail").map((span) => span.text).join("")).toBe("Link tail");
  expect(ansiSpans("\x1b[1;94mBlue\x1b[22;39mnormal")).toEqual([{ text: "Blue", bold: true, color: "#93c5fd" }, { text: "normal", bold: false, color: undefined }]);
  expect(ansiSpans("\x1b[38;5;45mCyan")[0].color).toBe("rgb(0, 215, 255)");
  expect(ansiSpans("\x1b[38;2;100;200;250mRGB")[0].color).toBe("rgb(100, 200, 250)");
  const style: AnsiStyle = { bold: false };
  ansiSpans("\x1b[31mred", style);
  expect(ansiSpans("next line", style)[0].color).toBe("#f87171");
  expect(jobDuration("2026-10-07T12:00:00Z", "2026-10-07T12:01:05Z")).toBe("1m 5s");
  expect(jobDuration(null)).toBe("Not started");
  expect(jobDuration("invalid", "invalid")).toBe("Duration unavailable");
});
