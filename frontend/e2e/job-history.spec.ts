import { expect, test, type Page } from "./a11y-test";
import { readFile } from "node:fs/promises";
import { stringify } from "yaml";
import { post, expectRunStatus } from "./setup-helpers";
import { ansiSpans, commandLines, jobDuration } from "../src/job";
import { jobListRows } from "../src/job-list";
import type { RunEvent, RunNode } from "../src/types";
import type { AnsiStyle } from "../src/job";

async function create(
  page: Page,
  key: string,
  nodes: object,
  extra: object = {},
) {
  const response = await post(page, "/api/workflows", {
    key,
    holder: `job-log-${key}`,
    yaml: stringify({
      name: key,
      jobs: nodes,
      ...extra,
    }),
  });
  expect(response.status(), await response.text()).toBe(201);
}
async function launch(page: Page, key: string) {
  const response = await post(page, "/api/runs", {
    workflow_key: key,
    inputs: {},
  });
  expect(response.status(), await response.text()).toBe(201);
  const value: { run_id: string } = await response.json();
  return value.run_id;
}

test.beforeEach(async ({ page }) => {
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
});

test("a failed command step retains its late error, exact attempt, and downloadable output", async ({
  page,
}, info) => {
  const reset: { python: string } = await (
    await post(page, "/__test__/reset")
  ).json();
  await create(page, "late-error", {
    before: {
      steps: [
        {
          id: "work",
          uses: "relay/command@v1",
          with: {
            argv: JSON.stringify([
              reset.python,
              "-c",
              "print('Earlier output\\n' * 20000)",
            ]),
          },
        },
      ],
    },
    check: {
      needs: ["before"],
      steps: [
        {
          id: "work",
          uses: "relay/command@v1",
          with: {
            argv: JSON.stringify([
              reset.python,
              "-c",
              "import sys; print('Command stdout'); sys.stderr.write('\\x1b[31mFinal command error\\x1b[0m\\n'); sys.exit(5)",
            ]),
          },
        },
      ],
    },
  });
  const id = await launch(page, "late-error");
  await expectRunStatus(page, id, "failed", 60_000);
  await page.goto(`/?view=runs&run=${id}`);
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  await expect(
    page.getByRole("heading", { name: "Steps and progress", exact: true }),
  ).toHaveCount(0);
  await expect(jobs.locator("[data-job-scope]").first()).toHaveAttribute(
    "data-job-scope",
    "root.check",
  );
  await expect(jobs.locator('[data-job-scope="root.check"]')).toHaveCount(1);
  await expect(
    jobs.getByText("Waiting and failed jobs", { exact: true }),
  ).toBeVisible();
  await page.goto(`/?view=runs&run=${id}&job=root.check.work`);
  const log = page.getByRole("region", { name: "Job log", exact: true });
  await expect(log.getByRole("alert")).toContainText("Final command error");
  await expect(log.getByRole("alert")).toBeInViewport();
  await page.screenshot({ path: info.outputPath("job-error.png") });
  await expect(page).toHaveURL(/job=root(?:%2E|\.)check/);
  const terminal = log.getByRole("region", { name: "Command output lines" });
  await expect(terminal).toContainText("Command stdout");
  await expect(
    terminal.getByText("Final command error", { exact: true }),
  ).toHaveCSS("color", "rgb(248, 113, 113)");
  const downloading = page.waitForEvent("download");
  await log.getByRole("button", { name: "Log options", exact: true }).click();
  await page
    .getByRole("menuitem", { name: "Download logs", exact: true })
    .click();
  const download = await downloading;
  const path = info.outputPath("command.log");
  await download.saveAs(path);
  expect(await readFile(path, "utf8")).toContain("Final command error");
  await page.reload();
  await expect(log.getByRole("alert")).toContainText("Final command error");
  await log.getByRole("button", { name: "Re-run job", exact: true }).click();
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/runs/${id}/job?job=root.check.work`)
          ).json()
        ).job.latest_attempt?.number,
    )
    .toBe(2);
  await expectRunStatus(page, id, "failed");
  await expect(
    log.getByRole("combobox", { name: "Attempt", exact: true }),
  ).toContainText("Attempt 2");
  await log.getByRole("combobox", { name: "Attempt", exact: true }).click();
  await page
    .getByRole("option", { name: "Attempt 1 · Failed", exact: true })
    .click();
  await expect(log.getByRole("alert")).toContainText("Final command error");
  await jobs.getByRole("link", { name: "Summary", exact: true }).click();
  await expect(log).toHaveCount(0);
  await expect(page).not.toHaveURL(/job=/);
  await page.goto(`/?view=runs&run=${id}&job=root.check.work`);
  await expect(log.getByRole("alert")).toContainText("Final command error");
});

test("a failed agent shows its captured instruction and error without loading the run feed", async ({
  page,
}) => {
  await create(page, "agent-log", {
    inspect: {
      outputs: {
        verdict: "${{ steps.work.outputs.value }}",
      },
      steps: [
        {
          id: "work",
          uses: "relay/agent@v1",
          with: {
            agent: "codex",
            model: "m1",
            "prompt-files": "prompts/prompt.md",
            report: "REVIEW.md",
            selector: JSON.stringify({
              label: {
                artifact: "REVIEW.md",
                label: "JobHistoryMissing",
              },
            }),
          },
        },
      ],
    },
  });
  const id = await launch(page, "agent-log");
  await expectRunStatus(page, id, "failed");
  const detail = (
    await (
      await page.request.get(`/api/runs/${id}/job?job=root.inspect.work`)
    ).json()
  ).job;
  await page.goto(`/?view=runs&run=${id}`);
  await page.goto(`/?view=runs&run=${id}&job=root.inspect.work`);
  const log = page.getByRole("region", { name: "Job log" });
  await expect(log.getByRole("alert")).toContainText(
    detail.latest_attempt.error_message,
  );
  await expect(log.getByRole("alert")).toBeInViewport();
  await expect(log).toContainText("Runs on Codex · m1");
  await log.getByRole("button", { name: "Instructions", exact: true }).click();
  await expect(
    log.getByText("prompts/prompt.md", { exact: true }),
  ).toBeVisible();
  await expect(
    log.getByRole("button", { name: "Agent conversation", exact: true }),
  ).toHaveAttribute("aria-expanded", "true");
});

test("nested reusable jobs have individual logs and stable links", async ({
  page,
}) => {
  await create(
    page,
    "child-log",
    {
      check: {
        name: "Check",
        steps: [
          { id: "verify", shell: "python", run: "print('child output')" },
        ],
      },
    },
    { on: { workflow_call: {} } },
  );
  await create(page, "nested-log", {
    child: { uses: "./.relay/workflows/child-log.yaml" },
  });
  const id = await launch(page, "nested-log");
  await expectRunStatus(page, id, "succeeded");
  await page.goto(`/?view=runs&run=${id}&job=root.child.check`);
  const log = page.getByRole("region", { name: "Job log", exact: true });
  await expect(
    log.getByRole("heading", { name: "Check", exact: true }),
  ).toBeVisible();
  await log.getByRole("button", { name: /1\. Verify/ }).click();
  await expect(log).toContainText("child output");
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  await expect(
    jobs.locator('[data-job-scope="root.child.check"]'),
  ).toBeVisible();
  await page.reload();
  await expect(
    log.getByRole("heading", { name: "Check", exact: true }),
  ).toBeVisible();
});

function job(scope: string, fields: Partial<RunNode> = {}): RunNode {
  return {
    id: scope,
    scope_path: scope,
    node_id: scope.split(".").at(-1) ?? scope,
    node_type: "actions_job",
    status: "succeeded",
    writes: false,
    parent_scope: null,
    dependencies: [],
    ...fields,
  };
}

test("a waiting job is pinned above completed work and opens from the keyboard", async ({
  page,
}) => {
  await create(page, "waiting-list", {
    before: {
      steps: [
        {
          id: "work",
          uses: "relay/command@v1",
          with: {
            argv: JSON.stringify(["git", "status"]),
          },
        },
      ],
    },
    approval: {
      needs: ["before"],
      steps: [
        {
          id: "work",
          uses: "relay/human-wait@v1",
          with: {
            prompt: "Approve the saved work.",
          },
        },
      ],
    },
  });
  const id = await launch(page, "waiting-list");
  await expectRunStatus(page, id, "paused_wait");
  await page.goto(`/?view=runs&run=${id}`);
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  const first = jobs.locator("[data-job-scope]").first();
  await expect(first).toHaveAttribute("data-job-scope", "root.approval");
  await expect(first).toContainText("Waiting");
  await expect(jobs.locator('[data-job-scope="root.before"]')).toContainText(
    "Succeeded",
  );
  await first.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/job=root.approval/);
  await expect(
    page.getByRole("region", { name: "Job log", exact: true }),
  ).toBeVisible();
});

test("terminal text keeps stream boundaries, ANSI colors, and inert escape sequences", () => {
  const event = (id: number, type: string, chunk: string): RunEvent => ({
    id,
    type,
    source: "command",
    ts: "2026-10-07T12:00:00Z",
    payload: { chunk },
  });
  expect(
    commandLines([
      event(1, "command.stdout", "one"),
      event(2, "command.stdout", " line\n"),
      event(3, "command.stderr", "error\n"),
      event(4, "node.succeeded", "ignored"),
    ]),
  ).toEqual([
    { stream: "stdout", text: "one line" },
    { stream: "stderr", text: "error" },
  ]);
  expect(
    ansiSpans("\x1b[31merror\x1b[0m <script>alert(1)</script>\x1b[2J"),
  ).toEqual([
    { text: "error", color: "#f87171", bold: false },
    { text: " <script>alert(1)</script>", color: undefined, bold: false },
  ]);
  expect(
    ansiSpans("\x1b]8;;https://example.test\x07Link\x1b]8;;\x07")
      .map((span) => span.text)
      .join(""),
  ).toBe("Link");
  expect(
    ansiSpans("\x1b]8;;https://example.test\x1b\\Link\x1b]8;;\x1b\\ tail")
      .map((span) => span.text)
      .join(""),
  ).toBe("Link tail");
  expect(ansiSpans("\x1b[1;94mBlue\x1b[22;39mnormal")).toEqual([
    { text: "Blue", bold: true, color: "#93c5fd" },
    { text: "normal", bold: false, color: undefined },
  ]);
  expect(ansiSpans("\x1b[38;5;45mCyan")[0].color).toBe("rgb(0, 215, 255)");
  expect(ansiSpans("\x1b[38;2;100;200;250mRGB")[0].color).toBe(
    "rgb(100, 200, 250)",
  );
  const style: AnsiStyle = { bold: false };
  ansiSpans("\x1b[31mred", style);
  expect(ansiSpans("next line", style)[0].color).toBe("#f87171");
  expect(jobDuration("2026-10-07T12:00:00Z", "2026-10-07T12:01:05Z")).toBe(
    "1m 5s",
  );
  expect(jobDuration(null)).toBe("Queued");
  expect(jobDuration("invalid", "invalid")).toBe("Duration unavailable");
});

test("unstarted terminal jobs have no elapsed duration while pending jobs stay explicit", () => {
  for (const status of ["skipped", "canceled", "failed", "succeeded"])
    expect(jobDuration(null, null, 0, status)).toBe("—");
  expect(jobDuration(null, null, 0, "pending")).toBe("Queued");
});
