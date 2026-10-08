import { rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { createStagingDirectory, publishBuild } from "./publish.mjs";

const staticRoot = fileURLToPath(new URL("../../relay/static/", import.meta.url));
const staging = await createStagingDirectory(staticRoot);
try {
  await build({ build: { outDir: staging, emptyOutDir: true } });
  await publishBuild(staging, staticRoot);
} finally {
  await rm(staging, { recursive: true, force: true });
}
