/**
 * __tests__/screener-columndefs-stability.test.tsx — Round-4 item 3a:
 * columnDef identity must be stable across unrelated state changes.
 *
 * WHY THIS EXISTS: AG Grid diffs `columnDefs` by REFERENCE — handing it a
 * freshly-built array forces a full column reconciliation pass (header
 * re-render, width re-measure), which is one of the most expensive things a
 * React parent can do to the grid. The page memoises
 * `createAgScreenerColumns(sparklines, suppressed)` on its inputs, but the
 * memo is only as stable as those inputs:
 *
 *   BUG (fixed Round 4): useScreenerSparklines returns `query.data ?? {}` —
 *   a NEW `{}` literal every render whenever sparkline data is absent. That
 *   fresh identity invalidated the useMemo on EVERY page render, so toggling
 *   the filter panel (or hovering a row) rebuilt all 34 columns. The page now
 *   substitutes a module-level EMPTY_SPARKLINES constant for the empty case.
 *
 * TEST STRATEGY: wrap the real ColDef factory in a spy (vi.mock with
 * importOriginal so behaviour is unchanged), render the page, let it settle,
 * then perform an unrelated state change (filter-panel open/close) and assert
 * the factory was NOT invoked again. Without the page-level identity fix this
 * fails (the factory re-runs once per render).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";

// ── Spy-wrap the REAL factory ────────────────────────────────────────────────
// WHY importOriginal: we want production ColDefs (the grid must actually
// mount); the mock only adds call-counting on top.
vi.mock("@/components/screener/ag-screener-columns", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/screener/ag-screener-columns")>();
  return {
    ...actual,
    createAgScreenerColumns: vi.fn(actual.createAgScreenerColumns),
  };
});

const { runScreenerMock } = vi.hoisted(() => ({
  runScreenerMock: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    runScreener: runScreenerMock,
    // NOTE: getBatchOhlcvBars is deliberately ABSENT — the sparkline query
    // errors out (retry: false), so `query.data` stays undefined and the
    // hook's `?? {}` empty-fallback path (the historically unstable one) is
    // exactly what this test exercises.
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
import { createAgScreenerColumns } from "@/components/screener/ag-screener-columns";

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

beforeEach(() => {
  vi.mocked(createAgScreenerColumns).mockClear();
  runScreenerMock.mockReset();
  runScreenerMock.mockImplementation(async () => ({
    results: [
      {
        instrument_id: "ins-1",
        entity_id: "ent-1",
        ticker: "AAPL",
        name: "Apple Inc.",
        gics_sector: "Information Technology",
        market_cap: 3e12,
        pe_ratio: 28.5,
        daily_return: 0.01,
        market_impact_score: 0.75,
      },
    ],
    total: 1,
    offset: 0,
    limit: 50,
  }));
});

describe("ScreenerPage — columnDefs identity stability (Round 4 item 3a)", () => {
  it("does NOT rebuild column definitions when the filter panel toggles", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // Let the page fully settle: data row rendered, queries resolved.
    await screen.findByText("AAPL");

    const callsAfterSettle = vi.mocked(createAgScreenerColumns).mock.calls.length;
    // Sanity: the factory ran at least once to mount the grid at all.
    expect(callsAfterSettle).toBeGreaterThanOrEqual(1);

    // Unrelated state change #1: open the filter panel (mounts the dynamic
    // ScreenerFilterBar chunk → multiple page re-renders).
    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    await waitFor(() =>
      expect(
        screen.getByLabelText(/search instruments by name or ticker/i),
      ).toBeInTheDocument(),
    );

    // Unrelated state change #2: close it again.
    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));

    // The memoised inputs (sparklines map identity + suppressed flag) did not
    // change, so the factory must not have been invoked again. Pre-fix this
    // was `callsAfterSettle + N` (one rebuild per re-render) because the
    // sparkline empty-fallback allocated a fresh `{}` each render.
    expect(vi.mocked(createAgScreenerColumns).mock.calls.length).toBe(callsAfterSettle);
  });
});
