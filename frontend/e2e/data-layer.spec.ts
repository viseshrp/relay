import { expect, test } from "./a11y-test";
import { sharedRead, invalidateReads } from "../src/read-cache";
import { post } from "./setup-helpers";

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
  await page.goto("/?view=home");
  await expect(
    page.getByRole("heading", { name: "Your work at a glance" }),
  ).toBeVisible();
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
  await page.clock.install();
  let reads = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/dashboard?limit=10")) reads++;
  });
  await page.goto("/?view=home");
  const refresh = page.getByRole("button", { name: "Refresh", exact: true });
  await expect(refresh).toBeEnabled();
  for (let index = 0; index < 12; index++) {
    const before = reads;
    await page.clock.runFor(5000);
    await expect.poll(() => reads).toBe(before + 1);
    await expect(refresh).toBeEnabled();
  }
  const backedOff = reads;
  await page.clock.runFor(29999);
  await page.clock.runFor(1);
  expect(reads - backedOff).toBeLessThanOrEqual(1);
  await expect(refresh).toBeEnabled();
  const beforeFocus = reads;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect.poll(() => reads).toBe(beforeFocus + 1);
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
