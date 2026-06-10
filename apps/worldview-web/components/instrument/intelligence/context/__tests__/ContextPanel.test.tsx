/**
 * components/instrument/intelligence/context/__tests__/ContextPanel.test.tsx
 *
 * WHY THIS EXISTS (Round-1 Foundation, requirement 4): pins the entity-overview
 * mode's new freshness contract:
 *   - "Updated <date>" renders from entity.enriched_at (the enrichment
 *     worker's write timestamp — the KG's honest "last updated")
 *   - missing enriched_at renders "Updated —" (named, not hidden)
 *   - missing entity entirely renders the NAMED empty state (icon + headline)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React, { type ReactNode } from "react";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    logout: vi.fn(),
  })),
}));

// ContextPanel's own entity-detail query goes through createGateway.
const mockGetEntityDetail = vi.hoisted(() => vi.fn());
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({ getEntityDetail: mockGetEntityDetail })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// WHY mock the whole intelligence hook module: ContextPanel uses
// useEntityIntelligence (health badge) and the NarrativeHistoryDisclosure
// child uses useEntityNarrativeHistory + useTriggerNarrativeGeneration —
// none of their fetch plumbing is under test here.
vi.mock("@/lib/api/intelligence", () => ({
  useEntityIntelligence: vi.fn(() => ({ data: null, isLoading: false })),
  useEntityNarrativeHistory: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
  })),
  useTriggerNarrativeGeneration: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

// ContradictionsBlock child fetches via the KG api — return empty.
vi.mock("@/lib/api/knowledge-graph", () => ({
  createKnowledgeGraphApi: vi.fn(() => ({
    getContradictions: vi.fn().mockResolvedValue({ entity_id: "ent-001", contradictions: [] }),
  })),
}));

import { ContextPanel } from "@/components/instrument/intelligence/context/ContextPanel";

const ENTITY = {
  entity_id: "ent-001",
  canonical_name: "Apple Inc.",
  entity_type: "financial_instrument",
  description: "Designs and sells consumer electronics.",
  enriched_at: "2026-06-05T03:00:00Z",
  metadata: {},
};

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockGetEntityDetail.mockReset();
});

afterEach(() => cleanup());

describe("ContextPanel last-updated timestamp (Round-1)", () => {
  it("renders 'Updated <date>' from entity.enriched_at", async () => {
    mockGetEntityDetail.mockResolvedValue(ENTITY);
    render(
      <Wrapper>
        <ContextPanel entityId="ent-001" selectedNodeId={null} onClearSelection={() => {}} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    });
    expect(screen.getByText(/Updated/i)).toBeInTheDocument();
    // formatDate renders UTC "Jun 5, 2026".
    expect(screen.getByText("Jun 5, 2026")).toBeInTheDocument();
  });

  it("renders 'Updated —' when the entity was never enriched", async () => {
    mockGetEntityDetail.mockResolvedValue({ ...ENTITY, enriched_at: null });
    render(
      <Wrapper>
        <ContextPanel entityId="ent-001" selectedNodeId={null} onClearSelection={() => {}} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText(/Updated/i)).toBeInTheDocument();
    });
    // The timestamp slot stays mounted with an explicit dash (named state).
    const updated = screen.getByText(/Updated/i);
    expect(updated.textContent).toContain("—");
  });
});

describe("ContextPanel named no-entity state (Round-1)", () => {
  it("renders the icon+headline empty state when the entity detail is null", async () => {
    // getEntityDetail returns null for 404 (entity not enriched yet).
    mockGetEntityDetail.mockResolvedValue(null);
    render(
      <Wrapper>
        <ContextPanel entityId="ent-001" selectedNodeId={null} onClearSelection={() => {}} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText("No entity context")).toBeInTheDocument();
    });
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
  });
});
