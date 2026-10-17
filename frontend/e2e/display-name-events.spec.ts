import { createServer, type Socket } from "node:net";
import { stringify } from "yaml";
import { expect, test } from "./a11y-test";
import { post } from "./setup-helpers";
import type { RunEvent } from "../src/types";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
});

for (const view of ["run", "job"]) {
  test(`${view} monitor refreshes on a display-name event while a command stays active`, async ({
    page,
  }, info) => {
    const listener = createServer();
    let peer: Socket | undefined;
    const connected = new Promise<void>((resolve) => {
      listener.once("connection", (socket) => {
        peer = socket;
        resolve();
      });
    });
    await new Promise<void>((resolve, reject) => {
      listener.once("error", reject);
      listener.listen(0, "127.0.0.1", resolve);
    });
    try {
      const address = listener.address();
      if (!address || typeof address === "string")
        throw new Error("The command gate has no TCP port.");
      const key = `display-name-${view}`;
      const created = await post(page, "/api/workflows", {
        key,
        holder: key,
        yaml: stringify({
          name: "Display name event",
          jobs: {
            work: {
              name: "Original label",
              steps: [
                {
                  id: "hold",
                  name: "Original label",
                  shell: "python",
                  run: `import socket\nwith socket.create_connection(("127.0.0.1", ${address.port}), timeout=${info.timeout / 1000}) as peer:\n    peer.recv(1)`,
                },
              ],
            },
          },
        }),
      });
      expect(created.ok(), await created.text()).toBeTruthy();
      const launched = await post(page, "/api/runs", {
        workflow_key: `${key}.yaml`,
        inputs: {},
      });
      expect(launched.status(), await launched.text()).toBe(201);
      const { run_id: id } = await launched.json();
      await connected;
      const stream = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/runs/${id}/stream`,
      );
      await page.goto(
        `/?view=runs&run=${id}${view === "job" ? "&job=root.work.hold" : ""}`,
      );
      await stream;
      const label = (value: string) =>
        view === "run"
          ? page
              .getByRole("region", { name: "Step progress" })
              .getByText(value, { exact: true })
          : page.getByRole("heading", { name: value, exact: true });
      await expect(label("Original label")).toBeVisible();
      const before = await (
        await page.request.get(`/api/runs/${id}/monitor`)
      ).json();
      expect(before.run.status).toBe("running");

      const renamed = await post(page, "/__test__/activity", {
        run_id: id,
        scope: view === "run" ? "root.work" : "root.work.hold",
        type: "node.display_name_changed",
        payload: { display_name: "Updated Windows label" },
      });
      expect(renamed.ok(), await renamed.text()).toBeTruthy();
      await expect(label("Updated Windows label")).toBeVisible();
      const tail = await (
        await page.request.get(
          `/api/runs/${id}/events?since=${before.event_cursor}`,
        )
      ).json();
      expect(tail.events.map((event: RunEvent) => event.type)).toEqual([
        "node.display_name_changed",
      ]);
      await info.attach("updated-display-name", {
        body: await page.screenshot(),
        contentType: "image/png",
      });
    } finally {
      peer?.destroy();
      await new Promise<void>((resolve) => listener.close(() => resolve()));
    }
  });
}
