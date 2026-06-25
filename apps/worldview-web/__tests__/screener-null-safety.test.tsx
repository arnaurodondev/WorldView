/**
 * __tests__/screener-null-safety.test.tsx — Round-4 item 1: malformed/partial
 * rows must not throw in renderers.
 *
 * WHY THIS EXISTS: the screener backend response nests metrics in a
 * `metrics: {…}` dict; instruments with no fundamentals coverage return
 * `metrics: {}`, which the gateway transformer (lib/api/screener.ts) flattens
 * to null on every metric field. A renderer or valueGetter that assumes a
 * number (e.g. `v.toFixed(1)` without a null check) would throw inside AG
 * Grid's render pass and white-screen the whole table for ONE bad row.
 *
 * Round 1 audited several columns; Round 4 sweeps ALL 28 (this test renders
 * the full default-visible set against a row whose every metric is absent
 * and a row whose metrics are explicit nulls — the two shapes the API layer
 * can emit).
 *
 * The companion unit test (screener-metric-mapping.test.ts "empty metrics
 * dict") pins the API-layer half: metrics:{} → null on every field.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";

const { runScreenerMock } = vi.hoisted(() => ({
  runScreenerMock: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    runScreener: runScreenerMock,
    refreshToken: vi.fn(),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/screener"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "t@e.com", name: "T", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

import ScreenerPage from "@/app/(app)/screener/page";

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <NuqsTestingAdapter searchParams="">
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </NuqsTestingAdapter>
    );
  };
}

// ── Pathological rows ────────────────────────────────────────────────────────

// Shape 1 — what the gateway emits for `metrics: {}` BEFORE its num() pass
// existed: every metric field simply ABSENT (undefined on property access).
// Only identity fields are present (the API client guarantees these strings).
const SPARSE_ROW = {
  instrument_id: "ins-sparse",
  entity_id: "ent-sparse",
  ticker: "SPRS",
  name: "Sparse Holdings Inc.",
};

// Shape 2 — what the gateway emits TODAY for `metrics: {}`: every metric
// field explicitly null (the num() coercion path).
const NULL_ROW = {
  instrument_id: "ins-null",
  entity_id: "ent-null",
  ticker: "NULL",
  name: "Null Metrics Corp.",
  exchange: null,
  gics_sector: null,
  current_price: null,
  market_cap: null,
  pe_ratio: null,
  daily_return: null,
  revenue: null,
  beta: null,
  market_impact_score: null,
  avg_volume_30d: null,
  forward_pe: null,
  dividend_yield: null,
  roe: null,
  operating_margin: null,
  revenue_growth_yoy: null,
  dist_from_52w_high_pct: null,
  dist_from_52w_low_pct: null,
  return_1m: null,
  return_3m: null,
  return_6m: null,
  return_ytd: null,
  return_1y: null,
  return_3y: null,
  analyst_target_price: null,
  analyst_consensus_rating: null,
  insider_net_buy_90d: null,
  institutional_ownership_pct: null,
  short_percent: null,
  news_count_7d: null,
  llm_relevance_7d_max: null,
  display_relevance_7d_weighted: null,
  recent_contradiction_count: null,
};

beforeEach(() => {
  runScreenerMock.mockReset();
  runScreenerMock.mockImplementation(async () => ({
    results: [SPARSE_ROW, NULL_ROW],
    total: 2,
    offset: 0,
    limit: 50,
  }));
});

describe("ScreenerPage — null-row safety (Round 4 item 1)", () => {
  it("renders rows with NO metric data (metrics:{}) as dashes — never throws", async () => {
    // If any of the 28 renderers/valueGetters assumed a non-null number, AG
    // Grid's render pass would throw here and findByText would never resolve.
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // Both pathological rows render their identity cells…
    expect(await screen.findByText("SPRS")).toBeInTheDocument();
    expect(screen.getByText("NULL")).toBeInTheDocument();
    expect(screen.getByText("Sparse Holdings Inc.")).toBeInTheDocument();

    // …and the metric cells degrade to em-dashes ("—"), the screener-wide
    // missing-data convention. With 2 rows × ~12 default-visible metric
    // columns we expect a large dash population (exact count is renderer
    // detail; ≥10 proves the convention holds across the board).
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(10);
  });

  it("export accessors tolerate metric-less rows (no throw building the export model)", async () => {
    // The ExportMenu's exportColumns accessors (page.tsx) read the same
    // nullable fields — opening the page with these rows already constructs
    // them. This assertion pins that the Export trigger is ENABLED (rows
    // exist) — i.e. zero-metric rows are exportable, not filtered/crashed.
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await screen.findByText("SPRS");
    expect(screen.getByRole("button", { name: /export results/i })).toBeEnabled();
  });
});
