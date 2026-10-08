import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { publishBuild } from "./publish.mjs";

const staging = await mkdtemp(join(tmpdir(), "relay-frontend-build-"));
try {
  await build({ build: { outDir: staging, emptyOutDir: true } });
  await publishBuild(staging, fileURLToPath(new URL("../../relay/static/", import.meta.url)));
} finally {
  await rm(staging, { recursive: true, force: true });
}
