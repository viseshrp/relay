import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from "@mui/material";
import { type UIEvent, useMemo, useState } from "react";

import type {
  ArtifactRecord,
  RunDetail,
  RunEvent,
  RunSummary,
  ProjectRecord,
} from "../types";

import { statusLabel } from "../navigation";

const EVENT_TYPES = [
  "actions.summary",
  "actions.error",
  "actions.warning",
  "actions.notice",
  "actions.debug",
  "actions.group",
  "actions.endgroup",
  "environment.approved",
  "step.recovery_resumed",
  "run.created",
  "run.started",
  "run.paused",
  "run.resumed",
  "run.failing",
  "run.failed",
  "run.canceling",
  "run.canceled",
  "run.interrupted",
  "run.succeeded",
  "run.completing",
  "run.merged",
  "run.rerun",
  "run.retry_scheduled",
  "run.retry_blocked",
  "run.retry_canceled",
  "run.recovery_changed",
  "run.recovery_scheduled",
  "run.recovery_preparing",
  "run.recovery_resumed",
  "run.recovery_blocked",
  "run.recovery_exhausted",
  "run.recovery_canceled",
  "run.dispatch_changed",
  "run.repairs_changed",
  "run.cleanup_succeeded",
  "run.cleanup_failed",
  "resource.cleanup_succeeded",
  "resource.cleanup_failed",
  "node.created",
  "node.ready",
  "node.dispatched",
  "node.running",
  "node.waiting",
  "node.succeeded",
  "node.failed",
  "node.skipped",
  "node.canceled",
  "node.interrupted",
  "node.pending",
  "node.settings_changed",
  "attempt.started",
  "attempt.ended",
  "agent.message",
  "agent.turn_started",
  "agent.thought",
  "agent.tool_call",
  "agent.tool_result",
  "agent.plan",
  "agent.provider_event",
  "agent.usage_limit",
  "agent.result",
  "agent.stderr",
  "agent.cleanup_warning",
  "command.stdout",
  "command.stderr",
  "command.exit",
  "permission.requested",
  "permission.answered",
  "elicitation.requested",
  "elicitation.answered",
  "wait.requested",
  "wait.answered",
  "artifact.preserved",
] as const;
const TERMINAL_RUNS = new Set(["succeeded", "failed", "canceled"]);
const PENDING_RECOVERY = new Set(["scheduled", "preparing"]);
const PAUSABLE_RUNS = new Set([
  "pending",
  "running",
  "paused_wait",
  "failed",
  "interrupted",
]);
const OUTPUT_ROW_HEIGHT = 86;
const OUTPUT_VIEW_HEIGHT = 430;
const VIRTUAL_ROW_OVERSCAN = 3;
interface RunWorkspaceProps {
  selectedRun: string | null;
  selectedWorkflow: string | null;
  onSelectWorkflow: (key: string | null) => void;
  onSelectRun: (runId: string | null) => void;
  onRunWorkflow: (key: string) => void;
  onEditWorkflow: (key: string) => void;
  project: ProjectRecord;
  selectedInteraction: string | null;
  selectedJob: string | null;
  onSelectJob: (scope: string | null) => void;
  waitingRuns: string[];
  onRunSucceeded?: () => void;
}
type DetailCollection = "nodes" | "interactions";
type PageMode = "replace" | "append" | "refresh";
interface RunDetailPage {
  run: RunDetail;
  next: number | null;
}
interface ArtifactPage {
  artifacts: ArtifactRecord[];
  next: number | null;
}
function mergeEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  // Both the API and SSE emit ordered IDs. Most live batches append directly;
  // overlapping pages merge once in linear time, preferring the incoming row.
  if (current.length === 0) return incoming;
  if (incoming.length === 0) return current;
  if (incoming[0].id > current[current.length - 1].id)
    return current.concat(incoming);
  const merged: RunEvent[] = [];
  let left = 0;
  let right = 0;
  while (left < current.length && right < incoming.length) {
    if (current[left].id < incoming[right].id) merged.push(current[left++]);
    else {
      if (current[left].id === incoming[right].id) left += 1;
      merged.push(incoming[right++]);
    }
  }
  return merged.concat(current.slice(left), incoming.slice(right));
}
function mergeRecords<T extends { id: string }>(
  current: T[],
  incoming: T[],
): T[] {
  const records = new Map(current.map((record) => [record.id, record]));
  for (const record of incoming) records.set(record.id, record);
  return Array.from(records.values());
}
function runStatusLabel(run: RunSummary): string {
  // Owner requests take priority over a dispatch pause; finished runs keep their result.
  return run.waiting_count
    ? "Waiting for you"
    : run.dispatch_paused && PAUSABLE_RUNS.has(run.status)
      ? "New jobs paused"
      : statusLabel(run.status);
}
function applyStateEvent(
  current: RunDetail | null,
  event: RunEvent,
): RunDetail | null {
  if (current === null) return null;
  const status = event.payload.status;
  if (
    event.type === "run.dispatch_changed" &&
    typeof event.payload.paused === "boolean"
  ) {
    return {
      ...current,
      dispatch_paused: event.payload.paused,
      dispatch_paused_at:
        typeof event.payload.dispatch_paused_at === "string"
          ? event.payload.dispatch_paused_at
          : null,
      dispatch_paused_seconds:
        typeof event.payload.dispatch_paused_seconds === "number"
          ? event.payload.dispatch_paused_seconds
          : current.dispatch_paused_seconds,
    };
  }
  if (event.type.startsWith("run.") && typeof status === "string") {
    const failed = ["failed", "canceling"].includes(status);
    return {
      ...current,
      status,
      problem: failed ? current.problem : null,
      failure_summary: failed
        ? typeof event.payload.failure_summary === "string"
          ? event.payload.failure_summary
          : current.failure_summary
        : null,
      failure_code: failed
        ? typeof event.payload.failure_code === "string"
          ? event.payload.failure_code
          : current.failure_code
        : null,
    };
  }
  if (event.type.startsWith("node.")) {
    const scopePath = event.payload.scope_path;
    if (typeof scopePath === "string" && typeof status === "string") {
      return {
        ...current,
        nodes: current.nodes.map((node) =>
          node.scope_path === scopePath ? { ...node, status } : node,
        ),
      };
    }
  }
  if (
    event.type === "run.merged" &&
    typeof event.payload.merged_commit === "string"
  ) {
    return { ...current, merged_commit: event.payload.merged_commit };
  }
  if (
    event.type === "run.cleanup_succeeded" ||
    event.type === "run.cleanup_failed"
  ) {
    const worktreeState = event.payload.worktree_state;
    return typeof worktreeState === "string"
      ? { ...current, worktree_state: worktreeState }
      : current;
  }
  return current;
}
function outputText(event: RunEvent): string | null {
  // {text: "Done."} -> "Done."; {plan: ["build"]} -> indented JSON.
  const keys = ["text", "chunk", "summary", "plan", "content", "event"];
  for (const key of keys) {
    const value = event.payload[key];
    if (typeof value === "string") return value;
    if (value !== undefined) return JSON.stringify(value, null, 2);
  }
  return event.type.startsWith("agent.") || event.type.startsWith("command.")
    ? JSON.stringify(event.payload, null, 2)
    : null;
}
function VirtualEvents({
  events,
  mode,
}: {
  events: RunEvent[];
  mode: "output" | "history";
}) {
  const rows = useMemo(
    () =>
      events.flatMap((event) => {
        const text =
          mode === "output"
            ? outputText(event)
            : JSON.stringify(event.payload, null, 2);
        return text === null ? [] : [{ event, text }];
      }),
    [events, mode],
  );
  const [scrollTop, setScrollTop] = useState(0);
  const [expanded, setExpanded] = useState<{
    event: RunEvent;
    text: string;
  } | null>(null);
  const start = Math.max(
    0,
    Math.floor(scrollTop / OUTPUT_ROW_HEIGHT) - VIRTUAL_ROW_OVERSCAN,
  );
  const visibleCount =
    Math.ceil(OUTPUT_VIEW_HEIGHT / OUTPUT_ROW_HEIGHT) +
    VIRTUAL_ROW_OVERSCAN * 2;
  const visible = rows.slice(start, start + visibleCount);

  function updateScroll(event: UIEvent<HTMLDivElement>) {
    setScrollTop(event.currentTarget.scrollTop);
  }

  return (
    <>
      <Box
        className={mode === "output" ? "output-viewport" : "event-list"}
        onScroll={updateScroll}
      >
        <Box
          sx={{
            position: "relative",
            height: Math.max(rows.length * OUTPUT_ROW_HEIGHT, 1),
          }}
        >
          {visible.map(({ event, text }, offset) => (
            <Box
              className={mode === "output" ? "output-row" : "event-row"}
              key={event.id}
              style={{
                top: (start + offset) * OUTPUT_ROW_HEIGHT,
                height: OUTPUT_ROW_HEIGHT,
              }}
            >
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <Chip size="small" className="event-type" label={event.type} />
                <Typography
                  variant="caption"
                  color="text.secondary"
                  className="event-meta"
                >
                  #{event.id} · {new Date(event.ts).toLocaleTimeString()}
                </Typography>
                <Button
                  size="small"
                  color="inherit"
                  onClick={() => setExpanded({ event, text })}
                >
                  View full text
                </Button>
              </Stack>
              <Typography
                component="pre"
                variant="body2"
                className="output-text"
              >
                {text}
              </Typography>
            </Box>
          ))}
        </Box>
        {rows.length === 0 && (
          <Typography color="text.secondary" sx={{ p: 2 }}>
            {mode === "output"
              ? "No provider or command output yet."
              : "No events yet."}
          </Typography>
        )}
      </Box>
      <Dialog
        open={expanded !== null}
        onClose={() => setExpanded(null)}
        fullWidth
        maxWidth="lg"
      >
        <DialogTitle>
          {expanded?.event.type} #{expanded?.event.id}
        </DialogTitle>
        <DialogContent>
          <Typography
            component="pre"
            variant="body2"
            className="full-output-text"
          >
            {expanded?.text}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setExpanded(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
export {
  EVENT_TYPES,
  TERMINAL_RUNS,
  PENDING_RECOVERY,
  PAUSABLE_RUNS,
  OUTPUT_ROW_HEIGHT,
  OUTPUT_VIEW_HEIGHT,
  VIRTUAL_ROW_OVERSCAN,
  type RunWorkspaceProps,
  type DetailCollection,
  type PageMode,
  type RunDetailPage,
  type ArtifactPage,
  mergeEvents,
  mergeRecords,
  runStatusLabel,
  applyStateEvent,
  outputText,
  VirtualEvents,
};
