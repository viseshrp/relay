import type { JsonValue, RunEvent } from "./types";
import { stageLabel } from "./navigation";

export interface ActivityMessage {
  id: number;
  lastId: number;
  scope: string;
  attempt: number | null;
  agent: string;
  kind: string;
  text: string;
  timestamp: string;
}

function record(value: JsonValue | undefined): Record<string, JsonValue> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}

function readableOutput(event: RunEvent, toolNames: Map<string, string>, owner: string): string | null {
  if (["agent.message", "agent.thought", "agent.stderr", "command.stdout", "command.stderr"].includes(event.type)) {
    const text = event.payload.text ?? event.payload.chunk;
    return typeof text === "string" ? text : null;
  }
  if (event.type === "agent.tool_call" || event.type === "agent.tool_result") {
    let summary: Record<string, JsonValue> | null = null;
    if (typeof event.payload.summary === "string") {
      try { summary = record(JSON.parse(event.payload.summary)); } catch { /* Raw parts stay in diagnostics. */ }
    }
    const toolId = typeof event.payload.tool_call_id === "string" ? `${owner}:${event.payload.tool_call_id}` : "";
    let title = typeof event.payload.tool === "string" ? event.payload.tool : "Tool";
    if (toolId && title === event.payload.tool_call_id) title = toolNames.get(toolId) ?? "Tool";
    // Older Claude events stored toolu_01ABC as a title. Show "Execute" (or
    // "Tool") instead; the original identifier stays in Advanced diagnostics.
    if (/^(?:toolu_[A-Za-z0-9]+|exec-[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})$/i.test(title)) title = "Tool";
    if (title === "Tool" && typeof summary?.kind === "string") title = stageLabel(summary.kind);
    if (toolId && title !== "Tool") toolNames.set(toolId, title);
    const content = summary?.content;
    const text = Array.isArray(content) ? content.flatMap((item) => {
      const value = record(item);
      if (typeof value?.text === "string") return [value.text];
      if (typeof value?.path === "string") return [`Changed ${value.path}`];
      return [];
    }).join("\n") : "";
    const native = record(summary?.tool_info);
    const output = native?.output ?? summary?.raw_output;
    const visible = text || (typeof output === "string" ? output : "");
    const input = record(native?.parameters ?? summary?.raw_input);
    const command = input?.command ?? input?.CommandLine ?? input?.path ?? input?.file_path;
    const status = summary?.status ?? summary?.state;
    if (title === "Tool" && !status && !command && !visible) return null;
    // A title "git status" with the same command shows it once, not twice.
    return `${title}${typeof status === "string" ? ` · ${status}` : ""}${typeof command === "string" && command !== title ? `\n${command}` : ""}${visible ? `\n${visible}` : ""}`;
  }
  if (event.type === "agent.plan" && Array.isArray(event.payload.plan)) {
    return event.payload.plan.flatMap((item) => {
      const entry = record(item);
      return typeof entry?.content === "string" ? [`• ${entry.content}`] : [];
    }).join("\n");
  }
  if (event.type === "command.exit") return `Command finished${typeof event.payload.exit_code === "number" ? ` with exit code ${event.payload.exit_code}` : ""}.`;
  if (event.type === "agent.cleanup_warning") return typeof event.payload.message === "string" ? event.payload.message : null;
  return null;
}

export function activityMessages(events: RunEvent[]): ActivityMessage[] {
  const agents = new Map<string, string>();
  const toolNames = new Map<string, string>();
  const rows: Array<{ message: ActivityMessage; chunks: string[] }> = [];
  let previousKey: string | null = null;
  for (let index = 0; index < events.length; index += 1) {
    let event = events[index];
    let lastId = event.id;
    // Split JSON summaries arrive as ordered parts. Join before parsing:
    // '{"status":' + '"completed"}' becomes one readable tool result.
    if (event.payload.part === 1 && typeof event.payload.parts === "number") {
      const field = ["text", "summary", "chunk"].find((name) => typeof event.payload[name] === "string");
      if (field) {
        const chunks = [String(event.payload[field])];
        for (let part = 2; part <= event.payload.parts; part += 1) {
          const next = events[index + 1];
          if (!next || next.type !== event.type || next.payload.part !== part || next.payload.parts !== event.payload.parts || next.payload.scope_path !== event.payload.scope_path || next.payload.attempt_number !== event.payload.attempt_number) break;
          chunks.push(String(next.payload[field] ?? "")); lastId = next.id; index += 1;
        }
        const combined = chunks.join("");
        if (field === "chunk" && chunks.length === event.payload.parts) {
          try { event = { ...event, payload: { ...event.payload, ...record(JSON.parse(combined)) } }; } catch { /* Original parts remain in diagnostics. */ }
        } else if (field !== "chunk") event = { ...event, payload: { ...event.payload, [field]: combined } };
      }
    }
    const scope = typeof event.payload.scope_path === "string" ? event.payload.scope_path : "";
    const attempt = typeof event.payload.attempt_number === "number" ? event.payload.attempt_number : null;
    const owner = `${scope}:${attempt}`;
    if (event.type === "attempt.started" && typeof event.payload.agent_id === "string") agents.set(owner, event.payload.agent_id);
    const text = readableOutput(event, toolNames, owner);
    if (text === null) {
      // Permission requests, turn markers, and intervening tool events keep message boundaries intact.
      if (!event.type.startsWith("agent.provider_event")) previousKey = null;
      continue;
    }
    const key = `${owner}:${event.type}:${event.payload.turn ?? ""}:${event.payload.message_id ?? ""}`;
    const join = ["agent.message", "agent.thought", "agent.stderr", "command.stdout", "command.stderr"].includes(event.type);
    if (join && previousKey === key && rows.length > 0) {
      rows[rows.length - 1].chunks.push(text);
      rows[rows.length - 1].message.lastId = lastId;
    } else {
      rows.push({ message: {
        id: event.id, lastId, scope, attempt,
        agent: typeof event.payload.agent_id === "string" ? event.payload.agent_id : agents.get(owner) ?? "",
        kind: event.type, text: "", timestamp: event.ts,
      }, chunks: [text] });
    }
    previousKey = join ? key : null;
  }
  // "Hello " + "world\n" becomes "Hello world\n". Join once, retaining exact stream bytes.
  return rows.map(({ message, chunks }) => ({ ...message, text: chunks.join("") }));
}
