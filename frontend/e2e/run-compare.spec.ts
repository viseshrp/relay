import { expect, test, type Page } from "./a11y-test";
import { stringify } from "yaml";
import { post, expectRunStatus } from "./setup-helpers";

async function launch(page: Page, argv: string[]): Promise<string> {
  const response = await post(page, "/api/runs", {
    workflow_key: "compare",
    inputs: { argv: JSON.stringify(argv) },
  });
  expect(response.status(), await response.text()).toBe(201);
  const value: { run_id: string } = await response.json();
  return value.run_id;
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
});

test("two runs compare their inputs and step results side by side", async ({
  page,
}) => {
  const created = await post(page, "/api/workflows", {
    key: "compare",
    holder: "run-compare",
    yaml: stringify({
      name: "compare",
      on: { workflow_dispatch: { inputs: { argv: { type: "string" } } } },
      jobs: {
        check: {
          steps: [
            {
              id: "work",
              uses: "relay/command@v1",
              with: { argv: "${{ inputs.argv }}" },
            },
          ],
        },
      },
    }),
  });
  expect(created.status(), await created.text()).toBe(201);
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const failed = await launch(page, ["git", "no-such-command"]);
  await expectRunStatus(page, failed, "failed", 30_000);
  const passed = await launch(page, ["git", "status"]);
  await expectRunStatus(page, passed, "succeeded", 30_000);

  await page.goto("/?view=runs&workflow=compare.yaml");
  await page.getByRole("button", { name: "Compare runs", exact: true }).click();
  await page
    .getByRole("checkbox", { name: /^Compare run #/ })
    .nth(0)
    .check();
  await page
    .getByRole("checkbox", { name: /^Compare run #/ })
    .nth(1)
    .check();
  await page.getByRole("button", { name: "Compare 2/2", exact: true }).click();

  const dialog = page.getByRole("dialog", { name: "Compare runs" });
  const inputs = dialog.getByRole("table", { name: "Inputs" });
  await expect(inputs).toContainText("argv");
  await expect(inputs).toContainText("Changed");
  await expect(inputs).toContainText('["git","no-such-command"]');
  const steps = dialog.getByRole("table", { name: "Jobs and steps" });
  await expect(steps).toContainText("Failed");
  await expect(steps).toContainText("Succeeded");
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(dialog).toBeHidden();
});
