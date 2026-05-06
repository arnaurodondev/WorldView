/**
 * __tests__/entity-description-panel.test.tsx — F-Q05 PLAN-0073 QA coverage
 *
 * WHY THIS EXISTS: EntityDescriptionPanel renders Worker 13J enrichment data
 * (PRD-0073) inside the Instrument Detail Intelligence tab. The component had
 * ZERO test coverage before this file landed (PLAN-0073 QA F-Q05 BLOCKING gap).
 *
 * The panel has several edge cases that all need coverage:
 *   - loading skeleton when isLoading
 *   - renders nothing when data is null (404 / not enriched yet)
 *   - renders nothing when data.description is null (enrichment ran, no desc)
 *   - replaces underscores in entity_type for display ("financial_instrument" → "financial instrument")
 *   - completeness progress bar width + aria-valuenow reflect data_completeness
 *   - filters out null metadata fields from the META_FIELDS list
 *   - 0% completeness rendered when data_completeness is null
 *
 * WHY mock gateway/useAuth: unit tests must not make real S9 calls or require
 * a logged-in user. Pattern matches __tests__/instrument-detail.test.tsx.
 *
 * DATA SOURCE: Mocked gateway client (createGateway).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EntityDescriptionPanel } from "@/components/instrument/EntityDescriptionPanel";
import { createGateway } from "@/lib/gateway";
import type { EntityPublic } from "@/types/api";

// ── Gateway mock ──────────────────────────────────────────────────────────────
// WHY: the panel calls createGateway(token).getEntityDetail(entityId) inside a
// useQuery. Tests configure the mock per-case to return loading/null/populated.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getEntityDetail: vi.fn().mockResolvedValue(null),
  })),
}));

// ── useAuth mock ──────────────────────────────────────────────────────────────
// WHY: useQuery's `enabled: !!accessToken` is gated on a non-empty token —
// without this mock the query never runs and the test sees an indefinite
// loading skeleton.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    user: { sub: "user-1" },
  })),
}));

// ── Render helper ────────────────────────────────────────────────────────────
// WHY: every test needs a fresh QueryClient so cached data does not leak
// between cases (e.g. the populated-data test would see null from a prior run).
function renderPanel(props: { entityId: string }) {
  const client = new QueryClient({
    defaultOptions: {
      // retry:false so 404 paths resolve immediately rather than waiting for
      // exponential backoff during the test.
      queries: { retry: false, gcTime: 0 },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <EntityDescriptionPanel {...props} />
    </QueryClientProvider>,
  );
}

// ── Mock data factory ────────────────────────────────────────────────────────
function _makeEntity(overrides: Partial<EntityPublic> = {}): EntityPublic {
  return {
    entity_id: "ent-001",
    canonical_name: "Apple Inc.",
    entity_type: "financial_instrument",
    ticker: "AAPL",
    isin: null,
    exchange: "NASDAQ",
    description: "A consumer electronics maker headquartered in Cupertino, California.",
    data_completeness: 0.85,
    enriched_at: "2026-05-04T02:00:00Z",
    metadata: {
      sector: "Technology",
      industry: "Consumer Electronics",
      country: "United States",
      ticker: "AAPL",
      exchange: "NASDAQ",
      isin: null,
      currency_code: null,
      employee_count: 164000,
      founded_year: 1976,
      headquarters_city: null,
      headquarters_country: null,
    },
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("EntityDescriptionPanel — F-Q05 (PLAN-0073)", () => {
  it("renders skeleton when isLoading", () => {
    // Make getEntityDetail hang forever so the query stays in `isLoading`.
    // WHY a non-resolving promise: lets us assert against the loading branch
    // without racing the resolver.
    const neverResolves = new Promise<EntityPublic | null>(() => {
      /* intentionally empty */
    });
    vi.mocked(createGateway).mockReturnValueOnce({
      getEntityDetail: vi.fn().mockReturnValue(neverResolves),
    } as unknown as ReturnType<typeof createGateway>);

    const { container } = renderPanel({ entityId: "ent-001" });

    // The skeleton state renders <Skeleton/> placeholders. We verify by
    // selecting elements that have the data-slot=skeleton attribute set by
    // the shadcn/ui Skeleton component.
    const skeletons = container.querySelectorAll('[data-slot="skeleton"]');
    expect(skeletons.length).toBeGreaterThanOrEqual(1);
  });

  it("renders nothing when data is null", async () => {
    vi.mocked(createGateway).mockReturnValueOnce({
      getEntityDetail: vi.fn().mockResolvedValue(null),
    } as unknown as ReturnType<typeof createGateway>);

    const { container } = renderPanel({ entityId: "ent-001" });

    // Wait for the query to settle (resolve with null). After settling the
    // panel returns null → the rendered fragment is empty.
    await waitFor(() => {
      // No <section> rendered when data is null.
      expect(container.querySelector("section")).toBeNull();
    });
  });

  it("renders nothing when data.description is null", async () => {
    vi.mocked(createGateway).mockReturnValueOnce({
      getEntityDetail: vi.fn().mockResolvedValue(
        _makeEntity({ description: null }),
      ),
    } as unknown as ReturnType<typeof createGateway>);

    const { container } = renderPanel({ entityId: "ent-001" });

    await waitFor(() => {
      // Even with metadata populated, no description → no panel rendered.
      // WHY: the panel disappears entirely so the tab feels clean (matches
      // the comment in EntityDescriptionPanel.tsx).
      expect(container.querySelector("section")).toBeNull();
    });
  });

  it("renders entity_type with underscores replaced by spaces", async () => {
    vi.mocked(createGateway).mockReturnValueOnce({
      getEntityDetail: vi.fn().mockResolvedValue(_makeEntity()),
    } as unknown as ReturnType<typeof createGateway>);

    renderPanel({ entityId: "ent-001" });

    // "financial_instrument" → "financial instrument" via .replace(/_/g, " ")
    const badge = await screen.findByText("financial instrument");
    expect(badge).toBeTruthy();
  });

  it("renders progress bar with correct width and aria-valuenow attribute", async () => {
    vi.mocked(createGateway).mockReturnValueOnce({
      getEntityDetail: vi.fn().mockResolvedValue(_makeEntity({ data_completeness: 0.85 })),
    } as unknown as ReturnType<typeof createGateway>);

    const { container } = renderPanel({ entityId: "ent-001" });

    // The progress bar is the inner div with role="progressbar".
    const bar = await waitFor(() => {
      const el = container.querySelector('[role="progressbar"]');
      if (!el) throw new Error("progressbar not yet rendered");
      return el;
    });

    // 0.85 * 100 = 85 (Math.round) → width:85% and aria-valuenow=85
    expect(bar.getAttribute("aria-valuenow")).toBe("85");
    expect(bar.getAttribute("aria-valuemin")).toBe("0");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    // The inline style sets width: 85%
    expect((bar as HTMLElement).style.width).toBe("85%");
  });

  it("filters out null metadata fields from META_FIELDS list", async () => {
    // Only sector + industry populated; everything else null.
    const entity = _makeEntity({
      metadata: {
        sector: "Technology",
        industry: "Consumer Electronics",
        country: null,
        ticker: null,
        exchange: null,
        isin: null,
        currency_code: null,
        employee_count: null,
        founded_year: null,
        headquarters_city: null,
        headquarters_country: null,
      },
    });
    vi.mocked(createGateway).mockReturnValueOnce({
      getEntityDetail: vi.fn().mockResolvedValue(entity),
    } as unknown as ReturnType<typeof createGateway>);

    renderPanel({ entityId: "ent-001" });

    // Sector + Industry labels render; HQ City must NOT render (null).
    await screen.findByText("Sector");
    expect(screen.getByText("Industry")).toBeTruthy();
    expect(screen.queryByText("HQ City")).toBeNull();
    expect(screen.queryByText("Country")).toBeNull();
  });

  it("renders 0% completeness when data_completeness is null", async () => {
    vi.mocked(createGateway).mockReturnValueOnce({
      getEntityDetail: vi.fn().mockResolvedValue(
        _makeEntity({ data_completeness: null }),
      ),
    } as unknown as ReturnType<typeof createGateway>);

    const { container } = renderPanel({ entityId: "ent-001" });

    const bar = await waitFor(() => {
      const el = container.querySelector('[role="progressbar"]');
      if (!el) throw new Error("progressbar not yet rendered");
      return el;
    });

    // null ?? 0 → 0 → Math.round(0 * 100) = 0
    expect(bar.getAttribute("aria-valuenow")).toBe("0");
    expect((bar as HTMLElement).style.width).toBe("0%");
    // The label should display "0%"
    expect(screen.getByText("0%")).toBeTruthy();
  });
});
