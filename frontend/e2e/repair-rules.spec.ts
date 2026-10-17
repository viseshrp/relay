import {
  advancedField,
  openJobSettings,
  closeJobSettings,
  expectRunStatus,
} from "./setup-helpers";
import { post } from "./setup-helpers";
import { expect, test, type Page } from "./a11y-test";
import { parse, stringify } from "yaml";

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
          {
            shell: "python",
            run: "from pathlib import Path; Path('fixed.txt').write_text('fixed\\n')",
          },
          {
            shell: "python",
            run: "from pathlib import Path; assert Path('fixed.txt').read_text() == 'fixed\\n'",
          },
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
  const input = await advancedField(page, "Action inputs");
  await input.fill(
    JSON.stringify({
      workflow: "./.relay/workflows/repair-child.yaml",
      "max-iterations": 3,
    }),
  );
  await input.blur();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.reload();
  await advancedField(page, "Action inputs");
  expect(JSON.parse(await input.inputValue())).toMatchObject({
    "max-iterations": 3,
  });
  const launch = await post(page, "/api/runs", {
    workflow_key: "native-repairs",
    inputs: {},
    cleanup_policy: "retain",
  });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const { run_id: id } = await launch.json();
  await expectRunStatus(page, id, "succeeded");
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
  await openJobSettings(page);
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
  const input = await advancedField(page, "Action inputs");
  await input.fill(
    JSON.stringify({
      agent: "codex",
      model: "m1",
      prompt: "Verify every required check.",
    }),
  );
  await input.blur();
  await expect(page.getByLabel("Effort", { exact: true })).toContainText(
    "Use project and global defaults",
  );
  await expect(page.getByLabel("Permission mode", { exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
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
