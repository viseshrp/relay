import { execFileSync, spawnSync } from "node:child_process";
import { dirname } from "node:path";

import { expect, test, type Page } from "@playwright/test";
import { stringify } from "yaml";

import { expectRunStatus, post } from "./setup-helpers";

// `scripts/docker.sh e2e` runs these flows against the published port of a
// container it started with a disposable repository and data directory mounted
// at their host paths. They cover what the entrypoint bridge and the mounts can
// change; the local browser suite covers the same screens in detail.
const container = required("RELAY_CONTAINER_NAME");
const repository = required("RELAY_CONTAINER_REPOSITORY");
const dataHome = required("RELAY_CONTAINER_DATA_HOME");
const owner = { username: "owner", password: "Relay-Test-Passphrase-2026!" };
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
  const holder = await page.evaluate(() =>
    sessionStorage.getItem("relay.editor-holder"),
  );
  const created = await post(page, "/api/workflows", { key, holder, yaml });
  expect(created.status(), await created.text()).toBe(201);
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
  // Keep the run worktree so host Git can resolve it after the run.
  await page
    .getByRole("option", { name: "Keep the working copy", exact: true })
    .click();
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
  await expectRunStatus(page, id, "succeeded", 60_000);
  const jobs = page.getByRole("navigation", { name: "Jobs", exact: true });
  await jobs.locator("[data-job-scope]").click();
  await page
    .getByRole("region", { name: "Job steps", exact: true })
    .getByRole("button", { name: /3\. Approved/ })
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
  hostGit("add", ".relay/workflows/container-review.yaml");
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
  await expectRunStatus(page, id, "canceled", 60_000);
  await expect
    .poll(() => containerProcesses().includes("sleep 600"), {
      timeout: 15_000,
    })
    .toBe(false);
});
