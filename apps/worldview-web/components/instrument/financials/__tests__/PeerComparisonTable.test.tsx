/**
 * PeerComparisonTable.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Pins the composition contract for the 5-peers + self table
 * and the PEERS / COMPETITORS tab toggle. Verifies:
 *   - PEERS tab (default): self-row from fundamentals, peer rows from peersData,
 *     "—" placeholder for null returns, loading/empty states.
 *   - COMPETITORS tab: fires KG fetch, skeleton during load, renders rows with
 *     similarity %, shows empty/error states, and degrades gracefully when
 *     entityId is absent.
 *
 * MOCKING STRATEGY:
 *   - next/navigation → useRouter (push stub)
 *   - @/lib/api-client → useApiClient with mockGateway (avoids real network)
 *   - @tanstack/react-query → QueryClientProvider wrapping each render so
 *     useQuery hooks can fire against a test-local in-memory cache.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PeerComparisonTable } from "@/components/instrument/financials/PeerComparisonTable";
import type { PeersResponse, Fundamentals, SimilarEntitiesResponse } from "@/types/api";

// WHY mock next/navigation: PeerComparisonTable uses useRouter for peer-row clicks.
// vi.mock is hoisted automatically by vitest.
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

// WHY mock @/lib/api-client: useApiClient returns the gateway that owns
// getSimilarEntities. We inject a controllable mock so tests can simulate
// loading, success, and error states without real network calls.
const mockGetSimilarEntities = vi.fn();
vi.mock("@/lib/api-client", () => ({
  useApiClient: () => ({ getSimilarEntities: mockGetSimilarEntities }),
}));

// ── Test fixtures ──────────────────────────────────────────────────────────

const FUNDAMENTALS: Fundamentals = {
  instrument_id: "aapl",
  ticker: "AAPL",
  name: "Apple Inc.",
  market_cap: 3_000_000_000_000,
  pe_ratio: 28.5,
  forward_pe: 26.0,
  price_to_book: 45.0,
  price_to_sales: 7.8,
  ev_to_ebitda: 20.0,
  gross_margin: 0.443,
  operating_margin: 0.302,
  net_margin: 0.254,
  roe: 1.6,
  roa: 0.28,
  revenue_growth_yoy: 0.05,
  earnings_growth_yoy: 0.07,
  dividend_yield: 0.006,
  payout_ratio: 0.15,
  debt_to_equity: 1.8,
  current_ratio: 0.99,
  quick_ratio: 0.94,
  week_52_high: 260.1,
  week_52_low: 164.08,
  daily_return: 0.012,
  analyst_strong_buy_count: 25,
  analyst_buy_count: 5,
  analyst_hold_count: 10,
  analyst_sell_count: 4,
  analyst_strong_sell_count: 1,
  analyst_rating: 4.2,
  analyst_target_price: 215.0,
  updated_at: "2026-05-19T12:00:00Z",
};

const PEERS_RESPONSE: PeersResponse = {
  instrument_id: "aapl",
  industry: "Technology Hardware",
  peers: [
    {
      instrument_id: "msft",
      ticker: "MSFT",
      name: "Microsoft Corp",
      market_cap: 2_900_000_000_000,
      pe_ratio: 35.2,
      // WHY 0.184: return_1y from S3 is a decimal fraction (0.184 = 18.4%).
      // S3 does NOT multiply return_1y by 100 (unlike change_pct which it does).
      return_1y: 0.184,
      // WHY 0.3: change_pct from S3 is already a percentage (0.3 = +0.30%).
      change_pct: 0.3,
    },
    {
      instrument_id: "googl",
      ticker: "GOOGL",
      name: "Alphabet Inc",
      market_cap: 2_000_000_000_000,
      pe_ratio: 22.1,
      return_1y: null,
      change_pct: -0.5,
    },
  ],
};

const SIMILAR_ENTITIES_RESPONSE: SimilarEntitiesResponse = {
  entity_id: "entity-aapl-uuid",
  canonical_name: "Apple Inc.",
  total: 2,
  results: [
    {
      entity_id: "entity-msft-uuid",
      canonical_name: "Microsoft Corporation",
      entity_type: "company",
      ticker: "MSFT",
      exchange: "NASDAQ",
      ann_similarity_score: 0.91,
      competes_with_confidence: 0.88,
      final_score: 0.874,
      has_competes_with_relation: true,
    },
    {
      entity_id: "entity-googl-uuid",
      canonical_name: "Alphabet Inc.",
      entity_type: "company",
      ticker: "GOOGL",
      exchange: "NASDAQ",
      ann_similarity_score: 0.78,
      competes_with_confidence: null,
      final_score: 0.612,
      has_competes_with_relation: false,
    },
  ],
};

// ── Test helpers ───────────────────────────────────────────────────────────

/** Wraps the component in a fresh QueryClient so each test gets an isolated cache. */
function renderWithQuery(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: {
      // WHY retry: 0: prevent TanStack Query from retrying failed fetches in
      // tests — that would cause test timeouts when we intentionally reject.
      queries: { retry: 0 },
    },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("PeerComparisonTable", () => {
  beforeEach(() => {
    // WHY reset between tests: mockGetSimilarEntities.mockResolvedValue in one
    // test must not bleed into the next. vi.resetAllMocks clears both
    // implementation and call history.
    vi.resetAllMocks();
    // Default: competitors query returns never-resolving promise so LOADING
    // state tests can assert the skeleton is visible.
    mockGetSimilarEntities.mockReturnValue(new Promise(() => {}));
  });

  // ── PEERS tab (default view) ─────────────────────────────────────────────

  it("renders PEERS tab by default", () => {
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    // The PEERS tab button must be aria-selected="true" by default.
    const peersBtn = screen.getByRole("tab", { name: /peers/i });
    expect(peersBtn).toHaveAttribute("aria-selected", "true");

    // The COMPETITORS tab button must NOT be selected by default.
    const compBtn = screen.getByRole("tab", { name: /competitors/i });
    expect(compBtn).toHaveAttribute("aria-selected", "false");
  });

  it("renders section header", () => {
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText(/PEER COMPARISON/)).toBeInTheDocument();
  });

  it("renders self-row with ticker from fundamentals", () => {
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
  });

  it("renders peer tickers", () => {
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("GOOGL")).toBeInTheDocument();
  });

  it("renders — for null return_1y", () => {
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    // GOOGL has null return_1y → should show "—"
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });

  it("formats return_1y as decimal fraction (18.4% shown as +18.40%)", () => {
    // WHY this test: return_1y from S3 is a decimal fraction (0.184 = 18.4%).
    // Previously fmtPct divided by 100 again → 0.001840 → "+0.18%" (wrong).
    // After fix, fmtDecimalPct calls formatPercent(0.184) → "+18.40%".
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    // MSFT has return_1y=0.184 → should render "+18.40%"
    expect(screen.getByText("+18.40%")).toBeInTheDocument();
  });

  it("formats change_pct as already-percentage (0.3 shown as +0.30%)", () => {
    // WHY this test: change_pct from S3 is already a percentage (0.3 = +0.30%).
    // fmtPctDirect calls formatPercentDirect(0.3) → "+0.30%".
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    // MSFT has change_pct=0.3 → should render "+0.30%"
    expect(screen.getByText("+0.30%")).toBeInTheDocument();
  });

  it("renders loading state when peersData is undefined", () => {
    renderWithQuery(
      <PeerComparisonTable
        peersData={undefined}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText(/peer data loading/i)).toBeInTheDocument();
  });

  it("renders empty state when peers array is empty", () => {
    renderWithQuery(
      <PeerComparisonTable
        peersData={{ instrument_id: "aapl", industry: null, peers: [] }}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText(/no peers available/i)).toBeInTheDocument();
  });

  // ── COMPETITORS tab ──────────────────────────────────────────────────────

  it("switches to COMPETITORS tab on click", () => {
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
        entityId="entity-aapl-uuid"
      />,
    );

    const compBtn = screen.getByRole("tab", { name: /competitors/i });
    fireEvent.click(compBtn);

    // After click, COMPETITORS must be aria-selected, PEERS must not.
    expect(compBtn).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /peers/i })).toHaveAttribute("aria-selected", "false");
  });

  it("shows skeleton while loading competitors", async () => {
    // mockGetSimilarEntities already returns a never-resolving promise (from
    // beforeEach) — the component will stay in LOADING state indefinitely.
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
        entityId="entity-aapl-uuid"
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: /competitors/i }));

    // WHY aria-label check: CompetitorsSkeleton has aria-label="Loading competitor
    // data". This is more robust than searching for CSS classes.
    expect(await screen.findByLabelText("Loading competitor data")).toBeInTheDocument();
  });

  it("renders competitors with similarity score", async () => {
    mockGetSimilarEntities.mockResolvedValue(SIMILAR_ENTITIES_RESPONSE);

    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
        entityId="entity-aapl-uuid"
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: /competitors/i }));

    // WHY waitFor: getSimilarEntities is async — the component re-renders after
    // the promise resolves. We wait for the MSFT row to appear.
    await waitFor(() => {
      expect(screen.getByRole("table", { name: /KG semantic competitors/i })).toBeInTheDocument();
    });

    // MSFT row: ticker, name, similarity score.
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("Microsoft Corporation")).toBeInTheDocument();
    // final_score=0.874 → "87.4%"
    expect(screen.getByText("87.4%")).toBeInTheDocument();
    // has_competes_with_relation=true → label "competes"
    expect(screen.getByText("competes")).toBeInTheDocument();

    // GOOGL row: final_score=0.612 → "61.2%", no competes_with relation → "similar"
    expect(screen.getByText("GOOGL")).toBeInTheDocument();
    expect(screen.getByText("61.2%")).toBeInTheDocument();
    expect(screen.getByText("similar")).toBeInTheDocument();
  });

  it("shows empty state when no competitors returned", async () => {
    mockGetSimilarEntities.mockResolvedValue({
      entity_id: "entity-aapl-uuid",
      canonical_name: "Apple Inc.",
      total: 0,
      results: [],
    } satisfies SimilarEntitiesResponse);

    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
        entityId="entity-aapl-uuid"
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: /competitors/i }));

    await waitFor(() => {
      expect(screen.getByText(/no semantic competitors found/i)).toBeInTheDocument();
    });
  });

  it("shows error message when competitors fetch fails", async () => {
    mockGetSimilarEntities.mockRejectedValue(new Error("network error"));

    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
        entityId="entity-aapl-uuid"
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: /competitors/i }));

    await waitFor(() => {
      expect(screen.getByText(/unable to load competitor data/i)).toBeInTheDocument();
    });
  });

  it("shows KG entity not linked message when entityId is absent", () => {
    renderWithQuery(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
        // WHY no entityId: simulates FinancialsTab used outside InstrumentPageClient
        // where bundle.entity_id is not yet resolved.
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: /competitors/i }));

    expect(screen.getByText(/KG entity not linked/i)).toBeInTheDocument();
    // The PEERS tab table should still be gone (switched away) but no query should fire.
    expect(mockGetSimilarEntities).not.toHaveBeenCalled();
  });
});
