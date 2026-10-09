import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";
import { activityRows, relativeActivityText } from "../src/activity";
import { safeMarkdownHref } from "../src/components/SafeMarkdown";
import { toolStatus } from "../src/components/ActivityFeed";
import type { RunEvent } from "../src/types";
import { historicalPost as post } from "./setup-helpers";

function event(
  id: number,
  type: string,
  payload: RunEvent["payload"],
): RunEvent {
  return {
    id,
    type,
    version: 1,
    source: "agent",
    ts: "2026-10-07T12:00:00Z",
    payload: {
      scope_path: "root.review",
      attempt_number: 1,
      turn: 1,
      ...payload,
    },
  };
}

test("matched tools merge across messages without crossing attempts, jobs, or turns", () => {
  const rows = activityRows([
    event(1, "agent.tool_call", {
      tool: "Read",
      tool_call_id: "read-1",
      summary: JSON.stringify({
        status: "in_progress",
        raw_input: { file_path: "/work/run/REVIEW.md" },
      }),
    }),
    event(2, "agent.message", { text: "**Reviewing**" }),
    event(3, "agent.tool_result", {
      tool: "read-1",
      tool_call_id: "read-1",
      summary: '{"status":"completed",',
      part: 1,
      parts: 2,
    }),
    event(4, "agent.tool_result", {
      tool: "read-1",
      tool_call_id: "read-1",
      summary: '"content":[{"text":"Ready: Yes"}]}',
      part: 2,
      parts: 2,
    }),
    event(5, "agent.tool_call", {
      tool: "Read",
      tool_call_id: "read-1",
      summary: '{"status":"pending"}',
      attempt_number: 2,
    }),
    event(6, "agent.tool_call", {
      tool: "Read",
      tool_call_id: "read-1",
      summary: '{"status":"pending"}',
      scope_path: "root.other",
    }),
    event(7, "agent.tool_result", {
      tool: "Read",
      tool_call_id: "read-1",
      summary: '{"status":"failed"}',
      turn: 2,
    }),
  ]);
  expect(rows).toHaveLength(5);
  expect(rows[0]).toMatchObject({
    id: 1,
    lastId: 4,
    tool: {
      title: "Read /work/run/REVIEW.md",
      input: "/work/run/REVIEW.md",
      output: "Ready: Yes",
      status: "completed",
    },
  });
  expect(rows[1].text).toBe("**Reviewing**");
  expect(rows[4].tool?.status).toBe("failed");
  const native = activityRows([
    event(8, "agent.tool_result", {
      tool: "run_command",
      tool_call_id: "native-1",
      summary: JSON.stringify({
        state: "DONE",
        tool_info: {
          parameters: { CommandLine: "git status" },
          output: "clean",
        },
      }),
    }),
  ]);
  expect(native[0].tool).toMatchObject({
    title: "Ran git status",
    input: "git status",
    output: "clean",
  });
  for (const [status, text] of [
    ["DONE", "Completed"],
    ["failed", "Failed"],
    ["pending", "Waiting"],
    ["in_progress", "In progress"],
    ["unknown", "Status unavailable"],
  ])
    expect(toolStatus(status).text).toBe(text);
});

test("relative paths strip only recorded roots and reader folders on each platform", () => {
  expect(
    relativeActivityText(
      "Read /work/run/r-42/docs/guide.md and /work/run-extra/file",
      "/work/run/",
    ),
  ).toBe("Read docs/guide.md and /work/run-extra/file");
  expect(
    relativeActivityText("C:\\Relay\\Run\\r-2\\README.md", "c:\\relay\\run"),
  ).toBe("README.md");
  expect(relativeActivityText("/work/Run/file", "/work/run")).toBe(
    "/work/Run/file",
  );
  expect(
    relativeActivityText("printf '\\n' /work/run/app.py", "/work/run"),
  ).toBe("printf '\\n' app.py");
  expect(
    relativeActivityText(
      "/work/run.v1+(check)/docs/guide.md",
      "/work/run.v1+(check)",
    ),
  ).toBe("docs/guide.md");
  expect(relativeActivityText("unchanged")).toBe("unchanged");
  expect(relativeActivityText("/etc/hosts", "/")).toBe("/etc/hosts");
});

test("Markdown URLs reject executable, local, and malformed targets", () => {
  for (const value of [
    "javascript:alert(1)",
    "data:text/html,test",
    "file:///etc/hosts",
    "//example.test",
    "https://example.test/\nattack",
    "/api/settings",
  ])
    expect(safeMarkdownHref(value)).toBeUndefined();
  expect(safeMarkdownHref("#review")).toBe("#review");
  expect(safeMarkdownHref("mailto:owner@example.test")).toBe(
    "mailto:owner@example.test",
  );
  expect(safeMarkdownHref("https://example.test/guide")).toBe(
    "https://example.test/guide",
  );
});

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

async function setup(
  page: Page,
  key = "readable-activity",
): Promise<{ id: string; folder: string }> {
  const created = await post(page, "/api/workflows", {
    key,
    holder: "activity-test",
    yaml: stringify({
      version: 1,
      name: "Readable activity",
      nodes: {
        before: { type: "command", run: ["git", "status"] },
        review: {
          type: "human_wait",
          needs: ["before"],
          prompt: "Review the saved work.",
        },
      },
    }),
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const response = await post(page, "/api/runs", {
    workflow_key: key,
    inputs: {},
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const id: string = (await response.json()).run_id;
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/runs/${id}`)).json()).run.status,
    )
    .toBe("paused_wait");
  const folder: string = (
    await (await page.request.get(`/api/runs/${id}`)).json()
  ).run.working_folder;
  return { id, folder };
}

async function append(
  page: Page,
  id: string,
  type: string,
  payload: object,
): Promise<void> {
  const response = await post(page, "/__test__/activity", {
    run_id: id,
    scope: "root.review",
    type,
    payload,
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

test("Markdown formatting renders while HTML, images, and unsafe URLs stay inert", async ({
  page,
}) => {
  const { id } = await setup(page, "markdown-activity");
  await append(page, id, "agent.message", {
    text: "# Review\n\n**Passed** and *ready* with `git status`.\n\n- First\n- Second\n\n1. Check\n2. Approve\n\n> Saved report\n\n| Job | Status |\n| --- | --- |\n| Build | **Passed** |\n\n```python\nprint('<tag>')\n```\n\n[Docs](https://example.test/guide) [Bad](javascript:alert)\n![Image](https://example.test/track.png)\n<script>window.relayUnsafe=true</script>\n<img src=x onerror=alert(1)>\n\n---\n\n\\*literal\\*\n\n~~~\nUnclosed code",
  });
  await page.goto(`/?view=runs&run=${id}`);
  const markdown = page
    .getByRole("region", { name: "Activity feed", exact: true })
    .locator(".markdown-text");
  await expect(
    markdown.getByRole("heading", { name: "Review", exact: true }),
  ).toBeVisible();
  for (const tag of [
    "h1",
    "strong",
    "em",
    "code",
    "ul",
    "ol",
    "blockquote",
    "table",
    "pre",
    "hr",
  ])
    expect(await markdown.locator(tag).count()).toBeGreaterThan(0);
  const link = markdown.getByRole("link", { name: "Docs", exact: true });
  await expect(link).toHaveAttribute("href", "https://example.test/guide");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  await expect(
    markdown.getByRole("link", { name: "Bad", exact: true }),
  ).toHaveCount(0);
  await expect(markdown.locator("script, img")).toHaveCount(0);
  await expect(markdown).toContainText(
    "<script>window.relayUnsafe=true</script>",
  );
  await expect(markdown).toContainText("*literal*");
  await expect(markdown.locator("pre").last()).toContainText("Unclosed code");
  expect(await page.evaluate(() => "relayUnsafe" in window)).toBe(false);
});

test("Summary and job conversation show safe Markdown, one tool row, thoughts, and filters", async ({
  page,
}) => {
  const { id, folder } = await setup(page);
  await append(page, id, "agent.message", {
    text: "## Review result\n\n**Passed** with `git status`.\n\n<script>window.relayUnsafe = true</script>\n[Bad](javascript:alert)",
  });
  await append(page, id, "agent.tool_call", {
    tool: "Read",
    tool_call_id: "read-1",
    summary: JSON.stringify({
      status: "in_progress",
      raw_input: { file_path: `${folder}/r-2/REVIEW.md` },
    }),
  });
  await append(page, id, "agent.thought", {
    text: "Thought preview is collapsed.",
  });
  await append(page, id, "agent.tool_result", {
    tool: "read-1",
    tool_call_id: "read-1",
    summary: JSON.stringify({
      status: "completed",
      content: [{ text: "Ready: Yes" }],
    }),
  });
  await page.goto(`/?view=runs&run=${id}`);
  const feed = page.getByRole("region", { name: "Activity feed", exact: true });
  await expect(
    feed.getByRole("heading", { name: "Review result", exact: true }),
  ).toBeVisible();
  await expect(feed.locator("strong")).toHaveText("Passed");
  await expect(feed.locator("script")).toHaveCount(0);
  await expect(
    feed.getByRole("link", { name: "Bad", exact: true }),
  ).toHaveCount(0);
  const tool = feed.locator("details.activity-tool");
  await expect(tool).toHaveCount(1);
  await expect(tool.locator("summary")).toContainText(
    "Read REVIEW.md · Completed",
  );
  await tool.locator("summary").click();
  await expect(tool).toContainText("Ready: Yes");
  await expect(tool).not.toContainText(folder);
  const thoughts = feed
    .locator("details")
    .filter({ has: page.locator("summary", { hasText: /^Thoughts$/ }) });
  await expect(thoughts).not.toHaveAttribute("open");
  await thoughts.locator("summary").click();
  await expect(
    thoughts.getByText("Thought preview is collapsed.", { exact: true }),
  ).toBeVisible();
  await feed
    .getByRole("combobox", { name: "Filter by job", exact: true })
    .click();
  await page.getByRole("option", { name: "Before", exact: true }).click();
  await expect(feed).not.toContainText("Review result");
  await expect(feed).toContainText("Command finished");
  await feed
    .getByRole("combobox", { name: "Filter by job", exact: true })
    .click();
  await page.getByRole("option", { name: "Review", exact: true }).click();
  await feed
    .getByRole("textbox", { name: "Search activity", exact: true })
    .fill("REVIEW.md");
  await expect(feed.getByRole("article")).toHaveCount(1);
  await feed
    .getByRole("textbox", { name: "Search activity", exact: true })
    .fill("missing phrase");
  await expect(
    feed.getByText("No messages match these filters.", { exact: true }),
  ).toBeVisible();
  const diagnostics = page.locator(".MuiAccordion-root").filter({
    has: page.getByRole("button", {
      name: "Advanced diagnostics and saved files",
      exact: true,
    }),
  });
  await diagnostics
    .getByRole("button", {
      name: "Advanced diagnostics and saved files",
      exact: true,
    })
    .click();
  await expect(diagnostics.locator(".MuiCollapse-root")).toHaveClass(
    /MuiCollapse-entered/,
  );
  await expect(
    page.getByRole("heading", { name: "Event history", exact: true }),
  ).toBeHidden();
  await page
    .getByLabel("Raw event details", { exact: true })
    .locator(":scope > summary")
    .click();
  await expect(
    page.getByRole("heading", { name: "Event history", exact: true }),
  ).toBeVisible();
  const original: { events: RunEvent[] } = await (
    await page.request.get(`/api/runs/${id}/events?limit=200`)
  ).json();
  expect(
    original.events.some(
      (event) =>
        typeof event.payload.summary === "string" &&
        event.payload.summary.includes(`${folder}/r-2/REVIEW.md`),
    ),
  ).toBe(true);
  await page.goto(`/?view=runs&run=${id}&job=root.review`);
  await page.getByRole("button", { name: "Human review", exact: true }).click();
  const jobLog = page.getByRole("region", {
    name: "Human review log",
    exact: true,
  });
  await expect(
    jobLog.getByRole("heading", { name: "Review result", exact: true }),
  ).toBeVisible();
  await expect(
    jobLog.getByRole("combobox", { name: "Filter by job", exact: true }),
  ).toHaveCount(0);
  expect(
    await jobLog.evaluate((element) => getComputedStyle(element).overflowY),
  ).toBe("auto");
});

test("live output follows the page until scrolling up, then Jump to latest resumes it", async ({
  page,
}) => {
  const { id } = await setup(page, "live-activity");
  await append(page, id, "agent.message", {
    text: Array.from({ length: 90 }, (_, index) => `Line ${index}`).join("\n"),
  });
  await page.goto(`/?view=runs&run=${id}`);
  const feed = page.getByRole("region", { name: "Activity feed", exact: true });
  const follow = feed.getByRole("switch", {
    name: "Follow latest",
    exact: true,
  });
  await feed.getByRole("article").last().scrollIntoViewIfNeeded();
  await follow.uncheck();
  await follow.check();
  await append(page, id, "agent.message", { text: "\n\nNew live output" });
  await expect(
    feed.getByText("New live output", { exact: true }),
  ).toBeInViewport();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(follow).not.toBeChecked();
  const top = await page.evaluate(() => window.scrollY);
  await append(page, id, "agent.message", {
    text: "\n\nHeld at current scroll",
  });
  await expect(
    feed.getByText("Held at current scroll", { exact: true }),
  ).toBeAttached();
  expect(await page.evaluate(() => window.scrollY)).toBe(top);
  await feed
    .getByRole("button", { name: "Jump to latest", exact: true })
    .click();
  await expect(follow).toBeChecked();
  await expect(
    feed.getByText("Held at current scroll", { exact: true }),
  ).toBeInViewport();
});

test("one paging control reveals older messages and recovers from a page read failure", async ({
  page,
}) => {
  const { id } = await setup(page, "paged-activity");
  for (let index = 0; index < 105; index += 1)
    await append(page, id, "agent.message", {
      text: `Saved message ${index}`,
      message_id: `message-${index}`,
    });
  await page.goto(`/?view=runs&run=${id}`);
  const feed = page.getByRole("region", { name: "Activity feed", exact: true });
  await expect(feed.getByRole("article")).toHaveCount(100);
  await expect(feed.getByText("Saved message 0", { exact: true })).toHaveCount(
    0,
  );
  const earlier = feed.getByRole("button", {
    name: "Load earlier messages",
    exact: true,
  });
  await expect(earlier).toHaveCount(1);
  await earlier.click();
  await expect(
    feed.getByText("Saved message 0", { exact: true }),
  ).toBeVisible();
  await page.route(`**/api/runs/${id}/events?since=*&limit=100`, (route) =>
    route.fulfill({
      status: 503,
      json: {
        code: "persistence_error",
        message: "Relay could not read this activity page.",
        context: {},
      },
    }),
  );
  await earlier.click();
  await expect(feed.getByRole("alert")).toContainText(
    "Relay could not read this activity page.",
  );
  await expect(earlier).toBeEnabled();
  await page.unroute(`**/api/runs/${id}/events?since=*&limit=100`);
  await earlier.click();
  await expect(feed.getByRole("alert")).toHaveCount(0);
  await expect(earlier).toHaveCount(0);
});
