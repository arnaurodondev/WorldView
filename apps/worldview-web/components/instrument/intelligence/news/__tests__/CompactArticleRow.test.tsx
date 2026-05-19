/**
 * components/instrument/intelligence/news/__tests__/CompactArticleRow.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-E-02): CompactArticleRow is the 28-px high
 * news row that fills the Intelligence tab's left rail (PRD-0088 §6.9,
 * T-D-02). The row encodes five atoms in one line; we pin the three most
 * load-bearing rendering contracts:
 *
 *   1. positive sentiment → green dot (bg-positive class).
 *   2. impact_score 0.82 → "82" rendered (0.0–1.0 → 0–100 mapping per PRD-0026).
 *   3. null impact_score → em-dash "—" fallback.
 *
 * WHY a pure props test (no gateway mocks): CompactArticleRow is fully
 * presentational — the parent NewsColumn owns the fetch and pipes a
 * RankedArticle. Driving it directly is the simplest, most stable surface.
 *
 * WHY not also test the cluster_size / dedup branch: cluster sizing is not
 * a visible atom on the 28-px row (only the underlying NewsColumn shows
 * dedup expanders). T-E-02 only requires the three contracts above.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { CompactArticleRow } from "@/components/instrument/intelligence/news/CompactArticleRow";
import type { RankedArticle } from "@/types/api";

/**
 * baseArticle — minimal RankedArticle skeleton with all required fields. The
 * tests override sentiment / impact_score on a per-test basis.
 *
 * WHY all fields explicit (no spread from Partial<RankedArticle>): forces a
 * compile error if RankedArticle's required fields change shape, which would
 * otherwise silently break the test if a runtime null slipped through.
 */
function baseArticle(overrides: Partial<RankedArticle> = {}): RankedArticle {
  return {
    article_id: "art-1",
    title: "Apple beats earnings expectations on iPhone strength",
    url: "https://example.com/a",
    published_at: "2025-05-10T14:30:00Z",
    source_type: "eodhd_news",
    source_name: "Reuters",
    routing_tier: "DEEP",
    routing_score: 0.9,
    market_impact_score: 0.82,
    llm_relevance_score: 0.85,
    display_relevance_score: 0.86,
    primary_entity_id: "ent-001",
    primary_entity_symbol: "AAPL",
    impact_windows: null,
    sentiment: "positive",
    impact_score: 0.82,
    cluster_size: 1,
    ...overrides,
  };
}

describe("CompactArticleRow", () => {
  it("renders the headline text and source name", () => {
    render(<CompactArticleRow article={baseArticle()} />);
    // WHY substring: title may be truncated by CSS — getByText defaults to
    // exact text match, so we use a regex.
    expect(
      screen.getByText(/Apple beats earnings expectations/),
    ).toBeInTheDocument();
    expect(screen.getByText("Reuters")).toBeInTheDocument();
  });

  it("uses the green (positive) sentiment dot class when sentiment='positive'", () => {
    const { container } = render(<CompactArticleRow article={baseArticle({ sentiment: "positive" })} />);
    // WHY class-name selector: the dot is a styled <div> with no text — the
    // only stable contract is the bg-positive class that drives the colour.
    const dot = container.querySelector(".bg-positive");
    expect(dot).not.toBeNull();
  });

  it("uses the red (negative) sentiment dot when sentiment='negative'", () => {
    const { container } = render(<CompactArticleRow article={baseArticle({ sentiment: "negative" })} />);
    const dot = container.querySelector(".bg-negative");
    expect(dot).not.toBeNull();
  });

  it("renders the impact score as the rounded 0–100 integer (0.82 → '82')", () => {
    render(<CompactArticleRow article={baseArticle({ impact_score: 0.82 })} />);
    // WHY exact "82": the formatting rule is Math.round(score * 100); 0.82
    // is unambiguous (no rounding boundary).
    expect(screen.getByText("82")).toBeInTheDocument();
  });

  it("renders em-dash '—' when impact_score is null", () => {
    render(<CompactArticleRow article={baseArticle({ impact_score: null })} />);
    // The em-dash is a visible label — multiple "—" placeholders may appear
    // in a future variant, so we use getAllByText and assert at least one.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });
});
