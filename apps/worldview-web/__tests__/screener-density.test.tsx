/**
 * __tests__/screener-density.test.tsx — Round-3 item 1: 20px row adoption
 *
 * WHY THIS EXISTS: the screener page adopted AgGridBase's Round-2
 * rowHeight/headerHeight props with the value 20 (NOT the §15.10 22px token —
 * the T-IA-14 architecture guard locks the screener to 20px for the
 * "≥240 cells above the fold" density gate). These tests pin:
 *
 *   1. PASSTHROUGH — the page passes rowHeight={20} + headerHeight={20} all
 *      the way down to AgGridReact (no default-28 regression, no 22 "fix").
 *   2. SKELETON — while the FIRST query is in flight, the shape-matched
 *      ScreenerTableSkeleton overlay is shown (Round-3 item 4), and it goes
 *      away once data lands.
 *
 * MOCK STRATEGY: same "spy component" pattern as
 * components/ui/ag-grid/__tests__/AgGridBase.test.tsx — a test-local
 * vi.mock("ag-grid-react") overrides the global table-shim from
 * vitest.setup.ts and echoes the height props as data-* attributes. We test
 * OUR prop plumbing, not AG Grid's rendering.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";

// ── ag-grid-react spy (test-local; overrides the global setup mock) ──────────
vi.mock("ag-grid-react", () => ({
  AgGridReact: (props: Record<string, unknown>) => (
    <div
      data-testid="ag-grid-spy"
      data-row-height={String(props.rowHeight)}
      data-header-height={String(props.headerHeight)}
    />
  ),
}));

// ── Controllable gateway mock ─────────────────────────────────────────────────
// WHY vi.hoisted: vi.mock factories hoist above imports; hoisting the spy
// alongside lets individual tests swap runScreener's behaviour (pending vs
// resolved) without re-mocking the whole module.
const { runScreenerMock } = vi.hoisted(() => ({
  runScreenerMock: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    runScreener: runScreenerMock,
    refreshToken: vi.fn(),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/screener"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "t@e.com", name: "T", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

import ScreenerPage from "@/app/(app)/screener/page";

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <NuqsTestingAdapter searchParams="">
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </NuqsTestingAdapter>
    );
  };
}

const ONE_ROW_RESPONSE = {
  results: [
    {
      instrument_id: "ins-1",
      entity_id: "ent-1",
      ticker: "AAPL",
      name: "Apple Inc.",
      exchange: "NASDAQ",
      gics_sector: "Information Technology",
      market_cap: 3_000_000_000_000,
      pe_ratio: 28.5,
      daily_return: 0.0124,
      market_impact_score: 0.75,
    },
  ],
  total: 1,
  offset: 0,
  limit: 50,
};

beforeEach(() => {
  runScreenerMock.mockReset();
});

describe("ScreenerPage — 20px density adoption (Round 3 item 1)", () => {
  it("passes rowHeight=20 and headerHeight=20 through to AgGridReact", async () => {
    runScreenerMock.mockResolvedValue(ONE_ROW_RESPONSE);
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    const grid = await screen.findByTestId("ag-grid-spy");
    // WHY both asserted: §15.10 rule 3 — header must match rows. A regression
    // to the 28 default (or a "fix" to 22, forbidden by T-IA-14) fails here
    // with a precise diff.
    expect(grid).toHaveAttribute("data-row-height", "20");
    expect(grid).toHaveAttribute("data-header-height", "20");
  });
});

describe("ScreenerPage — loading skeleton (Round 3 item 4)", () => {
  it("shows the shape-matched table skeleton while the first query is pending", async () => {
    // Never-resolving promise pins the page in isLoading.
    runScreenerMock.mockImplementation(() => new Promise(() => {}));
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    expect(await screen.findByTestId("screener-table-skeleton")).toBeInTheDocument();
    // The grid stays MOUNTED underneath (overlay pattern) — the headers test
    // in screener.test.tsx depends on this.
    expect(screen.getByTestId("ag-grid-spy")).toBeInTheDocument();
  });

  it("removes the skeleton once data lands", async () => {
    runScreenerMock.mockResolvedValue(ONE_ROW_RESPONSE);
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(screen.queryByTestId("screener-table-skeleton")).not.toBeInTheDocument();
    });
  });
});
