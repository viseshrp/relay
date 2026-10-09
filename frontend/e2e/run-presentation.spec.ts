import { expect, test } from "@playwright/test";
import { activityMessages } from "../src/activity";
import { capturedRunGraph } from "../src/graph";
import type { RunEvent, RunNode } from "../src/types";

function event(
  id: number,
  type: string,
  payload: RunEvent["payload"],
): RunEvent {
  return {
    id,
    type,
    version: 1,
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

test("legacy tool summaries omit opaque IDs and duplicate command titles", () => {
  const messages = activityMessages([
    event(1, "agent.tool_call", {
      tool: "git status",
      summary: '{"raw_input":{"command":"git status"}}',
    }),
    event(2, "agent.tool_call", { tool: "toolu_01ABC", summary: "{}" }),
    event(3, "agent.tool_result", {
      tool: "toolu_01ABC",
      summary:
        '{"kind":"execute","status":"completed","content":[{"text":"clean"}]}',
    }),
    event(4, "agent.tool_result", {
      tool: "exec-12345678-1234-1234-1234-123456789abc",
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
    node_type: "command",
    status: "succeeded",
    writes: false,
    loop_index: null,
    dependencies,
    controls: [],
    parent_scope,
    selected_branch: null,
  };
}

test("captured loop iterations and nested branches retain their execution order", () => {
  const graph = capturedRunGraph([
    node("root.repeat"),
    node("root.end", ["root.repeat"]),
    node("root.repeat#1.a", [], "root.repeat#1"),
    node("root.repeat#1.b", ["root.repeat#1.a"], "root.repeat#1"),
    node("root.repeat#2.a", [], "root.repeat#2"),
  ]);
  expect(
    graph.edges.some(
      (edge) =>
        edge.source === "root.repeat#1::complete" &&
        edge.target === "root.repeat#2.a",
    ),
  ).toBeTruthy();
  expect(
    graph.edges.some(
      (edge) =>
        edge.source === "root.repeat#2::complete" && edge.target === "root.end",
    ),
  ).toBeTruthy();
  const positions = new Map(
    graph.nodes.map((stage) => [stage.id, stage.position]),
  );
  expect(positions.get("root.repeat#2.a")!.y).toBeGreaterThan(
    positions.get("root.repeat#1.b")!.y,
  );
  expect(positions.get("root.end")!.y).toBeGreaterThan(
    positions.get("root.repeat#2.a")!.y,
  );
});

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
    "root.child::complete",
  ]);
  expect(
    graph.edges.some(
      (edge) =>
        edge.source === "root.child.check" &&
        edge.target === "root.child::complete",
    ),
  ).toBeTruthy();
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
