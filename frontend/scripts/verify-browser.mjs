import { spawnSync } from "node:child_process";
import {
  copyFile,
  mkdir,
  readFile,
  readdir,
  writeFile,
} from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("../", import.meta.url));
const repository = resolve(frontend, "..");
const playwright = join(frontend, "node_modules/playwright/cli.js");
const configs = {
  functional: "playwright.config.ts",
  "no-login": "playwright.no-login.config.ts",
  visual: "playwright.visual.config.ts",
  unit: "playwright.unit.config.ts",
};

const json = async (path) => JSON.parse(await readFile(path, "utf8"));
const save = async (path, value) => {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`);
};

export function checkoutSha() {
  const result = spawnSync("git", ["rev-parse", "HEAD"], {
    cwd: repository,
    encoding: "utf8",
    shell: false,
  });
  if (result.status !== 0) throw new Error("Cannot read the checkout SHA.");
  return result.stdout.trim();
}

function assertSha(value, sha) {
  if (value.sha !== sha)
    throw new Error(
      `Checkout SHA mismatch: expected ${sha}, got ${value.sha}.`,
    );
}

export function reportTests(report, group) {
  const tests = [];
  function visit(suite, titles = []) {
    for (const spec of suite.specs ?? []) {
      for (const test of spec.tests) {
        tests.push({
          id: `${group}:${spec.id}:${test.projectId}`,
          title: [...titles, spec.title].join(" > "),
          file: spec.file,
          line: spec.line,
          expectedStatus: test.expectedStatus,
          status: test.status,
          results: test.results,
        });
      }
    }
    for (const child of suite.suites ?? [])
      visit(child, [...titles, child.title]);
  }
  for (const suite of report.suites ?? []) visit(suite, [suite.title]);
  return tests;
}

function unique(tests, label) {
  const ids = new Set();
  for (const test of tests) {
    if (ids.has(test.id)) throw new Error(`Duplicate ${label}: ${test.id}.`);
    ids.add(test.id);
  }
  return ids;
}

export function verifyPartition(expected, shards) {
  const ids = unique(expected, "inventory test");
  const actual = unique(shards.flat(), "sharded test");
  if (ids.size !== actual.size || [...ids].some((id) => !actual.has(id)))
    throw new Error(
      "Functional shard inventory does not match the full inventory.",
    );
}

function list(group, shard, total) {
  const args = [
    "test",
    "--config",
    configs[group],
    "--list",
    "--reporter=json",
  ];
  if (shard) args.push(`--shard=${shard}/${total}`);
  const env = { ...process.env };
  // Listing must print JSON rather than inherit an output-file override.
  for (const name of Object.keys(env))
    if (name.startsWith("PLAYWRIGHT_JSON_OUTPUT_")) delete env[name];
  const result = spawnSync(process.execPath, [playwright, ...args], {
    cwd: frontend,
    env,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
    shell: false,
  });
  if (result.status !== 0)
    throw new Error(
      `Cannot collect ${group}: ${result.stderr || result.error || result.stdout}`,
    );
  const report = JSON.parse(result.stdout);
  if (report.errors?.length) throw new Error(`Collection errors in ${group}.`);
  if (report.config.fullyParallel !== false || report.config.workers !== 1)
    throw new Error(
      `Browser inventory requires one serial worker in ${group}.`,
    );
  const tests = reportTests(report, group).map((test) => ({
    id: test.id,
    title: test.title,
    file: test.file,
    line: test.line,
    expectedStatus: test.expectedStatus,
  }));
  unique(tests, `${group} inventory test`);
  if (!tests.length) throw new Error(`No tests collected for ${group}.`);
  return tests;
}

export async function inventory(output, total) {
  const groups = Object.fromEntries(
    Object.keys(configs).map((group) => [group, list(group)]),
  );
  const shards = Array.from({ length: total }, (_, index) =>
    list("functional", index + 1, total),
  );
  verifyPartition(groups.functional, shards);
  const value = { schema: 1, sha: checkoutSha(), total, groups, shards };
  await save(output, value);
  return value;
}

async function loadInventory(path, sha = checkoutSha()) {
  const value = await json(path);
  assertSha(value, sha);
  if (value.schema !== 1 || !Number.isInteger(value.total) || value.total < 1)
    throw new Error("Invalid browser inventory.");
  for (const group of Object.keys(configs)) {
    if (!value.groups[group]?.length)
      throw new Error(`Missing ${group} inventory.`);
    unique(value.groups[group], `${group} inventory test`);
  }
  if (!Array.isArray(value.shards) || value.shards.length !== value.total)
    throw new Error("Incorrect number of functional shard inventories.");
  verifyPartition(value.groups.functional, value.shards);
  return value;
}

export function verifyTestResults(expected, report, group) {
  if (report.errors?.length) throw new Error(`Playwright errors in ${group}.`);
  if (
    report.config?.workers !== 1 ||
    report.config?.fullyParallel !== false ||
    report.config?.projects?.some((project) => project.retries !== 0)
  )
    throw new Error(`Unsafe parallelism or retries in ${group}.`);
  const tests = reportTests(report, group);
  const ids = unique(tests, `${group} result`);
  const expectedIds = unique(expected, `${group} inventory test`);
  if (
    ids.size !== expectedIds.size ||
    [...ids].some((id) => !expectedIds.has(id))
  )
    throw new Error(`Missing or unexpected tests in ${group}.`);
  const expectedById = new Map(expected.map((test) => [test.id, test]));
  for (const test of tests) {
    if (test.expectedStatus !== expectedById.get(test.id).expectedStatus)
      throw new Error(`Unexpected skip or expected-status change: ${test.id}.`);
    const skipped = test.expectedStatus === "skipped";
    if (
      (!skipped && test.status !== "expected") ||
      (skipped && test.status !== "skipped") ||
      test.results.length !== 1 ||
      test.results[0].retry !== 0 ||
      test.results[0].status !== test.expectedStatus
    )
      throw new Error(
        `Failed, missing, skipped, retried, or interrupted test: ${test.id}.`,
      );
  }
  return tests;
}

export async function verifyRuns(directory, inventoryPath, sha, blobDirectory) {
  const value = await loadInventory(inventoryPath, sha);
  const errors = [];
  const groups = [["unit", "unit", value.groups.unit]];
  for (let shard = 1; shard <= value.total; shard++) {
    groups.push([`shard-${shard}`, "functional", value.shards[shard - 1]]);
    if (shard === value.total) {
      groups.push([`shard-${shard}`, "no-login", value.groups["no-login"]]);
      groups.push([`shard-${shard}`, "visual", value.groups.visual]);
    }
  }
  const directories = new Set(groups.map(([run]) => run));
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && !directories.has(entry.name))
      errors.push(`Unexpected browser run: ${entry.name}.`);
  }
  let count = 0;
  for (const [run, group, expected] of groups) {
    const output = join(directory, run, group);
    try {
      const report = await json(join(output, "report.json"));
      assertSha({ sha: report.config?.metadata?.relayCheckout }, sha);
      if (group === "functional") {
        const shard = Number(run.split("-")[1]);
        if (
          report.config.shard?.current !== shard ||
          report.config.shard?.total !== value.total
        )
          throw new Error(`Incorrect Playwright shard: ${run}.`);
      }
      // Preserve native blob reports even when a trusted run contains failures.
      // Unit reports have a separate test directory and remain separate.
      if (blobDirectory && group !== "unit") {
        const blobs = (await readdir(join(output, "blob"))).filter((name) =>
          name.endsWith(".zip"),
        );
        if (blobs.length !== 1)
          throw new Error(`Missing or duplicate blob report: ${run}/${group}.`);
        await mkdir(blobDirectory, { recursive: true });
        await copyFile(
          join(output, "blob", blobs[0]),
          join(blobDirectory, `${run}-${group}.zip`),
        );
      }
      count += verifyTestResults(expected, report, group).length;
    } catch (error) {
      errors.push(`${run}/${group}: ${error.message}`);
    }
  }
  await save(join(directory, "browser-summary.json"), {
    sha,
    tests: count,
    errors,
  });
  if (errors.length)
    throw new Error(`Browser verification failed:\n${errors.join("\n")}`);
  console.log(`Verified ${count} browser and unit tests.`);
  return count;
}

async function main() {
  const [command, first, second, third] = process.argv.slice(2);
  if (command === "inventory" && first && !second)
    await inventory(resolve(first), 4);
  else if (command === "verify" && first && second && third)
    await verifyRuns(
      resolve(first),
      resolve(second),
      checkoutSha(),
      resolve(third),
    );
  else
    throw new Error("Use: inventory OUTPUT | verify REPORTS INVENTORY BLOBS");
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
