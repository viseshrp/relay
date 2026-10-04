import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

import { parseGitDiff, splitDiffLines } from "../src/diff";

const patch = [
  "diff --git a/src/app.ts b/src/app.ts",
  "index 1234567..abcdef0 100644",
  "--- a/src/app.ts", "+++ b/src/app.ts",
  "@@ -3,4 +3,5 @@ function greet() {",
  " context", "-old", "+new", "+\t  kept indentation\r", " ", " tail",
  "@@ -20 +21 @@",
  "---starts with two dashes", "+++starts with two pluses", "\\ No newline at end of file",
  "diff --git a/my file.ts b/my file.ts",
  "new file mode 100644", "--- /dev/null", "+++ b/my file.ts", "@@ -0,0 +1 @@",
  "+<img src=x onerror=alert(1)>", "",
].join("\n");

test("unified patches preserve source text and line numbers across separate hunks", () => {
  const files = parseGitDiff(patch);
  expect(files.map((file) => [file.after, file.status, file.additions, file.removals])).toEqual([
    ["src/app.ts", "Modified", 3, 2], ["my file.ts", "Added", 1, 0],
  ]);
  expect(files[0].hunks[0].lines.map((line) => [line.kind, line.before, line.after, line.text])).toEqual([
    ["context", 3, 3, "context"], ["removed", 4, null, "old"], ["added", null, 4, "new"],
    ["added", null, 5, "\t  kept indentation\r"], ["context", 5, 6, ""], ["context", 6, 7, "tail"],
  ]);
  expect(files[0].hunks[1].lines).toEqual([
    { kind: "removed", before: 20, after: null, text: "--starts with two dashes" },
    { kind: "added", before: null, after: 21, text: "++starts with two pluses", noNewline: true },
  ]);
  expect(files[1].hunks[0].lines[0].after).toBe(1);
});

test("split rows preserve every change and leave excess additions or removals unpaired", () => {
  const lines = parseGitDiff("diff --git a/a b/a\n@@ -1,4 +1,4 @@\n-a\n-b\n+c\n context\n-d\n+e\n+f\n")[0].hunks[0].lines;
  const rows = splitDiffLines(lines);
  expect(rows.map((row) => [row.before?.text ?? null, row.after?.text ?? null])).toEqual([
    ["a", "c"], ["b", null], ["context", "context"], ["d", "e"], [null, "f"],
  ]);
  expect(rows.flatMap((row) => row.before ? [row.before] : [])).toEqual(lines.filter((line) => line.kind !== "added"));
  expect(rows.flatMap((row) => row.after ? [row.after] : [])).toEqual(lines.filter((line) => line.kind !== "removed"));
});

test("renames, copies, deleted, empty, mode-only, and binary files stay visible without hunks", () => {
  const files = parseGitDiff([
    "diff --git a/old.ts b/new.ts", "similarity index 100%", "rename from old.ts", "rename to new.ts",
    "diff --git a/new.ts b/copy.ts", "similarity index 100%", "copy from new.ts", "copy to copy.ts",
    "diff --git a/gone.ts b/gone.ts", "deleted file mode 100644", "--- a/gone.ts", "+++ /dev/null", "@@ -1 +0,0 @@", "-gone",
    "diff --git a/empty.ts b/empty.ts", "new file mode 100644", "index 0000000..e69de29",
    "diff --git a/exec b/exec", "old mode 100644", "new mode 100755",
    "diff --git a/dir b/file b/dir b/file", "Binary files a/dir b/file and b/dir b/file differ",
  ].join("\n"));
  expect(files.map((file) => [file.before, file.after, file.status, file.binary])).toEqual([
    ["old.ts", "new.ts", "Renamed", false], ["new.ts", "copy.ts", "Copied", false],
    ["gone.ts", "/dev/null", "Deleted", false], ["empty.ts", "empty.ts", "Added", false],
    ["exec", "exec", "Modified", false], ["dir b/file", "dir b/file", "Modified", true],
  ]);
  expect(files[4].metadata).toEqual(["old mode 100644", "new mode 100755"]);
});

test("Git quoted filenames decode UTF-8 and preserve escaped controls and invalid bytes", () => {
  const files = parseGitDiff(String.raw`diff --git "a/r\303\251sum\303\251.ts" "b/r\303\251sum\303\251.ts"
--- "a/r\303\251sum\303\251.ts"
+++ "b/r\303\251sum\303\251.ts"
@@ -1 +1 @@
-old
+new
diff --git "a/tab\tname.ts" "b/tab\tname.ts"
diff --git "a/invalid\377.ts" "b/invalid\377.ts"
diff --git "a/quote\"name.ts" "b/quote\"name.ts"
`);
  expect(files.map((file) => file.after)).toEqual(["résumé.ts", String.raw`"b/tab\tname.ts"`, String.raw`"b/invalid\377.ts"`, 'quote"name.ts']);
});

test("empty, unrecognized, and partial patches do not invent missing changes", () => {
  expect(parseGitDiff("")).toEqual([]);
  expect(parseGitDiff("a patch in an unsupported format")).toEqual([]);
  const files = parseGitDiff("diff --git a/a b/a\n@@ -1,99 +1,99 @@\n context\n+part");
  expect(files[0].additions).toBe(1);
  expect(files[0].hunks[0].lines.at(-1)?.text).toBe("part");
});

async function post(page: Page, path: string, data: object = {}) {
  const csrf = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  return page.request.post(path, { data, headers: { "X-CSRFToken": csrf?.value ?? "" } });
}

async function review(page: Page, key: string, text: string, truncated = false) {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  expect((await post(page, "/api/workflows", {
    key, holder,
    yaml: stringify({ version: 1, name: "Diff review", nodes: { review: { type: "human_wait", prompt: "Inspect changes before responding." } } }),
  })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const launched = await post(page, "/api/runs", { workflow_key: key, inputs: {} });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  // Replace only the patch response; the run and human review use the real server.
  await page.route(`**/api/runs/${runId}/changes`, (route) => route.fulfill({ json: { text, truncated } }));
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(page.getByRole("heading", { name: "Your review is needed" })).toBeVisible();
  await page.getByRole("button", { name: "Open review material", exact: true }).click();
  await expect(page.locator(".diff-viewer")).toBeVisible();
  return runId;
}

test("review switches files and layouts, expands, and preserves an unsent response", async ({ page }, testInfo) => {
  const runId = await review(page, "diff-review-layout", patch);
  const files = page.getByRole("navigation", { name: "Changed files" });
  await expect(files.getByRole("button")).toHaveCount(2);
  await expect(page.getByRole("table", { name: "Changes in src/app.ts" })).toBeVisible();
  await expect(page.locator(".diff-table-inline .diff-added")).toHaveCount(3);
  await page.getByLabel("Your response", { exact: true }).fill("Still reviewing — do not send.");
  await files.getByRole("button", { name: "my file.ts", exact: false }).click();
  await expect(page.getByRole("table", { name: "Changes in my file.ts" })).toBeVisible();
  await expect(page.locator(".diff-code-text")).toHaveText("<img src=x onerror=alert(1)>");
  await expect(page.locator(".diff-viewer img")).toHaveCount(0);
  await page.getByRole("button", { name: "Side by side", exact: true }).click();
  await expect(page.locator(".diff-table-split")).toBeVisible();
  await page.getByRole("checkbox", { name: "Wrap lines" }).uncheck();
  await expect(page.locator(".diff-scroll")).not.toHaveClass(/diff-wrap/);
  await page.getByRole("button", { name: "Full screen", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Committed code changes" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("table", { name: "Changes in my file.ts" })).toBeVisible();
  await dialog.getByRole("button", { name: "Show original patch" }).click();
  expect(await dialog.locator(".diff-original").textContent()).toBe(patch);
  await page.screenshot({ path: testInfo.outputPath("diff-full-screen.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByLabel("Your response", { exact: true })).toHaveValue("Still reviewing — do not send.");
  await expect(page.getByRole("button", { name: "Side by side" })).toHaveAttribute("aria-pressed", "true");
  const response = (await (await page.request.get(`/api/runs/${runId}?collection=interactions&pending=true`)).json()).run;
  expect(response.status).toBe("paused_wait");
  expect(response.interactions).toHaveLength(1);
});

test("truncated changes remain explicitly partial in the expanded view", async ({ page }) => {
  await review(page, "diff-review-partial", patch, true);
  await expect(page.getByText("2 changed files in preview")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Counts cover only the displayed changes");
  await page.getByRole("button", { name: "Full screen", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("partial preview");
  await page.getByRole("button", { name: "Close full screen" }).click();
  await expect(page.getByRole("button", { name: "Send response and continue" })).toBeDisabled();
});

test("a preview cut before a file's lines does not claim the file has no changes", async ({ page }) => {
  await review(page, "diff-review-partial-header", "diff --git a/app.ts b/app.ts\nindex 1234567..abcdef0 100644\n--- a/app.ts\n+++ b/app.ts\n", true);
  await expect(page.getByText("No text changes in this preview.", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("partial preview");
});

test("file selection and long lines stay inside a narrow review screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await review(page, "diff-review-narrow", patch.replace("+new", `+${"long code ".repeat(80)}`));
  await page.getByRole("button", { name: "Side by side", exact: true }).click();
  expect(await page.locator(".diff-viewer").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy();
  const scroll = page.getByRole("region", { name: "Scrollable changes in src/app.ts" });
  expect(await scroll.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBeTruthy();
  await page.getByRole("checkbox", { name: "Wrap lines" }).uncheck();
  expect(await scroll.evaluate((element) => element.scrollWidth > element.clientWidth)).toBeTruthy();
});

test("unsupported patches retain their original text as an inert fallback", async ({ page }) => {
  const original = "Unrecognized patch\n<script>alert('not executable')</script>\n";
  await review(page, "diff-review-fallback", original);
  await expect(page.getByRole("alert")).toContainText("cannot be formatted");
  expect(await page.locator(".diff-original").textContent()).toBe(original);
  await expect(page.locator(".diff-viewer script")).toHaveCount(0);
});
