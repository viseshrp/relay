import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

import { parseGitDiff } from "../src/diff";

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

test("file indexing preserves source text and counts across separate hunks", () => {
  const files = parseGitDiff(patch);
  expect(files.map((file) => [file.after, file.status, file.additions, file.removals])).toEqual([
    ["src/app.ts", "Modified", 3, 2], ["my file.ts", "Added", 1, 0],
  ]);
  expect(files.every((file) => file.hasHunks)).toBeTruthy();
  expect(files.map((file) => file.patch).join("")).toBe(patch);
  expect(files[0].patch).toContain("+\t  kept indentation\r\n \n");
  expect(files[0].patch).toContain("@@ -20 +21 @@\n---starts with two dashes\n+++starts with two pluses\n\\ No newline at end of file\n");
});

test("source text containing Git headers stays inside its file", () => {
  const original = "diff --git a/a b/a\n@@ -1 +1,2 @@\n context\n+diff --git a/b b/b\n";
  const files = parseGitDiff(original);
  expect(files).toHaveLength(1);
  expect(files[0].patch).toBe(original);
  expect(files[0].additions).toBe(1);
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
  expect(files[0].hasHunks).toBeTruthy();
  expect(files[0].patch.endsWith("+part")).toBeTruthy();
});

async function post(page: Page, path: string, data: object = {}) {
  const csrf = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  return page.request.post(path, { data, headers: { "X-CSRFToken": csrf?.value ?? "" } });
}

async function review(page: Page, key: string, text: string, truncated = false) {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/?view=workflows");
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
  await page.getByRole("region", { name: "Waiting for you", exact: true }).getByRole("button", { name: "Respond", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your review is needed" })).toBeVisible();
  await page.getByRole("button", { name: "Open review material", exact: true }).click();
  await expect(page.locator(".diff-viewer")).toBeVisible();
  return runId;
}

test("review switches files and layouts, expands, and preserves an unsent response", async ({ page }, testInfo) => {
  const runId = await review(page, "diff-review-layout", patch);
  const files = page.getByRole("navigation", { name: "Changed files" });
  await expect(files.getByRole("button")).toHaveCount(2);
  const comparison = page.locator("diffs-container");
  await expect(comparison.locator('[data-diff-type="single"]')).toBeVisible();
  await expect(comparison.locator('[data-code] [data-line][data-line-type="change-addition"]')).toHaveCount(3);
  await expect(comparison.locator('[data-code] [data-line="21"]')).toContainText("++starts with two pluses");
  await page.getByLabel("Your response", { exact: true }).fill("Still reviewing — do not send.");
  await files.getByRole("button", { name: "my file.ts", exact: false }).click();
  await expect(page.getByRole("region", { name: "Scrollable changes in my file.ts" })).toBeVisible();
  await expect(comparison.locator("[data-code] [data-line]")).toHaveText("<img src=x onerror=alert(1)>");
  await expect(page.locator(".diff-viewer img")).toHaveCount(0);
  await page.getByRole("button", { name: "Side by side", exact: true }).click();
  await expect(comparison.locator('[data-diff-type="single"]')).toBeVisible();
  await expect(page.locator(".diff-column-labels")).toHaveText("After");
  await files.getByRole("button", { name: "src/app.ts", exact: false }).click();
  await expect(comparison.locator('[data-diff-type="split"]')).toBeVisible();
  await files.getByRole("button", { name: "my file.ts", exact: false }).click();
  await page.getByRole("checkbox", { name: "Wrap lines" }).uncheck();
  await expect(comparison.locator('[data-overflow="scroll"]')).toBeVisible();
  await page.getByRole("button", { name: "Full screen", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Committed code changes" });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('diffs-container [data-diff-type="single"]')).toBeVisible();
  await dialog.getByRole("button", { name: "Show original patch" }).click();
  expect(await dialog.locator(".diff-original").textContent()).toBe(patch);
  await page.screenshot({ path: testInfo.outputPath("diff-full-screen.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Full screen", exact: true })).toBeFocused();
  await expect(page.getByLabel("Your response", { exact: true })).toHaveValue("Still reviewing — do not send.");
  await expect(page.getByRole("button", { name: "Side by side" })).toHaveAttribute("aria-pressed", "true");
  const response = (await (await page.request.get(`/api/runs/${runId}?collection=interactions&pending=true`)).json()).run;
  expect(response.status).toBe("paused_wait");
  expect(response.interactions).toHaveLength(1);
});

test("truncated changes remain explicitly partial in the expanded view", async ({ page }) => {
  await review(page, "diff-review-partial", patch, true);
  await expect(page.getByText("2 changed files in preview")).toBeVisible();
  await expect(page.locator(".diff-viewer").getByRole("alert")).toContainText("Counts cover only the displayed changes");
  await page.getByRole("button", { name: "Full screen", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("partial preview");
  await page.getByRole("button", { name: "Close full screen" }).click();
  await expect(page.getByRole("button", { name: "Full screen", exact: true })).toBeFocused();
  await expect(page.getByRole("button", { name: "Send response and continue" })).toBeDisabled();
});

test("a preview cut before a file's lines does not claim the file has no changes", async ({ page }) => {
  await review(page, "diff-review-partial-header", "diff --git a/app.ts b/app.ts\nindex 1234567..abcdef0 100644\n--- a/app.ts\n+++ b/app.ts\n", true);
  await expect(page.getByText("No text changes in this preview.", { exact: true })).toBeVisible();
  await expect(page.locator(".diff-viewer").getByRole("alert")).toContainText("partial preview");
});

test("file selection and long lines stay inside a narrow review screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await review(page, "diff-review-narrow", patch.replace("+new", `+${"long code ".repeat(80)}`));
  await page.getByRole("button", { name: "Side by side", exact: true }).click();
  expect(await page.locator(".diff-viewer").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy();
  const scroll = page.getByRole("region", { name: "Scrollable changes in src/app.ts" });
  await expect(scroll.locator('[data-overflow="wrap"]')).toBeVisible();
  expect(await scroll.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBeTruthy();
  await page.getByRole("checkbox", { name: "Wrap lines" }).uncheck();
  await expect(scroll.locator('[data-overflow="scroll"]')).toBeVisible();
  expect(await scroll.locator("[data-code]").evaluateAll((elements) => elements.some((element) => element.scrollWidth > element.clientWidth))).toBeTruthy();
});

test("code has syntax coloring and word-level highlights in both layouts", async ({ page }) => {
  await review(page, "diff-review-highlight", "diff --git a/app.ts b/app.ts\n--- a/app.ts\n+++ b/app.ts\n@@ -1 +1 @@\n-const count = 1;\n+const count = 2;\n");
  const comparison = page.locator("diffs-container");
  await expect(comparison.locator('[data-line-type="change-addition"] [data-diff-span]')).toHaveText("2");
  await expect(comparison.locator('[data-line-type="change-deletion"] [data-diff-span]')).toHaveText("1");
  await expect(comparison.locator('[data-code] span[style*="color:"]')).not.toHaveCount(0);
  await page.getByRole("button", { name: "Side by side", exact: true }).click();
  await expect(comparison.locator('[data-diff-type="split"]')).toBeVisible();
  await expect(comparison.locator('[data-line-type="change-addition"] [data-diff-span]')).toHaveText("2");
});

test("a preview ending inside a hunk preserves every byte in its fallback", async ({ page }) => {
  const original = "diff --git a/app.ts b/app.ts\n--- a/app.ts\n+++ b/app.ts\n@@ -1,3 +1,3 @@\n context\n-old\n+\tpart";
  await review(page, "diff-review-cut-hunk", original, true);
  await expect(page.getByRole("alert").filter({ hasText: "could not be displayed" })).toBeVisible();
  expect(await page.locator(".diff-original").textContent()).toBe(original);
  await expect(page.getByRole("button", { name: "Send response and continue" })).toBeDisabled();
});

test("a viewer load failure leaves the patch and review response available", async ({ page }) => {
  await page.route("**/assets/HighlightedDiff-*.js", (route) => route.abort());
  await review(page, "diff-review-load-failure", patch);
  await expect(page.getByRole("alert").filter({ hasText: "could not be displayed" })).toBeVisible();
  expect(await page.locator(".diff-original").textContent()).toBe(parseGitDiff(patch)[0].patch);
  await page.getByLabel("Your response", { exact: true }).fill("Comparison unavailable; still reviewing.");
  await page.getByRole("button", { name: "Full screen", exact: true }).click();
  await page.getByRole("button", { name: "Close full screen" }).click();
  await expect(page.getByLabel("Your response", { exact: true })).toHaveValue("Comparison unavailable; still reviewing.");
});

test("unsupported patches retain their original text as an inert fallback", async ({ page }) => {
  const original = "Unrecognized patch\n<script>alert('not executable')</script>\n";
  await review(page, "diff-review-fallback", original);
  await expect(page.locator(".diff-viewer").getByRole("alert")).toContainText("cannot be formatted");
  expect(await page.locator(".diff-original").textContent()).toBe(original);
  await expect(page.locator(".diff-viewer script")).toHaveCount(0);
});
