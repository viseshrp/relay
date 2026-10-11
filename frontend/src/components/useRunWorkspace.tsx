import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDisclosureState } from "../view-state";
import { runJobs } from "../job-list";

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
  PreviousRunInputs,
  RetryConfiguration,
  RetryOptions,
} from "../types";
import { repairOwnership, visibleRunStages } from "../graph";
import { projectPath } from "../navigation";
import { parseWorkflow, type WorkflowValue } from "../workflow";
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
  DetailCollection,
  PageMode,
  RunDetailPage,
  ArtifactPage,
  mergeEvents,
  mergeRecords,
  applyStateEvent,
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
    workflow: WorkflowValue;
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

  const loadDetailCollection = useCallback(
    async (
      collection: DetailCollection,
      since: number,
      mode: PageMode,
      publish = true,
    ): Promise<RunDetail> => {
      if (selectedRun === null)
        throw new Error("Select a run before loading its detail.");
      const query = new URLSearchParams({
        collection,
        since: String(since),
        limit: "200",
      });
      if (collection === "interactions") query.set("pending", "true");
      const response = await api<RunDetailPage>(
        `/api/runs/${encodeURIComponent(selectedRun)}?${query.toString()}`,
      );
      if (currentRun.current !== selectedRun) return response.run;
      if (publish)
        setDetail((current) => {
          const sameRun = current?.id === response.run.id;
          const currentNodes = sameRun ? current.nodes : [];
          const currentInteractions = sameRun ? current.interactions : [];
          return {
            ...response.run,
            nodes:
              collection === "nodes"
                ? mode === "replace"
                  ? response.run.nodes
                  : mergeRecords(currentNodes, response.run.nodes)
                : currentNodes,
            interactions:
              collection === "interactions"
                ? mode !== "append"
                  ? response.run.interactions
                  : mergeRecords(currentInteractions, response.run.interactions)
                : currentInteractions,
          };
        });
      if (collection === "nodes") setNodeCursor(response.next);
      else setInteractionCursor(response.next);
      return response.run;
    },
    [selectedRun],
  );

  const loadArtifacts = useCallback(
    async (since: number, mode: PageMode): Promise<void> => {
      if (selectedRun === null) return;
      const query = new URLSearchParams({
        since: String(since),
        limit: "50",
        visible: "true",
      });
      const response = await api<ArtifactPage>(
        `/api/runs/${encodeURIComponent(selectedRun)}/artifacts?${query.toString()}`,
      );
      if (currentRun.current !== selectedRun) return;
      setArtifacts((current) =>
        mode === "replace"
          ? response.artifacts
          : mergeRecords(current, response.artifacts),
      );
      setArtifactCursor(response.next);
    },
    [selectedRun],
  );

  const loadLinkedRequest = useCallback(async () => {
    if (!selectedRun || !selectedInteraction) {
      setLinkedRequest(null);
      return;
    }
    const response = await api<RunDetailPage>(
      `/api/runs/${selectedRun}?collection=interactions&interaction=${encodeURIComponent(selectedInteraction)}&limit=1`,
    );
    if (currentRun.current === selectedRun)
      setLinkedRequest(response.run.interactions[0] ?? null);
  }, [selectedRun, selectedInteraction]);

  const refreshDetail = useCallback(
    async (reset = false, publish = true): Promise<RunDetail | null> => {
      if (selectedRun === null) return null;
      const mode: PageMode = reset ? "replace" : "refresh";
      const [run, interactions] = await Promise.all([
        loadDetailCollection("nodes", 0, mode, !reset),
        loadDetailCollection("interactions", 0, mode, !reset),
        loadArtifacts(0, mode),
        loadLinkedRequest(),
      ]);
      const complete = { ...run, interactions: interactions.interactions };
      if (reset && currentRun.current === selectedRun) {
        if (publish) setDetail(complete);
        stateAfter.current = Math.min(
          run.event_cursor ?? 0,
          interactions.event_cursor ?? 0,
        );
      }
      return complete;
    },
    [loadArtifacts, loadDetailCollection, loadLinkedRequest, selectedRun],
  );

  const applyLiveUpdates = useCallback(
    (batch: RunEvent[]) => {
      // Historical output stays visible; progress starts at the loaded state cursor.
      const live = batch.filter((item) => item.id > stateAfter.current);
      setDetail((current) => live.reduce(applyStateEvent, current));
      if (
        live.some(
          (item) =>
            item.type.startsWith("run.") ||
            item.type.endsWith(".requested") ||
            item.type.endsWith(".answered"),
        )
      )
        attentionChanged();
      const interactionChanged = live.some(
        (item) =>
          item.type === "attempt.ended" ||
          item.type === "attempt.started" ||
          item.type.endsWith(".requested") ||
          item.type.endsWith(".answered"),
      );
      if (
        interactionChanged ||
        live.some(
          (item) =>
            item.type === "node.created" ||
            item.type === "run.dispatch_changed" ||
            item.type === "run.repairs_changed" ||
            item.type === "node.settings_changed" ||
            item.type.startsWith("run.retry_") ||
            item.type.startsWith("run.recovery_"),
        )
      ) {
        void loadDetailCollection("nodes", 0, "refresh").catch(
          (caught: unknown) => setError(errorMessage(caught)),
        );
      }
      if (interactionChanged) {
        void loadDetailCollection("interactions", 0, "refresh").catch(
          (caught: unknown) => setError(errorMessage(caught)),
        );
        void loadLinkedRequest().catch((caught: unknown) =>
          setError(errorMessage(caught)),
        );
      }
      if (live.some((item) => item.type === "artifact.preserved")) {
        void loadArtifacts(0, "refresh").catch((caught: unknown) =>
          setError(errorMessage(caught)),
        );
      }
    },
    [loadArtifacts, loadDetailCollection, loadLinkedRequest],
  );

  const loadEvents = useCallback(
    async (since = 0, full = false) => {
      if (selectedRun === null) return [];
      const summary = summaryOnly.current && !full;
      const response = await api<ReadResponse2>(
        `/api/runs/${encodeURIComponent(selectedRun)}/events?since=${since}&limit=${summary ? 50 : 100}${summary ? "&summary=true" : ""}`,
      );
      if (full) summaryOnly.current = false;
      if (currentRun.current !== selectedRun) return [];
      eventAfter.current = Math.max(
        eventAfter.current,
        response.events.at(-1)?.id ?? 0,
      );
      setEvents((current) =>
        since === 0 ? response.events : mergeEvents(current, response.events),
      );
      setEventCursor(summary && since === 0 ? 0 : response.next);
      return response.events;
    },
    [selectedRun],
  );

  useEffect(() => {
    if (selectedRun) return;
    void loadHistory().catch((caught: unknown) =>
      setError(errorMessage(caught)),
    );
  }, [loadHistory, selectedRun]);

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
    let initialRun: RunDetail | null = null;
    void refreshDetail(true, false)
      .then((run) => {
        initialRun = run;
        summaryOnly.current = Boolean(run && TERMINAL_RUNS.has(run.status));
        return loadEvents();
      })
      .then((history) => {
        if (disposed) return;
        // A step may finish between the state read and the history response.
        // Publish history and state together so job reads start at one revision.
        // Apply new events before the stream starts after their final ID.
        setDetail(initialRun);
        applyLiveUpdates(history);
        setStreamRun(selectedRun);
      })
      .catch((caught: unknown) => {
        if (!disposed) setError(errorMessage(caught));
      });
    return () => {
      disposed = true;
    };
  }, [applyLiveUpdates, loadEvents, refreshDetail, selectedRun]);

  useEffect(() => {
    if (detail === null || detail.id !== selectedRun) return;
    const previous = previousRunStatus.current;
    previousRunStatus.current = detail.status;
    if (
      previous !== null &&
      TERMINAL_RUNS.has(previous) &&
      (!TERMINAL_RUNS.has(detail.status) ||
        (detail.status === "failed" &&
          (detail.problem?.retry?.state === "scheduled" ||
            PENDING_RECOVERY.has(detail.recovery?.current?.state ?? "")))) &&
      streamState === "complete"
    )
      setStreamEpoch((value) => value + 1);
  }, [detail, selectedRun, streamState]);

  const streamActive =
    detail?.id === selectedRun &&
    (!TERMINAL_RUNS.has(detail.status) ||
      detail.problem?.retry?.state === "scheduled" ||
      PENDING_RECOVERY.has(detail.recovery?.current?.state ?? ""));
  useEffect(() => {
    if (selectedRun === null || streamRun !== selectedRun) return;
    if (!streamActive) {
      setStreamState("complete");
      return;
    }
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
          if (
            TERMINAL_RUNS.has(run.status) &&
            run.problem?.retry?.state !== "scheduled" &&
            !PENDING_RECOVERY.has(run.recovery?.current?.state ?? "")
          ) {
            source.close();
            setStreamState("complete");
          }
        })
        .catch((caught: unknown) => {
          if (!disposed) setError(errorMessage(caught));
        })
        .finally(() => {
          completionCheck = null;
        });
    };
    const flush = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      const batch = incoming;
      incoming = [];
      if (batch.length === 0) return;
      setEvents((current) => mergeEvents(current, batch));
      applyLiveUpdates(batch);
      if (
        batch.some(
          (item) =>
            item.id > stateAfter.current &&
            (item.type.startsWith("run.retry_") ||
              item.type.startsWith("run.recovery_") ||
              (item.type.startsWith("run.") &&
                typeof item.payload.status === "string" &&
                TERMINAL_RUNS.has(item.payload.status))),
        )
      )
        checkCompletion();
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
        if (incoming.at(-1)?.id === item.id)
          incoming[incoming.length - 1] = item;
        else incoming.push(item);
        // Publish one ordered batch per paint instead of copying/sorting the
        // growing history for each replayed event.
        if (frame === null) frame = requestAnimationFrame(flush);
        const status = item.payload.status;
        if (
          item.id > stateAfter.current &&
          item.type.startsWith("run.") &&
          typeof status === "string" &&
          TERMINAL_RUNS.has(status)
        ) {
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
  }, [
    applyLiveUpdates,
    loadDetailCollection,
    selectedRun,
    streamEpoch,
    streamRun,
    streamActive,
  ]);

  async function configureRecovery(enabled: boolean) {
    if (selectedRun === null) return;
    setRecoveryBusy(true);
    try {
      await api(`/api/runs/${encodeURIComponent(selectedRun)}/recovery`, {
        method: "POST",
        body: JSON.stringify({ enabled, idempotency_key: crypto.randomUUID() }),
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
        method: "POST",
        body: JSON.stringify({ paused, idempotency_key: crypto.randomUUID() }),
      });
      await Promise.all([refreshDetail(), loadHistory()]);
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
    await refreshDetail();
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
      const parsed = parseWorkflow(document.yaml);
      if (parsed.value === null)
        throw new Error(
          `Fix the saved workflow's YAML before running it again. ${parsed.errors.join(" ")}`,
        );
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
    if (scopePath === selectedJob)
      jobContent.current?.scrollIntoView({ block: "start" });
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
  const graph = useMemo(
    () => runSummaryGraph(detail?.nodes ?? [], now),
    [detail?.nodes, now],
  );
  const visibleStages = useMemo(
    () => visibleRunStages(runJobs(detail?.nodes ?? [])),
    [detail],
  );
  const repairOwners = useMemo(
    () => repairOwnership(detail?.nodes ?? []),
    [detail],
  );
  const repairGroups =
    detail?.nodes.filter((node) => node.repair_for && node.repair_settings) ??
    [];
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
    ["waiting", "running", "failed", "repairing", "repair_stopped"].includes(
      node.status,
    ),
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
    repairOwners,
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
    refreshDetail,
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
    repairGroups,
    repairChildren,
    eventCursor,
    loadEvents,
    streamState,
    graphJobs,
    stopOpen,
  };
}
export type RunWorkspaceState = ReturnType<typeof useRunWorkspace>;
