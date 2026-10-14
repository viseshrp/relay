import { spawn } from "node:child_process";
import {
  copyFile,
  cp,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  readdir,
  rm,
  stat,
} from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("../", import.meta.url));
const destination = fileURLToPath(
  new URL("../../docs/images/demo.gif", import.meta.url),
);
const diagnostics = join(frontend, "test-results", "readme-demo");

async function run(command, args, options = {}) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: frontend,
      stdio: "inherit",
      shell: false,
      ...options,
    });
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} failed (${signal ?? code}).`));
    });
  });
}

async function availablePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const port = server.address().port;
  await new Promise((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
  return String(port);
}

// Fail before building if the only extra demo dependency is missing.
await run("ffmpeg", ["-version"], { stdio: "ignore" }).catch(() => {
  throw new Error("Install FFmpeg and put ffmpeg on PATH before npm run demo.");
});
const scratch = await mkdtemp(join(tmpdir(), "relay-readme-demo-"));
try {
  const env = {
    ...process.env,
    RELAY_DEMO_PORT: await availablePort(),
    RELAY_DEMO_OUTPUT: scratch,
    RELAY_BUILD_ASSETS_ROOT: join(scratch, "assets"),
    RELAY_TEST_ASSETS_ROOT: join(scratch, "assets"),
    // macOS aliases /var to /private/var. Keep fixture roots canonical so
    // artifact paths and their resolved selections share the same spelling.
    TMPDIR: await realpath(tmpdir()),
    TEMP: await realpath(tmpdir()),
    TMP: await realpath(tmpdir()),
  };
  await run(process.execPath, ["scripts/build.mjs"], { env });
  await run(
    process.execPath,
    [
      "node_modules/@playwright/test/cli.js",
      "test",
      "--config",
      "playwright.demo.config.ts",
    ],
    { env },
  );
  const candidate = join(scratch, "demo.gif");
  await run("ffmpeg", [
    "-hide_banner",
    "-loglevel",
    "warning",
    "-y",
    "-f",
    "concat",
    "-safe",
    "1",
    "-i",
    join(scratch, "frames.txt"),
    "-filter_complex",
    "split[a][b];[a]palettegen=stats_mode=diff[p];" +
      "[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
    "-fps_mode",
    "vfr",
    "-loop",
    "0",
    candidate,
  ]);
  const header = await readFile(candidate);
  const bytes = (await stat(candidate)).size;
  if (
    header.subarray(0, 6).toString() !== "GIF89a" ||
    header.readUInt16LE(6) !== 1280 ||
    header.readUInt16LE(8) !== 800 ||
    bytes > 5 * 1024 * 1024
  )
    throw new Error("Demo must be a 1280x800 GIF under 5 MiB.");
  // The checked-in image changes only after the complete scenario and encoding pass.
  await copyFile(candidate, destination);
  console.log(`Generated ${destination} (${(bytes / 1024).toFixed(0)} KiB).`);
} finally {
  await mkdir(diagnostics, { recursive: true });
  for (const name of await readdir(scratch)) {
    if (
      name === "results" ||
      name.startsWith("frame-") ||
      name === "frames.txt"
    )
      await cp(join(scratch, name), join(diagnostics, name), {
        recursive: true,
      });
  }
  console.log(`Capture frames and failure traces: ${diagnostics}`);
  await rm(scratch, { recursive: true, force: true });
}
