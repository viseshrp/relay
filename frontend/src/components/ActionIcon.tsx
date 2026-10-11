import { statusPresentation } from "../status";

export type ActionGlyph =
  | "agent"
  | "command"
  | "loop"
  | "human"
  | "folder"
  | "summary"
  | "workflow"
  | "clock"
  | "branch"
  | "commit"
  | "search"
  | "chevron"
  | "up"
  | "down"
  | "refresh"
  | "settings"
  | "more"
  | "fullscreen"
  | "artifact"
  | "back"
  | "filter"
  | "check"
  | "cross"
  | "pause"
  | "skip"
  | "circle";
const paths: Record<ActionGlyph, string> = {
  agent: "M8 3h8v4h4v14H4V7h4ZM8 12h.01M16 12h.01M8 17h8M12 3V1",
  command: "m4 5 6 7-6 7M12 19h8",
  loop: "M19 8a8 8 0 1 0 1 7M19 3v6h-6",
  human: "M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M4 22v-4c0-6 16-6 16 0v4",
  folder: "M3 7V4h6l3 3h9v13H3ZM3 7h18",
  summary: "M3 10 12 3l9 7v11h-6v-7H9v7H3Z",
  workflow: "M4 3h11l5 5v13H4ZM15 3v6h5M8 13h8M8 17h6",
  clock: "M12 6v6l4 2",
  branch: "M6 6v12M18 6v4c0 4-12 0-12 6M3 3h6v6H3ZM3 15h6v6H3ZM15 3h6v6h-6Z",
  commit: "M3 12h5m8 0h5M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  search: "M16 16l5 5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  chevron: "m9 5 7 7-7 7",
  up: "m5 15 7-7 7 7",
  down: "m5 9 7 7 7-7",
  refresh:
    "M20 10a8 8 0 0 0-14-4L3 9m0-6v6h6M4 14a8 8 0 0 0 14 4l3-3m0 6v-6h-6",
  settings:
    "m10 3-1 3-3 1-3-1-2 4 2 2v3l-2 2 2 4 3-1 3 1 1 3h4l1-3 3-1 3 1 2-4-2-2v-3l2-2-2-4-3 1-3-1-1-3ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  fullscreen: "M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6",
  artifact: "M3 7l9-4 9 4v12l-9 4-9-4ZM3 7l9 4 9-4M12 11v12",
  back: "M20 12H4m6-6-6 6 6 6",
  filter: "M3 5h18M6 12h12M10 19h4",
  check: "m6 12 4 4 8-9",
  cross: "m8 8 8 8m0-8-8 8",
  pause: "M9 8v8m6-8v8",
  skip: "m5 19 14-14",
  circle: "",
};
export function ActionIcon({
  name,
  size = 18,
}: {
  name: ActionGlyph;
  size?: number;
}) {
  return (
    <svg
      style={{ flexShrink: 0 }}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {name === "clock" && <circle cx="12" cy="12" r="9" />}
      <path d={paths[name]} />
    </svg>
  );
}
export function StatusIcon({
  status,
  size = 18,
}: {
  status: string;
  size?: number;
}) {
  const { symbol, tone, label } = statusPresentation(status);
  return (
    <span
      role="img"
      aria-label={label}
      className={`status-icon status-${tone}`}
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
      >
        <circle
          cx="12"
          cy="12"
          r="10"
          fill={
            symbol === "check" || symbol === "cross" ? "currentColor" : "none"
          }
          stroke="currentColor"
          strokeWidth="2"
        />
        <path
          d={paths[symbol]}
          fill="none"
          stroke={
            symbol === "check" || symbol === "cross" ? "white" : "currentColor"
          }
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
