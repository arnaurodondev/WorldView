/**
 * __tests__/dashboard-round2.test.tsx — Round 2 enhancement widget coverage
 *
 * WHY THIS EXISTS: Round 2 (2026-06-10) added two new dashboard widgets.
 * Each gets render/empty/interaction coverage here with tailored mocks:
 *
 *   1. MarketClockWidget — SSR-deterministic placeholder, post-mount live
 *      clock + session state + countdown, per-second tick isolation, and the
 *      session-colored border. (The session MATH is exhaustively covered in
 *      features/dashboard/lib/__tests__/market-clock.test.ts — here we only
 *      pin the React wiring around it.)
 *   2. WatchlistQuickViewWidget — top-5-by-value selection, day P&L $
 *      (sign + semantic color), sparkline batch wiring, ticker-first row
 *      navigation, header /portfolio link, and the named empty state.
 *
 * WHY FAKE TIMERS FOR THE CLOCK: the widget owns a 1 Hz setInterval;
 * vi.setSystemTime gives us a deterministic "now" so assertions like
 * "10:00:00 ET" never flake on CI wall-clock.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Next.js router mock ───────────────────────────────────────────────────────
// WHY vi.hoisted: vi.mock factories are hoisted above imports — the shared
// push spy must exist in the hoisted scope so the factory and the test
// assertions reference the SAME function instance.
const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: pushMock, replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
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

// ── Gateway mock (WatchlistQuickView scenarios) ───────────────────────────────
// Fixture design: SIX holdings so the top-5 cut is observable. Market values
// (live price × qty):
//   AAPL  200 × 10 = 2000   ← top
//   MSFT  400 ×  4 = 1600
//   NVDA  800 ×  1.5 = 1200
//   AMZN  100 ×  8 =  800
//   GOOG  150 ×  4 =  600
//   TINY    5 × 10 =   50   ← 6th — must NOT render
// Day P&L: AAPL change +2.5 × 10 = +$25.00 (positive), MSFT −3 × 4 = −$12.00
// (negative). NVDA has NO quote in the batch → P&L renders "—" and its value
// falls back to current_price (the B-2 zero-price guard path).
const mkHolding = (
  n: number,
  ticker: string,
  quantity: number,
  averageCost: number,
  currentPrice: number,
) => ({
  holding_id: `h-${n}`,
  portfolio_id: "p1",
  instrument_id: `ins-${n}`,
  entity_id: `ins-${n}`,
  ticker,
  name: `${ticker} Inc`,
  quantity,
  average_cost: averageCost,
  current_price: currentPrice,
});

const mkQuote = (n: number, ticker: string, price: number, change: number) => ({
  instrument_id: `ins-${n}`,
  ticker,
  price,
  change,
  change_pct: price > 0 ? (change / price) * 100 : 0,
  timestamp: "2026-06-10T14:00:00Z",
  volume: null,
});

const holdingsFixture = {
  portfolio_id: "p1",
  holdings: [
    mkHolding(1, "AAPL", 10, 150, 200),
    mkHolding(2, "MSFT", 4, 300, 400),
    mkHolding(3, "NVDA", 1.5, 700, 800), // no live quote → fallback path
    mkHolding(4, "AMZN", 8, 90, 100),
    mkHolding(5, "GOOG", 4, 120, 150),
    mkHolding(6, "TINY", 10, 4, 5), // 6th by value — must be cut
  ],
  total_value: null,
  total_cost: null,
  total_unrealised_pnl: null,
  total_unrealised_pnl_pct: null,
};

const gatewayMocks = vi.hoisted(() => ({
  getPortfolios: vi.fn(),
  getHoldings: vi.fn(),
  getBatchQuotes: vi.fn(),
  getCompanyOverviewsBatch: vi.fn(),
  getMarketSparklines: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => gatewayMocks),
}));

import { MarketClockWidget } from "@/components/dashboard/MarketClockWidget";
import { WatchlistQuickViewWidget } from "@/components/dashboard/WatchlistQuickViewWidget";

// ── Test harness ──────────────────────────────────────────────────────────────

function renderWithClient(ui: ReactNode) {
  // retry:false — failed queries must fail fast in tests, not retry 3×.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function seedHappyPathMocks() {
  gatewayMocks.getPortfolios.mockResolvedValue([
    {
      portfolio_id: "p1",
      name: "Main",
      currency: "USD",
      owner_id: "u1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ]);
  gatewayMocks.getHoldings.mockResolvedValue(holdingsFixture);
  gatewayMocks.getBatchQuotes.mockResolvedValue({
    quotes: {
      "ins-1": mkQuote(1, "AAPL", 200, 2.5), // +$25.00 day P&L
      "ins-2": mkQuote(2, "MSFT", 400, -3), // −$12.00 day P&L
      // ins-3 (NVDA) deliberately absent → "—"
      "ins-4": mkQuote(4, "AMZN", 100, 1),
      "ins-5": mkQuote(5, "GOOG", 150, 0.5),
      "ins-6": mkQuote(6, "TINY", 5, 0.1),
    },
  });
  gatewayMocks.getCompanyOverviewsBatch.mockResolvedValue(
    Object.fromEntries(
      holdingsFixture.holdings.map((h) => [
        h.instrument_id,
        { instrument: { ticker: h.ticker, name: h.name } },
      ]),
    ),
  );
  gatewayMocks.getMarketSparklines.mockResolvedValue({
    "ins-1": [190, 195, 192, 198, 200],
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ══════════════════════════════════════════════════════════════════════════════
// MarketClockWidget
// ══════════════════════════════════════════════════════════════════════════════

describe("MarketClockWidget", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("server render emits the deterministic placeholder (hydration safety)", () => {
    // renderToString = exactly what Next.js does on the server. The output
    // must NOT depend on the wall clock, or hydration would mismatch.
    const html = renderToString(<MarketClockWidget />);
    expect(html).toContain("--:--:-- ET");
    expect(html).toContain("MARKET CLOCK");
    // No session resolved server-side → neutral border, muted dash state.
    expect(html).toContain("border-border/40");
  });

  it("resolves to MARKET OPEN with positive border during the regular session", async () => {
    // Wed 2026-06-10 10:00 ET (14:00 UTC, EDT) — regular session.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-10T14:00:00Z"));

    const { container } = render(<MarketClockWidget />);

    expect(screen.getByText("10:00:00 ET")).toBeInTheDocument();
    expect(screen.getByText("MARKET OPEN")).toBeInTheDocument();
    // 16:00 ET close is 6h away.
    expect(screen.getByText(/closes in 6h 0m/)).toBeInTheDocument();
    // Session-colored border on the widget root (the page cell has none).
    expect(container.firstChild).toHaveClass("border-positive/60");
  });

  it("ticks the clock without unmounting (1s interval is self-contained)", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-10T14:00:00Z"));

    render(<MarketClockWidget />);
    expect(screen.getByText("10:00:00 ET")).toBeInTheDocument();

    // Advance one tick — only this widget re-renders (state is local).
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText("10:00:01 ET")).toBeInTheDocument();
  });

  it("shows pre-market with warning border and opens-in countdown", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-10T12:00:00Z")); // 08:00 ET

    const { container } = render(<MarketClockWidget />);
    expect(screen.getByText("PRE-MARKET")).toBeInTheDocument();
    expect(screen.getByText(/opens in 1h 30m/)).toBeInTheDocument();
    expect(container.firstChild).toHaveClass("border-warning/60");
  });

  it("shows CLOSED with weekend caption and muted border on Saturday", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-13T16:00:00Z")); // Sat 12:00 ET

    const { container } = render(<MarketClockWidget />);
    expect(screen.getByText("CLOSED")).toBeInTheDocument();
    expect(screen.getByText(/weekend/)).toBeInTheDocument();
    expect(screen.getByText(/pre-market opens in/)).toBeInTheDocument();
    expect(container.firstChild).toHaveClass("border-border/40");
  });

  it("shows AFTER HOURS with warning styling at 16:30 ET", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-10T20:30:00Z")); // 16:30 ET

    render(<MarketClockWidget />);
    expect(screen.getByText("AFTER HOURS")).toBeInTheDocument();
    expect(screen.getByText(/after-hours end in 3h 30m/)).toBeInTheDocument();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// WatchlistQuickViewWidget
// ══════════════════════════════════════════════════════════════════════════════

describe("WatchlistQuickViewWidget", () => {
  it("renders the top-5 positions by market value and cuts the 6th", async () => {
    seedHappyPathMocks();
    renderWithClient(<WatchlistQuickViewWidget />);

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    // All of the top 5 present…
    for (const ticker of ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG"]) {
      expect(screen.getByText(ticker)).toBeInTheDocument();
    }
    // …and the smallest position is cut (top-5 only).
    expect(screen.queryByText("TINY")).not.toBeInTheDocument();
  });

  it("orders rows by market value descending", async () => {
    seedHappyPathMocks();
    renderWithClient(<WatchlistQuickViewWidget />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());

    const rows = screen.getAllByRole("button");
    const tickerOrder = rows.map((r) => r.textContent?.slice(0, 4));
    // AAPL(2000) > MSFT(1600) > NVDA(1200) > AMZN(800) > GOOG(600)
    expect(tickerOrder[0]).toContain("AAPL");
    expect(tickerOrder[1]).toContain("MSFT");
    expect(tickerOrder[2]).toContain("NVDA");
  });

  it("renders signed, color-coded day P&L $ (change × quantity)", async () => {
    seedHappyPathMocks();
    renderWithClient(<WatchlistQuickViewWidget />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());

    // AAPL: +2.5 × 10 shares = +$25.00, positive token.
    const gain = screen.getByText("+$25.00");
    expect(gain).toHaveClass("text-positive");
    // MSFT: −3 × 4 = −$12.00, negative token. (U+2212 minus — see widget WHY.)
    const loss = screen.getByText("−$12.00");
    expect(loss).toHaveClass("text-negative");
  });

  it("renders an em-dash P&L when the quote is missing (no silent metric swap)", async () => {
    seedHappyPathMocks();
    renderWithClient(<WatchlistQuickViewWidget />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    // NVDA has no quote in the batch → day P&L is unknowable, NOT 0.
    const nvdaRow = screen.getByText("NVDA").closest("[role='button']")!;
    expect(nvdaRow.textContent).toContain("—");
    // Price still renders via the current_price fallback.
    expect(nvdaRow.textContent).toContain("$800.00");
  });

  it("requests sparklines in ONE batch for the top-5 ids", async () => {
    seedHappyPathMocks();
    renderWithClient(<WatchlistQuickViewWidget />);
    await waitFor(() =>
      expect(gatewayMocks.getMarketSparklines).toHaveBeenCalledTimes(1),
    );
    const [ids, days] = gatewayMocks.getMarketSparklines.mock.calls[0];
    expect([...ids].sort()).toEqual(["ins-1", "ins-2", "ins-3", "ins-4", "ins-5"]);
    expect(days).toBe(5);
    // The sparkline svg carries the row's aria-label.
    await waitFor(() =>
      expect(screen.getByLabelText("AAPL 5-day trend")).toBeInTheDocument(),
    );
  });

  it("navigates ticker-first to /instruments/[ticker] on row click", async () => {
    seedHappyPathMocks();
    const user = userEvent.setup();
    renderWithClient(<WatchlistQuickViewWidget />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());

    await user.click(screen.getByText("AAPL"));
    expect(pushMock).toHaveBeenCalledWith("/instruments/AAPL");
  });

  it("header links to the full portfolio page", async () => {
    seedHappyPathMocks();
    renderWithClient(<WatchlistQuickViewWidget />);
    const link = await screen.findByRole("link", { name: /Portfolio →/ });
    expect(link).toHaveAttribute("href", "/portfolio");
  });

  it("shows the named empty state when the portfolio has no holdings", async () => {
    seedHappyPathMocks();
    gatewayMocks.getHoldings.mockResolvedValue({
      portfolio_id: "p1",
      holdings: [],
      total_value: null,
      total_cost: null,
      total_unrealised_pnl: null,
      total_unrealised_pnl_pct: null,
    });
    renderWithClient(<WatchlistQuickViewWidget />);

    expect(
      await screen.findByText("Track your top positions here"),
    ).toBeInTheDocument();
    const cta = screen.getByRole("link", { name: /Add holdings in Portfolio/ });
    expect(cta).toHaveAttribute("href", "/portfolio");
  });

  it("shows the named empty state when the user has no portfolios at all", async () => {
    seedHappyPathMocks();
    gatewayMocks.getPortfolios.mockResolvedValue([]);
    renderWithClient(<WatchlistQuickViewWidget />);

    expect(
      await screen.findByText("Track your top positions here"),
    ).toBeInTheDocument();
    // No downstream fetches fire without a portfolio id.
    expect(gatewayMocks.getHoldings).not.toHaveBeenCalled();
  });
});
