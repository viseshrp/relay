import { defineConfig } from "@playwright/test";

export default defineConfig({
  metadata: { relayCheckout: process.env.RELAY_TEST_CHECKOUT_SHA },
  testDir: "./unit",
  fullyParallel: false,
  workers: 1,
});
