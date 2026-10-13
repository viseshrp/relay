import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import {
  copyFile,
  lstat,
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

const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
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

export async function assetFiles(root, prefix = "") {
  const files = [];
  for (const name of (await readdir(join(root, prefix))).sort()) {
    const relative = prefix ? `${prefix}/${name}` : name;
    const path = join(root, relative);
    const stat = await lstat(path);
    if (stat.isDirectory()) files.push(...(await assetFiles(root, relative)));
    else if (stat.isFile())
      files.push({
        path: relative,
        size: stat.size,
        sha256: digest(await readFile(path)),
      });
    else throw new Error(`Unsupported build asset: ${relative}.`);
  }
  return files;
}

export async function prepareAssets(
  root,
  output,
  archive,
  sha = checkoutSha(),
) {
  const files = await assetFiles(root);
  if (!files.some((file) => file.path === "index.html"))
    throw new Error("The browser build has no index.html.");
  const manifest = {
    schema: 1,
    sha,
    files,
    treeSha256: digest(JSON.stringify(files)),
    archiveSha256: digest(await readFile(archive)),
  };
  await save(join(output, "assets-manifest.json"), manifest);
  return manifest;
}

export async function verifyAssets(
  root,
  manifestPath,
  archive,
  sha = checkoutSha(),
) {
  const manifest = await json(manifestPath);
  assertSha(manifest, sha);
  if (manifest.schema !== 1)
    throw new Error("Unsupported asset manifest schema.");
  if (digest(await readFile(archive)) !== manifest.archiveSha256)
    throw new Error("Browser asset archive checksum mismatch.");
  const files = await assetFiles(root);
  if (
    JSON.stringify(files) !== JSON.stringify(manifest.files) ||
    digest(JSON.stringify(files)) !== manifest.treeSha256
  )
    throw new Error("Browser asset tree checksum mismatch.");
  return manifest;
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
  return { value, hash: digest(await readFile(path)) };
}

export async function executeGroup(group, shard, total, directory) {
  const output = join(directory, group);
  await mkdir(output, { recursive: true });
  const args = [
    "test",
    "--config",
    configs[group],
    "--workers=1",
    "--retries=0",
    "--forbid-only",
    "--update-snapshots=none",
    "--reporter=line,json,blob",
    `--output=${join(output, "test-results")}`,
  ];
  if (group === "functional") args.push(`--shard=${shard}/${total}`);
  const started = Date.now();
  const env = {
    ...process.env,
    PLAYWRIGHT_JSON_OUTPUT_FILE: join(output, "report.json"),
    PLAYWRIGHT_BLOB_OUTPUT_DIR: join(output, "blob"),
    PLAYWRIGHT_BLOB_OUTPUT_NAME: `report-${group}-${shard}.zip`,
  };
  delete env.PLAYWRIGHT_BLOB_OUTPUT_FILE;
  const result = spawnSync(process.execPath, [playwright, ...args], {
    cwd: frontend,
    env,
    stdio: "inherit",
    shell: false,
  });
  return {
    group,
    exitCode: result.status,
    signal: result.signal,
    error: result.error?.message,
    durationMs: Date.now() - started,
  };
}

export async function runGroups({
  kind,
  shard,
  total,
  directory,
  inventoryPath,
  run = executeGroup,
}) {
  directory = resolve(directory);
  const { value, hash } = await loadInventory(inventoryPath);
  if (total !== value.total)
    throw new Error("Shard count does not match inventory.");
  const selected = kind === "unit" ? ["unit"] : ["functional"];
  if (kind === "shard" && shard === total) selected.push("no-login", "visual");
  const record = {
    schema: 1,
    sha: value.sha,
    inventorySha256: hash,
    kind,
    shard,
    total,
    completed: false,
    groups: [],
  };
  await mkdir(directory, { recursive: true });
  const recordPath = join(directory, "browser-run.json");
  await writeFile(recordPath, `${JSON.stringify(record, null, 2)}\n`, {
    flag: "wx",
  });
  for (const group of selected) {
    try {
      record.groups.push(await run(group, shard, total, directory));
    } catch (error) {
      record.groups.push({ group, exitCode: null, error: error.message });
    }
    await save(recordPath, record);
  }
  record.completed = true;
  await save(recordPath, record);
  return record.groups.every((group) => group.exitCode === 0) ? 0 : 1;
}

async function findRuns(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await findRuns(path)));
    else if (entry.name === "browser-run.json") files.push(path);
  }
  return files;
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
  const { value, hash } = await loadInventory(inventoryPath, sha);
  const files = await findRuns(directory);
  const seen = new Set();
  const timings = [];
  const errors = [];
  for (const path of files) {
    const run = await json(path);
    assertSha(run, sha);
    if (
      run.schema !== 1 ||
      !run.completed ||
      run.inventorySha256 !== hash ||
      run.total !== value.total
    )
      throw new Error(`Incomplete or mismatched browser run: ${path}.`);
    const unit = run.kind === "unit";
    if (
      !unit &&
      (run.kind !== "shard" ||
        !Number.isInteger(run.shard) ||
        run.shard < 1 ||
        run.shard > value.total)
    )
      throw new Error(`Invalid browser shard: ${path}.`);
    const key = unit ? "unit" : `shard-${run.shard}`;
    if (seen.has(key)) throw new Error(`Duplicate browser run: ${key}.`);
    seen.add(key);
    const expectedGroups = unit ? ["unit"] : ["functional"];
    if (!unit && run.shard === value.total)
      expectedGroups.push("no-login", "visual");
    if (
      JSON.stringify(run.groups.map((group) => group.group)) !==
      JSON.stringify(expectedGroups)
    )
      throw new Error(`Missing or unexpected browser groups in ${key}.`);
    for (const group of run.groups) {
      if (group.exitCode !== 0 || group.signal || group.error)
        errors.push(`Browser process failed: ${key}/${group.group}.`);
      const root = join(dirname(path), group.group);
      const report = await json(join(root, "report.json"));
      const expected =
        group.group === "functional"
          ? value.shards[run.shard - 1]
          : value.groups[group.group];
      if (
        group.group === "functional" &&
        (report.config?.shard?.current !== run.shard ||
          report.config?.shard?.total !== value.total)
      )
        throw new Error(`Incorrect Playwright shard in ${key}.`);
      // Failed outcomes remain gate errors, but their trusted reports are needed
      // to diagnose the failure in the merged HTML report.
      let tests;
      try {
        tests = verifyTestResults(expected, report, group.group);
      } catch (error) {
        errors.push(`${key}/${group.group}: ${error.message}`);
        tests = reportTests(report, group.group);
      }
      const blobs = (await readdir(join(root, "blob"))).filter((name) =>
        name.endsWith(".zip"),
      );
      if (blobs.length !== 1)
        throw new Error(
          `Missing or duplicate blob report: ${key}/${group.group}.`,
        );
      // Unit reports have a different testDir and cannot share the browser merge.
      if (blobDirectory && !unit) {
        await mkdir(blobDirectory, { recursive: true });
        await copyFile(
          join(root, "blob", blobs[0]),
          join(blobDirectory, `${key}-${group.group}.zip`),
        );
      }
      timings.push({
        run: key,
        group: group.group,
        tests: tests.length,
        durationMs: group.durationMs,
        slowest: [...tests]
          .filter((test) => test.results?.[0])
          .sort((a, b) => b.results[0].duration - a.results[0].duration)
          .slice(0, 10)
          .map((test) => ({
            title: test.title,
            durationMs: test.results[0].duration,
          })),
      });
    }
  }
  if (
    !seen.has("unit") ||
    Array.from(
      { length: value.total },
      (_, index) => `shard-${index + 1}`,
    ).some((key) => !seen.has(key))
  )
    throw new Error("Missing browser shard or frontend unit run.");
  await save(join(directory, "browser-summary.json"), { sha, timings, errors });
  if (process.env.GITHUB_STEP_SUMMARY) {
    const lines = [
      "## Browser test timings",
      "",
      "| Run | Group | Tests | Seconds |",
      "| --- | --- | ---: | ---: |",
    ];
    for (const timing of timings)
      lines.push(
        `| ${timing.run} | ${timing.group} | ${timing.tests} | ${(timing.durationMs / 1000).toFixed(1)} |`,
      );
    if (errors.length) lines.push("", "Verification errors:", "", ...errors);
    await writeFile(process.env.GITHUB_STEP_SUMMARY, `${lines.join("\n")}\n`, {
      flag: "a",
    });
  }
  if (errors.length)
    throw new Error(`Browser verification failed:\n${errors.join("\n")}`);
  return timings;
}

function options(args) {
  const parsed = {};
  for (let index = 0; index < args.length; index += 2) {
    const name = args[index];
    if (
      !name.startsWith("--") ||
      !args[index + 1] ||
      parsed[name.slice(2)] !== undefined
    )
      throw new Error(`Invalid option ${name}.`);
    parsed[name.slice(2)] = args[index + 1];
  }
  return parsed;
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  const opts = options(args);
  const required = (...names) => {
    for (const name of names)
      if (!opts[name]) throw new Error(`Missing --${name}.`);
  };
  const total = Number(opts.total ?? 4);
  const shard = Number(opts.shard ?? 0);
  if (
    !Number.isInteger(total) ||
    total < 1 ||
    !Number.isInteger(shard) ||
    shard < 0 ||
    shard > total
  )
    throw new Error("Invalid shard or total.");
  if (command === "prepare-assets") {
    required("assets-root", "output-dir", "archive");
    await prepareAssets(
      resolve(opts["assets-root"]),
      resolve(opts["output-dir"]),
      resolve(opts.archive),
    );
  } else if (command === "verify-assets") {
    required("assets-root", "manifest", "archive");
    await verifyAssets(
      resolve(opts["assets-root"]),
      resolve(opts.manifest),
      resolve(opts.archive),
    );
  } else if (command === "inventory") {
    required("output");
    const value = await inventory(resolve(opts.output), total);
    console.log(
      JSON.stringify(
        Object.fromEntries(
          Object.entries(value.groups).map(([name, tests]) => [
            name,
            tests.length,
          ]),
        ),
      ),
    );
  } else if (command === "run" || command === "unit") {
    required("reports-dir", "inventory");
    if (command === "run" && !shard) throw new Error("Missing --shard.");
    process.exitCode = await runGroups({
      kind: command === "unit" ? "unit" : "shard",
      shard,
      total,
      directory: opts["reports-dir"],
      inventoryPath: resolve(opts.inventory),
    });
  } else if (command === "verify") {
    required("reports-dir", "inventory", "sha");
    assertSha({ sha: opts.sha }, checkoutSha());
    await verifyRuns(
      resolve(opts["reports-dir"]),
      resolve(opts.inventory),
      opts.sha,
      opts["merged-blobs"] && resolve(opts["merged-blobs"]),
    );
  } else throw new Error(`Unknown browser CI command: ${command}.`);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
