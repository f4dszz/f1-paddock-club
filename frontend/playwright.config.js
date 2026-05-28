import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // refine.spec.js requires LLM_STUB_MODE=1 (the no-key supervisor returns
  // early without it). quote_incomplete.spec.js needs the same stub gate
  // because the unpriced ticket option only exists under APP_ENV=test +
  // LLM_STUB_MODE=1. Default-ignore both; opt in with E2E_INCLUDE_REFINE=1
  // locally and in CI. saved_trips.spec.js needs the same stub gate to
  // get a deterministic plan first, then exercises the save/load WS path
  // against the SQLite-backed persistence layer. Opt in with
  // E2E_INCLUDE_SAVED=1.
  testIgnore: (() => {
    const ignored = [];
    if (process.env.E2E_INCLUDE_REFINE !== "1") {
      ignored.push("**/refine.spec.js", "**/quote_incomplete.spec.js");
    }
    if (process.env.E2E_INCLUDE_SAVED !== "1") {
      ignored.push("**/saved_trips.spec.js");
    }
    return ignored;
  })(),
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
