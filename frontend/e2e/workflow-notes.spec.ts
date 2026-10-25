import { expect, test } from "./a11y-test";
import { stringify } from "yaml";
import { post, expectRunStatus } from "./setup-helpers";

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

test("an approved note is chosen at launch and a finished run can add another", async ({
  page,
}) => {
  await page.goto("/?view=workflows&workflow=workflow");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const created = await post(page, "/api/workflows", {
    key: "noted",
    holder,
    yaml: stringify({
      name: "noted",
      jobs: {
        check: {
          steps: [
            {
              id: "work",
              uses: "relay/command@v1",
              with: { argv: JSON.stringify(["git", "status"]) },
            },
          ],
        },
      },
    }),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  await page.goto("/?view=workflows&workflow=noted.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();

  await page
    .getByRole("button", { name: "Workflow notes", exact: true })
    .click();
  const notes = page.getByRole("dialog", { name: "Workflow notes" });
  await expect(notes.getByText("No notes yet.")).toBeVisible();
  await notes.getByRole("button", { name: "Add note", exact: true }).click();
  const save = notes.getByRole("button", { name: "Save note", exact: true });
  await notes
    .getByRole("textbox", { name: "When does this apply?" })
    .fill("The status check is slow");
  await notes
    .getByRole("textbox", { name: "What should the agent do?" })
    .fill("Check only changed files first");
  await expect(save).toBeDisabled();
  await notes
    .getByRole("textbox", { name: "What showed this?" })
    .fill("Run #1 spent most of its time in status");
  await save.click();
  await expect(notes.getByText("When: The status check is slow")).toBeVisible();
  await notes.getByRole("button", { name: "Close", exact: true }).click();

  await page
    .getByRole("region", { name: "Workflow header" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const panel = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await panel.getByText("Workflow notes (0 of 1 chosen)").click();
  await panel.getByRole("checkbox").first().check();
  await expect(panel.getByText("Workflow notes (1 of 1 chosen)")).toBeVisible();
  const launched = page.waitForResponse(
    (r) => r.url().endsWith("/api/runs") && r.request().method() === "POST",
  );
  await panel
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const response = await launched;
  expect(response.status(), await response.text()).toBe(201);
  expect(response.request().postDataJSON().notes).toHaveLength(1);
  const { run_id: runId } = await response.json();
  await expectRunStatus(page, runId, "succeeded", 30_000);

  await page.goto(`/?view=runs&run=${runId}`);
  await page.getByRole("button", { name: "Save as note", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "Save a lesson from this run",
  });
  await expect(
    dialog.getByRole("textbox", { name: "What showed this?" }),
  ).toHaveValue(/^Run #\d+ \(Succeeded\): $/);
  await dialog
    .getByRole("textbox", { name: "When does this apply?" })
    .fill("The run succeeds quickly");
  await dialog
    .getByRole("textbox", { name: "What should the agent do?" })
    .fill("Keep the change small");
  await dialog
    .getByRole("textbox", { name: "What showed this?" })
    .fill("Run finished without retries");
  await dialog.getByRole("button", { name: "Save note", exact: true }).click();
  await expect(dialog).toBeHidden();
  const listed = await (
    await page.request.get("/api/workflows/noted/notes")
  ).json();
  expect(listed.notes).toHaveLength(2);
  expect(listed.notes[1].evidence_run_id).toBe(runId);
});
