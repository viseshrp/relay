import {
  Alert,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  FormControlLabel,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import { type UIEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, errorMessage } from "../api";
import type {
  ArtifactRecord,
  AgentsResponse,
  WorkflowDocumentResponse,
  RunDetail,
  RunEvent,
  RunInteraction,
  RunNode,
  RunSummary,
  ProjectRecord,
  PreviousRunInputs,
  RetryConfiguration,
  RetryOptions,
} from "../types";
import { repairOwnership, visibleRunStages } from "../graph";
import { projectPath, stageLabel, statusLabel } from "../navigation";
import { parseWorkflow, type WorkflowValue } from "../workflow";
import { launchView, parseActions } from "../actions-workflow";
import { FlowCanvas } from "./FlowCanvas";
import { ReviewEvidence } from "./RunReview";
import { WaitingRequests } from "./WaitingRequests";
import { attentionChanged } from "../attention";
import { RunProblemNotice } from "./RunProblemNotice";
import { RetrySettings } from "./RetrySettings";
import { JobList } from "./JobList";
import { usePendingChoices, type SettingsChoices } from "./usePendingChoices";
import { JobWorkspace } from "./JobWorkspace";
import { RunActions } from "./RunActions";
import { LaunchPanel } from "./LaunchPanel";
import { ActivityFeed } from "./ActivityFeed";
import { RunArtifacts } from "./RunArtifacts";
import { RunWorkflowFile } from "./RunWorkflowFile";
import { RunHistory } from "./RunHistory";
import { RepairRoleDetails } from "./RepairRoleDetails";
import { ActionIcon, StatusIcon } from "./ActionIcon";
import { runSummaryGraph } from "../run-graph";
import { useClock } from "../useClock";
import { jobDuration } from "../job";
import { ActionsRunProducts } from "./ActionsRunProducts";

const EVENT_TYPES = [
  "actions.summary", "actions.error", "actions.warning", "actions.notice", "actions.debug", "actions.group", "actions.endgroup", "environment.approved", "step.recovery_resumed",
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
const PAUSABLE_RUNS = new Set(["pending", "running", "paused_wait", "failed", "interrupted"]);
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
  if (incoming[0].id > current[current.length - 1].id) return current.concat(incoming);
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

function mergeRecords<T extends { id: string }>(current: T[], incoming: T[]): T[] {
  const records = new Map(current.map((record) => [record.id, record]));
  for (const record of incoming) records.set(record.id, record);
  return Array.from(records.values());
}

function runStatusLabel(run: RunSummary): string {
  // Owner requests take priority over a dispatch pause; finished runs keep their result.
  return run.waiting_count ? "Waiting for you" : run.dispatch_paused && PAUSABLE_RUNS.has(run.status)
    ? "New jobs paused" : statusLabel(run.status);
}

function applyStateEvent(current: RunDetail | null, event: RunEvent): RunDetail | null {
  if (current === null) return null;
  const status = event.payload.status;
  if (event.type === "run.dispatch_changed" && typeof event.payload.paused === "boolean") {
    return { ...current, dispatch_paused: event.payload.paused };
  }
  if (event.type.startsWith("run.") && typeof status === "string") {
    const failed = ["failed", "canceling"].includes(status);
    return {
      ...current, status,
      problem: failed ? current.problem : null,
      failure_summary: failed
        ? typeof event.payload.failure_summary === "string" ? event.payload.failure_summary : current.failure_summary
        : null,
      failure_code: failed
        ? typeof event.payload.failure_code === "string" ? event.payload.failure_code : current.failure_code
        : null,
    };
  }
  if (event.type.startsWith("node.")) {
    const scopePath = event.payload.scope_path;
    if (typeof scopePath === "string" && typeof status === "string") {
      return {
        ...current,
        nodes: current.nodes.map((node) => (
          node.scope_path === scopePath ? { ...node, status } : node
        )),
      };
    }
  }
  if (event.type === "run.merged" && typeof event.payload.merged_commit === "string") {
    return { ...current, merged_commit: event.payload.merged_commit };
  }
  if (event.type === "run.cleanup_succeeded" || event.type === "run.cleanup_failed") {
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

function VirtualEvents({ events, mode }: { events: RunEvent[]; mode: "output" | "history" }) {
  const rows = useMemo(
    () => events.flatMap((event) => {
      const text = mode === "output" ? outputText(event) : JSON.stringify(event.payload, null, 2);
      return text === null ? [] : [{ event, text }];
    }),
    [events, mode],
  );
  const [scrollTop, setScrollTop] = useState(0);
  const [expanded, setExpanded] = useState<{ event: RunEvent; text: string } | null>(null);
  const start = Math.max(0, Math.floor(scrollTop / OUTPUT_ROW_HEIGHT) - VIRTUAL_ROW_OVERSCAN);
  const visibleCount = Math.ceil(OUTPUT_VIEW_HEIGHT / OUTPUT_ROW_HEIGHT) + VIRTUAL_ROW_OVERSCAN * 2;
  const visible = rows.slice(start, start + visibleCount);

  function updateScroll(event: UIEvent<HTMLDivElement>) {
    setScrollTop(event.currentTarget.scrollTop);
  }

  return (
    <>
      <Box className={mode === "output" ? "output-viewport" : "event-list"} onScroll={updateScroll}>
        <Box sx={{ position: "relative", height: Math.max(rows.length * OUTPUT_ROW_HEIGHT, 1) }}>
          {visible.map(({ event, text }, offset) => (
            <Box
              className={mode === "output" ? "output-row" : "event-row"}
              key={event.id}
              style={{ top: (start + offset) * OUTPUT_ROW_HEIGHT, height: OUTPUT_ROW_HEIGHT }}
            >
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <Chip size="small" className="event-type" label={event.type} />
                <Typography variant="caption" color="text.secondary" className="event-meta">
                  #{event.id} · {new Date(event.ts).toLocaleTimeString()}
                </Typography>
                <Button size="small" color="inherit" onClick={() => setExpanded({ event, text })}>
                  View full text
                </Button>
              </Stack>
              <Typography component="pre" variant="body2" className="output-text">
                {text}
              </Typography>
            </Box>
          ))}
        </Box>
        {rows.length === 0 && (
          <Typography color="text.secondary" sx={{ p: 2 }}>
            {mode === "output" ? "No provider or command output yet." : "No events yet."}
          </Typography>
        )}
      </Box>
      <Dialog open={expanded !== null} onClose={() => setExpanded(null)} fullWidth maxWidth="lg">
        <DialogTitle>{expanded?.event.type} #{expanded?.event.id}</DialogTitle>
        <DialogContent>
          <Typography component="pre" variant="body2" className="full-output-text">
            {expanded?.text}
          </Typography>
        </DialogContent>
        <DialogActions><Button onClick={() => setExpanded(null)}>Close</Button></DialogActions>
      </Dialog>
    </>
  );
}


export function RunWorkspace({ selectedWorkflow, onSelectWorkflow, selectedRun, onSelectRun, onRunWorkflow, onEditWorkflow, project, selectedInteraction, selectedJob, onSelectJob, waitingRuns, onRunSucceeded }: RunWorkspaceProps) {
  const [localFilters, setLocalFilters] = useState({ status: "", branch: "", query: "" });
  const filters = useMemo(() => ({ ...localFilters, workflow: selectedWorkflow ?? "" }), [localFilters, selectedWorkflow]);
  const [graphJobs, setGraphJobs] = useState<string[] | null>(null);
  const [workflowFileOpen, setWorkflowFileOpen] = useState(false);
  const [showArtifacts, setShowArtifacts] = useState(false);
  useEffect(() => {
    if (showArtifacts && !selectedJob) {
      document.getElementById("run-artifacts")?.scrollIntoView({ block: "start" });
      setShowArtifacts(false);
    }
  }, [showArtifacts, selectedJob]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runCursor, setRunCursor] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  useEffect(() => { if (detail?.status === "succeeded") onRunSucceeded?.(); }, [detail?.status, onRunSucceeded]);
  const [nodeCursor, setNodeCursor] = useState<number | null>(null);
  const [interactionCursor, setInteractionCursor] = useState<number | null>(null);
  const [linkedRequest, setLinkedRequest] = useState<RunInteraction | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [eventCursor, setEventCursor] = useState<number | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [artifactCursor, setArtifactCursor] = useState<number | null>(null);
  const [streamState, setStreamState] = useState("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [relaunchBusy, setRelaunchBusy] = useState(false);
  const [runAgain, setRunAgain] = useState<{ source: PreviousRunInputs; workflow: WorkflowValue; models: string[]; open: boolean } | null>(null);
  const relaunchButton = useRef<HTMLButtonElement>(null);
  const relaunchRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    setRunAgain(null);
    setRelaunchBusy(false);
    return () => { relaunchRequest.current?.abort(); relaunchRequest.current = null; };
  }, [selectedRun, project.id]);
  const [stopOpen, setStopOpen] = useState(false);
  const [retrySettings, setRetrySettings] = useState<RetryConfiguration | null>(null);
  const [pendingSettings, setPendingSettings] = useState<{ runId: string; settings: RetryConfiguration; choices: SettingsChoices } | null>(null);
  const [pauseBusy, setPauseBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [streamRun, setStreamRun] = useState<string | null>(null);
  const [streamEpoch, setStreamEpoch] = useState(0);
  const currentRun = useRef<string | null>(null);
  const stateAfter = useRef(0);
  const eventAfter = useRef(0);
  const previousRunStatus = useRef<string | null>(null);
  const stepProgress = useRef<HTMLDivElement>(null);
  const jobContent = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selectedJob) jobContent.current?.scrollIntoView({ block: "start" });
  }, [selectedJob]);

  const historyRequest = useRef<AbortController | null>(null);
  useEffect(() => () => historyRequest.current?.abort(), []);
  const loadHistory = useCallback(async (cursor?: string) => {
    const query = new URLSearchParams({ limit: "50" });
    query.set("project", project.id);
    for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);
    if (cursor) query.set("since", cursor);
    historyRequest.current?.abort();
    const controller = new AbortController();
    historyRequest.current = controller;
    try {
      const response = await api<{ runs: RunSummary[]; next: string | null }>(`/api/runs?${query.toString()}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setRuns((current) => (cursor ? [...current, ...response.runs] : response.runs));
      setRunCursor(response.next);
    } catch (caught) { if (!controller.signal.aborted) throw caught; }
  }, [project.id, filters]);

  const loadDetailCollection = useCallback(async (
    collection: DetailCollection,
    since: number,
    mode: PageMode,
  ): Promise<RunDetail> => {
    if (selectedRun === null) throw new Error("Select a run before loading its detail.");
    const query = new URLSearchParams({ collection, since: String(since), limit: "200" });
    if (collection === "interactions") query.set("pending", "true");
    const response = await api<RunDetailPage>(
      `/api/runs/${encodeURIComponent(selectedRun)}?${query.toString()}`,
    );
    if (currentRun.current !== selectedRun) return response.run;
    setDetail((current) => {
      const sameRun = current?.id === response.run.id;
      const currentNodes = sameRun ? current.nodes : [];
      const currentInteractions = sameRun ? current.interactions : [];
      return {
        ...response.run,
        nodes: collection === "nodes"
          ? (mode === "replace"
            ? response.run.nodes
            : mergeRecords(currentNodes, response.run.nodes))
          : currentNodes,
        interactions: collection === "interactions"
          ? (mode !== "append"
            ? response.run.interactions
            : mergeRecords(currentInteractions, response.run.interactions))
          : currentInteractions,
      };
    });
    if (collection === "nodes") setNodeCursor(response.next);
    else setInteractionCursor(response.next);
    return response.run;
  }, [selectedRun]);

  const loadArtifacts = useCallback(async (
    since: number,
    mode: PageMode,
  ): Promise<void> => {
    if (selectedRun === null) return;
    const query = new URLSearchParams({ since: String(since), limit: "200" });
    const response = await api<ArtifactPage>(
      `/api/runs/${encodeURIComponent(selectedRun)}/artifacts?${query.toString()}`,
    );
    if (currentRun.current !== selectedRun) return;
    setArtifacts((current) => (
      mode === "replace" ? response.artifacts : mergeRecords(current, response.artifacts)
    ));
    setArtifactCursor(response.next);
  }, [selectedRun]);

  const loadLinkedRequest = useCallback(async () => {
    if (!selectedRun || !selectedInteraction) { setLinkedRequest(null); return; }
    const response = await api<RunDetailPage>(`/api/runs/${selectedRun}?collection=interactions&interaction=${encodeURIComponent(selectedInteraction)}&limit=1`);
    if (currentRun.current === selectedRun) setLinkedRequest(response.run.interactions[0] ?? null);
  }, [selectedRun, selectedInteraction]);

  const refreshDetail = useCallback(async (reset = false): Promise<RunDetail | null> => {
    if (selectedRun === null) return null;
    const mode: PageMode = reset ? "replace" : "refresh";
    const [run, interactions] = await Promise.all([
      loadDetailCollection("nodes", 0, mode),
      loadDetailCollection("interactions", 0, mode),
      loadArtifacts(0, mode),
      loadLinkedRequest(),
    ]);
    if (reset && currentRun.current === selectedRun) {
      stateAfter.current = Math.min(run.event_cursor ?? 0, interactions.event_cursor ?? 0);
    }
    return run;
  }, [loadArtifacts, loadDetailCollection, loadLinkedRequest, selectedRun]);

  const applyLiveUpdates = useCallback((batch: RunEvent[]) => {
    // Historical output stays visible; progress starts at the loaded state cursor.
    const live = batch.filter((item) => item.id > stateAfter.current);
    setDetail((current) => live.reduce(applyStateEvent, current));
    const interactionChanged = live.some((item) => item.type === "attempt.ended" || item.type === "attempt.started"
      || item.type.endsWith(".requested") || item.type.endsWith(".answered"));
    if (interactionChanged || live.some((item) => item.type === "node.created" || item.type === "run.dispatch_changed" || item.type === "run.repairs_changed" || item.type === "node.settings_changed" || item.type.startsWith("run.retry_") || item.type.startsWith("run.recovery_"))) {
      void loadDetailCollection("nodes", 0, "refresh").catch((caught: unknown) =>
        setError(errorMessage(caught)),
      );
    }
    if (interactionChanged) {
      void loadDetailCollection("interactions", 0, "refresh").catch((caught: unknown) =>
        setError(errorMessage(caught)),
      );
      void loadLinkedRequest().catch((caught: unknown) => setError(errorMessage(caught)));
    }
    if (batch.some((item) => item.type === "artifact.preserved")) {
      void loadArtifacts(0, "refresh").catch((caught: unknown) =>
        setError(errorMessage(caught)),
      );
    }
  }, [loadArtifacts, loadDetailCollection, loadLinkedRequest]);

  const loadEvents = useCallback(async (since = 0) => {
    if (selectedRun === null) return [];
    const response = await api<{ events: RunEvent[]; next: number | null }>(
      `/api/runs/${encodeURIComponent(selectedRun)}/events?since=${since}&limit=100`,
    );
    if (currentRun.current !== selectedRun) return [];
    eventAfter.current = Math.max(eventAfter.current, response.events.at(-1)?.id ?? 0);
    setEvents((current) => (since === 0 ? response.events : mergeEvents(current, response.events)));
    setEventCursor(response.next);
    return response.events;
  }, [selectedRun]);

  useEffect(() => {
    void loadHistory().catch((caught: unknown) => setError(errorMessage(caught)));
  }, [loadHistory]);

  useEffect(() => {
    let disposed = false;
    currentRun.current = selectedRun;
    eventAfter.current = 0;
    stateAfter.current = 0;
    previousRunStatus.current = null;
    setStreamRun(null);
    setDetail(null);
    setSelectedStage(null);
    setRetrySettings(null);
    setPendingSettings(null);
    setError(null);
    setNodeCursor(null);
    setInteractionCursor(null);
    setLinkedRequest(null);
    setEvents([]);
    setArtifacts([]);
    setArtifactCursor(null);
    setEventCursor(null);
    if (selectedRun === null) return;
    void Promise.all([refreshDetail(true), loadEvents()])
      .then(([, history]) => {
        if (disposed) return;
        // A step may finish between the state read and the history response.
        // Apply those events before the stream starts after their final ID.
        applyLiveUpdates(history);
        setStreamRun(selectedRun);
      })
      .catch((caught: unknown) => { if (!disposed) setError(errorMessage(caught)); });
    return () => { disposed = true; };
  }, [applyLiveUpdates, loadEvents, refreshDetail, selectedRun]);

  useEffect(() => {
    if (detail === null || detail.id !== selectedRun) return;
    const previous = previousRunStatus.current;
    previousRunStatus.current = detail.status;
    if (
      previous !== null && TERMINAL_RUNS.has(previous)
      && (!TERMINAL_RUNS.has(detail.status)
        || detail.status === "failed" && (detail.problem?.retry?.state === "scheduled"
          || PENDING_RECOVERY.has(detail.recovery?.current?.state ?? "")))
      && streamState === "complete"
    ) setStreamEpoch((value) => value + 1);
  }, [detail, selectedRun, streamState]);

  useEffect(() => {
    if (selectedRun === null || streamRun !== selectedRun) return;
    const source = new EventSource(
      `/api/runs/${encodeURIComponent(selectedRun)}/stream?since=${eventAfter.current}`,
    );
    let incoming: RunEvent[] = [];
    let frame: number | null = null;
    let disposed = false;
    let completionCheck: Promise<void> | null = null;
    const checkCompletion = () => {
      if (completionCheck !== null) return;
      // A replayed terminal event may precede a retry. Confirm current state
      // before closing, including when the server ends a terminal stream.
      completionCheck = loadDetailCollection("nodes", 0, "refresh")
        .then((run) => {
          if (disposed || currentRun.current !== selectedRun) return;
          if (TERMINAL_RUNS.has(run.status) && run.problem?.retry?.state !== "scheduled"
            && !PENDING_RECOVERY.has(run.recovery?.current?.state ?? "")) {
            source.close();
            setStreamState("complete");
          }
        })
        .catch((caught: unknown) => { if (!disposed) setError(errorMessage(caught)); })
        .finally(() => { completionCheck = null; });
    };
    const flush = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      const batch = incoming;
      incoming = [];
      if (batch.length === 0) return;
      setEvents((current) => mergeEvents(current, batch));
      applyLiveUpdates(batch);
      if (batch.some((item) => item.id > stateAfter.current && (
        item.type.startsWith("run.retry_") || item.type.startsWith("run.recovery_") || item.type.startsWith("run.")
          && typeof item.payload.status === "string" && TERMINAL_RUNS.has(item.payload.status)
      ))) checkCompletion();
    };
    setStreamState("connecting");
    source.onopen = () => setStreamState("live");
    const receive = (event: Event) => {
      if (!(event instanceof MessageEvent)) {
        flush();
        setStreamState("reconnecting");
        checkCompletion();
        return;
      }
      try {
        const item = JSON.parse(event.data) as RunEvent;
        if (item.version !== 1) return;
        eventAfter.current = Math.max(eventAfter.current, item.id);
        if (incoming.at(-1)?.id === item.id) incoming[incoming.length - 1] = item;
        else incoming.push(item);
        // Publish one ordered batch per paint instead of copying/sorting the
        // growing history for each replayed event.
        if (frame === null) frame = requestAnimationFrame(flush);
        const status = item.payload.status;
        if (item.id > stateAfter.current && item.type.startsWith("run.") && typeof status === "string" && TERMINAL_RUNS.has(status)) {
          flush();
        }
      } catch {
        setError("Relay received an invalid event frame.");
      }
    };
    for (const type of EVENT_TYPES) source.addEventListener(type, receive);
    source.addEventListener("error", receive);
    return () => {
      disposed = true;
      if (frame !== null) cancelAnimationFrame(frame);
      source.close();
    };
  }, [applyLiveUpdates, loadDetailCollection, selectedRun, streamEpoch, streamRun]);

  async function configureRecovery(enabled: boolean) {
    if (selectedRun === null) return;
    setRecoveryBusy(true);
    try {
      await api(`/api/runs/${encodeURIComponent(selectedRun)}/recovery`, {
        method: "POST", body: JSON.stringify({ enabled, idempotency_key: crypto.randomUUID() }),
      });
      await refreshDetail();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setRecoveryBusy(false);
    }
  }

  async function configurePause(paused: boolean) {
    if (selectedRun === null) return;
    setPauseBusy(true);
    try {
      await api(`/api/runs/${encodeURIComponent(selectedRun)}/pause`, {
        method: "POST", body: JSON.stringify({ paused, idempotency_key: crypto.randomUUID() }),
      });
      await Promise.all([refreshDetail(), loadHistory()]);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPauseBusy(false);
    }
  }

  async function savePendingSettings(scopePath: string, options: RetryOptions = {}) {
    if (selectedRun === null) return;
    await api(`/api/runs/${encodeURIComponent(selectedRun)}/step-settings`, {
      method: "POST",
      body: JSON.stringify({ scope_path: scopePath, idempotency_key: crypto.randomUUID(), ...options }),
    });
    await refreshDetail();
  }

  async function cancelRun() {
    if (selectedRun === null) return;
    try {
      await api<{ result: string }>(`/api/runs/${encodeURIComponent(selectedRun)}/cancel`, {
        method: "POST",
        body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
      });
      await refreshDetail();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function rerunAll(): Promise<void> {
    if (selectedRun === null) return;
    const controller = new AbortController();
    relaunchRequest.current?.abort();
    relaunchRequest.current = controller;
    setRelaunchBusy(true);
    try {
      const source = await api<PreviousRunInputs>(`/api/runs/${encodeURIComponent(selectedRun)}/launch-inputs`, { signal: controller.signal });
      const [document, agents] = await Promise.all([
        api<WorkflowDocumentResponse>(projectPath(`/api/workflows/${source.workflow_key.split("/").map(encodeURIComponent).join("/")}`, source.project_id), { signal: controller.signal }),
        api<AgentsResponse>("/api/agents", { signal: controller.signal }).catch(() => null),
      ]);
      if (controller.signal.aborted) return;
      const parsed = parseWorkflow(document.yaml);
      if (parsed.value === null) throw new Error(`Fix the saved workflow's YAML before running it again. ${parsed.errors.join(" ")}`);
      const actions = parseActions(document.yaml);
      if (!actions.value) throw new Error(`Fix the saved workflow before starting a new run. ${actions.errors.join(" ")}`);
      const environments = await api<{ environments: Array<{ name: string }> }>(projectPath("/api/workflow-environments", source.project_id), { signal: controller.signal });
      if (controller.signal.aborted) return;
      setRunAgain({ source, workflow: launchView(actions.value, environments.environments.map(item => item.name))!, open: true,
        models: Array.from(new Set(agents?.agents.flatMap((agent) => agent.models.map((model) => model.value)) ?? [])).sort() });
    } catch (caught) { if (!controller.signal.aborted) setError(errorMessage(caught)); }
    finally {
      if (relaunchRequest.current === controller) {
        relaunchRequest.current = null;
        setRelaunchBusy(false);
      }
    }
  }

  async function rerunNode(scopePath: string, options: RetryOptions = {}) {
    if (selectedRun === null) return;
    try {
      await api<{ result: string }>(`/api/runs/${encodeURIComponent(selectedRun)}/rerun-node`, {
        method: "POST",
        body: JSON.stringify({ scope_path: scopePath, idempotency_key: crypto.randomUUID(), ...options }),
      });
      previousRunStatus.current = null;
      setStreamEpoch((value) => value + 1);
      await refreshDetail();
    } catch (caught) {
      setError(errorMessage(caught));
      throw caught;
    }
  }

  async function refreshRuns() {
    // Keep retry dialogs from capturing settings before another client's
    // latest attempt and configuration finish loading.
    setRefreshing(true);
    try {
      await Promise.all([loadHistory(), refreshDetail(true)]);
      const history = await loadEvents(eventAfter.current);
      applyLiveUpdates(history);
      // Another owner client may have retried after this terminal stream closed.
      // Reopen from the retained cursor so its new attempt updates remain visible.
      if (selectedRun !== null) {
        previousRunStatus.current = null;
        setStreamEpoch((value) => value + 1);
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setRefreshing(false);
    }
  }

  function showStep(scopePath: string): void {
    setSelectedStage(scopePath);
    onSelectJob(scopePath);
    if (scopePath === selectedJob) jobContent.current?.scrollIntoView({ block: "start" });
  }

  async function loadMoreNodes() {
    if (nodeCursor === null) return;
    try {
      await loadDetailCollection("nodes", nodeCursor, "append");
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function loadMoreInteractions() {
    if (interactionCursor === null) return;
    try {
      await loadDetailCollection("interactions", interactionCursor, "append");
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function loadMoreArtifacts() {
    if (artifactCursor === null) return;
    try {
      await loadArtifacts(artifactCursor, "append");
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  const now = useClock(Boolean(detail && !TERMINAL_RUNS.has(detail.status)));
  const graph = useMemo(() => runSummaryGraph(detail?.nodes ?? [], now), [detail?.nodes, now]);
  const visibleStages = useMemo(() => visibleRunStages(detail?.nodes ?? []), [detail]);
  const repairOwners = useMemo(() => repairOwnership(detail?.nodes ?? []), [detail]);
  const repairGroups = detail?.nodes.filter((node) => node.repair_for && node.repair_settings) ?? [];
  const repairChildren = useMemo(() => {
    const groups = new Map<string, RunNode[]>();
    for (const node of detail?.nodes ?? []) {
      const owner = repairOwners.get(node.scope_path);
      if (!owner || node.repair_settings) continue;
      const group = groups.get(owner) ?? [];
      group.push(node);
      groups.set(owner, group);
    }
    return groups;
  }, [detail, repairOwners]);
  const pendingInteractions = Array.from(new Map([...(detail?.interactions ?? []), ...(linkedRequest ? [linkedRequest] : [])].filter((item) => item.status === "pending" && item.respondable !== false).map((item) => [item.id, item])).values());
  const interactionRevision = pendingInteractions.map((request) => request.id).join(",");
  useEffect(() => attentionChanged(), [interactionRevision, detail?.status]);
  const currentStages = visibleStages.filter((node) => ["waiting", "running", "failed", "repairing", "repair_stopped"].includes(node.status));
  const focusStage = selectedStage ?? pendingInteractions[0]?.scope_path ?? currentStages[0]?.scope_path;
  const canPause = detail !== null && PAUSABLE_RUNS.has(detail.status);
  const dispatchPaused = canPause && detail.dispatch_paused;
  const pendingChoices = usePendingChoices(detail?.id ?? null, detail?.project_id ?? project.id, dispatchPaused,
    detail?.nodes.flatMap((node) => node.pending_settings ? [node.pending_settings] : []) ?? []);
  useEffect(() => { setPendingSettings(null); }, [selectedRun, dispatchPaused]);
  const recovery = detail?.recovery?.current;
  const recoveryPending = PENDING_RECOVERY.has(recovery?.state ?? "");
  const recovering = recovery?.state === "resumed" && detail?.status === "running"
    && detail.nodes.some((node) => node.scope_path === recovery.scope_path
      && ["ready", "dispatched", "running", "waiting"].includes(node.status));
  const summaryMessage = pendingInteractions.length ? "Choose Respond above to continue this job."
    : recoveryPending ? "Preparing retry. Relay is preserving reports and waiting for active work to stop."
      : recovering ? `Retrying step · ${recovery?.retry_number} of ${detail?.recovery.max_retries}.`
        : detail?.status === "failed" && detail.problem?.retry?.state === "scheduled" ? "Relay is waiting for the provider's reset. It will retry automatically."
          : detail?.status === "failed" ? detail.nodes.some((node) => node.status === "failed") ? "Select a failed job to inspect its logs and retry settings." : "The run could not merge or remove its working copy. See the error below."
            : detail?.status === "succeeded" ? "Work is complete. Review the saved documents and code changes below."
              : detail?.status === "canceled" ? "Work stopped. Finished jobs and their changes remain available for review."
                : detail?.status === "canceling" ? "Relay is stopping active tools and preserving their results."
                  : detail?.status === "interrupted" ? "This run was interrupted. Saved logs remain available."
                    : "Updates are live. Select a job to follow its output.";

  return (
    <Stack spacing={2}>
      {detail && <Box component="header" role="region" aria-label="Workflow run history" className="run-header">
        <Button size="small" startIcon={<ActionIcon name="back" />} onClick={() => onSelectRun(null)}>{detail.title || stageLabel(detail.workflow_key.replace(/\.(yaml|yml)$/, ""))}</Button>
        <Stack direction="row" spacing={2} className="run-heading-row">
          <Typography component="h1" variant="h5" sx={{ flex: 1 }}><StatusIcon status={detail.status} size={26} /> {detail.title || stageLabel(detail.workflow_key.replace(/\.(yaml|yml)$/, ""))} <Box component="span" color="text.secondary">#{detail.number}</Box></Typography>
          <Button variant="outlined" onClick={() => onRunWorkflow(detail.workflow_key)}>Run workflow</Button>
          <RunActions run={detail} busy={pauseBusy || relaunchBusy || refreshing}
            onPause={() => void configurePause(!detail.dispatch_paused)} onCancel={() => setStopOpen(true)}
            onRerunAll={() => void rerunAll()} onRerunFailed={() => setGraphJobs(detail.nodes.filter((node) => node.status === "failed").map((node) => node.scope_path))} rerunAllRef={relaunchButton} />
          <Button size="small" aria-label="Refresh" disabled={refreshing} onClick={() => void refreshRuns()}><ActionIcon name="refresh" /></Button>
        </Stack>
      </Box>}
      {dispatchPaused && <Alert severity="info">Paused. Running jobs will finish; nothing new will start until you resume.</Alert>}
      {pendingSettings && detail?.id === pendingSettings.runId && dispatchPaused && <RetrySettings
        key={`${pendingSettings.runId}:${pendingSettings.settings.scope_path}:pending`}
        purpose="pending" problem={pendingSettings.settings} initialChoices={pendingSettings.choices} projectId={detail.project_id}
        onClose={() => setPendingSettings(null)} onRetry={savePendingSettings} />}
      {runAgain && <LaunchPanel open={runAgain.open} workflowKey={runAgain.source.workflow_key} workflow={runAgain.workflow}
        project={project} requestProject={runAgain.source.project_id} modelOptions={runAgain.models} previousRun={runAgain.source}
        blockedReason={Object.keys(runAgain.workflow.nodes).length === 0 ? "Add a job to this empty workflow before running it." : null}
        saveError={null} onClose={() => setRunAgain((current) => current ? { ...current, open: false } : null)}
        onExited={() => { setRunAgain(null); relaunchButton.current?.focus(); }}
        onRunLaunched={(id) => { setRunAgain(null); onSelectRun(id); }} />}
      {retrySettings && detail && <RetrySettings key={`${detail.id}:${retrySettings.scope_path}`}
        problem={retrySettings} projectId={detail.project_id} onClose={() => setRetrySettings(null)} onRetry={rerunNode} />}
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      {workflowFileOpen && detail && <RunWorkflowFile key={detail.id} runId={detail.id}
        onClose={() => setWorkflowFileOpen(false)} onEdit={(key) => { setWorkflowFileOpen(false); onEditWorkflow(key); }} />}
      {!selectedRun ? <RunHistory project={project} runs={runs} waitingRuns={waitingRuns} more={Boolean(runCursor)} refreshing={refreshing}
        onMore={() => void loadHistory(runCursor ?? undefined)} onSelect={onSelectRun} onRefresh={() => void refreshRuns()}
        onRunWorkflow={onRunWorkflow} onEditWorkflow={onEditWorkflow} filters={filters} onFilters={(next) => { setLocalFilters({ status: next.status, branch: next.branch, query: next.query }); if (next.workflow !== filters.workflow) onSelectWorkflow(next.workflow || null); }} /> : <Box className="run-layout">
        <Paper variant="outlined" className="history-panel actions-sidebar">
          {detail && <JobList nodes={detail.nodes} selected={selectedJob} repairOwners={repairOwners}
            hasMore={nodeCursor !== null} onSelect={(scope) => scope ? showStep(scope) : onSelectJob(null)}
            onMore={() => void loadMoreNodes()} pendingChoices={dispatchPaused ? pendingChoices.choices : undefined}
            onCheck={pendingChoices.retry} onEdit={(settings, choices) => setPendingSettings({ runId: detail.id, settings, choices })} />}
          <Divider sx={{ my: 2 }} />
          <Typography variant="caption" color="text.secondary" sx={{ px: 2 }}>Run details</Typography>
          <ListItemButton onClick={() => { onSelectJob(null); setShowArtifacts(true); }}><ActionIcon name="artifact" /><ListItemText primary="Artifacts" /></ListItemButton>
          {detail && <ListItemButton onClick={() => setWorkflowFileOpen(true)}><ActionIcon name="workflow" /><ListItemText primary="Workflow file" /></ListItemButton>}
          <ListItemButton onClick={() => onSelectRun(null)}><ActionIcon name="clock" /><ListItemText primary="Run history" /></ListItemButton>
        </Paper>

        <Stack ref={jobContent} spacing={2} sx={{ minWidth: 0, scrollMarginTop: 80 }}>
          {detail && detail.nodes.some(node => node.node_type === "actions_job") && <ActionsRunProducts runId={detail.id} projectId={detail.project_id} events={events} nodes={detail.nodes} />}
          {detail && <WaitingRequests key={detail.id} requests={pendingInteractions} runId={detail.id} artifacts={artifacts}
            selected={selectedInteraction} hasMore={interactionCursor !== null} onMore={() => void loadMoreInteractions()}
            onAnswered={async () => { await refreshDetail(); attentionChanged(); }} />}
          {detail === null ? (
            <Paper variant="outlined" className="empty-panel">
              <Typography color="text.secondary">Select a run to inspect it.</Typography>
            </Paper>
          ) : selectedJob ? (
            <JobWorkspace key={`${detail.id}:${selectedJob}`} runId={detail.id} scope={selectedJob}
              liveEvents={events} canRetry={detail.status === "failed"} refreshing={refreshing}
              onRetry={rerunNode} onRetrySettings={setRetrySettings} />
          ) : (
            <>
              <Paper variant="outlined" className="section-card">
                <Box className="run-summary-metadata">
                  <Box><Typography variant="body2" color="text.secondary">Started manually {detail.started_at ? new Date(detail.started_at).toLocaleString() : "just now"}</Typography><Typography variant="subtitle1">{detail.launcher} <ActionIcon name="commit" size={16} /> <code>{detail.source_commit.slice(0, 7)}</code> {detail.source_branch && <Box component="span" className="branch-label">{detail.source_branch}</Box>}</Typography></Box>
                  <Box><Typography variant="body2" color="text.secondary">Status</Typography><Typography variant="subtitle1">{runStatusLabel(detail)}</Typography></Box>
                  <Box><Typography variant="body2" color="text.secondary">Total duration</Typography><Typography variant="subtitle1">{jobDuration(detail.started_at, detail.ended_at, now)}</Typography></Box>
                  <Box><Typography variant="body2" color="text.secondary">Artifacts</Typography><Button size="small" href="#run-artifacts">{artifacts.length || "None"}</Button></Box>
                </Box>
                {!dispatchPaused && <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>{summaryMessage}</Typography>}
                {detail.status === "completing" && <Alert severity="info" sx={{ mt: 2 }}>Every job finished. Relay is merging into {detail.source_branch} and deleting the run working copies.</Alert>}
                {detail.merged_commit && <Alert severity="success" sx={{ mt: 2 }}>Merged into {detail.source_branch} at <code>{detail.merged_commit.slice(0, 7)}</code>. {detail.worktree_state === "removed" ? "Run working copies deleted." : "The run working copy still needs cleanup."}</Alert>}
                <Button size="small" component="a" href={`?view=runs&project=${project.id}&run=${detail.id}`}>Link to run</Button>
                {detail.status === "interrupted" && (
                  <Alert severity="info" sx={{ mt: 2 }}>
                    Restarting <code>relay up</code> resumes this run from durable state as a fresh attempt.
                  </Alert>
                )}
              </Paper>

              {selectedInteraction && linkedRequest && linkedRequest.status !== "pending" && <Alert severity="info">The linked request has already been {linkedRequest.status}. Any current requests appear above.</Alert>}

              <Paper ref={stepProgress} variant="outlined" className="canvas-panel run-canvas" role="region" aria-label="Step progress" tabIndex={-1}>
                <Box className="graph-heading"><Typography variant="h6">{detail.workflow_key}</Typography><Typography variant="body2" color="text.secondary">Started manually · {visibleStages.length} jobs</Typography></Box>
                <Box className="run-graph-viewport"><FlowCanvas key={detail.id} runMode nodes={graph.nodes} edges={graph.edges} selectedId={repairOwners.get(focusStage ?? "") ?? focusStage} onSelect={(id) => {
                  const members = graph.nodes.find((node) => node.id === id)?.data.members;
                  if (Array.isArray(members) && members.every((value): value is string => typeof value === "string")) setGraphJobs(members);
                  else if (detail.nodes.some((node) => node.scope_path === id)) showStep(id);
                }} /></Box>
              </Paper>
              {(detail.nodes.some((node) => node.status === "failed") || detail.problem || detail.failure_summary) && <Paper variant="outlined" className="section-card" aria-label="Annotations">
                <Typography variant="h6">Annotations</Typography>
                {detail.problem && ["failed", "canceling"].includes(detail.status)
                  ? <RunProblemNotice problem={detail.problem} displayScope={repairOwners.get(detail.problem.scope_path)} onShowStep={showStep} onCancelRetry={() => void cancelRun()} />
                  : detail.failure_summary && <Alert severity="error" sx={{ mt: 2 }}>{detail.failure_summary}</Alert>}
                {detail.nodes.filter((node) => node.status === "failed").map((node) => <Stack key={node.id} direction="row" spacing={2} sx={{ mt: 1, alignItems: "center" }}>
                  <StatusIcon status="failed" /><Typography sx={{ flex: 1 }}>{stageLabel(node.scope_path)}</Typography>
                  <Button onClick={() => showStep(node.scope_path)}>Open job log</Button>
                </Stack>)}
              </Paper>}
              <Accordion><AccordionSummary>Run settings</AccordionSummary><AccordionDetails>                <FormControlLabel sx={{ mt: 2 }}
                  control={<Switch checked={detail.recovery?.enabled === true}
                    disabled={recoveryBusy || ["succeeded", "canceled"].includes(detail.status)}
                    onChange={(event) => void configureRecovery(event.target.checked)} />}
                  label="Automatic recovery" />
                <Typography variant="body2" color="text.secondary">
                  Eligible agent steps can retry up to {detail.recovery?.max_retries ?? 2} times.
                  Retries keep their model, settings, and original instructions. Turning this
                  off cancels queued recovery and keeps the remaining budget unchanged.
                </Typography>
                {recovery && ["blocked", "exhausted"].includes(recovery.state) &&
                  <Alert severity="warning" sx={{ mt: 2 }}>{recovery.message}</Alert>}
                {recovery?.instruction && <Accordion sx={{ mt: 2 }}>
                  <AccordionSummary>Automatic retry instruction</AccordionSummary>
                  <AccordionDetails>
                    <Typography variant="body2">{stageLabel(recovery.scope_path)} · Retry {recovery.retry_number} of {detail.recovery.max_retries} · {recovery.state}</Typography>
                    <Typography component="pre" className="activity-text">{recovery.instruction}</Typography>
                  </AccordionDetails>
                </Accordion>}
</AccordionDetails></Accordion>
              <RunArtifacts artifacts={artifacts} more={artifactCursor !== null} onMore={() => void loadMoreArtifacts()} />
              {repairGroups.length > 0 && <Accordion><AccordionSummary><Typography>Repairs · {repairGroups.length} configured</Typography></AccordionSummary><AccordionDetails><Stack spacing={2}>
                <Typography variant="body2">Relay handles these repairs behind each stage. Reports, attempts, and tool messages remain saved. Settings for this run are captured; edit the workflow to change future runs.</Typography>
                {repairGroups.map((group) => {
                  const settings = group.repair_settings!;
                  const children = repairChildren.get(group.repair_for!) ?? [];
                  const round = Math.max(0, ...children.map((node) => node.loop_index ?? 0));
                  const roleNodes = new Map<string, RunNode>();
                  for (const child of children) {
                    // root.hidden#2.verify is the direct verifier for round 2;
                    // a nested child must not replace its parent's role settings.
                    if (child.parent_scope !== `${group.scope_path}#${child.loop_index}`) continue;
                    const previous = roleNodes.get(child.node_id);
                    if (!previous || (child.loop_index ?? 0) >= (previous.loop_index ?? 0)) roleNodes.set(child.node_id, child);
                  }
                  const held = dispatchPaused && !["succeeded", "skipped", "failed", "canceled"].includes(group.status);
                  return <Paper key={group.id} variant="outlined" className="section-card" role="region" aria-label={`Repairs for ${stageLabel(group.repair_for!)}`}>
                    <Typography variant="h6">{stageLabel(group.repair_for!)} · {held ? "Repairs paused" : statusLabel(group.status)}</Typography>
                    <Typography variant="body2">{round ? `Round ${round} of ${settings.max_rounds}` : `Up to ${settings.max_rounds} rounds`}{settings.legacy ? " · Existing workflow loop" : ` · ${settings.accepted_output} must equal ${JSON.stringify(settings.accepted_value)}`}</Typography>
                    {Object.entries(settings.roles).map(([role, value]) => {
                      const child = roleNodes.get(role);
                      const current = child?.pending_settings ?? child?.retry_settings;
                      return <RepairRoleDetails key={role} role={role} saved={value} current={current} />;
                    })}
                    {settings.fix_instruction && <Typography variant="body2" sx={{ mt: 1 }}>Fixer instructions: {settings.fix_instruction}</Typography>}
                    {settings.verify_instruction && <Typography variant="body2" sx={{ mt: 1 }}>Verifier instructions: {settings.verify_instruction}</Typography>}
                    <Stack spacing={1} sx={{ mt: 1, alignItems: "flex-start" }}>{children.map((node) => <Button key={node.id} onClick={() => showStep(node.scope_path)}>{stageLabel(node.scope_path)} · {statusLabel(node.status)}</Button>)}</Stack>
                  </Paper>;
                })}
                <Button sx={{ alignSelf: "flex-start" }} href={`/?view=workflows&project=${encodeURIComponent(detail.project_id)}&workflow=${encodeURIComponent(detail.workflow_key)}`}>Edit repairs for future runs</Button>
              </Stack></AccordionDetails></Accordion>}

              <Paper variant="outlined" className="section-card">
                <Typography variant="h6" sx={{ mb: 1.5 }}>Activity</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Messages and tool results from this run, in order.</Typography>
                <ActivityFeed key={detail.id} events={events} nodes={detail.nodes} workingFolder={detail.working_folder}
                  live={!TERMINAL_RUNS.has(detail.status)} hasMore={eventCursor !== null}
                  onMore={async () => { if (eventCursor !== null) await loadEvents(eventCursor); }} />
              </Paper>

              {pendingInteractions.length === 0 && <Paper variant="outlined" className="section-card"><ReviewEvidence runId={detail.id} artifacts={artifacts} /></Paper>}

              <Accordion><AccordionSummary>Advanced diagnostics and saved files</AccordionSummary><AccordionDetails><Stack spacing={2}>
              <Box component="details" aria-label="Raw event details"><Box component="summary">Details</Box>
              <Paper variant="outlined" className="section-card">
                <Typography variant="body2" className="mono-wrap">Run {detail.id} · {detail.run_branch} · {detail.status} · SSE {streamState}</Typography>
                <Stack direction="row" sx={{ alignItems: "center", mb: 1 }}>
                  <Typography variant="h6" sx={{ flex: 1 }}>Event history</Typography>
                  {eventCursor !== null && (
                    <Button onClick={() => void loadEvents(eventCursor)}>Load next page</Button>
                  )}
                </Stack>
                <VirtualEvents key={`history-${detail.id}`} events={events} mode="history" />
              </Paper>
              </Box>


              </Stack></AccordionDetails></Accordion>
            </>
          )}

        </Stack>
      </Box>}
      <Dialog open={graphJobs !== null} onClose={() => setGraphJobs(null)} fullWidth><DialogTitle>{graphJobs?.every((scope) => detail?.nodes.find((node) => node.scope_path === scope)?.status === "failed") ? "Choose a failed job" : "Parallel jobs"}</DialogTitle><DialogContent><List>{graphJobs?.map((scope) => <ListItemButton key={scope} onClick={() => { setGraphJobs(null); showStep(scope); }}><StatusIcon status={detail?.nodes.find((node) => node.scope_path === scope)?.status ?? "pending"} /><ListItemText primary={stageLabel(scope)} /></ListItemButton>)}</List></DialogContent><DialogActions><Button onClick={() => setGraphJobs(null)}>Close</Button></DialogActions></Dialog>

      <Dialog open={stopOpen} onClose={() => setStopOpen(false)}>
        <DialogTitle>Cancel this run?</DialogTitle>
        <DialogContent><DialogContentText>Relay stops active tools and skips remaining work. Finished jobs keep their results and committed changes. You can still review the saved evidence.</DialogContentText></DialogContent>
        <DialogActions><Button onClick={() => setStopOpen(false)}>Keep working</Button><Button color="error" onClick={() => { setStopOpen(false); void cancelRun(); }}>Cancel run</Button></DialogActions>
      </Dialog>
    </Stack>
  );
}
