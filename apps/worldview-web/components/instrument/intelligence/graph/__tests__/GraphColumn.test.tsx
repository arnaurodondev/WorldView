/**
 * components/instrument/intelligence/graph/__tests__/GraphColumn.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-E-02): the Intelligence tab's center column
 * owns the AGE-graph query that has a 3-second deadline. When the deadline
 * fires the queryFn throws `Error("GRAPH_TIMEOUT")` and the component must
 * render the "Graph query timed out" fallback (registry key
 * "instrument.graph-timeout" + a "Reduce depth" action since Round-3) instead
 * of leaving the analyst on a blank canvas.
 *
 * This test pins the timeout-fallback contract by mocking the gateway's
 * getEntityGraph() to throw the typed timeout error and asserting the
 * fallback copy is in the DOM. The brief is mocked to null so the test
 * focuses on the graph branch only.
 *
 * WHY we don't try to trigger a real AbortController timeout: simulating the
 * 3-second deadline would require fake timers + careful flush sequencing
 * that is hostile to test stability. Throwing the typed error directly
 * exercises the EXACT branch the production code translates the abort into
 * (see GraphColumn.tsx queryFn catch block: throw new Error("GRAPH_TIMEOUT")).
 *
 * WHY we keep this in its own file (not IntelligenceTab): the timeout logic
 * lives in GraphColumn — IntelligenceTab is a thin 3-column layout that
 * just hosts GraphColumn. Testing GraphColumn directly avoids the news +
 * context-panel dependencies that would otherwise drag in their own mocks.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// WHY a hoisted handle: lets each test mock-reject getEntityGraph differently.
const mockGateway = vi.hoisted(() => ({
  getEntityGraph: vi.fn(),
  getInstrumentBrief: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// WHY stub the dynamically-imported EntityGraph: the real component pulls in
// sigma.js / WebGL which has no jsdom support. The dynamic() loader still
// fires next/dynamic in tests; stubbing the module short-circuits it.
vi.mock("@/components/instrument/EntityGraph", () => ({
  EntityGraph: () => <div data-testid="entity-graph-stub" />,
}));

// IMPORTANT: import AFTER mocks.
// eslint-disable-next-line import/first
import { GraphColumn } from "@/components/instrument/intelligence/graph/GraphColumn";

// ── Helpers ──────────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  // retry:0 mirrors the production setting on the graph query and prevents
  // TanStack from re-running the failing queryFn three times.
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockGateway.getEntityGraph.mockReset();
  mockGateway.getInstrumentBrief.mockReset();
  // Brief returns null in every test — we only care about the graph branch.
  mockGateway.getInstrumentBrief.mockResolvedValue(null);
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("GraphColumn timeout fallback", () => {
  it("renders the GRAPH_TIMEOUT fallback when the gateway throws the typed error", async () => {
    // WHY this exact error: the production queryFn catches an abort and
    // re-throws `new Error("GRAPH_TIMEOUT")`. The fallback predicate is
    // `graphErr instanceof Error && graphErr.message === "GRAPH_TIMEOUT"`.
    mockGateway.getEntityGraph.mockRejectedValue(new Error("GRAPH_TIMEOUT"));
    render(
      <Wrapper>
        <GraphColumn entityId="ent-001" selectedNodeId={null} onNodeSelect={() => {}} />
      </Wrapper>,
    );
    // Round-3 consolidation: the fallback copy now resolves through the
    // "instrument.graph-timeout" registry key (static, depth-free per DS
    // §15.12 — the active depth is visible in the toolbar/stats above). We
    // match substring so a wording tweak that keeps "timed out" still passes.
    await waitFor(() => {
      expect(screen.getByText(/timed out/i)).toBeInTheDocument();
    });
    // Registry body copy renders too — ported hint coverage from the retired
    // local EmptyState (it used to render this exact line as `hint`).
    expect(screen.getByText(/Deeper traversals are expensive/i)).toBeInTheDocument();
    // Ported from the local EmptyState contract test: the state announces via
    // role="status" and stays scannable via an inline <svg> icon.
    const status = screen.getByRole("status");
    expect(status.querySelector("svg")).not.toBeNull();
    // The graph stub must NOT have rendered — fallback is the only thing on
    // screen besides the brief block and toolbar.
    expect(screen.queryByTestId("entity-graph-stub")).not.toBeInTheDocument();
  });

  it("at the default depth (1) a timeout shows the named state WITHOUT a 'Reduce depth' CTA", async () => {
    // 2026-06-16 data-pipeline QA: the default depth is now 1 (depth=2 timed out
    // on hub entities → empty canvas). depth=1 is the floor, so the timeout state
    // must NOT offer "Reduce depth" (the `depth > 1` guard) — there is nothing
    // cheaper to drop to. The first (and only) fetch at depth 1 times out here.
    mockGateway.getEntityGraph.mockRejectedValue(new Error("GRAPH_TIMEOUT"));
    render(
      <Wrapper>
        <GraphColumn entityId="ent-001" selectedNodeId={null} onNodeSelect={() => {}} />
      </Wrapper>,
    );
    // Wait for the timeout state to settle (the named EmptyState renders).
    await waitFor(() => {
      expect(mockGateway.getEntityGraph).toHaveBeenCalled();
    });
    // The first fetch went out at depth 1 (the new default).
    expect(mockGateway.getEntityGraph).toHaveBeenCalledWith("ent-001", 1);
    // At the floor depth there is NO reduce-depth CTA (the `depth > 1` guard) —
    // nothing cheaper to drop to.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /reduce depth/i })).not.toBeInTheDocument();
    });
  });

  it("renders the shape-matched skeleton (not a spinner) while the graph query is in flight", () => {
    // A never-resolving promise pins the query in `isLoading`.
    mockGateway.getEntityGraph.mockReturnValue(new Promise(() => {}));
    render(
      <Wrapper>
        <GraphColumn entityId="ent-001" selectedNodeId={null} onNodeSelect={() => {}} />
      </Wrapper>,
    );
    // Round-3 item 4: async blocks get shape-matched skeletons — no spinners.
    expect(screen.getByTestId("graph-skeleton")).toBeInTheDocument();
  });
});

// ── Round-4 hardening (item 1b): generic (non-timeout) failure branch ─────────

describe("GraphColumn generic error fallback", () => {
  it("renders a named error with Retry for non-timeout failures (was an empty box)", async () => {
    // A 5xx/network error is NOT the typed GRAPH_TIMEOUT — before Round-4 it
    // matched no render branch and left an empty bordered canvas slot.
    mockGateway.getEntityGraph.mockRejectedValue(new Error("S9 unavailable"));
    render(
      <Wrapper>
        <GraphColumn entityId="ent-001" selectedNodeId={null} onNodeSelect={() => {}} />
      </Wrapper>,
    );
    const errBox = await screen.findByTestId("graph-fetch-error");
    expect(errBox).toBeInTheDocument();
    // It must NOT masquerade as the timeout state (different remedies:
    // retry vs reduce depth).
    expect(screen.queryByText(/timed out/i)).toBeNull();

    // Retry refires the SAME query (same depth) and clears the error.
    mockGateway.getEntityGraph.mockResolvedValue({
      entity_id: "ent-001",
      nodes: [
        { id: "ent-001", label: "Root", type: "financial_instrument" },
        { id: "ent-002", label: "Peer", type: "financial_instrument" },
      ],
      edges: [{ id: "e1", source: "ent-001", target: "ent-002", label: "peer_of" }],
    });
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => {
      expect(screen.getByTestId("entity-graph-stub")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("graph-fetch-error")).toBeNull();
  });
});
