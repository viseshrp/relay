import { expect, test, type Page } from "./a11y-test";
import { historicalPost as post } from "./setup-helpers";
import { stringify } from "yaml";
import type { ArtifactRecord, RunDetail, RunEvent } from "../src/types";

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function gate() {
  const { promise, resolve } = deferred<void>();
  return { pending: promise, release: () => resolve() };
}

async function painted(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
}

type DetailPage = { run: RunDetail; next: number | null };
type ArtifactPage = { artifacts: ArtifactRecord[]; next: number | null };
let python = "";
let activeRuns: string[] = [];

async function detail(page: Page, id: string): Promise<RunDetail> {
  const response = await page.request.get(
    `/api/runs/${id}?collection=interactions&pending=true`,
  );
  expect(response.ok(), await response.text()).toBeTruthy();
  return ((await response.json()) as DetailPage).run;
}

async function launch(page: Page, key: string, nodes: object): Promise<string> {
  const created = await post(page, "/api/workflows", {
    key,
    holder: key,
    yaml: stringify({
      version: 1,
      name: key,
      model: "m1",
      agents: ["codex"],
      nodes,
    }),
  });
  expect(created.status(), await created.text()).toBe(201);
  const response = await post(page, "/api/runs", {
    workflow_key: key,
    inputs: {},
  });
  expect(response.status(), await response.text()).toBe(201);
  const id: string = (await response.json()).run_id;
  activeRuns.push(id);
  await expect
    .poll(async () => (await detail(page, id)).status)
    .toBe("paused_wait");
  return id;
}

async function holdStream(page: Page, id: string) {
  const started = gate();
  const ready = gate();
  let since = 0;
  let body = "";
  await page.route(
    (url) => url.pathname === `/api/runs/${id}/stream`,
    async (route) => {
      since = Number(
        new URL(route.request().url()).searchParams.get("since") ?? 0,
      );
      started.release();
      await ready.pending;
      await route.fulfill({ contentType: "text/event-stream", body });
    },
  );
  return {
    started: started.pending,
    async replay() {
      const response = await page.request.get(
        `/api/runs/${id}/events?since=${since}&limit=200`,
      );
      const value: { events: RunEvent[]; next: number | null } =
        await response.json();
      expect(value.next).toBeNull();
      expect(value.events.some((event) => event.type === "attempt.ended")).toBe(
        true,
      );
      body = value.events
        .map(
          (event) =>
            `id: ${event.id}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
        )
        .join("");
      ready.release();
    },
    release: ready.release,
  };
}

async function holdRead<T>(
  page: Page,
  id: string,
  matches: (url: URL) => boolean,
) {
  const captured = deferred<T>();
  const stale = gate();
  const repair = gate();
  const repairing = gate();
  let held = false;
  let frozen = false;
  await page.route(
    (url) =>
      [
        `/api/runs/${id}`,
        `/api/runs/${id}/events`,
        `/api/runs/${id}/artifacts`,
      ].includes(url.pathname),
    async (route) => {
      if (frozen) {
        repairing.release();
        await repair.pending;
      } else if (!held && matches(new URL(route.request().url()))) {
        held = true;
        const response = await route.fetch();
        expect(response.ok(), await response.text()).toBeTruthy();
        captured.resolve((await response.json()) as T);
        await stale.pending;
        await route.fulfill({ response });
        return;
      }
      await route.continue();
    },
  );
  return {
    captured: captured.promise,
    async deliverLate() {
      // Freeze later repairs so another response cannot hide a stale publish.
      frozen = true;
      stale.release();
      await repairing.pending;
      await painted(page);
    },
    release() {
      stale.release();
      repair.release();
    },
  };
}

test.beforeEach(async ({ page }) => {
  activeRuns = [];
  await page.request.get("/api/auth");
  expect(
    (
      await post(page, "/api/auth/login", {
        username: "owner",
        password: "Relay-Test-Passphrase-2026!",
      })
    ).ok(),
  ).toBeTruthy();
  const reset = await post(page, "/__test__/reset");
  expect(reset.ok()).toBeTruthy();
  python = (await reset.json()).python;
});

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
  for (const id of activeRuns) {
    if (!["running", "paused_wait"].includes((await detail(page, id)).status))
      continue;
    expect(
      (
        await post(page, `/api/runs/${id}/cancel`, {
          idempotency_key: `cleanup-${id}`,
        })
      ).ok(),
    ).toBeTruthy();
    await expect
      .poll(async () => (await detail(page, id)).waiting_count)
      .toBe(0);
  }
});

for (const kind of ["permission", "elicitation"] as const)
  for (const linked of [false, true])
    test(`an answered ${kind} survives a late ${linked ? "linked-request" : "pending-request"} read`, async ({
      page,
    }) => {
      expect(
        (
          await post(
            page,
            kind === "permission"
              ? "/__test__/feedback-provider"
              : "/__test__/elicitation-provider",
          )
        ).ok(),
      ).toBeTruthy();
      const id = await launch(page, `late-${kind}-${linked}`, {
        inspect: { type: "agent" },
      });
      const request = (await detail(page, id)).interactions[0];
      expect(request?.kind).toBe(kind);
      const stream = await holdStream(page, id);
      let stale: Awaited<ReturnType<typeof holdRead<DetailPage>>> | undefined;
      try {
        await page.goto(
          `/?view=runs&run=${id}&job=${encodeURIComponent(request.scope_path)}${linked ? `&interaction=${request.id}` : ""}`,
        );
        await stream.started;
        const banner = page.getByRole("region", {
          name: "Waiting for you",
          exact: true,
        });
        const job = page.getByRole("region", { name: "Job log", exact: true });
        await expect(banner).toBeVisible();
        await expect(
          job.getByRole("combobox", { name: "Attempt", exact: true }),
        ).toContainText("Waiting");
        stale = await holdRead<DetailPage>(
          page,
          id,
          (url) =>
            url.searchParams.get("collection") === "interactions" &&
            url.searchParams.has("interaction") === linked,
        );
        await page
          .getByRole("button", { name: "Refresh", exact: true })
          .click();
        const saved = await stale.captured;
        expect(saved.run.interactions[0]?.status).toBe("pending");

        const answer = await post(
          page,
          `/api/attempts/${request.attempt_id}/${kind}`,
          {
            interaction_id: request.id,
            idempotency_key: `answer-${kind}-${linked}`,
            ...(kind === "permission"
              ? { decision: "allow" }
              : { value: { component: "Editor" } }),
          },
        );
        expect(answer.status(), await answer.text()).toBe(202);
        await expect
          .poll(async () => (await detail(page, id)).status)
          .toBe("succeeded");
        await stream.replay();
        await expect(banner).toHaveCount(0);
        await expect(
          job.getByRole("combobox", { name: "Attempt", exact: true }),
        ).toHaveText("Attempt 1 · Completed");

        await stale.deliverLate();
        await expect(banner).toHaveCount(0);
        await expect(
          page.getByRole("button", { name: "Pause", exact: true }),
        ).toHaveCount(0);
        await expect(
          job.getByRole("combobox", { name: "Attempt", exact: true }),
        ).toHaveText("Attempt 1 · Completed");
      } finally {
        stream.release();
        stale?.release();
      }
    });

test("a canceled wait cannot be restored by a late pending-request read", async ({
  page,
}) => {
  const id = await launch(page, "late-canceled-wait", {
    approval: { type: "human_wait", prompt: "Cancel this pending review." },
  });
  const stream = await holdStream(page, id);
  let stale: Awaited<ReturnType<typeof holdRead<DetailPage>>> | undefined;
  try {
    await page.goto(`/?view=runs&run=${id}&job=root.approval`);
    await stream.started;
    const banner = page.getByRole("region", {
      name: "Waiting for you",
      exact: true,
    });
    await expect(banner).toBeVisible();
    stale = await holdRead<DetailPage>(
      page,
      id,
      (url) => url.searchParams.get("collection") === "interactions",
    );
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    expect((await stale.captured).run.waiting_count).toBe(1);

    expect(
      (
        await post(page, `/api/runs/${id}/cancel`, {
          idempotency_key: "cancel-during-read",
        })
      ).ok(),
    ).toBeTruthy();
    await expect
      .poll(async () => (await detail(page, id)).status)
      .toBe("canceled");
    await stream.replay();
    await expect(banner).toHaveCount(0);
    const attempt = page
      .getByRole("region", { name: "Job log", exact: true })
      .getByRole("combobox", { name: "Attempt", exact: true });
    await expect(attempt).toHaveText("Attempt 1 · Canceled");

    await stale.deliverLate();
    await expect(banner).toHaveCount(0);
    await expect(attempt).toHaveText("Attempt 1 · Canceled");
    await expect(
      page.getByRole("button", { name: "Pause", exact: true }),
    ).toHaveCount(0);
  } finally {
    stream.release();
    stale?.release();
  }
});

for (const paused of [true, false])
  test(`a live ${paused ? "pause" : "resume"} survives a late node page`, async ({
    page,
  }) => {
    const id = await launch(page, `late-dispatch-${paused}`, {
      approval: { type: "human_wait", prompt: "Keep this review pending." },
    });
    if (!paused)
      expect(
        (
          await post(page, `/api/runs/${id}/pause`, {
            paused: true,
            idempotency_key: "initial-pause",
          })
        ).ok(),
      ).toBeTruthy();
    await page.goto(`/?view=runs&run=${id}`);
    const before = page.getByRole("button", {
      name: paused ? "Pause" : "Resume",
      exact: true,
    });
    const after = page.getByRole("button", {
      name: paused ? "Resume" : "Pause",
      exact: true,
    });
    await expect(before).toBeVisible();
    const stale = await holdRead<DetailPage>(
      page,
      id,
      (url) => url.searchParams.get("collection") === "nodes",
    );
    try {
      await page.getByRole("button", { name: "Refresh", exact: true }).click();
      expect((await stale.captured).run.dispatch_paused).toBe(!paused);
      expect(
        (
          await post(page, `/api/runs/${id}/pause`, {
            paused,
            idempotency_key: "change-while-read-is-held",
          })
        ).ok(),
      ).toBeTruthy();
      // Use the real, still-open stream; EOF reconciliation must not repair this race.
      await expect(after).toBeVisible();
      expect((await detail(page, id)).dispatch_paused).toBe(paused);

      await stale.deliverLate();
      await expect(after).toBeVisible();
      await expect(before).toHaveCount(0);
    } finally {
      stale.release();
    }
  });

test("switching runs rejects a late detail page from the previous selection", async ({
  page,
}) => {
  const first = await launch(page, "previous-race-run", {
    approval: { type: "human_wait", prompt: "The previous run's review." },
  });
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const second = await launch(page, "selected-race-run", {
    approval: { type: "human_wait", prompt: "The selected run's review." },
  });
  await page.goto(`/?view=runs&run=${first}&job=root.approval`);
  await expect(
    page.getByRole("region", { name: "Waiting for you", exact: true }),
  ).toContainText("The previous run's review.");
  const stale = await holdRead<DetailPage>(
    page,
    first,
    (url) => url.searchParams.get("collection") === "nodes",
  );
  try {
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    expect((await stale.captured).run.id).toBe(first);
    await page
      .getByRole("button", { name: "Run history", exact: true })
      .click();
    await page
      .getByRole("link", { name: "All workflows", exact: true })
      .click();
    await page.getByRole("link", { name: /selected-race-run.*#/ }).click();
    await expect(page).toHaveURL(new RegExp(`run=${second}`));
    const banner = page.getByRole("region", {
      name: "Waiting for you",
      exact: true,
    });
    await expect(banner).toContainText("The selected run's review.");

    await stale.deliverLate();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "selected-race-run",
    );
    await expect(banner).toContainText("The selected run's review.");
    await expect(banner).not.toContainText("The previous run's review.");
  } finally {
    stale.release();
  }
});

test("saved artifacts survive an older empty page delivered after completion", async ({
  page,
}) => {
  const id = await launch(page, "late-artifact-page", {
    approval: { type: "human_wait", prompt: "Approve the saved report." },
    save: {
      type: "command",
      needs: ["approval"],
      writes: true,
      run: [
        python,
        "-c",
        [
          "from pathlib import Path; import subprocess",
          "Path('approval.txt').write_text('Ready: Yes\\n', encoding='utf-8')",
          "subprocess.run(['git', 'add', 'approval.txt'], check=True)",
          "subprocess.run(['git', 'commit', '-q', '-m', 'Save approval'], check=True)",
        ].join("; "),
      ],
      outputs: {
        verdict: { label: { artifact: "approval.txt", label: "Ready" } },
      },
    },
  });
  const request = (await detail(page, id)).interactions[0];
  const stream = await holdStream(page, id);
  let stale: Awaited<ReturnType<typeof holdRead<ArtifactPage>>> | undefined;
  try {
    await page.goto(`/?view=runs&run=${id}`);
    await stream.started;
    stale = await holdRead<ArtifactPage>(page, id, (url) =>
      url.pathname.endsWith("/artifacts"),
    );
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    const before = await stale.captured;
    expect(
      before.artifacts.some((artifact) => artifact.name === "verdict"),
    ).toBe(false);

    expect(
      (
        await post(page, `/api/attempts/${request.attempt_id}/wait`, {
          interaction_id: request.id,
          idempotency_key: "save-the-report",
          value: "Approved",
        })
      ).ok(),
    ).toBeTruthy();
    await expect
      .poll(async () => (await detail(page, id)).status)
      .toBe("succeeded");
    const saved: ArtifactPage = await (
      await page.request.get(`/api/runs/${id}/artifacts`)
    ).json();
    const artifact = saved.artifacts.find((item) =>
      item.source_path.endsWith("approval.txt"),
    );
    if (!artifact) throw new Error("The declared report was not retained.");
    await stream.replay();
    const table = page.getByRole("table", {
      name: "Retained artifacts",
      exact: true,
    });
    await expect(table).toContainText(artifact.name);
    await expect(page.locator(".run-summary-metadata")).toContainText(
      "Succeeded",
    );

    await stale.deliverLate();
    await expect(table).toContainText(artifact.name);
    await expect(page.locator(".run-summary-metadata")).toContainText(
      "Succeeded",
    );
  } finally {
    stream.release();
    stale?.release();
  }
});
