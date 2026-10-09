import { ViewSkeleton } from "./ViewSkeleton";
import { Alert, Button, Paper } from "@mui/material";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { ansiSpans, commandLines } from "../job";
import { stageLabel } from "../navigation";
import type { RetryConfiguration, RunEvent, RunJob, RunNode } from "../types";

import { useDisclosureState } from "../view-state";
import { useClock } from "../useClock";
import { JobPage, EventPage, mergeEvents } from "./JobWorkspaceShared";
export function useJobWorkspace({
  runId,
  scope,
  nodes,
  embedded = false,
  liveEvents,
  canRetry,
  refreshing,
  onRetry,
  onRetrySettings,
}: {
  runId: string;
  scope: string;
  nodes: RunNode[];
  embedded?: boolean;
  liveEvents: RunEvent[];
  canRetry: boolean;
  refreshing: boolean;
  onRetry: (scope: string) => Promise<void>;
  onRetrySettings: (settings: RetryConfiguration) => void;
}) {
  const [panels, setPanel] = useDisclosureState(`${runId}:${scope}`);
  const steps = nodes.filter(
    (node) => node.node_type === "actions_step" && node.parent_scope === scope,
  );
  const [jobRevision, setJobRevision] = useState(0);
  const [job, setJob] = useState<RunJob | null>(null);
  const [attemptNumber, setAttemptNumber] = useState<number | null>(null);
  const [attemptCursor, setAttemptCursor] = useState<number | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [logRevision, setLogRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingJob, setLoadingJob] = useState(true);
  const [logsComplete, setLogsComplete] = useState(false);
  const [changesOpen, setChangesOpen] = useState(false);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const relevant = useMemo(
    () => liveEvents.filter((event) => event.payload.scope_path === scope),
    [liveEvents, scope],
  );
  const revision = relevant
    .filter(
      (event) =>
        event.type === "attempt.ended" ||
        event.type === "attempt.started" ||
        event.type.startsWith("node."),
    )
    .at(-1)?.id;
  const attempts = useMemo(
    () =>
      Array.from(
        new Map(
          [
            ...(job?.attempts ?? []),
            ...(job?.latest_attempt ? [job.latest_attempt] : []),
          ].map((attempt) => [attempt.number, attempt]),
        ).values(),
      ).sort((a, b) => a.number - b.number),
    [job],
  );
  const attempt = attempts.find(
    (row) => row.number === (attemptNumber ?? job?.latest_attempt?.number),
  );
  const now = useClock(
    attempt?.status === "running" || attempt?.status === "waiting",
  );
  const failed =
    attempt?.stop_reason === "failed" || Boolean(attempt?.error_code);
  const query = `job=${encodeURIComponent(scope)}&limit=200`;

  useEffect(() => {
    const controller = new AbortController();
    setLoadingJob(true);
    void api<JobPage>(`/api/runs/${runId}/job?${query}`, {
      signal: controller.signal,
    })
      .then((value) => {
        if (controller.signal.aborted) return;
        setJobError(null);
        setJob((current) => ({
          ...value.job,
          attempts: Array.from(
            new Map(
              [...(current?.attempts ?? []), ...value.job.attempts].map(
                (row) => [row.number, row],
              ),
            ).values(),
          ),
        }));
        setAttemptCursor(value.next);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setJobError(errorMessage(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingJob(false);
      });
    return () => controller.abort();
  }, [runId, query, revision, refreshing, jobRevision]);

  async function openRetrySettings(): Promise<void> {
    setBusy(true);
    try {
      const current = await api<JobPage>(`/api/runs/${runId}/job?${query}`);
      if (current.job.retry_settings)
        onRetrySettings(current.job.retry_settings);
      else
        setError(
          "This job no longer has retry settings. Refresh the run to see its current state.",
        );
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }
  const jobReady = Boolean(job);
  const selectedAttemptNumber = attempt?.number;
  useEffect(() => {
    if (!jobReady || embedded) return;
    heading.current?.scrollIntoView({ block: "start" });
    heading.current?.focus({ preventScroll: true });
  }, [jobReady, embedded]);
  useEffect(() => {
    if (!selectedAttemptNumber) return;
    const controller = new AbortController();
    setError(null);
    setEvents([]);
    setChangesOpen(false);
    setLogsComplete(false);
    setLoadingLogs(true);
    void (async () => {
      let before: number | null = null;
      do {
        const page: EventPage = await api<EventPage>(
          `/api/runs/${runId}/events?${query}&attempt=${selectedAttemptNumber}&latest=true${before === null ? "" : `&before=${before}`}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setEvents((current) => mergeEvents(page.events, current));
        if (page.next !== null && before !== null && page.next >= before)
          throw new Error(
            "Log history did not advance. Refresh logs to try again.",
          );
        before = page.next;
      } while (before !== null);
      setLogsComplete(true);
    })()
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingLogs(false);
      });
    return () => controller.abort();
  }, [runId, query, selectedAttemptNumber, logRevision]);
  useEffect(() => {
    if (selectedAttemptNumber)
      setEvents((current) =>
        mergeEvents(
          current,
          relevant.filter(
            (event) => event.payload.attempt_number === selectedAttemptNumber,
          ),
        ),
      );
  }, [relevant, selectedAttemptNumber]);

  async function moreAttempts() {
    if (attemptCursor === null) return;
    try {
      const value = await api<JobPage>(
        `/api/runs/${runId}/job?${query}&since=${attemptCursor}`,
      );
      setJob((current) =>
        current
          ? {
              ...current,
              attempts: [...current.attempts, ...value.job.attempts],
            }
          : value.job,
      );
      setAttemptCursor(value.next);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }
  const lines = commandLines(events);
  const lastError = lines
    .filter((line) => line.stream === "stderr")
    .slice(-12)
    .map((line) =>
      ansiSpans(line.text)
        .map((span) => span.text)
        .join(""),
    )
    .join("\n");
  if (!job)
    return {
      fallback: (
        <Paper className="section-card" aria-busy={!jobError && !error}>
          {jobError || error ? (
            <Alert severity="error">
              {jobError || error}
              <Button onClick={() => setJobRevision((value) => value + 1)}>
                Retry job
              </Button>
            </Alert>
          ) : (
            <ViewSkeleton view="job" />
          )}
        </Paper>
      ),
    };
  const activityType = job.activity_type || job.node_type;
  const outputLabel =
    activityType === "command"
      ? "Command output"
      : activityType === "agent"
        ? "Agent conversation"
        : activityType === "human_wait"
          ? "Human review"
          : "Job activity";
  const label =
    job.node_type.startsWith("actions_") && job.display_name
      ? job.display_name
      : stageLabel(scope);

  return {
    fallback: null as null,
    embedded,
    heading,
    job: job!,
    label,
    failed,
    attempt,
    lastError,
    activityType,
    now,
    scope,
    attempts,
    setAttemptNumber,
    canRetry,
    busy,
    refreshing,
    loadingJob,
    setBusy,
    onRetry,
    setError,
    openRetrySettings,
    attemptCursor,
    moreAttempts,
    error: jobError || error,
    panels,
    setPanel,
    outputLabel,
    runId,
    events,
    loadingLogs,
    logsComplete,
    setLogRevision,
    steps,
    nodes,
    liveEvents,
    onRetrySettings,
    changesOpen,
    setChangesOpen,
  };
}
export type JobWorkspaceState = Extract<
  ReturnType<typeof useJobWorkspace>,
  { fallback: null }
>;
