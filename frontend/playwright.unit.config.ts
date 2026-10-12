import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./unit",
  fullyParallel: false,
  workers: 1,
});
