import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdtemp,
  mkdir,
  readFile,
  readdir,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  assetFiles,
  checkoutSha,
  prepareAssets,
  reportTests,
  runGroups,
  verifyAssets,
  verifyPartition,
  verifyRuns,
  verifyTestResults,
} from "./ci-browser.mjs";

const sha = checkoutSha();
const save = async (path, value) => {
  await mkdir(join(path, ".."), { recursive: true });
  await writeFile(path, `${JSON.stringify(value)}\n`);
};

async function temporary(run) {
  const directory = await mkdtemp(join(tmpdir(), "relay-ci-browser-"));
  try {
    await run(directory);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

function report(group, number, expectedStatus = "passed") {
  return {
    config: {
      workers: 1,
      fullyParallel: false,
      projects: [{ retries: 0 }],
      shard: group === "functional" ? { current: number, total: 4 } : null,
    },
    errors: [],
    suites: [
      {
        title: `${group}.spec.ts`,
        specs: [
          {
            title: `${group} scenario ${number}`,
            id: `test-${number}`,
            file: `${group}.spec.ts`,
            line: number,
            tests: [
              {
                projectId: "",
                expectedStatus,
                status: expectedStatus === "skipped" ? "skipped" : "expected",
                results: [{ status: expectedStatus, retry: 0, duration: 10 }],
              },
            ],
          },
        ],
      },
    ],
  };
}

function expected(report, group) {
  return reportTests(report, group).map((value) => ({
    id: value.id,
    title: value.title,
    file: value.file,
    line: value.line,
    expectedStatus: value.expectedStatus,
  }));
}

async function fixture(directory) {
  const groups = {};
  const shards = Array.from({ length: 4 }, (_, index) =>
    expected(report("functional", index + 1), "functional"),
  );
  groups.functional = shards.flat();
  for (const group of ["no-login", "visual", "unit"])
    groups[group] = expected(report(group, 1), group);
  const inventory = { schema: 1, sha, total: 4, groups, shards };
  const inventoryPath = join(directory, "inventory.json");
  await save(inventoryPath, inventory);
  const inventorySha256 = createHash("sha256")
    .update(await readFile(inventoryPath))
    .digest("hex");
  const runs = [];
  for (const shard of [0, 1, 2, 3, 4]) {
    const unit = shard === 0;
    const names = unit
      ? ["unit"]
      : shard === 4
        ? ["functional", "no-login", "visual"]
        : ["functional"];
    const root = join(directory, `run-${shard}`);
    const run = {
      schema: 1,
      sha,
      inventorySha256,
      kind: unit ? "unit" : "shard",
      shard,
      total: 4,
      completed: true,
      groups: names.map((group) => ({
        group,
        exitCode: 0,
        signal: null,
        durationMs: 11,
      })),
    };
    await save(join(root, "browser-run.json"), run);
    for (const group of names) {
      await save(
        join(root, group, "report.json"),
        report(group, group === "functional" ? shard : 1),
      );
      await mkdir(join(root, group, "blob"));
      await writeFile(join(root, group, "blob", "report.zip"), "blob");
    }
    runs.push({ root, run });
  }
  return { inventoryPath, inventory, runs };
}

test("asset manifest retains hidden manifests and compressed companions", async () => {
  await temporary(async (directory) => {
    const root = join(directory, "assets");
    const archive = join(directory, "assets.tgz");
    await mkdir(join(root, ".vite"), { recursive: true });
    await writeFile(join(root, "index.html"), "entry");
    await writeFile(join(root, "index.html.br"), "compressed");
    await writeFile(join(root, ".vite", "manifest.json"), "{}");
    await writeFile(archive, "archive");
    const manifest = await prepareAssets(root, directory, archive, sha);
    assert.deepEqual(
      manifest.files.map((file) => file.path),
      [".vite/manifest.json", "index.html", "index.html.br"],
    );
    const manifestPath = join(directory, "assets-manifest.json");
    await verifyAssets(root, manifestPath, archive, sha);
    await assert.rejects(
      verifyAssets(root, manifestPath, archive, "different-sha"),
      /SHA mismatch/,
    );
    await writeFile(archive, "damaged archive");
    await assert.rejects(
      verifyAssets(root, manifestPath, archive, sha),
      /archive checksum/,
    );
    await writeFile(archive, "archive");
    await writeFile(join(root, "index.html.br"), "damaged compressed asset");
    await assert.rejects(
      verifyAssets(root, manifestPath, archive, sha),
      /tree checksum/,
    );
    await writeFile(join(root, "index.html.br"), "compressed");
    await writeFile(join(root, "unexpected.js"), "extra");
    await assert.rejects(
      verifyAssets(root, manifestPath, archive, sha),
      /tree checksum/,
    );
  });
});

test("asset inventory rejects symlinks rather than following outside the build", async () => {
  await temporary(async (directory) => {
    const root = join(directory, "assets");
    await mkdir(root);
    await writeFile(join(directory, "outside"), "outside");
    await symlink(join(directory, "outside"), join(root, "linked"));
    await assert.rejects(assetFiles(root), /Unsupported build asset/);
  });
});

test("functional partitions reject omitted, duplicate, and unexpected cases", () => {
  const one = expected(report("functional", 1), "functional");
  const two = expected(report("functional", 2), "functional");
  verifyPartition([...one, ...two], [one, two]);
  assert.throws(
    () => verifyPartition([...one, ...two], [one]),
    /does not match/,
  );
  assert.throws(
    () => verifyPartition([...one, ...two], [one, two, one]),
    /Duplicate/,
  );
  assert.throws(() => verifyPartition(one, [two]), /does not match/);
});

test("result checks preserve expected failures and declared skips", () => {
  for (const status of ["passed", "failed", "skipped"]) {
    const result = report("visual", 1, status);
    assert.equal(
      verifyTestResults(expected(result, "visual"), result, "visual").length,
      1,
    );
  }
});

test("result checks reject failures, dynamic skips, retries, missing attempts and collection errors", () => {
  const reference = expected(report("functional", 1), "functional");
  const mutations = [
    (value) => {
      value.suites[0].specs[0].tests[0].status = "unexpected";
    },
    (value) => {
      value.suites[0].specs[0].tests[0].expectedStatus = "skipped";
    },
    (value) => {
      value.suites[0].specs[0].tests[0].results[0].retry = 1;
    },
    (value) => {
      value.suites[0].specs[0].tests[0].results = [];
    },
    (value) => {
      value.suites[0].specs[0].tests[0].results[0].status = "interrupted";
    },
    (value) => {
      value.suites[0].specs = [];
    },
    (value) => {
      value.suites[0].specs.push(value.suites[0].specs[0]);
    },
    (value) => {
      value.errors.push({ message: "collection failed" });
    },
    (value) => {
      value.config.workers = 2;
    },
    (value) => {
      value.config.fullyParallel = true;
    },
    (value) => {
      value.config.projects[0].retries = 1;
    },
  ];
  for (const mutate of mutations) {
    const result = report("functional", 1);
    mutate(result);
    assert.throws(() => verifyTestResults(reference, result, "functional"));
  }
});

test("last shard continues login and visual suites after a functional failure", async () => {
  await temporary(async (directory) => {
    const { inventoryPath } = await fixture(directory);
    const calls = [];
    const reports = join(directory, "execution");
    const code = await runGroups({
      kind: "shard",
      shard: 4,
      total: 4,
      directory: reports,
      inventoryPath,
      run: async (group) => {
        calls.push(group);
        if (group === "functional") throw new Error("failed to start");
        return { group, exitCode: 0 };
      },
    });
    assert.equal(code, 1);
    assert.deepEqual(calls, ["functional", "no-login", "visual"]);
    const result = JSON.parse(
      await readFile(join(reports, "browser-run.json"), "utf8"),
    );
    assert.equal(result.completed, true);
    assert.equal(result.groups[0].error, "failed to start");
    await assert.rejects(
      runGroups({
        kind: "shard",
        shard: 4,
        total: 4,
        directory: reports,
        inventoryPath,
      }),
      /EEXIST/,
    );
  });
});

test("complete aggregate validates every suite and copies uniquely named blobs", async () => {
  await temporary(async (directory) => {
    const { inventoryPath } = await fixture(directory);
    const blobs = join(directory, "merged");
    const timings = await verifyRuns(directory, inventoryPath, sha, blobs);
    assert.equal(timings.length, 7);
    assert.equal(
      timings.reduce((sum, group) => sum + group.tests, 0),
      7,
    );
    assert.equal(
      await readFile(join(blobs, "shard-4-visual.zip"), "utf8"),
      "blob",
    );
    assert.ok(
      JSON.parse(
        await readFile(join(directory, "browser-summary.json"), "utf8"),
      ).timings,
    );
  });
});

for (const failure of ["failed process", "failed case", "unstarted case"]) {
  test(`aggregate retains trusted reports after a ${failure}`, async () => {
    await temporary(async (directory) => {
      const { inventoryPath, runs } = await fixture(directory);
      const { root, run } = runs[1];
      run.groups[0].exitCode = 1;
      await save(join(root, "browser-run.json"), run);
      if (failure !== "failed process") {
        const result = report("functional", 1);
        const test = result.suites[0].specs[0].tests[0];
        test.status = "unexpected";
        if (failure === "failed case") test.results[0].status = "failed";
        else test.results = [];
        await save(join(root, "functional", "report.json"), result);
      }
      const blobs = join(directory, "merged");
      await assert.rejects(
        verifyRuns(directory, inventoryPath, sha, blobs),
        /Browser verification failed/,
      );
      assert.equal((await readdir(blobs)).length, 6);
      assert.equal(
        await readFile(join(blobs, "shard-1-functional.zip"), "utf8"),
        "blob",
      );
      assert.equal(
        await readFile(join(blobs, "shard-4-visual.zip"), "utf8"),
        "blob",
      );
      const summary = JSON.parse(
        await readFile(join(directory, "browser-summary.json"), "utf8"),
      );
      assert.equal(summary.timings.length, 7);
      assert.ok(summary.errors.length);
    });
  });
}

test("aggregate never copies a report from a different checkout", async () => {
  await temporary(async (directory) => {
    const { inventoryPath, runs } = await fixture(directory);
    const { root, run } = runs[1];
    run.sha = "wrong";
    await save(join(root, "browser-run.json"), run);
    const blobs = join(directory, "merged");
    await assert.rejects(
      verifyRuns(directory, inventoryPath, sha, blobs),
      /SHA mismatch/,
    );
    await assert.rejects(readFile(join(blobs, "shard-1-functional.zip")), {
      code: "ENOENT",
    });
  });
});

for (const scenario of [
  "missing shard",
  "missing unit",
  "duplicate run",
  "canceled run",
  "failed process",
  "wrong sha",
  "wrong inventory",
  "missing group",
  "wrong shard",
  "missing blob",
]) {
  test(`aggregate rejects ${scenario}`, async () => {
    await temporary(async (directory) => {
      const { inventoryPath, runs } = await fixture(directory);
      const { root, run } = runs[4];
      if (scenario === "missing shard") await rm(root, { recursive: true });
      else if (scenario === "missing unit")
        await rm(runs[0].root, { recursive: true });
      else if (scenario === "duplicate run")
        await save(
          join(directory, "duplicate", "browser-run.json"),
          runs[0].run,
        );
      else if (scenario === "wrong shard") {
        const result = report("functional", 4);
        result.config.shard.current = 3;
        await save(join(root, "functional", "report.json"), result);
      } else if (scenario === "missing blob")
        await rm(join(root, "visual", "blob"), { recursive: true });
      else {
        if (scenario === "canceled run") run.completed = false;
        if (scenario === "failed process") run.groups[0].exitCode = 1;
        if (scenario === "wrong sha") run.sha = "wrong";
        if (scenario === "wrong inventory") run.inventorySha256 = "wrong";
        if (scenario === "missing group") run.groups.pop();
        await save(join(root, "browser-run.json"), run);
      }
      await assert.rejects(verifyRuns(directory, inventoryPath, sha));
    });
  });
}
