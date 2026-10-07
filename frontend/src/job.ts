import type { RunEvent } from "./types";

export function jobDuration(started?: string | null, ended?: string | null): string {
  if (!started) return "Not started";
  const seconds = Math.max(0, Math.floor(((ended ? Date.parse(ended) : Date.now()) - Date.parse(started)) / 1000));
  if (!Number.isFinite(seconds)) return "Duration unavailable";
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export interface AnsiSpan { text: string; color?: string; bold?: boolean }
export interface AnsiStyle { color?: string; bold: boolean }
const COLORS = ["#cbd5e1", "#f87171", "#86efac", "#fde047", "#93c5fd", "#d8b4fe", "#67e8f9", "#ffffff"];

function palette(value: number): string | undefined {
  if (!Number.isInteger(value) || value < 0 || value > 255) return undefined;
  if (value < 16) return COLORS[value % 8];
  if (value >= 232) { const grey = 8 + (value - 232) * 10; return `rgb(${grey}, ${grey}, ${grey})`; }
  const index = value - 16;
  const level = (part: number) => part === 0 ? 0 : 55 + part * 40;
  return `rgb(${level(Math.floor(index / 36))}, ${level(Math.floor(index / 6) % 6)}, ${level(index % 6)})`;
}

export function ansiSpans(text: string, style: AnsiStyle = { bold: false }): AnsiSpan[] {
  const spans: AnsiSpan[] = [];
  let color = style.color;
  let bold = style.bold;
  // Only known SGR colors become styles. Cursor controls and OSC links are inert.
  const clean = text.replace(/\x1b\](?:[^\x07\x1b]|\x1b(?!\\))*(?:\x07|\x1b\\)/g, "");
  const pattern = /\x1b\[([0-9;?]*)([A-Za-z])/g;
  let after = 0;
  for (const match of clean.matchAll(pattern)) {
    const index = match.index;
    if (index > after) spans.push({ text: clean.slice(after, index), color, bold });
    const values = (match[1] || "0").split(";").map(Number);
    if (match[2] === "m") for (let cursor = 0; cursor < values.length; cursor += 1) {
      const value = values[cursor];
      if (value === 0) { color = undefined; bold = false; }
      else if (value === 1) bold = true;
      else if (value === 22) bold = false;
      else if (value === 39) color = undefined;
      else if (value >= 30 && value <= 37) color = COLORS[value - 30];
      else if (value >= 90 && value <= 97) color = COLORS[value - 90];
      else if (value === 38 && values[cursor + 1] === 5) { color = palette(values[cursor + 2]); cursor += 2; }
      else if (value === 38 && values[cursor + 1] === 2) {
        const rgb = values.slice(cursor + 2, cursor + 5);
        if (rgb.length === 3 && rgb.every((part) => Number.isInteger(part) && part >= 0 && part <= 255)) color = `rgb(${rgb.join(", ")})`;
        cursor += 4;
      }
    }
    after = index + match[0].length;
  }
  if (after < clean.length) spans.push({ text: clean.slice(after), color, bold });
  style.color = color; style.bold = bold;
  return spans;
}

export interface TerminalLine { stream: "stdout" | "stderr"; text: string }
export function commandLines(events: RunEvent[]): TerminalLine[] {
  const lines: TerminalLine[] = [];
  let pending = false;
  for (const event of events) {
    if (event.type !== "command.stdout" && event.type !== "command.stderr") continue;
    const stream = event.type === "command.stderr" ? "stderr" : "stdout";
    const text = event.payload.chunk ?? event.payload.text;
    if (typeof text !== "string" || !text) continue;
    const parts = text.split("\n");
    for (let index = 0; index < parts.length; index += 1) {
      if (index === parts.length - 1 && !parts[index]) { pending = false; break; }
      let line = pending ? lines.at(-1) : undefined;
      if (!line || line.stream !== stream) { line = { stream, text: "" }; lines.push(line); }
      line.text += parts[index];
      pending = index === parts.length - 1;
    }
  }
  return lines;
}
