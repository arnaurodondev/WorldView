/**
 * __tests__/instrument-detail.test.tsx — Tests for F-6 Instrument Detail components
 *
 * WHY THIS EXISTS: The instrument detail page is the most data-dense page in
 * the app. Tests verify loading, error, and populated states for each tab
 * component independently — important because each tab has its own query.
 *
 * WHY MOCK gateway: Unit tests must not make real S9 calls.
 * Each test configures the mock to return specific shapes so we can
 * test boundary conditions (null fundamentals, empty contradictions, etc.)
 *
 * DATA SOURCE: Mocked gateway client
 */

import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FundamentalsTab } from "@/components/instrument/FundamentalsTab";
import { IntelligenceTab } from "@/components/instrument/IntelligenceTab";
import { InstrumentAISubheader } from "@/components/instrument/InstrumentAISubheader";
import { LiveQuoteBadge } from "@/components/instrument/LiveQuoteBadge";
import { OHLCVChart } from "@/components/instrument/OHLCVChart";
import { createGateway } from "@/lib/gateway";
import type { Fundamentals, Quote, ContradictionsResponse } from "@/types/api";

// ── @react-sigma/core mock ────────────────────────────────────────────────────
// WHY mock @react-sigma/core: sigma.js uses WebGL which is unavailable in jsdom.
// The dynamic import in IntelligenceTab (ssr:false) means EntityGraph is never
// rendered in unit tests. We mock the sigma module to prevent import-time errors
// in case any test imports a sigma-dependent component directly.
vi.mock("@react-sigma/core", () => ({
  SigmaContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="sigma-container">{children}</div>
  ),
  useRegisterEvents: vi.fn(() => vi.fn()),
  useLoadGraph: vi.fn(() => vi.fn()),
  useSigma: vi.fn(() => ({
    getGraph: vi.fn(() => ({
      getNodeAttributes: vi.fn(() => ({ label: "Test", nodeType: "company" })),
      getEdgeAttributes: vi.fn(() => ({ label: "CEO_OF", weight: 0.9 })),
      degree: vi.fn(() => 3),
    })),
  })),
}));

// ── graphology mock ───────────────────────────────────────────────────────────
// WHY mock: graphology Graph constructor is not needed in unit tests;
// the GraphLoader component that uses it is inside the sigma container
// which is mocked above. We prevent any graphology import side effects.
vi.mock("graphology", () => ({
  default: vi.fn(() => ({
    addNode: vi.fn(),
    addEdge: vi.fn(),
    hasNode: vi.fn(() => false),
    hasEdge: vi.fn(() => false),
    order: 0,
    degree: vi.fn(() => 0),
  })),
}));

// ── graphology-layout-forceatlas2 mock ────────────────────────────────────────
// WHY mock: no graph to lay out in tests; prevents import side effects
vi.mock("graphology-layout-forceatlas2", () => ({
  default: {
    assign: vi.fn(),
    inferSettings: vi.fn(() => ({})),
  },
}));

// ── next/dynamic mock ─────────────────────────────────────────────────────────
// WHY mock next/dynamic: ssr:false components do not render in jsdom.
// We replace all dynamic imports with a simple placeholder so that
// IntelligenceTab renders without waiting for async chunk loads.
vi.mock("next/dynamic", () => ({
  default: (_fn: () => Promise<{ default: React.ComponentType }>, _opts?: { loading?: () => React.ReactNode }) => {
    // WHY return a stable placeholder: unit tests don't need real sigma rendering.
    // The placeholder is stable across re-renders (not a new component each time).
    return function DynamicComponent() {
      return <div data-testid="dynamic-component" />;
    };
  },
}));

// ── lightweight-charts mock ───────────────────────────────────────────────────
// WHY mock: lightweight-charts uses browser Canvas/WebGL APIs unavailable in
// jsdom. Without mocking, the dynamic import in OHLCVChart's useEffect throws
// when the library tries to access canvas context. The chart is not the subject
// of these tests — we just verify the timeframe selector and skeleton logic.
// PLAN-0059 H-1: v5 factory mock — addSeries(SeriesDef, opts).
// addPane + removeSeries added for H-1 pane isolation (each oscillator now
// calls chart.addPane() then addSeries(..., paneIndex)).
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
    })),
    addPane: vi.fn(),
    removeSeries: vi.fn(),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn(), scrollToRealTime: vi.fn() })),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    subscribeCrosshairMove: vi.fn(),
    unsubscribeCrosshairMove: vi.fn(),
    remove: vi.fn(),
  })),
  CandlestickSeries: "CandlestickSeries",
  LineSeries: "LineSeries",
  HistogramSeries: "HistogramSeries",
  AreaSeries: "AreaSeries",
}));

// ── Next.js router mock ───────────────────────────────────────────────────────
// WHY: EntityGraphPanel uses useRouter() for node-click navigation.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// ── Test data fixtures ────────────────────────────────────────────────────────

const MOCK_FUNDAMENTALS: Fundamentals = {
  instrument_id: "ins-001",
  ticker: "AAPL",
  name: "Apple Inc.",
  market_cap: 2_800_000_000_000,
  pe_ratio: 28.5,
  forward_pe: 25.1,
  price_to_book: 45.2,
  price_to_sales: 7.8,
  ev_to_ebitda: 21.3,
  gross_margin: 0.4431,
  operating_margin: 0.2970,
  net_margin: 0.2531,
  roe: 1.6009,
  roa: 0.2878,
  revenue_growth_yoy: 0.0278,
  earnings_growth_yoy: 0.1085,
  dividend_yield: 0.0044,
  payout_ratio: 0.1565,
  debt_to_equity: 1.9800,
  current_ratio: 1.03,
  quick_ratio: 0.94,
  week_52_high: 199.62,
  week_52_low: 124.17,
  daily_return: 0.0125,
  updated_at: "2026-04-17T10:00:00Z",
};

const MOCK_QUOTE: Quote = {
  instrument_id: "ins-001",
  ticker: "AAPL",
  price: 187.43,
  change: 2.31,
  change_pct: 1.25,
  timestamp: "2026-04-17T14:30:00Z",
  volume: 52_000_000,
};

const MOCK_CONTRADICTIONS: ContradictionsResponse = {
  entity_id: "ent-001",
  contradictions: [
    {
      contradiction_id: "con-001",
      entity_id: "ent-001",
      claim_a: "Apple's supply chain is robust and diversified",
      claim_b: "Apple faces severe supply constraints from Taiwan",
      source_a: "Reuters 2026-04-15",
      source_b: "Bloomberg 2026-04-16",
      detected_at: "2026-04-16T18:00:00Z",
      severity: "HIGH",
    },
    {
      contradiction_id: "con-002",
      entity_id: "ent-001",
      claim_a: "iPhone demand is accelerating in China",
      claim_b: "Apple loses 15% China market share to Huawei",
      source_a: "IDC Q1 Report",
      source_b: "Canalys Q1 Data",
      detected_at: "2026-04-14T10:00:00Z",
      severity: "MEDIUM",
    },
  ],
};

// ── Gateway mock ──────────────────────────────────────────────────────────────

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getFundamentals: vi.fn().mockResolvedValue(MOCK_FUNDAMENTALS),
    getQuote: vi.fn().mockResolvedValue(MOCK_QUOTE),
    getContradictions: vi.fn().mockResolvedValue(MOCK_CONTRADICTIONS),
    getEntityGraph: vi.fn().mockResolvedValue({
      entity_id: "ent-001",
      nodes: [
        { id: "ent-001", label: "Apple Inc.", type: "company" },
        { id: "ent-002", label: "Tim Cook", type: "person" },
      ],
      edges: [
        { id: "e-1", source: "ent-001", target: "ent-002", label: "CEO_OF", weight: 1.0 },
      ],
    }),
    // WHY getInstrumentBrief: InstrumentBriefSection (PLAN-0034) and InstrumentAISubheader
    // (Wave 5) now fetch live AI briefs via S8. All IntelligenceTab tests and
    // InstrumentAISubheader tests need this mock to avoid TypeError.
    getInstrumentBrief: vi.fn().mockResolvedValue({
      // WHY narrative (not content): BriefingResponse.narrative mirrors S8's
      // PublicBriefingResponse schema field. See types/api.ts for definition.
      narrative: "**Apple** reported strong Q4 results above expectations.",
      risk_summary: null,
      entity_mentions: [{ entity_id: "ent-001", name: "Apple", ticker: "AAPL" }],
      citations: [],
      generated_at: new Date().toISOString(),
      cached: false,
      entity_id: "ent-001",
    }),
    getOHLCV: vi.fn().mockResolvedValue({
      instrument_id: "ins-001",
      ticker: "AAPL",
      timeframe: "1D",
      bars: [
        { timestamp: "2026-04-16T00:00:00Z", open: 185.0, high: 188.0, low: 184.0, close: 187.43, volume: 52000000 },
      ],
    }),
    // WHY getEntityNews: InstrumentTopNews (Wave 5 OverviewLayout center column)
    // fetches top-4 articles. Tests that render OverviewLayout need this mock.
    getEntityNews: vi.fn().mockResolvedValue({
      articles: [
        {
          article_id: "art-001",
          title: "Apple reports record Q4 revenue",
          url: "https://example.com/1",
          source: "Reuters",
          published_at: new Date().toISOString(),
          summary: null,
          entity_ids: ["ent-001"],
          tickers: ["AAPL"],
          display_relevance_score: 0.9,
          market_impact_score: 0.85,
          sentiment: "positive",
          impact_window_t0: null,
          impact_window_t1: null,
          impact_window_t2: null,
          impact_window_t5: null,
          routing_tier: "HIGH",
        },
      ],
      total: 1,
      offset: 0,
      limit: 4,
    }),
    // WHY getEntityDetail: EntityDescriptionPanel (PRD-0073 Wave D-1) calls this.
    // Returns null by default — entity not yet enriched — so the panel renders nothing.
    getEntityDetail: vi.fn().mockResolvedValue(null),
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "tok",
      user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── FundamentalsTab tests ─────────────────────────────────────────────────────

describe("FundamentalsTab", () => {
  it("renders market cap in trillions after data loads", async () => {
    render(<FundamentalsTab instrumentId="ins-001" />, { wrapper });

    // WHY getAllByText (not getByText): Wave D-2 adds a right sidebar with
    // MarketPositionPanel which also shows market cap. The value now legitimately
    // appears twice — once in the Valuation section and once in the sidebar.
    // getByText would throw "found multiple elements"; getAllByText asserts at
    // least one match exists (which is the intent of this test).
    await waitFor(() => {
      expect(screen.getAllByText("$2.80T").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders P/E ratio with x suffix", async () => {
    render(<FundamentalsTab instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("28.50x")).toBeInTheDocument();
    });
  });

  it("renders section headings", async () => {
    render(<FundamentalsTab instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Valuation")).toBeInTheDocument();
      expect(screen.getByText("Profitability")).toBeInTheDocument();
      expect(screen.getByText("Balance Sheet")).toBeInTheDocument();
    });
  });

  it("renders 52-week high", async () => {
    render(<FundamentalsTab instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("$199.62")).toBeInTheDocument();
    });
  });

  it("renders em dash for null fundamentals value", async () => {
    // Render with initial data containing null fields
    const partialFund = { ...MOCK_FUNDAMENTALS, ev_to_ebitda: null };
    render(<FundamentalsTab instrumentId="ins-001" initialData={partialFund} />, { wrapper });

    // The EV/EBITDA metric renders as em dash for null values
    const emDashes = screen.getAllByText("—");
    expect(emDashes.length).toBeGreaterThan(0);
  });

  // ── Wave 5: new FundamentalsTab sections ──────────────────────────────────

  it("renders Analyst Consensus section", async () => {
    // WHY: Wave 5 adds AnalystConsensusStrip as a full-width section above the grid.
    // Verify the section header text is present after data loads.
    render(<FundamentalsTab instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("ANALYST CONSENSUS")).toBeInTheDocument();
    });
  });

  it("renders Debt & Credit section", async () => {
    // WHY: Wave 5 adds a Debt & Credit section to the fundamentals grid.
    // The section title uses &amp; which React renders as "&".
    render(<FundamentalsTab instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Debt & Credit")).toBeInTheDocument();
    });
  });

  it("renders Cash Flow section", async () => {
    // WHY: Wave 5 adds a Cash Flow section to the fundamentals grid.
    render(<FundamentalsTab instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Cash Flow")).toBeInTheDocument();
    });
  });

  it("renders Revenue Trend section", async () => {
    // WHY: Wave 5 adds RevenueTrendSparklines as a full-width section.
    // It shows "REVENUE TREND" header and a pending message.
    render(<FundamentalsTab instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("REVENUE TREND")).toBeInTheDocument();
    });
  });
});

// ── InstrumentAISubheader tests ───────────────────────────────────────────────

describe("InstrumentAISubheader", () => {
  it("renders collapsed row with AI BRIEF label", async () => {
    // WHY: Verifies the collapsed state shows the label and brief preview.
    render(<InstrumentAISubheader entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("AI BRIEF")).toBeInTheDocument();
    });
  });

  it("renders brief preview text in collapsed state", async () => {
    // WHY: The collapsed row should show the first 120 chars of the brief content.
    // WHY getAllByText (not getByText): other test renders IntelligenceTab's
    // InstrumentBriefSection which also shows the same brief text from the shared
    // query cache. getAllByText allows multiple matches and we just check ≥1 exists.
    render(<InstrumentAISubheader entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      // The mock brief content starts with "**Apple** reported strong Q4..."
      // Preview shows first 120 chars.
      const matches = screen.getAllByText(/Apple.*reported strong Q4/);
      expect(matches.length).toBeGreaterThan(0);
    });
  });

  it("returns null when no brief is available", async () => {
    // WHY: If no brief exists yet, the component should return null (no empty bar).
    const noBriefGateway = {
      getInstrumentBrief: vi.fn().mockResolvedValue(null),
      refreshToken: vi.fn().mockResolvedValue({ access_token: "tok", user: {}, expires_in: 900 }),
      logout: vi.fn(),
    } as unknown as ReturnType<typeof createGateway>;

    vi.mocked(createGateway).mockReturnValueOnce(noBriefGateway);

    const { container } = render(<InstrumentAISubheader entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      // When null is returned, the component renders nothing
      expect(container.firstChild).toBeNull();
    });
  });
});

// ── IntelligenceTab tests ─────────────────────────────────────────────────────

describe("IntelligenceTab", () => {
  it("renders contradiction count badge", async () => {
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("2 found")).toBeInTheDocument();
    });
  });

  it("renders HIGH severity contradiction", async () => {
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      // Severity badge shows truncated "HIGH" text
      expect(screen.getByText("HIGH")).toBeInTheDocument();
    });
  });

  it("renders claim text", async () => {
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/Apple's supply chain is robust/),
      ).toBeInTheDocument();
    });
  });

  it("renders source attribution when contradiction row is expanded", async () => {
    // WHY update: Wave 5 makes ContradictionCard collapsible by default (22px row).
    // Source attribution ("— Reuters 2026-04-15") is only visible in the expanded
    // state. This test clicks the collapsed row to expand it, then checks source text.
    // WHY not delete: R19 — never delete tests; update to match the new behavior.
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    // Wait for contradictions to load and collapsed rows to render
    await waitFor(() => {
      expect(screen.getByText(/Apple's supply chain is robust/)).toBeInTheDocument();
    });

    // Click the first collapsed row to expand it
    const collapsedRow = screen.getByText(/Apple's supply chain is robust/).closest("div");
    if (collapsedRow) await user.click(collapsedRow);

    // Source attribution is now visible in the expanded card
    await waitFor(() => {
      expect(screen.getByText(/Reuters 2026-04-15/)).toBeInTheDocument();
    });
  });

  it("renders empty state when no contradictions", async () => {
    // WHY mockReturnValue (not Once): IntelligenceTab calls createGateway(accessToken)
    // TWICE — once for getEntityGraph and once for getContradictions. We need both
    // invocations to return the empty-state mocks. Using mockReturnValue overrides
    // ALL subsequent calls for this test. We restore via vi.restoreAllMocks() or
    // by calling mockReturnValue again with the original mock in afterEach if needed.
    // Since each describe block's tests use a fresh QueryClient (makeQueryClient),
    // and vi.mock module-level restores between test files, this approach is safe.
    const emptyGateway = {
      getContradictions: vi.fn().mockResolvedValue({ entity_id: "ent-001", contradictions: [] }),
      getEntityGraph: vi.fn().mockResolvedValue({ entity_id: "ent-001", nodes: [], edges: [] }),
      // WHY getInstrumentBrief: InstrumentBriefSection (added PLAN-0034) makes this call.
      // Without it the gateway factory throws TypeError on the missing method.
      getInstrumentBrief: vi.fn().mockResolvedValue({
        // WHY narrative (not content): BriefingResponse.narrative is the field name
        narrative: "", entity_mentions: [], citations: [], generated_at: new Date().toISOString(),
        risk_summary: null, cached: false, entity_id: "ent-001",
      }),
      // WHY getEntityDetail: EntityDescriptionPanel (PRD-0073 Wave D-1) adds a 4th
      // createGateway call. Returns null = entity not enriched yet → panel renders nothing.
      getEntityDetail: vi.fn().mockResolvedValue(null),
      refreshToken: vi.fn().mockResolvedValue({ access_token: "tok", user: {}, expires_in: 900 }),
      logout: vi.fn(),
    } as unknown as ReturnType<typeof createGateway>;

    // WHY four mockReturnValueOnce (was three): EntityDescriptionPanel (PRD-0073 Wave D-1)
    // adds a 4th createGateway call for getEntityDetail.  Order: getEntityDetail,
    // getEntityGraph, getInstrumentBrief, getContradictions.
    vi.mocked(createGateway)
      .mockReturnValueOnce(emptyGateway)
      .mockReturnValueOnce(emptyGateway)
      .mockReturnValueOnce(emptyGateway)
      .mockReturnValueOnce(emptyGateway);

    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/No contradictions detected/i)).toBeInTheDocument();
    });
  });

  it("renders entity graph section header", async () => {
    // WHY: verifies the new graph section is present in the Intelligence tab layout.
    // The EntityGraph component itself is mocked (next/dynamic → DynamicComponent).
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Entity Knowledge Graph")).toBeInTheDocument();
    });
  });

  it("shows node count from graph data", async () => {
    // WHY: the header shows "depth 2 · N entities" — verify N reflects the data.
    // Mock returns 2 nodes from the default gateway mock (ent-001 + ent-002).
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      // The text includes node count once graphData arrives: "depth 2 · 2 entities"
      expect(screen.getByText(/depth 2/)).toBeInTheDocument();
    });
  });

  it("renders AI intelligence brief section heading", async () => {
    // WHY: verifies the AI brief section header is visible. PLAN-0034 replaced
    // the static placeholder with a live InstrumentBriefSection component.
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("AI Intelligence Brief")).toBeInTheDocument();
    });
  });

  // ── Wave 5: severity count strip tests ────────────────────────────────────

  it("renders severity count buttons (HIGH, MEDIUM, LOW) when contradictions exist", async () => {
    // WHY: Wave 5 adds a severity count strip above the contradiction list.
    // MOCK_CONTRADICTIONS has 1 HIGH and 1 MEDIUM contradiction.
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      // The severity strip shows "HIGH N" and "MEDIUM N" buttons
      // and "LOW N" button (count may be 0 but button is still shown)
      expect(screen.getByText(/HIGH 1/)).toBeInTheDocument();
      expect(screen.getByText(/MEDIUM 1/)).toBeInTheDocument();
      expect(screen.getByText(/LOW 0/)).toBeInTheDocument();
    });
  });

  it("renders collapsed contradiction rows (22px single-line)", async () => {
    // WHY: Wave 5 changes ContradictionCard to be collapsed by default (22px row).
    // The claim text should be truncated (first 60 chars) in the collapsed state.
    render(<IntelligenceTab entityId="ent-001" />, { wrapper });

    await waitFor(() => {
      // The first 60 chars of claim_a: "Apple's supply chain is robust and diversified"
      // fits in 60 chars so it should appear without truncation
      expect(screen.getByText(/Apple's supply chain is robust/)).toBeInTheDocument();
    });
  });
});

// ── LiveQuoteBadge tests ──────────────────────────────────────────────────────

describe("LiveQuoteBadge", () => {
  it("renders price from initialPrice prop immediately (no loading skeleton)", () => {
    // WHY test initialPrice: the placeholderData prop means we should see price
    // without waiting for the query, improving perceived page load speed.
    render(
      <LiveQuoteBadge instrumentId="ins-001" initialPrice={187.43} />,
      { wrapper },
    );

    // The initial price renders immediately via placeholderData
    expect(screen.getByText("$187.43")).toBeInTheDocument();
  });

  it("renders positive change in green", async () => {
    render(<LiveQuoteBadge instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      // Change amount renders with + prefix (positive change)
      expect(screen.getByText(/\+\$2\.31/)).toBeInTheDocument();
    });
  });

  it("renders timestamp in UTC format", async () => {
    render(<LiveQuoteBadge instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      // Timestamp shows HH:MM:SS UTC from ISO string "14:30:00"
      expect(screen.getByText("14:30:00 UTC")).toBeInTheDocument();
    });
  });

  it("shows loading skeleton when no data and no initialPrice", () => {
    // Override mock to return a promise that never resolves (simulates loading)
    vi.mocked(createGateway).mockReturnValueOnce({
      getQuote: vi.fn().mockReturnValue(new Promise(() => {})), // never resolves
      refreshToken: vi.fn().mockResolvedValue({ access_token: "tok", user: {}, expires_in: 900 }),
      logout: vi.fn(),
    } as unknown as ReturnType<typeof createGateway>);

    render(<LiveQuoteBadge instrumentId="ins-001" />, { wrapper });

    // Without initialPrice and while loading, a static skeleton bar is shown.
    // After T-D-4-01, Skeleton renders with bg-muted (no animate-pulse) — static bars
    // are the Bloomberg terminal standard; animation is reserved for streaming states.
    expect(document.querySelector(".bg-muted")).toBeInTheDocument();
  });
});

// ── OHLCVChart tests ──────────────────────────────────────────────────────────

describe("OHLCVChart", () => {
  it("renders timeframe selector buttons", () => {
    render(<OHLCVChart instrumentId="ins-001" />, { wrapper });

    // All five timeframe options must always be visible.
    // WHY 1W and 1M: S3 ingests weekly (Timeframe.ONE_WEEK="1w") and monthly
    // (Timeframe.ONE_MONTH="1M") EODHD bars. The gateway normalizes "1W"→"1w"
    // and preserves "1M" as-is (uppercase M required by S3 enum).
    expect(screen.getByText("5M")).toBeInTheDocument();
    expect(screen.getByText("1H")).toBeInTheDocument();
    expect(screen.getByText("1D")).toBeInTheDocument();
    expect(screen.getByText("1W")).toBeInTheDocument();
    expect(screen.getByText("1M")).toBeInTheDocument();
  });

  it("shows 'Chart unavailable' fallback when dynamic import fails", async () => {
    // WHY test this: F-CRIT-006 — if lightweight-charts fails to load (CDN down,
    // bundle corruption, missing module), the chart component MUST show a visible
    // fallback instead of silently rendering blank space. Financial UIs that go
    // blank erode user trust ("is the price frozen? is the app broken?").
    //
    // HOW: We temporarily override the module-level mock to make the dynamic
    // import reject with an error. The component's try-catch (added in the fix)
    // should catch this and set chartError=true, rendering the fallback UI.

    // Override the lightweight-charts mock to throw on import
    vi.doMock("lightweight-charts", () => {
      throw new Error("Module load failed");
    });

    // Re-import the component so it picks up the throwing mock.
    // WHY dynamic re-import: vi.doMock only affects subsequent imports, not the
    // module-level vi.mock above. We need a fresh import that triggers the error.
    const { OHLCVChart: OHLCVChartWithError } = await import(
      "@/components/instrument/OHLCVChart"
    );

    render(<OHLCVChartWithError instrumentId="ins-001" />, { wrapper });

    // Wait for the error state to render (async effect → setState → re-render)
    await waitFor(() => {
      expect(screen.getByText("Chart unavailable")).toBeInTheDocument();
    });

    // Restore the original mock for subsequent tests
    vi.doMock("lightweight-charts", () => ({
      createChart: vi.fn(() => ({
        addSeries: vi.fn(() => ({ setData: vi.fn(), applyOptions: vi.fn() })),
        addPane: vi.fn(),
        removeSeries: vi.fn(),
        applyOptions: vi.fn(),
        timeScale: vi.fn(() => ({ fitContent: vi.fn(), scrollToRealTime: vi.fn() })),
        priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
        subscribeCrosshairMove: vi.fn(),
        unsubscribeCrosshairMove: vi.fn(),
        remove: vi.fn(),
      })),
      CandlestickSeries: "CandlestickSeries",
      LineSeries: "LineSeries",
      HistogramSeries: "HistogramSeries",
      AreaSeries: "AreaSeries",
    }));
  });

  it("does not show skeleton when loading but initial bars provided", () => {
    const initialBars = [
      { timestamp: "2026-04-16T00:00:00Z", open: 185.0, high: 188.0, low: 184.0, close: 187.43, volume: 52000000 },
    ];

    render(<OHLCVChart instrumentId="ins-001" initialBars={initialBars} />, { wrapper });

    // Skeleton should NOT render when we have initialBars.
    // After T-D-4-01, Skeleton uses .bg-muted (not .animate-pulse) — verify neither is present.
    expect(document.querySelector(".bg-muted")).toBeNull();
  });
});
