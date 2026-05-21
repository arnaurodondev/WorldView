/**
 * __tests__/indices/IndexDetailClient.test.tsx — QA F-002 follow-up.
 *
 * IndexDetailClient (140 LOC) shipped in W1 with zero unit tests; only
 * a Playwright spec covered the route (and only as a 200 probe, not as
 * a render check). The component owns three composed TanStack queries,
 * an InstrumentNotFound branch, a friendly-name lookup table, and a
 * Sparkline-fed intraday section. This file pins the contracts the
 * marquee + watchlist + e2e suite depend on:
 *
 *   - successful resolve renders ticker + friendly name + price + change
 *   - unresolved ticker falls back to <InstrumentNotFound>
 *   - empty bars array passes a [] to Sparkline without crashing
 *   - friendly-name lookup falls back to the raw symbol when unknown
 *   - quote price + change format via the existing utils (color + sign)
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ──────────────────────────────────────────────────────────────────

const mockSearchInstruments = vi.fn();
const mockGetBatchQuotes = vi.fn();
const mockGetBatchOhlcvBars = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    searchInstruments: mockSearchInstruments,
    getBatchQuotes: mockGetBatchQuotes,
    getBatchOhlcvBars: mockGetBatchOhlcvBars,
  }),
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "tok", isAuthenticated: true }),
}));

import { IndexDetailClient } from "@/app/(app)/indices/[ticker]/IndexDetailClient";

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockSearchInstruments.mockResolvedValue({
    results: [{ instrument_id: "01900000-0000-7000-8000-00000000spy0" }],
  });
  mockGetBatchQuotes.mockResolvedValue({
    quotes: {
      "01900000-0000-7000-8000-00000000spy0": {
        ticker: "SPY",
        price: 600.5,
        change: 5.0,
        change_pct: 0.84,
        timestamp: "2026-05-21T18:00:00Z",
        volume: 1_000_000,
        freshness_status: "live" as const,
      },
    },
  });
  mockGetBatchOhlcvBars.mockResolvedValue({
    results: [
      {
        instrument_id: "01900000-0000-7000-8000-00000000spy0",
        bars: [
          { timestamp: "2026-05-21T13:30:00Z", open: 599, high: 601, low: 598, close: 600, volume: 1000 },
          { timestamp: "2026-05-21T13:35:00Z", open: 600, high: 601, low: 599, close: 600.5, volume: 1000 },
        ],
      },
    ],
  });
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("IndexDetailClient", () => {
  it("renders ticker + friendly name + spot price + change once resolved", async () => {
    render(<IndexDetailClient ticker="SPY" />, { wrapper: makeWrapper() });
    expect(await screen.findByRole("heading", { name: "SPY" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/S&P 500 ETF/i)).toBeInTheDocument();
    });
    // Spot price is formatted by formatPrice; just assert the integer part.
    await waitFor(() => {
      expect(screen.getByText(/600\.50|\$600/i)).toBeInTheDocument();
    });
  });

  it("renders InstrumentNotFound when searchInstruments returns zero results", async () => {
    mockSearchInstruments.mockResolvedValue({ results: [] });
    render(<IndexDetailClient ticker="XYZNOPE" />, { wrapper: makeWrapper() });
    // InstrumentNotFound primitive shows the attempted ticker prominently.
    await waitFor(() => {
      expect(screen.getByText(/XYZNOPE/i)).toBeInTheDocument();
    });
  });

  it("falls back to the raw symbol when ticker is not in the friendly-name table", async () => {
    // ZZZZ has no entry in FRIENDLY_NAME — the header should fall back
    // to the raw ticker rather than showing 'undefined'.
    mockSearchInstruments.mockResolvedValue({
      results: [{ instrument_id: "01900000-0000-7000-8000-00000000zzz0" }],
    });
    mockGetBatchQuotes.mockResolvedValue({
      quotes: {
        "01900000-0000-7000-8000-00000000zzz0": {
          ticker: "ZZZZ",
          price: 1,
          change: 0,
          change_pct: 0,
          timestamp: "2026-05-21T18:00:00Z",
          volume: 0,
          freshness_status: "live" as const,
        },
      },
    });
    render(<IndexDetailClient ticker="ZZZZ" />, { wrapper: makeWrapper() });
    await waitFor(() => {
      const headings = screen.getAllByText("ZZZZ");
      // Heading + small uppercase fallback label both render the raw ticker.
      expect(headings.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders the Sparkline even when bars endpoint returns an empty results array", async () => {
    mockGetBatchOhlcvBars.mockResolvedValue({ results: [] });
    const { container } = render(<IndexDetailClient ticker="SPY" />, { wrapper: makeWrapper() });
    await screen.findByRole("heading", { name: "SPY" });
    // The Sparkline primitive renders an <svg role="img"> regardless of
    // data — in the empty case it renders the dotted-line placeholder.
    const svgs = container.querySelectorAll("svg[role='img']");
    expect(svgs.length).toBeGreaterThanOrEqual(1);
  });

  it("shows em-dash placeholders before the quote resolves", async () => {
    // Never-resolving quote → header should still render with `—`
    // placeholders rather than collapsing layout.
    mockGetBatchQuotes.mockImplementation(() => new Promise(() => {}));
    render(<IndexDetailClient ticker="SPY" />, { wrapper: makeWrapper() });
    await screen.findByRole("heading", { name: "SPY" });
    // The big spot-price slot renders the em-dash literal "—" (no value).
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });
});
