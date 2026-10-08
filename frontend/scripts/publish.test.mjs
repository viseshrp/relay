import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { publishBuild } from "./publish.mjs";

test("publishing retains chunks for open tabs and replaces the entry page", async () => {
  const root = await mkdtemp(join(tmpdir(), "relay-publish-test-"));
  try {
    const old = join(root, "served"), next = join(root, "staging");
    for (const directory of [old, next]) await mkdir(join(directory, "assets"), { recursive: true });
    await writeFile(join(old, "index.html"), "old entry");
    await writeFile(join(old, "assets/old-lazy.js"), "old lazy chunk");
    await writeFile(join(next, "assets/new-lazy.js"), "new lazy chunk");
    await writeFile(join(next, "index.html"), "new entry");
    await publishBuild(next, old);
    assert.equal(await readFile(join(old, "assets/old-lazy.js"), "utf8"), "old lazy chunk");
    assert.equal(await readFile(join(old, "assets/new-lazy.js"), "utf8"), "new lazy chunk");
    assert.equal(await readFile(join(old, "index.html"), "utf8"), "new entry");
    assert.deepEqual((await readdir(old)).sort(), ["assets", "index.html"]);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("an asset-copy failure preserves the previous entry page", async () => {
  const root = await mkdtemp(join(tmpdir(), "relay-publish-failure-"));
  try {
    const old = join(root, "served"), next = join(root, "staging");
    await mkdir(old);
    await mkdir(join(next, "assets"), { recursive: true });
    await writeFile(join(old, "index.html"), "old entry");
    await writeFile(join(old, "assets"), "blocked directory");
    await writeFile(join(next, "assets/new.js"), "new chunk");
    await writeFile(join(next, "index.html"), "new entry");
    await assert.rejects(publishBuild(next, old));
    assert.equal(await readFile(join(old, "index.html"), "utf8"), "old entry");
    assert.deepEqual((await readdir(old)).sort(), ["assets", "index.html"]);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("an open browser tab can load its earlier lazy chunk after publication", async () => {
  const { createServer } = await import("node:http");
  const { chromium } = await import("@playwright/test");
  const root = await mkdtemp(join(tmpdir(), "relay-publish-browser-"));
  const browser = await chromium.launch();
  const served = join(root, "served"), next = join(root, "staging");
  const server = createServer(async (request, response) => {
    try {
      const path = request.url === "/" ? "index.html" : request.url.slice(1);
      response.setHeader("Content-Type", path.endsWith(".js") ? "text/javascript" : "text/html");
      response.end(await readFile(join(served, path)));
    } catch { response.writeHead(404); response.end(); }
  });
  try {
    for (const directory of [served, next]) await mkdir(join(directory, "assets"), { recursive: true });
    await writeFile(join(served, "index.html"), '<button onclick="import(\'./assets/old.js\').then(m=>document.querySelector(\'output\').textContent=m.value)">Open workspace</button><output></output>');
    await writeFile(join(served, "assets/old.js"), 'export const value = "Earlier workspace loaded";');
    await writeFile(join(next, "assets/new.js"), 'export const value = "New workspace";');
    await writeFile(join(next, "index.html"), "New entry");
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("The test server has no address.");
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${address.port}/`);
    await publishBuild(next, served);
    await page.getByRole("button", { name: "Open workspace" }).click();
    await page.getByText("Earlier workspace loaded", { exact: true }).waitFor();
    assert.equal(await page.locator("output").textContent(), "Earlier workspace loaded");
    assert.equal(await readFile(join(served, "index.html"), "utf8"), "New entry");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
    await rm(root, { recursive: true, force: true });
  }
});
