import { copyFile, mkdir, mkdtemp, readdir, rename, rm, stat } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { dirname, join } from "node:path";

/** Keep source-map paths at the same depth as the served build. */
export async function createStagingDirectory(target) {
  return mkdtemp(join(dirname(target), ".frontend-build-"));
}

/** Copy into the destination directory before replacing a served file. */
async function replaceFile(source, target) {
  const temporary = `${target}.${randomUUID()}.tmp`;
  try {
    await copyFile(source, temporary);
    await rename(temporary, target);
  } finally {
    await rm(temporary, { force: true });
  }
}

/** Publish assets first and the entry page last, retaining earlier hashed chunks. */
export async function publishBuild(source, target) {
  if (!(await stat(join(source, "index.html"))).isFile()) {
    throw new Error("The frontend build must contain an entry page.");
  }
  await mkdir(target, { recursive: true });
  async function copyDirectory(directory, destination) {
    await mkdir(destination, { recursive: true });
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (directory === source && entry.name === "index.html") continue;
      const from = join(directory, entry.name);
      const to = join(destination, entry.name);
      if (entry.isDirectory()) await copyDirectory(from, to);
      else if (entry.isFile()) await replaceFile(from, to);
      else throw new Error("Frontend build entries must be regular files or directories.");
    }
  }
  await copyDirectory(source, target);
  await replaceFile(join(source, "index.html"), join(target, "index.html"));
}
