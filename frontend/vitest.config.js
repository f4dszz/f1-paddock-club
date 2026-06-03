// Vitest config for frontend unit tests (test-coverage-8, deps-config-6).
// Domain pure functions (domain/*.js) and hooks are unit-tested here; the
// Playwright suite (e2e/) remains the integration/E2E layer and is excluded.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    include: ["**/*.test.{js,jsx}", "**/__tests__/**/*.{js,jsx}"],
    exclude: ["node_modules/**", "dist/**", "e2e/**", "test-results/**"],
    coverage: {
      provider: "v8",
      reportsDirectory: "coverage",
      include: ["domain/**/*.js", "hooks/**/*.js"],
      reporter: ["text", "lcov"],
    },
  },
});
