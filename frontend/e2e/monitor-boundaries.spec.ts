import { test, expect } from "./a11y-test";
import { post } from "./setup-helpers";
import { stringify } from "yaml";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
});
test("a finished large run opens no stream and transfers less than 100 KB of event data", async ({
  page,
}) => {
  const fixture = await (
    await post(page, "/__test__/worst-case", { enabled: true })
  ).json();
  const streams: string[] = [];
  const eventBytes: Promise<number>[] = [];
  page.on("request", (request) => {
    if (request.url().includes(`/api/runs/${fixture.run}/stream`))
      streams.push(request.url());
  });
  page.on("response", (response) => {
    if (response.url().includes(`/api/runs/${fixture.run}/events`))
      eventBytes.push(response.body().then((body) => body.length));
  });
  await page.goto(`/?view=runs&project=${fixture.project}&run=${fixture.run}`);
  await expect(
    page.getByRole("region", { name: "Step progress" }),
  ).toBeVisible();
  await expect.poll(() => eventBytes.length).toBeGreaterThan(0);
  expect(
    (await Promise.all(eventBytes)).reduce((sum, bytes) => sum + bytes, 0),
  ).toBeLessThan(100000);
  expect(streams).toEqual([]);
  const output = await (
    await page.request.get(
      `/api/runs/${fixture.run}/events?job=${encodeURIComponent(fixture.job + ".verify")}&attempt=1&limit=200`,
    )
  ).json();
  expect(
    output.events
      .map(
        (event: { payload: { chunk?: string } }) => event.payload.chunk || "",
      )
      .join(""),
  ).toContain("00100 Check output");
});

test("run disclosures survive live events and stay scoped when switching runs", async ({
  page,
}) => {
  const f = await (
    await post(page, "/__test__/worst-case", { enabled: false })
  ).json();
  const workflow = await post(page, `/api/workflows?project=${f.project}`, {
    key: "disclosures",
    holder: "disclosure-test",
    yaml: stringify({
      name: "Disclosure test",
      jobs: {
        work: {
          steps: [
            { uses: "relay/human-wait@v1", with: { prompt: "Continue?" } },
            { run: "echo resumed" },
          ],
        },
      },
    }),
  });
  expect(workflow.ok(), await workflow.text()).toBeTruthy();
  expect(
    (await post(page, `/__test__/commit?project=${f.project}`)).ok(),
  ).toBeTruthy();
  const launched = await post(page, `/api/runs?project=${f.project}`, {
    workflow_key: "disclosures",
    inputs: {},
  });
  expect(launched.status(), await launched.text()).toBe(201);
  const id = (await launched.json()).run_id;
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${id}`)).json()).run.status,
    )
    .toBe("paused_wait");
  await page.goto(`/?view=runs&project=${f.project}&run=${id}`);
  const panel = page.getByRole("button", { name: "Run settings", exact: true });
  await panel.click();
  const request = (
    await (
      await page.request.get(`/api/runs/${id}?collection=interactions`)
    ).json()
  ).run.interactions[0];
  expect(
    (
      await post(page, `/api/attempts/${request.attempt_id}/wait`, {
        idempotency_key: "disclosure-answer",
        value: "yes",
      })
    ).ok(),
  ).toBeTruthy();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Disclosure test",
  );
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${id}`)).json()).run.status,
    )
    .toBe("succeeded");
  await expect(panel).toHaveAttribute("aria-expanded", "true");
  await page.goto(`/?view=runs&project=${f.project}&run=${f.run}`);
  await expect(panel).toHaveAttribute("aria-expanded", "false");
  await page.goto(`/?view=runs&project=${f.project}&run=${id}`);
  await expect(panel).toHaveAttribute("aria-expanded", "true");
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
});
