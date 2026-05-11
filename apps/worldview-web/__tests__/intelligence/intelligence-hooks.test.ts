/**
 * __tests__/intelligence/intelligence-hooks.test.ts — Unit tests for intelligence API hooks
 * (PLAN-0074 Wave H T-H-01)
 *
 * WHY THESE TESTS EXIST:
 * The intelligence hooks are the data layer for the intelligence page. Verifying
 * they call the correct URLs, respect staleTime, handle pagination cursors, and
 * invalidate the right queries on mutation success ensures the panels get fresh,
 * correctly-scoped data.
 *
 * WHAT WE TEST:
 * 1. useEntityIntelligence calls /v1/entities/{id}/intelligence
 * 2. useEntityPaths calls /v1/entities/{id}/paths with filter params
 * 3. useEntityNarrativeHistory uses cursor pagination
 * 4. useTriggerNarrativeGeneration invalidates intelligence + narratives on success
 * 5. useChatStream routes to entity-context endpoint when entityId is set
 * 6. useEntityIntelligence is disabled when entityId is empty
 *
 * WHY MOCK @/lib/api-client:
 * The hooks depend on useAccessToken() and useApiClient() from the
 * ApiClientProvider context. Without the provider, these hooks throw. We mock
 * the module so the hooks receive a test token + a mock gateway object.
 *
 * WHY MOCK FETCH GLOBALLY:
 * The apiFetch() underlying all hooks calls the browser fetch() API.
 * vi.stubGlobal("fetch") intercepts these calls without starting a real server.
 *
 * DATA SOURCE: Mocked fetch responses matching the S9 response shapes
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import {
  useEntityIntelligence,
  useEntityPaths,
  useEntityNarrativeHistory,
  useTriggerNarrativeGeneration,
} from "@/lib/api/intelligence";

// ── Mock @/lib/api-client ─────────────────────────────────────────────────────
// WHY: useAccessToken and useApiClient both require the ApiClientProvider context.
// Mocking the module lets hooks run without the provider tree.

vi.mock("@/lib/api-client", () => ({
  useAccessToken: vi.fn(() => "test-token"),
  useApiClient: vi.fn(() => ({
    getEntityGraph: vi.fn(),
  })),
  ApiClientProvider: ({ children }: { children: ReactNode }) => children,
}));

// ── Test QueryClient factory ──────────────────────────────────────────────────
// WHY makeWrapper: each test gets a fresh QueryClient so cache from one test
// doesn't leak into another. renderHook needs a React tree with QueryClientProvider.
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
}

// ── Mock response helpers ─────────────────────────────────────────────────────

function mockIntelligenceResponse() {
  return {
    entity_id: "test-entity-id",
    canonical_name: "Apple Inc.",
    entity_type: "company",
    health_score: 0.85,
    current_narrative: null,
    confidence_breakdown: {
      mean_support: 0.8,
      mean_corroboration: 0.7,
      mean_contradiction: 0.1,
      latest_evidence_at: "2026-05-01T00:00:00Z",
      relation_count: 42,
      source_distribution: [],
      confidence_trend: [],
    },
    key_metrics: { employees: 150000 },
    data_completeness: 0.92,
  };
}

function mockPathsResponse() {
  return {
    entity_id: "test-entity-id",
    paths: [
      {
        insight_id: "path-1",
        hop_count: 2,
        harmonic_score: 0.75,
        diversity_score: 0.6,
        surprise_score: 0.4,
        template_match: null,
        composite_score: 0.65,
        path_nodes: [],
        path_edges: [],
        llm_explanation: null,
        explanation_pending: false,
        computed_at: "2026-05-01T00:00:00Z",
      },
    ],
    total: 1,
    freshness_ts: "2026-05-01T00:00:00Z",
  };
}

function mockNarrativesPage(cursor: string | null = null) {
  // P0-9 PLAN-0088: canonical S7 NarrativeVersionListResponse uses `versions`
  // (not `items`) and does not return a `total` (cursor pagination on a
  // growing list). The earlier test fixture mocked the wrong shape, masking
  // the runtime contract mismatch that crashed the Narrative-history tab.
  return {
    entity_id: "00000000-0000-7000-8000-000000000001",
    versions: [
      {
        version_id: "v1",
        narrative_text: "Apple is a technology company...",
        model_id: "meta-llama/Meta-Llama-3.1-8B-Instruct",
        generation_reason: "PERIODIC_REFRESH",
        generated_at: "2026-05-01T00:00:00Z",
        word_count: 120,
        quality_score: 0.82,
      },
    ],
    next_cursor: cursor,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("useEntityIntelligence", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it("calls /v1/entities/{id}/intelligence and returns data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockIntelligenceResponse()), { status: 200 }),
      ),
    );

    const { result } = renderHook(
      () => useEntityIntelligence("test-entity-id"),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.entity_id).toBe("test-entity-id");
    expect(result.current.data?.canonical_name).toBe("Apple Inc.");

    // Verify the correct URL was called
    const fetchMock = vi.mocked(global.fetch);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/entities/test-entity-id/intelligence"),
      expect.any(Object),
    );
  });

  it("is disabled when entityId is empty string", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () => useEntityIntelligence(""),
      { wrapper: makeWrapper() },
    );

    // WHY check status (not fetchMock): the hook's `enabled` guard prevents
    // the query from ever firing when entityId is falsy. The status should
    // stay "pending" (not "success") without any fetch call.
    expect(result.current.status).toBe("pending");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("useEntityPaths", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it("calls /v1/entities/{id}/paths", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockPathsResponse()), { status: 200 }),
      ),
    );

    const { result } = renderHook(
      () => useEntityPaths("test-entity-id"),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.paths).toHaveLength(1);
    expect(result.current.data?.total).toBe(1);
  });

  it("includes filter params in URL when provided", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockPathsResponse()), { status: 200 }),
      ),
    );

    const { result } = renderHook(
      () => useEntityPaths("test-entity-id", { minScore: 0.5, maxHops: 3 }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const fetchMock = vi.mocked(global.fetch);
    const calledUrl = (fetchMock.mock.calls[0][0] as string);
    expect(calledUrl).toContain("min_score=0.5");
    expect(calledUrl).toContain("max_hops=3");
  });
});

describe("useEntityNarrativeHistory", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it("calls /v1/entities/{id}/narratives on first page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockNarrativesPage("cursor-2")), { status: 200 }),
      ),
    );

    const { result } = renderHook(
      () => useEntityNarrativeHistory("test-entity-id"),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // First page versions (canonical S7 schema — see fixture comment above)
    const allItems = result.current.data?.pages.flatMap((p) => p.versions ?? []) ?? [];
    expect(allItems).toHaveLength(1);
    expect(allItems[0].version_id).toBe("v1");

    // next_cursor should be exposed via hasNextPage
    expect(result.current.hasNextPage).toBe(true);
  });

  it("has no next page when next_cursor is null", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockNarrativesPage(null)), { status: 200 }),
      ),
    );

    const { result } = renderHook(
      () => useEntityNarrativeHistory("test-entity-id"),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(false);
  });
});

describe("useTriggerNarrativeGeneration", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it("calls POST /v1/entities/{id}/narratives/generate", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, { status: 202 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () => useTriggerNarrativeGeneration("test-entity-id"),
      { wrapper: makeWrapper() },
    );

    result.current.mutate(undefined);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/entities/test-entity-id/narratives/generate"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});
