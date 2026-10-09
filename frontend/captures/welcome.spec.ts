import { expect, test, type Locator } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { stringify } from "yaml";
import { openSettings, post } from "../e2e/setup-helpers";

// Tutorial images come from the disposable browser server, never an owner project.
test("capture the four welcome screens and their control bounds", async ({ page }) => {
  const directory = new URL("../src/assets/welcome/", import.meta.url);
  await mkdir(directory, { recursive: true });
  await page.addInitScript(() => sessionStorage.setItem("relay.editor-holder", "welcome-capture"));
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  const highlights: Record<string, { x: number; y: number; width: number; height: number }> = {};
  async function capture(kind: string, frame: Locator, focus: Locator): Promise<void> {
    await focus.scrollIntoViewIfNeeded();
    await expect(focus).toBeVisible();
    await page.evaluate(async () => { await document.fonts.ready; });
    const box = await focus.boundingBox();
    if (!box) throw new Error(`The ${kind} control has no bounds.`);
    const scroll = await page.evaluate(() => ({ x: scrollX, y: scrollY, width: innerWidth, height: innerHeight }));
    const outer = await frame.boundingBox();
    if (!outer) throw new Error(`The ${kind} screen has no bounds.`);
    const width = Math.min(outer.width, 1120), height = Math.min(width * 0.625, outer.height + (kind === "run" ? 24 : 0));
    const x = Math.max(0, Math.min(outer.x, scroll.width - width));
    const top = kind === "settings" ? box.y - 130 : outer.y - (kind === "run" ? 12 : 0);
    const y = Math.max(0, Math.min(top, scroll.height - height));
    const padding = 8;
    highlights[kind] = {
      x: (box.x - x - padding) / width * 100,
      y: (box.y - y - padding) / height * 100,
      width: (box.width + padding * 2) / width * 100,
      height: (box.height + padding * 2) / height * 100,
    };
    const png = await page.screenshot({ path: new URL(`${kind}.png`, directory).pathname, clip: { x, y, width, height }, animations: "disabled" });
    expect(Math.abs(png.readUInt32BE(16) - width * 2)).toBeLessThanOrEqual(2);
    expect(Math.abs(png.readUInt32BE(20) - height * 2)).toBeLessThanOrEqual(2);
  }
  await page.route("**/api/projects/folders*", (route) => route.fulfill({ json: { path: "/home/you/projects", parent: "/home/you", folders: [{ name: "website", path: "/home/you/projects/website", repository: true }, { name: "tools", path: "/home/you/projects/tools", repository: true }], next: null } }));
  await page.goto("/");
  await page.getByRole("main", { name: "Relay home" }).getByRole("button", { name: "Open project", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Open a project", exact: true });
  await dialog.getByRole("textbox", { name: "Repository folder", exact: true }).fill("/home/you/projects/website");
  await expect(dialog.getByRole("region", { name: "Browse repository folders" })).toBeVisible();
  await capture("project", dialog, dialog.getByRole("textbox", { name: "Repository folder", exact: true }).locator("xpath=ancestor::div[contains(@class,'help-field')]"));
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  const source = stringify({ version: 1, name: "Plan, build, and review", model: "m1", agents: ["codex"], nodes: {
    plan: { type: "agent" },
    build: { type: "agent", needs: ["plan"] },
    review: { type: "human_wait", needs: ["build"], prompt: "Review the result." },
  } });
  const created = await post(page, "/api/workflows", { key: "welcome", holder: "welcome-capture", yaml: source });
  expect(created.ok(), await created.text()).toBeTruthy();
  await page.goto("/?view=workflows&workflow=welcome.yaml");
  await expect(page.getByRole("region", { name: "Workflow header" })).toContainText("Plan, build, and review");
  const canvas = page.getByRole("region", { name: "Workflow canvas", exact: true });
  await expect(canvas.locator(".react-flow__node")).toHaveCount(3);
  await expect(canvas.locator(".react-flow__node").first()).toBeInViewport();
  await canvas.getByRole("button", { name: "Fit View", exact: true }).click();
  await expect(canvas.locator('.react-flow__node[data-id="review"]')).toBeInViewport();
  await capture("workflow", page.locator(".canvas-panel"), canvas.locator('.react-flow__node[data-id="build"]'));
  const logs = await post(page, "/api/workflows", { key: "welcome-logs", holder: "welcome-capture", yaml: stringify({ version: 1, name: "Check the repository", nodes: { check: { type: "command", run: ["git", "log", "--stat", "-4"] } } }) });
  expect(logs.ok(), await logs.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const launch = await post(page, "/api/runs", { workflow_key: "welcome-logs", inputs: {} });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const { run_id: run } = await launch.json();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${run}`)).json()).run.status).toBe("succeeded");
  await page.goto(`/?view=runs&run=${run}&job=root.check`);
  await expect(page.getByRole("region", { name: "Command output lines", exact: true })).toContainText(".relay");
  await capture("run", page.locator(".job-log"), page.getByRole("textbox", { name: "Search logs", exact: true }));
  await openSettings(page);
  await expect(page.getByRole("heading", { name: "Global defaults", exact: true })).toBeVisible();
  await capture("settings", page.locator(".settings-content"), page.locator('[data-tour="sharedModel"]'));
  await writeFile(new URL("highlights.ts", directory), "// Generated by npm run capture:welcome from measured UI controls.\nexport const highlights = " + JSON.stringify(highlights, null, 2) + " as const;\n");
});
