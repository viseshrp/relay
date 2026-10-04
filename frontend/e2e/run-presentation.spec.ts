import { expect, test } from "@playwright/test";
import { activityMessages } from "../src/activity";
import { capturedRunGraph } from "../src/graph";
import type { RunEvent, RunNode } from "../src/types";

function event(id: number, type: string, payload: RunEvent["payload"]): RunEvent {
  return { id, type, version: 1, source: "agent", ts: "2026-10-04T12:00:00Z", payload: { scope_path: "root.build", attempt_number: 1, ...payload } };
}

test("activity retains message, attempt, turn, and stdout/stderr boundaries", () => {
  const messages = activityMessages([
    event(1, "attempt.started", { agent_id: "codex" }),
    event(2, "agent.message", { text: "Hello ", message_id: "a", turn: 1 }),
    event(3, "agent.message", { text: "world\n", message_id: "a", turn: 1 }),
    event(4, "agent.message", { text: "Separate message", message_id: "b", turn: 1 }),
    event(5, "agent.message", { text: "Next turn", message_id: "b", turn: 2 }),
    event(6, "command.stdout", { chunk: "one" }),
    event(7, "command.stdout", { chunk: " line\n" }),
    event(8, "command.stderr", { chunk: "error\n" }),
    event(9, "command.stdout", { chunk: "later\n", attempt_number: 2 }),
  ]);
  expect(messages.map((message) => message.text)).toEqual(["Hello world\n", "Separate message", "Next turn", "one line\n", "error\n", "later\n"]);
  expect(messages[0].agent).toBe("codex");
  expect(messages[0].lastId).toBe(3);
});

test("split tool results reassemble and keep the original tool name", () => {
  const messages = activityMessages([
    event(1, "agent.tool_call", { tool: "Read report", tool_call_id: "call-1", summary: '{"status":"pending"}' }),
    event(2, "agent.tool_result", { tool: "call-1", tool_call_id: "call-1", summary: '{"status":"completed",', part: 1, parts: 2 }),
    event(3, "agent.tool_result", { tool: "call-1", tool_call_id: "call-1", summary: '"content":[{"text":"Ready: Yes"}]}', part: 2, parts: 2 }),
  ]);
  expect(messages[1].text).toBe("Read report · completed\nReady: Yes");
  expect(messages[1].lastId).toBe(3);
});

test("native Antigravity tools show the command and output without raw JSON", () => {
  const messages = activityMessages([
    event(1, "agent.tool_result", { tool: "run_command", tool_call_id: "conversation:3", summary: JSON.stringify({
      state: "DONE", tool_info: { parameters: { CommandLine: "git status --short" }, output: " M app.py\n" },
    }) }),
  ]);
  expect(messages[0].text).toBe("run_command · DONE\ngit status --short\n M app.py\n");
});

test("legacy tool summaries omit opaque IDs and duplicate command titles", () => {
  const messages = activityMessages([
    event(1, "agent.tool_call", { tool: "git status", summary: '{"raw_input":{"command":"git status"}}' }),
    event(2, "agent.tool_call", { tool: "toolu_01ABC", summary: '{}' }),
    event(3, "agent.tool_result", { tool: "toolu_01ABC", summary: '{"kind":"execute","status":"completed","content":[{"text":"clean"}]}' }),
  ]);
  expect(messages.map((message) => message.text)).toEqual(["git status", "Execute · completed\nclean"]);
});

function node(scope_path: string, dependencies: string[] = [], parent_scope: string | null = null): RunNode {
  return { id: scope_path, scope_path, node_id: scope_path.split(".").at(-1)!, node_type: "command", status: "succeeded", writes: false, loop_index: null, dependencies, controls: [], parent_scope, selected_branch: null };
}

test("captured loop iterations and nested branches retain their execution order", () => {
  const graph = capturedRunGraph([
    node("root.repeat"), node("root.end", ["root.repeat"]),
    node("root.repeat#1.a", [], "root.repeat#1"),
    node("root.repeat#1.b", ["root.repeat#1.a"], "root.repeat#1"),
    node("root.repeat#2.a", [], "root.repeat#2"),
  ]);
  expect(graph.edges.some((edge) => edge.source === "root.repeat#1::complete" && edge.target === "root.repeat#2.a")).toBeTruthy();
  expect(graph.edges.some((edge) => edge.source === "root.repeat#2::complete" && edge.target === "root.end")).toBeTruthy();
  const positions = new Map(graph.nodes.map((stage) => [stage.id, stage.position]));
  expect(positions.get("root.repeat#2.a")!.y).toBeGreaterThan(positions.get("root.repeat#1.b")!.y);
  expect(positions.get("root.end")!.y).toBeGreaterThan(positions.get("root.repeat#2.a")!.y);
});
