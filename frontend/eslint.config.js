// ESLint flat config for the React 19 + Vite frontend (deps-config-6).
// Plain JS/JSX project (no TypeScript source); `npm run typecheck` uses tsc
// with checkJs via jsconfig.json for lightweight type safety.
import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default [
  {
    // Things ESLint should never lint.
    ignores: [
      "dist/**",
      "node_modules/**",
      "test-results/**",
      "playwright-report/**",
      "coverage/**",
      "prototype.jsx",
    ],
  },
  js.configs.recommended,
  react.configs.flat.recommended,
  react.configs.flat["jsx-runtime"], // React 19 automatic runtime: no React-in-scope rule
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
    settings: {
      react: { version: "detect" },
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Pragmatic relaxations for an existing plain-JS codebase; this gate is
      // meant to catch dead imports / undefined vars, not to churn style.
      "react/prop-types": "off",
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      // eslint-plugin-react-hooks@7 promoted two React-Compiler-era heuristics
      // into `recommended` as errors. They flag intentional, working idioms in
      // this codebase (mirroring a state value into a ref so a stable WS handler
      // can read the latest value; a one-shot setState in an effect that reports
      // a "not connected" message). Keep them as advisory warnings so the lint
      // gate still catches dead code / rules-of-hooks / exhaustive-deps without
      // churning correct components. (Tracked as a follow-up cleanup.)
      "react-hooks/refs": "warn",
      "react-hooks/set-state-in-effect": "warn",
    },
  },
  {
    // Test files: allow vitest/node globals.
    files: ["**/*.test.{js,jsx}", "**/__tests__/**/*.{js,jsx}", "vitest.config.js"],
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.vitest,
      },
    },
  },
  {
    // Build/config + e2e (Playwright) files run under Node.
    files: ["*.config.js", "e2e/**/*.{js,jsx}", "playwright.config.js"],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },
];
