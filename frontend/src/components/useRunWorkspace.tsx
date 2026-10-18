import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDisclosureState } from "../view-state";
import { runJobs } from "../job-list";

import { api, errorMessage } from "../api";
import {
  finishRead,
  isAborted,
  readMonitorPages,
  retryRunRead,
  RunReadQueue,
  SnapshotChangedError,
  startRead,
  type MonitorPage,
} from "../run-monitor";
import type {
  ArtifactRecord,
  AgentsResponse,
  WorkflowDocumentResponse,
  RunDetail,
  RunEvent,
  RunInteraction,
  RunNode,
  RunSummary,
  PreviousRunInputs,
  RetryConfiguration,
  RetryOptions,
} from "../types";
import { projectPath } from "../navigation";
import type { LaunchWorkflow } from "../workflow";
import { launchView, parseActions } from "../actions-workflow";

import { attentionChanged } from "../attention";

import { usePendingChoices, type SettingsChoices } from "./usePendingChoices";

import { runSummaryGraph } from "../run-graph";
import { useClock } from "../useClock";

import {
  EVENT_TYPES,
  TERMINAL_RUNS,
  PENDING_RECOVERY,
  PAUSABLE_RUNS,
  RunWorkspaceProps,
  PageMode,
  ArtifactPage,
  mergeEvents,
  mergeRecords,
} from "./RunWorkspaceShared";
type ReadResponse1 = { runs: RunSummary[]; next: string | null };
type ReadResponse2 = { events: RunEvent[]; next: number | null };
type ReadResponse3 = { result: string };
type ReadResponse4 = { environments: Array<{ name: string }> };
type ReadResponse5 = { result: string };

export function useRunWorkspace({
  selectedWorkflow,
  onSelectWorkflow,
  selectedRun,
  onSelectRun,
  onRunWorkflow,
  onEditWorkflow,
  project,
  selectedInteraction,
  selectedJob,
  onSelectJob,
  waitingRuns,
  onRunSucceeded,
}: RunWorkspaceProps) {
  const [localFilters, setLocalFilters] = useState({
    status: "",
    branch: "",
    query: "",
  });
  const filters = useMemo(
    () => ({ ...localFilters, workflow: selectedWorkflow ?? "" }),
    [localFilters, selectedWorkflow],
  );
  const [panels, setPanel] = useDisclosureState(selectedRun ?? "history");
  useEffect(() => {
    window.scrollTo(0, 0);
    setWorkflowFileOpen(false);
    setGraphJobs(null);
  }, [selectedRun]);
  const [fullTitle, setFullTitle] = useState(false);
  const [graphJobs, setGraphJobs] = useState<string[] | null>(null);
  const [workflowFileOpen, setWorkflowFileOpen] = useState(false);
  const [showArtifacts, setShowArtifacts] = useState(false);
  useEffect(() => {
    if (showArtifacts && !selectedJob) {
      document
        .getElementById("run-artifacts")
        ?.scrollIntoView({ block: "start" });
      setShowArtifacts(false);
    }
  }, [showArtifacts, selectedJob]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runCursor, setRunCursor] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  useEffect(() => {
    if (detail?.status === "succeeded") onRunSucceeded?.();
  }, [detail?.status, onRunSucceeded]);
  const [nodeCursor, setNodeCursor] = useState<number | null>(null);
  const [interactionCursor, setInteractionCursor] = useState<number | null>(
    null,
  );
  const [linkedRequest, setLinkedRequest] = useState<RunInteraction | null>(
    null,
  );
  const summaryOnly = useRef(true);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [eventCursor, setEventCursor] = useState<number | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [artifactCursor, setArtifactCursor] = useState<number | null>(null);
  const [streamState, setStreamState] = useState("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [relaunchBusy, setRelaunchBusy] = useState(false);
  const [runAgain, setRunAgain] = useState<{
    source: PreviousRunInputs;
    workflow: LaunchWorkflow;
    models: string[];
    open: boolean;
  } | null>(null);
  const relaunchButton = useRef<HTMLButtonElement>(null);
  const relaunchRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    setRunAgain(null);
    setRelaunchBusy(false);
    return () => {
      relaunchRequest.current?.abort();
      relaunchRequest.current = null;
    };
  }, [selectedRun, project.id]);
  const [stopOpen, setStopOpen] = useState(false);
  const [retrySettings, setRetrySettings] = useState<RetryConfiguration | null>(
    null,
  );
  const [pendingSettings, setPendingSettings] = useState<{
    runId: string;
    settings: RetryConfiguration;
    choices: SettingsChoices;
  } | null>(null);
  const [pauseBusy, setPauseBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [streamRun, setStreamRun] = useState<string | null>(null);
  const [streamEpoch, setStreamEpoch] = useState(0);
  const currentRun = useRef<string | null>(null);
  const [readQueue, setReadQueue] = useState<RunReadQueue | null>(null);
  const queueOwner = useRef<{
    id: string;
    queue: RunReadQueue;
    initial: boolean;
  } | null>(null);
  const targets = useRef({ nodes: 200, interactions: 200 });
  const linkedId = useRef(selectedInteraction);
  const sourceRef = useRef<EventSource | null>(null);
  const flushRef = useRef<(() => void) | null>(null);
  const eventAfter = useRef(0);
  const persistedAfter = useRef(0);
  const artifactAfter = useRef(0);
  const streamComplete = useRef(false);
  const stepProgress = useRef<HTMLDivElement>(null);
  const jobContent = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selectedJob) jobContent.current?.scrollIntoView({ block: "start" });
  }, [selectedJob]);

  const historyRequest = useRef<AbortController | null>(null);
  useEffect(() => () => historyRequest.current?.abort(), []);
  const loadHistory = useCallback(
    async (cursor?: string) => {
      const query = new URLSearchParams({ limit: "50" });
      query.set("project", project.id);
      for (const [key, value] of Object.entries(filters))
        if (value) query.set(key, value);
      if (cursor) query.set("since", cursor);
      historyRequest.current?.abort();
      const controller = new AbortController();
      historyRequest.current = controller;
      setHistoryLoading(true);
      try {
        const response = await api<ReadResponse1>(
          `/api/runs?${query.toString()}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setRuns((current) =>
          cursor ? [...current, ...response.runs] : response.runs,
        );
        setRunCursor(response.next);
      } catch (caught) {
        if (!controller.signal.aborted) throw caught;
      } finally {
        if (!controller.signal.aborted) setHistoryLoading(false);
      }
    },
    [project.id, filters],
  );

  const loadEvents = useCallback(
    async (since = 0, full = false, signal?: AbortSignal) => {
      if (selectedRun === null) return [];
      const summary = summaryOnly.current && !full;
      const response = await api<ReadResponse2>(
        `/api/runs/${encodeURIComponent(selectedRun)}/events?since=${since}&limit=${summary ? 50 : 100}${summary ? "&summary=true" : ""}`,
        { signal, share: false },
      );
      if (currentRun.current !== selectedRun || signal?.aborted) return [];
      if (full) summaryOnly.current = false;
      eventAfter.current = Math.max(
        eventAfter.current,
        response.events.at(-1)?.id ?? 0,
      );
      if (!summary)
        persistedAfter.current = Math.max(
          persistedAfter.current,
          response.events.at(-1)?.id ?? 0,
        );
      setEvents((current) => mergeEvents(current, response.events));
      setEventCursor(summary && since === 0 ? 0 : response.next);
      return response.events;
    },
    [selectedRun],
  );

  const loadArtifacts = useCallback(
    async (
      since: number,
      _mode: PageMode,
    ): Promise<number | null | undefined> => {
      const owner = queueOwner.current;
      if (!selectedRun || owner?.id !== selectedRun) return;
      return owner.queue.read("artifacts", async (signal) => {
        const query = new URLSearchParams({
          since: String(since),
          limit: "50",
          visible: "true",
        });
        for (let attempt = 0; attempt < 4 && !signal.aborted; attempt += 1) {
          const observed = artifactAfter.current;
          const response = await retryRunRead(
            () =>
              api<ArtifactPage>(`/api/runs/${selectedRun}/artifacts?${query}`, {
                signal,
                share: false,
              }),
            signal,
            (caught) => setError(errorMessage(caught)),
          );
          if (signal.aborted || currentRun.current !== selectedRun) return;
          setArtifacts((current) => mergeRecords(current, response.artifacts));
          setArtifactCursor(response.next);
          // Coalescing must not consume an artifact event that arrived while
          // an older page was in flight. Append-only records remain visible.
          if (observed === artifactAfter.current) return response.next;
        }
        if (!signal.aborted) throw new SnapshotChangedError();
      });
    },
    [selectedRun],
  );

  const requestMonitor = useCallback(async (): Promise<RunDetail | null> => {
    const owner = queueOwner.current;
    if (!selectedRun || owner?.id !== selectedRun) return null;
    const queue = owner.queue;
    try {
      return await queue.read("monitor", async (signal) => {
        queue.clock = startRead(queue.clock);
        const observeHistory = (history: RunEvent[]) => {
          for (const event of history) {
            queue.observe(event);
            if (
              event.type === "artifact.preserved" &&
              event.id > artifactAfter.current
            ) {
              artifactAfter.current = event.id;
              void loadArtifacts(0, "refresh").catch((caught: unknown) => {
                if (!isAborted(caught)) setError(errorMessage(caught));
              });
            }
          }
        };
        try {
          for (let attempt = 0; attempt < 4 && !signal.aborted; attempt += 1) {
            const snapshot = await readMonitorPages(
              queue,
              (nodesSince, interactionsSince, selectedLink) => {
                const query = new URLSearchParams({
                  nodes_since: String(nodesSince),
                  interactions_since: String(interactionsSince),
                  limit: "200",
                });
                if (selectedLink) query.set("interaction", selectedLink);
                return retryRunRead(
                  () =>
                    api<MonitorPage>(
                      `/api/runs/${selectedRun}/monitor?${query}`,
                      { signal, share: false },
                    ),
                  signal,
                  (caught) => setError(errorMessage(caught)),
                );
              },
              () => ({ ...targets.current, linkedId: linkedId.current }),
              signal,
            );
            const terminal =
              TERMINAL_RUNS.has(snapshot.run.status) &&
              snapshot.run.problem?.retry?.state !== "scheduled" &&
              !PENDING_RECOVERY.has(
                snapshot.run.recovery?.current?.state ?? "",
              );
            if (owner.initial) {
              summaryOnly.current = terminal;
              if (terminal) {
                // An already-finished run opens with lazy historical logs.
                // Drain new output from this boundary if it is retried later.
                persistedAfter.current = snapshot.event_cursor;
                eventAfter.current = snapshot.event_cursor;
              }
              const history = await loadEvents(0, false, signal);
              observeHistory(history);
              owner.initial = false;
            }
            if (terminal) {
              flushRef.current?.();
              while (
                !signal.aborted &&
                persistedAfter.current < snapshot.event_cursor
              ) {
                const before = persistedAfter.current;
                const tail = await retryRunRead(
                  () => loadEvents(before, true, signal),
                  signal,
                  (caught) => setError(errorMessage(caught)),
                );
                observeHistory(tail);
                if (persistedAfter.current <= before)
                  throw new Error(
                    "Relay could not finish loading the run's saved output.",
                  );
              }
            }
            if (!queue.accept(snapshot.state_cursor, signal)) continue;
            const complete: RunDetail = {
              ...snapshot.run,
              nodes: snapshot.nodes,
              interactions: snapshot.interactions,
              event_cursor: snapshot.event_cursor,
              state_cursor: snapshot.state_cursor,
            };
            setDetail(complete);
            setNodeCursor(snapshot.nodes_next);
            setInteractionCursor(snapshot.interactions_next);
            setLinkedRequest(snapshot.linked_interaction);
            setError(null);
            if (streamComplete.current && !terminal)
              setStreamEpoch((value) => value + 1);
            streamComplete.current = terminal;
            if (terminal) {
              flushRef.current?.();
              sourceRef.current?.close();
              sourceRef.current = null;
              setStreamState("complete");
            }
            setStreamRun(selectedRun);
            return complete;
          }
          if (!signal.aborted) throw new SnapshotChangedError();
          return null;
        } finally {
          if (queue.clock.inFlight) queue.clock = finishRead(queue.clock, null);
        }
      });
    } catch (caught) {
      if (!isAborted(caught) && currentRun.current === selectedRun)
        setError(errorMessage(caught));
      return null;
    }
  }, [loadArtifacts, loadEvents, selectedRun]);

  const refresh = useCallback(async () => {
    const owner = queueOwner.current;
    if (owner?.id !== selectedRun) return null;
    owner.queue.invalidate();
    const run = await requestMonitor();
    void loadArtifacts(0, "refresh").catch((caught: unknown) => {
      if (!isAborted(caught)) setError(errorMessage(caught));
    });
    return run;
  }, [loadArtifacts, requestMonitor, selectedRun]);

  useEffect(() => {
    linkedId.current = selectedInteraction;
    void requestMonitor();
  }, [selectedInteraction, requestMonitor]);

  useEffect(() => {
    if (selectedRun) return;
    void loadHistory().catch((caught: unknown) =>
      setError(errorMessage(caught)),
    );
  }, [loadHistory, selectedRun]);

  useEffect(() => {
    currentRun.current = selectedRun;
    eventAfter.current = 0;
    persistedAfter.current = 0;
    artifactAfter.current = 0;
    streamComplete.current = false;
    targets.current = { nodes: 200, interactions: 200 };
    setStreamRun(null);
    setStreamState("connecting");
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
    if (!selectedRun) {
      queueOwner.current = null;
      setReadQueue(null);
      return;
    }
    const queue = new RunReadQueue(() => {
      void requestMonitor();
    });
    queueOwner.current = { id: selectedRun, queue, initial: true };
    setReadQueue(queue);
    void requestMonitor();
    void loadArtifacts(0, "replace").catch((caught: unknown) => {
      if (!isAborted(caught) && currentRun.current === selectedRun)
        setError(errorMessage(caught));
    });
    return () => queue.close();
  }, [loadArtifacts, requestMonitor, selectedRun]);

  useEffect(() => {
    if (
      !selectedRun ||
      streamRun !== selectedRun ||
      queueOwner.current?.id !== selectedRun ||
      streamComplete.current
    )
      return;
    const queue = queueOwner.current.queue;
    const source = new EventSource(
      `/api/runs/${encodeURIComponent(selectedRun)}/stream?since=${eventAfter.current}`,
    );
    sourceRef.current = source;
    let incoming: RunEvent[] = [];
    let frame: number | null = null;
    let disposed = false;
    let connected = false;
    const flush = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      const batch = incoming;
      incoming = [];
      if (batch.length && currentRun.current === selectedRun)
        setEvents((current) => mergeEvents(current, batch));
    };
    flushRef.current = flush;
    setStreamState("connecting");
    source.onopen = () => {
      setStreamState("live");
      // The first connection replays from the accepted history cursor.
      // Reconnects must also recover state when their event tail is missing.
      if (connected) void requestMonitor();
      connected = true;
    };
    const receive = (event: Event) => {
      if (disposed) return;
      if (!(event instanceof MessageEvent)) {
        flush();
        setStreamState("reconnecting");
        void requestMonitor();
        return;
      }
      try {
        const item = JSON.parse(event.data) as RunEvent;
        if (item.version !== 1) return;
        eventAfter.current = Math.max(eventAfter.current, item.id);
        incoming.push(item);
        if (frame === null) frame = requestAnimationFrame(flush);
        if (queue.observe(item)) {
          attentionChanged();
          void requestMonitor();
        }
        if (item.type === "artifact.preserved") {
          artifactAfter.current = Math.max(artifactAfter.current, item.id);
          void loadArtifacts(0, "refresh").catch((caught: unknown) => {
            if (!isAborted(caught)) setError(errorMessage(caught));
          });
        }
      } catch {
        setError("Relay received an invalid event frame.");
      }
    };
    for (const type of EVENT_TYPES) source.addEventListener(type, receive);
    source.addEventListener("error", receive);
    return () => {
      disposed = true;
      flush();
      source.close();
      if (sourceRef.current === source) sourceRef.current = null;
      if (flushRef.current === flush) flushRef.current = null;
    };
  }, [loadArtifacts, requestMonitor, selectedRun, streamEpoch, streamRun]);

  async function configureRecovery(enabled: boolean) {
    if (selectedRun === null) return;
    setRecoveryBusy(true);
    try {
      await api(`/api/runs/${encodeURIComponent(selectedRun)}/recovery`, {
        method: "POST",
        body: JSON.stringify({ enabled, idempotency_key: crypto.randomUUID() }),
      });
      await refresh();
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
        method: "POST",
        body: JSON.stringify({ paused, idempotency_key: crypto.randomUUID() }),
      });
      await Promise.all([refresh(), loadHistory()]);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPauseBusy(false);
    }
  }

  async function savePendingSettings(
    scopePath: string,
    options: RetryOptions = {},
  ) {
    if (selectedRun === null) return;
    await api(`/api/runs/${encodeURIComponent(selectedRun)}/step-settings`, {
      method: "POST",
      body: JSON.stringify({
        scope_path: scopePath,
        idempotency_key: crypto.randomUUID(),
        ...options,
      }),
    });
    await refresh();
  }

  async function cancelRun() {
    if (selectedRun === null) return;
    try {
      await api<ReadResponse3>(
        `/api/runs/${encodeURIComponent(selectedRun)}/cancel`,
        {
          method: "POST",
          body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
        },
      );
      await refresh();
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
      const source = await api<PreviousRunInputs>(
        `/api/runs/${encodeURIComponent(selectedRun)}/launch-inputs`,
        { signal: controller.signal },
      );
      const [document, agents] = await Promise.all([
        api<WorkflowDocumentResponse>(
          projectPath(
            `/api/workflows/${source.workflow_key.split("/").map(encodeURIComponent).join("/")}`,
            source.project_id,
          ),
          { signal: controller.signal },
        ),
        api<AgentsResponse>("/api/agents", { signal: controller.signal }).catch(
          () => null,
        ),
      ]);
      if (controller.signal.aborted) return;
      const actions = parseActions(document.yaml);
      if (!actions.value)
        throw new Error(
          `Fix the saved workflow before starting a new run. ${actions.errors.join(" ")}`,
        );
      const environments = await api<ReadResponse4>(
        projectPath("/api/workflow-environments", source.project_id),
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setRunAgain({
        source,
        workflow: launchView(
          actions.value,
          environments.environments.map((item) => item.name),
        )!,
        open: true,
        models: Array.from(
          new Set(
            agents?.agents.flatMap((agent) =>
              agent.models.map((model) => model.value),
            ) ?? [],
          ),
        ).sort(),
      });
    } catch (caught) {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    } finally {
      if (relaunchRequest.current === controller) {
        relaunchRequest.current = null;
        setRelaunchBusy(false);
      }
    }
  }

  async function rerunNode(scopePath: string, options: RetryOptions = {}) {
    if (selectedRun === null) return;
    try {
      await api<ReadResponse5>(
        `/api/runs/${encodeURIComponent(selectedRun)}/rerun-node`,
        {
          method: "POST",
          body: JSON.stringify({
            scope_path: scopePath,
            idempotency_key: crypto.randomUUID(),
            ...options,
          }),
        },
      );
      setStreamEpoch((value) => value + 1);
      await refresh();
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
      await Promise.all([loadHistory(), refresh()]);
      const history = await loadEvents(eventAfter.current);
      for (const event of history) queueOwner.current?.queue.observe(event);
      await requestMonitor();
      // Another owner client may have retried after this terminal stream closed.
      // Reopen from the retained cursor so its new attempt updates remain visible.
      if (selectedRun !== null) {
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
    if (scopePath === selectedJob)
      jobContent.current?.scrollIntoView({ block: "start" });
  }

  async function loadMoreNodes() {
    if (nodeCursor === null) return;
    try {
      targets.current.nodes += 200;
      await requestMonitor();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function loadMoreInteractions() {
    if (interactionCursor === null) return;
    try {
      targets.current.interactions += 200;
      await requestMonitor();
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

  /** Append the remaining artifact pages, bounded to 20 requests. */
  async function loadAllArtifacts() {
    let cursor: number | null | undefined = artifactCursor;
    try {
      for (let page = 0; page < 20 && typeof cursor === "number"; page += 1)
        cursor = await loadArtifacts(cursor, "append");
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  const now = useClock(Boolean(detail && !TERMINAL_RUNS.has(detail.status)));
  const graph = useMemo(
    () => runSummaryGraph(detail?.nodes ?? [], now),
    [detail?.nodes, now],
  );
  const visibleStages = useMemo(() => runJobs(detail?.nodes ?? []), [detail]);
  const pendingInteractions = Array.from(
    new Map(
      [
        ...(detail?.interactions ?? []),
        ...(linkedRequest ? [linkedRequest] : []),
      ]
        .filter(
          (item) => item.status === "pending" && item.respondable !== false,
        )
        .map((item) => [item.id, item]),
    ).values(),
  );
  const currentStages = visibleStages.filter((node) =>
    ["waiting", "running", "failed"].includes(node.status),
  );
  const focusStage =
    selectedStage ??
    pendingInteractions[0]?.scope_path ??
    currentStages[0]?.scope_path;
  const canPause = detail !== null && PAUSABLE_RUNS.has(detail.status);
  const dispatchPaused = canPause && detail.dispatch_paused;
  const pendingChoices = usePendingChoices(
    detail?.id ?? null,
    detail?.project_id ?? project.id,
    dispatchPaused,
    detail?.nodes.flatMap((node) =>
      node.pending_settings ? [node.pending_settings] : [],
    ) ?? [],
  );
  useEffect(() => {
    setPendingSettings(null);
  }, [selectedRun, dispatchPaused]);
  const recovery = detail?.recovery?.current;
  const recoveryPending = PENDING_RECOVERY.has(recovery?.state ?? "");
  const recovering =
    recovery?.state === "resumed" &&
    detail?.status === "running" &&
    detail.nodes.some(
      (node) =>
        node.scope_path === recovery.scope_path &&
        ["ready", "dispatched", "running", "waiting"].includes(node.status),
    );
  const summaryMessage = pendingInteractions.length
    ? "Choose Respond above to continue this job."
    : recoveryPending
      ? "Preparing retry. Relay is preserving reports and waiting for active work to stop."
      : recovering
        ? `Retrying step · ${recovery?.retry_number} of ${detail?.recovery.max_retries}.`
        : detail?.status === "failed" &&
            detail.problem?.retry?.state === "scheduled"
          ? "Relay is waiting for the provider's reset. It will retry automatically."
          : detail?.status === "failed"
            ? detail.nodes.some((node) => node.status === "failed")
              ? "Select a failed job to inspect its logs and retry settings."
              : "The run could not merge or remove its working copy. See the error below."
            : detail?.status === "succeeded"
              ? "Work is complete. Review the saved documents and code changes below."
              : detail?.status === "canceled"
                ? "Work stopped. Finished jobs and their changes remain available for review."
                : detail?.status === "canceling"
                  ? "Relay is stopping active tools and preserving their results."
                  : detail?.status === "interrupted"
                    ? "This run was interrupted. Saved logs remain available."
                    : "Updates are live. Select a job to follow its output.";

  return {
    detail,
    onSelectRun,
    onRunWorkflow,
    pauseBusy,
    relaunchBusy,
    refreshing,
    configurePause,
    setStopOpen,
    rerunAll,
    setGraphJobs,
    relaunchButton,
    refreshRuns,
    setFullTitle,
    fullTitle,
    dispatchPaused,
    pendingSettings,
    setPendingSettings,
    savePendingSettings,
    runAgain,
    project,
    setRunAgain,
    retrySettings,
    setRetrySettings,
    rerunNode,
    error,
    setError,
    workflowFileOpen,
    setWorkflowFileOpen,
    onEditWorkflow,
    selectedRun,
    runs,
    historyLoading,
    waitingRuns,
    runCursor,
    loadHistory,
    filters,
    setLocalFilters,
    onSelectWorkflow,
    selectedJob,
    nodeCursor,
    showStep,
    onSelectJob,
    loadMoreNodes,
    pendingChoices,
    setShowArtifacts,
    jobContent,
    events,
    pendingInteractions,
    artifacts,
    selectedInteraction,
    interactionCursor,
    loadMoreInteractions,
    refreshDetail: refresh,
    readQueue,
    now,
    summaryMessage,
    linkedRequest,
    stepProgress,
    visibleStages,
    graph,
    focusStage,
    cancelRun,
    panels,
    setPanel,
    recoveryBusy,
    configureRecovery,
    recovery,
    artifactCursor,
    loadMoreArtifacts,
    loadAllArtifacts,
    eventCursor,
    loadEvents,
    streamState,
    graphJobs,
    stopOpen,
  };
}
export type RunWorkspaceState = ReturnType<typeof useRunWorkspace>;
