import assert from "node:assert/strict";
import {
  mkdtemp,
  mkdir,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { test } from "node:test";
import {
  checkoutSha,
  reportTests,
  verifyPartition,
  verifyRuns,
  verifyTestResults,
} from "./verify-browser.mjs";

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
      metadata: { relayCheckout: sha },
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
  const shards = Array.from({ length: 4 }, (_, index) =>
    expected(report("functional", index + 1), "functional"),
  );
  const groups = { functional: shards.flat() };
  for (const group of ["no-login", "visual", "unit"])
    groups[group] = expected(report(group, 1), group);
  const inventoryPath = join(directory, "inventory.json");
  await save(inventoryPath, { schema: 1, sha, total: 4, groups, shards });
  const runs = [];
  for (let shard = 0; shard <= 4; shard++) {
    const root = join(directory, shard ? `shard-${shard}` : "unit");
    const names =
      shard === 0
        ? ["unit"]
        : shard === 4
          ? ["functional", "no-login", "visual"]
          : ["functional"];
    for (const group of names) {
      await save(
        join(root, group, "report.json"),
        report(group, group === "functional" ? shard : 1),
      );
      await mkdir(join(root, group, "blob"));
      await writeFile(join(root, group, "blob", "report.zip"), "blob");
    }
    runs.push(root);
  }
  return { inventoryPath, runs };
}
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

test("complete aggregate verifies native reports from every suite", async () => {
  await temporary(async (directory) => {
    const { inventoryPath } = await fixture(directory);
    const blobs = join(directory, "..", `${basename(directory)}-merged`);
    try {
      assert.equal(await verifyRuns(directory, inventoryPath, sha, blobs), 7);
      assert.equal((await readdir(blobs)).length, 6);
      assert.equal(
        JSON.parse(
          await readFile(join(directory, "browser-summary.json"), "utf8"),
        ).tests,
        7,
      );
    } finally {
      await rm(blobs, { recursive: true, force: true });
    }
  });
});

for (const damage of [
  "missing shard",
  "missing unit",
  "extra shard",
  "missing group",
  "wrong shard",
  "wrong sha",
  "failed case",
  "unstarted case",
  "missing blob",
]) {
  test(`native aggregate rejects ${damage}`, async () => {
    await temporary(async (directory) => {
      const { inventoryPath, runs } = await fixture(directory);
      const root = runs[4];
      const result = report("functional", 4);
      if (damage === "missing shard") await rm(root, { recursive: true });
      else if (damage === "missing unit")
        await rm(runs[0], { recursive: true });
      else if (damage === "extra shard")
        await mkdir(join(directory, "shard-5"));
      else if (damage === "missing group")
        await rm(join(root, "visual"), { recursive: true });
      else if (damage === "missing blob")
        await rm(join(root, "visual", "blob"), { recursive: true });
      else {
        if (damage === "wrong shard") result.config.shard.current = 3;
        if (damage === "wrong sha")
          result.config.metadata.relayCheckout = "wrong";
        if (damage === "failed case")
          result.suites[0].specs[0].tests[0].results[0].status = "failed";
        if (damage === "unstarted case")
          result.suites[0].specs[0].tests[0].results = [];
        await save(join(root, "functional", "report.json"), result);
      }
      const blobs = join(directory, "..", `${basename(directory)}-merged`);
      try {
        await assert.rejects(verifyRuns(directory, inventoryPath, sha, blobs));
      } finally {
        await rm(blobs, { recursive: true, force: true });
      }
    });
  });
}

test("trusted failed native reports still contribute HTML blobs", async () => {
  await temporary(async (directory) => {
    const { inventoryPath, runs } = await fixture(directory);
    const result = report("functional", 1);
    result.suites[0].specs[0].tests[0].results[0].status = "failed";
    await save(join(runs[1], "functional", "report.json"), result);
    const blobs = join(directory, "..", `${basename(directory)}-merged`);
    try {
      await assert.rejects(verifyRuns(directory, inventoryPath, sha, blobs));
      assert.equal((await readdir(blobs)).length, 6);
    } finally {
      await rm(blobs, { recursive: true, force: true });
    }
  });
});
