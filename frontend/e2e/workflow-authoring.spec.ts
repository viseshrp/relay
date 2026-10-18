import { expect, test, type Page } from "./a11y-test";
import {
  closeJobSettings,
  openAdvanced,
  openJobSettings,
  post,
} from "./setup-helpers";
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
}, testInfo) => {
  const promptFile = `smoke-${testInfo.repeatEachIndex}.md`;
  const promptReference = `prompts/${promptFile}`;
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
  // Finish the drawer's entrance before selecting a tab inside it.
  await page.getByRole("dialog").evaluate(async (dialog) => {
    await Promise.all(
      dialog
        .getAnimations({ subtree: true })
        .filter(
          (animation) =>
            animation.effect?.getComputedTiming().iterations !== Infinity,
        )
        .map((animation) => animation.finished.catch(() => undefined)),
    );
  });
  await page.getByRole("tab", { name: "Steps", exact: true }).click();
  await expect(
    page.getByRole("tab", { name: "Steps", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page
    .getByRole("textbox", { name: "New prompt file", exact: true })
    .fill(promptFile);
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
          .draft?.prompts?.[promptReference]?.text,
    )
    .toContain("First instructions");
  await page.reload();
  await expect(page.getByText(/Unsaved changes:/)).toContainText(
    promptReference,
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Workflow", exact: true }),
  ).toHaveText("Authoring smoke");
  await expect(
    page
      .getByRole("navigation", { name: "Workflow sidebar" })
      .getByRole("link", { name: /Authoring smoke/ }),
  ).toBeVisible();
  const source = await (
    await page.request.get("/api/workflows/workflow.yaml")
  ).json();
  expect(source.yaml).toContain(`prompt-files: ${promptReference}`);
  expect(source.yaml).toContain("task:");
  const prompt = await (
    await page.request.get(
      `/api/workflows/workflow.yaml/prompt?reference=${promptReference}`,
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
  const creatingRun = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/runs" &&
      response.request().method() === "POST",
  );
  await launch
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const createdRun = await creatingRun;
  expect(createdRun.status(), await createdRun.text()).toBe(201);
  // Start the unchanged completion deadline after launch persistence finishes.
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
      { exact: true },
    ),
  ).toBeVisible();
});

test("warnings appear beside the editor without blocking save", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .locator(".cm-content")
    .fill(
      "name: Warnings\njobs:\n  check:\n    steps:\n      - run: echo ${{ inputs.missing }}\n",
    );
  const warning = page.locator(".MuiAlert-colorWarning");
  await expect(warning).toHaveCount(1);
  await expect(warning).toHaveText(
    /Line 5: jobs\.check\.steps\[0\]\.run: inputs\.missing is not a declared input\. It will be empty at run time\./,
  );
  await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
  await expect(page.locator(".cm-lintRange-warning")).toHaveCount(1);
  await expect(warning.getByRole("button", { name: "Open job" })).toBeVisible();
  const save = page.getByRole("button", { name: "Save", exact: true });
  await expect(save).toBeEnabled();
  await save.click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
  const source = await (
    await page.request.get("/api/workflows/workflow.yaml")
  ).json();
  expect(source.yaml).toContain("${{ inputs.missing }}");
});

// Relay ships one command version; the browser-test server registers a
// stand-in relay/command@v2 beside it until the next reset.
const OLDER_COMMAND =
  "name: Versions\non: workflow_dispatch\njobs:\n  check:\n    steps:\n" +
  "      # Print a greeting.\n      - uses: relay/command@v1\n" +
  '        with:\n          argv: \'["echo","Ready"]\'\n';
const UPDATED_STEP =
  "Updated step 1 in job check from relay/command@v1 to relay/command@v2.";

test("a deprecated step shows the older-version notice", async ({ page }) => {
  await post(page, "/__test__/builtin-versions", { mode: "deprecated" });
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const editor = page.locator(".cm-content");
  await editor.fill(OLDER_COMMAND);
  const warning = page.locator(".MuiAlert-colorWarning");
  await expect(warning).toHaveCount(1);
  await expect(warning).toHaveText(
    /Line 7: jobs\.check\.steps\[0\]\.uses: relay\/command@v1 is deprecated and will be removed in a later Relay release\. Use relay\/command@v2\./,
  );
  await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Save", exact: true }),
  ).toBeEnabled();
  await openJobSettings(page);
  const drawer = page.getByRole("dialog", { name: /^Job settings: / });
  const notice = drawer.locator(".MuiAlert-colorInfo").filter({
    hasText: "This step uses an older version of Command.",
  });
  await expect(notice).toBeVisible();
  await expect(
    notice.getByRole("button", { name: "Update to current versions" }),
  ).toBeVisible();
  const stepType = drawer.getByRole("combobox", {
    name: "Step type",
    exact: true,
  });
  await expect(stepType).toHaveText("Command (older version)");
  await stepType.click();
  await expect(
    page.getByRole("option").filter({ hasText: "Command (older version)" }),
  ).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  // New steps use only the current version.
  await drawer.getByRole("button", { name: "Add step", exact: true }).click();
  await page
    .getByRole("menu")
    .getByRole("menuitem")
    .filter({ has: page.getByText("Command", { exact: true }) })
    .click();
  await expect(editor).toContainText("uses: relay/command@v2");
  await closeJobSettings(page);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
});

test("update to current versions rewrites the draft", async ({ page }) => {
  await post(page, "/__test__/builtin-versions", { mode: "deprecated" });
  const read = async () =>
    (
      (await (
        await page.request.get("/api/workflows/workflow.yaml")
      ).json()) as {
        yaml: string;
      }
    ).yaml;
  const saved = await read();
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const editor = page.locator(".cm-content");
  await editor.fill(OLDER_COMMAND);
  await expect(page.locator(".MuiAlert-colorWarning")).toHaveCount(1);
  const update = page.getByRole("button", {
    name: "Update to current versions",
    exact: true,
  });
  await update.click();
  const dialog = page.getByRole("dialog", {
    name: "Updated to current versions",
  });
  await expect(dialog.getByRole("list", { name: "Changes" })).toHaveText(
    UPDATED_STEP,
  );
  await expect(dialog.getByRole("list", { name: "Check by hand" })).toHaveCount(
    0,
  );
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(editor).toContainText("uses: relay/command@v2");
  await expect(editor).toContainText("# Print a greeting.");
  await expect(page.locator(".MuiAlert-colorWarning")).toHaveCount(0);
  await expect(update).toHaveCount(0);
  // The update is an unsaved draft: the saved source is unchanged.
  expect(await read()).toBe(saved);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(editor).toContainText("uses: relay/command@v1");
  await expect(page.locator(".MuiAlert-colorWarning")).toHaveCount(1);
  expect(await read()).toBe(saved);
});

test("a removed version names its replacement and updates in one click", async ({
  page,
}) => {
  await post(page, "/__test__/builtin-versions", { mode: "removed" });
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const editor = page.locator(".cm-content");
  await editor.fill(OLDER_COMMAND);
  const error = page.locator(".MuiAlert-colorError");
  await expect(error).toHaveCount(1);
  await expect(error).toHaveText(
    /Line 7: jobs\.check\.steps\[0\]\.uses: Only frozen local and versioned relay actions are supported\. relay\/command@v1 was removed in Relay 0\.0\.0; use relay\/command@v2\./,
  );
  const save = page.getByRole("button", { name: "Save", exact: true });
  await expect(save).toBeDisabled();
  await page
    .getByRole("button", { name: "Update to current versions", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Updated to current versions",
  });
  await expect(dialog.getByRole("list", { name: "Changes" })).toHaveText(
    UPDATED_STEP,
  );
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(editor).toContainText("uses: relay/command@v2");
  await expect(error).toHaveCount(0);
  await expect(save).toBeEnabled();
});

async function openYamlEditor(page: Page) {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Editor mode" }).click();
  await page.getByRole("option", { name: "YAML", exact: true }).click();
  return page.locator(".cm-content");
}

/** Replace the YAML, then type the last part so completion sees typing. */
async function typeYaml(page: Page, source: string, typed: string) {
  await page.locator(".cm-content").fill(source);
  await page.keyboard.press("ControlOrMeta+End");
  await page.keyboard.type(typed);
}

test("YAML completion offers only fields valid at the cursor", async ({
  page,
}) => {
  await openYamlEditor(page);
  const options = page.locator(".cm-tooltip-autocomplete [role=option]");
  const source =
    "name: Completion\non:\n  workflow_dispatch:\n    inputs:\n      task: {type: string}\njobs:\n  work:\n    steps:\n      - run: echo Ready\n";
  await typeYaml(page, source, "      - ru");
  await expect(options).toHaveText(["run"]);
  await typeYaml(page, source, "ru");
  await expect(options).toHaveText(["run-name"]);
  await typeYaml(page, source, "    ti");
  await expect(options).toHaveText(["timeout-minutes"]);
  await typeYaml(
    page,
    `${source}      - uses: relay/agent@v1\n        with:\n`,
    "          mo",
  );
  await expect(options).toHaveText(["model"]);
  await typeYaml(page, source, "      - run: echo ${{ inp");
  await expect(options).toHaveText(["inputs.task"]);
  await page.keyboard.press("Escape");
  await expect(options).toHaveCount(0);
});

test("Ctrl+Space after uses lists the built-in actions", async ({ page }) => {
  const { builtins } = await (
    await page.request.get("/api/workflow-language")
  ).json();
  const editor = await openYamlEditor(page);
  await editor.fill(
    "name: Actions\non: workflow_dispatch\njobs:\n  work:\n    steps:\n      - uses: ",
  );
  await page.keyboard.press("ControlOrMeta+End");
  await page.keyboard.press("Control+Space");
  const options = page.locator(".cm-tooltip-autocomplete [role=option]");
  await expect(options).toHaveText(
    [...builtins].sort().concat("./.relay/actions/"),
  );
  await options.filter({ hasText: "human-wait" }).click();
  await expect(options).toHaveCount(0);
  await expect(editor).toContainText("uses: relay/human-wait@v1");
  await expect(editor).toContainText("with:");
  await expect(editor).toContainText("prompt:");
});

test("clearing the YAML explains the empty workflow", async ({ page }) => {
  const editor = await openYamlEditor(page);
  await page.getByRole("combobox", { name: "Editor mode" }).click();
  await page.getByRole("option", { name: "Split", exact: true }).click();
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.press("Delete");
  const status = page.getByText("This workflow is empty.", { exact: true });
  await expect(status).toBeVisible({ timeout: 2000 });
  const empty = page.getByRole("alert").filter({
    hasText: "This workflow is empty. Restore the saved source or add a job.",
  });
  await expect(empty).toBeVisible();
  await expect(
    empty.getByRole("button", { name: "Restore saved source" }),
  ).toBeEnabled();
  for (const mode of ["Visual", "YAML"]) {
    await page.getByRole("combobox", { name: "Editor mode" }).click();
    await page.getByRole("option", { name: mode, exact: true }).click();
    await expect(empty).toBeVisible();
  }
  await expect(page.getByText("Validating workflow…")).toHaveCount(0);
  await empty.getByRole("button", { name: "Add a job" }).click();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await expect(empty).toHaveCount(0);
  await expect(editor).toContainText("name: Configuration");
  await expect(editor).toContainText("- run: echo Ready");
  await editor.fill("jobs:\n  work:\n    stpes: []\n");
  await expect(
    page.getByText("Fix the problems above to save.", { exact: true }),
  ).toBeVisible();
});

test("inventory refresh failure preserves save success and the next save base", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Workflow settings", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Workflow name", exact: true })
    .fill("Saved despite inventory failure");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  const inventory = /\/api\/workflows(?:\?.*)?$/;
  await page.route(inventory, (route) => {
    return route.fulfill({
      status: 503,
      json: {
        code: "inventory_unavailable",
        message: "Inventory temporarily unavailable.",
        context: {},
      },
    });
  });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
  const warning = page
    .getByRole("alert")
    .filter({ hasText: "The workflow list could not refresh." });
  await expect(warning).toBeVisible();
  await expect(page.getByText(/Unsaved changes:/)).toHaveCount(0);
  const saved = await (
    await page.request.get("/api/workflows/workflow.yaml")
  ).json();
  expect(parse(saved.yaml).name).toBe("Saved despite inventory failure");
  expect(saved.draft).toBeNull();
  await page.unroute(inventory);
  await page
    .getByRole("button", { name: "Workflow settings", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Workflow name", exact: true })
    .fill("Inventory recovered");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  const saving = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname ===
        "/api/workflows/workflow.yaml/save" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const response = await saving;
  expect(response.request().postDataJSON().base_hash).toBe(saved.base_hash);
  expect(response.status(), await response.text()).toBe(200);
  await expect(
    page.getByRole("combobox", { name: "Workflow", exact: true }),
  ).toHaveText("Inventory recovered");
  await expect(warning).toHaveCount(0);
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
  await openAdvanced(page);
  // Matrix jobs run one at a time, so the form offers no max-parallel field.
  await expect(page.getByText("Relay runs them one at a time")).toBeVisible();
  await expect(page.getByLabel(/parallel/i)).toHaveCount(0);
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
    .getByRole("button", {
      name: "Change type of Matrix axes.platform",
      exact: true,
    })
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
    .getByRole("button", { name: "Build a condition", exact: true })
    .click();
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
  // Advanced opens by itself once one of its fields has a value.
  await expect(
    page.getByRole("button", { name: "Advanced", exact: true }),
  ).toHaveAttribute("aria-expanded", "true");
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
    JSON.stringify(manifest.host_scripts.python.argv[0]),
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
  // Both successful jobs commit before the run reaches its terminal state.
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${run}`)).json()).run.status,
      { timeout: 15_000 },
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

// The step types in the order and words the editor offers them.
const STEP_TYPES = [
  "Agent",
  "Script",
  "Command",
  "Approval",
  "Check a report",
  "Check a value",
  "Upload artifact",
  "Download artifact",
  "Cache",
  "Restore cache",
  "Save cache",
  "Repeat a workflow",
];

async function chooseType(page: Page, select: string, label: string) {
  await page.getByRole("combobox", { name: select, exact: true }).click();
  await page
    .getByRole("option")
    .filter({ has: page.getByText(label, { exact: true }) })
    .click();
  await expect(page.getByRole("listbox")).toHaveCount(0);
}

/** Run an edit and return the server's verdict on the YAML it produced. */
async function validation(
  page: Page,
  edit: () => Promise<void>,
): Promise<{ valid: boolean; diagnostics: unknown[]; yaml: string }> {
  const response = page.waitForResponse(
    (item) =>
      new URL(item.url()).pathname === "/api/workflow-language/validate",
  );
  await edit();
  const done = await response;
  return {
    ...(await done.json()),
    yaml: done.request().postDataJSON().yaml,
  };
}

/** Create a workflow for this test under a key no other run has used. */
async function createWorkflow(
  page: Page,
  name: string,
  source: object,
): Promise<string> {
  const key = `${name}-${Date.now()}.yaml`;
  await page.addInitScript(() =>
    sessionStorage.setItem("relay.editor-holder", "visual-editor"),
  );
  const created = await post(page, "/api/workflows", {
    key,
    holder: "visual-editor",
    yaml: stringify(source),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  return key;
}

const yamlEditor = (page: Page) => page.locator('[aria-label="Workflow YAML"]');

test("a new command job shows the same arguments in the form and the YAML", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await chooseType(page, "New job type", "Command");
  const result = await validation(page, () =>
    page.getByRole("button", { name: "Add job", exact: true }).click(),
  );
  expect(result).toMatchObject({ valid: true, diagnostics: [] });
  const drawer = page.getByRole("dialog", { name: /^Job settings: / });
  await expect(
    drawer.getByRole("tab", { name: "Steps", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  for (const [index, value] of ["echo", "Ready"].entries())
    await expect(
      drawer.getByRole("textbox", {
        name: `Program and arguments item ${index + 1}`,
        exact: true,
      }),
    ).toHaveValue(value);
  await expect(drawer.getByRole("alert")).toHaveCount(0);
  expect(result.yaml).toContain(`argv: '["echo","Ready"]'`);
  await closeJobSettings(page);
  await expect(yamlEditor(page)).toContainText(`argv: '["echo","Ready"]'`);
  await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
});

test("a command step with unreadable arguments says so instead of an empty list", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .locator(".cm-content")
    .fill(
      "name: Broken arguments\njobs:\n  run:\n    steps:\n      - uses: relay/command@v1\n        with:\n          argv: '[\"echo\",'\n",
    );
  await expect(
    page.getByText("Fix the problems above to save.", { exact: true }),
  ).toBeVisible();
  await openJobSettings(page);
  const drawer = page.getByRole("dialog", { name: /^Job settings: / });
  await expect(drawer.getByRole("alert")).toHaveText(
    "This argument list is not valid. Fix it in YAML or replace it here.",
  );
  await drawer
    .getByRole("button", { name: "Add Program and arguments item" })
    .click();
  await drawer
    .getByRole("textbox", { name: "Program and arguments item 1" })
    .fill("git");
  await expect(drawer.getByRole("alert")).toHaveCount(0);
  await closeJobSettings(page);
  await expect(yamlEditor(page)).toContainText(`argv: '["git"]'`);
});

test("every new job type validates as soon as it is added", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  for (const label of STEP_TYPES.filter(
    (item) => item !== "Repeat a workflow",
  )) {
    await chooseType(page, "New job type", label);
    const result = await validation(page, () =>
      page.getByRole("button", { name: "Add job", exact: true }).click(),
    );
    expect(result, label).toMatchObject({ valid: true, diagnostics: [] });
    await closeJobSettings(page);
    await expect(
      page.getByText("Ready to edit", { exact: true }),
    ).toBeVisible();
    await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
  }
});

test("a new loop job repeats the workflow chosen in its dialog", async ({
  page,
}) => {
  const body = await createWorkflow(page, "repeat-body", {
    name: "Repeat body",
    on: "workflow_call",
    jobs: { check: { steps: [{ run: "echo again" }] } },
  });
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await chooseType(page, "New job type", "Repeat a workflow");
  await page.getByRole("button", { name: "Add job", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "Choose the workflow to repeat",
  });
  await dialog
    .getByRole("combobox", { name: "Workflow to repeat", exact: true })
    .click();
  await page
    .getByRole("option", { name: `Repeat body (${body})`, exact: true })
    .click();
  const result = await validation(page, () =>
    dialog
      .getByRole("button", { name: "Repeat this workflow", exact: true })
      .click(),
  );
  expect(result).toMatchObject({ valid: true, diagnostics: [] });
  const job = parse(result.yaml).jobs.job_1;
  expect(job.steps[0].with).toEqual({
    workflow: `./.relay/workflows/${body}`,
    "max-iterations": "3",
  });
  await expect(dialog).toHaveCount(0);
});

test("Add step inserts each primary step type", async ({ page }) => {
  const { builtin_versions: versions } = await (
    await page.request.get("/api/workflow-language")
  ).json();
  const reference = (name: string) =>
    Object.entries(
      versions as Record<string, { name: string; status: string }>,
    ).find(([, item]) => item.name === name && item.status === "current")?.[0];
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await openJobSettings(page);
  const primary: Array<[string, string | null]> = [
    ["Agent", "agent"],
    ["Script", null],
    ["Command", "command"],
    ["Approval", "human-wait"],
    ["Check a report", "validate-report"],
    ["Upload artifact", "upload-artifact"],
  ];
  for (const [offset, [label, name]] of primary.entries()) {
    await page.getByRole("button", { name: "Add step", exact: true }).click();
    const menu = page.getByRole("menu");
    await expect(menu.getByText("More", { exact: true })).toBeVisible();
    const result = await validation(page, () =>
      menu
        .getByRole("menuitem")
        .filter({ has: page.getByText(label, { exact: true }) })
        .click(),
    );
    expect(result, label).toMatchObject({ valid: true, diagnostics: [] });
    const step = parse(result.yaml).jobs.work.steps[offset + 1];
    if (name) expect(step.uses, label).toBe(reference(name));
    else expect(step).toEqual({ run: "echo Ready" });
    await expect(
      page
        .getByRole("list", { name: "Steps in this job" })
        .getByRole("button", { name: new RegExp(`^${offset + 2}\\. `) }),
    ).toHaveClass(/Mui-selected/);
  }
});

test("a job's steps appear as a list in the drawer and on the card", async ({
  page,
}) => {
  const key = await createWorkflow(page, "step-list", {
    name: "Step list",
    on: "workflow_dispatch",
    jobs: {
      build: {
        steps: [
          { name: "First", run: "echo 1" },
          { id: "second", run: "echo 2" },
          { run: "echo third\necho more" },
        ],
      },
    },
  });
  await page.goto(`/?view=workflows&workflow=${key}`);
  const card = page.locator('.react-flow__node[data-id="build"]');
  await expect(card.locator("li")).toHaveText([
    "First",
    "second",
    "echo third",
  ]);
  await openJobSettings(page);
  const rows = page
    .getByRole("list", { name: "Steps in this job" })
    .getByRole("listitem");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("1. First");
  await expect(rows.nth(1)).toContainText("2. second");
  await expect(rows.nth(2)).toContainText("3. echo third");
  await expect(rows.nth(2)).toContainText("Script");
  await page
    .getByRole("button", { name: "Move step 3 earlier", exact: true })
    .click();
  await expect(rows.nth(1)).toContainText("2. echo third");
  await closeJobSettings(page);
  await expect(card.locator("li")).toHaveText([
    "First",
    "echo third",
    "second",
  ]);
  const text = (await yamlEditor(page).textContent()) ?? "";
  expect(text.indexOf("echo third")).toBeLessThan(text.indexOf("id: second"));
});

test("step type menus use plain labels", async ({ page }) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  async function expectPlain(select: string) {
    await page.getByRole("combobox", { name: select, exact: true }).click();
    const options = page.getByRole("option");
    await expect(options.locator(".MuiListItemText-primary")).toHaveText(
      STEP_TYPES,
    );
    for (const text of await options.allTextContents()) {
      expect(text).not.toMatch(/^relay\//);
      expect(text).not.toMatch(/@v1$/);
    }
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox")).toHaveCount(0);
  }
  await expectPlain("New job type");
  await openJobSettings(page);
  await expectPlain("Step type");
  await expect(
    page.getByRole("combobox", { name: "Step type", exact: true }),
  ).toHaveText("Agent");
  await expect(
    page.getByLabel("Action reference", { exact: true }),
  ).toBeHidden();
  await closeJobSettings(page);
  await expect(page.locator(".editor-graph-node")).not.toContainText("relay/");
});

test("new jobs open on Steps and General shows the basics first", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add job", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Job settings: job_1" });
  await expect(
    drawer.getByRole("tab", { name: "Steps", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await drawer.getByRole("tab", { name: "General", exact: true }).click();
  for (const name of [
    "Job name",
    "Job ID",
    "Job condition",
    "Job timeout (minutes)",
  ])
    await expect(
      drawer.getByRole("textbox", { name, exact: true }),
    ).toBeVisible();
  await expect(
    drawer.getByRole("combobox", { name: "Start after", exact: true }),
  ).toBeVisible();
  const later = [
    drawer.getByRole("textbox", { name: "Reusable workflow", exact: true }),
    drawer.getByRole("textbox", { name: "Concurrency group", exact: true }),
    drawer.getByRole("combobox", {
      name: "Job condition expression helper",
      exact: true,
    }),
  ];
  for (const field of later) await expect(field).toBeHidden();
  await drawer
    .getByRole("button", { name: "Build a condition", exact: true })
    .click();
  await expect(later[2]).toBeVisible();
  await openAdvanced(page);
  await expect(later[0]).toBeVisible();
  await expect(later[1]).toBeVisible();
  await closeJobSettings(page);
  await page
    .getByRole("navigation", { name: "Workflow job navigation" })
    .getByRole("button", { name: "Work", exact: true })
    .click();
  const work = page.getByRole("dialog", { name: "Job settings: work" });
  await expect(
    work.getByRole("tab", { name: "General", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await work.getByRole("tab", { name: "Steps", exact: true }).click();
  await expect(
    work.getByRole("button", { name: "Advanced JSON: Action inputs" }),
  ).toBeHidden();
});

test("condition helpers offer only expressions that validate", async ({
  page,
}) => {
  const source = {
    name: "Conditions",
    on: {
      workflow_dispatch: { inputs: { task: { type: "string" } } },
    },
    env: { MODE: "local" },
    jobs: {
      first: { outputs: { x: "ready" }, steps: [{ id: "s", run: "echo" }] },
      second: {
        needs: ["first"],
        env: { LEVEL: "1" },
        steps: [
          { id: "ask", uses: "relay/human-wait@v1", with: { prompt: "Go?" } },
          { run: "echo done" },
        ],
      },
    },
  };
  const key = await createWorkflow(page, "conditions", source);
  await page.goto(`/?view=workflows&workflow=${key}`);
  await page
    .getByRole("navigation", { name: "Workflow job navigation" })
    .getByRole("button", { name: "Second", exact: true })
    .click();
  async function offered(label: string): Promise<string[]> {
    await page
      .getByRole("tabpanel")
      .getByRole("button", { name: "Build a condition", exact: true })
      .click();
    await page
      .getByRole("combobox", { name: `${label} expression helper` })
      .click();
    const options = await page.getByRole("option").allTextContents();
    await page.keyboard.press("Escape");
    return options;
  }
  async function expectValid(
    options: string[],
    place: (value: string) => object,
  ) {
    expect(options).not.toContain("${{ relay.project_id }}");
    for (const option of options) {
      const result = await post(page, "/api/workflow-language/validate", {
        yaml: stringify(place(option)),
        source: key,
      });
      expect(await result.json(), option).toMatchObject({ valid: true });
    }
  }
  const job = await offered("Job condition");
  expect(job).toEqual(
    expect.arrayContaining([
      "${{ needs.first.outputs.x }}",
      "${{ inputs.task }}",
    ]),
  );
  expect(job.some((item) => item.includes("steps."))).toBe(false);
  await expectValid(job, (value) => ({
    ...source,
    jobs: { ...source.jobs, second: { ...source.jobs.second, if: value } },
  }));
  await page.getByRole("tab", { name: "Steps", exact: true }).click();
  await page
    .getByRole("list", { name: "Steps in this job" })
    .getByRole("button", { name: /^2\. / })
    .click();
  const step = await offered("Step condition");
  expect(step).toEqual(
    expect.arrayContaining([
      "${{ steps.ask.outputs.answer }}",
      "${{ env.LEVEL }}",
      "${{ job.status }}",
    ]),
  );
  await expectValid(step, (value) => ({
    ...source,
    jobs: {
      ...source.jobs,
      second: {
        ...source.jobs.second,
        steps: [source.jobs.second.steps[0], { run: "echo done", if: value }],
      },
    },
  }));
});

test("dependencies show job names and job IDs can be renamed safely", async ({
  page,
}) => {
  const key = await createWorkflow(page, "rename", {
    name: "Rename",
    on: "workflow_dispatch",
    jobs: {
      check: { outputs: { x: "ready" }, steps: [{ run: "echo check" }] },
      later: {
        needs: ["check"],
        steps: [{ run: "echo ${{ needs.check.outputs.x }}" }],
      },
    },
  });
  await page.goto(`/?view=workflows&workflow=${key}`);
  const jobs = page.getByRole("navigation", {
    name: "Workflow job navigation",
  });
  await jobs.getByRole("button", { name: "Check", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Job name", exact: true })
    .fill("Review");
  await closeJobSettings(page);
  await jobs.getByRole("button", { name: "Later", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Start after", exact: true })
    .click();
  await expect(page.getByRole("option")).toHaveText(["Review (check)"]);
  await page.keyboard.press("Escape");
  await closeJobSettings(page);
  await jobs.getByRole("button", { name: "Review", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Job settings: Review" });
  await expect(
    drawer.getByRole("textbox", { name: "Job ID", exact: true }),
  ).toHaveValue("check");
  await drawer
    .getByRole("button", { name: "Rename job ID", exact: true })
    .click();
  const rename = page.getByRole("dialog", { name: "Rename job ID" });
  const field = rename.getByRole("textbox", { name: "New job ID" });
  await field.fill("later");
  await expect(rename).toContainText("Another job already uses this ID.");
  await field.fill("9review");
  await expect(
    rename.getByRole("button", { name: "Rename", exact: true }),
  ).toBeDisabled();
  await field.fill("review");
  await rename.getByRole("button", { name: "Rename", exact: true }).click();
  await expect(
    drawer.getByRole("textbox", { name: "Job ID", exact: true }),
  ).toHaveValue("review");
  await closeJobSettings(page);
  await expect(yamlEditor(page)).toContainText("${{ needs.review.outputs.x }}");
  const renamed = parse(
    await yamlEditor(page).evaluate((element) =>
      [...element.querySelectorAll(".cm-line")]
        .map((line) => line.textContent)
        .join("\n"),
    ),
  );
  expect(Object.keys(renamed.jobs)).toEqual(["review", "later"]);
  expect(renamed.jobs.later.needs).toEqual(["review"]);
  expect(renamed.jobs.later.steps[0].run).toBe(
    "echo ${{ needs.review.outputs.x }}",
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(yamlEditor(page)).toContainText("${{ needs.check.outputs.x }}");
  await expect(yamlEditor(page)).not.toContainText("review:");
});

test("closing the drawer keeps every card in view", async ({ page }) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add job", exact: true }).click();
  await closeJobSettings(page);
  const canvas = page.locator(".flow-canvas");
  await expect(page.locator(".editor-graph-node")).toHaveCount(2);
  await expect
    .poll(async () => {
      const bounds = await canvas.boundingBox();
      if (!bounds) return false;
      for (const card of await page.locator(".editor-graph-node").all()) {
        const box = await card.boundingBox();
        if (
          !box ||
          box.x < bounds.x ||
          box.y < bounds.y ||
          box.x + box.width > bounds.x + bounds.width ||
          box.y + box.height > bounds.y + bounds.height
        )
          return false;
      }
      return true;
    })
    .toBe(true);
});
