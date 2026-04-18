/**
 * playwright.config.ts — Playwright e2e test configuration
 *
 * WHY THIS EXISTS: E2E tests run against the full Next.js dev server and verify
 * user journeys (auth flow, dashboard load, instrument search, etc.).
 * Used only in T-1 wave. Per skill rules: pnpm test:e2e only runs for T-1.
 */

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // Run in parallel across multiple workers for speed
  fullyParallel: true,
  // Fail the build on CI if tests are accidentally left in focused/todo state
  forbidOnly: !!process.env.CI,
  // Retry once on CI (flaky network conditions in CI environments)
  retries: process.env.CI ? 1 : 0,
  // Default: single worker locally; max 4 on CI
  workers: process.env.CI ? 4 : 1,
  reporter: "html",
  use: {
    // Base URL — all tests use relative paths (e.g., await page.goto('/dashboard'))
    baseURL: "http://localhost:3001",
    // Capture trace on first retry to diagnose failures
    trace: "on-first-retry",
    // Disable video by default for speed; enable in CI if debugging is needed
    video: "off",
  },
  projects: [
    // Desktop Chromium — primary test target (target user: Bloomberg terminal users)
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    // WebKit for Safari 17+ support (NFR)
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
  ],
  // Start the Next.js dev server automatically before running tests
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:3001",
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
});
