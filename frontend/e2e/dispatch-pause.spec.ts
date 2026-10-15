import { post } from "./setup-helpers";
import { expect, test, type Page } from "./a11y-test";
import { stringify } from "yaml";

test("pause active work, reload the held run, and explicitly resume the next job", async ({
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
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  expect((await post(page, "/__test__/feedback-provider")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
  await expect(
    page.getByRole("button", { name: "Add job", exact: true }),
  ).toBeEnabled();
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const created = await post(page, "/api/workflows", {
    key: "pause-review",
    holder,
    yaml: stringify({
      name: "Pause review",
      jobs: {
        work: {
          steps: [
            {
              id: "work",
              uses: "relay/agent@v1",
              with: {
                agent: "codex",
                model: "m1",
              },
            },
          ],
        },
        review: {
          needs: ["work"],
          steps: [{ id: "work", shell: "python", run: "print('reviewed')" }],
        },
      },
    }),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const launch = await post(page, "/api/runs", {
    workflow_key: "pause-review",
    inputs: {},
    cleanup_policy: "retain",
  });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const { run_id: runId } = await launch.json();
  await page.goto(`/?view=runs&run=${runId}`);
  await page
    .getByRole("region", { name: "Waiting for you", exact: true })
    .getByRole("button", { name: "Respond", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "A tool needs your permission" }),
  ).toBeVisible();
  const before = (await (await page.request.get(`/api/runs/${runId}`)).json())
    .run;
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Resume", exact: true }),
  ).toBeVisible();
  // The provider is still awaiting its own permission answer in the same attempt.
  await page.getByRole("combobox", { name: "Your decision" }).click();
  await page.getByRole("option", { name: "Allow once", exact: true }).click();
  await page
    .getByLabel("Feedback for the agent (optional)")
    .fill("Finish the current step.");
  await page
    .getByRole("button", { name: "Send response and continue" })
    .click();
  await expect
    .poll(async () => {
      const run = (await (await page.request.get(`/api/runs/${runId}`)).json())
        .run;
      return run.nodes.find(
        (node: { scope_path: string }) => node.scope_path === "root.work",
      ).status;
    })
    .toBe("succeeded");
  await expect(
    page.getByRole("region", { name: "Waiting for you", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText(/needs (your )?input/i)).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: /Pause review #/ }),
  ).toBeVisible();
  await expect(
    page.getByText("New jobs paused", { exact: true }),
  ).toBeVisible();
  const pausedMessage =
    "Paused. Running jobs will finish; nothing new will start until you resume.";
  await expect(page.getByText(pausedMessage, { exact: true })).toHaveCount(1);
  await expect(
    page.getByText("Unstarted agent steps", { exact: true }),
  ).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByText("New jobs paused", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Resume", exact: true }).click();
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${runId}`)).json()).run
          .status,
    )
    .toBe("succeeded");
  await page.screenshot({
    path: testInfo.outputPath("resumed-current-jobs.png"),
  });
});
