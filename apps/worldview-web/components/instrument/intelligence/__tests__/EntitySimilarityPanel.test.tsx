/**
 * __tests__/EntitySimilarityPanel.test.tsx — Unit tests for EntitySimilarityPanel
 *
 * WHY THIS EXISTS:
 * EntitySimilarityPanel has five distinct render states (loading, error, null/no-embedding,
 * empty results, data). Without tests, regressions in the loading skeleton or the COMP
 * badge are invisible until a browser QA session. These tests pin the rendering contract
 * so CI catches regressions immediately.
 *
 * TEST STRATEGY:
 * Mock the gateway's getSimilarEntities at the module level so we can control
 * what state the query returns for each test. We also mock:
 *   - createGateway    — returns an object with mocked getSimilarEntities
 *   - useAccessToken   — returns a fake token (non-null) so `enabled` fires
 *   - @tanstack/react-query useQuery — returns a controlled result
 *
 * WHY mock useQuery directly (not createGateway + QueryClientProvider):
 * Setting up a real QueryClientProvider + MSW would add 50+ lines of boilerplate
 * for a component whose query has a fixed shape. Mocking useQuery at the module
 * level lets each test express exactly which state it cares about in 3 lines,
 * matching the OpportunityPathsPanel test strategy.
 *
 * WHY vi.mock at module level:
 * Vitest hoists vi.mock() calls before imports. Module-level mocks give us a
 * stable vi.fn() we can control per-test via mockReturnValue.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { SimilarEntitiesResponse } from "@/types/api";

// ── Mock useAccessToken so `enabled` is always true (token is present) ──────────
// WHY: without a token, the query is disabled and the component renders nothing
// (or the loading skeleton forever). We give it a fake token so the `enabled`
// guard passes and the query attempts to run — then useQuery's mock controls
// what data state the component actually sees.
vi.mock("@/lib/api-client", () => ({
  useAccessToken: vi.fn(() => "test-token"),
}));

// ── Mock createGateway so it never hits the network ──────────────────────────────
// WHY: EntitySimilarityPanel calls createGateway(token).getSimilarEntities(...)
// inside useQuery's queryFn. We don't actually reach the queryFn in these tests
// (useQuery itself is mocked), but the import must resolve without error.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getSimilarEntities: vi.fn(),
  })),
}));

// ── Mock useQuery so we control each render state ─────────────────────────────────
// WHY mock @tanstack/react-query and not the whole component: the component's
// rendering logic (which state to show) is exactly what we're testing. Mocking
// useQuery lets us drive each state (loading/error/null/empty/data) without a
// network layer, QueryClient, or server.
vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn(),
}));

// Import AFTER mocks are set up (Vitest hoists vi.mock, so these see the mocked modules).
// eslint-disable-next-line import/first
import { EntitySimilarityPanel } from "@/components/instrument/intelligence/EntitySimilarityPanel";
// eslint-disable-next-line import/first
import { useQuery } from "@tanstack/react-query";

// ── Typed mock reference ──────────────────────────────────────────────────────────
// WHY cast: vi.mock replaces useQuery with a vi.fn() but TypeScript still knows
// the original type. Cast to vi.Mock so we can call mockReturnValue() in each test.
const mockUseQuery = useQuery as ReturnType<typeof vi.fn>;

// ── Fixture factory ───────────────────────────────────────────────────────────────

/**
 * makeQueryResult — wraps a partial UseQueryResult for SimilarEntitiesResponse | null.
 *
 * WHY partial cast: UseQueryResult has ~30 fields. Tests only care about
 * isLoading/isError/data. We spread defaults and cast to avoid specifying them all.
 */
function makeQueryResult(
  partial: Partial<UseQueryResult<SimilarEntitiesResponse | null, Error>>,
): UseQueryResult<SimilarEntitiesResponse | null, Error> {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    isPending: false,
    isSuccess: false,
    isFetching: false,
    isRefetching: false,
    status: "pending",
    fetchStatus: "idle",
    error: null,
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    errorUpdateCount: 0,
    isFetchedAfterMount: false,
    isFetched: false,
    isLoadingError: false,
    isRefetchError: false,
    isPlaceholderData: false,
    isStale: false,
    isInitialLoading: false,
    isPaused: false,
    refetch: vi.fn(),
    promise: Promise.resolve(null),
    ...partial,
  } as UseQueryResult<SimilarEntitiesResponse | null, Error>;
}

/**
 * makeItem — builds a minimal SimilarEntityItem fixture.
 *
 * WHY factory (not static const): tests need items with different names, scores,
 * tickers, and has_competes_with_relation values. A factory lets each test express
 * only what it cares about.
 */
function makeItem(overrides: Partial<SimilarEntitiesResponse["results"][0]> = {}) {
  return {
    entity_id: "ent-001",
    canonical_name: "Microsoft Corporation",
    entity_type: "company",
    ticker: "MSFT",
    exchange: "NASDAQ",
    ann_similarity_score: 0.87,
    competes_with_confidence: 0.92,
    final_score: 0.87,
    has_competes_with_relation: false,
    ...overrides,
  };
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("EntitySimilarityPanel", () => {
  beforeEach(() => {
    // WHY reset: ensures each test starts with a clean mockReturnValue and doesn't
    // inherit state from the previous test.
    mockUseQuery.mockReset();
  });

  // ── T1: loading state ────────────────────────────────────────────────────────

  it("renders 5 skeleton rows when the query is pending", () => {
    // WHY isLoading:true (not isPending): isLoading is true when the query has no
    // cached data and is currently fetching — the correct "first load" state.
    // isPending can be true for disabled queries too (if enabled=false).
    mockUseQuery.mockReturnValue(
      makeQueryResult({ isLoading: true, data: undefined }),
    );

    const { container } = render(<EntitySimilarityPanel entityId="ent-001" />);

    // WHY aria-busy: signals to screen readers that content is loading
    const loadingRegion = container.querySelector("[aria-busy='true']");
    expect(loadingRegion).not.toBeNull();

    // WHY 5 skeletons: matches topK=5 so layout doesn't shift on data arrival.
    // Count via animate-pulse class which is applied to every skeleton row.
    const skeletons = loadingRegion!.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBe(5);
  });

  // ── T2: data state — 5 entity rows ──────────────────────────────────────────

  it("renders 5 entity rows with names and similarity percentages", () => {
    // Arrange: 5 items with different scores and names
    const items = [
      makeItem({ entity_id: "e1", canonical_name: "Microsoft Corporation", ticker: "MSFT", final_score: 0.91 }),
      makeItem({ entity_id: "e2", canonical_name: "Alphabet Inc.", ticker: "GOOGL", final_score: 0.87 }),
      makeItem({ entity_id: "e3", canonical_name: "Meta Platforms", ticker: "META", final_score: 0.82 }),
      makeItem({ entity_id: "e4", canonical_name: "Amazon.com Inc.", ticker: "AMZN", final_score: 0.79 }),
      makeItem({ entity_id: "e5", canonical_name: "NVIDIA Corporation", ticker: "NVDA", final_score: 0.74 }),
    ];

    mockUseQuery.mockReturnValue(
      makeQueryResult({
        isLoading: false,
        isError: false,
        isSuccess: true,
        data: {
          entity_id: "ent-apple",
          canonical_name: "Apple Inc.",
          results: items,
          total: 5,
        },
      }),
    );

    render(<EntitySimilarityPanel entityId="ent-apple" />);

    // WHY check panel header: SIMILAR ENTITIES header must always be present
    expect(screen.getByText(/SIMILAR ENTITIES/i)).toBeInTheDocument();

    // WHY check specific names: company names are the primary information in each row
    expect(screen.getByText("Microsoft Corporation")).toBeInTheDocument();
    expect(screen.getByText("Alphabet Inc.")).toBeInTheDocument();
    expect(screen.getByText("NVIDIA Corporation")).toBeInTheDocument();

    // WHY check score percentages: final_score=0.91 → "91%", 0.74 → "74%"
    // tabular-nums + font-mono classes pin the numeric rendering
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(screen.getByText("74%")).toBeInTheDocument();

    // WHY check tickers: ticker appears after the name for tradable entities
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
  });

  // ── T3: COMP badge ───────────────────────────────────────────────────────────

  it("renders 'COMP' badge only for entities with has_competes_with_relation=true", () => {
    // WHY two items: one competitor (badge shown), one non-competitor (badge hidden).
    // This ensures the badge is not rendered unconditionally on every row.
    const items = [
      makeItem({ entity_id: "e1", canonical_name: "Microsoft Corporation", has_competes_with_relation: true }),
      makeItem({ entity_id: "e2", canonical_name: "Alphabet Inc.", has_competes_with_relation: false }),
    ];

    mockUseQuery.mockReturnValue(
      makeQueryResult({
        isLoading: false,
        isSuccess: true,
        data: { entity_id: "ent-apple", canonical_name: "Apple Inc.", results: items, total: 2 },
      }),
    );

    render(<EntitySimilarityPanel entityId="ent-apple" />);

    // WHY exactly 1 COMP badge: only Microsoft has the competes_with relation
    const compBadges = screen.getAllByText("COMP");
    expect(compBadges.length).toBe(1);

    // WHY no badge for Alphabet: has_competes_with_relation=false must produce no badge
    expect(screen.getByText("Alphabet Inc.")).toBeInTheDocument();
  });

  // ── T4: empty state ──────────────────────────────────────────────────────────

  it("renders 'No similar entities found' when results array is empty", () => {
    // WHY empty array (not null): the API returns { results: [] } for entities
    // whose embedding has no close neighbours — distinct from null (no embedding).
    mockUseQuery.mockReturnValue(
      makeQueryResult({
        isLoading: false,
        isSuccess: true,
        data: { entity_id: "ent-001", canonical_name: "Unknown Corp", results: [], total: 0 },
      }),
    );

    render(<EntitySimilarityPanel entityId="ent-001" />);

    expect(screen.getByText(/No similar entities found/i)).toBeInTheDocument();

    // WHY no COMP badge: empty results means zero entity rows
    expect(screen.queryByText("COMP")).not.toBeInTheDocument();

    // WHY no loading skeleton: query resolved (isLoading=false)
    expect(document.querySelector(".animate-pulse")).toBeNull();
  });

  // ── T5: null state (no embedding computed yet) ───────────────────────────────

  it("renders 'No embedding available' when getSimilarEntities returns null", () => {
    // WHY data: null (not undefined): the gateway returns null for 404/422 responses
    // (entity not in KG or embedding not computed yet). useQuery resolves to null.
    // This is different from isLoading (undefined data) and isError (thrown).
    mockUseQuery.mockReturnValue(
      makeQueryResult({
        isLoading: false,
        isSuccess: true,
        data: null,
      }),
    );

    render(<EntitySimilarityPanel entityId="ent-001" />);

    expect(screen.getByText(/No embedding available/i)).toBeInTheDocument();

    // WHY no "No similar entities found": null and empty are distinct states —
    // null = no embedding; empty = embedding exists but no neighbours found.
    expect(screen.queryByText(/No similar entities found/i)).not.toBeInTheDocument();
  });

  // ── T6: error state ──────────────────────────────────────────────────────────

  it("renders 'Similarity data unavailable' when the query fails", () => {
    // WHY isError:true (not thrown): TanStack Query catches queryFn rejections internally.
    // The component reads isError from the hook result — it never sees a thrown error.
    mockUseQuery.mockReturnValue(
      makeQueryResult({
        isLoading: false,
        isError: true,
        data: undefined,
        error: new Error("Network timeout"),
      }),
    );

    render(<EntitySimilarityPanel entityId="ent-001" />);

    expect(screen.getByText(/Similarity data unavailable/i)).toBeInTheDocument();

    // WHY no loading skeleton: error means the query resolved (with failure)
    expect(document.querySelector(".animate-pulse")).toBeNull();
  });
});
