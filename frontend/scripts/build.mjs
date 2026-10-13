import { rm } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { compressBuild } from "./compress.mjs";
import { createStagingDirectory, publishBuild } from "./publish.mjs";

const staticRoot = process.env.RELAY_BUILD_ASSETS_ROOT
  ? resolve(process.env.RELAY_BUILD_ASSETS_ROOT)
  : fileURLToPath(new URL("../../relay/static/", import.meta.url));
const staging = await createStagingDirectory(staticRoot);
try {
  await build({
    mode: "development",
    build: { outDir: staging, emptyOutDir: true },
  });
  await compressBuild(staging);
  await publishBuild(staging, staticRoot);
} finally {
  await rm(staging, { recursive: true, force: true });
}
