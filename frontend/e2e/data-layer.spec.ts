import { expect, test, type Response } from "./a11y-test";
import { sharedRead, invalidateReads } from "../src/read-cache";
import { post } from "./setup-helpers";

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function cacheCleanup(): Promise<void> {
  // Cross the cache's task boundary without depending on elapsed wall time.
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
}

test("one abort does not cancel a shared read used by another subscriber", async () => {
  invalidateReads();
  let resolve: (value: string) => void = () => undefined;
  let requests = 0;
  const read = () => {
    requests += 1;
    return new Promise<string>((done) => {
      resolve = done;
    });
  };
  const first = new AbortController();
  const a = sharedRead("same", first.signal, read).catch((error) => error.name);
  const b = sharedRead("same", undefined, read);
  first.abort();
  resolve("result");
  expect(await a).toBe("AbortError");
  expect(await b).toBe("result");
  expect(requests).toBe(1);
});

test("an invalidated read cannot evict its replacement when it finishes late", async () => {
  invalidateReads();
  const stale = deferred<string>();
  const fresh = deferred<string>();
  const other = deferred<string>();
  const before = sharedRead("/api/runs/one", undefined, () => stale.promise);
  const unrelated = sharedRead("/api/projects", undefined, () => other.promise);
  invalidateReads("/api/runs/one");
  let requests = 0;
  const readFresh = () => {
    requests += 1;
    return fresh.promise;
  };
  const after = sharedRead("/api/runs/one", undefined, readFresh);
  stale.resolve("waiting");
  expect(await before).toBe("waiting");
  await cacheCleanup();

  const subscriber = sharedRead("/api/runs/one", undefined, readFresh);
  const otherSubscriber = sharedRead("/api/projects", undefined, () => {
    throw new Error("Invalidating one run must preserve unrelated reads.");
  });
  fresh.resolve("finished");
  other.resolve("project");
  expect(await Promise.all([after, subscriber])).toEqual([
    "finished",
    "finished",
  ]);
  expect(await Promise.all([unrelated, otherSubscriber])).toEqual([
    "project",
    "project",
  ]);
  expect(requests).toBe(1);
});

test("abort cleanup from an invalidated read cannot cancel its replacement", async () => {
  invalidateReads();
  const controller = new AbortController();
  const stale = deferred<string>();
  const fresh = deferred<string>();
  const before = sharedRead("replacement", controller.signal, (signal) => {
    signal.addEventListener("abort", () => stale.resolve("aborted"));
    return stale.promise;
  }).catch((error: Error) => error.name);
  controller.abort();
  invalidateReads("replacement");
  let requests = 0;
  const readFresh = (signal: AbortSignal) => {
    requests += 1;
    signal.addEventListener("abort", () =>
      fresh.resolve("incorrectly aborted"),
    );
    return fresh.promise;
  };
  const after = sharedRead("replacement", undefined, readFresh);
  await cacheCleanup();
  expect(await before).toBe("AbortError");
  expect(await stale.promise).toBe("aborted");

  const subscriber = sharedRead("replacement", undefined, readFresh);
  fresh.resolve("current");
  expect(await Promise.all([after, subscriber])).toEqual([
    "current",
    "current",
  ]);
  expect(requests).toBe(1);
});

test("a replacement subscriber keeps the underlying read alive across an abort", async () => {
  invalidateReads();
  const controller = new AbortController();
  const result = deferred<string>();
  let requests = 0;
  const read = (signal: AbortSignal) => {
    requests += 1;
    signal.addEventListener("abort", () =>
      result.resolve("incorrectly aborted"),
    );
    return result.promise;
  };
  const first = sharedRead("resubscribe", controller.signal, read).catch(
    (error: Error) => error.name,
  );
  controller.abort();
  const second = sharedRead("resubscribe", undefined, read);
  await cacheCleanup();
  result.resolve("retained");

  expect(await first).toBe("AbortError");
  expect(await second).toBe("retained");
  expect(requests).toBe(1);
});

test("a failed shared read does not poison the next refresh", async () => {
  invalidateReads();
  const failed = sharedRead("retry-read", undefined, () =>
    Promise.reject(new Error("temporary read failure")),
  );
  await expect(failed).rejects.toThrow("temporary read failure");
  await cacheCleanup();

  expect(
    await sharedRead("retry-read", undefined, () =>
      Promise.resolve("recovered"),
    ),
  ).toBe("recovered");
});

test("Home reads once under StrictMode and hidden tabs make no polling requests", async ({
  page,
}) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
  let dashboards = 0,
    attention = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/dashboard?limit=10")) dashboards += 1;
    if (request.url().includes("/api/attention")) attention += 1;
  });
  const initial = page.waitForResponse((response) =>
    response.url().includes("/api/dashboard?limit=10"),
  );
  await page.goto("/?view=home");
  await expect(
    page.getByRole("heading", { name: "Your work at a glance" }),
  ).toBeVisible();
  // Hide the tab only after the first read settles and leaves the shared cache.
  await (await initial).finished();
  await expect(page.locator(".dashboard .view-skeleton")).toHaveCount(0);
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)));
  expect(dashboards).toBe(1);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: document.hidden ? "hidden" : "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const before = [dashboards, attention];
  await page.clock.install();
  await page.clock.fastForward(90000);
  expect([dashboards, attention]).toEqual(before);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: document.hidden ? "hidden" : "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => dashboards).toBe(before[0] + 1);
});

test("unchanged visible Home backs off to thirty seconds and refreshes on focus", async ({
  page,
}) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
  // Network completion must not consume any part of a polling deadline.
  await page.clock.install({ time: new Date("2026-01-01T00:00:00Z") });
  await page.clock.pauseAt(new Date("2026-01-02T00:00:00Z"));
  let reads = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/dashboard?limit=10")) reads++;
  });
  const refresh = page.getByRole("button", { name: "Refresh", exact: true });
  const nextDashboard = () =>
    page.waitForResponse((response) =>
      response.url().includes("/api/dashboard?limit=10"),
    );
  async function settleDashboard(pending: Promise<Response>): Promise<void> {
    const response = await pending;
    expect(response.ok()).toBeTruthy();
    await response.finished();
    await expect(page.locator(".dashboard .view-skeleton")).toHaveCount(0);
    await expect(refresh).toBeEnabled();
    // A settled shared read is evicted on the next task, without elapsed time.
    await page.clock.runFor(0);
  }
  const initial = nextDashboard();
  await page.goto("/?view=home");
  await settleDashboard(initial);
  for (let index = 0; index < 12; index++) {
    const before = reads;
    const next = nextDashboard();
    await page.clock.runFor(5000);
    await settleDashboard(next);
    expect(reads).toBe(before + 1);
  }
  const backedOff = reads;
  const next = nextDashboard();
  await page.clock.runFor(29999);
  expect(reads).toBe(backedOff);
  await page.clock.runFor(1);
  await settleDashboard(next);
  expect(reads).toBe(backedOff + 1);
  const beforeFocus = reads;
  const focused = nextDashboard();
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await settleDashboard(focused);
  expect(reads).toBe(beforeFocus + 1);
  await page.clock.resume();
});

test("cached Run workflow opens within 150 ms while launch checks are pending", async ({
  page,
}) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  let release: () => void = () => undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/preflight**", async (route) => {
    await held;
    await route.continue();
  });
  try {
    const elapsed = await page.evaluate(
      () =>
        new Promise<number>((resolve) => {
          const start = performance.now();
          const observer = new MutationObserver(() => {
            const dialog = document.querySelector('[role="dialog"]');
            if (dialog?.textContent?.includes("Run workflow")) {
              observer.disconnect();
              resolve(performance.now() - start);
            }
          });
          observer.observe(document.body, { childList: true, subtree: true });
          const button = [
            ...document.querySelectorAll<HTMLButtonElement>("button"),
          ].find((item) => item.textContent === "Run workflow");
          button?.click();
        }),
    );
    expect(elapsed).toBeLessThan(150);
    await expect(
      page.getByRole("dialog", { name: "Run workflow" }),
    ).toBeVisible();
  } finally {
    release();
  }
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Run workflow" })).toHaveCount(
    0,
  );
});

test("each page loads each initial resource once", async ({ page }) => {
  await page.request.get("/api/auth");
  expect(
    (
      await post(page, "/api/auth/login", {
        username: "owner",
        password: "Relay-Test-Passphrase-2026!",
      })
    ).ok(),
  ).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  const response = await post(page, "/__test__/worst-case", { enabled: false });
  expect(response.ok()).toBeTruthy();
  const fixture = await response.json();
  const routes = [
    ["Home", `/?view=home&project=${fixture.project}`, "Your projects"],
    ["Runs", `/?view=runs&project=${fixture.project}`, "All runs"],
    [
      "finished run",
      `/?view=runs&project=${fixture.project}&run=${fixture.run}`,
      "Step progress",
    ],
    [
      "running run",
      `/?view=runs&project=${fixture.project}&run=${fixture.running}`,
      "Step progress",
    ],
    [
      "job",
      `/?view=runs&project=${fixture.project}&run=${fixture.run}&job=${fixture.job}`,
      "Job log",
    ],
  ];
  for (const [label, url, ready] of routes) {
    const counts = new Map<string, number>();
    const pending = new Set<string>();
    const requested = (request: import("@playwright/test").Request) => {
      if (
        request.method() !== "GET" ||
        !request.url().includes("/api/") ||
        request.url().includes("/stream?")
      )
        return;
      counts.set(request.url(), (counts.get(request.url()) ?? 0) + 1);
      pending.add(request.url());
    };
    const finished = (request: import("@playwright/test").Request) =>
      pending.delete(request.url());
    page.on("request", requested);
    page.on("requestfinished", finished);
    page.on("requestfailed", finished);
    await page.goto(url ?? "/");
    if (label === "Home")
      await expect(
        page.getByRole("heading", { name: ready, exact: true }),
      ).toBeVisible();
    else if (label === "Runs")
      await expect(page.locator(".history-run-title").first()).toBeVisible();
    else
      await expect(
        page.getByRole("region", { name: ready, exact: true }),
      ).toBeVisible();
    await expect.poll(() => pending.size).toBe(0);
    expect(
      [...counts].filter(([, count]) => count > 1),
      label,
    ).toEqual([]);
    expect(
      [...counts.keys()].filter((key) => key.includes("/api/attention")),
      label,
    ).toHaveLength(1);
    page.off("request", requested);
    page.off("requestfinished", finished);
    page.off("requestfailed", finished);
  }
});
