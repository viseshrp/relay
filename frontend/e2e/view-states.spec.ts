import { test, expect, type Page } from "./a11y-test";
import { post } from "./setup-helpers";

type Fixture = { project: string; run: string; job: string; workflow: string };
const screens = [
  "home",
  "workflows",
  "runs",
  "summary",
  "job",
  "settings",
] as const;
type Screen = (typeof screens)[number];
function href(f: Fixture, view: Screen) {
  const query = new URLSearchParams({
    view: ["summary", "job"].includes(view) ? "runs" : view,
    project: f.project,
  });
  if (view === "workflows") query.set("workflow", f.workflow);
  if (view === "summary" || view === "job") query.set("run", f.run);
  if (view === "job") query.set("job", f.job);
  return `/?${query}`;
}
function endpoint(f: Fixture, view: Screen) {
  return (url: URL) => {
    if (view === "home") return url.pathname === "/api/dashboard";
    if (view === "workflows")
      return url.pathname === `/api/workflows/${f.workflow}`;
    if (view === "runs") return url.pathname === "/api/runs";
    if (view === "job") return url.pathname === `/api/runs/${f.run}/job`;
    if (view === "summary") return url.pathname === `/api/runs/${f.run}`;
    return url.pathname === "/api/settings";
  };
}
async function seed(page: Page): Promise<Fixture> {
  await page.request.get("/api/auth");
  await post(page, "/api/auth/login", {
    username: "owner",
    password: "Relay-Test-Passphrase-2026!",
  });
  await post(page, "/__test__/reset");
  const response = await post(page, "/__test__/worst-case", { enabled: false });
  expect(response.ok()).toBeTruthy();
  return response.json();
}
async function ready(page: Page, view: Screen) {
  if (view === "workflows")
    await expect(
      page.getByText("Ready to edit", { exact: true }),
    ).toBeVisible();
  else if (view === "home")
    await expect(
      page.getByRole("heading", { name: "Your projects" }),
    ).toBeVisible();
  else if (view === "job")
    await expect(
      page.getByRole("region", { name: "Job log", exact: true }),
    ).toBeVisible();
  else if (view === "summary")
    await expect(
      page.getByRole("region", { name: "Step progress" }),
    ).toBeVisible();
  else if (view === "settings")
    await expect(
      page.getByRole("heading", { name: "Global defaults", exact: true }),
    ).toBeVisible();
  else
    await expect(page.getByRole("link", { name: /#1/ }).first()).toBeVisible();
}

test("each main view reserves loading space and reaches its success state", async ({
  page,
}) => {
  test.setTimeout(90000);
  const f = await seed(page);
  for (const view of screens) {
    const match = endpoint(f, view);
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(match, async (route) => {
      await held;
      await route.continue();
    });
    await page.goto(href(f, view));
    await expect(page.locator(".view-skeleton").first()).toBeVisible();
    release();
    await ready(page, view);
    await page.unroute(match);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  }
});

for (const status of [503, 403])
  test(`each main view explains HTTP ${status} and recovers with its visible control`, async ({
    page,
  }) => {
    test.setTimeout(90000);
    const f = await seed(page);
    for (const view of screens) {
      const match = endpoint(f, view);
      await page.route(match, (route) =>
        route.fulfill({
          status,
          json: {
            code: status === 403 ? "permission_denied" : "persistence_error",
            message:
              status === 403
                ? "Owner access is required."
                : "The saved data could not be read.",
            context: {},
          },
        }),
      );
      await page.goto(href(f, view));
      await expect(
        page
          .getByRole("alert")
          .filter({
            hasText:
              status === 403
                ? "Owner access is required."
                : "The saved data could not be read.",
          })
          .first(),
      ).toBeVisible();
      await page.unroute(match);
      const name =
        view === "home"
          ? "Refresh"
          : view === "workflows"
            ? "Retry workflow"
            : view === "job"
              ? "Retry job"
              : view === "settings"
                ? "Retry settings"
                : "Retry";
      await page.getByRole("button", { name, exact: true }).first().click();
      await ready(page, view);
    }
  });

test("Runs keeps saved history visible when its workflow inventory fails", async ({
  page,
}) => {
  const fixture = await seed(page);
  await page.route(
    (url) => url.pathname === "/api/workflows",
    (route) =>
      route.fulfill({
        status: 503,
        json: {
          code: "persistence_error",
          message: "The workflow inventory could not be read.",
          context: {},
        },
      }),
  );
  try {
    await page.goto(href(fixture, "runs"));
    await expect(page.getByRole("link", { name: /#1/ }).first()).toBeVisible();
    await expect(page.getByRole("alert")).toContainText(
      "The workflow inventory could not be read.",
    );
    await expect(page.locator(".view-skeleton")).toHaveCount(0);
  } finally {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
});

test("empty collections use copy appropriate to each view", async ({
  page,
}) => {
  test.setTimeout(90000);
  const f = await seed(page);
  await page.route("**/api/dashboard?**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.counts = Object.fromEntries(
      Object.keys(body.counts).map((key) => [key, 0]),
    );
    for (const section of ["projects", "waiting", "active", "recent"])
      body[section] = { items: [], next_cursor: null };
    await route.fulfill({ response, json: body });
  });
  await page.goto(href(f, "home"));
  await expect(
    page.getByRole("button", { name: "Open your first project" }),
  ).toBeVisible();
  await page.unroute("**/api/dashboard?**");
  await page.route(
    (url) => url.pathname === "/api/workflows",
    (route) => route.fulfill({ json: { workflows: [] } }),
  );
  await page.goto(`/?view=workflows&project=${f.project}`);
  await expect(
    page.getByText("No workflows yet", { exact: true }),
  ).toBeVisible();
  await page.unrouteAll({ behavior: "wait" });
  await page.route(
    (url) => url.pathname === "/api/runs",
    (route) => route.fulfill({ json: { runs: [], next: null } }),
  );
  await page.goto(href(f, "runs"));
  await expect(
    page.getByText("No runs yet. Choose a workflow to start a run."),
  ).toBeVisible();
  await page.unrouteAll({ behavior: "wait" });
  const summary = endpoint(f, "summary");
  await page.route(summary, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.run.nodes = [];
    body.next = null;
    await route.fulfill({ response, json: body });
  });
  await page.goto(href(f, "summary"));
  await expect(
    page.getByText("No jobs have been recorded for this run."),
  ).toBeVisible();
  await page.unrouteAll({ behavior: "wait" });
  await page.route(endpoint(f, "job"), async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.job.latest_attempt = null;
    body.job.attempts = [];
    body.next = null;
    await route.fulfill({ response, json: body });
  });
  await page.goto(href(f, "job"));
  await expect(
    page.getByRole("region", { name: "Job log", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Outputs", exact: true }).click();
  await expect(page.getByText("No declared outputs.")).toBeVisible();
  await page.unrouteAll({ behavior: "wait" });
  await page.goto(href(f, "settings"));
  await expect(
    page.getByRole("heading", { name: "Global defaults", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Project defaults", exact: true })
    .click();
  await expect(page.getByText(/inherit/i).first()).toBeVisible();
});
