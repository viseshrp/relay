import type { Edge, Node } from "@xyflow/react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  FormControl,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { type UIEvent, useCallback, useEffect, useMemo, useState } from "react";

import { api, errorMessage } from "../api";
import type {
  ArtifactRecord,
  JsonValue,
  RunDetail,
  RunEvent,
  RunInteraction,
  RunSummary,
} from "../types";
import type { WorkflowNodeData } from "../workflow";
import { FlowCanvas } from "./FlowCanvas";

const EVENT_TYPES = [
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
  "run.rerun",
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
  "attempt.started",
  "attempt.ended",
  "agent.message",
  "agent.thought",
  "agent.tool_call",
  "agent.tool_result",
  "agent.plan",
  "agent.provider_event",
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

const TERMINAL_RUNS = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const OUTPUT_ROW_HEIGHT = 86;
const OUTPUT_VIEW_HEIGHT = 430;

interface RunWorkspaceProps {
  selectedRun: string | null;
  onSelectRun: (runId: string | null) => void;
}

function mergeEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  const events = new Map(current.map((event) => [event.id, event]));
  for (const event of incoming) events.set(event.id, event);
  return Array.from(events.values()).sort((left, right) => left.id - right.id);
}

function runGraph(run: RunDetail | null): { nodes: Node<WorkflowNodeData>[]; edges: Edge[] } {
  if (run === null) return { nodes: [], edges: [] };
  return {
    nodes: run.nodes.map((node, index) => ({
      id: node.scope_path,
      position: { x: (index % 3) * 255, y: Math.floor(index / 3) * 145 },
      data: { label: node.scope_path, kind: node.node_type, status: node.status },
      className: `node-status-${node.status}`,
    })),
    edges: [],
  };
}

function outputText(event: RunEvent): string | null {
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

function VirtualOutput({ events }: { events: RunEvent[] }) {
  const rows = useMemo(
    () => events.flatMap((event) => {
      const text = outputText(event);
      return text === null ? [] : [{ event, text }];
    }),
    [events],
  );
  const [scrollTop, setScrollTop] = useState(0);
  const start = Math.max(0, Math.floor(scrollTop / OUTPUT_ROW_HEIGHT) - 3);
  const visibleCount = Math.ceil(OUTPUT_VIEW_HEIGHT / OUTPUT_ROW_HEIGHT) + 6;
  const visible = rows.slice(start, start + visibleCount);

  function updateScroll(event: UIEvent<HTMLDivElement>) {
    setScrollTop(event.currentTarget.scrollTop);
  }

  return (
    <Box className="output-viewport" onScroll={updateScroll}>
      <Box sx={{ position: "relative", height: Math.max(rows.length * OUTPUT_ROW_HEIGHT, 1) }}>
        {visible.map(({ event, text }, offset) => (
          <Box
            className="output-row"
            key={event.id}
            style={{ top: (start + offset) * OUTPUT_ROW_HEIGHT, height: OUTPUT_ROW_HEIGHT }}
          >
            <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
              <Chip size="small" label={event.type} />
              <Typography variant="caption" color="text.secondary">
                #{event.id} · {new Date(event.ts).toLocaleTimeString()}
              </Typography>
            </Stack>
            <Typography component="pre" variant="body2" className="output-text">
              {text}
            </Typography>
          </Box>
        ))}
      </Box>
      {rows.length === 0 && (
        <Typography color="text.secondary" sx={{ p: 2 }}>No provider or command output yet.</Typography>
      )}
    </Box>
  );
}

function optionValue(value: JsonValue): string | null {
  if (typeof value === "string") return value;
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  for (const key of ["id", "value", "optionId"]) {
    if (typeof value[key] === "string") return value[key];
  }
  return null;
}

function optionLabel(value: JsonValue): string {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return String(value);
  for (const key of ["name", "label", "id", "value", "optionId"]) {
    if (typeof value[key] === "string") return value[key];
  }
  return JSON.stringify(value);
}

function InteractionCard({
  interaction,
  onAnswered,
}: {
  interaction: RunInteraction;
  onAnswered: () => Promise<void>;
}) {
  const options = Array.isArray(interaction.request.options) ? interaction.request.options : [];
  const [value, setValue] = useState(() => optionValue(options[0] ?? "") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function answer() {
    setBusy(true);
    setError(null);
    try {
      const path = `/api/attempts/${encodeURIComponent(interaction.attempt_id)}/${interaction.kind}`;
      let answerValue: JsonValue = value;
      if (interaction.kind === "elicitation") {
        try {
          answerValue = JSON.parse(value) as JsonValue;
        } catch {
          answerValue = value;
        }
      }
      await api<{ result: string }>(path, {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: crypto.randomUUID(),
          ...(interaction.kind === "permission"
            ? { decision: value }
            : { value: answerValue }),
        }),
      });
      await onAnswered();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Paper variant="outlined" className="interaction-card">
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <Chip size="small" color="warning" label={interaction.kind} />
          <Typography variant="subtitle2">{interaction.scope_path}</Typography>
        </Stack>
        <Typography>{String(interaction.request.prompt ?? "Owner input required.")}</Typography>
        {options.length > 0 ? (
          <FormControl size="small">
            <InputLabel>Decision</InputLabel>
            <Select value={value} label="Decision" onChange={(event) => setValue(event.target.value)}>
              {options.flatMap((option) => {
                const id = optionValue(option);
                return id === null ? [] : [<MenuItem key={id} value={id}>{optionLabel(option)}</MenuItem>];
              })}
            </Select>
          </FormControl>
        ) : (
          <TextField
            size="small"
            label={interaction.kind === "permission" ? "Decision" : "Response (text or JSON)"}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        )}
        {error && <Alert severity="error">{error}</Alert>}
        <Button variant="contained" onClick={() => void answer()} disabled={busy || value === ""}>
          {busy ? "Sending…" : "Send response"}
        </Button>
      </Stack>
    </Paper>
  );
}

export function RunWorkspace({ selectedRun, onSelectRun }: RunWorkspaceProps) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runCursor, setRunCursor] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [eventCursor, setEventCursor] = useState<number | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [streamState, setStreamState] = useState("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [cleanupScope, setCleanupScope] = useState("all");
  const [cleanupOpen, setCleanupOpen] = useState(false);

  const loadHistory = useCallback(async (cursor?: string) => {
    const query = new URLSearchParams({ limit: "50" });
    if (cursor) query.set("since", cursor);
    const response = await api<{ runs: RunSummary[]; next: string | null }>(
      `/api/runs?${query.toString()}`,
    );
    setRuns((current) => (cursor ? [...current, ...response.runs] : response.runs));
    setRunCursor(response.next);
    if (!cursor && selectedRun === null && response.runs[0]) onSelectRun(response.runs[0].id);
  }, [onSelectRun, selectedRun]);

  const refreshDetail = useCallback(async (): Promise<RunDetail | null> => {
    if (selectedRun === null) return null;
    const [runResponse, artifactResponse] = await Promise.all([
      api<{ run: RunDetail }>(`/api/runs/${encodeURIComponent(selectedRun)}`),
      api<{ artifacts: ArtifactRecord[] }>(
        `/api/runs/${encodeURIComponent(selectedRun)}/artifacts`,
      ),
    ]);
    setDetail(runResponse.run);
    setArtifacts(artifactResponse.artifacts);
    return runResponse.run;
  }, [selectedRun]);

  const loadEvents = useCallback(async (since = 0) => {
    if (selectedRun === null) return;
    const response = await api<{ events: RunEvent[]; next: number | null }>(
      `/api/runs/${encodeURIComponent(selectedRun)}/events?since=${since}&limit=100`,
    );
    setEvents((current) => (since === 0 ? response.events : mergeEvents(current, response.events)));
    setEventCursor(response.next);
  }, [selectedRun]);

  useEffect(() => {
    void loadHistory().catch((caught: unknown) => setError(errorMessage(caught)));
  }, [loadHistory]);

  useEffect(() => {
    setDetail(null);
    setEvents([]);
    setArtifacts([]);
    setEventCursor(null);
    if (selectedRun === null) return;
    void Promise.all([refreshDetail(), loadEvents()]).catch((caught: unknown) =>
      setError(errorMessage(caught)),
    );

    const source = new EventSource(`/api/runs/${encodeURIComponent(selectedRun)}/stream`);
    setStreamState("connecting");
    source.onopen = () => setStreamState("live");
    const receive = (event: Event) => {
      if (!(event instanceof MessageEvent)) {
        setStreamState("reconnecting");
        return;
      }
      try {
        const item = JSON.parse(event.data) as RunEvent;
        setEvents((current) => mergeEvents(current, [item]));
        void refreshDetail()
          .then((run) => {
            if (run && TERMINAL_RUNS.has(run.status)) {
              source.close();
              setStreamState("complete");
            }
          })
          .catch((caught: unknown) => setError(errorMessage(caught)));
      } catch {
        setError("Relay received an invalid event frame.");
      }
    };
    for (const type of EVENT_TYPES) source.addEventListener(type, receive);
    source.addEventListener("error", receive);
    return () => source.close();
  }, [loadEvents, refreshDetail, selectedRun]);

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

  async function rerunNode(scopePath: string) {
    if (selectedRun === null) return;
    try {
      await api<{ result: string }>(`/api/runs/${encodeURIComponent(selectedRun)}/rerun-node`, {
        method: "POST",
        body: JSON.stringify({ scope_path: scopePath, idempotency_key: crypto.randomUUID() }),
      });
      await refreshDetail();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function cleanData() {
    try {
      await api<{ deleted: Record<string, number> }>("/api/data/clean", {
        method: "POST",
        body: JSON.stringify({ scope: cleanupScope, confirm: true }),
      });
      setCleanupOpen(false);
      onSelectRun(null);
      setDetail(null);
      await loadHistory();
    } catch (caught) {
      setError(errorMessage(caught));
      setCleanupOpen(false);
    }
  }

  const graph = useMemo(() => runGraph(detail), [detail]);
  const pendingInteractions = detail?.interactions.filter((item) => item.status === "pending") ?? [];
  const active = detail && ["pending", "running", "paused_wait", "canceling"].includes(detail.status);

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      <Box className="run-layout">
        <Paper variant="outlined" className="history-panel">
          <Stack direction="row" sx={{ alignItems: "center", p: 2 }}>
            <Typography variant="h6" sx={{ flex: 1 }}>Run history</Typography>
            <Button size="small" onClick={() => void loadHistory()}>Refresh</Button>
          </Stack>
          <Divider />
          <List disablePadding>
            {runs.map((run) => (
              <ListItemButton
                key={run.id}
                selected={run.id === selectedRun}
                onClick={() => onSelectRun(run.id)}
              >
                <ListItemText
                  primary={run.workflow_key}
                  secondary={`${run.status} · ${run.started_at ? new Date(run.started_at).toLocaleString() : "not started"}`}
                />
              </ListItemButton>
            ))}
          </List>
          {runCursor && (
            <Button fullWidth onClick={() => void loadHistory(runCursor)}>Load older runs</Button>
          )}
        </Paper>

        <Stack spacing={2} sx={{ minWidth: 0 }}>
          {detail === null ? (
            <Paper variant="outlined" className="empty-panel">
              <Typography color="text.secondary">Select a run to inspect it.</Typography>
            </Paper>
          ) : (
            <>
              <Paper variant="outlined" className="section-card">
                <Stack
                  direction={{ xs: "column", md: "row" }}
                  spacing={2}
                  sx={{ alignItems: { md: "center" } }}
                >
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="h5">{detail.workflow_key}</Typography>
                    <Typography variant="body2" color="text.secondary" className="mono-wrap">
                      {detail.id} · {detail.run_branch}
                    </Typography>
                  </Box>
                  <Chip color={detail.status === "succeeded" ? "success" : "default"} label={detail.status} />
                  <Chip variant="outlined" label={`SSE ${streamState}`} />
                  {active && (
                    <Button color="error" variant="outlined" onClick={() => void cancelRun()}>
                      Cancel run
                    </Button>
                  )}
                </Stack>
                {detail.failure_summary && <Alert severity="error" sx={{ mt: 2 }}>{detail.failure_summary}</Alert>}
                {detail.status === "interrupted" && (
                  <Alert severity="info" sx={{ mt: 2 }}>
                    Restarting <code>relay up</code> resumes this run from durable state as a fresh attempt.
                  </Alert>
                )}
              </Paper>

              {pendingInteractions.length > 0 && (
                <Box className="interaction-grid">
                  {pendingInteractions.map((interaction) => (
                    <InteractionCard
                      key={interaction.id}
                      interaction={interaction}
                      onAnswered={async () => { await refreshDetail(); }}
                    />
                  ))}
                </Box>
              )}

              <Paper variant="outlined" className="canvas-panel run-canvas">
                <FlowCanvas nodes={graph.nodes} edges={graph.edges} />
              </Paper>

              <Paper variant="outlined" className="section-card">
                <Typography variant="h6" sx={{ mb: 1.5 }}>Provider and command output</Typography>
                <VirtualOutput events={events} />
              </Paper>

              <Paper variant="outlined" className="section-card">
                <Stack direction="row" sx={{ alignItems: "center", mb: 1 }}>
                  <Typography variant="h6" sx={{ flex: 1 }}>Event history</Typography>
                  {eventCursor !== null && (
                    <Button onClick={() => void loadEvents(eventCursor)}>Load next page</Button>
                  )}
                </Stack>
                <Box className="event-list">
                  {events.map((event) => (
                    <Box key={event.id} className="event-row">
                      <Typography variant="caption" color="text.secondary">#{event.id}</Typography>
                      <Chip size="small" label={event.type} />
                      <Typography component="code" variant="body2" className="event-payload">
                        {JSON.stringify(event.payload)}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              </Paper>

              <Paper variant="outlined" className="section-card">
                <Typography variant="h6" sx={{ mb: 1 }}>Failed nodes</Typography>
                <Stack spacing={1}>
                  {detail.nodes.filter((node) => node.status === "failed").map((node) => (
                    <Stack key={node.id} direction="row" spacing={2} sx={{ alignItems: "center" }}>
                      <Typography className="mono-wrap" sx={{ flex: 1 }}>{node.scope_path}</Typography>
                      <Button variant="outlined" onClick={() => void rerunNode(node.scope_path)}>
                        Rerun node
                      </Button>
                    </Stack>
                  ))}
                  {!detail.nodes.some((node) => node.status === "failed") && (
                    <Typography color="text.secondary">No failed nodes are eligible for rerun.</Typography>
                  )}
                </Stack>
              </Paper>

              <Paper variant="outlined" className="section-card">
                <Typography variant="h6" sx={{ mb: 1 }}>Artifacts</Typography>
                <Stack spacing={1}>
                  {artifacts.map((artifact) => (
                    <Stack
                      key={artifact.id}
                      direction="row"
                      spacing={2}
                      sx={{ alignItems: "center" }}
                    >
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography>{artifact.name}</Typography>
                        <Typography variant="caption" color="text.secondary" className="mono-wrap">
                          {artifact.sha256} · {artifact.bytes.toLocaleString()} bytes
                        </Typography>
                      </Box>
                      <Button
                        component="a"
                        href={`/api/artifacts/${encodeURIComponent(artifact.id)}`}
                        download
                      >
                        Download
                      </Button>
                    </Stack>
                  ))}
                  {artifacts.length === 0 && (
                    <Typography color="text.secondary">No preserved artifacts.</Typography>
                  )}
                </Stack>
              </Paper>
            </>
          )}

          <Paper variant="outlined" className="section-card">
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={2}
              sx={{ alignItems: { sm: "center" } }}
            >
              <Box sx={{ flex: 1 }}>
                <Typography variant="h6">Retained data cleanup</Typography>
                <Typography variant="body2" color="text.secondary">
                  Cleanup is rejected while any project run is active and always requires confirmation.
                </Typography>
              </Box>
              <FormControl size="small" sx={{ minWidth: 150 }}>
                <InputLabel>Scope</InputLabel>
                <Select value={cleanupScope} label="Scope" onChange={(event) => setCleanupScope(event.target.value)}>
                  <MenuItem value="worktrees">Worktrees</MenuItem>
                  <MenuItem value="branches">Branches</MenuItem>
                  <MenuItem value="runs">Run history</MenuItem>
                  <MenuItem value="all">Everything</MenuItem>
                </Select>
              </FormControl>
              <Button color="error" variant="outlined" onClick={() => setCleanupOpen(true)}>
                Clean data
              </Button>
            </Stack>
          </Paper>
        </Stack>
      </Box>

      <Dialog open={cleanupOpen} onClose={() => setCleanupOpen(false)}>
        <DialogTitle>Delete retained Relay data?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This permanently deletes the selected <strong>{cleanupScope}</strong> scope for the current
            project. Relay will not change the launch branch.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCleanupOpen(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={() => void cleanData()}>
            Confirm deletion
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
