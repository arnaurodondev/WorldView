/**
 * vitest.config.ts — Vitest unit test configuration
 *
 * WHY THIS EXISTS: Configures Vitest for React component + hook + utility testing.
 * Uses jsdom environment to simulate browser APIs (DOM, fetch, etc.) in Node.
 * Uses @vitejs/plugin-react for JSX compilation (same plugin as the Vite devtool).
 *
 * IMPORTANT: This is separate from Playwright (e2e tests).
 * Vitest = unit + integration tests. Playwright = full browser e2e tests.
 */

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [
    // @vitejs/plugin-react: compiles JSX/TSX, enables React Fast Refresh in watch mode
    react(),
  ],
  test: {
    // jsdom: simulates a browser DOM environment in Node.js
    // WHY jsdom (not 'node'): React Testing Library requires DOM APIs (document, window)
    environment: "jsdom",

    // globals: true allows using describe/it/expect without importing them
    globals: true,

    // setupFiles: runs before each test file (imports jest-dom matchers)
    setupFiles: ["./vitest.setup.ts"],

    // Include both co-located tests and the top-level __tests__ directory
    include: ["**/__tests__/**/*.test.{ts,tsx}", "**/*.test.{ts,tsx}"],

    // Exclude playwright e2e tests and node_modules
    exclude: ["node_modules", "e2e/**", ".next/**"],

    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      include: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "hooks/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
      exclude: ["**/__tests__/**", "app/globals.css"],
    },
  },
  resolve: {
    // Map @/ to project root — matches tsconfig paths
    alias: {
      "@": path.resolve(__dirname, "."),
      // PLAN-0052 Wave B QA iter-1: lib/docs.ts uses `import "server-only"`
      // to fail builds on accidental client imports (the package only
      // exports a build-time error in client bundles). Vitest doesn't
      // know it's a real module, so alias it to an empty stub for tests.
      "server-only": path.resolve(__dirname, "vitest.server-only-stub.ts"),
    },
  },
});
