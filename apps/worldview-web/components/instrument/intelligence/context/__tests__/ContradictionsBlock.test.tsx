/**
 * components/instrument/intelligence/context/__tests__/ContradictionsBlock.test.tsx
 *
 * WHY THIS EXISTS (Round-1 Foundation, requirement 4): pins the upgraded
 * contradictions contract:
 *   - count badge reflects the TOTAL detected (not the visible slice)
 *   - each card attributes claim A / claim B to source_a / source_b and shows
 *     the detected date
 *   - the list is expandable past `limit` ("Show all (N)" / "Show less")
 *   - empty result renders the NAMED empty state (icon + headline), never a
 *     blank area
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React, { type ReactNode } from "react";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Contradiction } from "@/types/api";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    logout: vi.fn(),
  })),
}));

const mockGetContradictions = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/knowledge-graph", () => ({
  createKnowledgeGraphApi: vi.fn(() => ({
    getContradictions: mockGetContradictions,
  })),
}));

import { ContradictionsBlock } from "@/components/instrument/intelligence/context/ContradictionsBlock";

function makeContradiction(i: number): Contradiction {
  return {
    contradiction_id: `con-${i}`,
    entity_id: "ent-001",
    claim_a: `Claim A number ${i}`,
    claim_b: `Claim B number ${i}`,
    source_a: `Reuters-${i}`,
    source_b: `Bloomberg-${i}`,
    detected_at: "2026-06-01T08:00:00Z",
    severity: "HIGH",
  };
}

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockGetContradictions.mockReset();
});

afterEach(() => cleanup());

describe("ContradictionsBlock count badge + sources (Round-1)", () => {
  it("shows the total count badge and source-attributed claims with dates", async () => {
    mockGetContradictions.mockResolvedValue({
      entity_id: "ent-001",
      contradictions: [makeContradiction(1)],
    });
    render(
      <Wrapper>
        <ContradictionsBlock entityId="ent-001" limit={5} showHeader />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("contradictions-count")).toHaveTextContent("1");
    });
    // Source A vs source B attribution (requirement 4).
    expect(screen.getByText(/Reuters-1/)).toBeInTheDocument();
    expect(screen.getByText(/Bloomberg-1/)).toBeInTheDocument();
    expect(screen.getByText("Claim A number 1")).toBeInTheDocument();
    expect(screen.getByText("Claim B number 1")).toBeInTheDocument();
    // Detected date (formatDate UTC → "Jun 1, 2026").
    expect(screen.getByText("Jun 1, 2026")).toBeInTheDocument();
  });
});

describe("ContradictionsBlock expand/collapse (Round-1)", () => {
  it("collapses to `limit` cards and expands via 'Show all (N)'", async () => {
    mockGetContradictions.mockResolvedValue({
      entity_id: "ent-001",
      contradictions: Array.from({ length: 7 }, (_, i) => makeContradiction(i)),
    });
    render(
      <Wrapper>
        <ContradictionsBlock entityId="ent-001" limit={5} showHeader />
      </Wrapper>,
    );
    // Collapsed: 5 visible cards, badge still shows the TOTAL (7).
    await waitFor(() => {
      expect(screen.getAllByText(/Claim A number/).length).toBe(5);
    });
    expect(screen.getByTestId("contradictions-count")).toHaveTextContent("7");

    const toggle = screen.getByRole("button", { name: /show all \(7\)/i });
    fireEvent.click(toggle);
    expect(screen.getAllByText(/Claim A number/).length).toBe(7);

    // Collapse again.
    fireEvent.click(screen.getByRole("button", { name: /show less/i }));
    expect(screen.getAllByText(/Claim A number/).length).toBe(5);
  });

  it("renders no toggle when everything fits within the limit", async () => {
    mockGetContradictions.mockResolvedValue({
      entity_id: "ent-001",
      contradictions: [makeContradiction(1), makeContradiction(2)],
    });
    render(
      <Wrapper>
        <ContradictionsBlock entityId="ent-001" limit={5} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getAllByText(/Claim A number/).length).toBe(2);
    });
    expect(screen.queryByRole("button", { name: /show all/i })).toBeNull();
  });
});

describe("ContradictionsBlock named empty state (Round-1)", () => {
  it("renders the icon+headline empty state with a 0 badge", async () => {
    mockGetContradictions.mockResolvedValue({
      entity_id: "ent-001",
      contradictions: [],
    });
    render(
      <Wrapper>
        <ContradictionsBlock entityId="ent-001" showHeader />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText("No contradictions detected")).toBeInTheDocument();
    });
    // Named state semantics + zero badge — the section is a state, not a gap.
    // Round-3 consolidation: the shared primitive announces via role="status"
    // and renders the icon as an inline <svg> (both ported from the retired
    // local EmptyState contract test) + registry body (ported hint coverage).
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    expect(status.querySelector("svg")).not.toBeNull();
    expect(
      screen.getByText("Conflicting claims between sources surface here when the KG pipeline flags them."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("contradictions-count")).toHaveTextContent("0");
  });

  it("handles the 404→null gateway contract as an empty state", async () => {
    // getContradictions returns null for entities with no contradiction data.
    mockGetContradictions.mockResolvedValue(null);
    render(
      <Wrapper>
        <ContradictionsBlock entityId="ent-001" showHeader />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText("No contradictions detected")).toBeInTheDocument();
    });
  });
});
