import { expect, test } from "@playwright/test";
import {
  acceptsSnapshot,
  finishRead,
  idleMonitor,
  noteEvent,
  requestRead,
  RunReadQueue,
  SnapshotChangedError,
  startRead,
  wantsRead,
} from "../src/run-monitor";
import type { RunEvent } from "../src/types";

function permutations<T>(values: T[]): T[][] {
  return values.length
    ? values.flatMap((value, index) =>
        permutations(values.filter((_, i) => i !== index)).map((rest) => [
          value,
          ...rest,
        ]),
      )
    : [[]];
}

test("all read and event interleavings reject stale snapshots and schedule the next read", () => {
  for (let cursor = 0; cursor <= 3; cursor += 1) {
    for (const ordering of permutations(["start", "end", "1", "2", "3"])) {
      if (ordering.indexOf("end") < ordering.indexOf("start")) continue;
      let clock = { ...idleMonitor };
      for (const action of ordering) {
        if (action === "start") {
          expect(wantsRead(clock)).toBe(true);
          clock = startRead(clock);
          expect(wantsRead(clock)).toBe(false);
        } else if (action === "end") {
          const fresh = acceptsSnapshot(clock, cursor);
          clock = finishRead(clock, cursor);
          if (!fresh) expect(clock.version).toBe(-1);
        } else clock = noteEvent(clock, Number(action), "wait.answered");
        if (!clock.inFlight && clock.seen > clock.version)
          expect(wantsRead(clock)).toBe(true);
      }
      expect(clock.inFlight).toBe(false);
      if (clock.seen > clock.version) expect(wantsRead(clock)).toBe(true);
    }
  }
});

test("output cannot starve snapshots; owner actions and state events still request reads", () => {
  let clock = finishRead(startRead(idleMonitor), 10);
  for (let id = 11; id < 10_000; id += 1)
    clock = noteEvent(clock, id, "agent.message");
  expect(wantsRead(clock)).toBe(false);
  expect(acceptsSnapshot(clock, 10)).toBe(true);
  expect(wantsRead(requestRead(clock))).toBe(true);
  expect(wantsRead(noteEvent(clock, 10_000, "agent.usage_limit"))).toBe(true);
  expect(acceptsSnapshot(clock, 9)).toBe(false);
});

test("monitor and job tasks share one serial queue and repeated refreshes coalesce", async () => {
  const queue = new RunReadQueue();
  const trace: string[] = [];
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const first = queue.enqueue("monitor", async () => {
    trace.push("monitor started");
    await gate;
    trace.push("monitor ended");
  });
  const duplicate = queue.enqueue("monitor", async () => {
    throw new Error("duplicate read");
  });
  const job = queue.enqueue("job", async () => {
    trace.push("job");
  });
  await Promise.resolve();
  expect(first).toBe(duplicate);
  expect(trace).toEqual(["monitor started"]);
  release();
  await Promise.all([first, job]);
  expect(trace).toEqual(["monitor started", "monitor ended", "job"]);
});

test("an owner action or run change prevents a late response from being accepted", async () => {
  for (const action of ["owner", "selection"]) {
    const queue = new RunReadQueue();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const read = queue.enqueue("monitor", async (signal) => {
      await gate;
      return queue.accept(1, signal);
    });
    await Promise.resolve();
    if (action === "owner") queue.invalidate();
    else queue.close();
    release();
    expect(await read).toBe(false);
  }
});

test("an observed answer and an accepted newer snapshot both reject a late response", async () => {
  const queue = new RunReadQueue();
  const signal = new AbortController().signal;
  queue.observe({ id: 20, type: "wait.answered" } as RunEvent);
  expect(queue.accept(19, signal)).toBe(false);
  expect(queue.accept(20, signal)).toBe(true);
  expect(queue.accept(19, signal)).toBe(false);
});

test("loaded monitor pages beyond 1,000 records rebuild at one state version", async () => {
  const { readMonitorPages } = await import("../src/run-monitor");
  const queue = new RunReadQueue();
  const signal = new AbortController().signal;
  const calls: number[] = [];
  let changed = false;
  const value = await readMonitorPages(
    queue,
    async (since) => {
      calls.push(since);
      if (since === 200 && !changed) changed = true;
      const rows = Array.from(
        { length: Math.min(200, 1006 - since) },
        (_, offset) => ({
          id: since + offset + 1,
          status: changed ? "succeeded" : "waiting",
        }),
      );
      return {
        run: { id: "run", status: "running" },
        nodes: rows,
        interactions: [],
        nodes_next: since + rows.length < 1006 ? since + rows.length : null,
        interactions_next: null,
        linked_interaction: null,
        state_cursor: changed ? 2 : 1,
        event_cursor: 10_000 + since,
      } as unknown as import("../src/run-monitor").MonitorPage;
    },
    () => ({ nodes: 1200, interactions: 200, linkedId: null }),
    signal,
  );
  expect(calls).toEqual([0, 200, 0, 200, 400, 600, 800, 1000]);
  expect(value.nodes).toHaveLength(1006);
  expect(value.nodes.every((node) => node.status === "succeeded")).toBe(true);
  expect(value.state_cursor).toBe(2);
  expect(value.nodes_next).toBeNull();
});

test("job pages never publish attempts from different snapshots", async () => {
  const { readJobPages } = await import("../src/run-monitor");
  let refreshes = 0;
  const queue = new RunReadQueue(() => {
    refreshes += 1;
  });
  const signal = new AbortController().signal;
  queue.accept(1, signal);
  let changed = false;
  const cursors: number[] = [];
  const value = await readJobPages(
    queue,
    async (since) => {
      cursors.push(since);
      if (since === 200 && !changed) changed = true;
      return {
        job: {
          attempts: Array.from({ length: 200 }, (_, i) => ({
            number: since + i + 1,
            status: changed ? "terminal" : "running",
          })),
          state_cursor: changed ? 2 : 1,
          event_cursor: changed ? 9 : 8,
        },
        next: since === 0 ? 200 : null,
      } as unknown as import("../src/run-monitor").JobStatePage;
    },
    () => 400,
    signal,
  );
  expect(cursors).toEqual([0, 200, 0, 200]);
  expect(value.job.attempts).toHaveLength(400);
  expect(
    value.job.attempts.every((attempt) => attempt.status === "terminal"),
  ).toBe(true);
  expect(refreshes).toBe(1);
  expect(queue.accepts(1, signal)).toBe(false);
  expect(wantsRead(queue.clock)).toBe(true);
});

for (const kind of ["monitor", "job"] as const)
  test(`continuously changing ${kind} pages release the serial queue`, async () => {
    const { readMonitorPages, readJobPages } =
      await import("../src/run-monitor");
    const queue = new RunReadQueue();
    const controller = new AbortController();
    let calls = 0;
    let changing = true;
    const page = async (since: number) => {
      calls += 1;
      // Stop a broken implementation deterministically, without a test timeout.
      if (calls > 12 && changing) controller.abort();
      const cursor = changing ? calls : 100;
      return {
        run: { id: "run", status: "running" },
        nodes: [{ id: since + 1 }],
        interactions: [],
        nodes_next: since === 0 ? 200 : null,
        interactions_next: null,
        linked_interaction: null,
        state_cursor: cursor,
        event_cursor: cursor,
        job: { attempts: [{ number: since + 1 }], state_cursor: cursor },
        next: since === 0 ? 200 : null,
      };
    };
    const read = async (signal: AbortSignal) =>
      kind === "monitor"
        ? readMonitorPages(
            queue,
            page as unknown as Parameters<typeof readMonitorPages>[1],
            () => ({ nodes: 400, interactions: 200, linkedId: null }),
            signal,
          )
        : readJobPages(
            queue,
            page as unknown as Parameters<typeof readJobPages>[1],
            () => 400,
            signal,
          );
    const unstable = queue.enqueue("unstable", read, controller.signal);
    const other = queue.enqueue("other", async () => "queue progressed");
    await expect(unstable).rejects.toMatchObject({
      name: "SnapshotChangedError",
    });
    expect(await other).toBe("queue progressed");
    expect(calls).toBeLessThanOrEqual(12);
    changing = false;
    expect(await queue.enqueue("stable", read)).toBeTruthy();
  });

test("rebuild backoff lets an open job read progress before the next monitor attempt", async () => {
  const queue = new RunReadQueue();
  const trace: string[] = [];
  const monitor = queue.read("monitor", async () => {
    trace.push("monitor");
    if (trace.length === 1) throw new SnapshotChangedError();
    return "coherent monitor";
  });
  const job = queue.read("job", async () => {
    trace.push("job");
    return "coherent job";
  });
  expect(await job).toBe("coherent job");
  expect(trace).toEqual(["monitor", "job"]);
  const duplicate = queue.read("monitor", async () => {
    throw new Error("A refresh during backoff must reuse the pending rebuild.");
  });
  expect(duplicate).toBe(monitor);
  expect(await monitor).toBe("coherent monitor");
  expect(trace).toEqual(["monitor", "job", "monitor"]);
});

test("rebuild retries stop after their bounded backoff", async () => {
  const queue = new RunReadQueue();
  let calls = 0;
  await expect(
    queue.read("monitor", async () => {
      calls += 1;
      throw new SnapshotChangedError();
    }),
  ).rejects.toBeInstanceOf(SnapshotChangedError);
  expect(calls).toBe(4);
});

for (const action of ["owner", "selection", "job closed"])
  test(`${action} cancels a rebuild during backoff`, async () => {
    const queue = new RunReadQueue();
    const caller = new AbortController();
    let calls = 0;
    const monitor = queue.read(
      "monitor",
      async () => {
        calls += 1;
        throw new SnapshotChangedError();
      },
      caller.signal,
    );
    // A following queue task only starts once the failed read yields for backoff.
    await queue.enqueue("other", async () => undefined);
    if (action === "owner") queue.invalidate();
    else if (action === "selection") queue.close();
    else caller.abort();
    await expect(monitor).rejects.toMatchObject({ name: "AbortError" });
    expect(calls).toBe(1);
  });

test("invalidating owner reads cancels queued job work too", async () => {
  const queue = new RunReadQueue();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const first = queue.enqueue("monitor", async () => {
    await gate;
  });
  const job = queue.enqueue("job", async () => {
    throw new Error("An invalidated job must never start.");
  });
  const rejected = expect(job).rejects.toMatchObject({ name: "AbortError" });
  await Promise.resolve();
  queue.invalidate();
  release();
  await first;
  await rejected;
});

test("failed reads stop after bounded backoff and can be canceled", async () => {
  const { retryRunRead } = await import("../src/run-monitor");
  const controller = new AbortController();
  let tries = 0;
  await expect(
    retryRunRead(
      async () => {
        tries += 1;
        throw new Error("offline");
      },
      controller.signal,
      () => undefined,
    ),
  ).rejects.toThrow("offline");
  expect(tries).toBe(5);
  const canceled = retryRunRead(
    async () => {
      throw new Error("offline");
    },
    controller.signal,
    () => controller.abort(),
  );
  await expect(canceled).rejects.toMatchObject({ name: "AbortError" });
});
