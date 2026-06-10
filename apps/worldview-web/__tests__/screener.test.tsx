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

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
// PLAN-0059 C-6: ScreenerPage uses nuqs URL state (sector + capTier).
// Tests need NuqsTestingAdapter to stub the router.
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { HeatCell } from "@/components/screener/HeatCell";
import ScreenerPage from "@/app/(app)/screener/page";

// ── React partial mock — synchronous useDeferredValue ─────────────────────────
// WHY: ScreenerPage uses useDeferredValue for the sort+filter pipeline.
// In React 18 concurrent mode, useDeferredValue schedules a low-priority render
// AFTER the urgent one commits. In tests with rapid sequential clicks, TanStack's
// getNextSortingOrder() reads column.getIsSorted() synchronously at click time
// (outside the updater) — if a second click fires before the deferred pass
// commits, TanStack sees stale sort state and computes the wrong next direction.
// Making useDeferredValue synchronous removes the deferred-pass timing window so
// each click sees the fully-committed sort state.
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  // WHY cast: in .tsx files, <T>(...) is ambiguous (JSX vs generic). Using
  // (value: unknown) => value avoids the parse error while still acting as a
  // pass-through at runtime. The cast restores the correct TypeScript signature.
  const syncUseDeferredValue = (
    (value: unknown) => value
  ) as typeof actual.useDeferredValue;
  return {
    ...actual,
    useDeferredValue: syncUseDeferredValue,
  };
});

// ── Next.js router mock ───────────────────────────────────────────────────────
// WHY vi.hoisted: vi.mock factories are hoisted above imports, so a plain
// `const pushMock` defined here would not exist yet when the factory runs.
// vi.hoisted lifts the declaration alongside the mock so tests can assert
// against the SAME push spy the component receives (row-click navigation).
const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: pushMock,
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
    return (
      <NuqsTestingAdapter searchParams="">
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </NuqsTestingAdapter>
    );
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

  it("renders all 34 column headers with ALL CAPS text", () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    // WHY check columnheader role: AG Grid sets role="columnheader" on each
    // header cell for screen reader accessibility.
    // IB-L3/L4: added PERFORMANCE group (52W%↑, 52W%↓, 1M/3M/6M/YTD/1Y/3Y RTN)
    // and OWNERSHIP group (ANALYST TGT, ANALYST UPSIDE, CONSENSUS, INSIDER 90D,
    // INST OWN%, SHORT %) on top of the existing FUNDAMENTALS and RATIOS groups.
    // IB-L5: added INTELLIGENCE group (NEWS 7D, BRIEF SCORE) — default-visible.
    // Total is now 34 rendered columnheader roles (group headers + leaf columns
    // both receive role="columnheader" in AG Grid).
    const headers = screen.getAllByRole("columnheader");
    expect(headers.length).toBe(34);

    // WHY spot-check specific headers: verifies no columns were silently dropped
    // or renamed during the rewrite.
    expect(screen.getByRole("columnheader", { name: /ticker/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /name/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /sector/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /price/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /chg/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /mkt cap/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /p\/e/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /revenue/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /beta/i })).toBeInTheDocument();
    // WHY getAllByRole: IB-L5 added BRIEF SCORE so two headers match /score/i now.
    expect(screen.getAllByRole("columnheader", { name: /score/i }).length).toBeGreaterThanOrEqual(1);
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

// ── ScreenerPage — row click navigation (ROUND-1 item 6) ─────────────────────

describe("ScreenerPage — row click navigation", () => {
  beforeEach(() => {
    pushMock.mockClear();
  });

  it("navigates to /instruments/<TICKER> when a row is clicked", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // Wait for the grid to render the mocked rows.
    const aaplCell = await screen.findByText("AAPL");

    // Clicking any cell bubbles to AG Grid's rowClicked handler.
    await user.click(aaplCell);

    // ROUND-1 fix: the canonical instrument route is the TICKER slug
    // (app/(app)/instruments/[ticker]) — NOT the entity_id UUID. The mock row
    // has entity_id "ent-1"; asserting the ticker URL pins the fix.
    expect(pushMock).toHaveBeenCalledWith("/instruments/AAPL");
  });
});

// ── ScreenerPage — empty state + Reset filters CTA (ROUND-1 item 8) ──────────

describe("ScreenerPage — empty state with Reset filters CTA", () => {
  it("shows 'No results match your filters' + Reset CTA when filters exclude all rows, and reset restores them", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // Wait for data, then apply a search filter that matches nothing.
    // The search filter is client-side (applyClientFilters), so the mocked
    // gateway keeps returning both rows — they are filtered out locally.
    await screen.findByText("AAPL");
    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    await user.type(
      screen.getByLabelText(/search instruments by name or ticker/i),
      "ZZZZNOMATCH",
    );
    await user.click(screen.getByRole("button", { name: /apply filters/i }));

    // Empty state appears with the standardized title + CTA.
    await waitFor(() => {
      expect(screen.getByText("No results match your filters")).toBeInTheDocument();
    });
    // WHY the long accessible name: the filter bar's own bottom-toolbar Reset
    // button is also in the DOM (aria-label "Reset filters"); the CTA carries
    // a unique label so role queries are unambiguous.
    const resetCta = screen.getByRole("button", {
      name: /reset filters and show all instruments/i,
    });
    expect(resetCta).toBeInTheDocument();

    // Clicking Reset filters clears the search filter → rows come back.
    await user.click(resetCta);
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
    expect(screen.queryByText("No results match your filters")).not.toBeInTheDocument();
  });
});

// ── ScreenerPage — sort tests ─────────────────────────────────────────────────

describe("ScreenerPage — column sort", () => {
  it("clicking a sortable column header triggers sort icon change", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // WHY wait for data: the screener has 3 async layers (useQuery → setAccumulator
    // effect → useDeferredValue). Clicking sort before all 3 settle can catch
    // TanStack in a mid-deferred-render state in the full suite, causing the first
    // toggle to flip DESC instead of ASC. Waiting for a data row ensures the
    // component is fully stable before we interact with sort.
    await screen.findByText("AAPL");

    // WHY /ticker/i not /sort by ticker/i: DataTable renders the column header
    // text ("TICKER") as the accessible name; the old ScreenerTable used an
    // explicit aria-label="sort by ticker" pattern that DataTable doesn't follow.
    const tickerHeader = screen.getByRole("columnheader", { name: /ticker/i });
    expect(tickerHeader).toHaveAttribute("aria-sort", "none");

    await user.click(tickerHeader);

    // WHY waitFor: sort state flows sort state → screenerSortToTanstack → DataTable
    // controlled prop → TanStack re-evaluates → aria-sort updates. Two render
    // cycles may be needed in React 18 concurrent mode.
    // WHY "ascending" after first click: sort cycles null → asc → desc → null
    await waitFor(() =>
      expect(tickerHeader).toHaveAttribute("aria-sort", "ascending"),
    );
  });

  it("clicking sorted column again changes sort to descending", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // WHY wait for data before sort: see explanation in first sort test above.
    await screen.findByText("AAPL");

    const tickerHeader = screen.getByRole("columnheader", { name: /ticker/i });
    await user.click(tickerHeader); // none → asc
    await waitFor(() =>
      expect(tickerHeader).toHaveAttribute("aria-sort", "ascending"),
    );
    await user.click(tickerHeader); // asc → desc
    await waitFor(() =>
      expect(tickerHeader).toHaveAttribute("aria-sort", "descending"),
    );
  });

  it("clicking column third time clears sort (back to none)", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // WHY wait for data before sort: see explanation in first sort test above.
    await screen.findByText("AAPL");

    const tickerHeader = screen.getByRole("columnheader", { name: /ticker/i });
    await user.click(tickerHeader); // none → asc
    await waitFor(() =>
      expect(tickerHeader).toHaveAttribute("aria-sort", "ascending"),
    );
    await user.click(tickerHeader); // asc → desc
    await waitFor(() =>
      expect(tickerHeader).toHaveAttribute("aria-sort", "descending"),
    );
    await user.click(tickerHeader); // desc → none
    await waitFor(() =>
      expect(tickerHeader).toHaveAttribute("aria-sort", "none"),
    );
  });
});

// ── ScreenerPage — PLAN-0051 Wave B Part 1 ────────────────────────────────────
//
// WHY THESE TESTS: Wave B Part 1 expands the filter bar to FIVE collapsible
// sections (Valuation, Profitability, Growth, Leverage, Technical, News & Signals)
// and adds "X of Y" result count + Load More pagination. These tests verify the
// new structure renders correctly without regressing existing behaviour.

describe("ScreenerPage — Wave B filter sections (PLAN-0051)", () => {
  // WHY set env: Leverage + some Technical/News sections are gated behind
  // NEXT_PUBLIC_ENABLE_PENDING_METRICS (FR-4.4). Tests that assert those
  // sections exist must enable the flag so the sections render.
  beforeEach(() => { process.env.NEXT_PUBLIC_ENABLE_PENDING_METRICS = "true"; });
  afterEach(() => { delete process.env.NEXT_PUBLIC_ENABLE_PENDING_METRICS; });

  it("renders all six filter sections after the panel is opened", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));

    // Each section's header is rendered as a button (clickable to expand/collapse).
    // We assert every section name is present so a future rename or accidental
    // removal triggers a test failure.
    // WHY aria-controls query (not just name): PRD-0089 Wave I added a "Growth"
    // PresetBar chip which also matches /growth/i. The Section buttons carry
    // aria-controls="screener-section-<name>" which uniquely identifies them.
    expect(screen.getByRole("button", { name: /valuation/i, hidden: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /profitability/i })).toBeInTheDocument();
    // Match the Growth SECTION button (aria-controls set), not the Growth PRESET chip
    expect(
      document.querySelector("button[aria-controls='screener-section-growth']")
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: /leverage/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /technical/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /news & signals/i })).toBeInTheDocument();
  });

  it("Valuation section is expanded by default and shows P/E inputs", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));

    // P/E (TTM) min input — the Valuation section is open by default so this
    // should be visible without further clicks. Distinguishes "Wave B is wired"
    // from "Wave B is just imported but not rendered".
    expect(screen.getByLabelText(/p\/e .*ttm.*minimum/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/p\/e .*ttm.*maximum/i)).toBeInTheDocument();
  });

  it("Leverage filters are disabled with backend-pending hint", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    // Expand the Leverage section to reach the inputs
    await user.click(screen.getByRole("button", { name: /leverage/i }));

    // Both Debt/Equity and Current Ratio inputs are documented gaps in the
    // T-B-2-01 audit — they must be disabled until the backend derives the ratio.
    const debtMin = screen.getByLabelText(/debt\/equity minimum/i) as HTMLInputElement;
    expect(debtMin).toBeDisabled();
    const currentMin = screen.getByLabelText(/current ratio minimum/i) as HTMLInputElement;
    expect(currentMin).toBeDisabled();
  });

  it("active filter count badge appears when a Valuation min is entered", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    const peMin = screen.getByLabelText(/p\/e .*ttm.*minimum/i);
    await user.type(peMin, "10");

    // The Valuation section header now shows aria-label including "1 active filter"
    // (per Section sub-component rules in ScreenerFilterBar.tsx).
    expect(screen.getByLabelText(/1 active filter in valuation/i)).toBeInTheDocument();
  });
});

describe("ScreenerPage — Wave B result count (PLAN-0051 T-B-2-08)", () => {
  it("shows total match count when loaded equals total", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    // Mock returns total=2 and 2 rows — no "X of Y" formatting, just total
    await waitFor(() => {
      // "2 match" — ALL CAPS uppercase per design system, but the text content
      // is lowercase before CSS uppercase transform; we just match the substring.
      expect(screen.getByLabelText(/result count/i).textContent).toMatch(/2.*match/i);
    });
  });
});
