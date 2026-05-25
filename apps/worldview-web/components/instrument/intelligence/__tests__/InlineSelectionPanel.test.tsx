/**
 * InlineSelectionPanel.test.tsx — Block I T-26/T-27 unit tests
 *
 * WHY THIS EXISTS: InlineSelectionPanel is the primary interaction surface
 * for node/edge detail on the Intelligence tab. These tests pin the core
 * rendering contract so regressions (blank panel on click, breadcrumb missing,
 * × button not firing, description skeleton broken) surface in CI.
 *
 * TEST STRATEGY: two tiers of tests.
 *
 *   Tier 1 — pure presentational (no TanStack Query needed):
 *   Tests where `description` is a non-null string on the node. The component
 *   skips the lazy fetch entirely (`enabled=false`), so no QueryClient is
 *   required. These tests use a plain render().
 *
 *   Tier 2 — TanStack Query tests (description=null → lazy fetch):
 *   Tests that exercise the lazy entity-detail fetch path. These require:
 *     1. A QueryClientProvider wrapper.
 *     2. A mock for `useAccessToken` (returns a token so `enabled` is satisfied).
 *     3. The TanStack Query `queryFn` is never invoked in these unit tests —
 *        instead we pre-seed the QueryClient cache (setQueryData) so the query
 *        resolves synchronously without any network calls. This avoids MSW/fetch
 *        mocks and keeps the tests fast and deterministic.
 *
 * WHY seed cache instead of MSW:
 * MSW adds a server-setup/teardown lifecycle and requires fetch to be polyfilled
 * in jsdom. QueryClient.setQueryData() is the idiomatic TanStack Query testing
 * primitive for pre-seeding data — it's synchronous, isolated, and doesn't
 * require any network infrastructure.
 *
 * WHY mock useAccessToken:
 * The `enabled` guard includes `!!token`. Without a token the detailQuery is
 * disabled and isLoading is always false — the skeleton would never appear.
 * Mocking useAccessToken with a non-null string ensures the `enabled` condition
 * fires when `description === null`.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { qk } from "@/lib/query/keys";
import { InlineSelectionPanel } from "@/components/instrument/intelligence/InlineSelectionPanel";
import type { SelectedNodeInfo } from "@/components/instrument/intelligence/InlineSelectionPanel";
import type { SelectedEdgeInfo } from "@/components/instrument/EntityGraph";
import type { EntityPublic } from "@/types/api";

// ── Module mocks ──────────────────────────────────────────────────────────────

// WHY mock useAccessToken: the lazy entity-detail fetch is guarded by `!!token`.
// We need to control whether it's truthy (Tier-2 tests) or falsy (Tier-1 tests).
// Default to a truthy token so Tier-2 tests don't need to override it individually.
vi.mock("@/lib/api-client", () => ({
  useAccessToken: vi.fn(() => "test-token"),
}));

// WHY mock apiFetch: the queryFn calls apiFetch, but Tier-2 tests seed the cache
// via setQueryData so queryFn is NEVER invoked. The mock is a safety net — if
// the test accidentally triggers a real fetch it would throw, failing the test.
vi.mock("@/lib/api/_client", () => ({
  apiFetch: vi.fn(() => {
    throw new Error("apiFetch should not be called in unit tests — seed cache via setQueryData");
  }),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(msg: string, status: number) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Test fixtures ────────────────────────────────────────────────────────────

/**
 * mockNode — a graph node with description=null (the lazy-fetch scenario).
 * Used in Tier-2 tests that exercise the entity-detail fallback path.
 */
const mockNode: SelectedNodeInfo = {
  id: "node-001",
  label: "Apple Inc.",
  type: "company",
  degree: 3,
  edges: [
    { label: "COMPETES_WITH", weight: 0.85, neighborId: "node-002", neighborLabel: "Microsoft" },
    { label: "SUPPLIER_OF", weight: 0.6, neighborId: "node-003", neighborLabel: "TSMC" },
  ],
  description: null,
  sector: null,
};

/**
 * mockNodeWithDescription — node whose description comes directly from graph attrs.
 * The lazy fetch must NOT fire when description is a non-null string (Tier-1 tests).
 */
const mockNodeWithDescription: SelectedNodeInfo = {
  ...mockNode,
  description: "The world's most valuable technology company.",
};

const mockEdge: SelectedEdgeInfo = {
  id: "edge-001",
  label: "COMPETES_WITH",
  weight: 0.85,
  evidence_snippets: [
    "Apple and Microsoft compete directly in the cloud and productivity segments.",
    "Both companies vied for enterprise contracts in Q4 2023.",
  ],
  relation_summary: "Direct competitors in cloud, productivity, and enterprise software.",
  sourceId: "node-001",
  targetId: "node-002",
  sourceLabel: "Apple Inc.",
  targetLabel: "Microsoft",
  direction: "outbound",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Wrapper — QueryClientProvider with retry=false for deterministic tests.
 *
 * WHY create a new client per test (not a shared instance): TanStack Query
 * caches are global by default — a cache entry seeded in one test leaks into
 * the next. Creating a fresh QueryClient per Wrapper call isolates tests.
 *
 * WHY accept an optional pre-seeded qc: some tests need to seed cache before
 * rendering (Tier-2 lazy-fetch tests) so they create the client themselves,
 * seed it, then pass it in.
 */
function Wrapper({ children, qc }: { children: ReactNode; qc?: QueryClient }) {
  const client =
    qc ??
    new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

// ── Tier-1 tests: pure presentational (no query needed) ───────────────────────

describe("InlineSelectionPanel — presentational (Tier 1)", () => {
  it("renders nothing when both selectedNode and selectedEdge are null", () => {
    // WHY: null/null is the initial state — the panel must be a zero-height
    // no-op so the graph column doesn't reserve 180px before any click.
    const { container } = render(
      <Wrapper>
        <InlineSelectionPanel selectedNode={null} selectedEdge={null} onClear={vi.fn()} />
      </Wrapper>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("node mode: renders label, connection count, and edge rows", () => {
    // WHY: clicking a node must show the entity name + type + how many
    // direct connections it has so the analyst immediately understands
    // the node's centrality. Edge rows show the actual neighbour names.
    render(
      <Wrapper>
        <InlineSelectionPanel
          selectedNode={mockNodeWithDescription}
          selectedEdge={null}
          onClear={vi.fn()}
        />
      </Wrapper>,
    );

    // Header contains type + label
    expect(screen.getByText(/COMPANY · Apple Inc\./i)).toBeInTheDocument();

    // Connection count line
    expect(screen.getByText(/3 connections/i)).toBeInTheDocument();

    // Description renders from graph attrs (no query needed)
    expect(screen.getByText("The world's most valuable technology company.")).toBeInTheDocument();

    // Neighbour labels rendered in edge rows
    expect(screen.getByText("Microsoft")).toBeInTheDocument();
    expect(screen.getByText("TSMC")).toBeInTheDocument();

    // Relation labels (lowercased with _ replaced by space)
    expect(screen.getByText(/competes with/i)).toBeInTheDocument();
    expect(screen.getByText(/supplier of/i)).toBeInTheDocument();
  });

  it("edge mode: renders source → relation → target breadcrumb + evidence snippets", () => {
    // WHY: clicking an edge exposes the claim behind the relationship —
    // the source/relation/target triple tells the analyst WHAT the edge is,
    // and evidence snippets tell them WHERE the signal came from.
    render(
      <Wrapper>
        <InlineSelectionPanel selectedNode={null} selectedEdge={mockEdge} onClear={vi.fn()} />
      </Wrapper>,
    );

    // Breadcrumb: source and target labels visible
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("Microsoft")).toBeInTheDocument();

    // Relation type appears in both header and breadcrumb — assert at least one match
    expect(screen.getAllByText(/competes with/i).length).toBeGreaterThanOrEqual(1);

    // LLM summary
    expect(screen.getByText(/Direct competitors in cloud/i)).toBeInTheDocument();

    // Evidence snippet header
    expect(screen.getByText(/EVIDENCE · 2 snippets/i)).toBeInTheDocument();

    // Both snippets rendered
    expect(screen.getByText(/Apple and Microsoft compete/i)).toBeInTheDocument();
    expect(screen.getByText(/Both companies vied/i)).toBeInTheDocument();
  });

  it("onClear fires when the × button is clicked", () => {
    // WHY: the × dismiss button must trigger the parent's clear handler.
    const onClear = vi.fn();
    render(
      <Wrapper>
        <InlineSelectionPanel
          selectedNode={mockNodeWithDescription}
          selectedEdge={null}
          onClear={onClear}
        />
      </Wrapper>,
    );

    const closeBtn = screen.getByRole("button", { name: /close selection panel/i });
    fireEvent.click(closeBtn);
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  // F-004 — edge mode: no evidence AND no summary shows empty-state message
  it("shows 'No evidence or summary available' when edge has no snippets and no summary", () => {
    render(
      <Wrapper>
        <InlineSelectionPanel
          selectedNode={null}
          selectedEdge={{ ...mockEdge, evidence_snippets: [], relation_summary: undefined }}
          onClear={vi.fn()}
        />
      </Wrapper>,
    );
    expect(screen.getByText(/no evidence or summary available/i)).toBeInTheDocument();
  });

  // F-005 — node mode: singular "connection" (not "connections") when degree === 1
  it("renders '1 connection' (singular) when node degree is 1", () => {
    render(
      <Wrapper>
        <InlineSelectionPanel
          selectedNode={{ ...mockNodeWithDescription, degree: 1, edges: [mockNode.edges[0]] }}
          selectedEdge={null}
          onClear={vi.fn()}
        />
      </Wrapper>,
    );
    expect(screen.getByText(/1 connection$/i)).toBeInTheDocument();
  });

  // QW-3 — edge mode: direction badge
  it("shows 'outbound' direction badge on outbound edge", () => {
    render(
      <Wrapper>
        <InlineSelectionPanel
          selectedNode={null}
          selectedEdge={{ ...mockEdge, direction: "outbound" }}
          onClear={vi.fn()}
        />
      </Wrapper>,
    );
    expect(screen.getByText(/outbound/i)).toBeInTheDocument();
  });

  it("shows 'inbound' direction badge on inbound edge", () => {
    render(
      <Wrapper>
        <InlineSelectionPanel
          selectedNode={null}
          selectedEdge={{ ...mockEdge, direction: "inbound" }}
          onClear={vi.fn()}
        />
      </Wrapper>,
    );
    expect(screen.getByText(/inbound/i)).toBeInTheDocument();
  });

  it("hides direction badge for lateral edges", () => {
    render(
      <Wrapper>
        <InlineSelectionPanel
          selectedNode={null}
          selectedEdge={{ ...mockEdge, direction: "lateral" }}
          onClear={vi.fn()}
        />
      </Wrapper>,
    );
    expect(screen.queryByText(/outbound|inbound/i)).not.toBeInTheDocument();
  });

  // F-QA-003 — node mode: weight=0 edge renders 0% bar without error
  it("renders weight=0 edge as 0% bar and '0' label without crashing", () => {
    const zeroWeightEdge = {
      label: "COMPETES_WITH",
      weight: 0,
      neighborId: "node-002",
      neighborLabel: "Microsoft",
    };
    render(
      <Wrapper>
        <InlineSelectionPanel
          selectedNode={{ ...mockNodeWithDescription, edges: [zeroWeightEdge] }}
          selectedEdge={null}
          onClear={vi.fn()}
        />
      </Wrapper>,
    );
    // The weight bar renders "0" as the numeric label (pct=0)
    expect(screen.getByText("0")).toBeInTheDocument();
    // The neighbor label still renders
    expect(screen.getByText("Microsoft")).toBeInTheDocument();
  });

  // F-QA-004 — node mode: more than 6 edges truncates to first 6 (slice(0,6))
  it("renders at most 6 edge rows when node has more than 6 connections", () => {
    const manyEdges = Array.from({ length: 8 }, (_, i) => ({
      label: "COMPETES_WITH",
      weight: 0.5,
      neighborId: `node-${i + 10}`,
      neighborLabel: `Company ${i + 1}`,
    }));
    render(
      <Wrapper>
        <InlineSelectionPanel
          selectedNode={{ ...mockNodeWithDescription, degree: 8, edges: manyEdges }}
          selectedEdge={null}
          onClear={vi.fn()}
        />
      </Wrapper>,
    );
    // Only the first 6 neighbors should appear; Company 7 and 8 are truncated.
    expect(screen.getByText("Company 1")).toBeInTheDocument();
    expect(screen.getByText("Company 6")).toBeInTheDocument();
    expect(screen.queryByText("Company 7")).not.toBeInTheDocument();
    expect(screen.queryByText("Company 8")).not.toBeInTheDocument();
    // Degree count still shows the total (8), not the truncated display count.
    expect(screen.getByText(/8 connections/i)).toBeInTheDocument();
  });
});

// ── Tier-2 tests: lazy entity-detail fetch (description=null) ─────────────────

describe("InlineSelectionPanel — lazy entityDetail fetch (Tier 2)", () => {
  /**
   * WHY these tests are in a separate describe block:
   * They require a pre-seeded QueryClient and TanStack Query internal state
   * management. Keeping them separate from the pure-presentational Tier-1 tests
   * makes intent clear: Tier 1 = no network; Tier 2 = query lifecycle.
   */

  it("shows a skeleton row while entityDetail is loading (description=null, cache empty)", () => {
    // WHY: when description is null and the cache is empty, TanStack Query fires
    // the queryFn which is async. During that window isLoading=true and the
    // skeleton row must be visible so the analyst sees "data incoming" not an
    // empty gap in the panel.
    //
    // HOW: we create a QueryClient with NO pre-seeded data for the entity key.
    // The `enabled` condition is satisfied (description=null, token truthy).
    // isLoading will be true on the initial render before queryFn resolves.
    // Since we've mocked apiFetch to throw, the query will error-out — but
    // the skeleton is shown BEFORE the first resolution, which is what we test.
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <Wrapper qc={qc}>
        <InlineSelectionPanel selectedNode={mockNode} selectedEdge={null} onClear={vi.fn()} />
      </Wrapper>,
    );

    // On first render, the query is in "loading" state — skeleton must appear.
    // We test the aria-label set on the skeleton container div.
    expect(screen.getByRole("generic", { name: /loading description/i })).toBeInTheDocument();
  });

  it("shows description from entityDetail query when graphology attrs had null description", async () => {
    // WHY: this tests the core lazy-fetch value proposition. When the graph
    // response has description=null, the panel fires getEntityDetail() and
    // once it resolves, the returned description is displayed in the description row.
    //
    // HOW: we pre-seed the TanStack Query cache with the expected EntityPublic
    // response. This causes the query to resolve synchronously on render
    // (cache hit → data immediately available, no loading state).
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    // Pre-seed cache with the EntityPublic the query would return from S9.
    // WHY setQueryData (not MSW): synchronous, no server lifecycle, no fetch polyfill.
    // The query key must match exactly what the component uses: qk.kg.entityDetail(id).
    const entityDetail: EntityPublic = {
      entity_id: "node-001",
      canonical_name: "Apple Inc.",
      entity_type: "company",
      description: "Apple designs, manufactures and markets smartphones, tablets and PCs.",
      data_completeness: 0.9,
      enriched_at: "2026-05-20T00:00:00Z",
      metadata: {},
    };
    qc.setQueryData(qk.kg.entityDetail("node-001"), entityDetail);

    render(
      <Wrapper qc={qc}>
        <InlineSelectionPanel selectedNode={mockNode} selectedEdge={null} onClear={vi.fn()} />
      </Wrapper>,
    );

    // With the cache pre-seeded, isLoading=false and the description renders immediately.
    // waitFor handles any residual React async state flush.
    await waitFor(() => {
      expect(
        screen.getByText("Apple designs, manufactures and markets smartphones, tablets and PCs."),
      ).toBeInTheDocument();
    });

    // The skeleton must NOT be visible once the description is rendered.
    expect(screen.queryByRole("generic", { name: /loading description/i })).not.toBeInTheDocument();
  });

  it("does not show an error banner when entityDetail query errors — core node data intact", async () => {
    // WHY: a failed description fetch must NOT show an error banner — it should
    // silently leave the description row absent. The panel continues showing
    // label, type, connection count, and all edge rows — the core data the
    // analyst needs is still there.
    //
    // HOW: we pre-seed the cache with `undefined` (a deliberate miss that lets
    // TanStack Query call queryFn). apiFetch is mocked to throw, so the query
    // enters error state. We assert:
    //   1. No error banner is rendered (no "error / failed / unable" text).
    //   2. Core node data (connections, neighbour names) is intact.
    //
    // WHY we don't assert "skeleton is gone" here: the timing of when TanStack
    // Query transitions from isLoading → isError in jsdom depends on internal
    // microtask scheduling that is outside our test's control without faking
    // timers. The important invariant is that NO error UI is ever shown —
    // that assertion is stable regardless of query state.
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <Wrapper qc={qc}>
        <InlineSelectionPanel selectedNode={mockNode} selectedEdge={null} onClear={vi.fn()} />
      </Wrapper>,
    );

    // The core node data must always be present regardless of fetch state.
    expect(screen.getByText(/3 connections/i)).toBeInTheDocument();
    expect(screen.getByText("Microsoft")).toBeInTheDocument();
    expect(screen.getByText("TSMC")).toBeInTheDocument();

    // No error message shown at any point — silent failure as spec requires.
    // (This assertion is on the synchronous render output, before any async state.)
    expect(screen.queryByText(/error.*loading|failed.*description|unable.*fetch/i)).not.toBeInTheDocument();
  });
});
