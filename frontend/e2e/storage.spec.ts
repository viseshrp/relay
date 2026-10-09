import { expect, test, type Page } from "@playwright/test";
import type { RunSummary } from "../src/types";
import { historicalPost as post } from "./setup-helpers";

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
test.afterEach(async ({ page }) => {
  await post(page, "/__test__/reset");
});

async function isolatedProject(page: Page): Promise<string> {
  const created = await post(page, "/__test__/storage-project");
  expect(created.ok()).toBeTruthy();
  const body: { project_id: string } = await created.json();
  return body.project_id;
}

async function finishedRuns(
  page: Page,
  project: string,
  count = 1,
): Promise<RunSummary[]> {
  const created = await post(page, `/api/workflows?project=${project}`, {
    key: "storage-check",
    holder: "storage-check",
    yaml: "version: 1\nname: Storage cleanup check\nnodes:\n  check: {type: command, run: [git, status]}\n",
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const runs: RunSummary[] = [];
  for (let index = 0; index < count; index += 1) {
    const launched = await post(page, `/api/runs?project=${project}`, {
      workflow_key: "storage-check",
      inputs: {},
      cleanup_policy: "retain",
    });
    expect(launched.ok(), await launched.text()).toBeTruthy();
    const body: { run_id: string } = await launched.json();
    const detail = async (): Promise<RunSummary> => {
      const response: { run: RunSummary } = await (
        await page.request.get(`/api/runs/${body.run_id}`)
      ).json();
      return response.run;
    };
    await expect.poll(async () => (await detail()).status).toBe("succeeded");
    runs.push(await detail());
  }
  return runs;
}

async function openStorage(page: Page, project: string): Promise<void> {
  await page.goto(`/?view=settings&project=${project}`);
  await page
    .getByRole("navigation", { name: "Settings sections" })
    .getByRole("button", { name: "Storage", exact: true })
    .click();
}

test("temporary cleanup lives in Storage and removes only the confirmed run's marked folders", async ({
  page,
}, info) => {
  const project = await isolatedProject(page);
  const [target, other] = await finishedRuns(page, project, 2);
  for (const run of [target, other])
    expect(
      (await post(page, "/__test__/resource-remnant", { run_id: run.id })).ok(),
    ).toBeTruthy();
  await page.goto(`/?view=runs&project=${project}&run=${target.id}`);
  await page
    .getByText("Advanced diagnostics and saved files", { exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: /^(Retry temporary resource cleanup|Clean data|Review deletion)$/i,
    }),
  ).toHaveCount(0);
  await page.goto(
    `/?view=runs&project=${project}&run=${target.id}&job=root.check`,
  );
  await expect(
    page.getByRole("region", { name: "Job log", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: /^(Retry temporary resource cleanup|Clean data|Review deletion)$/i,
    }),
  ).toHaveCount(0);
  await openStorage(page, project);
  const panel = page.getByRole("region", {
    name: "Temporary run resources",
    exact: true,
  });
  const button = panel.getByRole("button", {
    name: "Retry temporary resource cleanup",
    exact: true,
  });
  await expect(button).toBeDisabled();
  const picker = panel.getByRole("combobox", {
    name: "Completed run",
    exact: true,
  });
  await expect(picker).toBeEnabled();
  await picker.focus();
  await picker.press("Enter");
  await expect(page.getByRole("option")).toHaveCount(3);
  await page
    .getByRole("option", {
      name: `#${target.number} Storage cleanup check Complete`,
      exact: true,
    })
    .click();
  await button.click();
  const dialog = page.getByRole("dialog", {
    name: `Retry temporary cleanup for run #${target.number}?`,
    exact: true,
  });
  await expect(dialog).toContainText(
    "Reports, code, run history, credentials, and personal browser profiles stay in place.",
  );
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(button).toBeFocused();
  await button.click();
  const request = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/runs/${target.id}/resources/clean`) &&
      response.request().method() === "POST",
  );
  await dialog
    .getByRole("button", { name: "Confirm temporary cleanup", exact: true })
    .click();
  const response = await request;
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ removed: 1 });
  await expect(dialog).toBeHidden();
  await expect(button).toBeFocused();
  await expect(panel.getByRole("alert")).toHaveText(
    `Removed 1 temporary folder for run #${target.number}.`,
  );
  const remaining: { run: RunSummary } = await (
    await page.request.get(`/api/runs/${target.id}`)
  ).json();
  expect(remaining.run).toMatchObject({
    status: "succeeded",
    source_commit: target.source_commit,
    run_branch: target.run_branch,
    worktree_state: "created",
  });
  expect(
    await (
      await post(page, `/api/runs/${target.id}/resources/clean`, {
        confirm: true,
      })
    ).json(),
  ).toEqual({ removed: 0 });
  expect(
    await (
      await post(page, `/api/runs/${other.id}/resources/clean`, {
        confirm: true,
      })
    ).json(),
  ).toEqual({ removed: 1 });
  await page.setViewportSize({ width: 1440, height: 1650 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: info.outputPath("storage-complete.png"),
    fullPage: true,
    animations: "disabled",
  });
});

test("Storage recovers failed reads and keeps server cleanup errors in the confirmation", async ({
  page,
}) => {
  const project = await isolatedProject(page);
  const [run] = await finishedRuns(page, project);
  await page.route("**/api/runs?**", (route) =>
    route.fulfill({
      status: 503,
      json: {
        code: "persistence_error",
        message: "Completed runs could not be read.",
        context: {},
      },
    }),
  );
  await openStorage(page, project);
  const panel = page.getByRole("region", {
    name: "Temporary run resources",
    exact: true,
  });
  await expect(panel.getByRole("alert")).toContainText(
    "Completed runs could not be read.",
  );
  const button = panel.getByRole("button", {
    name: "Retry temporary resource cleanup",
    exact: true,
  });
  await expect(button).toBeDisabled();
  await page.unroute("**/api/runs?**");
  await panel
    .getByRole("button", { name: "Reload completed runs", exact: true })
    .click();
  await expect(
    panel.getByRole("combobox", { name: "Completed run", exact: true }),
  ).toBeEnabled();
  await panel
    .getByRole("combobox", { name: "Completed run", exact: true })
    .click();
  await page
    .getByRole("option", {
      name: `#${run.number} Storage cleanup check Complete`,
      exact: true,
    })
    .click();
  const path = `**/api/runs/${run.id}/resources/clean`;
  await page.route(path, (route) =>
    route.fulfill({
      status: 409,
      json: {
        code: "permission_flow_error",
        message:
          "Temporary resources cannot be cleaned while this run is active.",
        context: {},
      },
    }),
  );
  await button.click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Confirm temporary cleanup", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Temporary resources cannot be cleaned while this run is active.",
  );
  await expect(dialog).toBeVisible();
  await page.unroute(path);
  await dialog
    .getByRole("button", { name: "Confirm temporary cleanup", exact: true })
    .click();
  await expect(dialog).toBeHidden();
  await expect(panel.getByRole("alert")).toHaveText(
    `No temporary folders remained for run #${run.number}.`,
  );
});

test("older completed runs load through bounded project-scoped pages", async ({
  page,
}) => {
  const project = await isolatedProject(page);
  const [run] = await finishedRuns(page, project);
  const recent: RunSummary = {
    ...run,
    number: 2,
    title: "Recent completed run",
  };
  const older: RunSummary = {
    ...run,
    id: "00000000-0000-0000-0000-000000000001",
    number: 1,
    title: "Older completed run",
  };
  await page.route("**/api/runs?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    expect(query.get("project")).toBe(project);
    expect(query.get("limit")).toBe("20");
    const succeeded = query.get("status") === "succeeded";
    const nextPage = query.has("since");
    return route.fulfill({
      json: {
        runs: succeeded ? [nextPage ? older : recent] : [],
        next: succeeded && !nextPage ? recent.id : null,
      },
    });
  });
  await openStorage(page, project);
  const panel = page.getByRole("region", {
    name: "Temporary run resources",
    exact: true,
  });
  await panel
    .getByRole("button", { name: "Load older completed runs", exact: true })
    .click();
  await expect(
    panel.getByRole("button", {
      name: "Load older completed runs",
      exact: true,
    }),
  ).toHaveCount(0);
  await panel
    .getByRole("combobox", { name: "Completed run", exact: true })
    .click();
  await expect(page.getByRole("option")).toHaveCount(3);
  await page
    .getByRole("option", {
      name: "#1 Older completed run Complete",
      exact: true,
    })
    .click();
  await panel
    .getByRole("button", {
      name: "Retry temporary resource cleanup",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("dialog", {
      name: "Retry temporary cleanup for run #1?",
      exact: true,
    }),
  ).toContainText("Older completed run");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
});
