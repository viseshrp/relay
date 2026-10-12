import { defineConfig } from "@playwright/test";

import config from "./playwright.config";

const port = process.env.PLAYWRIGHT_PORT ?? "4174";

export default defineConfig({
  ...config,
  testIgnore: [],
  testMatch: "optional-login.spec.ts",
  webServer: {
    command: `uv run python -m tests.e2e_server --port ${port} --no-login`,
    cwd: "..",
    url: `http://127.0.0.1:${port}/api/auth`,
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
