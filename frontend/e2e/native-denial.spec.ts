import { expect, test } from "./a11y-test";
import { post } from "./setup-helpers";

test("a native denied write keeps its reason across summary and step views", async ({
  page,
}) => {
  await page.request.get("/api/auth");
  const login = await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  expect(login.ok(), await login.text()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  expect(
    (await post(page, "/__test__/native-denial-provider")).ok(),
  ).toBeTruthy();
  const created = await post(page, "/api/workflows", {
    key: "native-denial",
    holder: "native-denial",
    yaml: `name: Native denial
on: workflow_dispatch
jobs:
  verify:
    steps:
      - id: agent
        uses: relay/agent@v1
        with:
          agent: antigravity
          model: m1
          report: report.txt
          format: label
          label: Ready
`,
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const launched = await post(page, "/api/runs", {
    workflow_key: "native-denial",
    inputs: {},
  });
  expect(launched.status(), await launched.text()).toBe(201);
  const { run_id: runId } = await launched.json();
  await expect
    .poll(async () => {
      const response = await page.request.get(`/api/runs/${runId}/monitor`);
      expect(response.ok(), await response.text()).toBeTruthy();
      return (await response.json()).run.problem?.stop_reason;
    })
    .toBe("soft_denied");

  const reason = "The tool did not have permission to complete its work.";
  for (const job of [null, "root.verify.agent", "root.verify"]) {
    await page.goto(`/?view=runs&run=${runId}${job ? `&job=${job}` : ""}`);
    if (job === "root.verify") {
      await page.getByRole("button", { name: /^Failed 1\. Agent/ }).click();
    }
    await expect(page.getByText(reason, { exact: true })).toBeVisible();
    await expect(
      page.getByText(/failed with exit code (0|undefined)/),
    ).toHaveCount(0);
  }
});
