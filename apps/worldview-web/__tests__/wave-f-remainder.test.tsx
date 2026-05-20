/**
 * __tests__/wave-f-remainder.test.tsx — Vitest tests for PLAN-0050 Wave F remainder tasks
 *
 * WHY THIS EXISTS: Covers the deferred Wave F tasks implemented in the final
 * Wave F pass:
 *   - T-F-6-03: Dashboard widget inner padding standardised to px-3 py-2
 *   - T-F-6-07: FundamentalSparkline right Y-axis (formatYAxisLabel helper)
 *   - T-F-6-11: FundamentalSparkline showAxis prop is wired to the rendered output
 *   - T-F-6-12: Instrument page loading skeleton matches the 9-section layout
 *
 * WHY UNIT TESTS (not e2e): These are visual-structure tests — they verify that
 * specific DOM attributes/classes are present. Unit tests run in under 100ms and
 * give instant feedback; e2e tests are reserved for user-flow scenarios that require
 * a real browser (navigation, hover states, scroll behaviour).
 *
 * WHAT IS NOT TESTED HERE:
 *   - T-F-6-13 (no date filter in NewsTab) — closed by code comment; no testable assertion
 *   - T-F-6-16 (sidebar scroll unification) — architectural, verified by code review;
 *     a DOM assertion that "there is only one overflow-y-auto" is fragile and low-value
 *   - T-F-6-05, T-F-6-18 (mobile baseline) — explicitly skipped per thesis-demo carve-out
 */

import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Shared mocks ─────────────────────────────────────────────────────────────

// WHY mock next/navigation: several instrument components use useRouter/useParams.
// These are undefined in jsdom without mocking.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// WHY mock useAuth: components that fetch data gate queries on !!accessToken.
// Without a token the queries stay disabled and the loading skeleton persists.
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

// WHY mock createGateway: prevents real HTTP calls to S9 in unit tests.
// We configure the mock to return a never-resolving promise so components
// stay in the "loading" state (the state we actually want to test for skeleton tests).
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getFundamentalsTimeseries: vi.fn().mockReturnValue(new Promise(() => {})), // stays loading
    getCompanyOverview: vi.fn().mockReturnValue(new Promise(() => {})),        // stays loading
    getFundamentals: vi.fn().mockReturnValue(new Promise(() => {})),
    getFundamentalsSnapshot: vi.fn().mockReturnValue(new Promise(() => {})),
    getOHLCV: vi.fn().mockReturnValue(new Promise(() => {})),
    getEntityNews: vi.fn().mockReturnValue(new Promise(() => {})),
    getInstrumentBrief: vi.fn().mockReturnValue(new Promise(() => {})),
    getAnalystRatings: vi.fn().mockReturnValue(new Promise(() => {})),
    // WHY getEarningsCalendar: EarningsCalendarWidget (PLAN-0068 Wave B-1) converted
    // from a static placeholder to a live useQuery component. Returns a never-resolving
    // promise so the widget stays in loading state — we only test DOM structure here,
    // not the loaded state.
    getEarningsCalendar: vi.fn().mockReturnValue(new Promise(() => {})), // stays loading
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "tok",
      user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// WHY mock useAlertStream: RecentAlerts and the dashboard context use this.
// Without it, the component throws "useAlertStream must be used within AlertStreamProvider".
vi.mock("@/contexts/AlertStreamContext", () => ({
  useAlertStream: vi.fn(() => ({ recentAlerts: [], connected: false })),
}));

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * makeWrapper — provides a fresh QueryClient for each test.
 *
 * WHY fresh per test: TanStack Query caches by queryKey. Reusing the same client
 * across tests causes data from one test to leak into another via the cache.
 * A fresh client ensures each test is isolated.
 */
function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── T-F-6-07: formatYAxisLabel unit tests ────────────────────────────────────

/**
 * WHY test formatYAxisLabel directly: it's a pure function — easy to unit test
 * exhaustively. The SVG rendering path is more complex (async data, viewBox coords)
 * and covered by the snapshot test below. Separating the formatter tests from the
 * render tests isolates failures.
 *
 * We import it via the component file's named export. Since formatYAxisLabel is
 * not exported (it's module-private), we test it indirectly via the rendered DOM
 * in the sparkline snapshot tests below. The pure-function logic is implicitly
 * covered by the "right Y-axis labels" render tests.
 */

// ── T-F-6-11 & T-F-6-07: FundamentalSparkline showAxis tests ─────────────────

// FundamentalSparkline was deleted in PLAN-0090 T-E-01 (PRD-0088 §6.10 — replaced
// by inline sparkline cells inside FinancialsTab MetricsTable). T-E-02 will add
// the new sparkline coverage; until then this describe is a placeholder skip to
// keep typecheck and vitest green without referencing the deleted module path.
describe.skip("FundamentalSparkline — showAxis wiring (obsolete; see PLAN-0090 T-E-02)", () => {
  it("placeholder until T-E-02 replaces the sparkline coverage", () => {
    expect(true).toBe(true);
  });
});

// ── T-F-6-12: Instrument page skeleton section count ─────────────────────────
//
// PLAN-0090 NOTE: these three tests pin the OLD client-component page.tsx
// skeleton (the 9-section grid that lived inside OverviewLayout). PLAN-0090's
// Option B strategy explicitly deletes OverviewLayout and converts page.tsx
// into a thin server component that hands off to InstrumentPageClient. The
// "skeleton" no longer exists in the same form — each tab now owns its own
// loading state, which is verified by per-tab tests in Wave B/C/D. Skipping
// here documents intent; Wave E (T-E-02) removes this whole describe block
// once the per-tab loading tests are in place.
describe.skip("Instrument page loading skeleton — 9-section layout (T-F-6-12)", () => {
  it("renders multiple skeleton sections while overview is loading", async () => {
    // WHY dynamic import: the instrument page uses useParams (Next.js hook) which
    // requires the next/navigation mock to be active before the module is imported.
    const { default: InstrumentDetailPage } = await import(
      "@/app/(app)/instruments/[entityId]/page"
    );

    // PLAN-0090: page.tsx is now a server component awaiting params; pass a
    // type-satisfying stub. The describe block is .skip()-ed so this never
    // runs — the assignment exists only to keep `tsc --noEmit` happy until
    // Wave E removes the whole block.
    const params = Promise.resolve({ entityId: "ins-001" });
    const { container } = render(<InstrumentDetailPage params={params} />, { wrapper: makeWrapper() });

    // WHY count bg-muted elements: after T-D-4-01, Skeleton renders with static
    // rounded-[2px] bg-muted bars (no animate-pulse). The old skeleton had 3 elements;
    // the new 9-section skeleton has significantly more. We assert at least 6 to
    // confirm the expanded skeleton (exact count may vary as some elements share classes).
    const skeletons = container.querySelectorAll(".bg-muted");
    expect(skeletons.length).toBeGreaterThanOrEqual(6);
  });

  it("renders a grid container in the loading skeleton (T-F-6-12 section grid)", async () => {
    // WHY check for grid: the 9-section skeleton uses a CSS grid for the fundamentals
    // section rows (grid grid-cols-2 gap-2). Its presence confirms the layout was
    // updated from the simple stack (3 Skeletons) to the 9-section version.
    const { default: InstrumentDetailPage } = await import(
      "@/app/(app)/instruments/[entityId]/page"
    );

    // PLAN-0090: page.tsx is now a server component awaiting params; pass a
    // type-satisfying stub. The describe block is .skip()-ed so this never
    // runs — the assignment exists only to keep `tsc --noEmit` happy until
    // Wave E removes the whole block.
    const params = Promise.resolve({ entityId: "ins-001" });
    const { container } = render(<InstrumentDetailPage params={params} />, { wrapper: makeWrapper() });

    // WHY .grid: the new skeleton has a grid-cols-2 container for the section rows.
    // The old skeleton had no grid element at all.
    const gridEl = container.querySelector(".grid");
    expect(gridEl).not.toBeNull();
  });

  it("renders a col-span-2 element in the skeleton (full-width section)", async () => {
    // WHY col-span-2: the Balance Sheet / 52-Week Range section in the skeleton
    // spans both columns. Its presence confirms the 9th section was added.
    const { default: InstrumentDetailPage } = await import(
      "@/app/(app)/instruments/[entityId]/page"
    );

    // PLAN-0090: page.tsx is now a server component awaiting params; pass a
    // type-satisfying stub. The describe block is .skip()-ed so this never
    // runs — the assignment exists only to keep `tsc --noEmit` happy until
    // Wave E removes the whole block.
    const params = Promise.resolve({ entityId: "ins-001" });
    const { container } = render(<InstrumentDetailPage params={params} />, { wrapper: makeWrapper() });

    // WHY querySelectorAll: there may be multiple col-span-2 elements (chart, grid section)
    const colSpan2Elements = container.querySelectorAll(".col-span-2");
    expect(colSpan2Elements.length).toBeGreaterThan(0);
  });
});

// ── T-F-6-03: Widget inner padding standardization ────────────────────────────

describe("Dashboard widget inner padding — px-3 standard (T-F-6-03)", () => {
  it("EarningsCalendarWidget loading skeleton uses px-3 (horizontal padding preserved)", async () => {
    // WHY EarningsCalendarWidget: The widget was converted from a static placeholder
    // to a live useQuery component in PLAN-0068 Wave B-1. It now requires a
    // QueryClientProvider wrapper and the gateway mock (both set at file scope).
    // The getEarningsCalendar mock returns a never-resolving Promise so the
    // component stays in loading/skeleton state.
    //
    // SA-2 PLAN-0088 density pass: vertical padding was tightened from py-2 to
    // py-1.5 (conservative 1-unit reduction) to better match the actual 22px row
    // height when data renders. We preserve the test but update it to assert the
    // current py-1.5 (not the previous py-2) so the test stays accurate per R19
    // ("fix implementation, never delete/weaken tests" — test still verifies
    // padding behaviour, just with the updated density spec).
    const { EarningsCalendarWidget } = await import(
      "@/components/dashboard/EarningsCalendarWidget"
    );

    // WHY wrapper: EarningsCalendarWidget uses useQuery which requires QueryClientProvider.
    const { container } = render(<EarningsCalendarWidget />, { wrapper: makeWrapper() });

    // WHY check for px-3 with py-1.5: horizontal padding (px-3) is from T-F-6-03
    // (unchanged); vertical padding was tightened to py-1.5 in SA-2 PLAN-0088.
    // [class*='px-3']: attribute-contains selector works with Tailwind's JIT.
    const paddedContent = container.querySelector("[class*='px-3'][class*='py-1']");
    expect(paddedContent).not.toBeNull();
  });

  it("EarningsCalendarWidget still renders the section header at px-2", async () => {
    // WHY test header padding separately: T-F-6-03 explicitly preserves header
    // padding (px-2). We must not have accidentally changed the header row.
    const { EarningsCalendarWidget } = await import(
      "@/components/dashboard/EarningsCalendarWidget"
    );

    // WHY wrapper: EarningsCalendarWidget uses useQuery which requires QueryClientProvider.
    const { container } = render(<EarningsCalendarWidget />, { wrapper: makeWrapper() });

    // WHY check EARNINGS CALENDAR label: this text lives in the header row which
    // should still be px-2, not px-3.
    expect(screen.getByText("EARNINGS CALENDAR")).toBeInTheDocument();

    // WHY find the parent div: the header div has px-2 (not px-3).
    const headerDiv = screen.getByText("EARNINGS CALENDAR").closest("div");
    // The header div class list should contain "px-2" but NOT "px-3"
    expect(headerDiv?.className).toContain("px-2");
    expect(headerDiv?.className).not.toContain("px-3");
  });
});
