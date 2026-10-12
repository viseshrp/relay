import type {
  RunDetail,
  RunEvent,
  RunInteraction,
  RunJob,
  RunNode,
} from "./types";

export interface MonitorPage {
  run: Omit<RunDetail, "nodes" | "interactions">;
  nodes: RunNode[];
  interactions: RunInteraction[];
  nodes_next: number | null;
  interactions_next: number | null;
  linked_interaction: RunInteraction | null;
  event_cursor: number;
  state_cursor: number;
}

export const OUTPUT_EVENT_TYPES = new Set([
  "agent.message",
  "agent.thought",
  "agent.tool_call",
  "agent.tool_result",
  "agent.plan",
  "agent.provider_event",
  "agent.stderr",
  "agent.result",
  "agent.turn_started",
  "command.stdout",
  "command.stderr",
  "actions.summary",
  "actions.error",
  "actions.warning",
  "actions.notice",
  "actions.debug",
  "actions.group",
  "actions.endgroup",
]);

export interface MonitorClock {
  version: number;
  seen: number;
  inFlight: boolean;
  again: boolean;
}
export const idleMonitor: MonitorClock = {
  version: -1,
  seen: 0,
  inFlight: false,
  again: true,
};
export function noteEvent(
  c: MonitorClock,
  id: number,
  type: string,
): MonitorClock {
  return OUTPUT_EVENT_TYPES.has(type)
    ? c
    : { ...c, seen: Math.max(c.seen, id) };
}
export function requestRead(c: MonitorClock): MonitorClock {
  return { ...c, again: true };
}
export function wantsRead(c: MonitorClock): boolean {
  return !c.inFlight && (c.again || c.seen > c.version);
}
export function startRead(c: MonitorClock): MonitorClock {
  return { ...c, inFlight: true, again: false };
}
export function acceptsSnapshot(c: MonitorClock, cursor: number): boolean {
  return cursor >= c.seen && cursor >= c.version;
}
export function finishRead(
  c: MonitorClock,
  cursor: number | null,
): MonitorClock {
  const accepted = cursor !== null && acceptsSnapshot(c, cursor);
  return {
    ...c,
    inFlight: false,
    version: accepted ? cursor : c.version,
    again: c.again || !accepted,
  };
}

function aborted(): DOMException {
  return new DOMException("The run read was canceled.", "AbortError");
}
export function isAborted(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
export function waitForReadRetry(
  ms: number,
  signal: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(aborted());
    const stop = () => {
      clearTimeout(timer);
      reject(aborted());
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", stop);
      resolve();
    }, ms);
    signal.addEventListener("abort", stop, { once: true });
  });
}

export async function retryRunRead<T>(
  read: () => Promise<T>,
  signal: AbortSignal,
  failed: (error: unknown) => void,
): Promise<T> {
  const backoff = [500, 1000, 2000, 5000];
  for (let attempt = 0; ; attempt += 1) {
    if (signal.aborted) throw aborted();
    try {
      return await read();
    } catch (error) {
      if (signal.aborted || isAborted(error)) throw aborted();
      failed(error);
      const status =
        typeof error === "object" && error !== null && "status" in error
          ? Number(error.status)
          : 0;
      if (attempt >= backoff.length || (status >= 400 && status < 500))
        throw error;
      await waitForReadRetry(backoff[attempt], signal);
    }
  }
}

/** Rebuild every loaded page, publishing only one coherent state version. */
export async function readMonitorPages(
  queue: RunReadQueue,
  page: (
    nodesSince: number,
    interactionsSince: number,
    linkedId: string | null,
  ) => Promise<MonitorPage>,
  targets: () => {
    nodes: number;
    interactions: number;
    linkedId: string | null;
  },
  signal: AbortSignal,
): Promise<MonitorPage> {
  while (!signal.aborted) {
    let nodesSince = 0,
      interactionsSince = 0;
    let nodes: RunNode[] = [],
      interactions: RunInteraction[] = [];
    let nodesNext: number | null = null,
      interactionsNext: number | null = null;
    let readNodes = true,
      readInteractions = true;
    const linkedId = targets().linkedId;
    let version: number | null = null;
    while (!signal.aborted) {
      const value = await page(nodesSince, interactionsSince, linkedId);
      version ??= value.state_cursor;
      if (
        value.state_cursor !== version ||
        !queue.accepts(version, signal) ||
        targets().linkedId !== linkedId
      )
        break;
      if (readNodes) {
        nodes = nodes.concat(value.nodes);
        nodesNext = value.nodes_next;
      }
      if (readInteractions) {
        interactions = interactions.concat(value.interactions);
        interactionsNext = value.interactions_next;
      }
      readNodes = nodesNext !== null && nodes.length < targets().nodes;
      readInteractions =
        interactionsNext !== null &&
        interactions.length < targets().interactions;
      if (!readNodes && !readInteractions)
        return {
          ...value,
          nodes,
          interactions,
          nodes_next: nodesNext,
          interactions_next: interactionsNext,
        };
      if (readNodes) {
        if (nodesNext! <= nodesSince)
          throw new Error("Node pages did not advance.");
        nodesSince = nodesNext!;
      }
      if (readInteractions) {
        if (interactionsNext! <= interactionsSince)
          throw new Error("Request pages did not advance.");
        interactionsSince = interactionsNext!;
      }
    }
    // A run changing between pages restarts from page one, retaining the old view.
    await waitForReadRetry(25, signal);
  }
  throw aborted();
}

/** One queue belongs to a selected run, including every open job's state reads. */
export class RunReadQueue {
  clock: MonitorClock = { ...idleMonitor };
  private tail: Promise<unknown> = Promise.resolve();
  private pending = new Map<
    string,
    {
      promise: Promise<unknown>;
      caller?: AbortSignal;
      controller: AbortController;
    }
  >();
  private active: AbortController | null = null;
  private closed = false;

  constructor(private readonly refreshMonitor: () => void = () => undefined) {}

  observe(event: RunEvent): boolean {
    this.clock = noteEvent(this.clock, event.id, event.type);
    return wantsRead(this.clock);
  }
  accepts(cursor: number, signal: AbortSignal): boolean {
    return (
      !this.closed && !signal.aborted && acceptsSnapshot(this.clock, cursor)
    );
  }
  accept(cursor: number, signal: AbortSignal): boolean {
    if (!this.accepts(cursor, signal)) return false;
    this.clock = finishRead(this.clock, cursor);
    return true;
  }
  acceptJob(cursor: number, signal: AbortSignal): boolean {
    if (!this.accepts(cursor, signal)) return false;
    // A job snapshot proves the run has reached this state too. Refresh the
    // monitor without pretending its visible collections have caught up.
    this.clock = { ...this.clock, seen: Math.max(this.clock.seen, cursor) };
    if (wantsRead(this.clock)) this.refreshMonitor();
    return true;
  }
  invalidate(): void {
    this.clock = requestRead(this.clock);
    this.active?.abort();
    for (const entry of this.pending.values()) entry.controller.abort();
    this.pending.clear();
  }
  close(): void {
    this.closed = true;
    this.invalidate();
  }
  enqueue<T>(
    key: string,
    read: (signal: AbortSignal) => Promise<T>,
    caller?: AbortSignal,
  ): Promise<T> {
    if (this.closed || caller?.aborted) return Promise.reject(aborted());
    const existing = this.pending.get(key);
    if (existing && !existing.caller?.aborted)
      return existing.promise as Promise<T>;
    const controller = new AbortController();
    const promise = this.tail.then(async () => {
      if (this.closed || caller?.aborted || controller.signal.aborted)
        throw aborted();
      const stop = () => controller.abort();
      caller?.addEventListener("abort", stop, { once: true });
      this.active = controller;
      try {
        return await read(controller.signal);
      } finally {
        caller?.removeEventListener("abort", stop);
        if (this.active === controller) this.active = null;
      }
    });
    this.pending.set(key, { promise, caller, controller });
    this.tail = promise.catch(() => undefined);
    void promise
      .finally(() => {
        if (this.pending.get(key)?.promise === promise)
          this.pending.delete(key);
      })
      .catch(() => undefined);
    return promise;
  }
}

export interface JobStatePage {
  job: RunJob;
  next: number | null;
}

/** Refresh the whole loaded attempt prefix before publishing a job. */
export async function readJobPages(
  queue: RunReadQueue,
  page: (since: number) => Promise<JobStatePage>,
  target: () => number,
  signal: AbortSignal,
): Promise<JobStatePage> {
  while (!signal.aborted) {
    let since = 0;
    let attempts: RunJob["attempts"] = [];
    let version: number | null = null;
    while (!signal.aborted) {
      const value = await page(since);
      version ??= value.job.state_cursor;
      if (value.job.state_cursor !== version || !queue.accepts(version, signal))
        break;
      attempts = attempts.concat(value.job.attempts);
      if (value.next === null || attempts.length >= target()) {
        if (queue.acceptJob(version, signal))
          return { ...value, job: { ...value.job, attempts } };
        break;
      }
      if (value.next <= since)
        throw new Error("Attempt pages did not advance.");
      since = value.next;
    }
    await waitForReadRetry(25, signal);
  }
  throw aborted();
}
