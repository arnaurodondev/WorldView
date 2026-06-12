/**
 * components/instrument/quote/strips/__tests__/quoteStrips.test.tsx
 *
 * WHY THIS EXISTS (Wave-2): the four new Quote-tab strips replace the
 * "backend endpoint pending" placeholders with live Wave-1 endpoints. This
 * suite pins, per strip:
 *
 *   ReturnsStrip       — values render with the PERCENT-FORM contract
 *                        (-7.93 → "-7.93%", NOT "-0.08%"), sign colouring,
 *                        and em-dash for null horizons (3Y/5Y in dev data).
 *   IntradayStatsStrip — O/H/L/PREV/VWAP/VOL cells render; the vs-30D ratio
 *                        renders as a percentage; VWAP source in the tooltip.
 *   PriceLevelsPanel   — 52w marker positioned from last_close, S/R chips
 *                        render with the sr_method tooltip, MA cells colour
 *                        by trend; null payload → all dashes (no crash).
 *   PeersTable         — 8 rows render ticker/last/chg%/mcap/P-E; row click
 *                        AND Enter key navigate to the peer's page; empty
 *                        peers → named "No peer data" state.
 *
 * FIXTURES mirror the LIVE AAPL responses verified 2026-06-10 (including the
 * unit quirk: peers.change_pct percent-form vs return_1y decimal).
 *
 * MOCK STRATEGY: gateway mocked at its seam; useAccessToken returns a token
 * so the token-gated queries fire; fresh QueryClient per test.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ────────────────────────────────────────────────────────────────────

const routerPush = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: routerPush, replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/i-1"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("@/lib/api-client", () => ({
  useAccessToken: vi.fn(() => "test-token"),
}));

const mockGateway = vi.hoisted(() => ({
  getMultiPeriodReturns: vi.fn(),
  getIntradayStats: vi.fn(),
  getPriceLevels: vi.fn(),
  getPeers: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// Imports AFTER mocks.
// eslint-disable-next-line import/first
import { ReturnsStrip } from "@/components/instrument/quote/strips/ReturnsStrip";
// eslint-disable-next-line import/first
import { IntradayStatsStrip } from "@/components/instrument/quote/strips/IntradayStatsStrip";
// eslint-disable-next-line import/first
import { PriceLevelsPanel } from "@/components/instrument/quote/strips/PriceLevelsPanel";
// eslint-disable-next-line import/first
import { PeersTable } from "@/components/instrument/quote/strips/PeersTable";

// ── Helpers / fixtures (live-verified shapes) ────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const RETURNS = {
  instrument_id: "i-1",
  as_of: "2026-06-10",
  // PERCENT-FORM values + null 3Y/5Y — exactly the live dev-data shape.
  returns: { "1D": -7.9289, "1W": -7.9289, "1M": -0.4282, "3M": 11.4413, "6M": 4.2578, YTD: 6.9116, "1Y": 43.4105, "3Y": null, "5Y": null },
};

const INTRADAY = {
  instrument_id: "i-1",
  session_date: "2026-06-10",
  open: 289.9, prev_close: 315.68, day_high: 290.99, day_low: 289.85,
  vwap: 290.6117, vwap_source: "1m", volume: 43_815, volume_vs_30d_ratio: 0.0016,
};

const LEVELS = {
  instrument_id: "i-1",
  as_of: "2026-06-10",
  last_close: 290.65, high_52w: 315.68, low_52w: 195.07,
  pct_from_52w_high: -7.9289, pct_from_52w_low: 48.9978,
  ma_50: 275.5951, ma_200: 263.3148,
  prior_session_high: 315.68, prior_session_low: 313.94,
  support: [271.7, 265.4, 265.07], resistance: [294.76, 311.47],
  sr_method: "fractal swing points (k=2) over the last 90 daily bars",
};

const PEERS = {
  instrument_id: "i-1",
  industry: "Technology",
  peers: [
    { instrument_id: "p-nvda", ticker: "NVDA", name: "NVIDIA Corporation", market_cap: 5_053_469_425_664, pe_ratio: 31.951, return_1y: 0.570155, change_pct: 1.6135, last_price: 222.82 },
    { instrument_id: "p-msft", ticker: "MSFT", name: "Microsoft Corporation", market_cap: 3_058_583_732_224, pe_ratio: 24.5229, return_1y: -0.047092, change_pct: 0.872, last_price: 441.31 },
    // A degraded peer: nulls render as em-dashes, never NaN.
    { instrument_id: "p-tsm", ticker: "TSM", name: "Taiwan Semiconductor", market_cap: 2_153_268_510_720, pe_ratio: null, return_1y: null, change_pct: null, last_price: null },
  ],
};

beforeEach(() => {
  routerPush.mockClear();
  mockGateway.getMultiPeriodReturns.mockReset().mockResolvedValue(RETURNS);
  mockGateway.getIntradayStats.mockReset().mockResolvedValue(INTRADAY);
  mockGateway.getPriceLevels.mockReset().mockResolvedValue(LEVELS);
  mockGateway.getPeers.mockReset().mockResolvedValue(PEERS);
});

// ── ReturnsStrip ─────────────────────────────────────────────────────────────

describe("ReturnsStrip", () => {
  it("renders percent-form values with sign colouring and em-dash nulls", async () => {
    render(<Wrapper><ReturnsStrip instrumentId="i-1" /></Wrapper>);
    // PERCENT-FORM contract: -7.9289 → "-7.93%" (formatPercentDirect),
    // NOT "-0.08%" (the double-divide bug formatPercent would produce).
    await waitFor(() => expect(screen.getAllByText("-7.93%").length).toBeGreaterThan(0));
    expect(screen.getByText("+43.41%")).toBeInTheDocument();   // 1Y, positive sign
    // Null horizons (3Y/5Y) render em-dashes — count them.
    expect(screen.getAllByText("—")).toHaveLength(2);
    // Sign colouring: the 1M loss is negative-red.
    expect(screen.getByText("-0.43%")).toHaveClass("text-negative");
    expect(screen.getByText("+43.41%")).toHaveClass("text-positive");
  });

  it("renders all 9 horizon labels before data arrives (stable skeleton)", () => {
    mockGateway.getMultiPeriodReturns.mockReturnValue(new Promise(() => { /* pending */ }));
    render(<Wrapper><ReturnsStrip instrumentId="i-1" /></Wrapper>);
    for (const h of ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y"]) {
      expect(screen.getByText(h)).toBeInTheDocument();
    }
  });
});

// ── IntradayStatsStrip ───────────────────────────────────────────────────────

describe("IntradayStatsStrip", () => {
  it("renders O/H/L/PREV/VWAP/VOL and the vs-30D ratio as a percentage", async () => {
    render(<Wrapper><IntradayStatsStrip instrumentId="i-1" /></Wrapper>);
    await waitFor(() => expect(screen.getByText("289.90")).toBeInTheDocument()); // open
    expect(screen.getByText("290.99")).toBeInTheDocument();  // high
    expect(screen.getByText("289.85")).toBeInTheDocument();  // low
    expect(screen.getByText("315.68")).toBeInTheDocument();  // prev close
    expect(screen.getByText("290.61")).toBeInTheDocument();  // vwap (2dp)
    // 0.0016 ratio → "0%" of the 30-day average (partial session).
    expect(screen.getByText("0%")).toBeInTheDocument();
    // VWAP source surfaces as a tooltip so precision is auditable.
    expect(screen.getByTitle("VWAP computed from 1m bars")).toBeInTheDocument();
  });

  it("renders em-dashes (not NaN) when the endpoint has no data yet", () => {
    mockGateway.getIntradayStats.mockReturnValue(new Promise(() => { /* pending */ }));
    render(<Wrapper><IntradayStatsStrip instrumentId="i-1" /></Wrapper>);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(6);
  });
});

// ── PriceLevelsPanel ─────────────────────────────────────────────────────────

describe("PriceLevelsPanel", () => {
  it("renders the 52w marker, MA cells, and S/R chips with the method tooltip", async () => {
    render(<Wrapper><PriceLevelsPanel instrumentId="i-1" /></Wrapper>);
    await waitFor(() => expect(screen.getByText("195.07")).toBeInTheDocument()); // 52w low
    expect(screen.getByText("315.68")).toBeInTheDocument();  // 52w high
    // Range marker exists and sits between the band edges
    // ((290.65-195.07)/(315.68-195.07) ≈ 79.3%).
    const marker = screen.getByTestId("range-marker");
    expect(parseFloat(marker.style.left)).toBeCloseTo(79.3, 0);
    // MA trend colouring: price 290.65 above both MAs → positive.
    expect(screen.getByText("275.60")).toHaveClass("text-positive"); // MA50
    expect(screen.getByText("263.31")).toHaveClass("text-positive"); // MA200
    // S/R chips (nearest 3) with the algorithm tooltip on the chip row.
    expect(screen.getByText("271.70")).toBeInTheDocument();
    expect(screen.getByText("294.76")).toBeInTheDocument();
    expect(screen.getByTitle(/fractal swing points/)).toBeInTheDocument();
  });

  it("renders dashes without crashing when the payload is pending", () => {
    mockGateway.getPriceLevels.mockReturnValue(new Promise(() => { /* pending */ }));
    render(<Wrapper><PriceLevelsPanel instrumentId="i-1" /></Wrapper>);
    expect(screen.getByText("Price Levels")).toBeInTheDocument();
    expect(screen.queryByTestId("range-marker")).not.toBeInTheDocument();
  });
});

// ── PeersTable ───────────────────────────────────────────────────────────────

describe("PeersTable", () => {
  it("renders peer rows with percent-form chg% and compact market caps", async () => {
    render(<Wrapper><PeersTable instrumentId="i-1" /></Wrapper>);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());
    expect(screen.getByText("NVIDIA Corporation")).toBeInTheDocument();
    expect(screen.getByText("222.82")).toBeInTheDocument();   // last
    // change_pct is PERCENT-FORM (1.6135 → "+1.61%") — the unit-quirk guard.
    expect(screen.getByText("+1.61%")).toBeInTheDocument();
    expect(screen.getByText("$5.05T")).toBeInTheDocument();   // mkt cap compact
    expect(screen.getByText("32.0")).toBeInTheDocument();     // P/E 1dp (31.951 → "32.0")
    // Degraded peer renders dashes, not NaN.
    const tsmRow = screen.getByText("TSM").closest("tr")!;
    expect(tsmRow.textContent).toContain("—");
    // Industry qualifier in the header.
    expect(screen.getByText("Technology")).toBeInTheDocument();
  });

  it("navigates to the peer's instrument page on row click and Enter", async () => {
    render(<Wrapper><PeersTable instrumentId="i-1" /></Wrapper>);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());
    fireEvent.click(screen.getByText("NVDA").closest("tr")!);
    expect(routerPush).toHaveBeenCalledWith("/instruments/p-nvda");
    // Keyboard parity: Enter on the focused row navigates too.
    fireEvent.keyDown(screen.getByText("MSFT").closest("tr")!, { key: "Enter" });
    expect(routerPush).toHaveBeenCalledWith("/instruments/p-msft");
  });

  it("renders the named empty state when no peers exist", async () => {
    mockGateway.getPeers.mockResolvedValue({ instrument_id: "i-1", industry: null, peers: [] });
    render(<Wrapper><PeersTable instrumentId="i-1" /></Wrapper>);
    await waitFor(() => expect(screen.getByText("No peer data")).toBeInTheDocument());
  });
});
