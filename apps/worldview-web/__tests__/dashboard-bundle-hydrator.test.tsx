/**
 * __tests__/dashboard-bundle-hydrator.test.tsx — Round 1 hydration contract
 *
 * WHY THIS EXISTS: DashboardBundleHydrator seeds per-widget TanStack caches
 * from the F-2 bundle. Round 1 fixed a silent shape mismatch: the bundle's
 * top_gainers/top_losers legs are the RAW S9 envelope ({results: [...]}) but
 * the widget caches must hold the TRANSFORMED {movers: Mover[]} shape that
 * getTopMovers() produces. These tests pin:
 *   1. the transform is applied before seeding, and
 *   2. BOTH key families are seeded — qk.dashboard.topMovers(...) (TopMovers,
 *      Round 1 MARKET tab) and the legacy ["dashboard-top-movers-<type>", "1D"]
 *      flat keys (PreMarketMoversWidget).
 *
 * WHY MOCK useDashboardBundle (not the gateway): the hydrator's contract is
 * "given a bundle, write the right cache entries" — the fetch itself is the
 * hook's responsibility and is covered by its own integration paths.
 */

import { describe, it, expect, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { qk } from "@/lib/query/keys";
import type { TopMoversResponse } from "@/types/api";

// ── Bundle hook mock ──────────────────────────────────────────────────────────
// RAW S9 envelope exactly as the bundle legs carry it (S3 period-movers rows:
// top-level period_return_pct, NO price, NO metrics).
const rawBundle = {
  brief: null,
  portfolios: null,
  top_gainers: {
    results: [
      { instrument_id: "ins-1", ticker: "NVDA", name: "NVIDIA Corp", period_return_pct: 5.2 },
      // Wrong-direction row — the transform's strict filter must drop it.
      { instrument_id: "ins-3", ticker: "GOOGL", name: "Alphabet Inc", period_return_pct: -0.54 },
    ],
    type: "gainers",
    period: "1D",
  },
  top_losers: {
    results: [
      { instrument_id: "ins-2", ticker: "TSLA", name: "Tesla Inc", period_return_pct: -3.1 },
    ],
    type: "losers",
    period: "1D",
  },
  sector_heatmap: null,
  recent_alerts: null,
  workspace: null,
};

vi.mock("@/features/dashboard/hooks/useDashboardBundle", () => ({
  useDashboardBundle: vi.fn(() => ({ data: rawBundle })),
}));

// ── Component import (after vi.mock) ─────────────────────────────────────────
import { DashboardBundleHydrator } from "@/components/dashboard/DashboardBundleHydrator";

describe("DashboardBundleHydrator — Round 1 top-movers hydration", () => {
  function renderWithClient() {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DashboardBundleHydrator />
      </QueryClientProvider>,
    );
    return qc;
  }

  it("seeds the qk.dashboard.topMovers keys with the TRANSFORMED {movers} shape", async () => {
    const qc = renderWithClient();

    await waitFor(() => {
      const gainers = qc.getQueryData<TopMoversResponse>(
        qk.dashboard.topMovers({ type: "gainers", limit: 10, period: "1D" }),
      );
      expect(gainers).toBeDefined();
    });

    const gainers = qc.getQueryData<TopMoversResponse>(
      qk.dashboard.topMovers({ type: "gainers", limit: 10, period: "1D" }),
    )!;
    // Transformed shape — NOT the raw {results} envelope.
    expect(gainers.type).toBe("gainers");
    // The wrong-direction GOOGL row (-0.54% in a gainers leg) is filtered out.
    expect(gainers.movers.map((m) => m.ticker)).toEqual(["NVDA"]);
    // period_return_pct mapped to change_pct without unit conversion.
    expect(gainers.movers[0].change_pct).toBe(5.2);

    const losers = qc.getQueryData<TopMoversResponse>(
      qk.dashboard.topMovers({ type: "losers", limit: 10, period: "1D" }),
    )!;
    expect(losers.movers.map((m) => m.ticker)).toEqual(["TSLA"]);
  });

  it("also seeds the legacy flat keys read by PreMarketMoversWidget", async () => {
    const qc = renderWithClient();

    await waitFor(() => {
      expect(
        qc.getQueryData<TopMoversResponse>(["dashboard-top-movers-gainers", "1D"]),
      ).toBeDefined();
    });

    const gainers = qc.getQueryData<TopMoversResponse>([
      "dashboard-top-movers-gainers",
      "1D",
    ])!;
    expect(gainers.movers[0].ticker).toBe("NVDA");

    const losers = qc.getQueryData<TopMoversResponse>([
      "dashboard-top-movers-losers",
      "1D",
    ])!;
    expect(losers.movers[0].ticker).toBe("TSLA");
  });
});
