import { expect, test } from "./a11y-test";
import { post } from "./setup-helpers";
import type { ArtifactRecord, RunNode } from "../src/types";

test("one repair round and one artifact byte use singular labels", async ({
  page,
}) => {
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
  const response = await post(page, "/__test__/worst-case", { enabled: false });
  expect(response.ok()).toBeTruthy();
  const fixture: { project: string; run: string } = await response.json();
  const repair: RunNode = {
    id: "single-round",
    scope_path: "root.hidden",
    node_id: "hidden",
    node_type: "loop",
    status: "pending",
    writes: false,
    selected_branch: null,
    loop_index: null,
    parent_scope: null,
    dependencies: [],
    controls: [],
    repair_for: "root.build",
    repair_settings: {
      legacy: false,
      max_rounds: 1,
      accepted_output: "ready",
      accepted_value: "Yes",
      fix_instruction: "fix",
      verify_instruction: "verify",
      roles: {},
    },
  };
  await page.route(
    `**/api/runs/${fixture.run}?collection=nodes*`,
    async (route) => {
      const response = await route.fetch();
      const body: { run: { nodes: RunNode[] } } = await response.json();
      body.run.nodes.push(repair);
      await route.fulfill({ response, json: body });
    },
  );
  await page.route(`**/api/runs/${fixture.run}/artifacts?*`, async (route) => {
    const response = await route.fetch();
    const body: { artifacts: ArtifactRecord[] } = await response.json();
    body.artifacts = [
      {
        id: "one-byte",
        attempt_id: "fixture-attempt",
        name: "answer.txt",
        source_path: "answer.txt",
        scope_path: "root.build.verify",
        attempt_number: 1,
        bytes: 1,
        media_type: "text/plain",
        preservation_state: "preserved",
        sha256:
          "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
      },
    ];
    await route.fulfill({ response, json: body });
  });
  await page.goto(`/?view=runs&project=${fixture.project}&run=${fixture.run}`);
  await page.getByRole("button", { name: /^Repairs ·/ }).click();
  await expect(page.getByText(/^Up to 1 round ·/)).toBeVisible();
  await expect(page.locator('#run-artifacts [title="1 byte"]')).toHaveCount(1);
});
