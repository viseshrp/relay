import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button,
  FormControl, InputLabel, MenuItem, Paper, Select, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { activityMessages } from "../activity";
import { ansiSpans, commandLines, jobDuration, type AnsiStyle } from "../job";
import { stageLabel, statusLabel } from "../navigation";
import type { JobAttempt, JobChanges, RetryConfiguration, RunEvent, RunJob } from "../types";
import { DiffViewer } from "./DiffViewer";

interface JobPage { job: RunJob; next: number | null }
interface EventPage { events: RunEvent[]; next: number | null }
function mergeEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  return Array.from(new Map([...current, ...incoming].map((event) => [event.id, event])).values()).sort((a, b) => a.id - b.id);
}

function JobChangesView({ runId, scope, attempt }: { runId: string; scope: string; attempt: JobAttempt }) {
  const [changes, setChanges] = useState<JobChanges | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void api<JobChanges>(`/api/runs/${runId}/changes?job=${encodeURIComponent(scope)}&attempt=${attempt.number}`, { signal: controller.signal })
      .then(setChanges).catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); });
    return () => controller.abort();
  }, [runId, scope, attempt.number, attempt.ending_head]);
  return <Stack spacing={1}>
    {error && <Alert severity="error">{error}</Alert>}
    {!changes && !error && <Typography>Loading this attempt's changes…</Typography>}
    {changes && <>
      {changes.commits.map((commit) => <Box key={commit.sha}><Typography>{commit.title}</Typography><Box component="details"><Box component="summary">Commit details</Box><Box component="code">{commit.sha}</Box></Box></Box>)}
      {changes.commits.length >= 100 && <Typography>Showing the latest 100 commits.</Typography>}
      <DiffViewer text={changes.text} truncated={changes.truncated} />
    </>}
  </Stack>;
}

export function JobWorkspace({ runId, scope, liveEvents, canRetry, refreshing, onRetry, onRetrySettings }: {
  runId: string; scope: string; liveEvents: RunEvent[]; canRetry: boolean;
  refreshing: boolean;
  onRetry: (scope: string) => Promise<void>;
  onRetrySettings: (settings: RetryConfiguration) => void;
}) {
  const [job, setJob] = useState<RunJob | null>(null);
  const [attemptNumber, setAttemptNumber] = useState<number | null>(null);
  const [attemptCursor, setAttemptCursor] = useState<number | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [older, setOlder] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingJob, setLoadingJob] = useState(true);
  const [changesOpen, setChangesOpen] = useState(false);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const relevant = useMemo(() => liveEvents.filter((event) => event.payload.scope_path === scope), [liveEvents, scope]);
  const revision = relevant.filter((event) => event.type === "attempt.ended" || event.type === "attempt.started" || event.type.startsWith("node.")).at(-1)?.id;
  const attempts = useMemo(() => Array.from(new Map([...(job?.attempts ?? []), ...(job?.latest_attempt ? [job.latest_attempt] : [])].map((attempt) => [attempt.number, attempt])).values()).sort((a, b) => a.number - b.number), [job]);
  const attempt = attempts.find((row) => row.number === (attemptNumber ?? job?.latest_attempt?.number));
  const failed = attempt?.stop_reason === "failed" || Boolean(attempt?.error_code);
  const query = `job=${encodeURIComponent(scope)}&limit=200`;

  useEffect(() => {
    const controller = new AbortController();
    setLoadingJob(true);
    void api<JobPage>(`/api/runs/${runId}/job?${query}`, { signal: controller.signal }).then((value) => {
      if (controller.signal.aborted) return;
      setJob((current) => ({ ...value.job, attempts: Array.from(new Map([...(current?.attempts ?? []), ...value.job.attempts].map((row) => [row.number, row])).values()) }));
      setAttemptCursor(value.next);
    }).catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); })
      .finally(() => { if (!controller.signal.aborted) setLoadingJob(false); });
    return () => controller.abort();
  }, [runId, query, revision, refreshing]);

  async function openRetrySettings(): Promise<void> {
    setBusy(true);
    try {
      const current = await api<JobPage>(`/api/runs/${runId}/job?${query}`);
      if (current.job.retry_settings) onRetrySettings(current.job.retry_settings);
      else setError("This job no longer has retry settings. Refresh the run to see its current state.");
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    if (!job) return;
    heading.current?.scrollIntoView({ block: "start" });
    heading.current?.focus({ preventScroll: true });
  }, [Boolean(job)]);
  useEffect(() => {
    if (!attempt) return;
    const controller = new AbortController();
    setEvents([]); setOlder(null); setChangesOpen(false);
    void api<EventPage>(`/api/runs/${runId}/events?${query}&attempt=${attempt.number}&latest=true`, { signal: controller.signal })
      .then((value) => { setEvents(value.events); setOlder(value.next); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); });
    return () => controller.abort();
  }, [runId, query, attempt?.number]);
  useEffect(() => {
    if (attempt) setEvents((current) => mergeEvents(current, relevant.filter((event) => event.payload.attempt_number === attempt.number)));
  }, [relevant, attempt?.number]);

  async function moreAttempts() {
    if (attemptCursor === null) return;
    try {
      const value = await api<JobPage>(`/api/runs/${runId}/job?${query}&since=${attemptCursor}`);
      setJob((current) => current ? { ...current, attempts: [...current.attempts, ...value.job.attempts] } : value.job);
      setAttemptCursor(value.next);
    } catch (caught) { setError(errorMessage(caught)); }
  }
  async function olderOutput() {
    if (!attempt || older === null) return;
    try {
      const value = await api<EventPage>(`/api/runs/${runId}/events?${query}&attempt=${attempt.number}&latest=true&before=${older}`);
      setEvents((current) => mergeEvents(value.events, current)); setOlder(value.next);
    } catch (caught) { setError(errorMessage(caught)); }
  }
  async function exportOutput(download: boolean) {
    if (!attempt) return;
    setBusy(true); setError(null);
    try {
      const pages: RunEvent[] = [];
      let since = 0;
      for (;;) {
        const value = await api<EventPage>(`/api/runs/${runId}/events?${query}&attempt=${attempt.number}&since=${since}`);
        pages.push(...value.events);
        if (value.next === null) break;
        since = value.next;
      }
      const text = pages.filter((event) => event.type === "command.stdout" || event.type === "command.stderr")
        .map((event) => String(event.payload.chunk ?? event.payload.text ?? "")).join("");
      if (!download) await navigator.clipboard.writeText(text);
      else {
        const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
        const link = document.createElement("a"); link.href = url;
        link.download = `${scope.replace(/[^a-zA-Z0-9_-]/g, "-")}-attempt-${attempt.number}.log`;
        link.click(); URL.revokeObjectURL(url);
      }
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }
  const lines = commandLines(events);
  const lastError = lines.filter((line) => line.stream === "stderr").slice(-12).map((line) => ansiSpans(line.text).map((span) => span.text).join("")).join("\n");
  const messages = activityMessages(events);
  const terminalStyle: AnsiStyle = { bold: false };
  if (!job) return <Paper className="section-card" aria-busy={!error}>{error ? <Alert severity="error">{error}</Alert> : "Loading job…"}</Paper>;
  return <Stack spacing={2} component="section" aria-label="Job log">
    <Paper variant="outlined" className="section-card">
      <Typography ref={heading} tabIndex={-1} component="h2" variant="h5" sx={{ scrollMarginTop: 90 }}>{stageLabel(scope)}</Typography>
      {failed && <Alert severity="error" sx={{ mt: 1 }}>
        <Typography>{attempt?.error_message ?? `Job failed${attempt?.exit_code !== null ? ` with exit code ${attempt?.exit_code}` : ""}.`}</Typography>
        {attempt?.provider_message && <Typography sx={{ whiteSpace: "pre-wrap" }}>{attempt.provider_message}</Typography>}
        {lastError && <Box component="pre" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", m: 0 }}>{lastError}</Box>}
      </Alert>}
      <Typography sx={{ mt: 1 }}>{attempt?.agent_id ? `Runs on ${stageLabel(attempt.agent_id)} · ${attempt.model_value}` : stageLabel(job.node_type)} · {jobDuration(attempt?.started_at, attempt?.ended_at)}</Typography>
      <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
        <FormControl size="small" sx={{ minWidth: 190 }}><InputLabel id="job-attempt">Attempt</InputLabel>
          <Select labelId="job-attempt" label="Attempt" value={attempt?.number ?? ""} onChange={(event) => setAttemptNumber(Number(event.target.value))}>
            {attempts.map((row) => <MenuItem key={row.number} value={row.number}>Attempt {row.number} · {row.stop_reason ? stageLabel(row.stop_reason) : statusLabel(row.status)}</MenuItem>)}
          </Select></FormControl>
        {canRetry && job.status === "failed" && <>
          <Button variant="outlined" disabled={busy || refreshing || loadingJob} onClick={() => { setBusy(true); void onRetry(scope).catch((caught: unknown) => setError(errorMessage(caught))).finally(() => setBusy(false)); }}>Re-run job</Button>
          {job.retry_settings && <Button disabled={busy || refreshing || loadingJob} onClick={() => void openRetrySettings()}>Re-run with settings</Button>}
        </>}
        {attemptCursor !== null && <Button onClick={() => void moreAttempts()}>Load more attempts</Button>}
      </Stack>
    </Paper>
    {error && <Alert severity="error">{error}</Alert>}
    <Accordion><AccordionSummary>Set up</AccordionSummary><AccordionDetails>
      <Typography>{job.writes ? "This job can write to its isolated working folder." : "This job reads its isolated working folder."}</Typography>
      <Typography>Captured job: {scope}</Typography>
      {job.command && <Box component="pre" className="activity-text">{job.command.join("\n")}</Box>}
    </AccordionDetails></Accordion>
    <Accordion><AccordionSummary>Instructions</AccordionSummary><AccordionDetails>
      {job.prompt && <Typography sx={{ whiteSpace: "pre-wrap" }}>{job.prompt}</Typography>}
      {job.instructions.map((instruction, index) => <Box key={index} sx={{ mb: 2 }}>
        <Typography variant="subtitle2">{instruction.reference.local ?? instruction.reference.global}</Typography>
        <Box component="pre" className="activity-text">{instruction.text}</Box>
        {instruction.truncated && <Alert severity="info">This captured instruction exceeds the preview limit.</Alert>}
      </Box>)}
      {!job.prompt && !job.instructions.length && <Typography>No prompt files were captured for this job.</Typography>}
    </AccordionDetails></Accordion>
    <Accordion key={`${attempt?.number}-${failed}`} defaultExpanded={failed || job.node_type === "command" || job.node_type === "agent"}>
      <AccordionSummary>{job.node_type === "command" ? "Command output" : "Agent conversation"}</AccordionSummary>
      <AccordionDetails>
        {older !== null && <Button onClick={() => void olderOutput()}>Load earlier output</Button>}
        {job.node_type === "command" ? <>
          <Stack direction="row" spacing={1} sx={{ mb: 1 }}><Button disabled={busy || !attempt} onClick={() => void exportOutput(false)}>Copy output</Button><Button disabled={busy || !attempt} onClick={() => void exportOutput(true)}>Download output</Button></Stack>
          <Box component="ol" aria-label="Command output lines" sx={{ bgcolor: "#0f172a", color: "#f1f5f9", fontFamily: "monospace", maxHeight: 430, overflow: "auto", p: 2, pl: 7, m: 0 }}>
            {lines.map((line, index) => <Box component="li" key={index} sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", pl: 1 }}>
              <Box component="span" sx={{ color: line.stream === "stderr" ? "#fca5a5" : "#94a3b8", mr: 1 }}>{line.stream}</Box>
              {ansiSpans(line.text, terminalStyle).map((span, part) => <Box component="span" key={part} sx={{ color: span.color, fontWeight: span.bold ? 700 : 400 }}>{span.text}</Box>)}
            </Box>)}
          </Box>
        </> : <Stack spacing={1}>{messages.map((message) => <Paper key={message.id} variant="outlined" sx={{ p: 2 }}>
          <Typography variant="subtitle2">{stageLabel(message.kind.replace(/^(agent|command)\./, ""))}</Typography>
          <Box component="pre" className="activity-text">{message.text}</Box>
        </Paper>)}</Stack>}
        {!lines.length && !messages.length && <Typography>There is no output for this attempt yet.</Typography>}
      </AccordionDetails>
    </Accordion>
    <Accordion><AccordionSummary>Outputs</AccordionSummary><AccordionDetails>
      {attempt?.number === job.latest_attempt?.number ? Object.keys(job.outputs).length ? <Table size="small" aria-label="Declared outputs"><TableHead><TableRow><TableCell>Name</TableCell><TableCell>Value</TableCell></TableRow></TableHead><TableBody>
        {Object.entries(job.outputs).map(([name, value]) => <TableRow key={name}><TableCell>{name}</TableCell><TableCell>
          {typeof value === "object" && value !== null ? <Box component="details"><Box component="summary">Details</Box><Box component="pre" className="activity-text">{JSON.stringify(value, null, 2)}</Box></Box> : String(value)}
        </TableCell></TableRow>)}
      </TableBody></Table> : <Typography>No declared outputs.</Typography> : <Typography>Declared outputs describe the latest attempt. Select it to see them.</Typography>}
    </AccordionDetails></Accordion>
    <Accordion expanded={changesOpen} onChange={(_event, expanded) => setChangesOpen(expanded)}><AccordionSummary>Changes</AccordionSummary><AccordionDetails>
      {changesOpen && attempt ? <JobChangesView runId={runId} scope={scope} attempt={attempt} /> : <Typography>No attempt has started.</Typography>}
    </AccordionDetails></Accordion>
    <Accordion><AccordionSummary>Complete</AccordionSummary><AccordionDetails>
      <Typography>{attempt?.stop_reason ? stageLabel(attempt.stop_reason) : statusLabel(job.status)}{attempt?.exit_code !== null && attempt?.exit_code !== undefined ? ` · Exit code ${attempt.exit_code}` : ""}</Typography>
      {attempt?.ended_at && <Typography>Finished {new Date(attempt.ended_at).toLocaleString()}</Typography>}
    </AccordionDetails></Accordion>
  </Stack>;
}
