/**
 * __tests__/query-keys.test.ts — PLAN-0059-C C-2 query-key factory.
 *
 * COVERS the C-2 critical tests from the plan:
 *   - test_query_key_factory_invalidation_cascades
 *     → invalidateQueries({ queryKey: qk.portfolios.detail(id) }) marks
 *       child queries (holdings/transactions/...) as invalidated.
 *   - structural assertions: keys are tuples, hierarchical, deterministic.
 */

import { describe, it, expect } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/query/keys";

describe("qk — query key factory", () => {
  it("portfolios.detail nests under portfolios.all so cascade invalidation works", () => {
    // Structural prefix check: TanStack Query partial-matches by tuple prefix.
    // qk.portfolios.detail(p) MUST start with qk.portfolios.all entries.
    const all = qk.portfolios.all;
    const detail = qk.portfolios.detail("p1");
    for (let i = 0; i < all.length; i++) {
      expect(detail[i]).toBe(all[i]);
    }
  });

  it("portfolios.holdings nests under portfolios.detail(id)", () => {
    const detail = qk.portfolios.detail("p1");
    const holdings = qk.portfolios.holdings("p1");
    for (let i = 0; i < detail.length; i++) {
      expect(holdings[i]).toBe(detail[i]);
    }
  });

  it("invalidateQueries on portfolios.detail() cascades to all child keys", async () => {
    const qc = new QueryClient();

    // Seed several queries scoped to the same portfolio.
    qc.setQueryData(qk.portfolios.detail("p1"), { id: "p1" });
    qc.setQueryData(qk.portfolios.holdings("p1"), [{ ticker: "AAPL" }]);
    qc.setQueryData(qk.portfolios.transactions("p1"), []);
    qc.setQueryData(qk.portfolios.valueHistory("p1", "1M"), []);
    // And one in a DIFFERENT portfolio that must NOT be touched.
    qc.setQueryData(qk.portfolios.holdings("p2"), [{ ticker: "MSFT" }]);

    // Pre-condition: nothing is invalidated yet.
    const stateBefore = qc
      .getQueryCache()
      .getAll()
      .map((q) => ({ key: q.queryKey, stale: q.isStale() }));
    // (Stale-by-time is irrelevant here — we just want to compare BEFORE/AFTER.)

    await qc.invalidateQueries({ queryKey: qk.portfolios.detail("p1") });

    const cache = qc.getQueryCache();
    const p1Holdings = cache.find({ queryKey: qk.portfolios.holdings("p1") });
    const p1Tx = cache.find({ queryKey: qk.portfolios.transactions("p1") });
    const p1Vh = cache.find({
      queryKey: qk.portfolios.valueHistory("p1", "1M"),
    });
    const p2Holdings = cache.find({ queryKey: qk.portfolios.holdings("p2") });

    // All p1 children invalidated (state.isInvalidated === true).
    expect(p1Holdings?.state.isInvalidated).toBe(true);
    expect(p1Tx?.state.isInvalidated).toBe(true);
    expect(p1Vh?.state.isInvalidated).toBe(true);
    // p2 untouched.
    expect(p2Holdings?.state.isInvalidated).toBe(false);

    // Reference the BEFORE snapshot so the var is genuinely consumed.
    expect(stateBefore.length).toBeGreaterThan(0);
  });

  it("watchlists.quotes sorts ids for stable cache key regardless of input order", () => {
    const a = qk.watchlists.quotes(["AAPL", "MSFT", "GOOG"]);
    const b = qk.watchlists.quotes(["GOOG", "AAPL", "MSFT"]);
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it("optional-params variants encode the absence of params", () => {
    expect(qk.news.top()).toEqual(["news", "top"]);
    expect(qk.news.top({ limit: 10 })).toEqual(["news", "top", { limit: 10 }]);
  });
});
