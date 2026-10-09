import { historicalPost } from "./setup-helpers";
import { expect, test, type Page } from "@playwright/test";
import { parse, stringify } from "yaml";
import { capturedRunGraph, visibleRunStages } from "../src/graph";
import type { RunNode } from "../src/types";

async function post(page: Page, path: string, data: object = {}) {
  return historicalPost(page, path, data);
}

function node(scope: string, fields: Partial<RunNode> = {}): RunNode {
  return {
    id: scope,
    scope_path: scope,
    node_id: scope.split(".").at(-1)!,
    node_type: "command",
    status: "succeeded",
    writes: false,
    selected_branch: null,
    loop_index: null,
    parent_scope: null,
    dependencies: [],
    controls: [],
    ...fields,
  };
}

test("only explicitly marked repairs leave the map and their edges stay connected", () => {
  const records = [
    node("root.review"),
    node("root.hidden", {
      node_type: "loop",
      dependencies: ["root.review"],
      repair_for: "root.review",
      status: "waiting",
      repair_settings: {
        legacy: false,
        max_rounds: 3,
        accepted_output: "ready",
        accepted_value: "Yes",
        fix_instruction: "fix",
        verify_instruction: "verify",
        roles: {},
      },
    }),
    node("root.hidden#1.fix", { parent_scope: "root.hidden#1", loop_index: 1 }),
    node("root.deliver", {
      status: "pending",
      dependencies: ["root.review", "root.hidden"],
    }),
    node("root.repairs", { node_type: "loop", status: "pending" }),
  ];
  expect(visibleRunStages(records).map((item) => item.scope_path)).toEqual([
    "root.review",
    "root.deliver",
    "root.repairs",
  ]);
  const graph = capturedRunGraph(records);
  expect(
    graph.nodes.find((item) => item.id === "root.review")?.data.status,
  ).toBe("repairing");
  expect(graph.edges.map((edge) => [edge.source, edge.target])).toEqual([
    ["root.review", "root.deliver"],
  ]);
});

test("bounded repair loops save, reload and execute frozen local workflows", async ({
  page,
}, testInfo) => {
  await page.addInitScript(() =>
    sessionStorage.setItem("relay.editor-holder", "repair-test"),
  );
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
  const child = stringify({
    on: { workflow_call: {} },
    jobs: {
      repair: {
        steps: [
          { run: "echo fixed > fixed.txt" },
          { run: "test -f fixed.txt" },
        ],
      },
    },
  });
  expect(
    (
      await post(page, "/api/workflows", {
        key: "repair-child",
        holder: "repair-test",
        yaml: child,
      })
    ).ok(),
  ).toBeTruthy();
  const source = stringify({
    name: "Bounded repair loop",
    jobs: {
      review: {
        steps: [
          {
            uses: "relay/loop@v1",
            with: {
              workflow: "./.relay/workflows/repair-child.yaml",
              "max-iterations": 1,
            },
          },
        ],
      },
    },
  });
  expect(
    (
      await post(page, "/api/workflows", {
        key: "native-repairs",
        holder: "repair-test",
        yaml: source,
      })
    ).ok(),
  ).toBeTruthy();
  await page.goto("/?view=workflows&workflow=native-repairs.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const input = page.getByLabel("Action inputs", { exact: true });
  await input.fill(
    JSON.stringify({
      workflow: "./.relay/workflows/repair-child.yaml",
      "max-iterations": 3,
    }),
  );
  await input.blur();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow saved and validated.", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(input).toHaveValue(/"max-iterations": 3/);
  const launch = await post(page, "/api/runs", {
    workflow_key: "native-repairs",
    inputs: {},
    cleanup_policy: "retain",
  });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const { run_id: id } = await launch.json();
  await page.goto(`/?view=runs&run=${id}`);
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
    ),
  ).toBeVisible();
  const detail = (await (await page.request.get(`/api/runs/${id}`)).json()).run;
  expect(
    detail.nodes
      .filter((item: { node_type: string }) => item.node_type === "actions_job")
      .every((item: { status: string }) => item.status === "succeeded"),
  ).toBeTruthy();
  await page.screenshot({
    path: testInfo.outputPath("repair-loop-complete.png"),
    fullPage: true,
  });
});

test("agent steps retain independent efforts and provider defaults across save", async ({
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
  await page.getByLabel("Agent", { exact: true }).click();
  await page.getByRole("option", { name: "Codex", exact: true }).click();
  await page
    .getByLabel("Agent prompt", { exact: true })
    .fill("Fix the reported findings and preserve required checks.");
  await page.getByLabel("Effort", { exact: true }).click();
  await page.getByRole("option", { name: "Low", exact: true }).click();
  await page.getByRole("button", { name: "Add step", exact: true }).click();
  await page
    .getByLabel("Action reference", { exact: true })
    .fill("relay/agent@v1");
  const input = page.getByLabel("Action inputs", { exact: true });
  await input.fill(
    JSON.stringify({
      agent: "codex",
      model: "m1",
      prompt: "Verify every required check.",
    }),
  );
  await input.blur();
  await expect(page.getByLabel("Effort", { exact: true })).toContainText(
    "Provider default",
  );
  await expect(page.getByLabel("Permission mode", { exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Workflow saved and validated.")).toBeVisible();
  await page.reload();
  const source = parse(
    (await (await page.request.get("/api/workflows/workflow")).json()).yaml,
  );
  expect(source.jobs.work.steps[0].with.effort).toBe("low");
  expect(source.jobs.work.steps[1].with.effort).toBeUndefined();
  expect(source.jobs.work.steps[0].with.prompt).toBe(
    "Fix the reported findings and preserve required checks.",
  );
});

test("exhausted repairs stop visibly at their source and keep every rejected report", async ({
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
  const reset = await post(page, "/__test__/reset");
  expect(reset.ok()).toBeTruthy();
  const python = (await reset.json()).python;
  await page.goto("/?view=workflows");
  await expect(
    page.getByRole("button", { name: "Add job", exact: true }),
  ).toBeEnabled();
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const report = (file: string) => ({
    type: "command",
    writes: true,
    allow_no_commit: true,
    run: [
      python,
      "-c",
      `from pathlib import Path; Path('${file}').write_text('Ready: No\\n')`,
    ],
    outputs: { ready: { label: { artifact: file, label: "Ready" } } },
  });
  const created = await post(page, "/api/workflows", {
    key: "repair-stop",
    holder,
    yaml: stringify({
      version: 1,
      name: "Stopped repairs",
      nodes: {
        review: report("REVIEW.md"),
        deliver: { type: "command", needs: ["review"], run: ["git", "status"] },
      },
      repairs: {
        review: {
          accepted_output: "ready",
          max_rounds: 1,
          fix: { type: "command", run: ["git", "status"] },
          verify: report("REVIEW_FIX_VERIFICATION.md"),
        },
      },
    }),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const response = await post(page, "/api/runs", {
    workflow_key: "repair-stop",
    inputs: {},
    cleanup_policy: "retain",
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const runId = (await response.json()).run_id;
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(
    page.getByRole("heading", { name: "Review stopped", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "The configured repair rounds ended without a passing verification. Open Repairs to inspect the rejected reports.",
      { exact: true },
    ),
  ).toBeVisible();
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  await expect(jobs.locator('[data-job-scope="root.review"]')).toHaveCount(1);
  await expect(jobs).toContainText("Repair for Review");
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  const detail = (await (await page.request.get(`/api/runs/${runId}`)).json())
    .run;
  expect(
    await jobs
      .locator("[data-job-scope]")
      .evaluateAll((elements) =>
        elements
          .map((element) => element.getAttribute("data-job-scope"))
          .sort(),
      ),
  ).toEqual(
    detail.nodes.map((node: { scope_path: string }) => node.scope_path).sort(),
  );
  expect(detail.problem.error_code).toBe("repair_exhausted");
  expect(
    detail.nodes.find(
      (item: { scope_path: string }) => item.scope_path === "root.deliver",
    ).status,
  ).toBe("canceled");
  const artifacts = (
    await (await page.request.get(`/api/runs/${runId}/artifacts`)).json()
  ).artifacts;
  const reports = artifacts.filter(
    (item: { name: string }) => item.name === "ready",
  );
  expect(reports).toHaveLength(2);
  for (const artifact of reports)
    await expect(
      (await page.request.get(`/api/artifacts/${artifact.id}`)).text(),
    ).resolves.toMatch(/^Ready: No\r?\n$/);
});

test("paused repair roles show saved model overrides instead of workflow defaults", async ({
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
  await page.goto("/?view=workflows");
  await expect(
    page.getByRole("button", { name: "Add job", exact: true }),
  ).toBeEnabled();
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const created = await post(page, "/api/workflows", {
    key: "repair-settings",
    holder,
    yaml: stringify({
      version: 1,
      name: "Paused repair settings",
      model: "m1",
      agents: ["codex"],
      nodes: {
        review: { type: "command", run: ["git", "status"] },
        repairs: {
          type: "loop",
          needs: ["review"],
          max_iterations: 2,
          until: "${{ loop.index >= 1 }}",
          exhausted: "stopped",
          body: {
            wait: { type: "human_wait", prompt: "Hold this isolated repair" },
            verify: {
              type: "agent",
              needs: ["wait"],
              model: "m1",
              agents: ["codex"],
              agent_options: {
                codex: { effort: "low", permission_mode: "auto" },
              },
            },
          },
        },
        stopped: { type: "command", run: ["git", "status"] },
      },
    }),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const launch = await post(page, "/api/runs", {
    workflow_key: "repair-settings",
    inputs: {},
    cleanup_policy: "retain",
  });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const runId = (await launch.json()).run_id;
  await expect
    .poll(async () => {
      const run = (await (await page.request.get(`/api/runs/${runId}`)).json())
        .run;
      return run.nodes.find(
        (item: { scope_path: string }) => item.scope_path === "root.repairs",
      )?.status;
    })
    .toBe("waiting");
  const before = (await (await page.request.get(`/api/runs/${runId}`)).json())
    .run;
  expect(
    (
      await post(page, `/api/runs/${runId}/pause`, {
        paused: true,
        idempotency_key: "hold-repairs",
      })
    ).ok(),
  ).toBeTruthy();
  expect(
    (
      await post(page, `/api/runs/${runId}/repairs`, {
        groups: { "root.repairs": "root.review" },
        idempotency_key: "group-repairs",
      })
    ).ok(),
  ).toBeTruthy();
  const changed = await post(page, `/api/runs/${runId}/step-settings`, {
    scope_path: "root.repairs#1.verify",
    agent_id: "claude",
    model: "m1",
    effort: "high",
    permission_mode: "auto",
    idempotency_key: "change-verifier",
  });
  expect(changed.ok(), await changed.text()).toBeTruthy();
  await page.goto(`/?view=runs&run=${runId}`);
  await page.getByText("Repairs · 1 configured", { exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Repairs for Review",
    exact: true,
  });
  await expect(
    panel.getByRole("heading", {
      name: "Review · Repairs paused",
      exact: true,
    }),
  ).toBeVisible();
  const verifier = panel.getByRole("region", {
    name: "Repair settings for Verify",
    exact: true,
  });
  await expect(verifier.getByText("Verify", { exact: true })).toBeVisible();
  await expect(verifier.locator("dt")).toHaveText([
    "Model",
    "Agent",
    "Thinking effort",
    "Permissions",
  ]);
  await expect(verifier.locator("dd")).toHaveText([
    "m1",
    "Claude",
    "high",
    "auto",
  ]);
  await expect(verifier).not.toContainText("Codex");
  await expect(
    page.getByRole("button", { name: "Resume", exact: true }),
  ).toBeVisible();
  const after = (await (await page.request.get(`/api/runs/${runId}`)).json())
    .run;
  expect(after.snapshot).toEqual(before.snapshot);
  expect(after.dispatch_paused).toBe(true);
  const canceled = await post(page, `/api/runs/${runId}/cancel`, {
    idempotency_key: "clean-test-hold",
  });
  expect(canceled.ok(), await canceled.text()).toBeTruthy();
});
