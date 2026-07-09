/**
 * components/portfolio/__tests__/PortfolioKPIStrip.test.tsx
 *
 * WHY THIS EXISTS: Verifies that PortfolioKPIStrip renders all 8 KPI tiles
 * correctly, including the Cash and Buying Power tiles added in W2 §4.2 /
 * PLAN-0108 T-3-06. Regression guard against accidental tile removal or
 * label mutation that would confuse portfolio managers.
 *
 * MOCKED: @tanstack/react-query (useQueryClient) — the component only uses
 * queryClient.invalidateQueries for the HIGH-016 refresh button, which we
 * exercise in a dedicated test. TanStack Query itself is fully mocked so we
 * don't need a real QueryClientProvider wrapping every render.
 *
 * WHY no gateway mock: PortfolioKPIStrip is a pure presentational component;
 * all data arrives via props. No hooks fetch data inside the component —
 * useQueryClient is the only hook, and only for the refresh action.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PortfolioKPIStrip, type PortfolioKPIStripProps } from "@/components/portfolio/PortfolioKPIStrip";

// ── TanStack Query stub ────────────────────────────────────────────────────────
// WHY: useQueryClient() is called unconditionally at the top of PortfolioKPIStrip
// so jsdom can render it without a full QueryClientProvider.
// The mock returns an object whose invalidateQueries is a spy — we use that spy
// in the HIGH-016 refresh button test to verify the correct query key is fired.
const mockInvalidateQueries = vi.fn(() => Promise.resolve());
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    invalidateQueries: mockInvalidateQueries,
  }),
}));

// ── lib/query/keys stub ────────────────────────────────────────────────────────
// WHY: qk.portfolios.holdings() is called when the refresh button is clicked.
// Return a stable key tuple so the spy assertion can check for an exact value.
vi.mock("@/lib/query/keys", () => ({
  qk: {
    portfolios: {
      holdings: (id: string) => ["portfolios", id, "holdings"],
    },
  },
}));

// ── Base props ─────────────────────────────────────────────────────────────────
// WHY a shared base: every test builds on these defaults, overriding only the
// props under test. Keeps individual tests focused and avoids repetition.
const baseProps = {
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

// ── Helpers ───────────────────────────────────────────────────────────────────
// WHY PortfolioKPIStripProps directly: inferring from baseProps would restrict
// overrides to the concrete types in baseProps (e.g. `number` not `number | null`).
// Using the actual prop type lets callers pass null, undefined, or any valid variant.
function renderStrip(overrides: Partial<PortfolioKPIStripProps> = {}) {
  return render(<PortfolioKPIStrip {...baseProps} {...overrides} />);
}

// ── Tests ──────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockInvalidateQueries.mockClear();
});

describe("PortfolioKPIStrip renders 8 cells", () => {
  it("renders all 8 tile labels", () => {
    // WHY check labels (not values): label text is stable and directly tied to
    // the tile's identity. A value change (e.g. cash from $5k to $10k) must
    // never accidentally remove a tile — this test would catch that regression.
    renderStrip();

    // Tiles 1-4: always present
    expect(screen.getByText("Total Value")).toBeInTheDocument();
    expect(screen.getByText("Day P&L")).toBeInTheDocument();
    expect(screen.getByText("Unrealised P&L")).toBeInTheDocument();
    expect(screen.getByText("Realized P&L")).toBeInTheDocument();

    // Tiles 5-6: Cash + Buying Power (PLAN-0108 T-3-06 / PRD-0089 W2 §4.2)
    expect(screen.getByText("Cash")).toBeInTheDocument();
    expect(screen.getByText("Buying Pwr")).toBeInTheDocument();

    // Tiles 7-8: Gainer + Loser
    expect(screen.getByText("Top Gain")).toBeInTheDocument();
    expect(screen.getByText("Top Lose")).toBeInTheDocument();
  });

  it("renders cash and buying power values when provided", () => {
    // WHY: confirm the formatted dollar value appears in the tile so portfolio
    // managers see the actual cash balance, not just the label.
    renderStrip({ cash: 5000, buyingPower: 8500 });

    // The tile holding data-testid="kpi-cash" must contain the formatted value.
    // WHY getByTestId: the tile label "Cash" could collide with other text;
    // the testId is scoped directly to the tile element.
    const cashTile = screen.getByTestId("kpi-cash");
    // $5,000.00 — formatPrice output for 5000
    expect(cashTile).toHaveTextContent("5,000");

    const bpTile = screen.getByTestId("kpi-buying-pwr");
    expect(bpTile).toHaveTextContent("8,500");
  });
});

// ── PLAN-0122 W-B (T-A-B-01): Simple/Advanced variant ────────────────────────
describe("PortfolioKPIStrip variant (PLAN-0122 W-B)", () => {
  it("test_kpi_strip_variant_simple_renders_four_tiles", () => {
    // Simple must render EXACTLY the 4 casual tiles, in order:
    // Total Value, Day P&L, Unrealised P&L, Cash — and NOTHING else.
    renderStrip({ variant: "simple" });

    // Each KPITile roots a role="group"; Simple = exactly 4 groups.
    expect(screen.getAllByRole("group")).toHaveLength(4);

    // The four Simple tiles are present…
    expect(screen.getByText("Total Value")).toBeInTheDocument();
    expect(screen.getByText("Day P&L")).toBeInTheDocument();
    expect(screen.getByText("Unrealised P&L")).toBeInTheDocument();
    expect(screen.getByText("Cash")).toBeInTheDocument();

    // …and the four Advanced-only tiles are absent (R19: the labels the Advanced
    // tests still assert must NOT appear in Simple).
    expect(screen.queryByText("Realized P&L")).not.toBeInTheDocument();
    expect(screen.queryByText("Buying Pwr")).not.toBeInTheDocument();
    expect(screen.queryByText("Top Gain")).not.toBeInTheDocument();
    expect(screen.queryByText("Top Lose")).not.toBeInTheDocument();
  });

  it("test_kpi_strip_default_variant_renders_eight", () => {
    // No `variant` prop → default "advanced" → all 8 tiles (backward compat).
    renderStrip();
    expect(screen.getAllByRole("group")).toHaveLength(8);
  });

  it("test_kpi_strip_simple_unrealised_shows_pct", () => {
    // The Simple Unrealised tile must still carry its % sub-value so a casual
    // user sees BOTH the dollar gain and the percentage.
    renderStrip({ variant: "simple", unrealisedPnl: 2500, unrealisedPnlPct: 0.025 });
    expect(screen.getByText("+$2,500.00 (+2.50%)")).toBeInTheDocument();
  });
});

describe("PortfolioKPIStrip renders dash for missing cash", () => {
  it("renders em-dash when cash is undefined", () => {
    // WHY: when the exposure endpoint has not yet returned, cash is not known.
    // Displaying "$0.00" would mislead traders into thinking they have no cash —
    // a dash clearly communicates "data not yet available".
    const { cash: _cash, buyingPower: _bp, ...propsWithoutCash } = baseProps;
    renderStrip({ ...propsWithoutCash, cash: undefined, buyingPower: undefined });

    const cashTile = screen.getByTestId("kpi-cash");
    expect(cashTile).toHaveTextContent("—");

    const bpTile = screen.getByTestId("kpi-buying-pwr");
    expect(bpTile).toHaveTextContent("—");
  });

  it("renders em-dash when cash is null", () => {
    // WHY: null and undefined both mean "not yet loaded" — the tile must
    // handle both consistently. null is the explicit "not loaded" sentinel
    // returned by the data hook before the first successful response.
    renderStrip({ cash: null, buyingPower: null });

    expect(screen.getByTestId("kpi-cash")).toHaveTextContent("—");
    expect(screen.getByTestId("kpi-buying-pwr")).toHaveTextContent("—");
  });
});

describe("PortfolioKPIStrip explicit P&L signs (R1 sprint)", () => {
  it("prefixes positive Day P&L with '+'", () => {
    // WHY: colour alone is insufficient to read direction (colour-blind users,
    // quick scans). Positive P&L dollars must carry an explicit "+" prefix,
    // matching formatPercent's long-standing behaviour for percentages.
    renderStrip({ dayPnl: 500 });
    expect(screen.getByTestId("kpi-day-pnl")).toHaveTextContent("+$500.00");
  });

  it("renders negative Day P&L with '-' (formatPrice native sign)", () => {
    renderStrip({ dayPnl: -250 });
    expect(screen.getByTestId("kpi-day-pnl")).toHaveTextContent("-$250.00");
  });

  it("renders zero Day P&L unsigned (flat market is not a gain)", () => {
    // WHY: "+$0.00" would falsely imply direction; a genuinely flat day reads
    // as a plain "$0.00" with neutral colour.
    renderStrip({ dayPnl: 0 });
    const tile = screen.getByTestId("kpi-day-pnl");
    expect(tile).toHaveTextContent("$0.00");
    expect(tile.textContent).not.toContain("+");
  });

  it("prefixes positive Unrealised P&L with '+'", () => {
    // unrealisedPnl 2500 / 2.5% — the dollar amount AND the percentage must
    // both be signed so the tile doesn't mix conventions.
    renderStrip({ unrealisedPnl: 2500, unrealisedPnlPct: 0.025 });
    expect(screen.getByText("+$2,500.00 (+2.50%)")).toBeInTheDocument();
  });
});

describe("PortfolioKPIStrip Day P&L skeleton", () => {
  it("renders skeleton when dayPnl is null (quotes not yet loaded)", () => {
    // WHY: F-P-012 — a missing $0 for an unknown day P&L misleads traders.
    // The skeleton communicates "loading" rather than "market is flat".
    renderStrip({ dayPnl: null });

    // The skeleton carries data-testid="kpi-day-pnl-skeleton" (set directly
    // on the Skeleton component via the valueNode prop in the component).
    expect(screen.getByTestId("kpi-day-pnl-skeleton")).toBeInTheDocument();
  });
});

describe("PortfolioKPIStrip Realized P&L approx badge + refresh", () => {
  it("shows (approx) badge when realizedPnlApprox is true", () => {
    // WHY: PLAN-0051 T-A-1-05 — traders must know when they're seeing a
    // client-side approximation vs the FIFO-accurate value from the endpoint.
    renderStrip({ realizedPnlApprox: true, portfolioId: "p1" });

    expect(screen.getByText("(approx)")).toBeInTheDocument();
  });

  it("shows refresh button when approx and portfolioId are set", async () => {
    // WHY: HIGH-016 — the refresh button lets traders force a re-fetch when
    // the FIFO endpoint was temporarily unavailable at page load.
    renderStrip({ realizedPnlApprox: true, portfolioId: "portfolio-123" });

    const refreshBtn = screen.getByTestId("kpi-realized-pnl-refresh");
    expect(refreshBtn).toBeInTheDocument();

    // Click the refresh button and verify invalidateQueries was called with
    // the correct holdings query key for the active portfolio.
    await userEvent.click(refreshBtn);
    expect(mockInvalidateQueries).toHaveBeenCalledWith({
      queryKey: ["portfolios", "portfolio-123", "holdings"],
    });
  });

  it("does NOT show refresh button when portfolioId is absent", () => {
    // WHY: without a portfolioId we cannot scope the invalidation — the button
    // would invalidate too broadly or not at all. Hide it entirely.
    renderStrip({ realizedPnlApprox: true, portfolioId: undefined });

    expect(screen.queryByTestId("kpi-realized-pnl-refresh")).not.toBeInTheDocument();
  });
});

describe("PortfolioKPIStrip top gainer/loser tiles", () => {
  it("renders ticker and percentage for gainer and loser", () => {
    renderStrip({
      topGainer: { ticker: "NVDA", pnlPct: 42.5 },
      topLoser: { ticker: "COIN", pnlPct: -18.3 },
    });

    // Gainer tile — should contain the ticker symbol
    const gainTile = screen.getByText("Top Gain").closest("[class]");
    expect(gainTile).toBeTruthy();
    // Loser tile
    const loseTile = screen.getByText("Top Lose").closest("[class]");
    expect(loseTile).toBeTruthy();

    // Verify the ticker symbols appear somewhere in the strip
    expect(screen.getByText(/NVDA/)).toBeInTheDocument();
    expect(screen.getByText(/COIN/)).toBeInTheDocument();
  });

  it("renders em-dash when there are no holdings", () => {
    // WHY: a new portfolio with no trades has no gainer or loser.
    // The tile must still render gracefully rather than crashing.
    renderStrip({ topGainer: null, topLoser: null });

    // Both tiles render "—" — getAllByText since both tiles produce the same
    // em-dash character.
    const dashes = screen.getAllByText("—");
    // At minimum gainer + loser tiles render a dash (plus cash/buying power
    // dashes when they're null, but here they're provided in baseProps).
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });
});
