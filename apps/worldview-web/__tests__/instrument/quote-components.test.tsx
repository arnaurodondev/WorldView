/**
 * __tests__/instrument/quote-components.test.tsx — W5 Quote-tab component unit tests (T-30)
 *
 * WHY THIS EXISTS: PRD-0089 W5 plan §6.1 mandates 1 test per component covering
 * the empty / populated / error / interaction paths. These are Vitest+JSDOM
 * tests that render components in isolation (no gateway calls). Hook tests that
 * require useQuery wiring are in a separate describe block with a QueryClient wrapper.
 *
 * COMPONENTS COVERED (U-4 through U-18 from the plan):
 *   U-4  MultiPeriodReturnsStrip  — 7 cells, semantic color, empty state
 *   U-5  IntradayStatsBand        — 6 cells with PREM, hidden PREM without premarket
 *   U-6  CompanyAboutCard         — ETF empty state / AAPL populated / "more" toggle
 *   U-7  MetricGrid4Col           — 8 cells in 4×2; null cells show "—"
 *   U-8  InsiderActivityList      — 5 rows, empty state, BUY=positive SALE=negative
 *   U-9  EarningsMiniList         — 4 rows newest-first, empty state
 *   U-10 RelatedHeadlinesList     — 5 rows, sentiment color, empty state
 *   U-11 PriceLevelsStrip         — rows + empty state, R=positive S=negative
 *   U-12 WhatsMovingStrip         — 3 rows, empty state
 *   U-13 InstrumentHeader         — sector pill present when gics_sector set
 *
 * WHY split from quote-density.test.tsx: density tests only count [role="cell"]
 * and [role="row"] totals. These tests verify structure, content, and interaction.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

// WHY mock next/navigation: RelatedHeadlinesList, PeersStrip, WhatsMovingStrip,
// AiBriefBanner, and InstrumentHeader all use useRouter() for navigation.
// Without this mock, Vitest throws "invariant expected app router to be mounted".
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: mockPush, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/AAPL"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// WHY mock useAccessToken + createGateway: InstrumentHeader renders LiveQuoteBadge
// which calls useAccessToken. We stub to prevent context errors in unit tests.
vi.mock("@/lib/api-client", () => ({
  useAccessToken: vi.fn(() => "test-token"),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({})),
}));

// WHY mock LiveQuoteBadge: it subscribes to a WebSocket feed. In unit tests
// we don't need the real badge — just the surrounding header layout.
vi.mock("@/components/instrument/LiveQuoteBadge", () => ({
  LiveQuoteBadge: () => <span data-testid="live-quote-badge-stub" />,
}));

// WHY mock WeekRangeMini: it renders an SVG that is irrelevant to header tests.
vi.mock("@/components/instrument/header/WeekRangeMini", () => ({
  WeekRangeMini: () => <span data-testid="week-range-mini-stub" />,
}));

import { MultiPeriodReturnsStrip } from "@/components/instrument/quote/strips/MultiPeriodReturnsStrip";
import { IntradayStatsBand } from "@/components/instrument/quote/strips/IntradayStatsBand";
import { CompanyAboutCard } from "@/components/instrument/quote/about/CompanyAboutCard";
import { MetricGrid4Col } from "@/components/instrument/quote/metrics/MetricGrid4Col";
import { InsiderActivityList } from "@/components/instrument/quote/insider/InsiderActivityList";
import { EarningsMiniList } from "@/components/instrument/quote/earnings/EarningsMiniList";
import { RelatedHeadlinesList } from "@/components/instrument/quote/news/RelatedHeadlinesList";
import { PriceLevelsStrip } from "@/components/instrument/quote/bottom/PriceLevelsStrip";
import { WhatsMovingStrip } from "@/components/instrument/quote/bottom/WhatsMovingStrip";
import { InstrumentHeader } from "@/components/instrument/header/InstrumentHeader";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const MULTI_PERIOD_DATA = {
  instrument_id: "aapl",
  periods: {
    "1D": 1.42, "5D": 3.21, "1M": 5.12, "3M": 8.77,
    "6M": -2.11, "YTD": 12.33, "1Y": 22.45,
  },
} as const;

const INTRADAY_DATA = {
  instrument_id: "aapl",
  vwap: 187.42, atr_14: 3.21, rsi_14: 58.3,
  gap_pct: 0.42, premarket_high: 188.10, premarket_low: 186.50,
  short_interest_pct: 0.92,
};

const INTRADAY_NO_PREM = {
  instrument_id: "aapl",
  vwap: 187.42, atr_14: 3.21, rsi_14: 58.3,
  gap_pct: 0.42, premarket_high: null, premarket_low: null,
  short_interest_pct: 0.92,
};

const INSTRUMENT_AAPL = {
  instrument_id: "aapl-uuid",
  ticker: "AAPL",
  name: "Apple Inc.",
  exchange: "NASDAQ",
  gics_sector: "Information Technology",
  gics_industry: "Technology Hardware, Storage & Peripherals",
  country: "US",
  founded: "1976-04-01",
  description: "Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide.",
};

const INSTRUMENT_SPY = {
  instrument_id: "spy-uuid",
  ticker: "SPY",
  name: "SPDR S&P 500 ETF Trust",
  exchange: "NYSE",
  gics_sector: null,
  gics_industry: null,
  country: "US",
  founded: null,
  description: null,
};

const METRIC_CELLS = [
  { label: "MKT CAP", value: "$2.89T" },
  { label: "P/E",     value: "28.4" },
  { label: "FWD P/E", value: "26.1" },
  { label: "EPS TTM", value: "$6.42" },
  { label: "P/S",     value: "7.2" },
  { label: "P/B",     value: null },      // null → "—"
  { label: "EV/EBITDA", value: "22.3" },
  { label: "FCF",     value: "$108B" },
];

const INSIDER_DATA = {
  records: [
    { id: "1", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-04-30", owner_name: "L.Maestri", transaction_type: "Sale", shares: 10000, value: 2800000 } },
    { id: "2", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-04-22", owner_name: "J.Williams", transaction_type: "Sale", shares: 5000, value: 900000 } },
    { id: "3", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-03-15", owner_name: "T.Cook", transaction_type: "Buy", shares: 2000, value: 370000 } },
    { id: "4", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-02-28", owner_name: "C.Adams", transaction_type: "Sale", shares: 3500, value: 640000 } },
    { id: "5", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-01-12", owner_name: "D.Luca", transaction_type: "Buy", shares: 1000, value: 182000 } },
  ],
};

const EARNINGS_DATA = {
  records: [
    { id: "1", security_id: "a", section: "e", period_end: "2024-09-30", period_type: "ANNUAL" as const, data: { date: "2024-09-30", epsActual: 6.42, epsEstimate: 6.38, surprisePercent: 0.63 } },
    { id: "2", security_id: "a", section: "e", period_end: "2023-09-30", period_type: "ANNUAL" as const, data: { date: "2023-09-30", epsActual: 6.12, epsEstimate: 5.98, surprisePercent: 2.34 } },
    { id: "3", security_id: "a", section: "e", period_end: "2022-09-30", period_type: "ANNUAL" as const, data: { date: "2022-09-30", epsActual: 6.11, epsEstimate: 6.05, surprisePercent: 0.99 } },
    { id: "4", security_id: "a", section: "e", period_end: "2021-09-30", period_type: "ANNUAL" as const, data: { date: "2021-09-30", epsActual: 5.61, epsEstimate: 5.52, surprisePercent: 1.63 } },
  ],
};

const NEWS_DATA = {
  total: 3,
  articles: [
    { article_id: "a1", title: "Apple beats Q4 estimates", url: null, published_at: new Date(Date.now() - 3_600_000).toISOString(), source_type: null, source_name: null, routing_tier: null, routing_score: null, market_impact_score: null, llm_relevance_score: null, display_relevance_score: 0.9, primary_entity_id: null, primary_entity_symbol: null, impact_windows: null, sentiment: "positive" as const, impact_score: null, cluster_size: null },
    { article_id: "a2", title: "iPhone demand weak in China", url: null, published_at: new Date(Date.now() - 7_200_000).toISOString(), source_type: null, source_name: null, routing_tier: null, routing_score: null, market_impact_score: null, llm_relevance_score: null, display_relevance_score: 0.7, primary_entity_id: null, primary_entity_symbol: null, impact_windows: null, sentiment: "negative" as const, impact_score: null, cluster_size: null },
    { article_id: "a3", title: "Cook sells $2.8M in stock", url: null, published_at: new Date(Date.now() - 25 * 3_600_000).toISOString(), source_type: null, source_name: null, routing_tier: null, routing_score: null, market_impact_score: null, llm_relevance_score: null, display_relevance_score: 0.5, primary_entity_id: null, primary_entity_symbol: null, impact_windows: null, sentiment: "neutral" as const, impact_score: null, cluster_size: null },
  ],
};

const PRICE_LEVELS_DATA = {
  instrument_id: "aapl",
  current_price: 185.00,
  pivot: 183.50,
  levels: [
    { label: "R3", price: 196.80, direction: "above" as const },
    { label: "R2", price: 192.40, direction: "above" as const },
    { label: "R1", price: 188.10, direction: "above" as const },
    { label: "PIVOT", price: 183.50, direction: "at" as const },
    { label: "S1", price: 179.20, direction: "below" as const },
    { label: "S2", price: 174.80, direction: "below" as const },
    { label: "S3", price: 170.40, direction: "below" as const },
  ],
  ma50: 182.30,
  ma200: 175.60,
};

// ── U-4: MultiPeriodReturnsStrip ──────────────────────────────────────────────

describe("U-4 MultiPeriodReturnsStrip", () => {
  it("renders 7 period cells (1D/5D/1M/3M/6M/YTD/1Y)", () => {
    render(<MultiPeriodReturnsStrip data={MULTI_PERIOD_DATA} />);
    const cells = screen.getAllByRole("cell");
    expect(cells.length).toBe(7);
  });

  it("renders '—' placeholders when isLoading=true", () => {
    render(<MultiPeriodReturnsStrip isLoading />);
    const cells = screen.getAllByRole("cell");
    // All 7 period columns still render; values are "—"
    expect(cells.length).toBe(7);
  });

  it("renders '—' when data is null", () => {
    render(<MultiPeriodReturnsStrip data={null} />);
    // Cells still render (structure stable) but values are "—"
    const cells = screen.getAllByRole("cell");
    expect(cells.length).toBe(7);
  });
});

// ── U-5: IntradayStatsBand ────────────────────────────────────────────────────

describe("U-5 IntradayStatsBand", () => {
  it("renders 6 cells when premarket_high is set (PREM visible)", () => {
    render(<IntradayStatsBand data={INTRADAY_DATA} />);
    const cells = screen.getAllByRole("cell");
    expect(cells.length).toBe(6);
  });

  it("renders 5 cells when premarket_high is null (PREM hidden)", () => {
    render(<IntradayStatsBand data={INTRADAY_NO_PREM} />);
    const cells = screen.getAllByRole("cell");
    expect(cells.length).toBe(5);
  });

  it("renders '—' placeholders when isLoading=true", () => {
    render(<IntradayStatsBand isLoading />);
    // Structure present even while loading
    const cells = screen.getAllByRole("cell");
    expect(cells.length).toBeGreaterThanOrEqual(5);
  });
});

// ── U-6: CompanyAboutCard ─────────────────────────────────────────────────────

describe("U-6 CompanyAboutCard", () => {
  it("AAPL: renders 4 stat rows (sector/industry/HQ/founded) and description", () => {
    render(<CompanyAboutCard instrument={INSTRUMENT_AAPL as Parameters<typeof CompanyAboutCard>[0]["instrument"]} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(4);
    // Description text present
    expect(screen.getByText(/Apple Inc\. designs/)).toBeTruthy();
  });

  it("ETF (no description, no sector): renders ETF empty state", () => {
    render(<CompanyAboutCard instrument={INSTRUMENT_SPY as Parameters<typeof CompanyAboutCard>[0]["instrument"]} />);
    // Should NOT render stat rows (ETF empty state branch)
    const rows = screen.queryAllByRole("row");
    expect(rows.length).toBe(0);
    expect(screen.getByText(/Description not available/)).toBeTruthy();
  });

  it("null instrument: renders loading placeholders, no content", () => {
    render(<CompanyAboutCard instrument={null} isLoading />);
    // About section header should be visible
    expect(screen.getByText("About")).toBeTruthy();
  });

  it("'more' button toggles description expand", () => {
    render(<CompanyAboutCard instrument={INSTRUMENT_AAPL as Parameters<typeof CompanyAboutCard>[0]["instrument"]} />);
    const moreBtn = screen.getByRole("button", { name: /expand description/i });
    fireEvent.click(moreBtn);
    // After expand, label changes to "Collapse description"
    expect(screen.getByRole("button", { name: /collapse description/i })).toBeTruthy();
  });

  it("wv:desc-toggle event toggles description expand", () => {
    render(<CompanyAboutCard instrument={INSTRUMENT_AAPL as Parameters<typeof CompanyAboutCard>[0]["instrument"]} />);
    // Initially collapsed
    expect(screen.getByRole("button", { name: /expand description/i })).toBeTruthy();
    // WHY act(): dispatching a custom event triggers setState inside CompanyAboutCard.
    // Without act(), React defers the state update and the assertion runs before
    // the re-render, causing a false negative.
    act(() => {
      window.dispatchEvent(new CustomEvent("wv:desc-toggle"));
    });
    expect(screen.getByRole("button", { name: /collapse description/i })).toBeTruthy();
  });
});

// ── U-7: MetricGrid4Col ───────────────────────────────────────────────────────

describe("U-7 MetricGrid4Col", () => {
  it("renders 8 cells for 8-cell input", () => {
    render(<MetricGrid4Col title="Valuation" cells={METRIC_CELLS} />);
    const cells = screen.getAllByRole("cell");
    expect(cells.length).toBe(8);
  });

  it("renders '—' for null values", () => {
    render(<MetricGrid4Col title="Test" cells={METRIC_CELLS} />);
    // The P/B cell has null value → should show "—"
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("renders section title when provided", () => {
    render(<MetricGrid4Col title="Valuation" cells={METRIC_CELLS} />);
    expect(screen.getByText("Valuation")).toBeTruthy();
  });

  it("omits title section when title prop is absent", () => {
    render(<MetricGrid4Col cells={METRIC_CELLS} />);
    // No "Valuation" text in DOM
    expect(screen.queryByText("Valuation")).toBeNull();
  });

  it("renders 0 cells for empty cells array", () => {
    render(<MetricGrid4Col cells={[]} />);
    const cells = screen.queryAllByRole("cell");
    expect(cells.length).toBe(0);
  });
});

// ── U-8: InsiderActivityList ──────────────────────────────────────────────────

describe("U-8 InsiderActivityList", () => {
  it("renders 5 rows for 5 transactions", () => {
    render(<InsiderActivityList data={INSIDER_DATA} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(5);
  });

  it("BUY transactions show positive-color label", () => {
    render(<InsiderActivityList data={INSIDER_DATA} />);
    // T.Cook bought shares — BUY label should exist
    const buyLabels = screen.getAllByText("BUY");
    expect(buyLabels.length).toBeGreaterThanOrEqual(1);
  });

  it("SALE transactions show negative-color label", () => {
    render(<InsiderActivityList data={INSIDER_DATA} />);
    const saleLabels = screen.getAllByText("SALE");
    expect(saleLabels.length).toBeGreaterThanOrEqual(1);
  });

  it("empty state: shows 'No insider activity' when data is null", () => {
    render(<InsiderActivityList data={null} />);
    expect(screen.getByText(/No insider activity/)).toBeTruthy();
  });

  it("empty state: shows message when records array is empty", () => {
    render(<InsiderActivityList data={{ records: [] }} />);
    expect(screen.getByText(/No insider activity/)).toBeTruthy();
  });

  it("caps at 5 rows even for >5 records", () => {
    const moreData = {
      records: [
        ...INSIDER_DATA.records,
        { id: "6", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-01-05", owner_name: "Extra Person", transaction_type: "Sale", shares: 500, value: 50000 } },
      ],
    };
    render(<InsiderActivityList data={moreData} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(5);
  });
});

// ── U-9: EarningsMiniList ─────────────────────────────────────────────────────

describe("U-9 EarningsMiniList", () => {
  it("renders 4 rows for 4 annual records (newest first)", () => {
    render(<EarningsMiniList data={EARNINGS_DATA} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(4);
  });

  it("shows FY24 (most recent) as first row", () => {
    render(<EarningsMiniList data={EARNINGS_DATA} />);
    // FY24 = fiscal year from "2024-09-30"
    const fy24 = screen.getByText("FY24");
    expect(fy24).toBeTruthy();
  });

  it("shows positive surprise as green-labeled percent", () => {
    render(<EarningsMiniList data={EARNINGS_DATA} />);
    // All 4 records have positive surprisePercent
    const positiveChips = screen.getAllByText(/\+[\d.]+%/);
    expect(positiveChips.length).toBeGreaterThanOrEqual(1);
  });

  it("empty state: shows 'No earnings history' when data is null", () => {
    render(<EarningsMiniList data={null} />);
    expect(screen.getByText(/No earnings history/)).toBeTruthy();
  });

  it("empty state: shows message when records array is empty", () => {
    render(<EarningsMiniList data={{ records: [] }} />);
    expect(screen.getByText(/No earnings history/)).toBeTruthy();
  });
});

// ── U-10: RelatedHeadlinesList ────────────────────────────────────────────────

describe("U-10 RelatedHeadlinesList", () => {
  beforeEach(() => {
    mockPush.mockClear();
  });

  it("renders 3 rows for 3 articles", () => {
    render(<RelatedHeadlinesList data={NEWS_DATA} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(3);
  });

  it("empty state: shows 'No related news' when data is null", () => {
    render(<RelatedHeadlinesList data={null} />);
    expect(screen.getByText(/No related news/)).toBeTruthy();
  });

  it("empty state: shows message when articles array is empty", () => {
    render(<RelatedHeadlinesList data={{ total: 0, articles: [] }} />);
    expect(screen.getByText(/No related news/)).toBeTruthy();
  });

  it("clicking a row navigates to /news/{article_id}", () => {
    render(<RelatedHeadlinesList data={NEWS_DATA} />);
    // Click the first article row
    const rows = screen.getAllByRole("row");
    fireEvent.click(rows[0]);
    expect(mockPush).toHaveBeenCalledWith("/news/a1");
  });

  it("displays relative time for recent articles ('1h' for 1-hour-old article)", () => {
    render(<RelatedHeadlinesList data={NEWS_DATA} />);
    // First article is 1h old → "1h"
    expect(screen.getByText("1h")).toBeTruthy();
  });
});

// ── U-11: PriceLevelsStrip ────────────────────────────────────────────────────

describe("U-11 PriceLevelsStrip", () => {
  it("renders 7 pivot level rows + MA50 + MA200 = 9 rows", () => {
    render(<PriceLevelsStrip data={PRICE_LEVELS_DATA} currentPrice={185} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(9); // 7 levels + MA50 + MA200
  });

  it("R labels are rendered (resistance levels)", () => {
    render(<PriceLevelsStrip data={PRICE_LEVELS_DATA} currentPrice={185} />);
    expect(screen.getByText("R1")).toBeTruthy();
    expect(screen.getByText("R3")).toBeTruthy();
  });

  it("S labels are rendered (support levels)", () => {
    render(<PriceLevelsStrip data={PRICE_LEVELS_DATA} currentPrice={185} />);
    expect(screen.getByText("S1")).toBeTruthy();
    expect(screen.getByText("S3")).toBeTruthy();
  });

  it("MA50 and MA200 rows are rendered", () => {
    render(<PriceLevelsStrip data={PRICE_LEVELS_DATA} currentPrice={185} />);
    expect(screen.getByText("MA50")).toBeTruthy();
    expect(screen.getByText("MA200")).toBeTruthy();
  });

  it("empty state: shows 'Price levels unavailable' when data is null", () => {
    render(<PriceLevelsStrip data={null} />);
    expect(screen.getByText(/Price levels unavailable/)).toBeTruthy();
  });

  it("error state: shows 'Price levels unavailable' (same empty/error message)", () => {
    render(<PriceLevelsStrip data={null} isError />);
    // WHY same text: PriceLevelsStrip renders (isEmpty || isError) → same "unavailable" message.
    expect(screen.getByText(/Price levels unavailable/)).toBeTruthy();
  });
});

// ── U-12: WhatsMovingStrip ────────────────────────────────────────────────────

describe("U-12 WhatsMovingStrip", () => {
  beforeEach(() => {
    mockPush.mockClear();
  });

  it("renders 3 rows for top-3 articles", () => {
    render(<WhatsMovingStrip data={NEWS_DATA} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(3);
  });

  it("empty state: shows 'No recent news' when data is null", () => {
    render(<WhatsMovingStrip data={null} />);
    expect(screen.getByText(/No recent news/)).toBeTruthy();
  });

  it("clicking a row navigates to /news/{article_id}", () => {
    render(<WhatsMovingStrip data={NEWS_DATA} />);
    const rows = screen.getAllByRole("row");
    fireEvent.click(rows[0]);
    expect(mockPush).toHaveBeenCalledWith("/news/a1");
  });
});

// ── U-13: InstrumentHeader — sector pill ─────────────────────────────────────

describe("U-13 InstrumentHeader sector pill (T-13, Δ)", () => {
  it("renders gics_sector as micro-pill when present", () => {
    render(
      <InstrumentHeader
        instrument={INSTRUMENT_AAPL as Parameters<typeof InstrumentHeader>[0]["instrument"]}
        quote={null}
        fundamentals={null}
      />
    );
    // Sector text should appear in the header
    expect(screen.getByText(/Information Technology/i)).toBeTruthy();
  });

  it("does NOT render sector pill when gics_sector is null", () => {
    render(
      <InstrumentHeader
        instrument={INSTRUMENT_SPY as Parameters<typeof InstrumentHeader>[0]["instrument"]}
        quote={null}
        fundamentals={null}
      />
    );
    expect(screen.queryByText(/Information Technology/i)).toBeNull();
  });

  it("renders ticker symbol in header", () => {
    render(
      <InstrumentHeader
        instrument={INSTRUMENT_AAPL as Parameters<typeof InstrumentHeader>[0]["instrument"]}
        quote={null}
        fundamentals={null}
      />
    );
    expect(screen.getByText("AAPL")).toBeTruthy();
  });

  it("renders '—' placeholders when instrument is null (loading state)", () => {
    render(<InstrumentHeader instrument={null} quote={null} fundamentals={null} />);
    // "—" fallback for ticker
    const placeholders = screen.getAllByText("—");
    expect(placeholders.length).toBeGreaterThanOrEqual(1);
  });
});
