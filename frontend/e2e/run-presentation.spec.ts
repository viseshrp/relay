import { expect, test } from "./a11y-test";
import { activityMessages } from "../src/activity";
import { capturedRunGraph } from "../src/graph";
import type { RunEvent, RunNode } from "../src/types";

function event(
  id: number,
  type: string,
  payload: RunEvent["payload"],
): RunEvent {
  return {
    version: 1,
    id,
    type,
    source: "agent",
    ts: "2026-10-04T12:00:00Z",
    payload: { scope_path: "root.build", attempt_number: 1, ...payload },
  };
}

test("activity retains message, attempt, turn, and stdout/stderr boundaries", () => {
  const messages = activityMessages([
    event(1, "attempt.started", { agent_id: "codex" }),
    event(2, "agent.message", { text: "Hello ", message_id: "a", turn: 1 }),
    event(3, "agent.message", { text: "world\n", message_id: "a", turn: 1 }),
    event(4, "agent.message", {
      text: "Separate message",
      message_id: "b",
      turn: 1,
    }),
    event(5, "agent.message", { text: "Next turn", message_id: "b", turn: 2 }),
    event(6, "command.stdout", { chunk: "one" }),
    event(7, "command.stdout", { chunk: " line\n" }),
    event(8, "command.stderr", { chunk: "error\n" }),
    event(9, "command.stdout", { chunk: "later\n", attempt_number: 2 }),
  ]);
  expect(messages.map((message) => message.text)).toEqual([
    "Hello world\n",
    "Separate message",
    "Next turn",
    "one line\n",
    "error\n",
    "later\n",
  ]);
  expect(messages[0].agent).toBe("codex");
  expect(messages[0].lastId).toBe(3);
});

test("split tool results reassemble and keep the original tool name", () => {
  const messages = activityMessages([
    event(1, "agent.tool_call", {
      tool: "Read report",
      tool_call_id: "call-1",
      summary: '{"status":"pending"}',
    }),
    event(2, "agent.tool_result", {
      tool: "call-1",
      tool_call_id: "call-1",
      summary: '{"status":"completed",',
      part: 1,
      parts: 2,
    }),
    event(3, "agent.tool_result", {
      tool: "call-1",
      tool_call_id: "call-1",
      summary: '"content":[{"text":"Ready: Yes"}]}',
      part: 2,
      parts: 2,
    }),
  ]);
  expect(messages[1].text).toBe("Read report · completed\nReady: Yes");
  expect(messages[1].lastId).toBe(3);
});

test("native Antigravity tools show the command and output without raw JSON", () => {
  const messages = activityMessages([
    event(1, "agent.tool_result", {
      tool: "run_command",
      tool_call_id: "conversation:3",
      summary: JSON.stringify({
        state: "DONE",
        tool_info: {
          parameters: { CommandLine: "git status --short" },
          output: " M app.py\n",
        },
      }),
    }),
  ]);
  expect(messages[0].text).toBe(
    "run_command · DONE\ngit status --short\n M app.py\n",
  );
});

test("tool summaries omit opaque IDs and duplicate command titles", () => {
  const messages = activityMessages([
    event(1, "agent.tool_call", {
      tool: "git status",
      summary: '{"raw_input":{"command":"git status"}}',
    }),
    event(2, "agent.tool_call", {
      tool: "call-a",
      tool_call_id: "call-a",
      summary: "{}",
    }),
    event(3, "agent.tool_result", {
      tool: "call-a",
      tool_call_id: "call-a",
      summary:
        '{"kind":"execute","status":"completed","content":[{"text":"clean"}]}',
    }),
    event(4, "agent.tool_result", {
      tool: "call-b",
      tool_call_id: "call-b",
      summary: '{"status":"completed"}',
    }),
  ]);
  expect(messages.map((message) => message.text)).toEqual([
    "git status",
    "Execute · completed\nclean",
    "Tool · completed",
  ]);
});

function node(
  scope_path: string,
  dependencies: string[] = [],
  parent_scope: string | null = null,
): RunNode {
  return {
    id: scope_path,
    scope_path,
    node_id: scope_path.split(".").at(-1)!,
    node_type: "actions_job",
    status: "succeeded",
    writes: false,
    dependencies,
    parent_scope,
  };
}

test("the top-level scope adds no synthetic completion job", () => {
  const graph = capturedRunGraph([
    node("root.first", [], "root"),
    node("root.second", ["root.first"], "root"),
    node("root.child", ["root.second"], "root"),
    node("root.child.check", [], "root.child"),
  ]);
  expect(graph.nodes.map((stage) => stage.id)).toEqual([
    "root.first",
    "root.second",
    "root.child",
    "root.child.check",
  ]);
  expect(graph.edges.map((edge) => [edge.source, edge.target])).toEqual([
    ["root.first", "root.second"],
    ["root.second", "root.child"],
  ]);
  expect(
    graph.nodes.some((stage) => stage.id === "root::complete"),
  ).toBeFalsy();
});
import { post } from "./setup-helpers";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
});

test("answer buttons resume an exact approval; steps stay inside jobs; terminal runs open no stream", async ({
  page,
}) => {
  const yaml = `name: Approval smoke\non: workflow_dispatch\njobs:\n  review:\n    steps:\n      - id: approval\n        name: Approve release\n        uses: relay/human-wait@v1\n        with:\n          prompt: Choose Approve or Reject.\n          options: '["Approve","Reject"]'\n      - run: echo Ready\n`;
  const created = await post(page, "/api/workflows", {
    key: "approval-smoke",
    holder: "approval-smoke",
    yaml,
  });
  expect(created.status(), await created.text()).toBe(201);
  const launch = await post(page, "/api/runs", {
    workflow_key: "approval-smoke.yaml",
    inputs: {},
  });
  expect(launch.status(), await launch.text()).toBe(201);
  const id = (await launch.json()).run_id;
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${id}`)).json()).run
          .waiting_count,
    )
    .toBe(1);
  await page.goto(`/?view=runs&run=${id}`);
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  await expect(jobs.locator("[data-job-scope]")).toHaveCount(1);
  await page
    .getByRole("region", { name: "Waiting for you", exact: true })
    .getByRole("button", { name: "Respond", exact: true })
    .click();
  await expect(page.getByText(/Expires.*default job timeout/)).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Review material" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${id}`)).json()).run.status,
    )
    .toBe("succeeded");
  let streams = 0;
  page.on("request", (request) => {
    if (request.url().includes("/stream?")) streams += 1;
  });
  await page.reload();
  await expect(jobs.locator("[data-job-scope]")).toHaveCount(1);
  await jobs.locator("[data-job-scope]").click();
  const steps = page.getByRole("region", { name: "Job steps", exact: true });
  await expect(
    steps.getByRole("button", { name: /Approve release/ }),
  ).toBeVisible();
  await steps.getByRole("button", { name: /Step 2/ }).click();
  await expect(
    page.getByRole("region", { name: "Command output lines" }),
  ).toContainText("Ready");
  expect(streams).toBe(0);
});

test("run views show names, rounds, and one row per file", async ({ page }) => {
  test.setTimeout(150_000);
  expect(
    (
      await post(page, "/__test__/starter-project", { full_workflow: true })
    ).ok(),
  ).toBeTruthy();
  const created = await post(page, "/api/workflows", {
    key: "named-run",
    name: "AI coding workflow",
    holder: "named-run",
    template_id: "ai-coding-workflow",
  });
  expect(created.status(), await created.text()).toBe(201);
  const launch = await post(page, "/api/runs", {
    workflow_key: (await created.json()).key,
    inputs: {
      task: "Add dark mode",
      agent: "codex",
      model: "m1",
      opus_model: "m2",
    },
  });
  expect(launch.status(), await launch.text()).toBe(201);
  const id: string = (await launch.json()).run_id;
  await page.goto(`/?view=runs&run=${id}`);
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  async function expectNamedView(): Promise<void> {
    await expect(
      page.getByText("Started manually · 9 jobs", { exact: true }),
    ).toBeVisible();
    // Queued jobs already show their declared names, not their IDs.
    await expect(
      jobs.getByText("Human review of the audited test diff", { exact: true }),
    ).toBeVisible();
    for (const generated of ["iteration", "cycle", "refine_plan", "Cycle"])
      await expect(page.getByText(generated, { exact: true })).toHaveCount(0);
    await expect(page.getByText(/Iteration \d/)).toHaveCount(0);
  }
  const answeredIds = new Set<string>();
  for (const answer of ["IMPLEMENT", "TESTS", "ACCEPT"]) {
    let pending: { id: string; attempt_id: string } | undefined;
    await expect
      .poll(
        async () => {
          const monitor = await (
            await page.request.get(`/api/runs/${id}/monitor`)
          ).json();
          pending = monitor.interactions.find(
            (item: { id: string; status: string }) =>
              item.status === "pending" && !answeredIds.has(item.id),
          );
          return Boolean(pending);
        },
        { timeout: 45_000 },
      )
      .toBe(true);
    await expectNamedView();
    if (answer === "IMPLEMENT")
      await expect(jobs.getByText("Round 1", { exact: true })).toBeVisible();
    const answered = await post(
      page,
      `/api/attempts/${pending!.attempt_id}/wait`,
      {
        idempotency_key: crypto.randomUUID(),
        interaction_id: pending!.id,
        value: answer,
      },
    );
    expect(answered.ok(), await answered.text()).toBeTruthy();
    answeredIds.add(pending!.id);
  }
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${id}`)).json()).run.status,
      { timeout: 60_000 },
    )
    .toBe("succeeded");
  await page.reload();
  await expectNamedView();
  await expect(jobs.getByText("Plan round", { exact: true })).toBeVisible();
  const table = page.getByRole("table", {
    name: "Retained artifacts",
    exact: true,
  });
  // Copies of one working-copy file collapse into its newest row.
  const rows = table
    .locator("tbody tr")
    .filter({ hasText: "INITIAL_OPUS_PLANNING_PROMPT.md" });
  await expect(rows).toHaveCount(1);
  await expect(rows.getByText(/^\d+ earlier cop(y|ies)$/)).toBeVisible();
  await expect(table.getByText("cycle", { exact: true })).toHaveCount(0);
});
