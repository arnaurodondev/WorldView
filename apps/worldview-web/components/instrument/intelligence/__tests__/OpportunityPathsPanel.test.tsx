/**
 * __tests__/OpportunityPathsPanel.test.tsx — Unit tests for OpportunityPathsPanel
 *
 * WHY THIS EXISTS:
 * OpportunityPathsPanel fetches async path data and has four distinct render
 * states (loading, data, empty, error). Without tests, any regression in the
 * loading/error branch is invisible until a browser QA session. These tests pin
 * the four states so CI catches regressions immediately.
 *
 * TEST STRATEGY:
 * Mock useEntityPaths (the TanStack Query hook) at the module level so we can
 * control what state it returns for each test. This avoids needing a real
 * QueryClient, MSW, or network layer — OpportunityPathsPanel is pure presentation
 * above the hook boundary.
 *
 * WHY vi.mock at the module level (not in each test):
 * Vitest hoists vi.mock() calls to the top of the file. If we mocked inside
 * individual tests, the module would already be imported with the real implementation.
 * The module-level mock gives us a stable vi.fn() we can control per-test via
 * mockReturnValue / mockImplementation.
 *
 * WHY we don't need QueryClientProvider:
 * Because we mock useEntityPaths entirely, the component never calls
 * useQuery internally (the hook is replaced). No QueryClient needed.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { EntityPathsResponse, PathInsightPublic } from "@/types/intelligence";

// ── Mock useEntityPaths before the component is imported ──────────────────────
// WHY mock the whole module: OpportunityPathsPanel calls useEntityPaths() which
// internally calls useQuery (browser-only). Mocking the whole module replaces
// useEntityPaths with a vi.fn() stub that returns whatever we configure per test.
vi.mock("@/lib/api/intelligence", () => ({
  useEntityPaths: vi.fn(),
}));

// Import AFTER the mock is set up — Vitest hoists vi.mock() so this import
// will get the mocked version of the module, not the real one.
// eslint-disable-next-line import/first
import { OpportunityPathsPanel } from "@/components/instrument/intelligence/OpportunityPathsPanel";
// eslint-disable-next-line import/first
import { useEntityPaths } from "@/lib/api/intelligence";

// ── Typed mock reference ──────────────────────────────────────────────────────
// WHY cast to vi.Mock: vi.mock replaces the export with a vi.fn(), but TypeScript
// still thinks it's the original function type. The cast lets us call
// mockReturnValue() without a type error.
const mockUseEntityPaths = useEntityPaths as ReturnType<typeof vi.fn>;

// ── Test fixtures ─────────────────────────────────────────────────────────────

/**
 * makePath — builds a minimal PathInsightPublic fixture.
 *
 * WHY a factory (not a static const): different tests need paths with different
 * entity names and relation types. The factory takes overrides so each test
 * expresses only what it cares about, not the full object shape.
 */
function makePath(overrides: Partial<PathInsightPublic> = {}): PathInsightPublic {
  return {
    insight_id: "path-001",
    hop_count: 2,
    harmonic_score: 0.75,
    diversity_score: 0.6,
    surprise_score: 0.5,
    template_match: null,
    composite_score: 0.72,
    path_nodes: [
      // index 0 = subject entity (not shown in the label)
      { entity_id: "ent-001", name: "Apple Inc.", entity_type: "company" },
      // index 1 = first hop (shown)
      { entity_id: "ent-002", name: "TSMC", entity_type: "company" },
    ],
    path_edges: [
      { relation_type: "SUPPLIER_OF", confidence: 0.88 },
    ],
    llm_explanation: null,
    explanation_pending: false,
    computed_at: "2026-05-22T10:00:00Z",
    ...overrides,
  };
}

/**
 * makeQueryResult — wraps a partial UseQueryResult so TypeScript is happy.
 *
 * WHY partial cast: UseQueryResult has ~30 fields. Tests only care about
 * data/isLoading/isError. We cast the rest to satisfy the type without
 * specifying them all.
 */
function makeQueryResult(
  partial: Partial<UseQueryResult<EntityPathsResponse, Error>>,
): UseQueryResult<EntityPathsResponse, Error> {
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
    promise: Promise.resolve({} as EntityPathsResponse),
    ...partial,
  } as UseQueryResult<EntityPathsResponse, Error>;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("OpportunityPathsPanel", () => {
  beforeEach(() => {
    // WHY reset: if a previous test left mockReturnValue set, the next test
    // would inherit that value. Resetting ensures each test configures its own state.
    mockUseEntityPaths.mockReset();
  });

  // ── T1: loading state ──────────────────────────────────────────────────────

  it("renders skeleton rows when the query is pending", () => {
    // WHY isLoading: true (not isPending): TanStack Query's isLoading is true when
    // the query has no data yet and is currently fetching. isPending can be true
    // for disabled queries too. isLoading matches "first fetch in progress."
    mockUseEntityPaths.mockReturnValue(
      makeQueryResult({ isLoading: true, data: undefined }),
    );

    const { container } = render(
      <OpportunityPathsPanel entityId="ent-001" />,
    );

    // WHY check aria-busy: screen readers need to know content is loading.
    // We assert on the aria attribute so the test also verifies accessibility.
    const loadingRegion = container.querySelector("[aria-busy='true']");
    expect(loadingRegion).not.toBeNull();

    // WHY count children: we always show 5 skeleton rows (matches the limit=5
    // data request). Verifying count ensures no layout regression.
    const skeletonRows = loadingRegion!.children;
    expect(skeletonRows.length).toBe(5);

    // WHY check animate-pulse: the skeleton uses Tailwind's animate-pulse class;
    // if it were missing the skeletons would be static shapes with no visual cue.
    const firstRow = skeletonRows[0];
    expect(firstRow?.className).toContain("animate-pulse");
  });

  // ── T2: data state ─────────────────────────────────────────────────────────

  it("renders path rows when data is available", () => {
    // Arrange: two paths with different relation types and scores
    const path1 = makePath({
      insight_id: "path-001",
      composite_score: 0.82,
      path_nodes: [
        { entity_id: "ent-001", name: "Apple Inc.", entity_type: "company" },
        { entity_id: "ent-002", name: "TSMC", entity_type: "company" },
      ],
      path_edges: [{ relation_type: "SUPPLIER_OF", confidence: 0.9 }],
    });

    const path2 = makePath({
      insight_id: "path-002",
      composite_score: 0.67,
      path_nodes: [
        { entity_id: "ent-001", name: "Apple Inc.", entity_type: "company" },
        { entity_id: "ent-003", name: "Samsung", entity_type: "company" },
        { entity_id: "ent-004", name: "Google", entity_type: "company" },
      ],
      path_edges: [
        { relation_type: "COMPETES_WITH", confidence: 0.75 },
        { relation_type: "PARTNER_OF", confidence: 0.6 },
      ],
    });

    mockUseEntityPaths.mockReturnValue(
      makeQueryResult({
        isLoading: false,
        isError: false,
        isSuccess: true,
        data: {
          entity_id: "ent-001",
          paths: [path1, path2],
          total: 2,
          freshness_ts: "2026-05-22T10:00:00Z",
        },
      }),
    );

    render(<OpportunityPathsPanel entityId="ent-001" />);

    // WHY check section header: it should always be present in the data state
    expect(screen.getByText(/opportunity paths/i)).toBeInTheDocument();

    // WHY check "TSMC": it's path1's first hop (index 1 node) → appears in label
    expect(screen.getByText("TSMC")).toBeInTheDocument();

    // WHY check "Samsung → Google": path2 has two hops; both should appear joined
    // with an arrow in the label
    expect(screen.getByText("Samsung → Google")).toBeInTheDocument();

    // WHY check relation label: the first edge type is shown as an uppercase badge
    // with underscores replaced by spaces — "SUPPLIER OF" for path1
    expect(screen.getByText(/supplier of/i)).toBeInTheDocument();

    // WHY check score format: formatted to 2 decimal places, tabular-nums aligned
    expect(screen.getByText("0.82")).toBeInTheDocument();
    expect(screen.getByText("0.67")).toBeInTheDocument();

    // WHY no "No paths found" text: confirms we're NOT in the empty state
    expect(screen.queryByText(/no paths found/i)).not.toBeInTheDocument();
  });

  // ── T3: empty state ────────────────────────────────────────────────────────

  it("renders 'No paths found' when the paths array is empty", () => {
    // WHY empty array (not undefined): the API returns an EntityPathsResponse
    // with paths: [] for entities with sparse KGs — not a null/undefined.
    mockUseEntityPaths.mockReturnValue(
      makeQueryResult({
        isLoading: false,
        isError: false,
        isSuccess: true,
        data: {
          entity_id: "ent-001",
          paths: [],
          total: 0,
          freshness_ts: null,
        },
      }),
    );

    render(<OpportunityPathsPanel entityId="ent-001" />);

    // WHY text match: this exact string is specified in the design spec
    expect(screen.getByText(/no paths found/i)).toBeInTheDocument();

    // WHY no error message: empty paths is a data state, not an error state.
    // The error message would only show when isError=true.
    expect(screen.queryByText(/failed to load/i)).not.toBeInTheDocument();

    // WHY no skeleton: the query resolved successfully — no loading indicators
    expect(document.querySelector("[aria-busy='true']")).toBeNull();
  });

  // ── T4: error state ────────────────────────────────────────────────────────

  it("renders inline error message when useEntityPaths returns isError=true", () => {
    // WHY isError: true instead of throwing: useEntityPaths catches the error
    // internally (TanStack Query catches all queryFn rejections). The component
    // never sees a thrown error — it reads isError from the hook result.
    mockUseEntityPaths.mockReturnValue(
      makeQueryResult({
        isLoading: false,
        isError: true,
        isSuccess: false,
        data: undefined,
        error: new Error("Network error"),
      }),
    );

    render(<OpportunityPathsPanel entityId="ent-001" />);

    // WHY "Failed to load paths": design spec mandates this exact message in
    // text-[#EF5350] (red). The test checks text content; color is a snapshot concern.
    expect(screen.getByText(/failed to load paths/i)).toBeInTheDocument();

    // WHY no "No paths found": error and empty states are mutually exclusive
    expect(screen.queryByText(/no paths found/i)).not.toBeInTheDocument();

    // WHY no skeleton: the query has resolved (with an error), not pending
    expect(document.querySelector("[aria-busy='true']")).toBeNull();
  });

  // ── T5: useEntityPaths called with correct params ──────────────────────────

  it("calls useEntityPaths with entityId and fixed filters limit=5 minScore=0.4", () => {
    // WHY this test: if someone changes the filter defaults, the right-rail
    // query silently changes character (returning too many / low-quality paths).
    // Pinning the call signature here makes that change explicit.
    mockUseEntityPaths.mockReturnValue(
      makeQueryResult({
        isLoading: true,
        data: undefined,
      }),
    );

    render(<OpportunityPathsPanel entityId="ent-xyz" />);

    // WHY toHaveBeenCalledWith: exact param match ensures the design-spec values
    // (limit=5, minScore=0.4) are always passed — not defaults from the hook.
    expect(mockUseEntityPaths).toHaveBeenCalledWith("ent-xyz", {
      limit: 5,
      minScore: 0.4,
    });
  });
});
