import { expect, test, type Page } from "./a11y-test";
import { stringify } from "yaml";
import { post } from "./setup-helpers";
import type { MonitorPage } from "../src/run-monitor";

function gate() {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { pending, release };
}
const runs: string[] = [];
async function waitingRun(page: Page, key: string) {
  const created = await post(page, "/api/workflows", {
    key,
    holder: key,
    yaml: stringify({
      name: key,
      jobs: {
        review: {
          steps: [
            {
              id: "work",
              uses: "relay/human-wait@v1",
              with: {
                prompt: `Approve ${key}.`,
              },
            },
          ],
        },
      },
    }),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const launched = await post(page, "/api/runs", {
    workflow_key: key,
    inputs: {},
  });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: id } = await launched.json();
  runs.push(id);
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${id}/monitor`)).json())
          .interactions.length,
    )
    .toBe(1);
  return id as string;
}
test.beforeEach(async ({ page }) => {
  runs.length = 0;
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
});
test.afterEach(async ({ page }) => {
  for (const id of runs)
    await post(page, `/api/runs/${id}/cancel`, {
      idempotency_key: `cleanup-${id}`,
    });
});

for (const action of ["pause", "resume", "answer", "cancel"] as const) {
  test(`a ${action} invalidates a pending monitor read before a late response`, async ({
    page,
  }) => {
    const id = await waitingRun(page, `late-${action}`);
    if (action === "resume")
      await post(page, `/api/runs/${id}/pause`, {
        paused: true,
        idempotency_key: "initial-pause",
      });
    const stream = gate(),
      stale = gate(),
      release = gate();
    await page.route(
      (url) => url.pathname === `/api/runs/${id}/stream`,
      async (route) => {
        await stream.pending;
        await route.fulfill({ contentType: "text/event-stream", body: "" });
      },
    );
    try {
      await page.goto(`/?view=runs&run=${id}`);
      const banner = page.getByRole("region", {
        name: "Waiting for you",
        exact: true,
      });
      await expect(banner).toContainText(`Approve late-${action}.`);
      let held = false;
      await page.route(
        (url) => url.pathname === `/api/runs/${id}/monitor`,
        async (route) => {
          if (held) {
            await route.continue();
            return;
          }
          held = true;
          const response = await route.fetch();
          stale.release();
          await release.pending;
          await route.fulfill({ response });
        },
      );
      stream.release();
      await stale.pending;
      if (action === "pause" || action === "resume") {
        await page
          .getByRole("button", {
            name: action === "pause" ? "Pause" : "Resume",
            exact: true,
          })
          .click();
        await expect(
          page.getByRole("button", {
            name: action === "pause" ? "Resume" : "Pause",
            exact: true,
          }),
        ).toBeEnabled();
      } else if (action === "answer") {
        await banner
          .getByRole("button", { name: "Respond", exact: true })
          .click();
        await page
          .getByRole("textbox", { name: "Your response", exact: true })
          .fill("APPROVED");
        await page
          .getByRole("button", {
            name: "Send response and continue",
            exact: true,
          })
          .click();
        await expect(banner).toHaveCount(0);
      } else {
        await page
          .getByRole("button", { name: "Cancel run", exact: true })
          .click();
        await page
          .getByRole("dialog")
          .getByRole("button", { name: "Cancel run", exact: true })
          .click();
        await expect(banner).toHaveCount(0);
      }
      release.release();
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      );
      if (action === "pause" || action === "resume")
        await expect(
          page.getByRole("button", {
            name: action === "pause" ? "Resume" : "Pause",
            exact: true,
          }),
        ).toBeEnabled();
      else await expect(banner).toHaveCount(0);
    } finally {
      stream.release();
      release.release();
      await page.unrouteAll({ behavior: "wait" });
    }
  });
}

test("a failed monitor read retains the accepted view and retries", async ({
  page,
}) => {
  const id = await waitingRun(page, "read-failure");
  await page.goto(`/?view=runs&run=${id}`);
  const banner = page.getByRole("region", {
    name: "Waiting for you",
    exact: true,
  });
  await expect(banner).toContainText("Approve read-failure.");
  const failed = gate(),
    release = gate();
  let reads = 0;
  await page.route(
    (url) => url.pathname === `/api/runs/${id}/monitor`,
    async (route) => {
      reads += 1;
      if (reads === 1) {
        await route.fulfill({
          status: 503,
          json: {
            code: "temporarily_unavailable",
            message: "Temporary monitor failure",
            context: {},
          },
        });
        failed.release();
      } else {
        await release.pending;
        await route.continue();
      }
    },
  );
  try {
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await failed.pending;
    await expect(banner).toContainText("Approve read-failure.");
    await expect(
      page.getByRole("alert").filter({ hasText: "Temporary monitor failure" }),
    ).toBeVisible();
    release.release();
    await expect(
      page.getByRole("alert").filter({ hasText: "Temporary monitor failure" }),
    ).toHaveCount(0);
    expect(reads).toBeGreaterThan(1);
  } finally {
    release.release();
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("a monitor rebuild pages beyond 1,000 records without mixing changed pages", async ({
  page,
}) => {
  const id = await waitingRun(page, "paged-monitor");
  const snapshot: MonitorPage = await (
    await page.request.get(`/api/runs/${id}/monitor`)
  ).json();
  let changed = false;
  const cursors: number[] = [];
  await page.route(
    (url) => url.pathname === `/api/runs/${id}/stream`,
    (route) => route.fulfill({ contentType: "text/event-stream", body: "" }),
  );
  await page.route(
    (url) => url.pathname === `/api/runs/${id}/monitor`,
    async (route) => {
      const since = Number(
        new URL(route.request().url()).searchParams.get("nodes_since") ?? 0,
      );
      cursors.push(since);
      if (since === 200 && !changed) changed = true;
      const count = Math.min(200, 1006 - since);
      const nodes = Array.from({ length: count }, (_, offset) => ({
        ...snapshot.nodes[0],
        id: String(since + offset + 1),
        node_id: `job_${since + offset + 1}`,
        scope_path: `root.job_${since + offset + 1}`,
        status: changed ? "succeeded" : "waiting",
      }));
      await route.fulfill({
        json: {
          ...snapshot,
          nodes,
          nodes_next: since + count < 1006 ? since + count : null,
          state_cursor: snapshot.state_cursor + (changed ? 1 : 0),
        },
      });
    },
  );
  await page.goto(`/?view=runs&run=${id}`);
  for (let pageNumber = 0; pageNumber < 5; pageNumber += 1) {
    await page.getByRole("button", { name: /Load more jobs/i }).click();
    await expect
      .poll(() => cursors.includes(Math.min(1000, (pageNumber + 1) * 200)))
      .toBe(true);
  }
  await expect(
    page.getByRole("button", { name: /Load more jobs/i }),
  ).toHaveCount(0);
  expect(cursors.filter((cursor) => cursor === 0).length).toBeGreaterThan(1);
});

test("constant page changes retain the accepted collection and let an open job load", async ({
  page,
}) => {
  const id = await waitingRun(page, "changing-pages");
  const snapshot: MonitorPage = await (
    await page.request.get(`/api/runs/${id}/monitor`)
  ).json();
  const stream = gate();
  let phase: "initial" | "changing" | "stable" = "initial";
  let changingReads = 0;
  let jobReads = 0;
  await page.route(
    (url) => url.pathname === `/api/runs/${id}/stream`,
    async (route) => {
      await stream.pending;
      await route.fulfill({ contentType: "text/event-stream", body: "" });
    },
  );
  await page.route(
    (url) => url.pathname === `/api/runs/${id}/monitor`,
    async (route) => {
      const since = Number(
        new URL(route.request().url()).searchParams.get("nodes_since") ?? 0,
      );
      if (phase === "changing") changingReads += 1;
      const version =
        phase === "initial" ? 0 : phase === "stable" ? 1000 : changingReads;
      const nodes = Array.from(
        { length: Math.min(200, 201 - since) },
        (_, offset) => {
          const number = since + offset;
          return number === 0
            ? snapshot.nodes[0]
            : {
                ...snapshot.nodes[0],
                id: String(number),
                node_id: `extra_${number}`,
                scope_path: `root.extra_${number}`,
              };
        },
      );
      await route.fulfill({
        json: {
          ...snapshot,
          run: {
            ...snapshot.run,
            dispatch_paused: phase !== "initial",
          },
          nodes,
          nodes_next: since === 0 ? 200 : null,
          state_cursor: snapshot.state_cursor + version,
        },
      });
    },
  );
  await page.route(
    (url) => url.pathname === `/api/runs/${id}/job`,
    async (route) => {
      jobReads += 1;
      await route.continue();
    },
  );
  try {
    await page.goto(`/?view=runs&run=${id}`);
    await page.getByRole("button", { name: /Load more jobs/i }).click();
    await expect(
      page.getByRole("navigation", { name: "Jobs" }).getByRole("link"),
    ).toHaveCount(202);
    phase = "changing";
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect.poll(() => changingReads).toBeGreaterThanOrEqual(8);
    // A partially rebuilt paused snapshot must not replace the accepted view.
    await expect(
      page.getByRole("button", { name: "Pause", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("navigation", { name: "Jobs" })
      .getByRole("link", { name: /^Review/ })
      .click();
    await expect.poll(() => jobReads).toBeGreaterThan(0);
    expect(phase).toBe("changing");
    phase = "stable";
    await expect(
      page.getByRole("button", { name: "Resume", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Jobs" }).getByRole("link"),
    ).toHaveCount(202);
    await expect(
      page.getByRole("alert").filter({ hasText: "changing quickly" }),
    ).toHaveCount(0);
  } finally {
    stream.release();
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("changing runs cancels old monitor and job reads", async ({ page }) => {
  const oldRun = await waitingRun(page, "old-selection");
  const newRun = await waitingRun(page, "new-selection");
  const stream = gate(),
    stale = gate(),
    release = gate();
  await page.route(
    (url) => url.pathname === `/api/runs/${oldRun}/stream`,
    async (route) => {
      await stream.pending;
      await route.fulfill({ contentType: "text/event-stream", body: "" });
    },
  );
  try {
    await page.goto(`/?view=runs&run=${oldRun}&job=root.review`);
    await expect(
      page.getByRole("region", { name: "Waiting for you", exact: true }),
    ).toContainText("Approve old-selection.");
    let held = false;
    await page.route(
      (url) =>
        url.pathname === `/api/runs/${oldRun}/monitor` ||
        url.pathname === `/api/runs/${oldRun}/job`,
      async (route) => {
        if (held) {
          await route.continue();
          return;
        }
        held = true;
        const response = await route.fetch();
        stale.release();
        await release.pending;
        await route.fulfill({ response });
      },
    );
    stream.release();
    await stale.pending;
    await page
      .getByRole("button", { name: "Run history", exact: true })
      .click();
    await page.getByRole("link", { name: /new-selection.*#/ }).click();
    await expect(page).toHaveURL(new RegExp(`run=${newRun}`));
    await expect(
      page.getByRole("region", { name: "Waiting for you", exact: true }),
    ).toContainText("Approve new-selection.");
    release.release();
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    await expect(
      page.getByRole("region", { name: "Waiting for you", exact: true }),
    ).toContainText("Approve new-selection.");
    await expect(
      page.getByRole("heading", { name: /old-selection.*#/ }),
    ).toHaveCount(0);
  } finally {
    stream.release();
    release.release();
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("completion waits for persisted output omitted from the terminal stream", async ({
  page,
}) => {
  const id = await waitingRun(page, "terminal-tail");
  const stream = gate(),
    tailRead = gate(),
    release = gate();
  let terminal = false;
  await page.route(
    (url) => url.pathname === `/api/runs/${id}/stream`,
    async (route) => {
      await stream.pending;
      await route.fulfill({ contentType: "text/event-stream", body: "" });
    },
  );
  try {
    await page.goto(`/?view=runs&run=${id}`);
    await expect(
      page.getByRole("region", { name: "Waiting for you", exact: true }),
    ).toBeVisible();
    await page.route(
      (url) =>
        url.pathname === `/api/runs/${id}/events` &&
        !url.searchParams.has("job"),
      async (route) => {
        if (terminal) {
          tailRead.release();
          await release.pending;
        }
        await route.continue();
      },
    );
    const saved = await post(page, "/__test__/activity", {
      run_id: id,
      scope: "root.review",
      type: "agent.message",
      payload: {
        text: "The final saved output must survive.",
        message_id: "final-tail",
      },
    });
    expect(saved.ok(), await saved.text()).toBeTruthy();
    const value: MonitorPage = await (
      await page.request.get(`/api/runs/${id}/monitor`)
    ).json();
    const request = value.interactions[0];
    await post(page, `/api/attempts/${request.attempt_id}/wait`, {
      interaction_id: request.id,
      idempotency_key: "finish-tail",
      value: "APPROVED",
    });
    await expect
      .poll(
        async () =>
          (await (await page.request.get(`/api/runs/${id}/monitor`)).json()).run
            .status,
      )
      .toBe("succeeded");
    terminal = true;
    stream.release();
    await tailRead.pending;
    const completion = page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
    );
    await expect(completion).toHaveCount(0);
    release.release();
    await expect(completion).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Activity feed", exact: true }),
    ).toContainText("The final saved output must survive.");
  } finally {
    stream.release();
    release.release();
    await page.unrouteAll({ behavior: "wait" });
  }
});
