import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: "optional-login.spec.ts",
  snapshotPathTemplate: "{testDir}/baselines/{arg}{ext}",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4174",
    browserName: "chromium",
    timezoneId: "America/New_York",
    // Existing behavior specs start after onboarding; its own specs use fresh storage.
    storageState: {
      cookies: [],
      origins: [
        {
          origin: "http://127.0.0.1:4174",
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
    command: "uv run python -m tests.e2e_server --port 4174",
    cwd: "..",
    url: "http://127.0.0.1:4174/api/auth",
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
