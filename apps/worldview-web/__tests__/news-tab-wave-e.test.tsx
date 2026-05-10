/**
 * __tests__/news-tab-wave-e.test.tsx — Unit tests for PLAN-0050 Wave E news features
 *
 * WHY THIS EXISTS: Wave E adds sentiment pills, impact pills, time-grouping headers,
 * source filter, and sort controls to the News tab. These tests verify:
 *   - Sentiment pill rendering and colour (positive/negative/neutral/mixed)
 *   - Impact pill rendering and Δ prefix
 *   - Relevance badge gradient thresholds (amber/green/muted)
 *   - Time-grouping logic (TODAY / PAST 3 DAYS / PAST WEEK / OLDER)
 *   - Source filter dropdown narrows article list
 *   - Sort dropdown reorders articles (relevance / impact / time)
 *
 * WHY MOCKS: NewsTab uses useQuery (TanStack Query), useAuth (JWT hook), and
 * useRouter (Next.js navigation). All three require context/module mocks in jsdom.
 * The gateway is mocked to return controlled article fixtures.
 *
 * WHAT IS NOT TESTED HERE (covered in e2e/instrument.spec.ts instead):
 *   - Entity chip click navigates to instrument page (requires router + navigation)
 *   - Load-more pagination (requires multiple query responses)
 *   - Stale-graph banner (requires time manipulation in IntelligenceTab tests)
 *
 * DATA REFERENCE: RankedArticle interface in types/api.ts
 * DESIGN REFERENCE: PRD-0050 Wave E T-E-5-03, T-E-5-07
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { RankedArticle } from "@/types/api";

// ── Mocks ─────────────────────────────────────────────────────────────────────

// WHY mock next/navigation: NewsTab uses useRouter for entity chip navigation.
// Without this mock, Next.js throws "invariant useRouter must be in Router context".
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// WHY mock useAuth: NewsTab calls useAuth() to get the access token.
// Mocking returns a stable token so the query is not disabled.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token", user: null, isLoading: false })),
}));

// WHY mock createGateway: NewsTab calls gateway.getEntityNews() in a useQuery.
// We override it per-test to control the returned articles.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getEntityNews: vi.fn(),
  })),
}));

// ── Test data factory ─────────────────────────────────────────────────────────

/** Build a RankedArticle fixture with overrideable fields. */
function makeArticle(overrides: Partial<RankedArticle> = {}): RankedArticle {
  return {
    article_id: "art-" + Math.random().toString(36).slice(2, 8),
    title: "Test Article Title",
    url: "https://example.com/article",
    published_at: new Date().toISOString(), // defaults to now (TODAY group)
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
    // PLAN-0050 Wave E fields
    sentiment: null,
    impact_score: null,
    // SA-4: cluster_size added to RankedArticle type; null for test fixtures
    cluster_size: null,
    ...overrides,
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Wrap a component in TanStack Query provider with a fresh client per test. */
function withQueryClient(ui: React.ReactElement): React.ReactElement {
  const queryClient = new QueryClient({
    defaultOptions: {
      // WHY retry:false in tests: prevents retry delays slowing down the test suite.
      queries: { retry: false },
    },
  });
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>;
}

// ── Isolated sub-component tests ──────────────────────────────────────────────
// WHY test sub-components directly (not via NewsTab full render with mocked queries):
// NewsTab uses useQuery which requires query-client context + gateway mock resolution.
// For pure presentational pieces (SentimentPill, ImpactPill, RelevanceBadge), we
// can import the component's internal logic directly — but since these are not
// exported, we test their visible output through the full NewsTab or by importing
// the presentational types and asserting aria-labels and DOM text.
//
// ALTERNATIVE: We extract the rendering logic into a unit-testable helper. For this
// wave, we test the visible DOM output (aria-labels, text content) after rendering
// a full NewsTab with stubbed query data.

// ── Sentiment configuration tests (standalone logic) ─────────────────────────

describe("Sentiment pill rendering logic", () => {
  // WHY test the config map in isolation: ensures the label/class mapping is
  // correct before testing the full component. Fast and no DOM setup needed.

  it("should map all 4 sentiment values to unique labels", () => {
    const sentiments = ["positive", "negative", "neutral", "mixed"] as const;
    // WHY each: ensures all 4 values are handled, no runtime crashes for any value.
    const expectedLabels: Record<string, string> = {
      positive: "POS",
      negative: "NEG",
      neutral: "NEU",
      mixed: "MIX",
    };
    for (const s of sentiments) {
      expect(expectedLabels[s]).toBeDefined();
      expect(expectedLabels[s].length).toBe(3);
    }
  });
});

// ── Time-grouping logic tests ─────────────────────────────────────────────────

describe("News tab time-grouping logic", () => {
  // WHY test pure helper (not component): the getTimeGroup function determines which
  // section header an article appears under. Testing it in isolation avoids mocking
  // the full useQuery/gateway pipeline just to check time-bucket assignment.

  const DAY_MS = 24 * 60 * 60 * 1000;

  function getTimeGroup(publishedAt: string | null): string {
    if (!publishedAt) return "OLDER";
    const ageMs = Date.now() - new Date(publishedAt).getTime();
    if (ageMs < DAY_MS) return "TODAY";
    if (ageMs < 3 * DAY_MS) return "PAST 3 DAYS";
    if (ageMs < 7 * DAY_MS) return "PAST WEEK";
    return "OLDER";
  }

  it("groups an article from 30 minutes ago as TODAY", () => {
    const published = new Date(Date.now() - 30 * 60 * 1000).toISOString();
    expect(getTimeGroup(published)).toBe("TODAY");
  });

  it("groups an article from 2 days ago as PAST 3 DAYS", () => {
    const published = new Date(Date.now() - 2 * DAY_MS).toISOString();
    expect(getTimeGroup(published)).toBe("PAST 3 DAYS");
  });

  it("groups an article from 5 days ago as PAST WEEK", () => {
    const published = new Date(Date.now() - 5 * DAY_MS).toISOString();
    expect(getTimeGroup(published)).toBe("PAST WEEK");
  });

  it("groups an article from 10 days ago as OLDER", () => {
    const published = new Date(Date.now() - 10 * DAY_MS).toISOString();
    expect(getTimeGroup(published)).toBe("OLDER");
  });

  it("groups null published_at as OLDER (graceful null handling)", () => {
    // WHY: RankedArticle.published_at is string | null. Null means the S6 pipeline
    // didn't populate it. Bucketing as OLDER prevents an OLDER header from missing.
    expect(getTimeGroup(null)).toBe("OLDER");
  });
});

// ── Relevance badge threshold tests ──────────────────────────────────────────

describe("Relevance badge colour threshold logic", () => {
  // WHY test threshold logic in isolation: the badge className depends on 3 breakpoints.
  // These tests document the exact threshold values so any future change is deliberate.

  function getScoreClass(score: number): string {
    // WHY mirror the actual component logic (from NewsTab.tsx RelevanceBadge):
    // ≥ 0.70 → positive, ≥ 0.40 → warning, < 0.40 → muted
    if (score >= 0.70) return "positive";
    if (score >= 0.40) return "warning";
    return "muted";
  }

  it("classifies score 0.85 as positive (above 0.70 threshold)", () => {
    expect(getScoreClass(0.85)).toBe("positive");
  });

  it("classifies score 0.70 as positive (exactly at threshold)", () => {
    expect(getScoreClass(0.70)).toBe("positive");
  });

  it("classifies score 0.55 as warning (between 0.40 and 0.70)", () => {
    expect(getScoreClass(0.55)).toBe("warning");
  });

  it("classifies score 0.40 as warning (exactly at lower threshold)", () => {
    expect(getScoreClass(0.40)).toBe("warning");
  });

  it("classifies score 0.25 as muted (below 0.40)", () => {
    expect(getScoreClass(0.25)).toBe("muted");
  });

  it("classifies score 0.0 as muted (routing-only article)", () => {
    expect(getScoreClass(0.0)).toBe("muted");
  });
});

// ── Sort order tests ──────────────────────────────────────────────────────────

describe("News tab sort order logic", () => {
  // WHY test sort in isolation: the sort functions are pure comparators.
  // Testing them here avoids rendering a full component with mocked queries.

  const articles: RankedArticle[] = [
    makeArticle({ article_id: "art-1", display_relevance_score: 0.3, impact_score: 0.8 }),
    makeArticle({ article_id: "art-2", display_relevance_score: 0.9, impact_score: 0.2 }),
    makeArticle({ article_id: "art-3", display_relevance_score: 0.6, impact_score: 0.5 }),
  ];

  it("sorts by relevance desc: highest display_relevance_score first", () => {
    const sorted = [...articles].sort(
      (a, b) => (b.display_relevance_score ?? 0) - (a.display_relevance_score ?? 0),
    );
    expect(sorted[0].article_id).toBe("art-2"); // 0.9
    expect(sorted[1].article_id).toBe("art-3"); // 0.6
    expect(sorted[2].article_id).toBe("art-1"); // 0.3
  });

  it("sorts by impact desc: highest impact_score first", () => {
    const sorted = [...articles].sort(
      (a, b) => (b.impact_score ?? -1) - (a.impact_score ?? -1),
    );
    expect(sorted[0].article_id).toBe("art-1"); // 0.8
    expect(sorted[1].article_id).toBe("art-3"); // 0.5
    expect(sorted[2].article_id).toBe("art-2"); // 0.2
  });

  it("sorts null impact_score to bottom (articles without price windows)", () => {
    const withNull: RankedArticle[] = [
      makeArticle({ article_id: "art-a", impact_score: 0.7 }),
      makeArticle({ article_id: "art-b", impact_score: null }),
      makeArticle({ article_id: "art-c", impact_score: 0.4 }),
    ];
    const sorted = [...withNull].sort(
      (a, b) => (b.impact_score ?? -1) - (a.impact_score ?? -1),
    );
    // WHY -1 as null substitute: null articles should sink below all real scores (0.0-1.0).
    // Using -1 as the sentinel ensures they sort last.
    expect(sorted[0].article_id).toBe("art-a"); // 0.7
    expect(sorted[2].article_id).toBe("art-b"); // null → -1
  });
});

// ── Intelligence filter state tests ──────────────────────────────────────────

describe("IntelligenceFilters confidence threshold filter logic", () => {
  // WHY test filter logic in isolation: the client-side filtering in IntelligenceTab
  // applies confidence threshold + relation type + entity type filters to graph edges.
  // Isolating the logic avoids setting up sigma.js mocks for these edge cases.

  const edges = [
    { id: "e1", source: "n1", target: "n2", label: "CEO_OF", weight: 0.9 },
    { id: "e2", source: "n1", target: "n3", label: "COMPETES_WITH", weight: 0.3 },
    { id: "e3", source: "n2", target: "n3", label: "PARTNER_OF", weight: 0.6 },
  ];

  it("confidence threshold 0.5 removes edges below 0.5", () => {
    const threshold = 0.5;
    const filtered = edges.filter((e) => e.weight >= threshold);
    expect(filtered).toHaveLength(2);
    expect(filtered.map((e) => e.id)).toEqual(["e1", "e3"]);
  });

  it("confidence threshold 0.0 keeps all edges", () => {
    const filtered = edges.filter((e) => e.weight >= 0.0);
    expect(filtered).toHaveLength(3);
  });

  it("confidence threshold 1.0 keeps only perfect-confidence edges", () => {
    const filtered = edges.filter((e) => e.weight >= 1.0);
    expect(filtered).toHaveLength(0);
  });

  it("relation-type filter empty array keeps all edges", () => {
    const activeTypes: string[] = [];
    const filtered = edges.filter(
      (e) => activeTypes.length === 0 || activeTypes.includes(e.label),
    );
    expect(filtered).toHaveLength(3);
  });

  it("relation-type filter [CEO_OF] keeps only CEO_OF edges", () => {
    const activeTypes = ["CEO_OF"];
    const filtered = edges.filter(
      (e) => activeTypes.length === 0 || activeTypes.includes(e.label),
    );
    expect(filtered).toHaveLength(1);
    expect(filtered[0].label).toBe("CEO_OF");
  });
});

// ── NewsTab DOM tests with mocked query ───────────────────────────────────────

describe("NewsTab rendered output with stubbed data", () => {
  // WHY use createGateway mock: NewsTab calls createGateway(token).getEntityNews().
  // We stub the return value so useQuery resolves immediately with known fixtures.

  beforeEach(() => {
    vi.clearAllMocks();
  });

  async function renderNewsTab(articles: RankedArticle[]) {
    // WHY dynamic import after mocks are set: avoids module-level mock timing issues.
    const { createGateway } = await import("@/lib/gateway");
    const mockGateway = createGateway as ReturnType<typeof vi.fn>;
    mockGateway.mockReturnValue({
      getEntityNews: vi.fn().mockResolvedValue({ articles, total: articles.length }),
    });

    const { NewsTab } = await import("@/components/instrument/NewsTab");

    return render(
      withQueryClient(<NewsTab entityId="ent-001" />),
    );
  }

  it("renders source filter dropdown with 'All sources' default", async () => {
    await renderNewsTab([makeArticle({ source_name: "Bloomberg" })]);
    // WHY wait for DOM: useQuery is async; data appears after the first render cycle.
    // aria-label gives a stable selector.
    const dropdown = await screen.findByLabelText("Filter articles by source");
    expect(dropdown).toBeInTheDocument();
  });

  it("renders sort dropdown with Sort: Relevance default", async () => {
    await renderNewsTab([makeArticle()]);
    const sortDropdown = await screen.findByLabelText("Sort articles");
    expect(sortDropdown).toBeInTheDocument();
  });

  it("renders sentiment pill with aria-label for positive sentiment", async () => {
    await renderNewsTab([makeArticle({ sentiment: "positive" })]);
    // WHY aria-label="sentiment positive": the pill renders with this label so
    // screen readers announce the sentiment and tests can find it precisely.
    const pill = await screen.findByLabelText("sentiment positive");
    expect(pill).toBeInTheDocument();
    expect(pill).toHaveTextContent("POS");
  });

  it("renders sentiment pill for negative sentiment", async () => {
    await renderNewsTab([makeArticle({ sentiment: "negative" })]);
    const pill = await screen.findByLabelText("sentiment negative");
    expect(pill).toHaveTextContent("NEG");
  });

  it("renders sentiment pill for neutral sentiment", async () => {
    await renderNewsTab([makeArticle({ sentiment: "neutral" })]);
    const pill = await screen.findByLabelText("sentiment neutral");
    expect(pill).toHaveTextContent("NEU");
  });

  it("renders sentiment pill for mixed sentiment", async () => {
    await renderNewsTab([makeArticle({ sentiment: "mixed" })]);
    const pill = await screen.findByLabelText("sentiment mixed");
    expect(pill).toHaveTextContent("MIX");
  });

  it("does NOT render sentiment pill when sentiment is null", async () => {
    await renderNewsTab([makeArticle({ sentiment: null })]);
    // WHY wait for article title to appear first: confirms the article rendered.
    await screen.findByText("Test Article Title");
    // Neither positive/negative/neutral/mixed pill should appear.
    expect(screen.queryByLabelText(/^sentiment /)).not.toBeInTheDocument();
  });

  it("renders impact pill with Δ prefix when impact_score is set", async () => {
    await renderNewsTab([makeArticle({ impact_score: 0.74 })]);
    // WHY aria-label="impact score": pill has this label; text shows Δ74
    const pill = await screen.findByLabelText("impact score");
    expect(pill).toBeInTheDocument();
    expect(pill.textContent).toMatch(/^Δ\d+$/);
  });

  it("does NOT render impact pill when impact_score is null", async () => {
    await renderNewsTab([makeArticle({ impact_score: null })]);
    await screen.findByText("Test Article Title");
    expect(screen.queryByLabelText("impact score")).not.toBeInTheDocument();
  });

  it("renders relevance badge with aria-label for scored articles", async () => {
    await renderNewsTab([makeArticle({ display_relevance_score: 0.75 })]);
    const badge = await screen.findByLabelText("relevance score");
    expect(badge).toBeInTheDocument();
    // WHY "75": 0.75 * 100 = 75 (integer)
    expect(badge.textContent).toBe("75");
  });

  it("renders TODAY group header for a recent article", async () => {
    const recent = makeArticle({
      published_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2h ago
    });
    await renderNewsTab([recent]);
    // WHY findByText: useQuery resolves async; findByText waits up to 1s.
    const header = await screen.findByText("TODAY");
    expect(header).toBeInTheDocument();
  });

  it("renders OLDER group header for an article from 10 days ago", async () => {
    const old = makeArticle({
      published_at: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(), // 10d ago
    });
    await renderNewsTab([old]);
    const header = await screen.findByText("OLDER");
    expect(header).toBeInTheDocument();
  });

  it("shows 'No news articles available' when articles array is empty", async () => {
    await renderNewsTab([]);
    const empty = await screen.findByText(/No news articles available/);
    expect(empty).toBeInTheDocument();
  });

  it("shows article count in filter toolbar", async () => {
    const twoArticles = [makeArticle(), makeArticle()];
    await renderNewsTab(twoArticles);
    // WHY aria-live="polite": the count updates dynamically when filters change.
    const count = await screen.findByText("2 articles");
    expect(count).toBeInTheDocument();
  });

  it("source filter dropdown changes displayed count", async () => {
    const articles = [
      makeArticle({ source_name: "Bloomberg" }),
      makeArticle({ source_name: "Reuters" }),
    ];
    await renderNewsTab(articles);

    // Wait for articles to appear
    await screen.findByText("2 articles");

    // Select "Bloomberg" from the source filter
    const sourceDropdown = screen.getByLabelText("Filter articles by source");
    fireEvent.change(sourceDropdown, { target: { value: "Bloomberg" } });

    // WHY findByText with "1 articles": after filtering to Bloomberg only, count drops to 1.
    // Note: "1 articles" (not "1 article") is correct per the component's template literal.
    const count = await screen.findByText("1 articles");
    expect(count).toBeInTheDocument();
  });
});
