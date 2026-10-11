import { expect, test } from "./a11y-test";
import { post } from "./setup-helpers";
import { parse, stringify } from "yaml";

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
});

test("inputs, ordered prompts, and YAML are saved together and launch end to end", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Workflow settings", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Workflow name", exact: true })
    .fill("Authoring smoke");
  await page.getByRole("button", { name: "Add workflow input" }).click();
  await page
    .getByRole("textbox", { name: "Input name", exact: true })
    .fill("task");
  await page
    .getByRole("textbox", { name: "Workflow name", exact: true })
    .click();
  await page.getByRole("button", { name: "Add task default" }).click();
  await page
    .getByRole("textbox", { name: "task default", exact: true })
    .fill("Ready");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page
    .getByRole("navigation", { name: "Workflow job navigation" })
    .getByRole("button", { name: "Work", exact: true })
    .click();
  await page.getByRole("tab", { name: "Steps", exact: true }).click();
  await page
    .getByRole("textbox", { name: "New prompt file", exact: true })
    .fill("smoke.md");
  await page
    .getByRole("button", { name: "Create prompt", exact: true })
    .click();
  await page
    .locator('[aria-label="Prompt instructions"]')
    .fill("# First instructions\nComplete this check.\n");
  await page
    .getByRole("button", { name: "Preview Markdown", exact: true })
    .last()
    .click();
  await expect(
    page.getByRole("heading", { name: "First instructions", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close job settings" }).click();
  await expect
    .poll(
      async () =>
        (await (await page.request.get("/api/workflows/workflow.yaml")).json())
          .draft?.prompts?.["prompts/smoke.md"]?.text,
    )
    .toContain("First instructions");
  await page.reload();
  await expect(page.getByText(/Unsaved changes:/)).toContainText(
    "prompts/smoke.md",
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
  const source = await (
    await page.request.get("/api/workflows/workflow.yaml")
  ).json();
  expect(source.yaml).toContain("prompt-files: prompts/smoke.md");
  expect(source.yaml).toContain("task:");
  const prompt = await (
    await page.request.get(
      "/api/workflows/workflow.yaml/prompt?reference=prompts/smoke.md",
    )
  ).json();
  expect(prompt.text).toContain("First instructions");
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  const launch = page.getByRole("dialog", {
    name: "Run workflow",
    exact: true,
  });
  await expect(
    launch.getByRole("textbox", { name: "Task", exact: true }),
  ).toHaveValue("Ready");
  await launch
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
      { exact: true },
    ),
  ).toBeVisible();
});

test("drawing changes rewrite YAML and can be undone, redone, and formatted", async ({
  page,
}) => {
  await page.goto("/?view=workflows");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const before = await page
    .locator('[aria-label="Workflow YAML"]')
    .textContent();
  await page.locator(".react-flow__node").first().click({ button: "right" });
  await page.getByRole("menuitem", { name: "Duplicate job" }).click();
  await page.getByRole("button", { name: "Close job settings" }).click();
  await expect(page.locator('[aria-label="Workflow YAML"]')).toContainText(
    "work_copy",
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator('[aria-label="Workflow YAML"]')).toHaveText(before);
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(page.locator('[aria-label="Workflow YAML"]')).toContainText(
    "work_copy",
  );
  await page
    .locator('.react-flow__node[data-id="work"] .react-flow__handle.source')
    .dragTo(
      page.locator(
        '.react-flow__node[data-id="work_copy"] .react-flow__handle.target',
      ),
    );
  await expect(page.locator('[aria-label="Workflow YAML"]')).toContainText(
    "needs:",
  );
  await page.locator(".react-flow__edge").first().focus();
  await page.keyboard.press("Delete");
  await expect(page.locator(".react-flow__edge")).toHaveCount(0);
  await page.getByRole("button", { name: "Format as YAML" }).click();
  await expect(
    page.getByRole("dialog", { name: "Preview YAML formatting" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Apply formatting" }).click();
  await page.getByRole("combobox", { name: "Editor mode" }).click();
  await page.getByRole("option", { name: "Visual", exact: true }).click();
  await expect(page.locator('[aria-label="Workflow YAML"]')).toHaveCount(0);
  await page.getByRole("combobox", { name: "Editor mode" }).click();
  await page.getByRole("option", { name: "YAML", exact: true }).click();
  await expect(page.locator('[aria-label="Workflow YAML"]')).toBeVisible();
});

test("matrix, concurrency, comparisons, and bounded retry controls round trip without JSON", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .getByRole("navigation", { name: "Workflow job navigation" })
    .getByRole("button", { name: "Work", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Concurrency group", exact: true })
    .fill("local-build");
  await page
    .getByRole("checkbox", { name: "Cancel in-progress work in this group" })
    .check();
  await page
    .getByRole("button", { name: "Add Matrix axes entry", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Matrix axes key", exact: true })
    .fill("platform");
  await page
    .getByRole("textbox", { name: "Concurrency group", exact: true })
    .click();
  await page
    .getByRole("combobox", {
      name: "Matrix axes.platform value type",
      exact: true,
    })
    .click();
  await page.getByRole("option", { name: "List", exact: true }).click();
  await page
    .getByRole("button", { name: "Add Matrix axes.platform item", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Matrix axes.platform item 1", exact: true })
    .fill("local");
  await page
    .getByRole("combobox", {
      name: "Job condition expression helper",
      exact: true,
    })
    .fill("${{ success() }}");
  await page
    .getByRole("button", { name: "Insert expression", exact: true })
    .click();
  await page.getByRole("tab", { name: "When it fails", exact: true }).click();
  await page
    .getByRole("combobox", { name: "When this job fails", exact: true })
    .click();
  await page
    .getByRole("option", { name: "Retry up to N times", exact: true })
    .click();
  await page
    .getByRole("combobox", {
      name: "Maximum automatic retries per agent step",
      exact: true,
    })
    .click();
  await page.getByRole("option", { name: "1", exact: true }).click();
  await page.getByRole("button", { name: "Close job settings" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
  const { parse } = await import("yaml");
  const document = parse(
    (await (await page.request.get("/api/workflows/workflow.yaml")).json())
      .yaml,
  );
  expect(document.jobs.work.strategy.matrix.platform).toEqual(["local"]);
  expect(document.jobs.work.concurrency).toEqual({
    group: "local-build",
    "cancel-in-progress": true,
  });
  expect(document.jobs.work.if).toBe("${{ success() }}");
  expect(document.jobs.work.steps[0].with).toMatchObject({
    "auto-retry": true,
    "retry-limit": 1,
  });
  await page.reload();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .getByRole("navigation", { name: "Workflow job navigation" })
    .getByRole("button", { name: "Work", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", {
      name: "Matrix axes.platform item 1",
      exact: true,
    }),
  ).toHaveValue("local");
  await expect(
    page.getByRole("checkbox", {
      name: "Cancel in-progress work in this group",
    }),
  ).toBeChecked();
});

test("script editing previews the host arguments, saves, executes, and deletes jobs with undo", async ({
  page,
}) => {
  await page.addInitScript(() =>
    sessionStorage.setItem("relay.editor-holder", "script-test"),
  );
  const source = {
    name: "Scripts",
    on: "workflow_dispatch",
    jobs: {
      build: { steps: [{ id: "check", run: "print('old')", shell: "python" }] },
      later: { needs: ["build"], steps: [{ run: "echo later" }] },
    },
  };
  const created = await post(page, "/api/workflows", {
    key: "scripts.yaml",
    holder: "script-test",
    yaml: stringify(source),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  await page.goto("/?view=workflows&workflow=scripts.yaml");
  await page.locator('.react-flow__node[data-id="build"]').click();
  await page.getByRole("tab", { name: "Steps", exact: true }).click();
  const script =
    "import sys\nprint('quoted 王秀英')\nassert sys.version_info.major == 3\n";
  await page.locator('[aria-label="Script"]').fill(script);
  await page.getByText("Process arguments", { exact: true }).click();
  const manifest = await (
    await page.request.get("/api/workflow-language")
  ).json();
  await expect(page.locator(".script-editor").locator("..")).toContainText(
    manifest.host_scripts.python.argv[0],
  );
  await page.getByRole("button", { name: "Close job settings" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
  const saved = await (
    await page.request.get("/api/workflows/scripts.yaml")
  ).json();
  expect(parse(saved.yaml).jobs.build.steps[0]).toMatchObject({
    run: script,
    shell: "python",
  });
  await page.locator('.react-flow__node[data-id="later"]').click();
  await page.getByRole("button", { name: "Close job settings" }).click();
  await page.locator('.react-flow__node[data-id="later"]').focus();
  await page.keyboard.press("Delete");
  await expect(page.locator('.react-flow__node[data-id="later"]')).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(
    page.locator('.react-flow__node[data-id="later"]'),
  ).toBeVisible();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const launched = await post(page, "/api/runs", {
    workflow_key: "scripts.yaml",
    inputs: {},
  });
  expect(launched.status(), await launched.text()).toBe(201);
  const run = (await launched.json()).run_id;
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${run}`)).json()).run.status,
    )
    .toBe("succeeded");
  const events = (
    await (await page.request.get(`/api/runs/${run}/events`)).json()
  ).events;
  expect(
    events.some((event: { payload: { chunk?: string } }) =>
      event.payload.chunk?.includes("quoted 王秀英"),
    ),
  ).toBeTruthy();
});

test("loop and reusable cards expand their child graph and link to the editable source", async ({
  page,
}) => {
  await page.addInitScript(() =>
    sessionStorage.setItem("relay.editor-holder", "linked-test"),
  );
  for (const [key, source] of Object.entries({
    "body.yaml": {
      name: "Loop body",
      on: "workflow_call",
      jobs: { child: { name: "Child", steps: [{ run: "echo child" }] } },
    },
    "linked.yaml": {
      name: "Linked workflows",
      on: "workflow_dispatch",
      jobs: {
        repeat: {
          steps: [
            {
              uses: "relay/loop@v1",
              with: {
                workflow: "./.relay/workflows/body.yaml",
                "max-iterations": "2",
              },
            },
          ],
        },
        reuse: { uses: "./.relay/workflows/body.yaml" },
      },
    },
  })) {
    const response = await post(page, "/api/workflows", {
      key,
      holder: "linked-test",
      yaml: stringify(source),
    });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
  await page.goto("/?view=workflows&workflow=linked.yaml");
  await page
    .getByRole("button", { name: "Expand loop body", exact: true })
    .click();
  await expect(
    page.getByRole("application", { name: "Read-only workflow graph" }),
  ).toContainText("Child");
  await expect(
    page.getByRole("link", { name: "Open loop body to edit" }),
  ).toHaveAttribute("href", /workflow=body.yaml/);
  await page
    .getByRole("button", { name: "Loop body: body.yaml", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Open child workflow", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "Open child workflow to edit" }),
  ).toHaveAttribute("href", /workflow=body.yaml/);
});
