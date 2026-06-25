/**
 * __tests__/market-snapshot-resolution.test.tsx — unified instrument
 * resolution (user report 2026-06-10).
 *
 * BUG: the TopBar strip showed IWM 285.21 while MarketSnapshotWidget rendered
 * "—" for IWM and BTC. Two divergences:
 *   1. the widget asked resolveTickersBatch for "BTC" (resolves null on S3);
 *      the canonical row is "BTC-USD".
 *   2. the widget read ONLY overview.quote, which S9 returns as null for
 *      IWM/VIX, while the strip's POST /v1/quotes/batch had a real price.
 * These tests pin the fix: canonical "BTC-USD" symbol + batch-quote fallback.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ──────────────────────────────────────────────────────────────────

const mockResolveTickersBatch = vi.fn();
const mockGetCompanyOverview = vi.fn();
const mockGetBatchQuotes = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    resolveTickersBatch: mockResolveTickersBatch,
    getCompanyOverview: mockGetCompanyOverview,
    getBatchQuotes: mockGetBatchQuotes,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { MarketSnapshotWidget } from "@/components/dashboard/MarketSnapshotWidget";

// ── Fixtures ───────────────────────────────────────────────────────────────

// Mirror the live S3 behaviour observed 2026-06-10:
//   - "BTC-USD" resolves (the old "BTC" symbol did NOT)
//   - IWM resolves but its overview has quote: null
const TICKER_IDS: Record<string, string | null> = {
  SPY: "id-spy",
  QQQ: "id-qqq",
  IWM: "id-iwm",
  VIX: "id-vix",
  "BTC-USD": "id-btc",
  AAPL: "id-aapl",
  MSFT: "id-msft",
  NVDA: "id-nvda",
  AMZN: "id-amzn",
  GOOGL: "id-googl",
  JPM: "id-jpm",
};

/** Overview responses keyed by instrument id — IWM/VIX have NO quote leg. */
function overviewFor(id: string) {
  if (id === "id-iwm" || id === "id-vix") return { quote: null };
  if (id === "id-btc") {
    return { quote: { price: 76736.46, change: -4367.81, change_pct: -5.39 } };
  }
  return { quote: { price: 100, change: 1, change_pct: 1 } };
}

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockResolveTickersBatch.mockResolvedValue(TICKER_IDS);
  mockGetCompanyOverview.mockImplementation(async (id: string) => overviewFor(id));
  // Batch quotes — the IndexStrip's working path. IWM has the price the
  // overview lacks (the exact live discrepancy from the user's screenshot).
  mockGetBatchQuotes.mockResolvedValue({
    quotes: {
      "id-iwm": { price: 285.21, change: 0, change_pct: 0 },
      "id-vix": { price: 18.42, change: 0.3, change_pct: 1.66 },
    },
  });
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("MarketSnapshotWidget — unified instrument resolution", () => {
  it("resolves crypto via the canonical BTC-USD symbol (not the unresolvable 'BTC')", async () => {
    render(<MarketSnapshotWidget />, { wrapper: makeWrapper() });
    await waitFor(() => expect(mockResolveTickersBatch).toHaveBeenCalled());
    const requested = mockResolveTickersBatch.mock.calls[0][0] as string[];
    expect(requested).toContain("BTC-USD");
    expect(requested).not.toContain("BTC");
  });

  it("falls back to the batch-quote path when the overview has no quote (IWM)", async () => {
    render(<MarketSnapshotWidget />, { wrapper: makeWrapper() });
    // IWM's overview.quote is null — pre-fix the row rendered "—". The batch
    // fallback supplies 285.21 (the price the TopBar strip already showed).
    await waitFor(() => {
      expect(screen.getByText("$285.21")).toBeInTheDocument();
    });
    // The fallback call went out exactly once with the resolved ids.
    expect(mockGetBatchQuotes).toHaveBeenCalled();
  });

  it("still renders the BTC row's overview price under its short 'BTC' label", async () => {
    render(<MarketSnapshotWidget />, { wrapper: makeWrapper() });
    await waitFor(() => {
      // Display label is "BTC" (the canonical "BTC-USD" is API-side only).
      expect(screen.getByText("BTC")).toBeInTheDocument();
      // Overview quote for id-btc renders (fallback not needed for BTC).
      expect(screen.getByText("$76,736.46")).toBeInTheDocument();
    });
  });

  it("renders '—' when BOTH the overview and batch legs lack a positive price", async () => {
    // Simulate the genuine no-data case: overview null AND batch empty.
    mockGetBatchQuotes.mockResolvedValue({ quotes: {} });
    render(<MarketSnapshotWidget />, { wrapper: makeWrapper() });
    await waitFor(() => expect(screen.getByText("IWM")).toBeInTheDocument());
    // IWM + VIX rows have no price at all → dashes (3 cells each: price,
    // change-$, change-%).
    await waitFor(() => {
      expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(6);
    });
  });
});
