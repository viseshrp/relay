import { expect, test, type Page } from "./a11y-test";
import { stringify } from "yaml";
import { expectRunStatus, post } from "./setup-helpers";
import type { Attention } from "../src/attention";
import type { RunDetail, RunEvent } from "../src/types";

declare global {
  interface Window {
    relayTestNotification: (title: string) => Promise<void>;
  }
}
let activeRun: string | null = null;

async function create(
  page: Page,
  key: string,
  nodes: object,
  reusable = false,
) {
  const created = await post(page, "/api/workflows", {
    key,
    holder: `waiting-${key}`,
    yaml: stringify({
      name: key,
      ...(reusable ? { on: { workflow_call: {} } } : {}),
      jobs: nodes,
    }),
  });
  expect(created.status(), await created.text()).toBe(201);
}
async function launch(page: Page, key: string): Promise<string> {
  const response = await post(page, "/api/runs", {
    workflow_key: key,
    inputs: {},
  });
  expect(response.status(), await response.text()).toBe(201);
  const result: { run_id: string } = await response.json();
  activeRun = result.run_id;
  return result.run_id;
}
async function detail(page: Page, id: string): Promise<RunDetail> {
  return (
    await (
      await page.request.get(
        `/api/runs/${id}?collection=interactions&pending=true`,
      )
    ).json()
  ).run;
}
async function waiting(page: Page): Promise<Attention> {
  return (await page.request.get("/api/attention")).json();
}

function gate() {
  let release: () => void = () => undefined;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { pending, release: () => release() };
}

test.beforeEach(async ({ page }) => {
  activeRun = null;
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
  if (!activeRun) return;
  const id = activeRun;
  if (["running", "paused_wait"].includes((await detail(page, id)).status)) {
    expect(
      (
        await post(page, `/api/runs/${id}/cancel`, {
          idempotency_key: "waiting-test-cleanup",
        })
      ).ok(),
    ).toBeTruthy();
    await expect
      .poll(async () => (await detail(page, id)).waiting_count)
      .toBe(0);
  }
});

for (const kind of ["wait", "permission", "elicitation"] as const)
  for (const placement of ["loop", "child", "repair"] as const) {
    test(`${kind} inside a ${placement} appears in the header, navigation, title, and run list`, async ({
      page,
    }) => {
      if (kind !== "wait")
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
      const key = `waiting-${kind}-${placement}`;
      const job =
        kind === "wait"
          ? {
              steps: [
                {
                  id: "work",
                  uses: "relay/human-wait@v1",
                  with: {
                    prompt: "Check this nested approval. Respond YES.",
                  },
                },
              ],
            }
          : {
              steps: [
                {
                  id: "work",
                  uses: "relay/agent@v1",
                  with: {
                    agent: "codex",
                    model: "m1",
                  },
                },
              ],
            };
      await create(page, `${key}-child`, { question: job }, true);
      const group = placement === "repair" ? "repairs" : "rounds";
      await create(
        page,
        key,
        placement === "child"
          ? { child: { uses: `./.relay/workflows/${key}-child.yaml` } }
          : {
              [group]: {
                steps: [
                  {
                    uses: "relay/loop@v1",
                    with: {
                      workflow: `./.relay/workflows/${key}-child.yaml`,
                      "max-iterations": 1,
                    },
                  },
                ],
              },
            },
      );
      const id = await launch(page, key);
      await expect
        .poll(
          async () => {
            const run = await detail(page, id);
            if (run.status === "failed")
              throw new Error(
                run.failure_summary ?? JSON.stringify(run.problem),
              );
            return run.interactions.length;
          },
          { timeout: 20_000 },
        )
        .toBe(1);
      if (placement === "repair") {
        expect(
          (
            await post(page, `/api/runs/${id}/pause`, {
              paused: true,
              idempotency_key: "pause-for-group",
            })
          ).ok(),
        ).toBeTruthy();
      }
      await page.goto(`/?view=runs&run=${id}`);
      const banner = page.getByRole("region", {
        name: "Waiting for you",
        exact: true,
      });
      await expect(banner).toContainText(
        kind === "wait"
          ? "Check this nested approval"
          : kind === "permission"
            ? "Inspect project"
            : "Which component should I check?",
      );
      await expect(banner.getByRole("alert")).toBeInViewport();
      const count = (await waiting(page)).waiting_count;
      await expect(
        page.getByRole("link", { name: `Runs (${count})`, exact: true }),
      ).toBeVisible();
      await expect(page).toHaveTitle(`(${count}) Relay`);
      await expect(
        page.getByRole("heading", { name: new RegExp(`${key} #`) }),
      ).toBeVisible();
      await expect(
        page.getByText("Waiting for you", { exact: true }).last(),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Run history", exact: true })
        .click();
      const historyRun = page.getByRole("link", {
        name: new RegExp(`${key}.*#`),
      });
      await expect(historyRun).toContainText("Waiting for you");
      await historyRun.click();
      await expect(page.getByText(/needs (your )?input/i)).toHaveCount(0);
      await page.getByRole("link", { name: "Workflows", exact: true }).click();
      await expect(
        page.getByRole("link", { name: `Runs (${count})`, exact: true }),
      ).toBeVisible();
      await page
        .getByRole("link", { name: `Runs (${count})`, exact: true })
        .click();
      await banner
        .getByRole("button", { name: "Respond", exact: true })
        .click();
      if (kind === "permission") {
        const decision = page.getByRole("combobox", {
          name: "Your decision",
          exact: true,
        });
        await expect(decision).toBeFocused();
        await decision.click();
        await page
          .getByRole("option", { name: "Allow once", exact: true })
          .click();
      } else {
        const answer = page.getByRole("textbox", {
          name: kind === "wait" ? "Your response" : "Component",
          exact: true,
        });
        await expect(answer).toBeFocused();
        await answer.fill(kind === "wait" ? "YES" : "Editor");
      }
      await page
        .getByRole("button", {
          name: "Send response and continue",
          exact: true,
        })
        .click();
      if (placement === "repair")
        expect(
          (
            await post(page, `/api/runs/${id}/pause`, {
              paused: false,
              idempotency_key: "resume-after-answer",
            })
          ).ok(),
        ).toBeTruthy();
      await expectRunStatus(page, id, "succeeded");
      await expect(banner).toHaveCount(0);
      await page
        .getByRole("navigation", { name: "Jobs", exact: true })
        .getByRole("link", { name: "Summary", exact: true })
        .click();
      await expect(
        page.getByRole("heading", { name: "Artifacts", exact: true }),
      ).toBeVisible();
      await expect(page.getByText(/before sending your response/)).toHaveCount(
        0,
      );
    });
  }

test("returning from Workflows keeps the selected run while another run is queued", async ({
  page,
}) => {
  await create(page, "other-waiting", {
    approval: {
      steps: [
        {
          id: "work",
          uses: "relay/human-wait@v1",
          with: {
            prompt: "Another pending request.",
          },
        },
      ],
    },
  });
  await create(page, "selected-waiting", {
    approval: {
      steps: [
        {
          id: "work",
          uses: "relay/human-wait@v1",
          with: {
            prompt: "Answer this selected run.",
          },
        },
      ],
    },
  });
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const selected = await launch(page, "selected-waiting");
  await expectRunStatus(page, selected, "paused_wait", 30_000);
  const other = await launch(page, "other-waiting");
  activeRun = selected;
  try {
    expect((await detail(page, other)).interactions).toHaveLength(0);
    await page.goto(`/?view=runs&run=${selected}`);
    await expect(
      page.getByRole("region", { name: "Waiting for you", exact: true }),
    ).toContainText("Answer this selected run.");
    await page.getByRole("link", { name: "Workflows", exact: true }).click();
    await page.getByRole("link", { name: /^Runs \(/ }).click();
    await expect(page).toHaveURL(new RegExp(`run=${selected}`));
    await expect(
      page.getByRole("region", { name: "Waiting for you", exact: true }),
    ).toContainText("Answer this selected run.");
  } finally {
    expect(
      (
        await post(page, `/api/runs/${other}/cancel`, {
          idempotency_key: "other-wait-cleanup",
        })
      ).ok(),
    ).toBeTruthy();
    await expect
      .poll(async () => (await detail(page, other)).waiting_count)
      .toBe(0);
  }
});

test("a job log keeps its pending response available above the output", async ({
  page,
}) => {
  await create(page, "waiting-job-log", {
    approval: {
      steps: [
        {
          id: "work",
          uses: "relay/human-wait@v1",
          with: {
            prompt: "Read the job output and approve.",
          },
        },
      ],
    },
  });
  const id = await launch(page, "waiting-job-log");
  await expect
    .poll(async () => (await detail(page, id)).interactions.length)
    .toBe(1);
  await page.goto(`/?view=runs&run=${id}&job=root.approval`);
  const banner = page.getByRole("region", {
    name: "Waiting for you",
    exact: true,
  });
  await banner.getByRole("button", { name: "Respond", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "Your response", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("textbox", { name: "Your response", exact: true })
    .fill("Approved");
  await page
    .getByRole("button", { name: "Send response and continue", exact: true })
    .click();
  await expect
    .poll(async () => (await detail(page, id)).status)
    .toBe("succeeded");
  await expect(banner).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Job log", exact: true }),
  ).toBeVisible();
});

for (const delivery of [
  "missing stream tail",
  "late pending read",
  "late node read",
] as const)
  test(`a human-wait job reconciles its answer after a ${delivery}`, async ({
    page,
  }) => {
    const key = `waiting-${delivery.replaceAll(" ", "-")}.yaml`;
    const created = await post(page, "/api/workflows", {
      key,
      holder: key,
      yaml: stringify({
        name: key,
        on: "workflow_dispatch",
        jobs: {
          review: {
            steps: [
              {
                id: "approval",
                uses: "relay/human-wait@v1",
                with: { prompt: "Approve this exact job." },
              },
            ],
          },
        },
      }),
    });
    expect(created.status(), await created.text()).toBe(201);
    const id = await launch(page, key);
    await expect
      .poll(async () => (await detail(page, id)).interactions.length)
      .toBe(1);
    const interaction = (await detail(page, id)).interactions[0];
    if (!interaction) throw new Error("The human-wait request is missing.");

    const streamStarted = gate();
    const streamReady = gate();
    const staleReady = gate();
    const staleRelease = gate();
    const freshReady = gate();
    const freshRelease = gate();
    let streamSince = 0;
    let streamBody = "";
    let holding = false;
    let readsAfterAnswer = 0;
    await page.route(
      (url) => url.pathname === `/api/runs/${id}/stream`,
      async (route) => {
        streamSince = Number(
          new URL(route.request().url()).searchParams.get("since") ?? 0,
        );
        streamStarted.release();
        await streamReady.pending;
        await route.fulfill({
          contentType: "text/event-stream",
          body: streamBody,
        });
      },
    );
    try {
      await page.goto(
        `/?view=runs&run=${id}&job=${encodeURIComponent(interaction.scope_path)}`,
      );
      await streamStarted.pending;
      const banner = page.getByRole("region", {
        name: "Waiting for you",
        exact: true,
      });
      const job = page.getByRole("region", { name: "Job log", exact: true });
      await expect(banner).toContainText("Approve this exact job.");
      await expect(
        job.getByRole("combobox", { name: "Attempt", exact: true }),
      ).toContainText("Waiting");
      await job.getByRole("button", { name: "Outputs", exact: true }).click();
      await expect(job.getByText("No declared outputs.")).toBeVisible();
      if (delivery !== "missing stream tail") {
        let held = false;
        await page.route(
          (url) => url.pathname === `/api/runs/${id}/monitor`,
          async (route) => {
            const response = await route.fetch();
            if (held) {
              readsAfterAnswer += 1;
              freshReady.release();
              await freshRelease.pending;
              await route.fulfill({ response });
              return;
            }
            held = true;
            holding = true;
            const saved = await response.json();
            expect(saved.run.status).toBe("paused_wait");
            expect(
              saved.interactions.map((item: { id: string }) => item.id),
            ).toContain(interaction.id);
            expect(
              saved.nodes.find(
                (node: { scope_path: string }) =>
                  node.scope_path === interaction.scope_path,
              )?.status,
            ).toBe("waiting");
            // A stale publication leaves visible evidence even if the next read repairs it.
            saved.interactions[0].request.prompt =
              "STALE MONITOR WAS PUBLISHED";
            staleReady.release();
            await staleRelease.pending;
            holding = false;
            await route.fulfill({ response, json: saved });
          },
        );
        await page.evaluate(() => {
          (
            window as unknown as { staleMonitorPublished: boolean }
          ).staleMonitorPublished = false;
          new MutationObserver(() => {
            if (
              document.body.textContent?.includes("STALE MONITOR WAS PUBLISHED")
            )
              (
                window as unknown as { staleMonitorPublished: boolean }
              ).staleMonitorPublished = true;
          }).observe(document.body, {
            subtree: true,
            childList: true,
            characterData: true,
          });
        });
        await page
          .getByRole("button", { name: "Refresh", exact: true })
          .click();
        await staleReady.pending;
      }
      const answer = "Approved without losing the final state.";
      const answered = await post(
        page,
        `/api/attempts/${interaction.attempt_id}/wait`,
        {
          interaction_id: interaction.id,
          idempotency_key: `answer-${delivery}`,
          value: answer,
        },
      );
      expect(answered.status(), await answered.text()).toBe(202);
      await expect
        .poll(async () => (await detail(page, id)).status)
        .toBe("succeeded");
      if (delivery !== "missing stream tail") {
        const replay: { events: RunEvent[] } = await (
          await page.request.get(
            `/api/runs/${id}/events?since=${streamSince}&limit=100`,
          )
        ).json();
        expect(
          replay.events.some((event) => event.type === "wait.answered"),
        ).toBe(true);
        streamBody = replay.events
          .map(
            (event) =>
              `id: ${event.id}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
          )
          .join("");
      }
      streamReady.release();
      if (holding) {
        // Let EventSource deliver the observed state version before the old read returns.
        await page
          .waitForResponse(
            (response) =>
              new URL(response.url()).pathname === `/api/runs/${id}/stream`,
          )
          .catch(() => undefined);
        await page.evaluate(
          () =>
            new Promise<void>((resolve) =>
              requestAnimationFrame(() =>
                requestAnimationFrame(() => resolve()),
              ),
            ),
        );
        staleRelease.release();
        await freshReady.pending;
        expect(readsAfterAnswer).toBeGreaterThan(0);
        expect(
          await page.evaluate(
            () =>
              (window as unknown as { staleMonitorPublished: boolean })
                .staleMonitorPublished,
          ),
        ).toBe(false);
        freshRelease.release();
      }
      await expect(banner).toHaveCount(0);
      await expect(
        job.getByRole("combobox", { name: "Attempt", exact: true }),
      ).toHaveText("Attempt 1 · Completed");
      await expect(
        job.getByRole("table", { name: "Declared outputs", exact: true }),
      ).toContainText(answer);
      await expect(
        page.getByRole("button", { name: "Pause", exact: true }),
      ).toHaveCount(0);
      if (delivery !== "missing stream tail")
        expect(
          await page.evaluate(
            () =>
              (window as unknown as { staleMonitorPublished: boolean })
                .staleMonitorPublished,
          ),
        ).toBe(false);
    } finally {
      streamReady.release();
      staleRelease.release();
      freshRelease.release();
      await page.unrouteAll({ behavior: "wait" });
    }
  });

test("desktop notifications require opt-in and announce new waits and completions", async ({
  page,
}) => {
  const calls: string[] = [];
  await page.exposeFunction("relayTestNotification", (title: string) =>
    calls.push(title),
  );
  await page.addInitScript(() => {
    class TestNotification {
      static permission =
        localStorage.getItem("relay.notifications") === "true"
          ? "granted"
          : "default";
      static async requestPermission() {
        this.permission = "granted";
        return "granted";
      }
      onclick: (() => void) | null = null;
      constructor(title: string) {
        void window.relayTestNotification(title);
      }
      close() {}
    }
    Object.defineProperty(window, "Notification", { value: TestNotification });
  });
  await page.goto("/?view=workflows");
  expect(calls).toEqual([]);
  expect(
    await page.evaluate(() => localStorage.getItem("relay.notifications")),
  ).toBeNull();
  await page
    .getByRole("button", { name: /^(Help|Account menu for owner)$/ })
    .click();
  await page
    .getByRole("menuitem", {
      name: "Enable desktop notifications",
      exact: true,
    })
    .click();
  await expect
    .poll(() =>
      page.evaluate(() => localStorage.getItem("relay.notifications")),
    )
    .toBe("true");
  await create(page, "notify-wait", {
    approval: {
      steps: [
        {
          id: "work",
          uses: "relay/human-wait@v1",
          with: {
            prompt: "Approve this run.",
          },
        },
      ],
    },
  });
  const id = await launch(page, "notify-wait");
  await expect
    .poll(async () => (await detail(page, id)).interactions.length)
    .toBe(1);
  await page.evaluate(() =>
    window.dispatchEvent(new Event("relay-attention-change")),
  );
  await expect.poll(() => calls).toContain("Relay is waiting for you");
  await page.goto(`/?view=runs&run=${id}`);
  await page
    .getByRole("region", { name: "Waiting for you", exact: true })
    .getByRole("button", { name: "Respond", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Your response", exact: true })
    .fill("YES");
  await page
    .getByRole("button", { name: "Send response and continue", exact: true })
    .click();
  await expect.poll(() => calls).toContain("Relay run complete");
  await page
    .getByRole("button", { name: /^(Help|Account menu for owner)$/ })
    .click();
  await page
    .getByRole("menuitem", {
      name: "Disable desktop notifications",
      exact: true,
    })
    .click();
  expect(
    await page.evaluate(() => localStorage.getItem("relay.notifications")),
  ).toBeNull();
});

for (const support of ["denied", "unavailable"] as const)
  test(`notification permission ${support} leaves waiting counts available`, async ({
    page,
  }) => {
    await page.addInitScript((value) => {
      if (value === "unavailable")
        Reflect.deleteProperty(window, "Notification");
      else {
        class DeniedNotification {
          static permission = "denied";
          static async requestPermission() {
            return "denied";
          }
        }
        Object.defineProperty(window, "Notification", {
          value: DeniedNotification,
        });
      }
    }, support);
    await page.goto("/?view=workflows");
    await page
      .getByRole("button", { name: /^(Help|Account menu for owner)$/ })
      .click();
    await page
      .getByRole("menuitem", {
        name: "Enable desktop notifications",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("alert").filter({
        hasText:
          support === "denied"
            ? "notifications are blocked"
            : "does not support desktop notifications",
      }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => localStorage.getItem("relay.notifications")),
    ).toBeNull();
    await page.evaluate(() =>
      window.dispatchEvent(new Event("relay-attention-change")),
    );
    const count = (await waiting(page)).waiting_count;
    await expect(
      page.getByRole("link", {
        name: count ? `Runs (${count})` : "Runs",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page).toHaveTitle(count ? `(${count}) Relay` : "Relay");
  });
