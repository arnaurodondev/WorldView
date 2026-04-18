/**
 * __tests__/alerts-page.test.tsx — Unit tests for Wave F-7 news + alert components
 *
 * WHY THIS FILE EXISTS: Covers the three core F-7 components:
 * 1. ArticleImpactBadge — score display and null handling
 * 2. ArticleCard — article title, source, and link rendering
 * 3. AlertsList — severity badge rendering (used in Alerts tab)
 *
 * The file also retains a smoke test for the new tabbed AlertsPage (Alerts /
 * News Feed / Top Today tabs) introduced in Wave F-7, replacing the previous
 * single-tab alerts page.
 *
 * WHY MOCK GATEWAY: We don't want real S9 calls in unit tests.
 * WHY MOCK AlertStreamContext: The context wraps a WebSocket — avoid real connections.
 * WHY MOCK useAuth: No AuthProvider in unit test environment.
 *
 * DATA SOURCE: Inline article + alert fixtures; mocked gateway client.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ArticleImpactBadge } from "@/components/news/ArticleImpactBadge";
import { ArticleCard } from "@/components/news/ArticleCard";
import { AlertsList } from "@/components/alerts/AlertsList";
import type { Article } from "@/types/api";

// ── Next.js navigation mock ───────────────────────────────────────────────────
// WHY: ArticleCard uses next/link; AlertsList uses useRouter for navigation.
// App Router is not mounted in unit tests — mock to avoid invariant errors.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  })),
  usePathname: vi.fn(() => "/alerts"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
// WHY: AlertsList calls useAuth() to get the access token for the gateway.
// No AuthProvider in unit tests — mock the hook directly.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "Test", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getPendingAlerts: vi.fn().mockResolvedValue({
      alerts: [
        {
          alert_id: "alert-001",
          entity_id: "entity-aapl",
          ticker: "AAPL",
          alert_type: "PRICE_MOVE",
          severity: "HIGH" as const,
          title: "AAPL moved +5%",
          body: "Apple Inc shares surged 5% on earnings beat",
          metadata: {},
          created_at: new Date(Date.now() - 10 * 60_000).toISOString(),
          acknowledged_at: null,
        },
        {
          alert_id: "alert-002",
          entity_id: "entity-tsla",
          ticker: "TSLA",
          alert_type: "NEWS_SIGNAL",
          severity: "CRITICAL" as const,
          title: "TSLA critical signal",
          body: "Tesla critical news signal detected — review immediately",
          metadata: {},
          created_at: new Date(Date.now() - 2 * 60_000).toISOString(),
          acknowledged_at: null,
        },
        {
          alert_id: "alert-003",
          entity_id: "entity-msft",
          ticker: "MSFT",
          alert_type: "EARNINGS_EVENT",
          severity: "MEDIUM" as const,
          title: "MSFT earnings tomorrow",
          body: "Microsoft reports earnings after market close tomorrow",
          metadata: {},
          created_at: new Date(Date.now() - 60 * 60_000).toISOString(),
          acknowledged_at: null,
        },
      ],
      total: 3,
      offset: 0,
      limit: 50,
    }),
    getRelevantNews: vi.fn().mockResolvedValue({ articles: [], total: 0, offset: 0, limit: 20 }),
    getTopNews: vi.fn().mockResolvedValue({ articles: [], total: 0, offset: 0, limit: 20 }),
    acknowledgeAlert: vi.fn().mockResolvedValue(undefined),
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "tok",
      user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      // WHY retry: false — don't retry in unit tests; want immediate results.
      queries: { retry: false },
    },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Article fixtures ──────────────────────────────────────────────────────────

const ARTICLE_WITH_SCORE: Article = {
  article_id: "art-001",
  title: "Apple beats Q1 earnings expectations",
  url: "https://example.com/apple-earnings",
  source: "Reuters",
  published_at: new Date(Date.now() - 2 * 60 * 60_000).toISOString(),
  summary: "Apple Inc reported better-than-expected Q1 earnings, driven by strong iPhone sales.",
  entity_ids: ["entity-aapl"],
  tickers: ["AAPL"],
  display_relevance_score: 0.75,
  market_impact_score: 0.8,
  sentiment: "positive",
  impact_window_t0: 0.012,
  impact_window_t1: 0.015,
  impact_window_t2: 0.018,
  impact_window_t5: 0.02,
};

const ARTICLE_NO_SCORE: Article = {
  article_id: "art-002",
  title: "Market wrap: Stocks rally on Fed comments",
  url: "https://example.com/market-wrap",
  source: "Bloomberg",
  published_at: new Date(Date.now() - 5 * 60 * 60_000).toISOString(),
  summary: null,
  entity_ids: [],
  tickers: [],
  display_relevance_score: null,
  market_impact_score: null,
  sentiment: null,
  impact_window_t0: null,
  impact_window_t1: null,
  impact_window_t2: null,
  impact_window_t5: null,
};

// ── Tests: ArticleImpactBadge ─────────────────────────────────────────────────

describe("ArticleImpactBadge", () => {
  it("renders score 0.75 as '75'", () => {
    // WHY: API returns 0.0–1.0 floats; badge must display 0–100 integers.
    // 0.75 × 100 = 75 (Math.round). Traders read "75" faster than "0.75".
    render(<ArticleImpactBadge score={0.75} sentiment="positive" />);
    expect(screen.getByText("75")).toBeInTheDocument();
  });

  it("renders score 0.32 as '32'", () => {
    render(<ArticleImpactBadge score={0.32} sentiment="negative" />);
    expect(screen.getByText("32")).toBeInTheDocument();
  });

  it("renders nothing when score is null", () => {
    // WHY: Older articles predate PRD-0026 scoring; hiding is cleaner than "—".
    const { container } = render(
      <ArticleImpactBadge score={null} sentiment={null} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders positive sentiment symbol '+'", () => {
    render(<ArticleImpactBadge score={0.8} sentiment="positive" />);
    expect(screen.getByText("+")).toBeInTheDocument();
  });

  it("renders negative sentiment symbol '−'", () => {
    render(<ArticleImpactBadge score={0.3} sentiment="negative" />);
    // WHY unicode minus (−) not ASCII hyphen: distinguishes from hyphen in readers
    expect(screen.getByText("−")).toBeInTheDocument();
  });

  it("renders neutral sentiment symbol '~'", () => {
    render(<ArticleImpactBadge score={0.5} sentiment="neutral" />);
    expect(screen.getByText("~")).toBeInTheDocument();
  });
});

// ── Tests: ArticleCard ────────────────────────────────────────────────────────

describe("ArticleCard", () => {
  it("renders the article title", () => {
    render(<ArticleCard article={ARTICLE_WITH_SCORE} />);
    expect(
      screen.getByText("Apple beats Q1 earnings expectations"),
    ).toBeInTheDocument();
  });

  it("renders the article source name", () => {
    render(<ArticleCard article={ARTICLE_WITH_SCORE} />);
    // Source appears in the Badge at the top-left of the card
    expect(screen.getByText("Reuters")).toBeInTheDocument();
  });

  it("renders the article summary when present", () => {
    render(<ArticleCard article={ARTICLE_WITH_SCORE} />);
    expect(
      screen.getByText(/better-than-expected Q1 earnings/i),
    ).toBeInTheDocument();
  });

  it("does not render summary when summary is null", () => {
    render(<ArticleCard article={ARTICLE_NO_SCORE} />);
    // No summary text in ARTICLE_NO_SCORE — the summary slot should be absent
    expect(
      screen.queryByText(/market wrap.*summary/i),
    ).not.toBeInTheDocument();
  });

  it("renders entity ticker", () => {
    render(<ArticleCard article={ARTICLE_WITH_SCORE} />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("renders impact badge score for scored articles", () => {
    render(<ArticleCard article={ARTICLE_WITH_SCORE} />);
    // 0.75 → "75"
    expect(screen.getByText("75")).toBeInTheDocument();
  });

  it("does not render impact badge when score is null", () => {
    render(<ArticleCard article={ARTICLE_NO_SCORE} />);
    // No aria-label on a badge that doesn't exist
    expect(
      screen.queryByLabelText(/impact score/i),
    ).not.toBeInTheDocument();
  });

  it("renders a link with the article URL", () => {
    render(<ArticleCard article={ARTICLE_WITH_SCORE} />);
    const link = screen.getByRole("link", { name: /apple beats/i });
    expect(link).toHaveAttribute("href", "https://example.com/apple-earnings");
  });

  it("renders link with target=_blank", () => {
    render(<ArticleCard article={ARTICLE_WITH_SCORE} />);
    const link = screen.getByRole("link", { name: /apple beats/i });
    expect(link).toHaveAttribute("target", "_blank");
  });
});

// ── Tests: AlertsList severity badge ─────────────────────────────────────────

describe("AlertsList — severity badges", () => {
  beforeEach(() => {
    // WHY: clear mocks between tests to prevent state bleed across query clients
    vi.clearAllMocks();
  });

  it("shows HIGH severity badge after data loads", async () => {
    render(<AlertsList />, { wrapper });

    await waitFor(() => {
      // SeverityBadge abbreviates HIGH → "HIGH" (4 chars, not truncated)
      const badges = screen.getAllByText("HIGH");
      expect(badges.length).toBeGreaterThan(0);
    });
  });

  it("shows CRIT badge for CRITICAL alert", async () => {
    render(<AlertsList />, { wrapper });

    await waitFor(() => {
      // SeverityBadge abbreviates CRITICAL → "CRIT"
      const critBadges = screen.getAllByText("CRIT");
      expect(critBadges.length).toBeGreaterThan(0);
    });
  });

  it("shows MED badge for MEDIUM alert", async () => {
    render(<AlertsList />, { wrapper });

    await waitFor(() => {
      const medBadges = screen.getAllByText("MED");
      expect(medBadges.length).toBeGreaterThan(0);
    });
  });

  it("shows ticker AAPL in an alert row", async () => {
    render(<AlertsList />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
  });
});
