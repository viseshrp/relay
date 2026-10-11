import {
  copyFile,
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  writeFile,
  rename,
  rm,
  stat,
} from "node:fs/promises";
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
  const record = join(target, ".relay-builds.json");
  const validAsset = (value) =>
    typeof value === "string" &&
    value.startsWith("assets/") &&
    !value.split("/").some((part) => !part || part === "." || part === "..") &&
    !value.includes("\\");
  async function assetFiles(root, prefix = "assets") {
    try {
      const files = [];
      for (const entry of await readdir(join(root, prefix), {
        withFileTypes: true,
      })) {
        const name = `${prefix}/${entry.name}`;
        if (entry.isDirectory()) files.push(...(await assetFiles(root, name)));
        else if (entry.isFile() && validAsset(name)) files.push(name);
      }
      return files;
    } catch (error) {
      if (error.code === "ENOENT") return [];
      throw error;
    }
  }
  let previous;
  try {
    previous = JSON.parse(await readFile(record, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    previous = [await assetFiles(target)];
  }
  if (
    !Array.isArray(previous) ||
    previous.some(
      (files) =>
        !Array.isArray(files) || files.some((file) => !validAsset(file)),
    )
  )
    throw new Error("Invalid frontend build retention record.");
  const generations = [await assetFiles(source), ...previous].slice(0, 3);
  if (!(await stat(join(source, "index.html"))).isFile()) {
    throw new Error("The frontend build must contain an entry page.");
  }
  await mkdir(target, { recursive: true });
  async function copyDirectory(directory, destination) {
    await mkdir(destination, { recursive: true });
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (
        directory === source &&
        (entry.name.startsWith("index.html") || entry.name === ".vite")
      )
        continue;
      const from = join(directory, entry.name);
      const to = join(destination, entry.name);
      if (entry.isDirectory()) await copyDirectory(from, to);
      else if (entry.isFile()) await replaceFile(from, to);
      else
        throw new Error(
          "Frontend build entries must be regular files or directories.",
        );
    }
  }
  await copyDirectory(source, target);
  for (const extension of [".br", ".gz"]) {
    const from = join(source, `index.html${extension}`);
    try {
      await replaceFile(from, join(target, `index.html${extension}`));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      await rm(join(target, `index.html${extension}`), { force: true });
    }
  }
  await replaceFile(join(source, "index.html"), join(target, "index.html"));
  const stagedRecord = `${record}.${randomUUID()}.tmp`;
  try {
    await writeFile(stagedRecord, JSON.stringify(generations));
    await rename(stagedRecord, record);
  } finally {
    await rm(stagedRecord, { force: true });
  }
  const retained = new Set(generations.flat());
  for (const file of await assetFiles(target))
    if (!retained.has(file)) await rm(join(target, file));
}
