import { expect, test } from "@playwright/test";
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
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => dashboards).toBe(before[0] + 1);
});
