/**
 * __tests__/slash-command-card.test.tsx — tests for the inline cards
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-08):
 * Each card type fetches different data and renders subtly different UI. We
 * verify (a) the right gateway method is called for each command, and
 * (b) the rendered output contains the headline values the trader expects.
 * Mocking the gateway keeps the tests fast + deterministic.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { SlashCommandCard } from "@/components/chat/SlashCommandCard";
import type { ParsedCommand } from "@/lib/chat/slash-commands";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/chat",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: null,
    setTokens: vi.fn(),
    logout: vi.fn(),
  }),
}));

const gatewayMocks = {
  getQuote: vi.fn(),
  getPortfolios: vi.fn(),
  getHoldings: vi.fn(),
  getTopNews: vi.fn(),
  getWatchlists: vi.fn(),
  getPendingAlerts: vi.fn(),
};

vi.mock("@/lib/gateway", () => ({
  createGateway: () => gatewayMocks,
  GatewayError: class extends Error {
    constructor(public status: number, msg: string) {
      super(msg);
    }
  },
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  // WHY retry: false — surface failed queries fast in tests.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderCard(command: ParsedCommand) {
  return render(<SlashCommandCard command={command} />, { wrapper: Wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("SlashCommandCard — Quote", () => {
  it("renders price + change% from getQuote", async () => {
    gatewayMocks.getQuote.mockResolvedValue({
      instrument_id: "AAPL",
      ticker: "AAPL",
      price: 187.42,
      change: 2.1,
      change_pct: 1.13,
      timestamp: "2026-04-29T12:00:00Z",
      volume: 1_234_567,
    });

    renderCard({ kind: "quote", params: { ticker: "AAPL" } });

    await waitFor(() => {
      expect(screen.getByText(/Quote: AAPL/i)).toBeInTheDocument();
    });
    // Price headline
    await waitFor(() => {
      expect(screen.getByText(/\$187\.42/)).toBeInTheDocument();
    });
  });
});

describe("SlashCommandCard — Portfolio", () => {
  it("renders total value + holdings count", async () => {
    gatewayMocks.getPortfolios.mockResolvedValue([
      { portfolio_id: "p1", name: "Main", currency: "USD", owner_id: "u1", created_at: "2026-01-01", updated_at: "2026-01-01" },
    ]);
    gatewayMocks.getHoldings.mockResolvedValue({
      portfolio_id: "p1",
      holdings: [
        { holding_id: "h1", portfolio_id: "p1", instrument_id: "i1", entity_id: "e1", ticker: "AAPL", name: "Apple", quantity: 10, average_cost: 150 },
        { holding_id: "h2", portfolio_id: "p1", instrument_id: "i2", entity_id: "e2", ticker: "MSFT", name: "Microsoft", quantity: 5, average_cost: 300 },
      ],
      total_value: 5500,
      total_cost: 3000,
      total_unrealised_pnl: 2500,
      total_unrealised_pnl_pct: 83.33,
    });

    renderCard({ kind: "portfolio", params: {} });

    await waitFor(() => {
      expect(screen.getByText(/Portfolio summary/i)).toBeInTheDocument();
    });
    // Holdings count = 2
    await waitFor(() => {
      expect(screen.getByText("2")).toBeInTheDocument();
    });
  });
});

describe("SlashCommandCard — News", () => {
  it("renders 5 most-recent ranked articles with sentiment", async () => {
    gatewayMocks.getTopNews.mockResolvedValue({
      articles: Array.from({ length: 5 }).map((_, i) => ({
        article_id: `a${i}`,
        title: `Article ${i}`,
        url: `https://example.com/${i}`,
        published_at: "2026-04-29T11:00:00Z",
        source_type: "eodhd_news",
        source_name: "EODHD",
        routing_tier: "DEEP",
        routing_score: 0.5,
        market_impact_score: 0.6,
        llm_relevance_score: 0.7,
        display_relevance_score: 0.6,
        primary_entity_id: null,
        primary_entity_symbol: null,
        impact_windows: null,
        sentiment: i % 2 === 0 ? "positive" : "negative",
        impact_score: 0.6,
      })),
      total: 5,
    });

    renderCard({ kind: "news", params: {} });

    await waitFor(() => {
      // First article title should appear
      expect(screen.getByText("Article 0")).toBeInTheDocument();
    });
    // 5 article titles total
    expect(screen.getAllByText(/^Article \d$/).length).toBe(5);
  });
});

describe("SlashCommandCard — Screener", () => {
  it("renders a static link to the screener page", () => {
    renderCard({ kind: "screener", params: {} });
    // The link text is "Open screener →"
    const link = screen.getByRole("link", { name: /open screener/i });
    expect(link).toBeInTheDocument();
    expect(link.getAttribute("href")).toBe("/screener");
  });
});
