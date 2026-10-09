import { expect, test } from "@playwright/test";
import { post, runStarter } from "./setup-helpers";
import type { AgentsResponse } from "../src/types";

test("account creation explains the password rules before submission", async ({
  page,
}) => {
  await page.route("**/api/auth", (route) =>
    route.fulfill({
      json: {
        authenticated: false,
        owner_created: false,
        username: null,
        login_required: true,
        password_rules: [
          "Use at least 12 characters.",
          "Avoid common passwords.",
        ],
      },
    }),
  );
  await page.goto("/?view=workflows");
  await expect(
    page.getByText(
      "Create a password for this computer's Relay. Only people who can use this computer can reach it.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveText([
    "Use at least 12 characters.",
    "Avoid common passwords.",
  ]);
  await expect(page.getByText(/Django/)).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Username" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel(/^Password/)).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Create password" }),
  ).toBeFocused();
});

test("returning users see sign-in without account creation rules", async ({
  page,
}) => {
  await page.goto("/?view=workflows");
  await expect(
    page.getByText("Sign in to Relay on this computer."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Choose a password that follows these rules:"),
  ).toHaveCount(0);
});

for (const [id, name] of [
  ["ask-agent", "Ask an agent"],
  ["plan-approve-implement", "Plan, approve, implement"],
  ["implement-and-test", "Implement and test"],
  ["review-branch", "Review my branch"],
  ["fix-tests", "Fix until tests pass"],
  ["write-docs", "Write docs for a change"],
]) {
  test(`${name} copies its sources and completes with the fake agent`, async ({
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
    await runStarter(page, id, name, testInfo, id === "ask-agent");
  });
}

for (const readyCount of [0, 5]) {
  test(`setup shows ${readyCount} agents ready and can check again`, async ({
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
    await page.route("**/api/runs?*status=succeeded*", (route) =>
      route.fulfill({ json: { runs: [], next: null } }),
    );
    const source: AgentsResponse = await (
      await page.request.get("/api/agents")
    ).json();
    const inventory = {
      ...source,
      agents: source.agents.map((agent) => ({
        ...agent,
        installed: readyCount === 5 || agent.installed,
      })),
    };
    await page.route("**/api/agents", (route) =>
      route.fulfill({ json: inventory }),
    );
    let checks = 0;
    await page.route("**/api/agents/check", async (route) => {
      checks += 1;
      const agents = inventory.agents;
      await route.fulfill({
        json: {
          agents: agents.map((agent) => ({
            ...agent,
            ready: readyCount > 0,
            error_code: readyCount ? null : "agent_auth_error",
            reason: readyCount ? null : "Sign in to continue.",
            cleanup_warning: null,
            models: readyCount ? ["m1"] : [],
            login_command: "codex login",
            login_guidance: "Sign in in your terminal.",
          })),
        },
      });
    });
    await page.goto("/?view=workflows");
    await page
      .getByRole("button", { name: "Get started", exact: true })
      .click();
    const setup = page.getByRole("region", {
      name: "Get started",
      exact: true,
    });
    await expect(setup.getByRole("article")).toHaveCount(5);
    // Installed status comes from the inventory; model checks never install an agent.
    const installed = inventory.agents.filter(
      (agent) => agent.installed,
    ).length;
    await expect(setup.getByText(/Ready to connect/)).toHaveCount(
      readyCount ? installed : 0,
    );
    if (!readyCount)
      await expect(
        setup.getByText(
          "Install and sign in to one agent, then choose Check again.",
        ),
      ).toBeVisible();
    await setup
      .getByRole("button", { name: "Check again", exact: true })
      .click();
    await expect.poll(() => checks).toBeGreaterThanOrEqual(2);
    await expect(
      setup.getByRole("button", { name: "Check again", exact: true }),
    ).toBeEnabled();
  });
}
