/**
 * news/__tests__/DenseArticleRow.test.tsx — W7 T-23
 *
 * WHY THIS EXISTS: DenseArticleRow is the 18px terminal-density row that
 * replaced CompactArticleRow (28px) in W7 T-04/T-05. We pin 4 contracts:
 *  1. Positive sentiment → bg-positive stripe.
 *  2. Negative sentiment → bg-negative stripe.
 *  3. impact_score ≥ 0.70 → text-positive class on the score element.
 *  4. highlighted=true → ring-1 ring-border wrapper class.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DenseArticleRow } from "@/components/instrument/intelligence/news/DenseArticleRow";
import type { RankedArticle } from "@/types/api";

function makeArticle(overrides: Partial<RankedArticle> = {}): RankedArticle {
  return {
    article_id: "art-001",
    title: "Apple beats earnings expectations",
    url: "https://example.com/article",
    source_name: "Reuters",
    source_type: "news",
    published_at: "2026-05-22T08:30:00Z",
    sentiment: "positive",
    impact_score: 0.75,
    display_relevance_score: 0.9,
    ...overrides,
  } as RankedArticle;
}

describe("DenseArticleRow", () => {
  it("renders a positive-sentiment stripe with bg-positive", () => {
    const { container } = render(<DenseArticleRow article={makeArticle({ sentiment: "positive" })} />);
    // The first child is the 2px stripe div
    const stripe = container.querySelector("[class*='bg-positive']");
    expect(stripe).not.toBeNull();
  });

  it("renders a negative-sentiment stripe with bg-negative", () => {
    const { container } = render(<DenseArticleRow article={makeArticle({ sentiment: "negative" })} />);
    const stripe = container.querySelector("[class*='bg-negative']");
    expect(stripe).not.toBeNull();
  });

  it("applies text-positive to impact score ≥ 0.70", () => {
    const { container } = render(<DenseArticleRow article={makeArticle({ impact_score: 0.82 })} />);
    const scoreEl = container.querySelector("[class*='text-positive']");
    expect(scoreEl).not.toBeNull();
    // Score is rendered as 0–100 integer
    expect(scoreEl?.textContent).toBe("82");
  });

  it("applies ring-1 ring-border when highlighted", () => {
    const { container } = render(<DenseArticleRow article={makeArticle()} highlighted />);
    // DenseArticleRow is a div (role="link"); check its root element
    const root = container.firstElementChild;
    expect(root?.className).toMatch(/ring-1/);
  });

  it("renders the headline text", () => {
    render(<DenseArticleRow article={makeArticle({ title: "Apple beats earnings" })} />);
    expect(screen.getByText("Apple beats earnings")).toBeDefined();
  });
});
