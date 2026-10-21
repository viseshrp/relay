import { parse } from "yaml";
import { expect, test } from "./a11y-test";
import {
  chooseAgent,
  closeJobSettings,
  expectRunStatus,
  openJobSettings,
  post,
} from "./setup-helpers";

// Follows docs/build-your-first-workflow.md step by step, with its labels.
test("following Build your first workflow produces a successful run", async ({
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
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  // A disposable repository with Codex and a passing `python -m pytest`.
  expect((await post(page, "/__test__/starter-project")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");

  // 1. Create a blank workflow.
  await page.getByRole("button", { name: "New workflow", exact: true }).click();
  const gallery = page.getByRole("dialog", { name: "Choose a workflow" });
  await gallery
    .getByRole("button", { name: "Blank workflow", exact: true })
    .click();
  await gallery.getByLabel("Workflow name").fill("Review and test");
  await gallery
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Review and test", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();

  // 2. Turn the first job into the Review job with an agent step.
  await openJobSettings(page, "General");
  await page.getByLabel("Job name", { exact: true }).fill("Review");
  await page
    .getByRole("button", { name: "Rename job ID", exact: true })
    .click();
  await page.getByLabel("New job ID", { exact: true }).fill("review");
  await page.getByRole("button", { name: "Rename", exact: true }).click();
  await openJobSettings(page);
  await page.getByRole("combobox", { name: "Step type", exact: true }).click();
  await page.getByRole("option", { name: /^Agent / }).click();
  await chooseAgent(page, "Codex");
  await page.getByRole("combobox", { name: "Model", exact: true }).fill("m1");
  await page
    .getByLabel("Agent prompt", { exact: true })
    .fill("Review README.md and list anything unclear.");
  await closeJobSettings(page);

  // 3. Add a Command job that runs the tests after Review.
  await page
    .getByRole("combobox", { name: "New job type", exact: true })
    .click();
  await page.getByRole("option", { name: /^Command / }).click();
  await page.getByRole("button", { name: "Add job", exact: true }).click();
  const argument = (item: number) =>
    page.getByRole("textbox", {
      name: `Program and arguments item ${item}`,
      exact: true,
    });
  await argument(1).fill("python");
  await argument(2).fill("-m");
  await page
    .getByRole("button", {
      name: "Add Program and arguments item",
      exact: true,
    })
    .click();
  await argument(3).fill("pytest");
  await openJobSettings(page, "General");
  await page.getByLabel("Job name", { exact: true }).fill("Test");
  await page
    .getByRole("button", { name: "Rename job ID", exact: true })
    .click();
  await page.getByLabel("New job ID", { exact: true }).fill("test");
  await page.getByRole("button", { name: "Rename", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Start after", exact: true })
    .click();
  await page
    .getByRole("option", { name: "Review (review)", exact: true })
    .click();
  await closeJobSettings(page);

  // 4. Save and run it.
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
  const saved = parse(
    (
      await (
        await page.request.get("/api/workflows/review-and-test.yaml")
      ).json()
    ).yaml,
  );
  expect(saved).toEqual({
    name: "Review and test",
    on: "workflow_dispatch",
    jobs: {
      review: {
        name: "Review",
        steps: [
          {
            uses: "relay/agent@v1",
            with: {
              agent: "codex",
              model: "m1",
              prompt: "Review README.md and list anything unclear.",
            },
          },
        ],
      },
      test: {
        name: "Test",
        needs: ["review"],
        steps: [
          {
            uses: "relay/command@v1",
            with: { argv: '["python","-m","pytest"]' },
          },
        ],
      },
    },
  });
  const launched = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("region", { name: "Workflow header" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Run workflow" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const created = await launched;
  expect(created.status(), await created.text()).toBe(201);
  const { run_id: runId } = await created.json();
  await expectRunStatus(page, runId, "succeeded", 60_000);
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
      { exact: true },
    ),
  ).toBeVisible();
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  await expect(jobs.getByRole("link", { name: /^Review / })).toBeVisible();
  await expect(jobs.getByRole("link", { name: /^Test / })).toBeVisible();

  // 5. Break the YAML on purpose, read the suggestion, and fix it.
  await page.goto("/?view=workflows&workflow=review-and-test.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const source = (
    await (await page.request.get("/api/workflows/review-and-test.yaml")).json()
  ).yaml as string;
  const editor = page.locator(".yaml-editor .cm-content");
  await editor.fill(source.replace("    steps:", "    stpes:"));
  await expect(page.locator(".MuiAlert-colorError")).toContainText(
    "workflow.jobs.review.stpes: Unknown workflow field. Did you mean steps?",
  );
  await expect(
    page.getByRole("button", { name: "Save", exact: true }),
  ).toBeDisabled();
  await editor.fill(source);
  await expect(page.locator(".MuiAlert-colorError")).toHaveCount(0);
});

test("the Help menu shows the guides as readable steps and tables", async ({
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
  await page.goto("/?view=workflows");
  const openGuide = async (name: string) => {
    await page
      .getByRole("button", { name: /^(Help|Account menu for owner)$/ })
      .click();
    await page.getByRole("menuitem", { name, exact: true }).click();
    const dialog = page.getByRole("dialog", { name, exact: true });
    await expect(dialog).toBeVisible();
    return dialog;
  };
  const guide = await openGuide("Build your first workflow");
  // A wrapped step stays one list item, and example tags stay hidden.
  await expect(guide.getByRole("listitem").nth(1)).toHaveText(
    "Choose Blank workflow and enter Review and test as the Workflow name.",
  );
  await expect(guide).not.toContainText("relay-example");
  await expect(
    guide.getByRole("row", { name: /^Approval relay\/human-wait@v1/ }),
  ).toBeVisible();
  await guide.getByRole("button", { name: "Close", exact: true }).click();
  const actions = await openGuide("Coming from GitHub Actions");
  // An escaped pipe is cell text rather than a column break.
  await expect(
    actions.getByRole("row", { name: /^Lists in with:/ }).getByRole("cell"),
  ).toHaveText([
    "Lists in with:",
    "One value per line under |, or a JSON array string",
  ]);
});
