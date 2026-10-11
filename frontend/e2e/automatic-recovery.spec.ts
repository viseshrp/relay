import {
  advancedField,
  openJobSettings,
  closeJobSettings,
} from "./setup-helpers";
import { historicalPost } from "./setup-helpers";
import { expect, test, type Page } from "./a11y-test";
import { parse, stringify } from "yaml";

async function post(page: Page, path: string, data: object = {}) {
  return historicalPost(page, path, data);
}

test("enable recovery for a stopped report step and continue through the same provider", async ({
  page,
}) => {
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
  expect((await post(page, "/__test__/recovery-provider")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await expect(
    page.getByRole("button", { name: "Add job", exact: true }),
  ).toBeEnabled();
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  expect(
    (
      await post(page, "/api/workflows", {
        key: "automatic-recovery",
        holder,
        yaml: stringify({
          version: 1,
          name: "Automatic recovery",
          model: "m2",
          agents: ["codex"],
          nodes: {
            critique: {
              type: "agent",
              writes: true,
              allow_no_commit: true,
              agent_options: {
                codex: { effort: "low", permission_mode: "auto" },
              },
              outputs: {
                author: {
                  label: { artifact: "PLAN_CRITIQUE.md", label: "Created by" },
                },
              },
            },
          },
        }),
      })
    ).ok(),
  ).toBeTruthy();
  const launched = await post(page, "/api/runs", {
    workflow_key: "automatic-recovery",
    inputs: {},
    cleanup_policy: "retain",
  });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${runId}`)).json()).run
          .status,
    )
    .toBe("failed");
  const before = (await (await page.request.get(`/api/runs/${runId}`)).json())
    .run;
  await page.goto(`/?view=runs&run=${runId}`);
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  const recovery = page.getByRole("switch", {
    name: "Automatic recovery",
    exact: true,
  });
  await expect(recovery).not.toBeChecked();
  await recovery.click();
  await expect(recovery).toBeChecked();
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${runId}`)).json()).run
          .status,
    )
    .toBe("succeeded");
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
    ),
  ).toBeVisible();
  await page.getByText("Automatic retry instruction", { exact: true }).click();
  await expect(
    page.getByText("Recover only this failed step.", { exact: false }),
  ).toBeVisible();
  const after = (await (await page.request.get(`/api/runs/${runId}`)).json())
    .run;
  expect(after.snapshot.hashes).toEqual(before.snapshot.hashes);
  expect(after.recovery.current).toMatchObject({
    state: "resumed",
    retry_number: 1,
    scope_path: "root.critique",
  });
  const events = (
    await (await page.request.get(`/api/runs/${runId}/events?limit=200`)).json()
  ).events;
  const attempts = events.filter(
    (event: { type: string }) => event.type === "attempt.started",
  );
  expect(attempts).toHaveLength(2);
  expect(attempts[1].payload).toMatchObject({
    agent_id: "codex",
    model_value: "m2",
  });
  const configured = events.filter(
    (event: { payload: { text?: string } }) =>
      event.payload.text === "config: model=m2;effort=low;mode=auto",
  );
  expect(configured).toHaveLength(2);
});

test("agent recovery override survives source form save and reload", async ({
  page,
}) => {
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
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  const input = await advancedField(page, "Action inputs");
  const value = JSON.parse(await input.inputValue());
  await input.fill(JSON.stringify({ ...value, "auto-retry": false }));
  await input.blur();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
  await page.reload();
  await advancedField(page, "Action inputs");
  await expect(input).toHaveValue(
    JSON.stringify({ ...value, "auto-retry": false }, null, 2),
  );
  const document = parse(
    (await (await page.request.get("/api/workflows/workflow")).json()).yaml,
  );
  expect(document.jobs.work.steps[0].with["auto-retry"]).toBe(false);
});
