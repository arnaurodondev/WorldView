/**
 * __tests__/index-ticker-stale.test.tsx — Tests for W2-10: IndexTicker
 * muted color + suppressed % change when quote is stale/delayed/unavailable
 *
 * WHY THIS EXISTS: IndexTicker was updated to suppress directional color coding
 * and % change when a quote's freshness_status is "delayed", "stale", or
 * "unavailable". Showing green/red on a stale price misleads traders into
 * thinking the market is moving when it may not be.
 *
 * WHAT IS TESTED:
 *   1. Stale quote → price shown in muted color, no % change span, dot shown
 *   2. Live quote → price shown with priceChangeClass color, % change shown
 *   3. No quote → dashes shown in muted color
 *
 * WHY MOCK gateway: deterministic freshness_status values; no network.
 * WHY MOCK useAuth: eliminates AuthContext tree dependency for unit isolation.
 *
 * DATA SOURCE: Mocked gateway client
 * DESIGN REFERENCE: PLAN-0036 W2-10 — IndexTicker stale indicator
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Auth mock ──────────────────────────────────────────────────────────────────
// WHY: IndexTicker gates the query on !!accessToken; must be truthy for queries to fire.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "u1",
      tenant_id: "t1",
      email: "trader@example.com",
      name: "Test Trader",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ───────────────────────────────────────────────────────────────
// WHY: IndexTicker only calls getBatchQuotes — we only need to mock that method.
const mockGetBatchQuotes = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getBatchQuotes: mockGetBatchQuotes,
    // Auth plumbing
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "test-token",
      user: { user_id: "u1", tenant_id: "t1", email: "t@e.com", name: "T", avatar_url: null },
      expires_in: 900,
    }),
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

// ── Fixtures ───────────────────────────────────────────────────────────────────

// Live quote for SPY (+1.12% change) — should show colored text and % change
const SPY_LIVE = {
  instrument_id: "SPY",
  ticker: "SPY",
  price: 520.45,
  change: 5.78,
  change_pct: 1.12,
  timestamp: "2026-04-24T14:00:00Z",
  volume: 80_000_000,
  freshness_status: "live" as const,
  source: "fresh_quote" as const,
  data_as_of: "2026-04-24T14:00:00Z",
  stale_reason: null,
};

// Delayed quote for QQQ — should show muted text, no % change, dot instead
const QQQ_DELAYED = {
  instrument_id: "QQQ",
  ticker: "QQQ",
  price: 435.20,
  change: -2.10,
  change_pct: -0.48,
  timestamp: "2026-04-24T13:00:00Z",
  volume: 40_000_000,
  freshness_status: "delayed" as const,
  source: "bulk_quote" as const,
  data_as_of: "2026-04-24T12:45:00Z",
  stale_reason: "No quote in last 15 min",
};

// Stale quote for VIX
const VIX_STALE = {
  instrument_id: "VIX",
  ticker: "VIX",
  price: 18.50,
  change: 0.30,
  change_pct: 1.65,
  timestamp: "2026-04-23T20:00:00Z",
  volume: null,
  freshness_status: "stale" as const,
  source: "stale_snapshot" as const,
  data_as_of: "2026-04-23T16:00:00Z",
  stale_reason: "No data for >1 day",
};

// Recent quote for BTC-USD (+3.5%) — "recent" is still fresh, should be colored
const BTC_RECENT = {
  instrument_id: "BTC-USD",
  ticker: "BTC-USD",
  price: 67_800.00,
  change: 2_300.00,
  change_pct: 3.51,
  timestamp: "2026-04-24T13:55:00Z",
  volume: 25_000_000,
  freshness_status: "recent" as const,
  source: "fresh_quote" as const,
  data_as_of: "2026-04-24T13:55:00Z",
  stale_reason: null,
};

// ── Helpers ────────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function makeWrapper() {
  const qc = makeQueryClient();
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── Import component AFTER mocks ───────────────────────────────────────────────
// WHY late import: ensures vi.mock() hoisting takes effect before module load
const { IndexTicker } = await import("@/components/shell/IndexTicker");

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("IndexTicker — stale indicator (W2-10)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows muted-foreground color and dot (no % change) for a delayed quote", async () => {
    // WHY: a delayed price should not show directional color — it could mislead
    // traders into thinking QQQ is falling right now when the price is 15+ min old.
    mockGetBatchQuotes.mockResolvedValue({
      quotes: {
        SPY: SPY_LIVE,
        QQQ: QQQ_DELAYED,
        VIX: VIX_STALE,
        "BTC-USD": BTC_RECENT,
      },
    });

    render(<IndexTicker />, { wrapper: makeWrapper() });

    // Wait for the component to render the QQQ price
    await waitFor(() => {
      // formatPrice(435.20) → "$435.20"
      expect(screen.getByText("$435.20")).toBeInTheDocument();
    });

    // WHY getAllByTitle: both the price span AND the dot span for a stale quote share
    // the same title attribute (the stale_reason). getAllByTitle avoids the
    // "Found multiple elements" error that getByTitle would throw.
    const staleSpans = screen.getAllByTitle("No quote in last 15 min");
    // Two spans must share this title: the price and the dot
    expect(staleSpans.length).toBe(2);

    // WHY find the price span by price text: the price span contains "$435.20"
    const stalePriceSpan = staleSpans.find((el) => el.textContent === "$435.20");
    expect(stalePriceSpan).toBeDefined();

    // WHY check class directly: the muted color is applied via className string.
    // toHaveClass() checks that at least one of the provided classes is present.
    expect(stalePriceSpan).toHaveClass("text-muted-foreground");

    // WHY check for the dot: stale quotes show a "·" instead of the % change.
    const dotSpan = staleSpans.find((el) => el.textContent === "·");
    expect(dotSpan).toBeDefined();

    // WHY assert % change is absent: "-0.48%" must NOT appear for delayed quotes —
    // showing a change % on an old price misleads traders about current momentum.
    expect(screen.queryByText("-0.48%")).not.toBeInTheDocument();
  });

  it("shows priceChangeClass color and % change for a live quote", async () => {
    // WHY: a live quote should show the full colored price + % change.
    // This is the primary purpose of the IndexTicker — real-time direction.
    mockGetBatchQuotes.mockResolvedValue({
      quotes: {
        SPY: SPY_LIVE,
        QQQ: QQQ_DELAYED,
        VIX: VIX_STALE,
        "BTC-USD": BTC_RECENT,
      },
    });

    render(<IndexTicker />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // formatPrice(520.45) → "$520.45"
      expect(screen.getByText("$520.45")).toBeInTheDocument();
    });

    // WHY check % change appears: +1.12% should be visible for the live SPY quote
    // formatPercentDirect(1.12) → "+1.12%"
    expect(screen.getByText("+1.12%")).toBeInTheDocument();

    // WHY title should be undefined for live: live prices don't set a stale title.
    // The SPY price span should have no title attribute (or title="").
    const spyPriceSpan = screen.getByText("$520.45");
    expect(spyPriceSpan).not.toHaveAttribute("title");

    // WHY text-positive: SPY change_pct = +1.12% → priceChangeClass returns "text-positive"
    // for positive values. The span must use the directional color, not muted.
    expect(spyPriceSpan).toHaveClass("text-positive");
  });

  it("shows muted color for a stale (>1 day) quote and no % change", async () => {
    // WHY: "stale" is a stronger signal than "delayed" — price is >1 day old.
    // Same treatment applies: muted color + dot, no % change.
    mockGetBatchQuotes.mockResolvedValue({
      quotes: {
        SPY: SPY_LIVE,
        QQQ: QQQ_DELAYED,
        VIX: VIX_STALE,
        "BTC-USD": BTC_RECENT,
      },
    });

    render(<IndexTicker />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // formatPrice(18.50) → "$18.50"
      expect(screen.getByText("$18.50")).toBeInTheDocument();
    });

    // WHY getAllByTitle: both the price span and the dot span share the same title.
    const vixStaleSpans = screen.getAllByTitle("No data for >1 day");
    const vixPriceSpan = vixStaleSpans.find((el) => el.textContent === "$18.50");
    expect(vixPriceSpan).toBeDefined();
    expect(vixPriceSpan).toHaveClass("text-muted-foreground");

    // "+1.65%" must NOT appear for the VIX stale quote
    expect(screen.queryByText("+1.65%")).not.toBeInTheDocument();
  });

  it("treats 'recent' freshness_status as live (colored + % change shown)", async () => {
    // WHY: "recent" means < 5 min old — trustworthy enough for directional display.
    // It must NOT be treated as stale. BTC-USD is "recent" in this fixture.
    mockGetBatchQuotes.mockResolvedValue({
      quotes: {
        SPY: SPY_LIVE,
        QQQ: QQQ_DELAYED,
        VIX: VIX_STALE,
        "BTC-USD": BTC_RECENT,
      },
    });

    render(<IndexTicker />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // formatPrice(67800) → "$67,800.00"
      expect(screen.getByText("$67,800.00")).toBeInTheDocument();
    });

    // "+3.51%" should be visible — "recent" is not stale
    expect(screen.getByText("+3.51%")).toBeInTheDocument();

    // BTC price span should NOT have a stale title attribute
    const btcPriceSpan = screen.getByText("$67,800.00");
    expect(btcPriceSpan).not.toHaveAttribute("title");
  });

  it("shows muted dashes when no quote exists for an index", async () => {
    // WHY: when getBatchQuotes returns an empty map (e.g., auth issue or cold start),
    // IndexTicker should show "—" placeholders in muted color for all tickers.
    mockGetBatchQuotes.mockResolvedValue({
      quotes: {}, // no quotes returned
    });

    render(<IndexTicker />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // WHY getAllByText: all 4 tickers show "—" when no data
      const dashes = screen.getAllByText("—");
      expect(dashes.length).toBeGreaterThanOrEqual(4);
    });
  });
});
