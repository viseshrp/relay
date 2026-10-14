import { expect, test, type Locator } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import { stringify } from "yaml";
import { closeJobSettings, openJobSettings, post } from "./setup-helpers";

// This is an opt-in capture scenario, excluded from normal *.spec.ts discovery.
// Real authoring, execution, Git, approval, and artifact APIs; fake ACP agents.
test("record the README workflow walkthrough", async ({ page }) => {
  page.setDefaultTimeout(10_000);
  const directory = process.env.RELAY_DEMO_OUTPUT!;
  const frames: string[] = ["ffconcat version 1.0"];
  let count = 0;
  async function capture(title: string, focus?: Locator, seconds = 3) {
    if (focus) {
      await focus.scrollIntoViewIfNeeded();
      await expect(focus).toBeVisible();
    }
    await page.evaluate(async (text) => {
      await document.fonts.ready;
      // A recording caption, outside the app's layout and interactions.
      let caption = document.getElementById("demo-caption");
      if (!caption) {
        caption = document.createElement("div");
        caption.id = "demo-caption";
        caption.style.cssText =
          "position:fixed;bottom:16px;left:50%;" +
          "transform:translateX(-50%);z-index:2147483647;pointer-events:none;" +
          "padding:12px 22px;border-radius:12px;background:#162637;color:#fff;" +
          "font:600 20px Inter,sans-serif;white-space:nowrap;" +
          "box-shadow:0 3px 16px #0003";
        document.body.append(caption);
      }
      caption.textContent = text;
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve()),
      );
    }, title);
    const filename = `frame-${String(count++).padStart(2, "0")}.png`;
    await page.screenshot({
      path: join(directory, filename),
      animations: "disabled",
      caret: "hide",
    });
    frames.push(`file '${filename}'`, `duration ${seconds}`);
  }

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
  await page.goto("/?view=workflows");
  await page
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  const gallery = page.getByRole("dialog", { name: "Choose a workflow" });
  await expect(gallery.getByRole("button", { name: /^Use / })).toHaveCount(7);
  await capture("1. Start from a template or build your own", gallery);
  await gallery
    .getByRole("button", { name: "Blank workflow", exact: true })
    .click();
  await page.getByLabel("Workflow name").fill("Plan, approve, build, test");
  await gallery
    .getByRole("button", { name: "Create workflow", exact: true })
    .click();
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  await page
    .getByRole("combobox", { name: "Editor mode", exact: true })
    .click();
  await page.getByRole("option", { name: "Split", exact: true }).click();
  const yaml = page.locator('[aria-label="Workflow YAML"]');
  await yaml.fill(
    stringify({
      name: "Plan, approve, build, test",
      on: {
        workflow_dispatch: {
          inputs: {
            task: {
              type: "string",
              required: true,
              default: "Add a project health check.",
            },
          },
        },
      },
      jobs: {
        plan: {
          name: "Plan the change",
          steps: [
            {
              uses: "relay/agent@v1",
              with: {
                agent: "codex",
                model: "m1",
                prompt: "Plan: ${{ inputs.task }}",
              },
            },
            {
              run: "printf '# Implementation plan\\n\\nAdd a health check, then verify the result.\\n' > PLAN.md",
            },
            {
              uses: "relay/upload-artifact@v1",
              with: { name: "implementation-plan", path: "PLAN.md" },
            },
          ],
        },
        approve: {
          name: "Approve the plan",
          needs: "plan",
          steps: [
            {
              uses: "relay/human-wait@v1",
              with: {
                prompt:
                  "Review the saved implementation plan. Approve to build and test.",
              },
            },
          ],
        },
        build: {
          name: "Build and test",
          needs: "approve",
          steps: [
            {
              uses: "relay/agent@v1",
              with: {
                agent: "claude",
                model: "m1",
                prompt: "Implement: ${{ inputs.task }}",
              },
            },
            {
              name: "Check project health",
              run: "git diff --check && git rev-parse --is-inside-work-tree && printf '# Health check\\n\\nRepository checks passed.\\n' > HEALTH.md && printf 'Repository checks passed.\\n'",
            },
            {
              uses: "relay/upload-artifact@v1",
              with: { name: "health-check", path: "HEALTH.md" },
            },
          ],
        },
      },
    }),
  );
  await expect(page.locator(".react-flow__node")).toHaveCount(3);
  await expect(page.getByText("Ready to edit", { exact: true })).toBeVisible();
  const canvas = page.getByRole("application", {
    name: "Workflow graph editor",
    exact: true,
  });
  await canvas.getByRole("button", { name: "Fit View", exact: true }).click();
  await expect(canvas.locator(".react-flow__node").last()).toBeInViewport();
  await yaml.press("ControlOrMeta+Home");
  await capture("2. Edit connected jobs visually or in YAML", yaml, 4);
  await openJobSettings(page);
  const codex = page.getByRole("region", { name: "Codex configuration" });
  await expect(
    codex.getByRole("combobox", { name: "Effort", exact: true }),
  ).toBeEnabled();
  await codex.getByRole("combobox", { name: "Effort", exact: true }).click();
  await page.getByRole("option", { name: "High", exact: true }).click();
  await capture(
    "3. Choose each agent, exact model, and thinking effort",
    codex,
    4,
  );
  await closeJobSettings(page);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const canonical = page.getByRole("button", {
    name: "Save canonical YAML",
    exact: true,
  });
  if (await canonical.isVisible()) await canonical.click();
  await expect(
    page.getByText("Workflow and instructions saved and validated."),
  ).toBeVisible();
  await page
    .getByRole("region", { name: "Workflow header" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const launch = page.getByRole("dialog", {
    name: "Run workflow",
    exact: true,
  });
  await launch
    .getByRole("textbox", { name: "Task", exact: true })
    .fill("Add a project health check.");
  await expect(
    launch.getByRole("button", { name: "Run workflow", exact: true }),
  ).toBeEnabled();
  await capture(
    "4. Enter the task and launch on an isolated branch",
    launch,
    4,
  );
  const launched = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  await launch
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const response = await launched;
  expect(response.status(), await response.text()).toBe(201);
  const { run_id: runId } = await response.json();
  await expect
    .poll(async () => {
      const detail = (
        await (await page.request.get(`/api/runs/${runId}`)).json()
      ).run;
      if (detail.status === "failed") {
        throw new Error(
          JSON.stringify(detail.problem ?? detail.failure_summary),
        );
      }
      return detail.status;
    })
    .toBe("paused_wait");
  const waiting = page.getByRole("region", {
    name: "Waiting for you",
    exact: true,
  });
  await expect(waiting).toBeVisible();
  await capture("5. Follow progress; approval holds the next job", waiting, 4);
  await waiting.getByRole("button", { name: "Respond", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your review is needed" }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Review material", exact: true })
    .click();
  await page.getByRole("option", { name: "PLAN.md", exact: true }).click();
  await expect(page.locator(".review-preview")).toContainText(
    "Implementation plan",
  );
  await page
    .getByLabel("Your response", { exact: true })
    .fill("Approved. Build and run the checks.");
  await capture(
    "6. Respond when the workflow needs your decision",
    page.getByLabel("Your response", { exact: true }),
    4,
  );
  await page
    .getByRole("button", { name: "Send response and continue", exact: true })
    .click();
  await expect(
    page.getByText(
      "Work is complete. Review the saved documents and code changes below.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(
    page.getByRole("heading", { name: /Plan, approve, build, test #1/ }),
  ).toBeVisible();
  await capture("7. Completed work and run history stay saved", undefined, 4);
  await page.goto(`/?view=runs&run=${runId}&job=root.build`);
  const log = page.getByRole("region", { name: "Job log", exact: true });
  await log.getByRole("button", { name: /2\. Check project health/ }).click();
  await expect(log).toContainText("Repository checks passed.");
  await capture("8. Inspect each job and its command output", log, 4);
  await page.goto(`/?view=runs&run=${runId}`);
  const preview = page.getByRole("button", {
    name: "Preview health-check",
    exact: true,
  });
  await expect(preview).toBeVisible();
  await preview.click();
  const artifact = page.getByRole("dialog", {
    name: "health-check",
    exact: true,
  });
  await expect(artifact).toContainText("Repository checks passed.");
  await capture("9. Preview or download the retained artifacts", artifact, 4);
  frames.push(`file 'frame-${String(count - 1).padStart(2, "0")}.png'`);
  await writeFile(join(directory, "frames.txt"), frames.join("\n") + "\n");
});
