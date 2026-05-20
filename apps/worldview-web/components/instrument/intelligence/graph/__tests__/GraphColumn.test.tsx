/**
 * components/instrument/intelligence/graph/__tests__/GraphColumn.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-E-02): the Intelligence tab's center column
 * owns the AGE-graph query that has a 3-second deadline. When the deadline
 * fires the queryFn throws `Error("GRAPH_TIMEOUT")` and the component must
 * render a "Graph timed out at depth N. Try depth 1 or 2." fallback instead
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
import { render, screen, waitFor } from "@testing-library/react";
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
    // The fallback copy is "Graph timed out at depth 2. Try depth 1 or 2."
    // (depth defaults to 2 in the component). We match substring so a future
    // wording tweak that keeps "timed out" still passes.
    await waitFor(() => {
      expect(screen.getByText(/timed out at depth 2/i)).toBeInTheDocument();
    });
    // The graph stub must NOT have rendered — fallback is the only thing on
    // screen besides the brief block and toolbar.
    expect(screen.queryByTestId("entity-graph-stub")).not.toBeInTheDocument();
  });
});
