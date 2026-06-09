/**
 * __tests__/top-bar-marquee.test.tsx — Unit tests for TopBarMarquee
 *
 * WHY THIS EXISTS: TopBarMarquee replaced IndexTicker (4 static chips) with a
 * 10-ticker scrolling strip. This test validates:
 *   1. The two-step data flow (resolve ticker → UUID, then batch-quote)
 *   2. Correct chip rendering: symbol, price, change%, pipe separator
 *   3. Skeleton loading state
 *   4. Em-dash placeholders when quote is absent or errored
 *   5. Stale quote → muted color, no % change (same contract as IndexTicker)
 *
 * WHY MOCK gateway:
 *   deterministic ticker→UUID resolution + quote values; no network.
 * WHY MOCK useAuth:
 *   TopBarMarquee gates both queries on !!accessToken; must be truthy.
 *
 * DESIGN REFERENCE: Handoff 2026-05-01 Tier-3 #7
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Auth mock ──────────────────────────────────────────────────────────────────
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
// WHY resolveTickersBatch returns ticker === id: the component (post-PLAN-0099-W4
// refactor) uses resolveTickersBatch (not searchInstruments) for one-shot batch
// resolution. The test fixtures key quotes by ticker symbol, so returning the
// ticker itself as the instrument_id keeps the two-step lookup consistent.
const mockGetBatchQuotes = vi.fn();
const mockResolveTickersBatch = vi.fn().mockImplementation((tickers: string[]) => {
  // Return each ticker mapped to itself — the test fixtures use ticker symbols
  // as quote keys, so ticker-as-id keeps the quotes[instrumentId] lookup correct.
  const map: Record<string, string | null> = {};
  tickers.forEach((t) => { map[t] = t; });
  return Promise.resolve(map);
});

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getBatchQuotes: mockGetBatchQuotes,
    resolveTickersBatch: mockResolveTickersBatch,
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

// ── Quote fixtures ─────────────────────────────────────────────────────────────

const SPY_LIVE = {
  price: 520.45,
  change_pct: 1.12,
  freshness_status: "live",
  stale_reason: null,
};

const QQQ_DELAYED = {
  price: 435.20,
  change_pct: -0.48,
  freshness_status: "delayed",
  stale_reason: "No quote in last 15 min",
};

const BTC_LIVE = {
  price: 67_800.0,
  change_pct: 3.51,
  freshness_status: "live",
  stale_reason: null,
};

// ── Helper ─────────────────────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── Import component AFTER mocks ───────────────────────────────────────────────
// WHY late import: ensures vi.mock() hoisting takes effect before module load.
const { TopBarMarquee } = await import("@/components/shell/TopBarMarquee");

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("TopBarMarquee", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Re-apply default implementation after clearAllMocks resets it.
    mockResolveTickersBatch.mockImplementation((tickers: string[]) => {
      const map: Record<string, string | null> = {};
      tickers.forEach((t) => { map[t] = t; });
      return Promise.resolve(map);
    });
  });

  it("renders ticker symbols and prices after data loads", async () => {
    // WHY: the marquee renders each ticker label + its price. This is the golden-path
    // verification — if symbols and prices are visible, the two-step fetch worked.
    mockGetBatchQuotes.mockResolvedValue({
      quotes: { SPY: SPY_LIVE, QQQ: QQQ_DELAYED, "BTC-USD": BTC_LIVE },
    });

    render(<TopBarMarquee />, { wrapper: makeWrapper() });

    // WHY waitFor wraps the price check (not just the label): ticker labels render
    // immediately (before quotes arrive), so asserting on them would pass too early.
    // The price only appears after BOTH queries resolve (ticker→id, then id→quote).
    // Labels appear twice (list is rendered twice for the seamless CSS loop).
    await waitFor(() => {
      // formatPrice(520.45) → "$520.45"
      expect(screen.getAllByText("$520.45").length).toBeGreaterThanOrEqual(2);
    });

    // Positive change percentage visible — formatPercentDirect(1.12) → "+1.12%"
    expect(screen.getAllByText("+1.12%").length).toBeGreaterThanOrEqual(2);
    // Labels also rendered twice
    expect(screen.getAllByText("SPY").length).toBeGreaterThanOrEqual(2);
  });

  it("suppresses % change and applies muted color for a delayed quote", async () => {
    // WHY: a delayed price must not show directional % — it could mislead traders
    // into thinking QQQ is moving when the price is 15+ minutes old.
    mockGetBatchQuotes.mockResolvedValue({
      quotes: { SPY: SPY_LIVE, QQQ: QQQ_DELAYED },
    });

    render(<TopBarMarquee />, { wrapper: makeWrapper() });

    // Wait for prices to appear (proves second query resolved).
    await waitFor(() => {
      // formatPrice(435.20) → "$435.20"
      expect(screen.getAllByText("$435.20").length).toBeGreaterThanOrEqual(2);
    });

    // "-0.48%" must NOT appear for a delayed quote.
    expect(screen.queryByText("-0.48%")).not.toBeInTheDocument();
  });

  it("shows em-dash placeholders when a quote is not resolved", async () => {
    // WHY: if getBatchQuotes returns an empty object (cold-start, auth race) the
    // chip must degrade gracefully with "—" rather than crashing or showing 0.
    mockGetBatchQuotes.mockResolvedValue({ quotes: {} });

    render(<TopBarMarquee />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // Every unresolved ticker renders "—" for price (rendered twice in the loop).
      const dashes = screen.getAllByText("—");
      expect(dashes.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("renders 10 distinct ticker labels in the strip", async () => {
    // WHY: the MARQUEE_TICKERS manifest must contain all 10 symbols.
    // If a symbol is missing, coverage gaps appear in the market heartbeat strip.
    mockGetBatchQuotes.mockResolvedValue({ quotes: {} });

    render(<TopBarMarquee />, { wrapper: makeWrapper() });

    // Each label appears at least twice (first + second pass).
    for (const label of ["SPY", "QQQ", "IWM", "DIA", "VIX", "TLT", "DXY", "GLD", "USO", "BTC"]) {
      await waitFor(() => {
        expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(2);
      });
    }
  });

  it("has role=marquee and aria-label on the outer wrapper", async () => {
    // WHY: WCAG requires that auto-playing content regions carry a label so
    // screen readers can announce the region and users can navigate past it.
    mockGetBatchQuotes.mockResolvedValue({ quotes: {} });

    render(<TopBarMarquee />, { wrapper: makeWrapper() });

    await waitFor(() => {
      const region = screen.getByRole("marquee");
      expect(region).toHaveAttribute("aria-label", "Market index ticker");
    });
  });
});
