/**
 * components/portfolio/__tests__/portfolio-advanced-snapshot.test.tsx —
 * PLAN-0122 W-A (T-A-A-04): the ANTI-FORK guard.
 *
 * WHY THIS EXISTS: PRD-0122's #1 risk is that "Simple" and "Advanced" drift into
 * a fork and power users silently lose features. The design is a *rendering gate,
 * never a fork*: Advanced mode must equal today's output byte-for-byte. These
 * tests capture "today's Advanced layout" BEFORE W-B adds any conditional
 * rendering, so if a later wave accidentally changes Advanced output, the diff
 * fails here and the fork is caught at review time.
 *
 * ⚠️ SNAPSHOT REGENERATION POLICY: regeneration of this snapshot requires an
 * EXPLICIT, intended Advanced-layout change — NEVER a Simple-mode side effect. If
 * `pnpm vitest -u` changes this file because of a Simple-mode edit, that is a
 * real fork bug: fix the code, do not update the snapshot.
 *
 * ✅ SANCTIONED REGENERATION — PLAN-0122 W-D (the ONE approved change so far):
 *   W-D added a pinned-right ACTIONS kebab column to the holdings table
 *   (`ag-holdings-columns.tsx` → colId "actions"). This is an INTENTIONAL
 *   Advanced-layout change (the plan's W-D Break Impact table explicitly
 *   authorises it), NOT a Simple-mode side effect: the Advanced table now carries
 *   an extra empty header cell + a per-row ⋮ button. The snapshot was regenerated
 *   with `pnpm vitest run -u` for this and only this reason. Any FURTHER diff must
 *   again be traced to a deliberate Advanced change before you run -u.
 *
 * ✅ SANCTIONED REGENERATION — PLAN-0122 W-E (the SECOND approved change):
 *   W-E added the ⚙ HoldingsColumnGroupToggle (a Settings2 gear button) to the
 *   HoldingsTableChrome row, rendered ONLY in Advanced mode (PRD §6.7 / R-26).
 *   This is an INTENTIONAL Advanced-layout addition (the plan's W-E tasks
 *   explicitly authorise the toggle UI), NOT a Simple-mode side effect — Simple
 *   passes `columnToggle={null}` so its chrome is byte-identical to before. The
 *   snapshot was regenerated with `pnpm vitest run -u` for this and only this
 *   reason: the Advanced chrome now carries the extra gear button. Any FURTHER
 *   diff must again be traced to a deliberate Advanced change before you run -u.
 *
 * SCOPE NOTE (deviation, documented): the plan's T-A-A-04 lists both HoldingsTab
 * strips AND page-level chrome (8 KPI tiles, the 4-trigger TabsList) in one
 * snapshot. Mounting the whole `page.tsx` would require mocking usePortfolioData
 * + useAuth + the bundle/filter hooks — an enormous, brittle harness for a
 * scaffold wave. Instead we guard the two surfaces W-B actually gates with the
 * lightest faithful mounts: (a) the HoldingsTab strip layout (snapshot +
 * presence), and (b) the KPI-strip tile count (8). The page-level TabsList gate
 * is covered by the W-B unit tests + the forced-Advanced e2e specs.
 */

import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── next/navigation mock ─────────────────────────────────────────────────────
// WHY: SemanticHoldingsTable (rendered inside HoldingsTab) calls useRouter at the
// top level; several strip panels read usePathname/useSearchParams. jsdom has no
// Next router, so we provide inert stubs (same pattern as
// __tests__/portfolio-wave-f-polish.test.tsx).
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
// WHY: HoldingsTab's data hooks (useHoldingsSeries, useExposure, …) read
// `accessToken` from AuthContext, which throws outside an <AuthProvider>. We stub
// the context hook so the tree mounts without the full auth provider (the queries
// stay pending in jsdom regardless — we only need the tree to render).
vi.mock("@/contexts/AuthContext", () => ({
  useAuthContext: () => ({
    isLoading: false,
    isAuthenticated: true,
    accessToken: "test-token",
    user: null,
    setTokens: vi.fn(),
    logout: vi.fn(),
  }),
  // AuthProvider is exported for real callers; a passthrough keeps any import
  // that references it from breaking (nothing in this test renders it).
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import { HoldingsTab } from "@/features/portfolio/components/HoldingsTab";
import { PortfolioKPIStrip } from "@/components/portfolio/PortfolioKPIStrip";
import type { Holding } from "@/types/api";
import type { PortfolioKPI, PortfolioAllocations } from "@/features/portfolio/lib/kpi";

// ── Fixtures (fixed so the snapshot is deterministic) ────────────────────────
function wrap(children: ReactNode) {
  // retry:false so the strip panels' queries settle immediately (they stay
  // pending with no network in jsdom — deterministic loading output).
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const HOLDING: Holding = {
  holding_id: "h-1",
  portfolio_id: "p-1",
  instrument_id: "ins-1",
  entity_id: "ent-1",
  ticker: "AAPL",
  name: "Apple",
  quantity: 10,
  average_cost: 100,
  current_price: 150,
  unrealised_pnl: 500,
  unrealised_pnl_pct: 0.5,
};

const KPI: PortfolioKPI = {
  totalValue: 1500,
  dayPnl: 25,
  unrealisedPnl: 500,
  unrealisedPnlPct: 0.5,
  topGainer: { ticker: "AAPL", pnlPct: 50 },
  topLoser: { ticker: "MSFT", pnlPct: -5 },
  positionCount: 1,
  realizedPnl: 0,
};

const ALLOC: Pick<PortfolioAllocations, "bySector" | "byType"> = {
  bySector: [{ label: "Technology", value: 1500, pct: 1 }],
  byType: [{ label: "Equity", value: 1500, pct: 1 }],
};

// WHY portfolioKind=null (not "manual"/"brokerage"): those kinds swap the table
// for an empty-state when holdings are 0; with a holding present and kind null we
// render the real Case-4 table + all strips — i.e. today's Advanced layout.
function renderAdvancedHoldings(mode?: "simple" | "advanced") {
  return render(
    <HoldingsTab
      // When `mode` is undefined we exercise the DEFAULT (must be "advanced").
      {...(mode ? { mode } : {})}
      activePortfolioId="p-1"
      holdingsLoading={false}
      holdingsResp={{ holdings: [HOLDING] } as never}
      enrichedHoldings={[HOLDING]}
      holdingsQuotes={{}}
      holdingOverviews={{}}
      kpi={KPI}
      bySector={ALLOC.bySector}
      byType={ALLOC.byType}
      equityPeriod="3M"
      setEquityPeriod={() => {}}
      portfolioKind={null}
    />,
    { wrapper: ({ children }) => wrap(children) },
  );
}

const KPI_PROPS = {
  totalValue: 100_000,
  dayPnl: 500,
  unrealisedPnl: 2500,
  unrealisedPnlPct: 0.025,
  topGainer: { ticker: "AAPL", pnlPct: 15.5 },
  topLoser: { ticker: "META", pnlPct: -8.2 },
  realizedPnl: 1200,
  cash: 5000,
  buyingPower: 5000,
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe("PLAN-0122 W-A · Advanced-mode parity (anti-fork guard)", () => {
  it("test_advanced_mode_is_todays_layout: Advanced HoldingsTab === committed snapshot", () => {
    const { container } = renderAdvancedHoldings("advanced");

    // Human-readable presence assertions (so a reviewer sees intent even without
    // reading the opaque snapshot): the two power-strips W-B gates are present.
    expect(screen.getByTestId("overview-panel-band")).toBeInTheDocument();
    expect(screen.getByTestId("bottom-strip-cluster")).toBeInTheDocument();

    // Byte-level guard: any accidental change to Advanced output diffs here.
    // See the REGENERATION POLICY in the file header before running -u.
    expect(container).toMatchSnapshot();
  });

  it("test_advanced_mode_kpi_tile_count_is_eight: KPI strip renders exactly 8 tiles", () => {
    // Each KPITile roots a role="group"; the Advanced strip must render all 8
    // (Total Value, Day P&L, Unrealised, Realized, Cash, Buying Pwr, Top Gain,
    // Top Lose). W-B's Simple variant returns after the 4th — this pins the
    // Advanced (default) count so that gate cannot silently drop a tile.
    render(<PortfolioKPIStrip {...KPI_PROPS} />, {
      wrapper: ({ children }) => wrap(children),
    });
    expect(screen.getAllByRole("group")).toHaveLength(8);
  });

  it("test_holdingstab_defaults_mode_advanced: no mode prop behaves as Advanced", () => {
    // T-A-A-03 acceptance: HoldingsTab without a `mode` prop renders the full
    // Advanced strip set (default "advanced"), so every existing caller/test is
    // unchanged by the new optional prop.
    renderAdvancedHoldings(/* no mode → default */);
    expect(screen.getByTestId("overview-panel-band")).toBeInTheDocument();
    expect(screen.getByTestId("bottom-strip-cluster")).toBeInTheDocument();
  });
});
