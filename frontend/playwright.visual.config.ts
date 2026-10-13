import base from "./playwright.config";
import { defineConfig } from "@playwright/test";

const port = process.env.PLAYWRIGHT_VISUAL_PORT ?? "4176";

export default defineConfig({
  ...base,
  testIgnore: [],
  testMatch: "visual-regression.spec.ts",
  snapshotPathTemplate: "{testDir}/baselines/{platform}/{arg}{ext}",
  use: {
    ...base.use,
    baseURL: `http://127.0.0.1:${port}`,
    storageState: {
      cookies: [],
      origins: [
        {
          origin: `http://127.0.0.1:${port}`,
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
    command: `uv run python -m tests.e2e_server --port ${port}`,
    url: `http://127.0.0.1:${port}/api/auth`,
  },
});
