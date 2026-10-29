import { execFileSync, spawnSync } from "node:child_process";
import { dirname } from "node:path";

import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

import { post } from "./setup-helpers";

// `scripts/docker.sh e2e` runs these flows against the published port of a
// container it started with a disposable repository and data directory mounted
// at their host paths. They cover what the entrypoint bridge and the mounts can
// change; the local browser suite covers the same screens in detail.
const container = required("RELAY_CONTAINER_NAME");
const repository = required("RELAY_CONTAINER_REPOSITORY");
const dataHome = required("RELAY_CONTAINER_DATA_HOME");
const owner = { username: "owner", password: "Relay-Test-Passphrase-2026!" };
const agentWritten = "Agent output written in the container.";
const written = "Written by Relay in the container.";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Run the container flows with make docker-e2e.`);
  return value;
}

function hostGit(...args: string[]): string {
  return execFileSync("git", ["-C", repository, ...args], {
    encoding: "utf8",
  });
}

function containerProcesses(): string[] {
  return execFileSync("docker", ["exec", container, "ps", "-eo", "args="], {
    encoding: "utf8",
  })
    .split("\n")
    .map((line) => line.trim());
}

function installContainerCodexAgent(): void {
  execFileSync(
    "docker",
    [
      "exec",
      container,
      "sh",
      "-ec",
      `
        pkg="$(mktemp -d)"
        cat >"$pkg/package.json" <<'EOF'
{"name":"@agentclientprotocol/codex-acp","version":"1.2.3","bin":{"codex-acp":"./bin.js"}}
EOF
        cat >"$pkg/bin.js" <<'EOF'
#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

if (process.argv.includes("--version")) {
  console.log("codex-acp 1.2.3");
  process.exit(0);
}

let selected = "m1";
let cwd = process.cwd();
const selector = () => ({
  id: "model",
  name: "Model",
  category: "model",
  type: "select",
  currentValue: selected,
  options: [
    { value: "m1", name: "Model One" },
    { value: "m2", name: "Model Two" },
  ],
});
const send = (payload) => process.stdout.write(JSON.stringify(payload) + "\\n");

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  if (!line.trim()) return;
  const msg = JSON.parse(line);
  const id = msg.id;
  const params = msg.params || {};
  if (msg.method === "initialize") {
    send({
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: 1,
        agentInfo: { name: "codex-acp", version: "1.2.3" },
        agentCapabilities: { sessionCapabilities: { close: {} } },
        authMethods: [],
      },
    });
  } else if (msg.method === "session/new") {
    if (typeof params.cwd === "string" && params.cwd) cwd = params.cwd;
    selected = "m1";
    send({
      jsonrpc: "2.0",
      id,
      result: { sessionId: "container-session", configOptions: [selector()] },
    });
  } else if (msg.method === "session/set_config_option") {
    if (params.configId === "model" && typeof params.value === "string") {
      selected = params.value;
    }
    send({ jsonrpc: "2.0", id, result: { configOptions: [selector()] } });
  } else if (msg.method === "session/prompt") {
    fs.writeFileSync(path.join(cwd, "agent-e2e.txt"), "${agentWritten}\\n", "utf8");
    send({
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: "container-session",
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "Agent completed in the container." },
        },
      },
    });
    send({ jsonrpc: "2.0", id, result: { stopReason: "end_turn" } });
  } else if (msg.method === "session/close") {
    send({ jsonrpc: "2.0", id, result: {} });
  }
});
EOF
        chmod +x "$pkg/bin.js"
        tarball="$(cd "$pkg" && npm pack --silent)"
        npm install -g --no-audit --no-fund "$pkg/$tarball" >/dev/null
        rm -rf "$pkg"
        test "$(command -v codex-acp)" = "/home/relay/.local/bin/codex-acp"
      `,
    ],
    { encoding: "utf8" },
  );
}

async function signIn(page: Page, button: string): Promise<void> {
  await page.goto("/?view=workflows");
  await page.getByRole("textbox", { name: "Username" }).fill(owner.username);
  await page.getByLabel(/^Password/).fill(owner.password);
  await page.getByRole("button", { name: button, exact: true }).click();
  await expect(
    page.getByRole("button", {
      name: `Account menu for ${owner.username}`,
      exact: true,
    }),
  ).toBeVisible();
}

async function createWorkflow(page: Page, key: string, yaml: string) {
  // The workflow workspace creates this tab's editor holder once it mounts.
  const holder = await (
    await page.waitForFunction(() =>
      sessionStorage.getItem("relay.editor-holder"),
    )
  ).jsonValue();
  const created = await post(page, "/api/workflows", { key, holder, yaml });
  expect(created.status(), await created.text()).toBe(201);
}

async function expectContainerRunStatus(
  page: Page,
  id: string,
  status: string,
): Promise<void> {
  let run: { status: string; problem?: unknown } = { status: "pending" };
  // Idle keep-alive sockets across the published-port bridge can reset once after Uvicorn's 5s timeout.
  await expect
    .poll(
      async () => {
        const response = await page.request
          .get(`/api/runs/${id}`)
          .catch(() => null);
        if (!response) return false;
        expect(response.ok(), await response.text()).toBeTruthy();
        run = (await response.json()).run;
        return (
          run.status === status ||
          ["succeeded", "failed", "canceled"].includes(run.status)
        );
      },
      { timeout: 60_000 },
    )
    .toBe(true);
  expect(run).toMatchObject({ status });
}

// The second flow signs in to the owner account that the first one creates.
test.describe.configure({ mode: "serial" });

test("a new owner runs a workflow, answers its wait live, and host Git sees the commit", async ({
  page,
}) => {
  // The bridge closes connections until Relay accepts them.
  await expect
    .poll(
      async () =>
        (await page.request.get("/api/auth").catch(() => null))?.status(),
      { timeout: 60_000 },
    )
    .toBe(200);
  await signIn(page, "Create password");
  // The session cookie set through the published port survives a reload.
  await page.reload();
  await expect(
    page.getByRole("button", {
      name: `Account menu for ${owner.username}`,
      exact: true,
    }),
  ).toBeVisible();
  const current = await page.request.get("/api/projects/current");
  expect((await current.json()).project.canonical_path).toBe(repository);

  installContainerCodexAgent();
  const agentsResponse = await post(page, "/api/agents/check", {});
  expect(agentsResponse.status()).toBe(200);
  const codex = (await agentsResponse.json()).agents.find(
    (entry: { id: string }) => entry.id === "codex",
  );
  expect(codex).toMatchObject({
    id: "codex",
    installed: true,
    ready: true,
    models: ["m1", "m2"],
  });

  await createWorkflow(
    page,
    "container-review",
    stringify({
      name: "Container review",
      on: "workflow_dispatch",
      jobs: {
        write: {
          steps: [
            {
              id: "agent",
              uses: "relay/agent@v1",
              with: {
                agent: "codex",
                model: "m1",
              },
            },
            {
              id: "write",
              shell: "sh",
              run: `printf '%s\\n' '${written}' > container-e2e.txt`,
            },
            {
              id: "approval",
              uses: "relay/human-wait@v1",
              with: {
                prompt: "Approve the container change.",
                options: '["Approve", "Reject"]',
              },
            },
            {
              id: "approved",
              if: "steps.approval.outputs.answer == 'Approve'",
              shell: "sh",
              run: "echo 'Approved in the container.'",
            },
          ],
        },
      },
    }),
  );
  await page.goto("/?view=workflows&workflow=container-review.yaml");
  await page
    .getByRole("region", { name: "Workflow header" })
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const panel = page.getByRole("dialog", { name: "Run workflow", exact: true });
  await panel.getByText("Advanced options", { exact: true }).click();
  await panel
    .getByRole("combobox", { name: "After a successful run", exact: true })
    .click();
  const retainPreflight = page.waitForResponse(
    (response) =>
      response
        .url()
        .includes("/api/workflows/container-review.yaml/preflight") &&
      response.url().includes("cleanup_policy=retain"),
  );
  // Keep the run worktree so host Git can resolve it after the run.
  await page
    .getByRole("option", { name: "Keep the working copy", exact: true })
    .click();
  await retainPreflight;
  const launched = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/runs") &&
      response.request().method() === "POST",
  );
  const stream = page.waitForResponse((response) =>
    /^\/api\/runs\/[^/]+\/stream$/.test(new URL(response.url()).pathname),
  );
  await panel
    .getByRole("button", { name: "Run workflow", exact: true })
    .click();
  const launch = await launched;
  expect(launch.status(), await launch.text()).toBe(201);
  const id: string = (await launch.json()).run_id;
  const events = await stream;
  expect(new URL(events.url()).pathname).toBe(`/api/runs/${id}/stream`);
  expect(events.status()).toBe(200);
  expect(events.headers()["content-type"]).toContain("text/event-stream");

  // The open page learns of the wait from the event stream, without a reload.
  const waiting = page.getByRole("region", {
    name: "Waiting for you",
    exact: true,
  });
  await expect(waiting).toContainText("Approve the container change.", {
    timeout: 60_000,
  });
  await waiting.getByRole("button", { name: "Respond", exact: true }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expectContainerRunStatus(page, id, "succeeded");
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  await jobs.locator("[data-job-scope]").click();
  await page
    .getByRole("region", { name: "Job steps", exact: true })
    .getByRole("button", { name: /4\. Approved/ })
    .click();
  await expect(
    page.getByRole("region", { name: "Command output lines" }),
  ).toContainText("Approved in the container.");

  const run = (await (await page.request.get(`/api/runs/${id}`)).json()).run;
  const branch = `refs/heads/${run.run_branch}`;
  const head = hostGit("rev-parse", "--verify", branch).trim();
  expect(hostGit("rev-parse", "--verify", `${head}^`).trim()).toBe(
    run.source_commit,
  );
  expect(hostGit("show", `${head}:agent-e2e.txt`)).toBe(`${agentWritten}\n`);
  expect(hostGit("show", `${head}:container-e2e.txt`)).toBe(`${written}\n`);
  // Relay registered the run worktree from inside the container; host Git must
  // resolve it at the same path rather than report it as prunable.
  expect(dirname(run.working_folder)).toBe(`${dataHome}/relay/worktrees`);
  const record = hostGit("worktree", "list", "--porcelain")
    .split("\n\n")
    .find((block) => block.startsWith(`worktree ${run.working_folder}\n`));
  expect(record?.trim().split("\n")).toEqual([
    `worktree ${run.working_folder}`,
    `HEAD ${head}`,
    `branch ${branch}`,
  ]);
  // Git reports what prune would remove on standard error.
  const prune = spawnSync(
    "git",
    ["-C", repository, "worktree", "prune", "--dry-run", "--verbose"],
    { encoding: "utf8" },
  );
  expect(prune.status).toBe(0);
  expect(prune.stdout + prune.stderr).toBe("");
});

test("a returning owner cancels a running command and its process stops", async ({
  page,
}) => {
  await signIn(page, "Sign in");
  // Launch rejects other untracked workflows, so commit the first flow's.
  hostGit("add", ".relay");
  hostGit("commit", "-q", "-m", "Add the container review workflow");
  await createWorkflow(
    page,
    "container-cancel",
    stringify({
      name: "Container cancel",
      on: "workflow_dispatch",
      jobs: {
        wait: { steps: [{ id: "wait", shell: "sh", run: "sleep 600" }] },
      },
    }),
  );
  hostGit("add", ".relay");
  hostGit("commit", "-q", "-m", "Add the container cancel workflow");
  const launch = await post(page, "/api/runs", {
    workflow_key: "container-cancel.yaml",
    inputs: {},
  });
  expect(launch.status(), await launch.text()).toBe(201);
  const id: string = (await launch.json()).run_id;
  await expect
    .poll(() => containerProcesses().includes("sleep 600"), {
      timeout: 60_000,
    })
    .toBe(true);

  await page.goto(`/?view=runs&run=${id}`);
  await page.getByRole("button", { name: "Cancel run", exact: true }).click();
  await page
    .getByRole("dialog", { name: "Cancel this run?" })
    .getByRole("button", { name: "Cancel run", exact: true })
    .click();
  await expectContainerRunStatus(page, id, "canceled");
  await expect
    .poll(() => containerProcesses().includes("sleep 600"), {
      timeout: 15_000,
    })
    .toBe(false);
});
