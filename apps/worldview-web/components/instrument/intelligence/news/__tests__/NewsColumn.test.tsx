/**
 * components/instrument/intelligence/news/__tests__/NewsColumn.test.tsx
 *
 * WHY THIS EXISTS (Round-3 consolidation): NewsColumn migrated from the
 * retired local components/instrument/shared/EmptyState.tsx onto the shared
 * primitives/EmptyState + the reserved "instrument.no-articles" registry key.
 * The local component's contract test (role="status" semantics, inline <svg>
 * icon, headline + hint rendering) was deleted with it — these tests PORT
 * those assertions to the live call site so coverage does not shrink, and pin
 * the NEW Round-3 behaviour: when a sentiment/time filter is active, the
 * empty state offers a one-click "Clear filters" action (registry copy must
 * stay static per DS §15.12, so the old filter-aware hint became an action).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ── Mocks ────────────────────────────────────────────────────────────────────

// WHY mock the hook (not the gateway): NewsColumn's only data dependency is
// useEntityNewsInfinite; mocking at the hook boundary keeps the test free of
// QueryClient + IntersectionObserver plumbing and pins the component contract.
const mockNewsHook = vi.hoisted(() => ({
  state: {
    data: { pages: [{ articles: [] as unknown[] }] },
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
    isLoading: false,
  },
}));

vi.mock("@/components/instrument/hooks/useEntityNewsInfinite", () => ({
  useEntityNewsInfinite: vi.fn(() => mockNewsHook.state),
}));

// jsdom has no IntersectionObserver — stub the constructor the sentinel uses.
class IOStub {
  observe() {}
  disconnect() {}
  unobserve() {}
}
vi.stubGlobal("IntersectionObserver", IOStub);

// IMPORTANT: import AFTER mocks.
// eslint-disable-next-line import/first
import { NewsColumn } from "@/components/instrument/intelligence/news/NewsColumn";

beforeEach(() => {
  mockNewsHook.state = {
    data: { pages: [{ articles: [] }] },
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
    isLoading: false,
  };
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("NewsColumn named empty state (Round-3 consolidation)", () => {
  it("renders the registry copy with role=status and an svg icon (ported contract)", () => {
    render(<NewsColumn entityId="ent-001" />);
    // Registry title + body for "instrument.no-articles".
    expect(screen.getByText("No articles for this entity")).toBeInTheDocument();
    expect(
      screen.getByText(/Articles appear here as the ingestion pipeline links coverage/i),
    ).toBeInTheDocument();
    // Ported from the retired local EmptyState contract test.
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    expect(status.querySelector("svg")).not.toBeNull();
  });

  it("offers no Clear-filters action when no filter is active", () => {
    render(<NewsColumn entityId="ent-001" />);
    expect(screen.queryByRole("button", { name: /clear filters/i })).toBeNull();
  });

  it("offers a Clear-filters action when a filter is active, which resets both filters", () => {
    render(<NewsColumn entityId="ent-001" />);
    // Activate the TODAY time filter via the NewsFilters strip.
    fireEvent.click(screen.getByRole("button", { name: "TODAY" }));
    // The empty state now carries the actionable reset (the most likely cause
    // of zero rows under an active filter is the filter itself).
    const clear = screen.getByRole("button", { name: /clear filters/i });
    fireEvent.click(clear);
    // Both filters reset → the action disappears again (back to the
    // unfiltered empty state).
    expect(screen.queryByRole("button", { name: /clear filters/i })).toBeNull();
  });

  it("renders row-bar skeletons (not a spinner) while loading", () => {
    mockNewsHook.state = { ...mockNewsHook.state, data: undefined as never, isLoading: true };
    render(<NewsColumn entityId="ent-001" />);
    // Round-3 item 4: shape-matched skeleton — h-7 bars matching the 28px
    // CompactArticleRow height; no role=status spinner chrome.
    // Round-4 item 4: skeletons are STATIC per DS §6.2 (raw animate-pulse is
    // banned) — assert via the stable testid, and pin the ban itself.
    expect(screen.getAllByTestId("news-skeleton-row").length).toBeGreaterThan(0);
    expect(document.querySelectorAll(".animate-pulse").length).toBe(0);
  });
});

// ── Round-4 hardening (item 1b): per-section error isolation ─────────────────

describe("NewsColumn per-section error state", () => {
  it("renders a named error with Retry when the cold fetch fails (NOT the empty state)", () => {
    const refetch = vi.fn();
    // WHY cast via never: the hook mock's state literal doesn't declare the
    // full UseInfiniteQueryResult surface — only the fields the component
    // destructures matter for the contract.
    mockNewsHook.state = {
      ...mockNewsHook.state,
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    } as never;
    render(<NewsColumn entityId="ent-001" />);
    // NAMED error — the "no articles" empty state would tell the analyst no
    // coverage exists when the truth is the request failed.
    expect(screen.getByTestId("news-fetch-error")).toBeInTheDocument();
    expect(screen.queryByText("No articles for this entity")).toBeNull();
    // Retry refires the query.
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("keeps loaded articles visible when a background refetch errors (stale beats error)", () => {
    mockNewsHook.state = {
      ...mockNewsHook.state,
      data: {
        pages: [
          {
            articles: [
              {
                article_id: "a1",
                title: "Loaded headline survives the failed refetch",
                source: "wire",
                published_at: "2026-06-10T00:00:00Z",
                sentiment: null,
                url: "https://example.com/a1",
              },
            ],
          },
        ],
      },
      isLoading: false,
      isError: true,
      refetch: vi.fn(),
    } as never;
    render(<NewsColumn entityId="ent-001" />);
    // The error branch is gated on `!data` — already-loaded content wins.
    expect(screen.queryByTestId("news-fetch-error")).toBeNull();
    expect(screen.getByText("Loaded headline survives the failed refetch")).toBeInTheDocument();
  });
});
