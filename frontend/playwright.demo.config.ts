import { defineConfig } from "@playwright/test";

const port = process.env.RELAY_DEMO_PORT;
const output = process.env.RELAY_DEMO_OUTPUT;
if (!port || !output)
  throw new Error("Use npm run demo to isolate demo capture.");
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "readme.demo.ts",
  testIgnore: [],
  retries: 0,
  timeout: 90_000,
  outputDir: `${output}/results`,
  reporter: "list",
  workers: 1,
  use: {
    browserName: "chromium",
    timezoneId: "America/New_York",
    trace: "retain-on-failure",
    baseURL: origin,
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    reducedMotion: "reduce",
    locale: "en-US",
    storageState: {
      cookies: [],
      origins: [
        {
          origin,
          localStorage: [
            { name: "relay.welcome-seen", value: "true" },
            { name: "relay.tour-seen", value: "true" },
            { name: "relay.setup-dismissed", value: "true" },
          ],
        },
      ],
    },
  },
  webServer: {
    command: `uv run python -m tests.e2e_server --port ${port}`,
    cwd: "..",
    url: `${origin}/api/auth`,
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
