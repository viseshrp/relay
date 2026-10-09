import {
  advancedField,
  openJobSettings,
  closeJobSettings,
} from "./setup-helpers";
import { expect, test, type Page } from "./a11y-test";
import { parse, stringify } from "yaml";
import { post, currentWorkflow, openSettings } from "./setup-helpers";

async function document(page: Page, key = "workflow.yaml") {
  return (await page.request.get(`/api/workflows/${key}`)).json();
}
async function create(page: Page, key: string, name: string, nodes: object) {
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const response = await post(page, "/api/workflows", {
    key,
    holder,
    yaml: stringify(currentWorkflow({ version: 1, name, nodes })),
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}
async function launch(page: Page, key: string): Promise<string> {
  const response = await post(page, "/api/runs", {
    workflow_key: key,
    inputs: {},
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const result: { run_id: string } = await response.json();
  return result.run_id;
}
async function settled(page: Page, id: string, status: string) {
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${id}`)).json()).run.status,
    )
    .toBe(status);
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
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(
    page.getByRole("button", { name: "Add job", exact: true }),
  ).toBeEnabled();
});

test("settings inspection leaves YAML untouched and restoring source replaces the draft", async ({
  page,
}) => {
  const original = await document(page);
  await page
    .getByRole("button", {
      name: "Variables, secrets, environments and library",
      exact: true,
    })
    .click();
  await page.getByRole("dialog").press("Escape");
  await expect(
    page.getByRole("button", { name: "Save", exact: true }),
  ).toBeDisabled();
  expect((await document(page)).yaml).toBe(original.yaml);
  await openJobSettings(page);
  await page.getByLabel("Step name", { exact: true }).fill("Changed draft");
  await closeJobSettings(page);
  await expect
    .poll(async () => (await document(page)).draft?.yaml)
    .toContain("Changed draft");
  await page
    .getByRole("button", { name: "Restore saved source", exact: true })
    .click();
  await expect.poll(async () => (await document(page)).draft).toBeNull();
  const restored = await document(page);
  expect(restored.yaml).toBe(original.yaml);
  expect(restored.base_hash).toBe(original.base_hash);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Save", exact: true }),
  ).toBeDisabled();
});

test("restoring the saved YAML also replaces a previously stored recovery draft", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(
    page.getByRole("button", { name: "Add job", exact: true }),
  ).toBeEnabled();
  const original = await document(page);
  const editor = page.locator('[aria-label="Workflow YAML"]');
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.insertText(
    original.yaml.replace("name:", "name: Changed #"),
  );
  await expect
    .poll(async () => (await document(page)).draft?.yaml)
    .toContain("Changed");
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.insertText(original.yaml);
  await expect
    .poll(async () => (await document(page)).draft?.yaml)
    .toBe(original.yaml);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Save", exact: true }),
  ).toBeDisabled();
});

test("workflow history filters persist in the URL and Back restores run and job views", async ({
  page,
}) => {
  await create(page, "audit-a", "Audit A", {
    check: { type: "command", run: ["git", "status"] },
  });
  await create(page, "audit-b", "Audit B", {
    check: { type: "command", run: ["git", "status"] },
  });
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const id = await launch(page, "audit-a");
  await settled(page, id, "succeeded");
  await page.goto("/?view=runs&workflow=audit-a.yaml");
  await expect(
    page.getByRole("heading", { name: "Audit A", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Audit A", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Workflow sidebar" })
    .getByRole("link", { name: "All workflows", exact: true })
    .click();
  await expect(page).not.toHaveURL(/workflow=/);
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Audit A", exact: true }),
  ).toBeVisible();
  await openSettings(page);
  await expect(
    page.getByRole("heading", { name: "Global defaults", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Audit A", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: /^Audit.a #/i }).click();
  await expect(page).toHaveURL(new RegExp(`run=${id}`));
  await page
    .getByRole("navigation", { name: "Jobs", exact: true })
    .getByRole("link", { name: /^check / })
    .click();
  await expect(page).toHaveURL(/job=root/);
  await page.goBack();
  await expect(
    page.getByRole("region", { name: "Job log", exact: true }),
  ).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`run=${id}`));
  await page.goForward();
  await expect(
    page.getByRole("region", { name: "Job log", exact: true }),
  ).toBeVisible();
});

test("human reviews and unstarted jobs have accurate log labels and empty states", async ({
  page,
}) => {
  await create(page, "audit-wait", "Audit waiting", {
    approval: { type: "human_wait", prompt: "Review the result." },
    later: { type: "command", needs: ["approval"], run: ["git", "status"] },
  });
  const id = await launch(page, "audit-wait");
  await settled(page, id, "paused_wait");
  await page.goto(`/?view=runs&run=${id}&job=root.approval.step_1`);
  const log = page.getByRole("region", { name: "Job log", exact: true });
  await expect(
    log.getByRole("button", { name: "Human review", exact: true }),
  ).toBeVisible();
  await expect(
    log.getByRole("button", { name: "Agent conversation", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Jobs", exact: true })
    .getByRole("link", { name: /^later / })
    .click();
  await expect(
    log.getByText("No attempt has started yet.", { exact: true }),
  ).toBeVisible();
  await expect(log.getByText(/Incomplete/)).toHaveCount(0);
  await expect(
    log.getByRole("button", { name: "Retry log history", exact: true }),
  ).toHaveCount(0);
  await expect(
    log.getByRole("button", { name: "Stop following", exact: true }),
  ).toHaveCount(0);
  expect(
    (
      await post(page, `/api/runs/${id}/cancel`, {
        idempotency_key: "audit-cleanup",
      })
    ).ok(),
  ).toBeTruthy();
});

test("a named script step opens its terminal output", async ({ page }) => {
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const response = await post(page, "/api/workflows", {
    key: "script-log",
    holder,
    yaml: stringify({
      name: "Script log",
      on: "workflow_dispatch",
      jobs: {
        check: {
          steps: [
            {
              id: "script",
              name: "Visible command",
              run: "echo Captured terminal output",
            },
          ],
        },
      },
    }),
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const id = await launch(page, "script-log");
  await settled(page, id, "succeeded");
  await page.goto(`/?view=runs&run=${id}&job=root.check.script`);
  const log = page.getByRole("region", { name: "Job log", exact: true });
  await expect(
    log.getByRole("heading", { name: "Visible command", exact: true }),
  ).toBeVisible();
  await expect(
    log.getByRole("button", { name: "Command output", exact: true }),
  ).toBeVisible();
  await expect(
    log.getByRole("region", { name: "Command output lines", exact: true }),
  ).toContainText("Captured terminal output");
});

test("Workflow file shows frozen source and empty internal artifacts remain hidden", async ({
  page,
}) => {
  await create(page, "audit-frozen", "Original source", {
    check: { type: "command", run: ["git", "status"] },
  });
  const id = await launch(page, "audit-frozen");
  await settled(page, id, "succeeded");
  const original = await document(page, "audit-frozen.yaml");
  const saved = await post(page, "/api/workflows/audit-frozen.yaml/save", {
    holder: await page.evaluate(() =>
      sessionStorage.getItem("relay.editor-holder"),
    ),
    base_hash: original.base_hash,
    yaml: original.yaml.replace("Original source", "Edited source"),
  });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  await page.goto(`/?view=runs&run=${id}`);
  await page
    .getByRole("button", { name: "Workflow file", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Workflow file",
    exact: true,
  });
  await expect(
    dialog.getByLabel("Captured workflow YAML", { exact: true }),
  ).toContainText("Original source");
  await expect(
    dialog.getByLabel("Captured workflow YAML", { exact: true }),
  ).not.toContainText("Edited source");
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Workflow file", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("table", { name: "Retained artifacts", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText(
      "No artifacts yet. Add relay/upload-artifact to a step to save a file.",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Workflow file", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Edit current workflow", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Workflow header", exact: true }),
  ).toContainText("Edited source");
});

test("the project dialog browses isolated directories and selects a repository", async ({
  page,
}) => {
  await page.goto("/?view=workflows");
  await page
    .getByRole("button", { name: "Open another project", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Open a project",
    exact: true,
  });
  const browser = dialog.getByRole("region", {
    name: "Browse repository folders",
    exact: true,
  });
  await expect(
    browser.getByRole("button", { name: "repo Git repository", exact: true }),
  ).toBeEnabled();
  await browser
    .getByRole("button", { name: "repo Git repository", exact: true })
    .click();
  await expect(
    browser.getByRole("button", { name: "Use this folder", exact: true }),
  ).toBeEnabled();
  await browser
    .getByRole("button", { name: "Use this folder", exact: true })
    .click();
  await expect(
    dialog.getByRole("textbox", { name: "Repository folder", exact: true }),
  ).toHaveValue(/repo$/);
  await expect(
    dialog.getByRole("button", { name: "Open project", exact: true }),
  ).toBeEnabled();
  await dialog
    .getByRole("button", { name: "Open project", exact: true })
    .click();
  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole("region", { name: "Workflow header", exact: true }),
  ).toBeVisible();
});

for (const type of ["condition", "loop", "subworkflow"] as const) {
  test(`Add a job saves and runs a ${type} workflow`, async ({ page }) => {
    const childKey = `audit-child-${type}`;
    const childYaml = stringify({
      on: { workflow_call: {} },
      jobs: { check: { steps: [{ run: "git status --short" }] } },
    });
    if (type !== "condition")
      expect(
        (
          await post(page, "/api/workflows", {
            key: childKey,
            holder: "audit-create",
            yaml: childYaml,
          })
        ).ok(),
      ).toBeTruthy();
    const key = `audit-add-${type}`;
    await create(page, key, `Create ${type}`, {
      base: { type: "command", run: ["git", "status"] },
    });
    await page.goto(`/?view=workflows&workflow=${key}.yaml`);
    await page.getByRole("button", { name: "Add job", exact: true }).click();
    await openJobSettings(page, type === "loop" ? "Steps" : "General");
    if (type === "condition")
      await page.getByLabel("Job condition", { exact: true }).fill("true");
    if (type === "subworkflow")
      await page
        .getByLabel("Reusable workflow", { exact: true })
        .fill(`./.relay/workflows/${childKey}.yaml`);
    if (type === "loop") {
      await page
        .getByLabel("Action reference", { exact: true })
        .fill("relay/loop@v1");
      const inputs = await advancedField(page, "Action inputs");
      await inputs.fill(
        JSON.stringify({
          workflow: `./.relay/workflows/${childKey}.yaml`,
          "max-iterations": 1,
        }),
      );
      await inputs.blur();
    }
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(
      page.getByText("Workflow and instructions saved and validated.", {
        exact: true,
      }),
    ).toBeVisible();
    const saved = parse((await document(page, `${key}.yaml`)).yaml);
    expect(saved.jobs.job_1).toBeDefined();
    const id = await launch(page, key);
    await settled(page, id, "succeeded");
  });
}
