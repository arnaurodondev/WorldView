/**
 * __tests__/entity-predictions-section.test.tsx — EntityPredictionsSection
 * (PLAN-0056 Wave E2, task 6): renders rows, polarity colours + a working link.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { EntityPredictionsResponse } from "@/types/api";

const mockUseEntityPredictions = vi.fn();
vi.mock("@/lib/api/prediction-markets-hooks", () => ({
  useEntityPredictions: (entityId: string, params: unknown) =>
    mockUseEntityPredictions(entityId, params),
}));

import { EntityPredictionsSection } from "@/components/intelligence/EntityPredictionsSection";

function resp(items: EntityPredictionsResponse["items"]): EntityPredictionsResponse {
  return { items, total: items.length, limit: 10, offset: 0 };
}

beforeEach(() => mockUseEntityPredictions.mockReset());

describe("EntityPredictionsSection", () => {
  it("renders a row per linked market with the question and header", () => {
    mockUseEntityPredictions.mockReturnValue({
      data: resp([
        { condition_id: "c1", question: "Will Apple ship a foldable in 2026?", polarity: "bullish", polarity_confidence: 0.8, close_time: null, confidence: 0.9 },
        { condition_id: "c2", question: "Will the DOJ break up Apple?", polarity: "bearish", polarity_confidence: 0.6, close_time: null, confidence: 0.7 },
      ]),
      isLoading: false,
      isError: false,
    });
    render(<EntityPredictionsSection entityId="e1" />);

    expect(screen.getByText(/prediction markets/i)).toBeInTheDocument();
    expect(screen.getByText("Will Apple ship a foldable in 2026?")).toBeInTheDocument();
    expect(screen.getAllByTestId("entity-prediction-row")).toHaveLength(2);
  });

  it("colours polarity: bullish green, bearish red, neutral muted", () => {
    mockUseEntityPredictions.mockReturnValue({
      data: resp([
        { condition_id: "c1", question: "bull", polarity: "bullish", polarity_confidence: null, close_time: null, confidence: 0.9 },
        { condition_id: "c2", question: "bear", polarity: "bearish", polarity_confidence: null, close_time: null, confidence: 0.9 },
        { condition_id: "c3", question: "neut", polarity: "neutral", polarity_confidence: null, close_time: null, confidence: 0.9 },
      ]),
      isLoading: false,
      isError: false,
    });
    render(<EntityPredictionsSection entityId="e1" />);

    const indicators = screen.getAllByTestId("polarity-indicator");
    expect(indicators[0]).toHaveAttribute("data-polarity", "bullish");
    expect(indicators[0].className).toContain("text-positive");
    expect(indicators[1]).toHaveAttribute("data-polarity", "bearish");
    expect(indicators[1].className).toContain("text-negative");
    expect(indicators[2]).toHaveAttribute("data-polarity", "neutral");
    expect(indicators[2].className).toContain("text-muted-foreground");
  });

  it("links each row to a Polymarket URL", () => {
    mockUseEntityPredictions.mockReturnValue({
      data: resp([
        { condition_id: "c1", question: "Will X happen?", polarity: null, polarity_confidence: null, close_time: null, confidence: 0.5 },
      ]),
      isLoading: false,
      isError: false,
    });
    render(<EntityPredictionsSection entityId="e1" />);
    const link = screen.getByTestId("entity-prediction-row");
    expect(link).toHaveAttribute("href", expect.stringContaining("polymarket.com"));
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("renders nothing when the entity has no linked markets", () => {
    mockUseEntityPredictions.mockReturnValue({ data: resp([]), isLoading: false, isError: false });
    const { container } = render(<EntityPredictionsSection entityId="e1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a loading skeleton while pending", () => {
    mockUseEntityPredictions.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(<EntityPredictionsSection entityId="e1" />);
    expect(screen.getByTestId("entity-predictions-loading")).toBeInTheDocument();
  });
});
