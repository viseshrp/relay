import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4174",
    browserName: "chromium",
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
