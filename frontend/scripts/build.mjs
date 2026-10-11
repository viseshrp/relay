import { rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { compressBuild } from "./compress.mjs";
import { createStagingDirectory, publishBuild } from "./publish.mjs";

const staticRoot = fileURLToPath(
  new URL("../../relay/static/", import.meta.url),
);
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
