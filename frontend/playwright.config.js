import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // refine.spec.js requires a working LLM (the no-key supervisor returns
  // early). Default-ignore it; opt in with E2E_INCLUDE_REFINE=1 locally.
  testIgnore: process.env.E2E_INCLUDE_REFINE === "1" ? [] : ["**/refine.spec.js"],
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
