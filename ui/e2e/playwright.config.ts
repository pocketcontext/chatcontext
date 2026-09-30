import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  workers: 1,
  timeout: 60000,
  expect: { timeout: 10000 },
  reporter: "list",
  outputDir: process.env.READER_TEST_OUTPUT,
  use: {
    baseURL: process.env.READER_TEST_URL,
    browserName: "chromium",
    headless: true,
  },
});
