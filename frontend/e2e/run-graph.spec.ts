import { expect, test } from "./a11y-test";
import { stringify } from "yaml";
import { historicalPost as post } from "./setup-helpers";

test("refreshing unchanged job geometry keeps measured nodes and their connection visible", async ({
  page,
}) => {
  await page.addInitScript(() => {
    class ControlledResizeObserver extends ResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        super((entries, observer) => {
          if (!Reflect.get(window, "relay-test-hold-resize"))
            callback(entries, observer);
        });
      }
    }
    window.ResizeObserver = ControlledResizeObserver;
  });
  await page.request.get("/api/auth");
  expect(
    (
      await post(page, "/api/auth/login", {
        username: "owner",
        password: "Relay-Test-Passphrase-2026!",
      })
    ).ok(),
  ).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  const created = await post(page, "/api/workflows", {
    key: "measured-graph",
    holder: "graph-test",
    yaml: stringify({
      version: 1,
      name: "Measured graph",
      nodes: {
        prepare: { type: "command", run: ["git", "status"] },
        verify: { type: "command", needs: ["prepare"], run: ["git", "status"] },
      },
    }),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const launch = await post(page, "/api/runs", {
    workflow_key: "measured-graph",
    inputs: {},
  });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const { run_id: runId } = await launch.json();
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${runId}`)).json()).run
          .status,
    )
    .toBe("succeeded");
  await page.goto(`/?view=runs&run=${runId}`);
  const graph = page.getByRole("region", {
    name: "Step progress",
    exact: true,
  });
  await expect(graph.locator(".react-flow__edge")).toHaveCount(1);
  for (const scope of ["root.prepare", "root.verify"]) {
    await expect(
      graph.locator(`.react-flow__node[data-id="${scope}"]`),
    ).toBeVisible();
  }
  // Unchanged dimensions do not require another browser resize notification.
  await page.evaluate(() =>
    Reflect.set(window, "relay-test-hold-resize", true),
  );
  const refreshed = page.waitForResponse((response) =>
    response.url().includes(`/api/runs/${runId}?collection=nodes`),
  );
  const refresh = page.getByRole("button", { name: "Refresh", exact: true });
  await refresh.click();
  await refreshed;
  await expect(refresh).toBeEnabled();
  for (const scope of ["root.prepare", "root.verify"]) {
    await expect(
      graph.locator(`.react-flow__node[data-id="${scope}"]`),
    ).toBeVisible();
  }
  await expect(graph.locator(".react-flow__edge")).toHaveCount(1);
  await page.evaluate(() =>
    Reflect.set(window, "relay-test-hold-resize", false),
  );
});

test("a long run starts at its entry job and Refresh preserves the chosen viewport", async ({
  page,
}) => {
  await page.request.get("/api/auth");
  expect(
    (
      await post(page, "/api/auth/login", {
        username: "owner",
        password: "Relay-Test-Passphrase-2026!",
      })
    ).ok(),
  ).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  const nodes = Object.fromEntries(
    Array.from({ length: 14 }, (_value, index) => [
      `job_${index}`,
      {
        type: "command",
        run: ["git", "status"],
        ...(index ? { needs: [`job_${index - 1}`] } : {}),
      },
    ]),
  );
  const created = await post(page, "/api/workflows", {
    key: "audit-long",
    holder: "audit-long",
    yaml: stringify({ version: 1, name: "Long run", nodes }),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const launched = await post(page, "/api/runs", {
    workflow_key: "audit-long",
    inputs: {},
  });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${runId}`)).json()).run
          .status,
    )
    .toBe("succeeded");
  await page.goto(`/?view=runs&run=${runId}`);
  const graph = page.getByRole("region", {
    name: "Step progress",
    exact: true,
  });
  await graph.scrollIntoViewIfNeeded();
  await expect(
    graph.locator('.react-flow__node[data-id="root.job_0"]'),
  ).toBeInViewport();
  const viewport = graph.locator(".react-flow__viewport");
  await graph.getByRole("button", { name: "Zoom Out", exact: true }).click();
  const before = await viewport.getAttribute("style");
  const read = page.waitForResponse((response) =>
    response.url().includes(`/api/runs/${runId}?collection=nodes`),
  );
  const refresh = page.getByRole("button", { name: "Refresh", exact: true });
  await refresh.click();
  await read;
  await expect(refresh).toBeEnabled();
  await expect(viewport).toHaveAttribute("style", before ?? "");
});
