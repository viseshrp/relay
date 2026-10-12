import { defineConfig } from "@playwright/test";

const port = process.env.PLAYWRIGHT_PORT ?? "4174";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["optional-login.spec.ts", "visual-regression.spec.ts"],
  snapshotPathTemplate: "{testDir}/baselines/{platform}/{arg}{ext}",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    browserName: "chromium",
    timezoneId: "America/New_York",
    // Existing behavior specs start after onboarding; its own specs use fresh storage.
    storageState: {
      cookies: [],
      origins: [
        {
          origin: `http://127.0.0.1:${port}`,
          localStorage: [
            { name: "relay.welcome-seen", value: "true" },
            { name: "relay.tour-seen", value: "true" },
          ],
        },
      ],
    },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `uv run python -m tests.e2e_server --port ${port}`,
    cwd: "..",
    url: `http://127.0.0.1:${port}/api/auth`,
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
