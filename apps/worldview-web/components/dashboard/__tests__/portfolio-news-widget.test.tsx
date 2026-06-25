/**
 * portfolio-news-widget.test.tsx — regression tests for the PORTFOLIO NEWS widget.
 *
 * ── WHY THIS FILE EXISTS (W4 root-cause fix, 2026-06-14) ────────────────────
 * The dashboard "PORTFOLIO NEWS" widget showed "No recent news" despite the
 * demo portfolio holding 10 well-known names (AAPL/TSLA/NVDA/…). Investigation
 * found the widget fanned out `/v1/news/entity/{id}` on the holding's
 * `entity_id` field — which on the S1 holdings payload is STALE seed data
 * (`11111111-000X-…`) that 404s in the knowledge graph and carries ZERO
 * articles. Per knowledge-graph M-017 the canonical entity news is tagged to
 * for a tradable security IS its `instrument_id` (the same id the Instrument
 * page News tab uses), which DOES return hundreds of articles.
 *
 * These tests pin the fix so it can never silently regress:
 *  1. the news fan-out uses `instrument_id` (NOT the stale `entity_id`);
 *  2. aggregated articles render with their owning-ticker badge;
 *  3. with holdings present but every feed empty, the widget shows the
 *     "no-news" empty state (not the "no-holdings" one).
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PortfolioNewsWidget } from "@/components/dashboard/PortfolioNewsWidget";
import type { HoldingsResponse, Portfolio, RankedNewsResponse } from "@/types/api";

// ── Auth mock — widget only reads accessToken ────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token", isAuthenticated: true })),
}));

// ── Defer hook — return true synchronously so queries fire immediately in
// the test (the real hook waits two animation frames). ───────────────────────
vi.mock("@/hooks/useAboveFoldReady", () => ({
  useAboveFoldReady: vi.fn(() => true),
}));

// ── Active-portfolio context — no provider mounted; resolve to portfolios[0]
// via the hook's documented fallback (returns null active id). ────────────────
vi.mock("@/contexts/ActivePortfolioContext", () => ({
  useActivePortfolio: vi.fn(() => ({
    activePortfolioId: null,
    setActivePortfolio: vi.fn(),
  })),
}));

// ── Gateway mock — the three calls the widget makes. getEntityNews is the one
// under test: it must be invoked with the holding's instrument_id. ────────────
const gatewayMocks = {
  getPortfolios: vi.fn(),
  getHoldings: vi.fn(),
  getEntityNews: vi.fn(),
};
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => gatewayMocks),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Fixtures mirroring the live S9 payloads ──────────────────────────────────
const DEMO_PORTFOLIO_ID = "01900000-0000-7000-8000-000000000100";
const AAPL_INSTRUMENT_ID = "01900000-0000-7000-8000-000000001001";
// The STALE entity id the S1 holdings JOIN returns — must NOT be used to fetch.
const AAPL_STALE_ENTITY_ID = "11111111-0001-7000-8000-000000000001";

const portfolios: Portfolio[] = [
  {
    portfolio_id: DEMO_PORTFOLIO_ID,
    name: "Demo Portfolio",
    currency: "USD",
    owner_id: "01900000-0000-7000-8000-000000000010",
    created_at: "2026-05-07T21:54:37Z",
    updated_at: "2026-05-07T21:54:37Z",
    kind: "manual",
  },
];

const holdings: HoldingsResponse = {
  portfolio_id: DEMO_PORTFOLIO_ID,
  holdings: [
    {
      holding_id: "h-aapl",
      portfolio_id: DEMO_PORTFOLIO_ID,
      instrument_id: AAPL_INSTRUMENT_ID,
      entity_id: AAPL_STALE_ENTITY_ID,
      ticker: "AAPL",
      name: "Apple Inc.",
      quantity: 10,
      average_cost: 150,
      asset_class: "equity",
    },
  ],
  total_value: null,
  total_cost: null,
  total_unrealised_pnl: null,
  total_unrealised_pnl_pct: null,
};

const aaplNews: RankedNewsResponse = {
  articles: [
    {
      article_id: "art-aapl-1",
      title: "Apple Unveils New AI Features at WWDC",
      url: "https://finance.yahoo.com/news/apple-ai-wwdc.html",
      published_at: "2026-06-12T10:00:00Z",
      market_impact_score: 0.8,
      display_relevance_score: 0.8,
      routing_tier: "HIGH",
      primary_entity_symbol: "AAPL",
    } as RankedNewsResponse["articles"][number],
  ],
  total: 1,
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("PortfolioNewsWidget — news fan-out keys on instrument_id (W4 fix)", () => {
  it("fetches per-holding news with instrument_id, NOT the stale entity_id", async () => {
    gatewayMocks.getPortfolios.mockResolvedValue(portfolios);
    gatewayMocks.getHoldings.mockResolvedValue(holdings);
    gatewayMocks.getEntityNews.mockResolvedValue(aaplNews);

    render(<PortfolioNewsWidget />, { wrapper });

    await waitFor(() => {
      expect(gatewayMocks.getEntityNews).toHaveBeenCalled();
    });

    // The CRITICAL assertion: the fan-out id is the instrument_id (which carries
    // news per M-017), never the orphan entity_id that returns zero articles.
    const calledIds = gatewayMocks.getEntityNews.mock.calls.map((c) => c[0]);
    expect(calledIds).toContain(AAPL_INSTRUMENT_ID);
    expect(calledIds).not.toContain(AAPL_STALE_ENTITY_ID);
  });

  it("renders the aggregated article tagged with its owning ticker badge", async () => {
    gatewayMocks.getPortfolios.mockResolvedValue(portfolios);
    gatewayMocks.getHoldings.mockResolvedValue(holdings);
    gatewayMocks.getEntityNews.mockResolvedValue(aaplNews);

    render(<PortfolioNewsWidget />, { wrapper });

    expect(
      await screen.findByText("Apple Unveils New AI Features at WWDC"),
    ).toBeInTheDocument();
    // The owning-ticker badge (per-entity provenance from the fan-out).
    const badges = await screen.findAllByTestId("portfolio-news-ticker-badge");
    expect(badges.some((b) => b.textContent === "AAPL")).toBe(true);
  });

  it("shows the no-news empty state when holdings resolve but every feed is empty", async () => {
    gatewayMocks.getPortfolios.mockResolvedValue(portfolios);
    gatewayMocks.getHoldings.mockResolvedValue(holdings);
    // Empty feed — the pre-fix bug surfaced here (entity_id always returned 0).
    gatewayMocks.getEntityNews.mockResolvedValue({ articles: [], total: 0 });

    render(<PortfolioNewsWidget />, { wrapper });

    // "No recent news" (dashboard.no-news) — NOT the no-holdings copy, because
    // a holding with a resolvable instrument_id IS present.
    expect(await screen.findByText("No recent news")).toBeInTheDocument();
  });
});
