import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig(base, {
  testDir: "./captures",
  testIgnore: [],
  use: {
    baseURL: "http://127.0.0.1:4175",
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 2,
    reducedMotion: "reduce",
    storageState: {
      cookies: [],
      origins: [
        {
          origin: "http://127.0.0.1:4175",
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
    ...base.webServer,
    command: "uv run python -m tests.e2e_server --port 4175",
    cwd: "..",
    url: "http://127.0.0.1:4175/api/auth",
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
