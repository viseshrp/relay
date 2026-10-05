import { defineConfig } from "@playwright/test";

import config from "./playwright.config";

export default defineConfig({
  ...config,
  testIgnore: [],
  testMatch: "optional-login.spec.ts",
  webServer: {
    command: "uv run python -m tests.e2e_server --port 4174 --no-login",
    cwd: "..",
    url: "http://127.0.0.1:4174/api/auth",
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
