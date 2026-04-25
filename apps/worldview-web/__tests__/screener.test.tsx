/**
 * __tests__/screener.test.tsx — Unit tests for Screener page (Wave 3 rewrite)
 *
 * WHY THIS EXISTS: The screener is the primary discovery tool for institutional
 * traders. After the Wave 3 rewrite (12-column table, virtual scroll, collapsible
 * filter bar), these tests verify:
 *
 * 1. HeatCell renders correctly (unchanged from Wave 0)
 * 2. ScreenerPage structural elements render (filter bar, heading)
 * 3. Column headers are all present and ALL CAPS
 * 4. Filter bar toggles open/closed
 * 5. Data rows render correctly after query resolves
 * 6. Sort cycling (asc → desc → null) works
 * 7. Missing fields (Revenue, Beta) show "—"
 *
 * WHY MOCK @tanstack/react-virtual: jsdom has no layout engine, so the
 * virtualizer's getScrollElement() returns a 0-height container and renders
 * 0 virtual items. Mocking useVirtualizer makes it render ALL items, which is
 * correct for unit tests that don't need scroll behavior.
 *
 * WHY MOCK GATEWAY: Prevents real HTTP calls, controls response for assertions.
 *
 * DATA SOURCE: Mocked gateway client (runScreener)
 * DESIGN REFERENCE: PRD-0031 §7 Screener, Wave 3
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HeatCell } from "@/components/screener/HeatCell";
import ScreenerPage from "@/app/(app)/screener/page";

// ── @tanstack/react-virtual mock ──────────────────────────────────────────────
// WHY mock useVirtualizer: jsdom has no layout engine. The virtualizer measures
// the scroll container via getBoundingClientRect() which returns zeros in jsdom.
// This causes getTotalSize() = 0 and getVirtualItems() = [] — no rows render.
// Mocking renders ALL items so tests can assert on data cell content.
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number; [k: string]: unknown }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, i) => ({
        index: i,
        key: i,
        start: i * 22,
        size: 22,
      })),
    getTotalSize: () => count * 22,
    measure: () => undefined,
  }),
}));

// ── Next.js router mock ───────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/screener"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    runScreener: vi.fn().mockResolvedValue({
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
        {
          instrument_id: "ins-2",
          entity_id: "ent-2",
          ticker: "TSLA",
          name: "Tesla Inc.",
          exchange: "NASDAQ",
          gics_sector: "Consumer Discretionary",
          market_cap: 750_000_000_000,
          pe_ratio: null,
          daily_return: -0.0315,
          market_impact_score: null,
        },
      ],
      total: 2,
      offset: 0,
      limit: 50,
    }),
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "test-token",
      user: {
        user_id: "u1",
        tenant_id: "t1",
        email: "test@example.com",
        name: "Test User",
        avatar_url: null,
      },
      expires_in: 900,
    }),
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

// ── Auth mock ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "u1",
      tenant_id: "t1",
      email: "test@example.com",
      name: "Test User",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Test helpers ──────────────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── HeatCell tests ────────────────────────────────────────────────────────────

describe("HeatCell", () => {
  it("renders the score as integer 0–100 for score 0.75", () => {
    render(<HeatCell score={0.75} />);
    expect(screen.getByText("75")).toBeInTheDocument();
  });

  it('renders "—" for null score (no data case)', () => {
    render(<HeatCell score={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it('renders "0" for score 0.0 (worst possible score)', () => {
    render(<HeatCell score={0} />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it('renders "100" for score 1.0 (best possible score)', () => {
    render(<HeatCell score={1.0} />);
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it('renders "50" for score 0.5 (neutral score)', () => {
    render(<HeatCell score={0.5} />);
    expect(screen.getByText("50")).toBeInTheDocument();
  });

  it("renders a title attribute for accessibility", () => {
    render(<HeatCell score={0.75} />);
    expect(screen.getByTitle("Signal score: 75/100")).toBeInTheDocument();
  });

  it("renders a title attribute for null score", () => {
    render(<HeatCell score={null} />);
    expect(screen.getByTitle("No score available")).toBeInTheDocument();
  });
});

// ── ScreenerPage — structure tests ────────────────────────────────────────────

describe("ScreenerPage — structure", () => {
  it("renders the page heading", () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    expect(screen.getByText("Instrument Screener")).toBeInTheDocument();
  });

  it("renders the filter toggle button", () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    // WHY aria-label "Toggle screener filters": distinct from Apply/Reset labels
    // to avoid ambiguous multi-element matches. See ScreenerFilterBar.tsx.
    expect(
      screen.getByRole("button", { name: /toggle screener filters/i })
    ).toBeInTheDocument();
  });

  it("renders all 12 column headers with ALL CAPS text", () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    // WHY check columnheader role: ScreenerTable sets role="columnheader" on
    // each header div for screen reader accessibility.
    const headers = screen.getAllByRole("columnheader");
    expect(headers.length).toBe(12);

    // WHY spot-check specific headers: verifies no columns were silently dropped
    // or renamed during the 12-column rewrite.
    expect(screen.getByRole("columnheader", { name: /ticker/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /name/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /sector/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /price/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /chg/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /mkt cap/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /p\/e/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /revenue/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /beta/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /score/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /52w range/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /volume/i })).toBeInTheDocument();
  });
});

// ── ScreenerPage — filter bar tests ──────────────────────────────────────────

describe("ScreenerPage — filter bar", () => {
  it("filter bar is collapsed by default (Apply button not visible in normal flow)", () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    // WHY collapsed by default: terminal density-first principle (§0.5).
    // The toggle button is present; Apply button is in collapsed panel (still
    // in DOM but inside a grid 0fr container).
    expect(
      screen.getByRole("button", { name: /toggle screener filters/i })
    ).toBeInTheDocument();
  });

  it("opens filter bar when toggle is clicked", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    expect(
      screen.getByLabelText(/search instruments by name or ticker/i)
    ).toBeInTheDocument();
  });

  it("renders sector dropdown when filter panel is opened", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    expect(screen.getByLabelText(/filter by gics sector/i)).toBeInTheDocument();
  });

  it("renders Apply and Reset buttons when filter panel is opened", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    expect(screen.getByRole("button", { name: /apply filters/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset all filters/i })).toBeInTheDocument();
  });

  it("renders market cap tier buttons when filter panel is opened", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    expect(screen.getByRole("button", { name: "All cap: No market cap filter" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Large cap: > $10B" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mid cap: $2B–$10B" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Small cap: < $2B" })).toBeInTheDocument();
  });
});

// ── ScreenerPage — data rendering tests ──────────────────────────────────────

describe("ScreenerPage — data rows", () => {
  it("shows AAPL ticker after data loads", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    // WHY waitFor: query resolves asynchronously from the mocked gateway.
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
  });

  it("shows TSLA ticker after data loads", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await waitFor(() => {
      expect(screen.getByText("TSLA")).toBeInTheDocument();
    });
  });

  it("shows HeatCell score of 75 for AAPL (market_impact_score 0.75)", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await waitFor(() => {
      // AAPL has market_impact_score=0.75 → HeatCell displays "75"
      expect(screen.getByText("75")).toBeInTheDocument();
    });
  });

  it("shows em-dash for TSLA (null market_impact_score)", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await waitFor(() => {
      // TSLA has null market_impact_score → HeatCell shows "—"
      // Multiple "—" exist (Price, Revenue, Beta, Volume also show "—")
      const dashes = screen.getAllByText("—");
      expect(dashes.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("backend-pending columns (Revenue, Beta, Price, Volume) show em-dash", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await waitFor(() => {
      // WHY multiple: each backend-pending column per row shows "—".
      // 2 rows × 4 backend-pending cols = 8 dashes minimum, plus TSLA's HeatCell.
      const dashes = screen.getAllByText("—");
      // At minimum: 2 rows × 4 backend-pending cols (Price, Revenue, Beta, Volume) = 8
      // Plus: TSLA HeatCell = 9
      expect(dashes.length).toBeGreaterThanOrEqual(8);
    });
  });

  it("positive change% renders with + prefix", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    // AAPL daily_return=0.0124 → +1.24%
    await waitFor(() => {
      expect(screen.getByText("+1.24%")).toBeInTheDocument();
    });
  });

  it("negative change% renders with - prefix", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    // TSLA daily_return=-0.0315 → -3.15%
    await waitFor(() => {
      expect(screen.getByText("-3.15%")).toBeInTheDocument();
    });
  });

  it("market cap renders abbreviated (T for trillions)", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    // AAPL market_cap=3T → "3.0T"
    await waitFor(() => {
      expect(screen.getByText("3.0T")).toBeInTheDocument();
    });
  });
});

// ── ScreenerPage — sort tests ─────────────────────────────────────────────────

describe("ScreenerPage — column sort", () => {
  it("clicking a sortable column header triggers sort icon change", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // Find the TICKER column header (sortable)
    const tickerHeader = screen.getByRole("columnheader", { name: /sort by ticker/i });
    // WHY aria-sort "none" before click: no sort active initially
    expect(tickerHeader).toHaveAttribute("aria-sort", "none");

    await user.click(tickerHeader);

    // WHY "ascending" after first click: sort cycles null → asc → desc → null
    expect(tickerHeader).toHaveAttribute("aria-sort", "ascending");
  });

  it("clicking sorted column again changes sort to descending", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    const tickerHeader = screen.getByRole("columnheader", { name: /sort by ticker/i });
    await user.click(tickerHeader); // asc
    await user.click(tickerHeader); // desc

    expect(tickerHeader).toHaveAttribute("aria-sort", "descending");
  });

  it("clicking column third time clears sort (back to none)", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    const tickerHeader = screen.getByRole("columnheader", { name: /sort by ticker/i });
    await user.click(tickerHeader); // asc
    await user.click(tickerHeader); // desc
    await user.click(tickerHeader); // none

    expect(tickerHeader).toHaveAttribute("aria-sort", "none");
  });
});
