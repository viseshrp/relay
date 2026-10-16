import { stringify } from "yaml";
import { assertAccessible, expect, test } from "./a11y-test";
import { expectRunStatus, post } from "./setup-helpers";
import type { RunEvent } from "../src/types";

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

const cases = [
  { format: "oneOf", label: "Staging", value: "STAGING_exact_v2" },
  { format: "enum", label: "ALPHA", value: "ALPHA" },
  { format: "empty", label: "Skip", value: "" },
] as const;

for (const { format, label, value } of cases) {
  test(`elicitation ${format} choices preserve offered labels, ordering and exact values`, async ({
    page,
  }) => {
    expect(
      (
        await post(page, "/__test__/elicitation-provider", { choices: format })
      ).ok(),
    ).toBeTruthy();
    const key = `elicitation-${format}`;
    expect(
      (
        await post(page, "/api/workflows", {
          key,
          holder: key,
          yaml: stringify({
            jobs: {
              work: {
                steps: [
                  {
                    id: "agent",
                    uses: "relay/agent@v1",
                    with: { agent: "codex", model: "m1" },
                  },
                ],
              },
            },
          }),
        })
      ).ok(),
    ).toBeTruthy();
    const launched = await post(page, "/api/runs", {
      workflow_key: key,
      inputs: {},
    });
    expect(launched.status(), await launched.text()).toBe(201);
    const { run_id: id } = await launched.json();
    try {
      await expectRunStatus(page, id, "paused_wait");
      const { run } = await (
        await page.request.get(
          `/api/runs/${id}?collection=interactions&pending=true`,
        )
      ).json();
      const interaction = run.interactions[0];
      expect(interaction.kind).toBe("elicitation");
      await page.goto(
        `/?view=runs&run=${id}&job=root.work.agent&interaction=${interaction.id}`,
      );
      const send = page.getByRole("button", {
        name: "Send response and continue",
        exact: true,
      });
      await expect(send).toBeDisabled();
      const choices = page.getByRole("combobox", {
        name: "Component",
        exact: true,
      });
      await expect(choices).toBeVisible();
      await expect(choices).toHaveAccessibleDescription(
        "Choose the component to inspect.",
      );
      await assertAccessible(page);
      await choices.click();
      const options = page.getByRole("option");
      await expect(options).toHaveCount(2);
      if (format === "oneOf") {
        await expect(
          options.nth(0).getByText("Staging", { exact: true }),
        ).toBeVisible();
        await expect(options.nth(0)).toContainText(
          "Use the staging environment.",
        );
        await expect(options.nth(1)).toContainText("Production");
        await options.nth(0).click();
      } else if (format === "enum") {
        await expect(options).toHaveText(["alpha", "ALPHA"]);
        await options.nth(1).click();
      } else {
        await expect(options.nth(0)).toContainText("Skip");
        await expect(options.nth(0)).toContainText(
          "Leave the component unspecified.",
        );
        await options.nth(0).click();
      }
      await expect(choices).toContainText(label);
      await expect(send).toBeEnabled();
      await send.click();
      await expectRunStatus(page, id, "succeeded");
      const history = await (
        await page.request.get(`/api/runs/${id}?collection=interactions`)
      ).json();
      expect(history.run.interactions[0].response).toMatchObject({
        value: { component: value },
      });
      const { events }: { events: RunEvent[] } = await (
        await page.request.get(`/api/runs/${id}/events`)
      ).json();
      const prefix = "Owner answer: ";
      const echo = events
        .filter((event) => event.type === "agent.message")
        .map((event) => event.payload.text)
        .find((text) => typeof text === "string" && text.startsWith(prefix));
      expect(
        JSON.parse(
          typeof echo === "string" ? echo.slice(prefix.length) : "null",
        ),
      ).toMatchObject({ action: "accept", content: { component: value } });
    } finally {
      const { run } = await (await page.request.get(`/api/runs/${id}`)).json();
      if (["running", "paused_wait"].includes(run.status)) {
        await post(page, `/api/runs/${id}/cancel`, {
          idempotency_key: "elicitation-choice-test-cleanup",
        });
        await expectRunStatus(page, id, "canceled");
      }
    }
  });
}
