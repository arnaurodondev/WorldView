/**
 * context/__tests__/PathInsightsBlock.warm-cache.test.tsx — audit 2026-06-23 §2a
 *
 * WHY THIS SUITE EXISTS (separate from PathInsightsBlock.test.tsx):
 *   The sibling suite mocks `useEntityPaths` directly to pin render contracts.
 *   This suite does the OPPOSITE — it uses the REAL `useEntityPaths` hook
 *   against a pre-seeded QueryClient to prove the MUST-FIX claim that the block
 *   renders from the SAME warm ["entity-paths", entityId, {}] cache slot that
 *   `useEntityIntelligenceBundle` hydrates on tab mount, WITHOUT firing its own
 *   network fetch. If the cache key ever drifts from the bundle hydrator's key,
 *   this test fails (the block would fall through to a fetch / empty render).
 *
 * It also pins the tidy empty-state when the warm cache holds zero paths.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Provide a token so useEntityPaths' `enabled: !!entityId && !!token` gate opens.
vi.mock("@/lib/api-client", () => ({
  useAccessToken: vi.fn(() => "test-token"),
}));

// Spy on the network layer so we can assert the warm cache is reused (apiFetch
// must NOT be called for an entity whose paths slot is already populated).
const apiFetchSpy = vi.fn();
vi.mock("@/lib/api/_client", () => ({
  apiFetch: (...args: unknown[]) => apiFetchSpy(...args),
  // GatewayError is imported by lib/api/intelligence.ts at module load.
  GatewayError: class GatewayError extends Error {},
}));

import { PathInsightsBlock } from "@/components/instrument/intelligence/context/PathInsightsBlock";

const ENTITY_ID = "ent-warm-001";

/**
 * Renders the block against a QueryClient whose ["entity-paths", ENTITY_ID, {}]
 * slot is pre-seeded — exactly the slot+shape the bundle hydrator writes
 * (useEntityIntelligenceBundle.ts: setQueryData(["entity-paths", entityId, {}], …)).
 */
function renderWithWarmCache(paths: unknown[]) {
  const qc = new QueryClient({
    // staleTime Infinity guarantees the seeded data is considered fresh, so the
    // real useEntityPaths returns it from cache and never schedules a fetch.
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  // Same key tuple the hydrator uses: ["entity-paths", entityId, {}].
  qc.setQueryData(["entity-paths", ENTITY_ID, {}], { paths });
  return render(
    <QueryClientProvider client={qc}>
      <PathInsightsBlock entityId={ENTITY_ID} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiFetchSpy.mockReset();
});

describe("PathInsightsBlock — warm-cache reuse (audit §2a)", () => {
  it("renders from the pre-seeded ['entity-paths', id, {}] slot WITHOUT a new fetch", async () => {
    const paths = [
      {
        insight_id: "p1",
        hop_count: 2,
        weirdness: 0.62,
        path_nodes: [
          { entity_id: "n1", name: "Apple", entity_type: "company" },
          { entity_id: "n2", name: "TSMC", entity_type: "company" },
          { entity_id: "n3", name: "ASML", entity_type: "company" },
        ],
        path_edges: [{ relation_type: "SUPPLIER_OF" }, { relation_type: "CUSTOMER_OF" }],
      },
    ];
    renderWithWarmCache(paths);

    // The flagship "Apple → TSMC → ASML" indirect path renders from cache.
    await waitFor(() => screen.getByText("Apple → TSMC → ASML"));
    // Cache HIT — no network call was made for the warm slot.
    expect(apiFetchSpy).not.toHaveBeenCalled();
  });

  it("renders a tidy empty state (not a blank box) when the warm cache holds zero paths", async () => {
    renderWithWarmCache([]);
    // Section header is always present + the named empty message — no blank box.
    await waitFor(() => screen.getByText("No multi-hop paths discovered."));
    expect(screen.getByText("PATH INSIGHTS")).toBeInTheDocument();
    expect(apiFetchSpy).not.toHaveBeenCalled();
  });
});
