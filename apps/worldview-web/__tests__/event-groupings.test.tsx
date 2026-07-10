/**
 * __tests__/event-groupings.test.tsx — EventGroupings (PLAN-0056 Wave E2,
 * task 5): renders event groups and expands/collapses.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { PredictionEventsResponse } from "@/types/api";

const mockUsePredictionEvents = vi.fn();
vi.mock("@/lib/api/prediction-markets-hooks", () => ({
  usePredictionEvents: (params: unknown) => mockUsePredictionEvents(params),
}));

import { EventGroupings } from "@/components/prediction-markets/EventGroupings";

function resp(items: PredictionEventsResponse["items"]): PredictionEventsResponse {
  return { items, total: items.length, limit: 25, offset: 0 };
}

beforeEach(() => mockUsePredictionEvents.mockReset());

describe("EventGroupings", () => {
  it("renders nothing when there are no events", () => {
    mockUsePredictionEvents.mockReturnValue({ data: resp([]), isLoading: false, isError: false });
    const { container } = render(<EventGroupings />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the collapsed section header with a count", () => {
    mockUsePredictionEvents.mockReturnValue({
      data: resp([
        { event_id: "ev1", name: "US Election 2026", category: "politics", start_date: null, end_date: null, market_count: 12 },
      ]),
      isLoading: false,
      isError: false,
    });
    render(<EventGroupings />);
    expect(screen.getByText("Events")).toBeInTheDocument();
    // Section starts collapsed → event rows are not shown yet.
    expect(screen.queryByTestId("event-row")).not.toBeInTheDocument();
  });

  it("expands to reveal event rows, then each row expands to its metadata", () => {
    mockUsePredictionEvents.mockReturnValue({
      data: resp([
        { event_id: "ev1", name: "US Election 2026", category: "politics", start_date: null, end_date: null, market_count: 12 },
      ]),
      isLoading: false,
      isError: false,
    });
    render(<EventGroupings />);

    // Expand the section.
    fireEvent.click(screen.getByRole("button", { name: /events/i }));
    expect(screen.getByTestId("event-row")).toBeInTheDocument();
    expect(screen.getByText("US Election 2026")).toBeInTheDocument();
    // Row body is collapsed until the row is clicked.
    expect(screen.queryByTestId("event-row-body")).not.toBeInTheDocument();

    // Expand the row.
    fireEvent.click(screen.getByText("US Election 2026"));
    expect(screen.getByTestId("event-row-body")).toBeInTheDocument();
  });
});
