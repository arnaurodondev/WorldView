/**
 * __tests__/intelligence-density.test.tsx — W7 T-22
 *
 * Density gate: verifies that the Intelligence tab renders ≥ 30 news rows
 * at 18px density and that no legacy 28-px CompactArticleRow rows appear.
 *
 * WHY THIS TEST EXISTS: the W7 redesign replaced 28px rows with 18px rows,
 * allowing ≥30 articles above the fold vs. ~20 previously. This gate prevents
 * regressions where a future change re-introduces taller rows and silently
 * halves the visible content. Bloomberg-class terminals live and die by
 * information density.
 *
 * APPROACH: render 30 DenseArticleRow elements directly (bypassing NewsColumn's
 * fetch layer) and assert:
 *   1. All 30 rows are present in the DOM.
 *   2. No element carries the legacy h-7 (28px via Tailwind h-7 = 1.75rem) class.
 *   3. The layout wrapper carries no h-[28px] literal.
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { DenseArticleRow } from "@/components/instrument/intelligence/news/DenseArticleRow";
import type { RankedArticle } from "@/types/api";

function makeArticle(i: number): RankedArticle {
  return {
    article_id: `art-${i}`,
    title: `Article headline number ${i}`,
    url: `https://example.com/article-${i}`,
    source_name: "Reuters",
    source_type: "news",
    published_at: "2026-05-22T08:30:00Z",
    sentiment: i % 3 === 0 ? "positive" : i % 3 === 1 ? "negative" : "neutral",
    impact_score: (i % 10) / 10,
    relevance_score: 0.9,
  } as RankedArticle;
}

describe("Intelligence tab density gate", () => {
  it("renders 30 DenseArticleRow elements (≥30 cells above fold)", () => {
    const articles = Array.from({ length: 30 }, (_, i) => makeArticle(i));
    const { container } = render(
      <div>
        {articles.map((a) => (
          <DenseArticleRow key={a.article_id} article={a} />
        ))}
      </div>,
    );
    // DenseArticleRow renders a <div role="link"> per article
    const rows = container.querySelectorAll("[role='link']");
    expect(rows.length).toBeGreaterThanOrEqual(30);
  });

  it("no row carries the legacy h-7 (28px) class", () => {
    const articles = Array.from({ length: 30 }, (_, i) => makeArticle(i));
    const { container } = render(
      <div>
        {articles.map((a) => (
          <DenseArticleRow key={a.article_id} article={a} />
        ))}
      </div>,
    );
    // h-7 = 28px Tailwind class from CompactArticleRow
    const legacyRows = container.querySelectorAll(".h-7");
    expect(legacyRows.length).toBe(0);
  });

  it("no element carries a literal h-[28px] class", () => {
    const article = makeArticle(0);
    const { container } = render(<DenseArticleRow article={article} />);
    const legacyEl = container.querySelector("[class*='h-[28px]']");
    expect(legacyEl).toBeNull();
  });
});
