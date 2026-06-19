/**
 * events/__tests__/EventsBlock.test.tsx — PLAN-0099 Wave 2.
 *
 * Pins the EVENTS rail block against a mocked GET /v1/entities/{id}/events
 * (useEntityEvents): dense rows with event-type chip + lifecycle-phase chip +
 * mono date, the total badge, and the four states (rows / skeleton / NAMED
 * empty / NAMED error with Retry).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";

const mockUseEntityEvents = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/intelligence", () => ({
  useEntityEvents: mockUseEntityEvents,
}));

import { EventsBlock } from "@/components/instrument/intelligence/events/EventsBlock";
import type { EntityEventsResponse } from "@/lib/api/knowledge-graph";

const EVENTS: EntityEventsResponse = {
  total: 2,
  events: [
    {
      event_id: "ev-1",
      event_type: "regulatory",
      scope: "NATIONAL",
      region: null,
      title: "Regulatory action could cause a 40% drawdown",
      description: "Antitrust filing pending.",
      active_from: "2026-05-15T19:45:18Z",
      active_until: null,
      residual_impact_days: 90,
      lifecycle_phase: "ACTIVE",
      confidence: 0.7,
      exposed_entity_count: 2,
      created_at: "2026-05-21T03:40:33Z",
    },
    {
      event_id: "ev-2",
      event_type: "earnings",
      scope: "COMPANY",
      region: null,
      title: "Q3 earnings window",
      description: null,
      active_from: "2026-04-30T00:00:00Z",
      active_until: "2026-05-02T00:00:00Z",
      residual_impact_days: 5,
      lifecycle_phase: "EXPIRED",
      confidence: 0.9,
      exposed_entity_count: 1,
      created_at: "2026-04-29T00:00:00Z",
    },
  ],
};

function setHookState(state: {
  data?: EntityEventsResponse | null;
  isLoading?: boolean;
  isError?: boolean;
  refetch?: () => void;
}) {
  mockUseEntityEvents.mockReturnValue({
    data: state.data,
    isLoading: state.isLoading ?? false,
    isError: state.isError ?? false,
    refetch: state.refetch ?? vi.fn(),
  });
}

beforeEach(() => mockUseEntityEvents.mockReset());
afterEach(() => cleanup());

describe("EventsBlock rows", () => {
  it("renders one dense row per event with type + lifecycle chips and a date", () => {
    setHookState({ data: EVENTS });
    render(<EventsBlock entityId="ent-001" />);
    expect(screen.getByTestId("event-row-ev-1")).toBeInTheDocument();
    expect(screen.getByTestId("event-row-ev-2")).toBeInTheDocument();
    // Type chip normalises snake_case → spaces.
    expect(screen.getByText("regulatory")).toBeInTheDocument();
    expect(screen.getByText("earnings")).toBeInTheDocument();
    // Lifecycle phase chips — the block's reason to exist.
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
    expect(screen.getByText("EXPIRED")).toBeInTheDocument();
    // Title.
    expect(screen.getByText(/Regulatory action could cause/)).toBeInTheDocument();
  });

  it("shows the total badge in the accent-bar header", () => {
    setHookState({ data: EVENTS });
    render(<EventsBlock entityId="ent-001" />);
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});

describe("EventsBlock states", () => {
  it("renders static skeleton bars while loading", () => {
    setHookState({ isLoading: true });
    render(<EventsBlock entityId="ent-001" />);
    expect(screen.getByTestId("events-skeleton")).toBeInTheDocument();
  });

  it("times the skeleton out to the empty state when loading hangs (DESIGN-QA I-1)", () => {
    // A wedged request keeps isLoading=true forever. Before the fix the rail
    // showed its skeleton indefinitely; now useSkeletonTimeout flips after the
    // budget and the rail falls through to the named empty state (data is null
    // while still "loading", so events == [] → "No events for this entity").
    vi.useFakeTimers();
    try {
      setHookState({ isLoading: true, data: null });
      render(<EventsBlock entityId="ent-001" />);
      // Initially the skeleton is shown.
      expect(screen.getByTestId("events-skeleton")).toBeInTheDocument();
      // Advance past the 12s max-wait budget (act flushes the state update the
      // timer fires so the re-render happens before we assert).
      act(() => vi.advanceTimersByTime(12_500));
      // Skeleton is gone; the designed empty terminal state is shown instead.
      expect(screen.queryByTestId("events-skeleton")).toBeNull();
      expect(screen.getByTestId("events-empty")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the NAMED empty state for zero events (role=status + icon)", () => {
    setHookState({ data: { events: [], total: 0 } });
    render(<EventsBlock entityId="ent-001" />);
    const empty = screen.getByTestId("events-empty");
    expect(empty).toBeInTheDocument();
    expect(empty.getAttribute("role")).toBe("status");
    expect(empty.querySelector("svg")).not.toBeNull();
    expect(screen.getByText("No events for this entity")).toBeInTheDocument();
  });

  it("renders the NAMED error with a working Retry (errors are not emptiness)", () => {
    const refetch = vi.fn();
    setHookState({ isError: true, refetch });
    render(<EventsBlock entityId="ent-001" />);
    expect(screen.getByTestId("events-fetch-error")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("treats a null payload (404 → no events ingested) as the empty state", () => {
    setHookState({ data: null });
    render(<EventsBlock entityId="ent-001" />);
    expect(screen.getByTestId("events-empty")).toBeInTheDocument();
  });
});
