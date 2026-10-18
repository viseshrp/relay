import { expect, test } from "./a11y-test";
import { post, runStarter, expectRunStatus } from "./setup-helpers";
import type { AgentsResponse } from "../src/types";

test("account creation explains the password rules before submission", async ({
  page,
}) => {
  await page.route("**/api/auth", (route) =>
    route.fulfill({
      json: {
        authenticated: false,
        owner_created: false,
        username: null,
        login_required: true,
        password_rules: [
          "Use at least 12 characters.",
          "Avoid common passwords.",
        ],
      },
    }),
  );
  await page.goto("/?view=workflows");
  await expect(
    page.getByText(
      "Create a password for this computer's Relay. Only people who can use this computer can reach it.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveText([
    "Use at least 12 characters.",
    "Avoid common passwords.",
  ]);
  await expect(page.getByText(/Django/)).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Username" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel(/^Password/)).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Create password" }),
  ).toBeFocused();
});

test("returning users see sign-in without account creation rules", async ({
  page,
}) => {
  await page.goto("/?view=workflows");
  await expect(
    page.getByText("Sign in to Relay on this computer."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Choose a password that follows these rules:"),
  ).toHaveCount(0);
});

for (const [id, name] of [
  ["ask-agent", "Ask an agent"],
  ["plan-approve-implement", "Plan, approve, implement"],
  ["implement-and-test", "Implement and test"],
  ["review-branch", "Review my branch"],
  ["fix-tests", "Fix until tests pass"],
  ["write-docs", "Write docs for a change"],
]) {
  test(`${name} copies its sources and completes with the fake agent`, async ({
    page,
  }, testInfo) => {
    await page.request.get("/api/auth");
    expect(
      (
        await post(page, "/api/auth/login", {
          username: "owner",
          password: "Relay-Test-Passphrase-2026!",
        })
      ).ok(),
    ).toBeTruthy();
    await runStarter(page, id, name, testInfo, id === "ask-agent");
  });
}

for (const readyCount of [0, 5]) {
  test(`setup shows ${readyCount} agents ready and can check again`, async ({
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
    await page.route("**/api/runs?*status=succeeded*", (route) =>
      route.fulfill({ json: { runs: [], next: null } }),
    );
    const source: AgentsResponse = await (
      await page.request.get("/api/agents")
    ).json();
    const inventory = {
      ...source,
      agents: source.agents.map((agent) => ({
        ...agent,
        installed: readyCount === 5 || agent.installed,
      })),
    };
    await page.route("**/api/agents", (route) =>
      route.fulfill({ json: inventory }),
    );
    let checks = 0;
    await page.route("**/api/agents/check", async (route) => {
      checks += 1;
      const agents = inventory.agents;
      await route.fulfill({
        json: {
          agents: agents.map((agent) => ({
            ...agent,
            ready: readyCount > 0,
            error_code: readyCount ? null : "agent_auth_error",
            reason: readyCount ? null : "Sign in to continue.",
            cleanup_warning: null,
            models: readyCount ? ["m1"] : [],
            login_command: "codex login",
            login_guidance: "Sign in in your terminal.",
          })),
        },
      });
    });
    await page.goto("/?view=workflows");
    await page
      .getByRole("button", { name: "Get started", exact: true })
      .click();
    const setup = page.getByRole("region", {
      name: "Get started",
      exact: true,
    });
    await expect(setup.getByRole("article")).toHaveCount(5);
    // Installed status comes from the inventory; model checks never install an agent.
    const installed = inventory.agents.filter(
      (agent) => agent.installed,
    ).length;
    await expect(setup.getByText(/Ready to connect/)).toHaveCount(
      readyCount ? installed : 0,
    );
    if (!readyCount)
      await expect(
        setup.getByText(
          "Install and sign in to one agent, then choose Check again.",
        ),
      ).toBeVisible();
    await setup
      .getByRole("button", { name: "Check again", exact: true })
      .click();
    await expect.poll(() => checks).toBeGreaterThanOrEqual(2);
    await expect(
      setup.getByRole("button", { name: "Check again", exact: true }),
    ).toBeEnabled();
  });
}

test("the full AI coding workflow is preselected and runs from one task", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.request.get("/api/auth");
  expect(
    (
      await post(page, "/api/auth/login", {
        username: "owner",
        password: "Relay-Test-Passphrase-2026!",
      })
    ).ok(),
  ).toBeTruthy();
  expect(
    (
      await post(page, "/__test__/starter-project", { full_workflow: true })
    ).ok(),
  ).toBeTruthy();
  await page.goto("/?view=workflows");
  await page
    .getByRole("button", { name: "Account menu for owner", exact: true })
    .click();
  await page
    .getByRole("menuitem", { name: "Get started", exact: true })
    .click();
  const setup = page.getByRole("dialog", { name: "Get started", exact: true });
  await expect(
    setup.getByRole("article", { name: "Claude Code", exact: true }),
  ).toContainText("Ready to connect");
  await setup
    .getByRole("button", { name: "Start from a template", exact: true })
    .click();
  const gallery = page.getByRole("dialog", { name: "Choose a workflow" });
  await expect(
    gallery.getByRole("button", {
      name: "Use AI coding workflow",
      exact: true,
    }),
  ).toHaveAttribute("aria-pressed", "true");
  await gallery
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  await expect(gallery).toBeHidden();
  await expect(
    setup.getByRole("button", { name: "Run workflow", exact: true }),
  ).toBeDisabled();
  await setup
    .getByLabel("What should we build?", { exact: true })
    .fill("Add dark mode");
  await setup
    .getByRole("combobox", {
      name: "Exact model value for the selected agent",
      exact: true,
    })
    .click();
  await page.getByRole("option", { name: "m1", exact: true }).click();
  await setup
    .getByRole("combobox", {
      name: "Exact Claude Opus model value advertised by Claude",
      exact: true,
    })
    .click();
  await page.getByRole("option", { name: "m2", exact: true }).click();
  await expect(
    setup.getByRole("combobox", { name: "Model", exact: true }),
  ).toHaveCount(0);
  const launched = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await setup
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const response = await launched;
  expect(response.status(), await response.text()).toBe(201);
  expect(response.request().postDataJSON()).toMatchObject({
    inputs: {
      task: "Add dark mode",
      agent: "codex",
      model: "m1",
      opus_model: "m2",
    },
  });
  expect(response.request().postDataJSON()).not.toHaveProperty("model");
  const { run_id: runId } = await response.json();
  for (const answer of ["IMPLEMENT", "TESTS", "ACCEPT"]) {
    await page
      .getByRole("region", { name: "Waiting for you", exact: true })
      .getByRole("button", { name: "Respond", exact: true })
      .click();
    const request = page.locator(".interaction-card").filter({
      has: page.getByRole("button", { name: answer, exact: true }),
    });
    await expect(request).toBeVisible({ timeout: 30_000 });
    // Each approval offers its allowed answers; nothing can be mistyped.
    await expect(
      request.getByLabel("Your response", { exact: true }),
    ).toHaveCount(0);
    await request.getByRole("button", { name: answer, exact: true }).click();
    await expect(request).toHaveCount(0);
  }
  await expectRunStatus(page, runId, "succeeded");
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
      { exact: true },
    ),
  ).toBeVisible();
  const run = (
    await (await page.request.get(`/api/runs/${runId}/monitor`)).json()
  ).run;
  expect(run.has_committed_changes).toBe(true);
  let total = 0;
  for (let since: number | null = 0; since !== null;) {
    const page_: { artifacts: unknown[]; next: number | null } = await (
      await page.request.get(
        `/api/runs/${runId}/artifacts?since=${since}&limit=200&visible=true`,
      )
    ).json();
    total += page_.artifacts.length;
    since = page_.next;
  }
  expect(total).toBeGreaterThan(50);
  expect(run.artifact_count).toBe(total);
  await expect(
    page
      .locator(".run-summary-metadata")
      .getByRole("link", { name: String(total), exact: true }),
  ).toBeVisible();
  const material = page.getByRole("combobox", { name: "Review material" });
  await expect(material).toHaveText("Committed code changes");
  await material.click();
  await expect(
    page.getByRole("option", { name: "Committed code changes", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Open changes and documents", exact: true })
    .click();
  await expect(
    page.getByRole("navigation", { name: "Changed files", exact: true }),
  ).toContainText("feature.py");
  const location = page.getByRole("region", {
    name: "Where the code is",
    exact: true,
  });
  await expect(location).toContainText(
    `2 files changed on branch ${run.run_branch}.`,
  );
  expect(run.run_branch).toMatch(/^relay\/run\//);
  for (const file of ["feature.py", "test_feature.py"])
    await expect(location.getByText(file, { exact: true })).toBeVisible();
  for (const command of [
    `git switch ${run.source_branch}`,
    `git merge --ff-only ${run.run_branch}`,
  ])
    await expect(location.getByText(command, { exact: true })).toBeVisible();
  await expect(location).toContainText(
    'To merge automatically next time, choose "Merge into the active branch, then delete working copies" under Advanced options when you run the workflow.',
  );
});

test("Plan, approve, implement stops without implementing when Stop is chosen", async ({
  page,
}, testInfo) => {
  await page.request.get("/api/auth");
  expect(
    (
      await post(page, "/api/auth/login", {
        username: "owner",
        password: "Relay-Test-Passphrase-2026!",
      })
    ).ok(),
  ).toBeTruthy();
  const runId = await runStarter(
    page,
    "plan-approve-implement",
    "Plan, approve, implement",
    testInfo,
    false,
    "Stop",
  );
  const { nodes } = (await (
    await page.request.get(`/api/runs/${runId}/monitor`)
  ).json()) as {
    nodes: { scope_path: string; node_type: string; conclusion: string }[];
  };
  const steps = nodes.filter((node) => node.node_type === "actions_step");
  expect(steps.map((step) => step.conclusion)).toEqual([
    "success",
    "success",
    "skipped",
    "success",
  ]);
  await page.goto(`/?view=runs&run=${runId}`);
  await page
    .getByRole("navigation", { name: "Jobs", exact: true })
    .locator("[data-job-scope]")
    .click();
  await page
    .getByRole("region", { name: "Job steps", exact: true })
    .getByRole("button", { name: /Step 4/ })
    .click();
  await expect(
    page.getByRole("region", { name: "Command output lines" }),
  ).toContainText("Stopped at plan review.");
});

test("gallery cards show their size, needs, and YAML input types", async ({
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
  expect((await post(page, "/__test__/starter-project")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await page
    .getByRole("button", { name: "Account menu for owner", exact: true })
    .click();
  await page
    .getByRole("menuitem", { name: "Get started", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Get started", exact: true })
    .getByRole("button", { name: "Start from a template", exact: true })
    .click();
  const gallery = page.getByRole("dialog", { name: "Choose a workflow" });
  const card = (name: string) =>
    gallery.getByRole("article", { name, exact: true });
  await expect(card("Implement and test")).toContainText(
    "Inputs: task (string), test_runner (choice)",
  );
  await expect(gallery).not.toContainText("(enum)");
  await expect(card("AI coding workflow")).toContainText(
    "9 jobs · 3 approvals",
  );
  await expect(card("AI coding workflow")).toContainText(
    "Needs Claude Code with an Opus model and one other coding agent. Choose Ask an agent for a smaller first run.",
  );
  await expect(card("Ask an agent")).toContainText("1 job");
  await expect(card("Ask an agent")).not.toContainText("approval");
  await expect(card("Ask an agent")).not.toContainText("Needs Claude Code");
  await expect(card("Plan, approve, implement")).toContainText(
    "1 job · 1 approval",
  );
});

test("the full starter requires Claude and the blank option remains available", async ({
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
  expect((await post(page, "/__test__/starter-project")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await page
    .getByRole("button", { name: "Account menu for owner", exact: true })
    .click();
  await page
    .getByRole("menuitem", { name: "Get started", exact: true })
    .click();
  const setup = page.getByRole("dialog", { name: "Get started", exact: true });
  await expect(
    setup.getByRole("article", { name: "Codex", exact: true }),
  ).toContainText("Ready to connect");
  await setup
    .getByRole("button", { name: "Start from a template", exact: true })
    .click();
  const gallery = page.getByRole("dialog", { name: "Choose a workflow" });
  await expect(
    gallery.getByRole("button", {
      name: "Use AI coding workflow",
      exact: true,
    }),
  ).toHaveAttribute("aria-pressed", "true");
  await gallery
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  await expect(gallery).toBeHidden();
  await expect(
    setup.getByText(
      "Install and sign in to Claude Code, then choose Check again. This workflow uses Claude Opus for planning and review.",
    ),
  ).toBeVisible();
  await expect(
    setup.getByRole("button", { name: "Run workflow", exact: true }),
  ).toBeDisabled();
  await setup
    .getByRole("button", { name: "Blank workflow", exact: true })
    .click();
  await expect(
    gallery.getByRole("textbox", { name: "Workflow name", exact: true }),
  ).toBeVisible();
  await expect(
    gallery.getByRole("button", { name: "Blank workflow", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
});
