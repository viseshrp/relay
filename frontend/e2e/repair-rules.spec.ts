import { expect, test, type Page } from "@playwright/test";
import { parse, stringify } from "yaml";
import { capturedRunGraph, visibleRunStages } from "../src/graph";
import type { RunNode } from "../src/types";

async function post(page: Page, path: string, data: object = {}) {
  const csrf = (await page.context().cookies()).find((item) => item.name === "relay_csrftoken");
  return page.request.post(path, { data, headers: { "X-CSRFToken": csrf?.value ?? "" } });
}

function node(scope: string, fields: Partial<RunNode> = {}): RunNode {
  return { id: scope, scope_path: scope, node_id: scope.split(".").at(-1)!, node_type: "command",
    status: "succeeded", writes: false, selected_branch: null, loop_index: null, parent_scope: null,
    dependencies: [], controls: [], ...fields };
}

test("only explicitly marked repairs leave the map and their edges stay connected", () => {
  const records = [node("root.review"), node("root.hidden", {
    node_type: "loop", dependencies: ["root.review"], repair_for: "root.review", status: "waiting",
    repair_settings: { legacy: false, max_rounds: 3, accepted_output: "ready", accepted_value: "Yes", fix_instruction: "fix", verify_instruction: "verify", roles: {} },
  }), node("root.hidden#1.fix", { parent_scope: "root.hidden#1", loop_index: 1 }),
  node("root.deliver", { status: "pending", dependencies: ["root.review", "root.hidden"] }),
  node("root.repairs", { node_type: "loop", status: "pending" })];
  expect(visibleRunStages(records).map((item) => item.scope_path)).toEqual(["root.review", "root.deliver", "root.repairs"]);
  const graph = capturedRunGraph(records);
  expect(graph.nodes.find((item) => item.id === "root.review")?.data.status).toBe("repairing");
  expect(graph.edges.map((edge) => [edge.source, edge.target])).toEqual([["root.review", "root.deliver"]]);
});

test("configure repairs, save and reload, then run fix and verification behind two stages", async ({ page }, testInfo) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  const reset = await post(page, "/__test__/reset");
  expect(reset.ok()).toBeTruthy();
  const python = (await reset.json()).python;
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const initial = "from pathlib import Path; Path('REVIEW.md').write_text('Ready: No\\n')";
  const fix = "from pathlib import Path; import subprocess; Path('fixed.txt').write_text('Fixed'); subprocess.run(['git','add','fixed.txt'],check=True); subprocess.run(['git','commit','-qm','Repair'],check=True)";
  const verify = "from pathlib import Path; Path('REVIEW_FIX_VERIFICATION.md').write_text('Ready: Yes\\n')";
  const created = await post(page, "/api/workflows", { key: "native-repairs", holder, yaml: stringify({
    version: 1, name: "Implicit repairs", nodes: {
      review: { type: "command", writes: true, allow_no_commit: true, run: [python, "-c", initial], outputs: { ready: { label: { artifact: "REVIEW.md", label: "Ready" } } } },
      deliver: { type: "command", needs: ["review"], if: "${{ needs.review.outputs.ready == 'Yes' }}", run: ["git", "status"] },
    }, repairs: { review: { max_rounds: 2, accepted_output: "ready", accepted_value: "Yes",
      fix: { type: "command", writes: true, run: [python, "-c", fix] },
      verify: { type: "command", writes: true, allow_no_commit: true, run: [python, "-c", verify], outputs: { ready: { label: { artifact: "REVIEW_FIX_VERIFICATION.md", label: "Ready" } } } },
    } },
  }) });
  expect(created.ok(), await created.text()).toBeTruthy();
  await page.goto("/?view=author&workflow=native-repairs.yaml");
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  await page.getByRole("button", { name: "Review Automatic repairs configured" }).click();
  await page.getByRole("button", { name: "Repairs", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Repairs for Review" });
  await settings.getByLabel("Maximum repair rounds", { exact: true }).fill("3");
  await settings.getByLabel("Fixer repair instructions", { exact: true }).fill("Fix the rejected findings without weakening checks.");
  await settings.getByRole("button", { name: "Verifier settings", exact: true }).click();
  await expect(settings.getByLabel("Verification report file", { exact: true })).toHaveValue("REVIEW_FIX_VERIFICATION.md");
  await settings.getByRole("button", { name: "Done", exact: true }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Workflow saved and validated.", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Review Automatic repairs configured" }).click();
  await page.getByRole("button", { name: "Repairs", exact: true }).click();
  await expect(page.getByLabel("Maximum repair rounds", { exact: true })).toHaveValue("3");
  await expect(page.getByLabel("Fixer repair instructions", { exact: true })).toHaveValue("Fix the rejected findings without weakening checks.");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const launched = await post(page, "/api/runs", { workflow_key: "native-repairs", inputs: {}, cleanup_policy: "retain" });
  expect(launched.ok(), await launched.text()).toBeTruthy();
  const { run_id: runId } = await launched.json();
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(page.getByText("Work is complete. Review the saved documents and code changes below.")).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Review · Complete", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Deliver · Complete", exact: true })).toBeVisible();
  await page.getByText("Repairs · 1 configured", { exact: true }).click();
  const panel = page.getByRole("region", { name: "Repairs for Review", exact: true });
  await expect(panel).toContainText("Round 1 of 3");
  await expect(panel).toContainText("Fix the rejected findings without weakening checks.");
  const detail = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  expect(detail.nodes.find((item: { scope_path: string }) => item.scope_path === "root.review").status).toBe("succeeded");
  const artifacts = (await (await page.request.get(`/api/runs/${runId}/artifacts`)).json()).artifacts;
  const bytes = await Promise.all(artifacts.filter((item: { name: string }) => item.name === "ready").map(async (item: { id: string }) => (await page.request.get(`/api/artifacts/${item.id}`)).text()));
  expect(bytes).toEqual(expect.arrayContaining([expect.stringMatching(/^Ready: No\r?\n$/), expect.stringMatching(/^Ready: Yes\r?\n$/)]));
  await page.screenshot({ path: testInfo.outputPath("implicit-repairs-complete.png"), fullPage: true });
});

test("a new repair rule keeps provider defaults and saves independent role choices", async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/");
  await page.getByRole("button", { name: "Work", exact: true }).click();
  await page.getByRole("button", { name: "Repairs", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Repairs for Work" });
  const fixer = dialog.getByRole("region", { name: "Codex configuration" });
  const effort = fixer.getByRole("combobox", { name: "Effort", exact: true });
  await expect(effort).toBeEnabled();
  await expect(effort).toHaveText("Provider default");
  await dialog.getByLabel("What should the agent do?", { exact: true }).fill("Fix the reported findings and preserve every required check.");
  await expect(dialog.getByLabel("Maximum repair rounds", { exact: true })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Verifier settings", exact: true })).toBeDisabled();
  await expect(effort).toBeDisabled();
  await dialog.getByRole("button", { name: "Save instructions", exact: true }).click();
  await expect(effort).toBeEnabled();
  await effort.click();
  await page.getByRole("option", { name: "Low", exact: true }).click();
  await dialog.getByRole("button", { name: "Verifier settings", exact: true }).click();
  await expect(dialog.getByRole("region", { name: "Codex configuration" }).getByRole("combobox", { name: "Effort", exact: true })).toHaveText("Provider default");
  await dialog.getByRole("combobox", { name: "Result type", exact: true }).click();
  await page.getByRole("option", { name: "Null", exact: true }).click();
  await expect(dialog.getByText("Passing result: null", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const confirmation = page.getByRole("button", { name: "Save canonical YAML", exact: true });
  if (await confirmation.isVisible()) await confirmation.click();
  await expect(page.getByText("Workflow saved and validated.")).toBeVisible();
  const document = parse((await (await page.request.get("/api/workflows/workflow")).json()).yaml);
  expect(document.repairs.work.fix.agent_options).toEqual({ codex: { effort: "low" } });
  expect(document.repairs.work.fix.prompts).toEqual([{ local: "prompts/ui/workflow/work-fix.md" }]);
  expect(document.repairs.work.verify.agent_options).toBeUndefined();
  expect(document.repairs.work.accepted_value).toBeNull();
  await page.reload();
  await page.getByRole("button", { name: "Work Automatic repairs configured", exact: true }).click();
  await page.getByRole("button", { name: "Repairs", exact: true }).click();
  await expect(page.getByText("Passing result: null", { exact: true })).toBeVisible();
});

test("exhausted repairs stop visibly at their source and keep every rejected report", async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  const reset = await post(page, "/__test__/reset");
  expect(reset.ok()).toBeTruthy();
  const python = (await reset.json()).python;
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const report = (file: string) => ({ type: "command", writes: true, allow_no_commit: true,
    run: [python, "-c", `from pathlib import Path; Path('${file}').write_text('Ready: No\\n')`],
    outputs: { ready: { label: { artifact: file, label: "Ready" } } },
  });
  const created = await post(page, "/api/workflows", { key: "repair-stop", holder, yaml: stringify({
    version: 1, name: "Stopped repairs", nodes: {
      review: report("REVIEW.md"), deliver: { type: "command", needs: ["review"], run: ["git", "status"] },
    }, repairs: { review: { accepted_output: "ready", max_rounds: 1,
      fix: { type: "command", run: ["git", "status"] }, verify: report("REVIEW_FIX_VERIFICATION.md"),
    } },
  }) });
  expect(created.ok(), await created.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const response = await post(page, "/api/runs", { workflow_key: "repair-stop", inputs: {}, cleanup_policy: "retain" });
  expect(response.ok(), await response.text()).toBeTruthy();
  const runId = (await response.json()).run_id;
  await page.goto(`/?view=runs&run=${runId}`);
  await expect(page.getByRole("heading", { name: "Review stopped", exact: true })).toBeVisible();
  await expect(page.getByText("The configured repair rounds ended without a passing verification. Open Repairs to inspect the rejected reports.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review · Repairs stopped", exact: true })).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  const detail = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  expect(detail.problem.error_code).toBe("repair_exhausted");
  expect(detail.nodes.find((item: { scope_path: string }) => item.scope_path === "root.deliver").status).toBe("canceled");
  const artifacts = (await (await page.request.get(`/api/runs/${runId}/artifacts`)).json()).artifacts;
  const reports = artifacts.filter((item: { name: string }) => item.name === "ready");
  expect(reports).toHaveLength(2);
  for (const artifact of reports) await expect((await page.request.get(`/api/artifacts/${artifact.id}`)).text()).resolves.toMatch(/^Ready: No\r?\n$/);
});

test("paused repair roles show saved model overrides instead of workflow defaults", async ({ page }) => {
  await page.request.get("/api/auth");
  expect((await post(page, "/api/auth/login", { username: "owner", password: "Relay-Test-Passphrase-2026!" })).ok()).toBeTruthy();
  expect((await post(page, "/__test__/reset")).ok()).toBeTruthy();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Add stage", exact: true })).toBeEnabled();
  const holder = await page.evaluate(() => sessionStorage.getItem("relay.editor-holder"));
  const created = await post(page, "/api/workflows", { key: "repair-settings", holder, yaml: stringify({
    version: 1, name: "Paused repair settings", model: "m1", agents: ["codex"], nodes: {
      review: { type: "command", run: ["git", "status"] },
      repairs: { type: "loop", needs: ["review"], max_iterations: 2, until: "${{ loop.index >= 1 }}", exhausted: "stopped", body: {
        wait: { type: "human_wait", prompt: "Hold this isolated repair" },
        verify: { type: "agent", needs: ["wait"], model: "m1", agents: ["codex"], agent_options: { codex: { effort: "low", permission_mode: "auto" } } },
      } },
      stopped: { type: "command", run: ["git", "status"] },
    },
  }) });
  expect(created.ok(), await created.text()).toBeTruthy();
  expect((await post(page, "/__test__/commit")).ok()).toBeTruthy();
  const launch = await post(page, "/api/runs", { workflow_key: "repair-settings", inputs: {}, cleanup_policy: "retain" });
  expect(launch.ok(), await launch.text()).toBeTruthy();
  const runId = (await launch.json()).run_id;
  await expect.poll(async () => {
    const run = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
    return run.nodes.find((item: { scope_path: string }) => item.scope_path === "root.repairs")?.status;
  }).toBe("waiting");
  const before = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  expect((await post(page, `/api/runs/${runId}/pause`, { paused: true, idempotency_key: "hold-repairs" })).ok()).toBeTruthy();
  expect((await post(page, `/api/runs/${runId}/repairs`, { groups: { "root.repairs": "root.review" }, idempotency_key: "group-repairs" })).ok()).toBeTruthy();
  const changed = await post(page, `/api/runs/${runId}/step-settings`, {
    scope_path: "root.repairs#1.verify", agent_id: "claude", model: "m1", effort: "high", permission_mode: "auto", idempotency_key: "change-verifier",
  });
  expect(changed.ok(), await changed.text()).toBeTruthy();
  await page.goto(`/?view=runs&run=${runId}`);
  await page.getByText("Repairs · 1 configured", { exact: true }).click();
  const panel = page.getByRole("region", { name: "Repairs for Review", exact: true });
  await expect(panel.getByRole("heading", { name: "Review · Repairs paused", exact: true })).toBeVisible();
  const verifier = panel.getByRole("region", { name: "Repair settings for Verify", exact: true });
  await expect(verifier).toContainText("Verify · m1");
  await expect(verifier).toContainText("Claude · Effort override: high · Permission override: auto");
  await expect(verifier).not.toContainText("Codex");
  await expect(page.getByRole("button", { name: "Resume", exact: true })).toBeVisible();
  const after = (await (await page.request.get(`/api/runs/${runId}`)).json()).run;
  expect(after.snapshot).toEqual(before.snapshot);
  expect(after.dispatch_paused).toBe(true);
  const canceled = await post(page, `/api/runs/${runId}/cancel`, { idempotency_key: "clean-test-hold" });
  expect(canceled.ok(), await canceled.text()).toBeTruthy();
});
