/**
 * __tests__/primitives/DenseArticleRow.test.tsx
 *
 * PRD-0089 F1: pins density classes + sentiment-stripe color wiring.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DenseArticleRow } from "@/components/primitives/DenseArticleRow";

const baseArticle = {
  id: "a1",
  title: "Apple beats earnings",
  source: "Reuters",
  publishedAt: "2026-05-20T14:21:08Z",
  sentiment: 0.6,
};

describe("DenseArticleRow", () => {
  it("renders the title and applies terminal density (18px) by default", () => {
    render(<DenseArticleRow article={baseArticle} />);
    const row = screen.getByRole("row");
    expect(row.className).toContain("h-[18px]");
    expect(screen.getByText("Apple beats earnings")).toBeInTheDocument();
  });

  it("renders the positive sentiment stripe when sentiment ≥ 0.15", () => {
    const { container } = render(<DenseArticleRow article={baseArticle} />);
    const stripe = container.querySelector('[aria-hidden="true"]');
    expect(stripe?.className).toContain("bg-positive");
  });

  it("renders the muted stripe when sentiment is null", () => {
    const { container } = render(
      <DenseArticleRow article={{ ...baseArticle, sentiment: null }} />,
    );
    const stripe = container.querySelector('[aria-hidden="true"]');
    expect(stripe?.className).toContain("bg-muted-foreground/30");
  });
});
