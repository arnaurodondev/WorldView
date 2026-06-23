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
  testMatch: "**/*.spec.ts",
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
    // ── MOCKED projects (default, fast, per-PR) ─────────────────────────────
    // These run the existing mock-driven specs. They install a catch-all S9 stub
    // (shell-helpers.ts) and never touch the live backend, so they are
    // deterministic and safe to run in parallel on every PR.
    //
    // WHY testIgnore /live\//: the live specs (e2e/live/*.spec.ts) MUST NOT run
    // under the mocked projects — they expect a real backend + the live-auth
    // seam. The dedicated `live` project below is the only place they run.
    {
      name: "chromium",
      testIgnore: /live\//,
      use: { ...devices["Desktop Chrome"] },
    },
    // WebKit for Safari 17+ support (NFR)
    {
      name: "webkit",
      testIgnore: /live\//,
      use: { ...devices["Desktop Safari"] },
    },

    // ── LIVE project (@live, serial, run against the dev stack) ─────────────
    // WHY a SEPARATE project (2026-06-22 E2E-gaps audit, recommendation §5.3):
    // the live specs hit the REAL S9 gateway with a real JWT (live-helpers.ts),
    // so they verify real response shapes + data integration — but they are
    // slower and depend on a running stack. Run them with `--project=live`
    // nightly / pre-release, NOT on every PR.
    //
    // WHY fullyParallel:false + workers:1: the gateway aggressively 429s under
    // rapid fan-out navigation (audit BUG-3). A single serial worker keeps
    // request bursts below the limiter; live-helpers.gotoLive() adds 429 retry
    // on top. retries:1 absorbs the occasional transient rate-limit flake.
    {
      name: "live",
      testMatch: /live\/.*\.spec\.ts$/,
      fullyParallel: false,
      workers: 1,
      retries: 1,
      use: {
        ...devices["Desktop Chrome"],
        // WHY an overridable baseURL for the live project only: the live specs
        // must run against a frontend serving THIS branch's code, talking to the
        // live S9 stack. Locally that is a `next dev` you start yourself (the
        // default :3001 may be occupied by a stale container). Point the run at
        // it via E2E_BASE_URL, e.g.:
        //   E2E_BASE_URL=http://localhost:3002 \
        //     pnpm exec playwright test --project=live
        baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3001",
      },
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
