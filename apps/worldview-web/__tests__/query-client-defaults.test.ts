/**
 * __tests__/query-client-defaults.test.ts — QueryClient cache-policy pin
 * (Round-4 hardening, DESIGN_SYSTEM.md §9).
 *
 * WHY THIS EXISTS: app/providers.tsx defines the platform-wide TanStack Query
 * defaults. They encode deliberate finance-terminal decisions:
 *
 *   - queries.staleTime 30s — no refetch storm on every mount; per-query
 *     overrides (quotes 5s) handle hot data.
 *   - queries.retry 1 — surface failures fast (the TanStack default of 3
 *     exponential retries hides an outage for 3+ seconds).
 *   - queries.refetchOnWindowFocus true — prices refresh on tab return.
 *   - mutations.retry 0 — NEVER auto-retry writes; a retried mutation that
 *     partially succeeded can duplicate orders/alerts/watchlist entries.
 *
 * WHY a source-contract test (regex on providers.tsx, not importing it):
 * importing app/providers.tsx drags the full provider tree (Sentry SDK, Auth,
 * WebSocket contexts) into a unit test. Grepping the source is the repo's
 * established pattern for config pins (see toast-config.test.ts, which
 * documents the same trade-off).
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import * as path from "path";

const PROVIDERS = readFileSync(
  path.resolve(__dirname, "..", "app", "providers.tsx"),
  "utf8",
);

describe("QueryClient platform defaults (app/providers.tsx)", () => {
  it("pins queries.staleTime to 30s", () => {
    // \s* tolerates formatting churn; the VALUE is the contract.
    expect(PROVIDERS).toMatch(/staleTime:\s*30\s*\*\s*1000/);
  });

  it("pins queries.retry to exactly 1 (fail fast, no 3-retry default)", () => {
    expect(PROVIDERS).toMatch(/retry:\s*1/);
    // Guard against someone "fixing" retry to a function or true (unlimited
    // semantics for `true` = 3 retries default; functions hide the policy).
    expect(PROVIDERS).not.toMatch(/retry:\s*true/);
    expect(PROVIDERS).not.toMatch(/retry:\s*3/);
  });

  it("pins mutations.retry to 0 (writes are never auto-retried)", () => {
    // Anchored on the mutations block so a queries-side `retry: 0` can't
    // satisfy it by accident. [\s\S] instead of the dotAll flag because the
    // tsconfig target predates es2018 regex flags.
    expect(PROVIDERS).toMatch(/mutations:\s*\{[\s\S]*?retry:\s*0/);
  });

  it("keeps refetchOnWindowFocus enabled for finance-data freshness", () => {
    expect(PROVIDERS).toMatch(/refetchOnWindowFocus:\s*true/);
  });
});
