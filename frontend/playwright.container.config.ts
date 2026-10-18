import { defineConfig } from "@playwright/test";

import config from "./playwright.config";

// `scripts/docker.sh e2e` starts the container and passes its published port.
// There is no default, so these flows never reach an owner's running Relay.
const baseURL = process.env.RELAY_CONTAINER_URL;
if (!baseURL)
  throw new Error("Run the container flows with `make docker-e2e`.");

export default defineConfig({
  ...config,
  testIgnore: [],
  testMatch: "container.spec.ts",
  // Container start, Git, and process shutdown are slower than the local server.
  timeout: 120_000,
  use: {
    ...config.use,
    baseURL,
    storageState: {
      cookies: [],
      origins: [
        {
          origin: baseURL,
          localStorage: [
            { name: "relay.welcome-seen", value: "true" },
            { name: "relay.tour-seen", value: "true" },
          ],
        },
      ],
    },
  },
  webServer: undefined,
});
