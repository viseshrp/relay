import {
  activityRows,
  relativeActivityText,
  type ActivityMessage,
} from "./activity";
import { ansiSpans, type AnsiSpan, type AnsiStyle } from "./job";
import type { RunEvent } from "./types";

export interface LogRow {
  id: string;
  text: string;
  timestamp: string;
  spans?: AnsiSpan[];
  message?: ActivityMessage;
}
export interface LogMatch {
  row: number;
  start: number;
  end: number;
}
export function logRows(
  events: RunEvent[],
  command: boolean,
  workingFolder?: string,
): LogRow[] {
  if (!command)
    return activityRows(events).map((message) => ({
      id: String(message.id),
      timestamp: message.timestamp,
      message,
      text: relativeActivityText(
        `${message.text}\n${message.tool?.title ?? ""}\n${message.tool?.input ?? ""}\n${message.tool?.output ?? ""}`,
        workingFolder,
      ),
    }));
  const rows: LogRow[] = [];
  let pending = false;
  let previousStream = "";
  for (const event of events) {
    if (!["command.stdout", "command.stderr"].includes(event.type)) continue;
    const chunk = event.payload.chunk ?? event.payload.text;
    if (typeof chunk !== "string" || !chunk) continue;
    const parts = chunk.split("\n");
    for (let part = 0; part < parts.length; part += 1) {
      if (part === parts.length - 1 && !parts[part]) {
        pending = false;
        break;
      }
      let row =
        pending && previousStream === event.type ? rows.at(-1) : undefined;
      if (!row) {
        row = { id: `${event.id}:${part}`, timestamp: event.ts, text: "" };
        rows.push(row);
      }
      row.text += parts[part];
      previousStream = event.type;
      pending = part === parts.length - 1;
    }
  }
  const style: AnsiStyle = { bold: false };
  return rows.map((row) => {
    const spans = ansiSpans(row.text, style);
    return { ...row, text: spans.map((span) => span.text).join(""), spans };
  });
}
export function logMatches(rows: LogRow[], search: string): LogMatch[] {
  if (!search) return [];
  const needle = search.toLocaleLowerCase();
  return rows.flatMap((row, index) => {
    const text = row.text.toLocaleLowerCase();
    const matches: LogMatch[] = [];
    for (
      let start = text.indexOf(needle);
      start !== -1;
      start = text.indexOf(needle, start + needle.length)
    ) {
      matches.push({ row: index, start, end: start + needle.length });
    }
    return matches;
  });
}
export function rawLog(events: RunEvent[], command: boolean): string {
  if (command)
    return events
      .filter((event) =>
        ["command.stdout", "command.stderr"].includes(event.type),
      )
      .map((event) => String(event.payload.chunk ?? event.payload.text ?? ""))
      .join("");
  return activityRows(events)
    .map((message) => `[${message.timestamp}] ${message.text}`)
    .join("\n\n");
}
