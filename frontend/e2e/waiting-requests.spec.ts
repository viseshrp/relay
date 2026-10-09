import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";
import { historicalPost as post } from "./setup-helpers";
import type { Attention } from "../src/attention";
import type { RunDetail } from "../src/types";

declare global { interface Window { relayTestNotification: (title: string) => Promise<void> } }
let activeRun: string | null = null;

async function create(page: Page, key: string, nodes: object) {
  const created = await post(page, "/api/workflows", { key, holder: `waiting-${key}`, yaml: stringify({ version: 1, name: key, model: "m1", agents: ["codex"], nodes }) });
  expect(created.status(), await created.text()).toBe(201);
}
async function launch(page: Page, key: string): Promise<string> {
  const response = await post(page, "/api/runs", { workflow_key: key, inputs: {} });
  expect(response.status(), await response.text()).toBe(201);
  const result: { run_id: string } = await response.json();
  activeRun = result.run_id;
  return result.run_id;
}
async function detail(page: Page, id: string): Promise<RunDetail> {
  return (await (await page.request.get(`/api/runs/${id}?collection=interactions&pending=true`)).json()).run;
}
async function waiting(page: Page): Promise<Attention> {
  return (await page.request.get("/api/attention")).json();
}

test.beforeEach(async ({ page }) => {
  activeRun = null;
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});
test.afterEach(async ({ page }) => {
  if (!activeRun) return;
  const id = activeRun;
  if (["running", "paused_wait"].includes((await detail(page, id)).status)) {
    expect((await post(page, `/api/runs/${id}/cancel`, { idempotency_key: "waiting-test-cleanup" })).ok()).toBeTruthy();
    await expect.poll(async () => (await detail(page, id)).waiting_count).toBe(0);
  }
});

for (const kind of ["wait", "permission", "elicitation"] as const) for (const placement of ["loop", "child", "repair"] as const) {
  test(`${kind} inside a ${placement} appears in the header, navigation, title, and run list`, async ({ page }) => {
    if (kind !== "wait") expect((await post(page, kind === "permission" ? "/__test__/feedback-provider" : "/__test__/elicitation-provider")).ok()).toBeTruthy();
    const key = `waiting-${kind}-${placement}`;
    const job = kind === "wait" ? { type: "human_wait", prompt: "Check this nested approval. Respond YES." } : { type: "agent" };
    if (placement === "child") await create(page, `${key}-child`, { question: job });
    const group = placement === "repair" ? "repairs" : "rounds";
    await create(page, key, placement === "child" ? { child: { type: "subworkflow", workflow: `${key}-child` } } : {
      before: { type: "command", run: ["git", "status"] },
      [group]: { type: "loop", needs: ["before"], max_iterations: 1, until: "${{ loop.index >= 1 }}", exhausted: "fallback", body: { question: job } },
      fallback: { type: "command", needs: [group], run: ["git", "status"] },
    });
    const id = await launch(page, key);
    await expect.poll(async () => {
      const run = await detail(page, id);
      if (run.status === "failed") throw new Error(run.failure_summary ?? JSON.stringify(run.problem));
      return run.interactions.length;
    }).toBe(1);
    if (placement === "repair") {
      expect((await post(page, `/api/runs/${id}/pause`, { paused: true, idempotency_key: "pause-for-group" })).ok()).toBeTruthy();
      expect((await post(page, `/api/runs/${id}/repairs`, { groups: { "root.repairs": "root.before" }, idempotency_key: "group-repairs" })).ok()).toBeTruthy();
    }
    await page.goto(`/?view=runs&run=${id}`);
    const banner = page.getByRole("region", { name: "Waiting for you", exact: true });
    await expect(banner).toContainText(kind === "wait" ? "Check this nested approval" : kind === "permission" ? "Inspect project" : "Which component should I check?");
    await expect(banner.getByRole("alert")).toBeInViewport();
    const count = (await waiting(page)).waiting_count;
    await expect(page.getByRole("tab", { name: `Runs (${count})`, exact: true })).toBeVisible();
    await expect(page).toHaveTitle(`(${count}) Relay`);
    await expect(page.getByRole("heading", { name: new RegExp(`${key} #`) })).toBeVisible();
    await expect(page.getByText("Waiting for you", { exact: true }).last()).toBeVisible();
    await page.getByRole("button", { name: "Run history", exact: true }).click();
    const historyRun = page.getByRole("button", { name: new RegExp(`^${key} #`) });
    await expect(historyRun).toContainText("Waiting for you");
    await historyRun.click();
    await expect(page.getByText(/needs (your )?input/i)).toHaveCount(0);
    await page.getByRole("tab", { name: "Workflows", exact: true }).click();
    await expect(page.getByRole("tab", { name: `Runs (${count})`, exact: true })).toBeVisible();
    await page.getByRole("tab", { name: `Runs (${count})`, exact: true }).click();
    await banner.getByRole("button", { name: "Respond", exact: true }).click();
    if (kind === "permission") {
      const decision = page.getByRole("combobox", { name: "Your decision", exact: true });
      await expect(decision).toBeFocused();
      await decision.click();
      await page.getByRole("option", { name: "Allow once", exact: true }).click();
    } else {
      const answer = page.getByRole("textbox", { name: kind === "wait" ? "Your response" : "Component", exact: true });
      await expect(answer).toBeFocused();
      await answer.fill(kind === "wait" ? "YES" : "Editor");
    }
    await page.getByRole("button", { name: "Send response and continue", exact: true }).click();
    if (placement === "repair") expect((await post(page, `/api/runs/${id}/pause`, { paused: false, idempotency_key: "resume-after-answer" })).ok()).toBeTruthy();
    await expect.poll(async () => (await detail(page, id)).status).toBe("succeeded");
    await expect(banner).toHaveCount(0);
    await expect(page.getByText("Changes and documents", { exact: true })).toBeVisible();
    await expect(page.getByText(/before sending your response/)).toHaveCount(0);
  });
}

test("returning from Workflows keeps the selected run when several runs are waiting", async ({ page }) => {
  await create(page, "other-waiting", { approval: { type: "human_wait", prompt: "Another pending request." } });
  await create(page, "selected-waiting", { approval: { type: "human_wait", prompt: "Answer this selected run." } });
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const other = await launch(page, "other-waiting");
  try {
    const selected = await launch(page, "selected-waiting");
    await expect.poll(async () => (await detail(page, other)).interactions.length).toBe(1);
    await expect.poll(async () => (await detail(page, selected)).interactions.length).toBe(1);
    await page.goto(`/?view=runs&run=${selected}`);
    await expect(page.getByRole("region", { name: "Waiting for you", exact: true })).toContainText("Answer this selected run.");
    await page.getByRole("tab", { name: "Workflows", exact: true }).click();
    await page.getByRole("tab", { name: /^Runs \(/ }).click();
    await expect(page).toHaveURL(new RegExp(`run=${selected}`));
    await expect(page.getByRole("region", { name: "Waiting for you", exact: true })).toContainText("Answer this selected run.");
  } finally {
    expect((await post(page, `/api/runs/${other}/cancel`, { idempotency_key: "other-wait-cleanup" })).ok()).toBeTruthy();
    await expect.poll(async () => (await detail(page, other)).waiting_count).toBe(0);
  }
});

test("a job log keeps its pending response available above the output", async ({ page }) => {
  await create(page, "waiting-job-log", { approval: { type: "human_wait", prompt: "Read the job output and approve." } });
  const id = await launch(page, "waiting-job-log");
  await expect.poll(async () => (await detail(page, id)).interactions.length).toBe(1);
  await page.goto(`/?view=runs&run=${id}&job=root.approval`);
  const banner = page.getByRole("region", { name: "Waiting for you", exact: true });
  await banner.getByRole("button", { name: "Respond", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Your response", exact: true })).toBeFocused();
  await page.getByRole("textbox", { name: "Your response", exact: true }).fill("Approved");
  await page.getByRole("button", { name: "Send response and continue", exact: true }).click();
  await expect.poll(async () => (await detail(page, id)).status).toBe("succeeded");
  await expect(banner).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Job log", exact: true })).toBeVisible();
});

test("desktop notifications require opt-in and announce new waits and completions", async ({ page }) => {
  const calls: string[] = [];
  await page.exposeFunction("relayTestNotification", (title: string) => calls.push(title));
  await page.addInitScript(() => {
    class TestNotification {
      static permission = localStorage.getItem("relay.notifications") === "true" ? "granted" : "default";
      static async requestPermission() { this.permission = "granted"; return "granted"; }
      onclick: (() => void) | null = null;
      constructor(title: string) { void window.relayTestNotification(title); }
      close() {}
    }
    Object.defineProperty(window, "Notification", { value: TestNotification });
  });
  await page.goto("/?view=workflows");
  expect(calls).toEqual([]);
  expect(await page.evaluate(() => localStorage.getItem("relay.notifications"))).toBeNull();
  await page.getByRole("button", { name: /^(Help|Account menu for owner)$/ }).click();
  await page.getByRole("menuitem", { name: "Enable desktop notifications", exact: true }).click();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("relay.notifications"))).toBe("true");
  await create(page, "notify-wait", { approval: { type: "human_wait", prompt: "Approve this run." } });
  const id = await launch(page, "notify-wait");
  await expect.poll(async () => (await detail(page, id)).interactions.length).toBe(1);
  await page.evaluate(() => window.dispatchEvent(new Event("relay-attention-change")));
  await expect.poll(() => calls).toContain("Relay is waiting for you");
  await page.goto(`/?view=runs&run=${id}`);
  await page.getByRole("region", { name: "Waiting for you", exact: true }).getByRole("button", { name: "Respond", exact: true }).click();
  await page.getByRole("textbox", { name: "Your response", exact: true }).fill("YES");
  await page.getByRole("button", { name: "Send response and continue", exact: true }).click();
  await expect.poll(() => calls).toContain("Relay run complete");
  await page.getByRole("button", { name: /^(Help|Account menu for owner)$/ }).click();
  await page.getByRole("menuitem", { name: "Disable desktop notifications", exact: true }).click();
  expect(await page.evaluate(() => localStorage.getItem("relay.notifications"))).toBeNull();
});

for (const support of ["denied", "unavailable"] as const) test(`notification permission ${support} leaves waiting counts available`, async ({ page }) => {
  await page.addInitScript((value) => {
    if (value === "unavailable") Reflect.deleteProperty(window, "Notification");
    else {
      class DeniedNotification {
        static permission = "denied";
        static async requestPermission() { return "denied"; }
      }
      Object.defineProperty(window, "Notification", { value: DeniedNotification });
    }
  }, support);
  await page.goto("/?view=workflows");
  await page.getByRole("button", { name: /^(Help|Account menu for owner)$/ }).click();
  await page.getByRole("menuitem", { name: "Enable desktop notifications", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: support === "denied" ? "notifications are blocked" : "does not support desktop notifications" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("relay.notifications"))).toBeNull();
  await page.evaluate(() => window.dispatchEvent(new Event("relay-attention-change")));
  const count = (await waiting(page)).waiting_count;
  await expect(page.getByRole("tab", { name: count ? `Runs (${count})` : "Runs", exact: true })).toBeVisible();
  await expect(page).toHaveTitle(count ? `(${count}) Relay` : "Relay");
});
