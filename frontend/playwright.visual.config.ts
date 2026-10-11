import base from "./playwright.config";
import { defineConfig } from "@playwright/test";

export default defineConfig({
  ...base,
  testIgnore: [],
  testMatch: "visual-regression.spec.ts",
  snapshotPathTemplate: "{testDir}/baselines/{platform}/{arg}{ext}",
  use: {
    ...base.use,
    baseURL: "http://127.0.0.1:4176",
    storageState: {
      cookies: [],
      origins: [
        {
          origin: "http://127.0.0.1:4176",
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
    command: "uv run python -m tests.e2e_server --port 4176",
    url: "http://127.0.0.1:4176/api/auth",
  },
});
