import { expect, test } from "@playwright/test";
import { post, runStarter } from "./setup-helpers";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});

test("setup completes a starter run without login", async ({ page }, testInfo) => {
  await page.request.get("/api/auth");
  await runStarter(page, "ask-agent", "Ask an agent", testInfo);
  await expect(page.getByText("Login disabled", { exact: true })).toBeVisible();
});

test("a fresh local app opens and runs a workflow without an owner login", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Login disabled", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Password", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  expect(await (await page.request.get("/api/auth")).json()).toMatchObject({
    owner_created: false, authenticated: true, username: "local", login_required: false,
  });
  expect((await page.context().cookies()).some((cookie) => cookie.name === "relay_sessionid")).toBeFalsy();

  const token = (await page.context().cookies()).find((cookie) => cookie.name === "relay_csrftoken");
  const headers = { "X-CSRFToken": token?.value ?? "" };
  const workflow = await page.request.post("/api/workflows", {
    headers,
    data: {
      key: "local-run", holder: "local-browser",
      yaml: "version: 1\nname: Local run\nnodes:\n  work: {type: command, run: [git, status]}\n",
    },
  });
  expect(workflow.ok(), await workflow.text()).toBeTruthy();
  expect((await page.request.post("/__test__/commit", { headers })).ok()).toBeTruthy();
  const launched = await page.request.post("/api/runs", {
    headers, data: { workflow_key: "local-run", inputs: {} },
  });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(page.getByRole("heading", { name: "Local run" })).toBeVisible();
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Login disabled", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Local run" })).toBeVisible();
});
