/**
 * components/portfolio/__tests__/HoldingNewsList.test.tsx (F-008)
 *
 * WHY: Pins three render paths:
 *  1. Shows "No recent news" when the query returns an empty articles array.
 *  2. Renders article headlines when the query returns articles.
 *  3. Respects the `limit` prop — shows at most N headlines.
 *
 * MOCKED: useAuth, createGateway, next/navigation (useRouter).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { RankedNewsResponse } from "@/types/api";

// ── Auth stub ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "t@x.com", name: "T", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Router stub ───────────────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    refresh: vi.fn(),
  })),
}));

// ── Gateway stub ──────────────────────────────────────────────────────────────
const mockGetEntityNews = vi.fn();

const mockGateway = { getEntityNews: mockGetEntityNews };

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
}));

// WHY also mock api-client: SUT now uses useApiClient() (D1 remediation).
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => mockGateway),
}));

// ── SUT import ────────────────────────────────────────────────────────────────
import { HoldingNewsList } from "../HoldingNewsList";

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Minimal RankedNewsResponse with N articles. */
function makeNewsResponse(count: number): RankedNewsResponse {
  return {
    articles: Array.from({ length: count }, (_, i) => ({
      article_id: `a-${i}`,
      title: `Headline number ${i + 1}`,
      source_name: "Reuters",
      source_type: "news",
      published_at: "2026-05-22T10:00:00Z",
      url: `https://example.com/article-${i}`,
      // Required fields with null stubs — not exercised by these tests.
      routing_tier: null,
      routing_score: null,
      market_impact_score: null,
      llm_relevance_score: null,
      display_relevance_score: 0.9,
      primary_entity_id: null,
      primary_entity_symbol: null,
      impact_windows: null,
      sentiment: null,
      impact_score: null,
      cluster_size: null,
    })),
    total: count,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HoldingNewsList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows 'No recent news' when articles array is empty", async () => {
    mockGetEntityNews.mockResolvedValue(makeNewsResponse(0));

    render(wrap(<HoldingNewsList instrumentId="e-001" />));

    await waitFor(() => {
      expect(screen.getByText("No recent news")).toBeInTheDocument();
    });
  });

  it("renders article headlines when data is available", async () => {
    mockGetEntityNews.mockResolvedValue(makeNewsResponse(3));

    render(wrap(<HoldingNewsList instrumentId="e-001" limit={3} />));

    await waitFor(() => {
      expect(screen.getByText("Headline number 1")).toBeInTheDocument();
      expect(screen.getByText("Headline number 2")).toBeInTheDocument();
      expect(screen.getByText("Headline number 3")).toBeInTheDocument();
    });
  });

  it("respects the limit prop — shows at most N headlines", async () => {
    // WHY 10 articles with limit=2: confirms the slice(0, limit) is applied.
    mockGetEntityNews.mockResolvedValue(makeNewsResponse(10));

    render(wrap(<HoldingNewsList instrumentId="e-001" limit={2} />));

    await waitFor(() => {
      // Only headlines 1 and 2 should appear; headline 3+ must NOT be present.
      expect(screen.getByText("Headline number 1")).toBeInTheDocument();
      expect(screen.getByText("Headline number 2")).toBeInTheDocument();
      expect(screen.queryByText("Headline number 3")).not.toBeInTheDocument();
    });
  });
});
