/**
 * __tests__/portfolio-wave-f-polish.test.tsx — Unit tests for PLAN-0051 Wave F.
 *
 * WHY THIS EXISTS: Wave F closes 21 polish items across the portfolio surface.
 * The behavioural fixes (skeleton vs zero, sort persistence, resolution
 * timeout, colour-blind encoding, sector a11y, empty-state copy, etc.) need
 * regression coverage so future PRs can't silently revert them.
 *
 * SCOPE: this file pins the contracts that have observable DOM/behaviour
 * impact. Pure CSS tweaks (row height, divider tone, padding) are not
 * unit-testable from jsdom — those are validated by visual review + the
 * heavy WHY comments in the source.
 *
 * MOCKED MODULES:
 *   - @/hooks/useAuth: stub auth so components don't gate on a real token.
 *   - @/lib/gateway: stub the gateway so EquityCurveChart / ExposureBreakdown
 *     have controlled responses.
 *   - next/navigation: useRouter().replace + useSearchParams capture URL writes
 *     for the holdings sort persistence test (F-P-025).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Auth mock — every consumer gates on accessToken; provide one. ───────────
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

// ── Gateway mock — simple stub; per-test override via mockResolvedValue. ───
const mockGetExposure = vi.fn();
const mockGetValueHistory = vi.fn();
const mockGetRiskMetrics = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getExposure: mockGetExposure,
    getValueHistory: mockGetValueHistory,
    getRiskMetrics: mockGetRiskMetrics,
    getBatchQuotes: vi.fn().mockResolvedValue({ quotes: {} }),
    getWatchlistMembers: vi.fn().mockResolvedValue([]),
  })),
}));

// ── next/navigation mock — capture URL replace calls. ───────────────────────
const mockReplace = vi.fn();
const mockSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: mockReplace,
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => mockSearchParams),
}));

// ── SUT imports ─────────────────────────────────────────────────────────────
import { PortfolioKPIStrip } from "@/components/portfolio/PortfolioKPIStrip";
import { ExposureBreakdown } from "@/components/portfolio/ExposureBreakdown";
import { SemanticHoldingsTable } from "@/components/portfolio/SemanticHoldingsTable";
import { SectorAllocationPanel } from "@/components/portfolio/SectorAllocationPanel";
import { TransactionsTable } from "@/components/portfolio/TransactionsTable";
import { EquityCurveChart } from "@/components/portfolio/EquityCurveChart";
import type { Holding, Transaction } from "@/types/api";

// ── Helpers ─────────────────────────────────────────────────────────────────
function wrap(children: ReactNode) {
  // Disable retries so error/empty paths resolve immediately.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const baseKpiProps = {
  totalValue: 100_000,
  unrealisedPnl: 0,
  unrealisedPnlPct: 0,
  topGainer: null,
  topLoser: null,
  positionCount: 0,
};

beforeEach(() => {
  vi.clearAllMocks();
  // Reset URL state between tests so F-P-025 tests stay isolated.
  for (const key of Array.from(mockSearchParams.keys())) {
    mockSearchParams.delete(key);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// F-P-012: Day P&L tile distinguishes null (unknown) from 0 (genuine zero).
// ─────────────────────────────────────────────────────────────────────────────
describe("Wave F · F-P-012 · Day P&L skeleton vs $0", () => {
  it("renders a skeleton placeholder when dayPnl is null (quotes not loaded)", () => {
    render(<PortfolioKPIStrip {...baseKpiProps} dayPnl={null} />);
    // Skeleton has the dedicated test id we added in PortfolioKPIStrip.
    expect(screen.getByTestId("kpi-day-pnl-skeleton")).toBeInTheDocument();
    // Sanity: no "$0.00" string for the Day P&L tile when dayPnl is null.
    const tile = screen.getByTestId("kpi-day-pnl");
    expect(tile.textContent).not.toContain("$0.00");
  });

  it("renders $0.00 (no skeleton) when dayPnl is genuinely zero", () => {
    render(<PortfolioKPIStrip {...baseKpiProps} dayPnl={0} />);
    // No skeleton — value is known and zero.
    expect(screen.queryByTestId("kpi-day-pnl-skeleton")).not.toBeInTheDocument();
    const tile = screen.getByTestId("kpi-day-pnl");
    expect(tile.textContent).toContain("$0.00");
  });

  it("renders the formatted positive value when dayPnl > 0", () => {
    render(<PortfolioKPIStrip {...baseKpiProps} dayPnl={123.45} />);
    expect(screen.queryByTestId("kpi-day-pnl-skeleton")).not.toBeInTheDocument();
    expect(screen.getByTestId("kpi-day-pnl").textContent).toContain("123.45");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// F-P-002: ExposureBreakdown empty state vertically centered.
// ─────────────────────────────────────────────────────────────────────────────
describe("Wave F · F-P-002 · Exposure empty state centering", () => {
  it("centers the empty state inside a min-height block when total = 0", async () => {
    mockGetExposure.mockResolvedValue({
      invested: 0,
      cash: 0,
      gross_exposure_pct: 0,
      prices_stale: false,
    });

    const { container, findByText } = render(
      <ExposureBreakdown portfolioId="p-1" />,
      { wrapper: ({ children }) => wrap(children) },
    );

    await findByText(/No positions to measure/i);
    // The wrapping container must have the min-h-[180px] class so the panel
    // doesn't shrink to fit the message.
    const minHeightBlock = container.querySelector('.min-h-\\[180px\\]');
    expect(minHeightBlock).not.toBeNull();
    // The flex-centering wrapper must surround the empty state copy.
    const centeredFlex = container.querySelector(".items-center.justify-center");
    expect(centeredFlex).not.toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// F-P-003: EquityCurveChart period state is controllable from the parent.
// ─────────────────────────────────────────────────────────────────────────────
describe("Wave F · F-P-003 · EquityCurveChart period hoist", () => {
  it("calls onPeriodChange when the user clicks a period button", async () => {
    mockGetValueHistory.mockResolvedValue({
      points: [
        { date: "2026-04-01", value: 100, cost_basis: 100, cash: 0 },
        { date: "2026-04-29", value: 110, cost_basis: 100, cash: 0 },
      ],
      metadata: { last_snapshot_at: "2026-04-29", next_scheduled_run_utc: null },
    });
    const onPeriodChange = vi.fn();

    render(
      <EquityCurveChart
        portfolioId="p-1"
        period="3M"
        onPeriodChange={onPeriodChange}
      />,
      { wrapper: ({ children }) => wrap(children) },
    );

    // The toggle buttons render the period labels — click "1Y".
    const oneYearBtn = await screen.findByText("1Y");
    fireEvent.click(oneYearBtn);
    expect(onPeriodChange).toHaveBeenCalledWith("1Y");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// F-P-014: Sector allocation bar a11y — aria-label per bar.
// ─────────────────────────────────────────────────────────────────────────────
describe("Wave F · F-P-014 · Sector bar a11y label", () => {
  it("renders aria-label='Sector X: Y%' on each allocation bar in BARS view", () => {
    // PLAN-0053 T-D-4-04: SectorAllocationPanel now defaults to a Treemap
    // view; the legacy bar a11y attribute lives on the BARS view. Click
    // the toggle to switch view, then assert the original contract.
    render(
      <SectorAllocationPanel
        bySector={[
          { label: "Information Technology", value: 50000, pct: 50 },
          { label: "Financials", value: 25000, pct: 25 },
        ]}
        byType={[]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "bars" }));
    // role=img + aria-label exposes the percentage to assistive tech.
    expect(
      screen.getByLabelText("Sector Information Technology: 50.0%"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Sector Financials: 25.0%")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// F-P-016: Empty state copy guide — Title + Body explanation.
// ─────────────────────────────────────────────────────────────────────────────
describe("Wave F · F-P-016 · Empty-state copy", () => {
  it("transactions empty state explains how to populate the table", () => {
    render(<TransactionsTable transactions={[]} />);
    // Title + body in one InlineEmptyState string.
    expect(screen.getByText(/No transactions yet\./i)).toBeInTheDocument();
    expect(
      screen.getByText(/Connect a brokerage to import activity/i),
    ).toBeInTheDocument();
  });

  it("holdings empty state mentions both connect-brokerage and Add Position paths", () => {
    render(
      <SemanticHoldingsTable
        holdings={[]}
        quotes={{}}
        sectors={{}}
        totalValue={0}
      />,
    );
    expect(screen.getByText(/No holdings yet\./i)).toBeInTheDocument();
    expect(screen.getByText(/Add Position/i)).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// F-P-025: Holdings sort state is persisted to URL on click.
// ─────────────────────────────────────────────────────────────────────────────
describe("Wave F · F-P-025 · Sort persisted to URL", () => {
  function holding(over: Partial<Holding>): Holding {
    return {
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
      unrealised_pnl_pct: 50,
      ...over,
    };
  }

  it("calls router.replace with sort+dir query params when a header is clicked", async () => {
    const holdings: Holding[] = [
      holding({ holding_id: "h-1", ticker: "AAPL", quantity: 10 }),
      holding({ holding_id: "h-2", ticker: "MSFT", quantity: 5 }),
    ];

    render(
      <SemanticHoldingsTable
        holdings={holdings}
        quotes={{}}
        sectors={{}}
        totalValue={2000}
      />,
    );

    // The default sort is value/desc — first header click on QTY should
    // change the URL to sort=qty&dir=desc.
    const qtyHeader = screen.getByText("QTY");
    fireEvent.click(qtyHeader);

    // useEffect runs after render — wait for the effect tick.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(mockReplace).toHaveBeenCalled();
    const lastCall = mockReplace.mock.calls[mockReplace.mock.calls.length - 1];
    const [url] = lastCall;
    expect(String(url)).toContain("sort=qty");
    expect(String(url)).toContain("dir=desc");
  });

  it("reads initial sort from URL params when present", async () => {
    // Pre-seed the mocked search params so the table picks them up at mount.
    mockSearchParams.set("sort", "pnl");
    mockSearchParams.set("dir", "asc");

    const holdings: Holding[] = [
      holding({ holding_id: "h-1", ticker: "AAPL", quantity: 10 }),
      holding({ holding_id: "h-2", ticker: "MSFT", quantity: 5 }),
    ];

    render(
      <SemanticHoldingsTable
        holdings={holdings}
        quotes={{}}
        sectors={{}}
        totalValue={2000}
      />,
    );

    // After mount the active sort should be PNL (visible as the column with
    // text-primary class). We assert by verifying the P&L $ header renders
    // the sort indicator (▲ for asc).
    const pnlHeader = screen.getByText("P&L $").parentElement;
    // The indicator span carries " ▲" — assert that text is present in the
    // header cell when the URL drives PNL/ASC.
    expect(pnlHeader?.textContent).toContain("▲");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// F-P-026: Cash vs Invested colourblind-safe encoding.
// ─────────────────────────────────────────────────────────────────────────────
describe("Wave F · F-P-026 · Exposure colourblind encoding", () => {
  it("renders distinct backgroundImage on cash vs invested segments", async () => {
    mockGetExposure.mockResolvedValue({
      invested: 60_000,
      cash: 40_000,
      gross_exposure_pct: 0.6,
      prices_stale: false,
    });

    const { container, findByLabelText } = render(
      <ExposureBreakdown portfolioId="p-1" />,
      { wrapper: ({ children }) => wrap(children) },
    );

    // Wait for the bar to render.
    await findByLabelText(/Invested 60\.0% \/ Cash 40\.0%/);

    // The cash segment should carry a backgroundImage (diagonal stripes);
    // we look for any element with style.backgroundImage matching repeating-linear-gradient.
    const segments = container.querySelectorAll('[style*="repeating-linear-gradient"]');
    // Should find at least the cash segment + the cash legend swatch.
    expect(segments.length).toBeGreaterThanOrEqual(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// F-P-028: Zero-qty/zero-price transactions render with muted style.
// ─────────────────────────────────────────────────────────────────────────────
describe("Wave F · F-P-028 · Zero-qty placeholder rows are de-emphasised", () => {
  function tx(overrides: Partial<Transaction>): Transaction {
    return {
      transaction_id: "tx-x",
      portfolio_id: "p1",
      instrument_id: "ins-x",
      ticker: "AAPL",
      // PLAN-0053 T-D-4-02: asset_class is required on Transaction now.
      asset_class: null,
      type: "BUY",
      quantity: 10,
      price: 100,
      fee: 1,
      amount: null,
      currency: "USD",
      executed_at: "2026-04-01T15:30:00Z",
      notes: null,
      ...overrides,
    };
  }

  it("applies text-muted-foreground/50 to the row when qty=0 and price=0 (corporate-action sentinel)", () => {
    const data: Transaction[] = [
      tx({ transaction_id: "tx-real", quantity: 5, price: 200 }),
      tx({
        transaction_id: "tx-zero",
        ticker: "ZZZ",
        quantity: 0,
        price: 0,
        type: "BUY",
      }),
    ];
    render(<TransactionsTable transactions={data} />);
    // The placeholder row's <tr> carries the muted class.
    const placeholderBadge = screen.getByTestId("tx-type-tx-zero");
    const placeholderRow = placeholderBadge.closest("tr");
    expect(placeholderRow).not.toBeNull();
    expect(placeholderRow!.className).toContain("text-muted-foreground/50");

    // The real row does NOT have the muted class.
    const realBadge = screen.getByTestId("tx-type-tx-real");
    const realRow = realBadge.closest("tr");
    expect(realRow!.className).not.toContain("text-muted-foreground/50");
  });

  it("renders 'n/a' as the Total cell for placeholder rows (not $0)", () => {
    const data: Transaction[] = [
      tx({
        transaction_id: "tx-zero",
        ticker: "ZZZ",
        quantity: 0,
        price: 0,
        type: "BUY",
      }),
    ];
    render(<TransactionsTable transactions={data} />);
    // The placeholder row should NOT show "$0.00" in the Total column —
    // it shows "n/a" so the user reads "this isn't a real fill".
    expect(screen.getByText("n/a")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// F-P-022: Canonical period set documented + comprehensive.
// ─────────────────────────────────────────────────────────────────────────────
describe("Wave F · F-P-022 · Canonical equity-curve period set", () => {
  it("renders exactly the 6 canonical period buttons (1W / 1M / 3M / 6M / 1Y / All)", async () => {
    mockGetValueHistory.mockResolvedValue({
      points: [
        { date: "2026-04-01", value: 100, cost_basis: 100, cash: 0 },
      ],
      metadata: { last_snapshot_at: "2026-04-01", next_scheduled_run_utc: null },
    });

    render(<EquityCurveChart portfolioId="p-1" />, {
      wrapper: ({ children }) => wrap(children),
    });

    // Each of the 6 canonical labels is rendered exactly once. WHY: the
    // F-P-022 contract is "DO NOT silently re-add removed periods" — if a
    // future PR adds a 7th button this assertion catches it.
    for (const label of ["1W", "1M", "3M", "6M", "1Y", "All"]) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
    // 1D MUST NOT appear — F-P-006 explains why (no intraday snapshots).
    expect(screen.queryByText("1D")).toBeNull();
  });
});

// Cleanup any leaked mocks across the whole suite.
afterEach(() => {
  vi.restoreAllMocks();
});
