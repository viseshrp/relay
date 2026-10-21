import { assertAccessible, expect, test } from "./a11y-test";
import { post } from "./setup-helpers";

// The audit's typical CI file: two triggers, a hosted runner, checkout, setup.
const CI = `name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest
`;

const CONVERTED = `name: CI
on:
  push:
    branches: [main]
jobs:
  test:
    steps:
      - run: pip install -r requirements.txt
      - run: pytest
`;

test.beforeEach(async ({ page }) => {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
});

test("import a GitHub Actions workflow, review its changes, and save it", async ({
  page,
}) => {
  expect(
    (await post(page, "/__test__/github-workflow", { yaml: CI })).ok(),
  ).toBeTruthy();
  await page.goto("/?view=workflows&workflow=workflow.yaml");
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  const gallery = page.getByRole("dialog", { name: "Choose a workflow" });
  await gallery
    .getByRole("button", { name: "Import from GitHub Actions", exact: true })
    .click();
  await expect(
    gallery.getByRole("button", { name: "Create workflow", exact: true }),
  ).toBeDisabled();
  await gallery
    .getByRole("button", { name: "CI · .github/workflows/ci.yml", exact: true })
    .click();
  await expect(
    gallery.getByRole("list", { name: "Changes" }).getByRole("listitem"),
  ).toHaveText([
    "Removed runs-on from job test; jobs run on this computer.",
    "Removed the pull_request trigger; it has no local equivalent.",
    "Removed actions/checkout from job test; jobs already run in a working copy.",
    "Removed actions/setup-python@v5 from job test; use the tool installed on this computer.",
  ]);
  await expect(
    gallery.getByRole("list", { name: "Check by hand" }),
  ).toHaveCount(0);
  await assertAccessible(page);
  const created = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/workflows" &&
      response.request().method() === "POST",
  );
  await gallery
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  const document: { key: string } = await (await created).json();
  await expect(gallery).toBeHidden();
  // The converted YAML opens as an unsaved draft over the blank saved file.
  await expect(
    page.getByText(
      "Your unsaved draft is not included when you run the saved workflow.",
    ),
  ).toBeVisible();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Workflow and instructions saved and validated.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const saved = await page.request.get(
    `/api/workflows/${encodeURIComponent(document.key)}`,
  );
  expect(await saved.json()).toMatchObject({ yaml: CONVERTED, draft: null });
});
