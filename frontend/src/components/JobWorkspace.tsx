import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button,
  FormControl, InputLabel, MenuItem, Paper, Select, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { ansiSpans, commandLines, jobDuration } from "../job";
import { stageLabel, statusLabel } from "../navigation";
import type { JobAttempt, JobChanges, RetryConfiguration, RunEvent, RunJob } from "../types";
import { DiffViewer } from "./DiffViewer";
import { JobLog } from "./JobLog";
import { ActionIcon, StatusIcon } from "./ActionIcon";
import { useClock } from "../useClock";

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
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [logRevision, setLogRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingJob, setLoadingJob] = useState(true);
  const [logsComplete, setLogsComplete] = useState(false);
  const [changesOpen, setChangesOpen] = useState(false);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const relevant = useMemo(() => liveEvents.filter((event) => event.payload.scope_path === scope), [liveEvents, scope]);
  const revision = relevant.filter((event) => event.type === "attempt.ended" || event.type === "attempt.started" || event.type.startsWith("node.")).at(-1)?.id;
  const attempts = useMemo(() => Array.from(new Map([...(job?.attempts ?? []), ...(job?.latest_attempt ? [job.latest_attempt] : [])].map((attempt) => [attempt.number, attempt])).values()).sort((a, b) => a.number - b.number), [job]);
  const attempt = attempts.find((row) => row.number === (attemptNumber ?? job?.latest_attempt?.number));
  const now = useClock(attempt?.status === "running" || attempt?.status === "waiting");
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
    setError(null);
    setEvents([]); setChangesOpen(false);
    setLogsComplete(false);
    setLoadingLogs(true);
    void (async () => {
      let before: number | null = null;
      do {
        const page: EventPage = await api<EventPage>(`/api/runs/${runId}/events?${query}&attempt=${attempt.number}&latest=true${before === null ? "" : `&before=${before}`}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setEvents((current) => mergeEvents(page.events, current));
        if (page.next !== null && before !== null && page.next >= before) throw new Error("Log history did not advance. Refresh logs to try again.");
        before = page.next;
      } while (before !== null);
      setLogsComplete(true);
    })().catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); })
      .finally(() => { if (!controller.signal.aborted) setLoadingLogs(false); });
    return () => controller.abort();
  }, [runId, query, attempt?.number, logRevision]);
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
  const lines = commandLines(events);
  const lastError = lines.filter((line) => line.stream === "stderr").slice(-12).map((line) => ansiSpans(line.text).map((span) => span.text).join("")).join("\n");
  if (!job) return <Paper className="section-card" aria-busy={!error}>{error ? <Alert severity="error">{error}</Alert> : "Loading job…"}</Paper>;
  const outputLabel = job.node_type === "command" ? "Command output" : job.node_type === "agent" ? "Agent conversation" : job.node_type === "human_wait" ? "Human review" : "Job activity";
  return <Stack spacing={0} component="section" aria-label="Job log" className="job-workspace">
    <Paper variant="outlined" className="section-card job-heading">
      <Typography ref={heading} tabIndex={-1} component="h2" variant="h5" sx={{ scrollMarginTop: 90 }}><span aria-hidden="true"><StatusIcon status={job.status} size={22} /></span> {stageLabel(scope)}</Typography>
      {failed && <Alert severity="error" sx={{ mt: 1 }}>
        <Typography>{attempt?.error_message ?? `Job failed${attempt?.exit_code !== null ? ` with exit code ${attempt?.exit_code}` : ""}.`}</Typography>
        {attempt?.provider_message && <Typography sx={{ whiteSpace: "pre-wrap" }}>{attempt.provider_message}</Typography>}
        {lastError && <Box component="pre" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", m: 0 }}>{lastError}</Box>}
      </Alert>}
      <Typography sx={{ mt: 1 }}>{attempt?.agent_id ? `Runs on ${stageLabel(attempt.agent_id)} · ${attempt.model_value}` : job.node_type === "human_wait" ? "Human review" : stageLabel(job.node_type)} · {jobDuration(attempt?.started_at, attempt?.ended_at, now, attempt?.status ?? job.status)}</Typography>
      <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 2, flexWrap: "wrap", alignItems: "center" }}>
        <FormControl size="small" sx={{ minWidth: 190 }}><InputLabel id="job-attempt" shrink>Attempt</InputLabel>
          <Select displayEmpty renderValue={!attempt ? () => "Not started" : undefined} labelId="job-attempt" label="Attempt" disabled={!attempts.length} value={attempt?.number ?? ""} onChange={(event) => setAttemptNumber(Number(event.target.value))}>
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
    <Accordion><AccordionSummary expandIcon={<ActionIcon name="chevron" />}>Set up</AccordionSummary><AccordionDetails>
      <Typography>{job.writes ? "This job can write to its isolated working folder." : "This job reads its isolated working folder."}</Typography>
      <Typography>Captured job: {scope}</Typography>
      {job.command && <Box component="pre" className="activity-text">{job.command.join("\n")}</Box>}
    </AccordionDetails></Accordion>
    <Accordion><AccordionSummary expandIcon={<ActionIcon name="chevron" />}>Instructions</AccordionSummary><AccordionDetails>
      {job.prompt && <Typography sx={{ whiteSpace: "pre-wrap" }}>{job.prompt}</Typography>}
      {job.instructions.map((instruction, index) => <Box key={index} sx={{ mb: 2 }}>
        <Typography variant="subtitle2">{instruction.reference.local ?? instruction.reference.global}</Typography>
        <Box component="pre" className="activity-text">{instruction.text}</Box>
        {instruction.truncated && <Alert severity="info">This captured instruction exceeds the preview limit.</Alert>}
      </Box>)}
      {!job.prompt && !job.instructions.length && <Typography>No prompt files were captured for this job.</Typography>}
    </AccordionDetails></Accordion>
    <Accordion key={`${attempt?.number}-${failed}`} defaultExpanded={failed || job.node_type === "command" || job.node_type === "agent"}>
      <AccordionSummary aria-label={outputLabel} expandIcon={<ActionIcon name="chevron" />}><span aria-hidden="true"><StatusIcon status={attempt?.status === "succeeded" ? "succeeded" : job.status} /></span> {outputLabel}<Typography className="step-duration" variant="caption">{jobDuration(attempt?.started_at, attempt?.ended_at, now, attempt?.status ?? job.status)}</Typography></AccordionSummary>
      <AccordionDetails>
        {attempt ? <JobLog key={`${runId}:${scope}:${attempt?.number}`} events={events} label={outputLabel} workingFolder={job.working_folder}
          live={attempt?.status === "running" || attempt?.status === "waiting"} command={job.node_type === "command"}
          loading={loadingLogs} hasMore={!logsComplete} onMore={async () => setLogRevision((value) => value + 1)} onRefresh={() => setLogRevision((value) => value + 1)}
          scope={scope} attempt={attempt.number} /> : <Typography>{["canceled", "skipped"].includes(job.status) ? "This job did not run." : "No attempt has started yet."}</Typography>}
      </AccordionDetails>
    </Accordion>
    <Accordion><AccordionSummary expandIcon={<ActionIcon name="chevron" />}>Outputs</AccordionSummary><AccordionDetails>
      {attempt?.number === job.latest_attempt?.number ? Object.keys(job.outputs).length ? <Table size="small" aria-label="Declared outputs"><TableHead><TableRow><TableCell>Name</TableCell><TableCell>Value</TableCell></TableRow></TableHead><TableBody>
        {Object.entries(job.outputs).map(([name, value]) => <TableRow key={name}><TableCell>{name}</TableCell><TableCell>
          {typeof value === "object" && value !== null ? <Box component="details"><Box component="summary">Details</Box><Box component="pre" className="activity-text">{JSON.stringify(value, null, 2)}</Box></Box> : String(value)}
        </TableCell></TableRow>)}
      </TableBody></Table> : <Typography>No declared outputs.</Typography> : <Typography>Declared outputs describe the latest attempt. Select it to see them.</Typography>}
    </AccordionDetails></Accordion>
    <Accordion expanded={changesOpen} onChange={(_event, expanded) => setChangesOpen(expanded)}><AccordionSummary expandIcon={<ActionIcon name="chevron" />}>Changes</AccordionSummary><AccordionDetails>
      {changesOpen && attempt ? <JobChangesView runId={runId} scope={scope} attempt={attempt} /> : <Typography>No attempt has started.</Typography>}
    </AccordionDetails></Accordion>
    <Accordion><AccordionSummary expandIcon={<ActionIcon name="chevron" />}>Complete</AccordionSummary><AccordionDetails>
      <Typography>{attempt?.stop_reason ? stageLabel(attempt.stop_reason) : statusLabel(job.status)}{attempt?.exit_code !== null && attempt?.exit_code !== undefined ? ` · Exit code ${attempt.exit_code}` : ""}</Typography>
      {attempt?.ended_at && <Typography>Finished {new Date(attempt.ended_at).toLocaleString()}</Typography>}
    </AccordionDetails></Accordion>
  </Stack>;
}
