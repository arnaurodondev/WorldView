/**
 * __tests__/instrument-wave-e-plan-0053.test.tsx —
 *   Vitest coverage for PLAN-0053 Wave E instrument-page polish
 *
 * WHY THIS EXISTS: Wave E touches four instrument-page surfaces (OverviewSidebar,
 * FundamentalsTab inline sparklines, IntelligenceTab Sheet, NewsTab source/narrative
 * polish). Each non-trivial change gets at least one unit test per the wave spec
 * to lock in:
 *   1. OverviewSidebar — Zone 1 / Competitors / News all render with correct
 *      loading + empty + content states (BP-291 compliant skeleton heights).
 *   2. NewsTab — source monogram derives from URL domain (mapped + fallback),
 *      narrative chips trigger on title keywords, sessionStorage persists filters
 *      across re-renders.
 *   3. FundamentalsTab — major metric rows now wire instrumentId + sparklineMetric
 *      to the inline FundamentalSparkline.
 *   4. IntelligenceTab — clicking a contradiction row opens the side Sheet (not
 *      in-place expand) and the Sheet contains Claim A + Claim B text.
 *
 * WHY MOCKS: All four components hit useQuery (TanStack Query) + useAuth (JWT) +
 * useRouter (Next.js navigation). We mock the gateway per-test to control fixtures
 * without spinning up a real S9.
 *
 * WHAT IS NOT TESTED HERE (covered elsewhere or e2e):
 *   - WeekRangeBar visual alignment — already covered by existing component tests.
 *   - PeerComparisonPanel data-fetch logic — already covered in instrument-detail.test.
 *   - Sheet animation timing — Radix internals; out of scope.
 *
 * DESIGN REFERENCE: PLAN-0053 §Wave E
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { RankedArticle, Fundamentals, Instrument } from "@/types/api";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001", instrumentId: "inst-001" })),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token", user: null, isLoading: false })),
}));

// WHY mock createGateway with a configurable return value: each test sets up the
// methods it needs. Default returns empty payloads so unrelated useQuery calls
// (e.g., entity-graph in OverviewSidebar) don't crash with "is not a function".
const mockGateway = {
  getEntityGraph: vi.fn().mockResolvedValue({
    entity_id: "ent-001",
    nodes: [],
    edges: [],
  }),
  runScreener: vi.fn().mockResolvedValue({ results: [], total: 0 }),
  getEntityNews: vi.fn().mockResolvedValue({ articles: [], total: 0 }),
  getFundamentals: vi.fn().mockResolvedValue(null),
  getFundamentalsSnapshot: vi.fn().mockResolvedValue(null),
  getFundamentalsTimeseries: vi.fn().mockResolvedValue({ data: [] }),
  getContradictions: vi.fn().mockResolvedValue({
    entity_id: "ent-001",
    contradictions: [],
  }),
  getInstrumentBrief: vi.fn().mockResolvedValue({
    narrative: "",
    entity_mentions: [],
    citations: [],
    generated_at: new Date().toISOString(),
    risk_summary: null,
    cached: false,
    entity_id: "ent-001",
  }),
};

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * makeQueryClient — fresh QueryClient with retries disabled.
 * WHY: TanStack Query retries every failed query 3 times by default which makes
 * tests slow and noisy. Disabling retries means failures surface immediately.
 */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={makeQueryClient()}>{children}</QueryClientProvider>
  );
}

/** Build a RankedArticle fixture with overrideable fields. */
function makeArticle(overrides: Partial<RankedArticle> = {}): RankedArticle {
  return {
    article_id: "art-" + Math.random().toString(36).slice(2, 8),
    title: "Test Article",
    url: "https://example.com/article",
    published_at: new Date().toISOString(),
    source_type: "eodhd_news",
    source_name: "Reuters",
    routing_tier: "MEDIUM",
    routing_score: 0.6,
    market_impact_score: 0.5,
    llm_relevance_score: 0.7,
    display_relevance_score: 0.65,
    primary_entity_id: "ent-001",
    primary_entity_symbol: "AAPL",
    impact_windows: null,
    sentiment: null,
    impact_score: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  // WHY restore default mock returns: each describe block's `beforeEach` may
  // override mockGateway methods; after a test we reset to safe defaults so the
  // next test's queries don't accidentally use stale fixtures.
  mockGateway.getEntityGraph.mockResolvedValue({
    entity_id: "ent-001",
    nodes: [],
    edges: [],
  });
  mockGateway.runScreener.mockResolvedValue({ results: [], total: 0 });
  mockGateway.getEntityNews.mockResolvedValue({ articles: [], total: 0 });
  mockGateway.getFundamentals.mockResolvedValue(null);
  mockGateway.getFundamentalsSnapshot.mockResolvedValue(null);
  mockGateway.getFundamentalsTimeseries.mockResolvedValue({ data: [] });
  mockGateway.getContradictions.mockResolvedValue({
    entity_id: "ent-001",
    contradictions: [],
  });

  // Clear sessionStorage between tests so persistence assertions start clean.
  if (typeof window !== "undefined") {
    window.sessionStorage.clear();
  }
});

// ── OverviewSidebar tests ─────────────────────────────────────────────────────

describe("OverviewSidebar (T-E-5-01 + T-E-5-02)", () => {
  it("renders 5 zones: Overview Summary, Competitors, News, plus children slot", async () => {
    const { OverviewSidebar } = await import(
      "@/components/instrument/OverviewSidebar"
    );

    const fund: Fundamentals = {
      instrument_id: "inst-001",
      ticker: "AAPL",
      market_cap: 3_000_000_000_000,
      pe_ratio: 28,
      forward_pe: 25,
      price_to_book: 45,
      price_to_sales: 7.2,
      ev_to_ebitda: 22,
      gross_margin: 0.45,
      operating_margin: 0.30,
      net_margin: 0.25,
      roe: 0.30,
      roa: 0.20,
      revenue_growth_yoy: 0.08,
      earnings_growth_yoy: 0.10,
      dividend_yield: 0.005,
      payout_ratio: 0.15,
      debt_to_equity: 1.5,
      current_ratio: 1.0,
      quick_ratio: 0.8,
      week_52_low: 150,
      week_52_high: 200,
      daily_return: 0.012,
      updated_at: new Date().toISOString(),
    } as Fundamentals;

    const instrument: Instrument = {
      instrument_id: "inst-001",
      ticker: "AAPL",
      gics_sector: "Information Technology",
    } as Instrument;

    render(
      <OverviewSidebar
        instrumentId="inst-001"
        entityId="ent-001"
        fundamentals={fund}
        instrument={instrument}
        currentPrice={185.0}
        onViewAllNews={vi.fn()}
        metricsAndSparklines={<div data-testid="slot-content">METRICS_SLOT</div>}
      />,
      { wrapper },
    );

    // Zone 1 (Summary) — current price renders as "$185.00"
    expect(screen.getByText("$185.00")).toBeInTheDocument();
    // Zone 1 — MCAP / P/E / YLD badges. WHY getAllByText: "P/E" also appears
    // as the P/E sparkline trend metric label; we just need at least one badge.
    expect(screen.getByText("MCAP")).toBeInTheDocument();
    expect(screen.getAllByText("P/E").length).toBeGreaterThan(0);
    expect(screen.getByText("YLD")).toBeInTheDocument();

    // Zone 2 (Competitors) — section heading
    expect(screen.getByText("COMPETITORS")).toBeInTheDocument();
    // Zone 3 (News) — section heading
    expect(screen.getByText("NEWS")).toBeInTheDocument();

    // Children slot (zones 4 + 5) — passed-through metric panel content
    expect(screen.getByTestId("slot-content")).toHaveTextContent("METRICS_SLOT");
  });

  it("renders Overview Summary loading skeleton when fundamentals + price are null", async () => {
    const { OverviewSidebar } = await import(
      "@/components/instrument/OverviewSidebar"
    );

    render(
      <OverviewSidebar
        instrumentId="inst-001"
        entityId="ent-001"
        fundamentals={null}
        instrument={null}
        currentPrice={null}
        onViewAllNews={vi.fn()}
        metricsAndSparklines={null}
      />,
      { wrapper },
    );

    // Section labels still render (Competitors / News are static section headers)
    expect(screen.getByText("COMPETITORS")).toBeInTheDocument();
    expect(screen.getByText("NEWS")).toBeInTheDocument();
    // Zone 1 should NOT show a hard "$" price line because we have no data — the
    // skeleton replaces the content. We assert the price text is absent.
    expect(screen.queryByText(/^\$\d/)).not.toBeInTheDocument();
  });

  it("collapses the Competitors zone when the trigger is clicked", async () => {
    const { OverviewSidebar } = await import(
      "@/components/instrument/OverviewSidebar"
    );

    render(
      <OverviewSidebar
        instrumentId="inst-001"
        entityId="ent-001"
        fundamentals={null}
        instrument={null}
        currentPrice={null}
        onViewAllNews={vi.fn()}
        metricsAndSparklines={null}
      />,
      { wrapper },
    );

    // The Competitors trigger button is identified by its aria-label
    const trigger = screen.getByLabelText("Collapse competitors");
    fireEvent.click(trigger);

    // After clicking, aria-label flips to "Expand competitors"
    await waitFor(() => {
      expect(screen.getByLabelText("Expand competitors")).toBeInTheDocument();
    });
  });
});

// ── NewsTab — source monogram + narrative chips + sessionStorage ──────────────

describe("NewsTab Wave E polish (T-E-5-05)", () => {
  it("renders 2-letter source monogram from a known publisher domain", async () => {
    mockGateway.getEntityNews.mockResolvedValue({
      articles: [
        makeArticle({
          url: "https://www.bloomberg.com/news/2026/04/27",
          source_name: "Bloomberg",
          title: "Apple to launch new product line in Q3",
        }),
      ],
      total: 1,
    });

    const { NewsTab } = await import("@/components/instrument/NewsTab");
    render(<NewsTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      // Monogram should be "BB" (curated map) — find by aria-label
      expect(screen.getByLabelText("Source: Bloomberg")).toHaveTextContent("BB");
    });
  });

  it("falls back to first 2 letters of domain stem for unknown publishers", async () => {
    mockGateway.getEntityNews.mockResolvedValue({
      articles: [
        makeArticle({
          url: "https://rare-publisher.com/article",
          source_name: "Rare Publisher",
          title: "Some headline",
        }),
      ],
      total: 1,
    });

    const { NewsTab } = await import("@/components/instrument/NewsTab");
    render(<NewsTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      // "rare-publisher" stem → "RA"
      expect(screen.getByLabelText("Source: Rare Publisher")).toHaveTextContent("RA");
    });
  });

  it("tags an article with the EARNINGS narrative chip when title mentions earnings", async () => {
    mockGateway.getEntityNews.mockResolvedValue({
      articles: [
        makeArticle({
          title: "Apple beats Q4 earnings; EPS $2.10 vs $1.95 expected",
        }),
      ],
      total: 1,
    });

    const { NewsTab } = await import("@/components/instrument/NewsTab");
    render(<NewsTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("EARNINGS")).toBeInTheDocument();
    });
  });

  it("tags an article with M&A narrative chip when title mentions acquisition", async () => {
    mockGateway.getEntityNews.mockResolvedValue({
      articles: [
        makeArticle({ title: "Microsoft to acquire Activision in $69B deal" }),
      ],
      total: 1,
    });

    const { NewsTab } = await import("@/components/instrument/NewsTab");
    render(<NewsTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("M&A")).toBeInTheDocument();
    });
  });

  it("persists source filter to sessionStorage under the news-filters key", async () => {
    mockGateway.getEntityNews.mockResolvedValue({
      articles: [
        makeArticle({ source_name: "Reuters" }),
        makeArticle({ source_name: "Bloomberg" }),
      ],
      total: 2,
    });

    const { NewsTab } = await import("@/components/instrument/NewsTab");
    const { unmount } = render(<NewsTab entityId="ent-001" />, { wrapper });

    // Wait for the source filter dropdown to populate with article sources.
    await waitFor(() => {
      const dropdown = screen.getByLabelText(
        "Filter articles by source",
      ) as HTMLSelectElement;
      expect(dropdown.querySelector('option[value="Reuters"]')).not.toBeNull();
    });

    // Change source filter to "Reuters"
    const dropdown = screen.getByLabelText(
      "Filter articles by source",
    ) as HTMLSelectElement;
    fireEvent.change(dropdown, { target: { value: "Reuters" } });

    // sessionStorage should reflect the change under the per-instrument key.
    await waitFor(() => {
      const raw = window.sessionStorage.getItem("news-filters-inst-001");
      expect(raw).not.toBeNull();
      const parsed = JSON.parse(raw ?? "{}");
      expect(parsed.sourceFilter).toBe("Reuters");
    });

    unmount();
  });

  it("rehydrates persisted filter on remount", async () => {
    // Pre-seed sessionStorage as if the user had set "Bloomberg" earlier.
    window.sessionStorage.setItem(
      "news-filters-inst-001",
      JSON.stringify({ sourceFilter: "Bloomberg", sortKey: "time" }),
    );

    mockGateway.getEntityNews.mockResolvedValue({
      articles: [
        makeArticle({ source_name: "Reuters" }),
        makeArticle({ source_name: "Bloomberg" }),
      ],
      total: 2,
    });

    const { NewsTab } = await import("@/components/instrument/NewsTab");
    render(<NewsTab entityId="ent-001" />, { wrapper });

    // The dropdown defaults should reflect the persisted value.
    await waitFor(() => {
      const dropdown = screen.getByLabelText(
        "Filter articles by source",
      ) as HTMLSelectElement;
      expect(dropdown.value).toBe("Bloomberg");
    });
  });
});

// ── IntelligenceTab — Sheet behaviour ─────────────────────────────────────────

describe("IntelligenceTab contradiction Sheet (T-E-5-04)", () => {
  it("opens a side Sheet with full Claim A + Claim B when a row is clicked", async () => {
    mockGateway.getContradictions.mockResolvedValue({
      entity_id: "ent-001",
      contradictions: [
        {
          contradiction_id: "c-001",
          severity: "HIGH" as const,
          claim_a: "Revenue growth is accelerating into Q4",
          claim_b: "Revenue is decelerating with weaker iPhone demand",
          source_a: "Reuters",
          source_b: "Bloomberg",
          detected_at: new Date().toISOString(),
        },
      ],
    });

    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    const { IntelligenceTab } = await import(
      "@/components/instrument/IntelligenceTab"
    );
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    // Wait for the row (truncated claim_a) to appear.
    await waitFor(() => {
      expect(
        screen.getByText(/Revenue growth is accelerating/),
      ).toBeInTheDocument();
    });

    // Click the row button — Sheet opens (Radix Dialog portal).
    const row = screen.getByText(/Revenue growth is accelerating/).closest("button");
    expect(row).not.toBeNull();
    if (row) await user.click(row);

    // Sheet content includes both claim labels.
    await waitFor(() => {
      expect(screen.getByText("Claim A")).toBeInTheDocument();
      expect(screen.getByText("Claim B")).toBeInTheDocument();
    });
  });
});

// ── FundamentalsTab — inline sparkline wiring ─────────────────────────────────

describe("FundamentalsTab inline sparklines (T-E-5-03)", () => {
  it("invokes the timeseries gateway for trended valuation metrics on render", async () => {
    // Provide minimal fundamentals so the component renders the metric grid.
    mockGateway.getFundamentals.mockResolvedValue({
      instrument_id: "inst-001",
      ticker: "AAPL",
      market_cap: 3_000_000_000_000,
      pe_ratio: 28,
      forward_pe: 25,
      price_to_book: 45,
      price_to_sales: 7.2,
      ev_to_ebitda: 22,
      gross_margin: 0.45,
      operating_margin: 0.30,
      net_margin: 0.25,
      roe: 0.30,
      roa: 0.20,
      revenue_growth_yoy: 0.08,
      earnings_growth_yoy: 0.10,
      dividend_yield: 0.005,
      payout_ratio: 0.15,
      debt_to_equity: 1.5,
      current_ratio: 1.0,
      quick_ratio: 0.8,
      week_52_low: 150,
      week_52_high: 200,
      daily_return: 0.012,
      updated_at: new Date().toISOString(),
    });

    // FundamentalSparkline calls getFundamentalsTimeseries — assert it gets
    // invoked with at least pe_ratio and roe (two of the metrics we wired).
    const { FundamentalsTab } = await import(
      "@/components/instrument/FundamentalsTab"
    );
    render(
      <FundamentalsTab instrumentId="inst-001" currentPrice={185} />,
      { wrapper },
    );

    await waitFor(() => {
      const calls = mockGateway.getFundamentalsTimeseries.mock.calls;
      const calledMetrics = calls.map((c: unknown[]) => c[1]);
      // We wired sparklines on: pe_ratio, price_to_book, price_to_sales,
      // ev_to_ebitda, gross_margin, operating_margin, net_margin, roe, roa,
      // revenue_growth_yoy, earnings_growth_yoy.
      // Assert two representative keys to lock the wiring.
      expect(calledMetrics).toContain("pe_ratio");
      expect(calledMetrics).toContain("roe");
    });
  });
});
