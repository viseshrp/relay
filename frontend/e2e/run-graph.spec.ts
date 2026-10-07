import { expect, test } from "@playwright/test";
import { stringify } from "yaml";
import { post } from "./setup-helpers";

test("refreshing unchanged job geometry keeps measured nodes and their connection visible", async ({ page }) => {
  await page.addInitScript(() => {
    class ControlledResizeObserver extends ResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        super((entries, observer) => {
          if (!Reflect.get(window, "relay-test-hold-resize")) callback(entries, observer);
        });
      }
    }
    window.ResizeObserver = ControlledResizeObserver;
  });
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", {
    username: "owner", password: "Relay-Test-Passphrase-2026!",
  })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  const created = await post(page, "/api/workflows", { key: "measured-graph", holder: "graph-test", yaml: stringify({
    version: 1, name: "Measured graph", nodes: {
      prepare: { type: "command", run: ["git", "status"] },
      verify: { type: "command", needs: ["prepare"], run: ["git", "status"] },
    },
  }) });
  expect(created.ok(), await created.text()).toBeTruthy();
  const launch = await post(page, "/api/runs", { workflow_key: "measured-graph", inputs: {} });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const { run_id: runId } = await launch.json();
  await expect.poll(async () => (await (await page.request.get(`/api/runs/${runId}`)).json()).run.status).toBe("succeeded");
  await page.goto(`/?view=runs&run=${runId}`);
  const graph = page.getByRole("region", { name: "Step progress", exact: true });
  await expect(graph.locator(".react-flow__edge")).toHaveCount(1);
  for (const scope of ["root.prepare", "root.verify"]) {
    await expect(graph.locator(`.react-flow__node[data-id="${scope}"]`)).toBeVisible();
  }
  // Unchanged dimensions do not require another browser resize notification.
  await page.evaluate(() => Reflect.set(window, "relay-test-hold-resize", true));
  const refreshed = page.waitForResponse((response) => response.url().includes(`/api/runs/${runId}?collection=nodes`));
  const refresh = page.getByRole("button", { name: "Refresh", exact: true });
  await refresh.click();
  await refreshed;
  await expect(refresh).toBeEnabled();
  for (const scope of ["root.prepare", "root.verify"]) {
    await expect(graph.locator(`.react-flow__node[data-id="${scope}"]`)).toBeVisible();
  }
  await expect(graph.locator(".react-flow__edge")).toHaveCount(1);
  await page.evaluate(() => Reflect.set(window, "relay-test-hold-resize", false));
});
