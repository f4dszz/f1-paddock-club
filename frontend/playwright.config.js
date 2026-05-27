import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // refine.spec.js requires LLM_STUB_MODE=1 (the no-key supervisor returns
  // early without it). quote_incomplete.spec.js needs the same stub gate
  // because the unpriced ticket option only exists under APP_ENV=test +
  // LLM_STUB_MODE=1. Default-ignore both; opt in with E2E_INCLUDE_REFINE=1
  // locally and in CI.
  testIgnore: process.env.E2E_INCLUDE_REFINE === "1"
    ? []
    : ["**/refine.spec.js", "**/quote_incomplete.spec.js"],
  timeout: 180000,
  expect: {
    timeout: 15000,
  },
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
