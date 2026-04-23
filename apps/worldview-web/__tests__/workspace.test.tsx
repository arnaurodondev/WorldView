/**
 * __tests__/workspace.test.tsx — Unit tests for the Workspace multi-panel page
 *
 * WHY THIS EXISTS: The Workspace page is a stateful multi-panel UI with 8 panel
 * types. These tests verify:
 * 1. The page title ("Workspace") renders
 * 2. All 8 panel selector buttons render
 * 3. Clicking an inactive panel button adds it to the workspace
 * 4. Clicking an active panel button removes it from the workspace
 * 5. The panel capacity indicator renders and updates
 * 6. The close button (X) on a panel card also removes the panel
 *
 * WHY MOCK GATEWAY: Prevents real S9 HTTP calls in unit tests.
 * Many embedded panel components (OHLCVChart, AlertsList, FundamentalsTab) call
 * createGateway — mocking it prevents network errors from failing these tests.
 *
 * WHY MOCK useAuth: WorkspacePage embeds components that call useAuth(). Without
 * a mock, vitest throws "No AuthContext found" during render.
 *
 * WHY MOCK next/navigation: Next.js App Router hooks (useRouter, usePathname)
 * are unavailable in vitest/jsdom — mock to avoid "invariant" errors.
 *
 * WHY MOCK EntityGraphPanel: EntityGraphPanel uses sigma.js which requires
 * a WebGL canvas. jsdom does not support WebGL — mock to prevent canvas errors.
 *
 * WHY MOCK OHLCVChart: lightweight-charts uses browser canvas APIs unavailable
 * in jsdom — mock to prevent initialisation errors.
 *
 * DATA SOURCE: No real data — mocked gateway, static panel state via userEvent.
 * DESIGN REFERENCE: PRD-0028 §6.5 Workspace, canvas State A.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WorkspacePage from "@/app/(app)/workspace/page";

// WHY stub localStorage in beforeEach: The workspace page reads from localStorage
// on mount (lazy initializer) and writes on every state change (useEffect).
// jsdom shares a single Storage object across tests in the same file. Without
// resetting it, a test that writes panel state could corrupt the initial state
// seen by a later test that expects DEFAULT_PANELS_CONFIG (chart + news + alerts).
//
// WHY vi.stubGlobal (not localStorage.clear()): some jsdom configurations do not
// expose a writable `clear()` on localStorage. Replacing the entire object with a
// fresh in-memory stub avoids the "not a function" error and guarantees isolation.
beforeEach(() => {
  // In-memory localStorage substitute — supports getItem/setItem/removeItem/clear
  const store: Record<string, string> = {};
  const localStorageStub: Storage = {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { Object.keys(store).forEach((k) => { delete store[k]; }); },
    key: (index: number) => Object.keys(store)[index] ?? null,
    get length() { return Object.keys(store).length; },
  };
  vi.stubGlobal("localStorage", localStorageStub);
});

// ── Next.js navigation mock ────────────────────────────────────────────────────
// WHY: WorkspacePage indirectly uses next/navigation via embedded panel components
// (AlertsList uses useRouter). Mock to avoid "invariant" error in vitest/jsdom.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  })),
  usePathname: vi.fn(() => "/workspace"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ──────────────────────────────────────────────────────────────────
// WHY: Embedded panel components (AlertsList, FundamentalsTab, etc.) call useAuth().
// Returning a static token keeps these tests self-contained with no AuthProvider.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "u1",
      tenant_id: "t1",
      email: "trader@example.com",
      name: "Test Trader",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ───────────────────────────────────────────────────────────────
// WHY: AlertsList calls getPendingAlerts, FundamentalsTab calls getFundamentals,
// etc. Mock returns deterministic data so tests don't depend on S9 availability.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getPendingAlerts: vi.fn().mockResolvedValue({
      alerts: [],
      total: 0,
      offset: 0,
      limit: 50,
    }),
    getFundamentals: vi.fn().mockResolvedValue({
      instrument_id: "ins-aapl",
      ticker: "AAPL",
      name: "Apple Inc.",
      market_cap: 3_000_000_000_000,
      pe_ratio: 28.5,
      forward_pe: 27.1,
      price_to_book: 45.2,
      price_to_sales: 8.1,
      ev_to_ebitda: 22.3,
      gross_margin: 0.4523,
      operating_margin: 0.3012,
      net_margin: 0.2512,
      roe: 1.47,
      roa: 0.276,
      revenue_growth_yoy: 0.062,
      earnings_growth_yoy: 0.081,
      dividend_yield: 0.005,
      payout_ratio: 0.15,
      debt_to_equity: 1.73,
      current_ratio: 0.98,
      quick_ratio: 0.92,
      week_52_high: 199.62,
      week_52_low: 124.17,
      daily_return: 0.0124,
      updated_at: new Date().toISOString(),
    }),
    getOHLCV: vi.fn().mockResolvedValue({
      instrument_id: "ins-aapl",
      ticker: "AAPL",
      timeframe: "1D",
      bars: [],
    }),
    getEntityGraph: vi.fn().mockResolvedValue({
      entity_id: "entity-aapl",
      nodes: [],
      edges: [],
    }),
    // WHY mock refreshToken + logout: AuthContext calls these on mount in some
    // test environments where the full AuthProvider is mounted.
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "test-token",
      user: {
        user_id: "u1",
        tenant_id: "t1",
        email: "trader@example.com",
        name: "Test Trader",
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

// ── Canvas API mocks ───────────────────────────────────────────────────────────
// WHY mock OHLCVChart: lightweight-charts calls HTMLCanvasElement.getContext("2d")
// and requestAnimationFrame. jsdom provides a partial canvas implementation but
// the library fails during chart.addCandlestickSeries() in the test environment.
// Mocking the whole component avoids the canvas API dependency entirely.
vi.mock("@/components/instrument/OHLCVChart", () => ({
  OHLCVChart: vi.fn(() => (
    <div data-testid="ohlcv-chart-mock">OHLCVChart (mocked)</div>
  )),
}));

// WHY mock EntityGraphPanel: sigma.js requires WebGL (HTMLCanvasElement.getContext
// ("webgl")). jsdom does not support WebGL — the panel throws during init.
// Mocking lets workspace tests focus on panel add/remove logic, not graph rendering.
vi.mock("@/components/instrument/EntityGraphPanel", () => ({
  EntityGraphPanel: vi.fn(() => (
    <div data-testid="entity-graph-panel-mock">EntityGraphPanel (mocked)</div>
  )),
}));

// ── Test helpers ───────────────────────────────────────────────────────────────

/**
 * makeQueryClient — fresh QueryClient per test with retries disabled.
 *
 * WHY retry: false — avoids a 4-second wait per query failure in tests.
 * Failed queries should surface immediately so assertions don't time out.
 */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

/**
 * wrapper — TanStack Query provider for components under test.
 * WHY per-test new client: prevents query cache from leaking between tests.
 */
function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("WorkspacePage", () => {
  // WHY beforeEach clearAllMocks: ensures mock call counts don't bleed
  // between tests (e.g., a "was called once" assertion in test 3 wouldn't
  // be confused by calls from test 1 and test 2).
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Title rendering ─────────────────────────────────────────────────────────

  it("renders the workspace title", () => {
    // WHY this test: verifies the page mounts without errors and the primary
    // heading is visible — the most basic smoke test for the route.
    render(<WorkspacePage />, { wrapper });
    expect(screen.getByRole("heading", { name: /workspace/i })).toBeInTheDocument();
  });

  // ── Panel selector bar ───────────────────────────────────────────────────────

  it("renders the panel selector toolbar", () => {
    // WHY check toolbar role: the selector bar has role="toolbar" for accessibility.
    // This also verifies the aria-label is present for screen readers.
    render(<WorkspacePage />, { wrapper });
    expect(screen.getByRole("toolbar", { name: /panel selector/i })).toBeInTheDocument();
  });

  it("renders all 8 panel type buttons in the selector bar", () => {
    // WHY 8: matches PANEL_CATALOGUE length — all panel types must be present
    // in the selector bar so users can discover and add any panel type.
    render(<WorkspacePage />, { wrapper });

    const panelTypes = [
      "Chart",
      "Screener",
      "News",
      "Chat",
      "Alerts",
      "Fundamentals",
      "Graph",
      "Portfolio",
    ];

    panelTypes.forEach((label) => {
      // WHY name regex: buttons show icon + label + plus/x icon, so exact match
      // would fail. Regex matches the label substring.
      const buttons = screen.getAllByRole("button", { name: new RegExp(label, "i") });
      // WHY check length >= 1: some labels (e.g., "Alerts") may appear in both
      // the selector bar and the panel header when the panel is active.
      expect(buttons.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── Default panels ───────────────────────────────────────────────────────────

  it("renders the default panels (chart, news, alerts) on load", () => {
    // WHY default panels: the workspace initialises with chart + news + alerts
    // so the user sees a useful layout immediately on first visit.
    render(<WorkspacePage />, { wrapper });

    // WHY check panel card headers (not selector buttons): panel headers appear
    // inside the workspace grid, confirming the panels are actually rendered,
    // not just selected in the toolbar.
    const panelGrid = screen.getByRole("region", { name: /workspace panels/i });
    expect(within(panelGrid).getByText("Chart")).toBeInTheDocument();
    expect(within(panelGrid).getByText("News")).toBeInTheDocument();
    expect(within(panelGrid).getByText("Alerts")).toBeInTheDocument();
  });

  it("renders the panel count as '3/4 panels' on initial load", () => {
    // WHY check count: the "3/4 panels" indicator gives users immediate feedback
    // on their workspace capacity without needing to count panels manually.
    render(<WorkspacePage />, { wrapper });
    // WHY tabular-nums span: the count uses font-mono tabular-nums in the real UI.
    // We look for the text content directly without caring about styling.
    expect(screen.getByText(/3\/4 panels/)).toBeInTheDocument();
  });

  // ── Add panel ────────────────────────────────────────────────────────────────

  it("adds a panel when its inactive selector button is clicked", async () => {
    // WHY userEvent (not fireEvent): userEvent simulates realistic browser events
    // including focus management and pointer events — more faithful to real usage.
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper });

    // Initially "Screener" is not in the default panels
    const panelGrid = screen.getByRole("region", { name: /workspace panels/i });
    expect(within(panelGrid).queryByText("Screener")).not.toBeInTheDocument();

    // Click the "Add Screener panel" button in the selector bar
    // WHY regex match on "Add Screener": aria-label is "Add Screener panel"
    const addButton = screen.getByRole("button", { name: /add screener panel/i });
    await user.click(addButton);

    // After click, the Screener panel card header should appear in the grid
    await waitFor(() => {
      expect(within(panelGrid).getByText("Screener")).toBeInTheDocument();
    });
  });

  it("shows '4/4 panels' after adding a 4th panel", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper });

    // Default state is 3/4 panels. Add "Fundamentals" to reach 4/4.
    const addButton = screen.getByRole("button", { name: /add fundamentals panel/i });
    await user.click(addButton);

    await waitFor(() => {
      expect(screen.getByText(/4\/4 panels/)).toBeInTheDocument();
    });
  });

  it("disables all panel buttons when at max capacity (4 panels)", async () => {
    // WHY test ALL buttons disabled (not just inactive): In the multi-instance model,
    // every selector bar button ADDS a new instance. When MAX_PANELS is reached no new
    // instance can be added regardless of type — so all buttons are disabled.
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper });

    // Add a 4th panel to reach max capacity
    const addFundamentals = screen.getByRole("button", { name: /add fundamentals panel/i });
    await user.click(addFundamentals);

    // WHY wait for panel count: state update is async in React
    await waitFor(() => {
      expect(screen.getByText(/4\/4 panels/)).toBeInTheDocument();
    });

    // At max capacity, ALL panel buttons should be disabled (no slots left).
    // Check an inactive type button ("Screener" was not added).
    const screenerButton = screen.getByRole("button", { name: /add screener panel/i });
    expect(screenerButton).toBeDisabled();

    // Also check an active type button ("Chart" is in default panels) — also disabled.
    const chartButton = screen.getByRole("button", { name: /remove chart panel/i });
    expect(chartButton).toBeDisabled();
  });

  // ── Remove panel via card close button ────────────────────────────────────────
  //
  // WHY via card X button (not selector bar): The workspace now uses a multi-instance
  // model. Selector bar buttons always ADD a new instance — they no longer toggle/remove.
  // Removal is done exclusively via the close (X) button on each panel card.

  it("removes a panel when the close (X) button in the panel card is clicked", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper });

    // "Alerts" is in the default panels — it should be in the grid
    const panelGrid = screen.getByRole("region", { name: /workspace panels/i });
    expect(within(panelGrid).getByText("Alerts")).toBeInTheDocument();

    // Remove via the card close button (aria-label "Close Alerts panel")
    const closeButton = within(panelGrid).getByRole("button", { name: /close alerts panel/i });
    await user.click(closeButton);

    // After removal, the Alerts panel card should no longer be in the grid
    await waitFor(() => {
      // WHY queryByText within panelGrid: "Alerts" also appears in the selector bar button.
      // We need to confirm it's gone from the panel grid specifically.
      expect(within(panelGrid).queryByText("Alerts")).not.toBeInTheDocument();
    });
  });

  it("decrements panel count when a panel is removed via card close button", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper });

    // Starting count is 3/4
    expect(screen.getByText(/3\/4 panels/)).toBeInTheDocument();

    // Remove the "News" panel via its card close button
    const panelGrid = screen.getByRole("region", { name: /workspace panels/i });
    const closeButton = within(panelGrid).getByRole("button", { name: /close news panel/i });
    await user.click(closeButton);

    // Count should drop to 2/4
    await waitFor(() => {
      expect(screen.getByText(/2\/4 panels/)).toBeInTheDocument();
    });
  });

  // ── Remove panel via card close button ────────────────────────────────────────

  it("removes a panel when the close (X) button inside the panel card is clicked", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper });

    const panelGrid = screen.getByRole("region", { name: /workspace panels/i });

    // The Chart panel is in the default layout — find its close button
    // WHY aria-label: each panel card's close button has aria-label "Close X panel"
    const closeChartButton = within(panelGrid).getByRole("button", {
      name: /close chart panel/i,
    });
    await user.click(closeChartButton);

    // Chart panel should be removed from the grid
    await waitFor(() => {
      expect(within(panelGrid).queryByText("Chart")).not.toBeInTheDocument();
    });
  });

  // ── Empty state ───────────────────────────────────────────────────────────────

  it("shows empty state message when all panels are removed via card close buttons", async () => {
    // WHY use card close buttons (not selector bar): The multi-instance model means
    // selector bar buttons ADD instances. Removal is done via the close (X) button
    // on individual panel cards.
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper });

    const panelGrid = screen.getByRole("region", { name: /workspace panels/i });

    // Remove all 3 default panels via their card close buttons
    const closeChart = within(panelGrid).getByRole("button", { name: /close chart panel/i });
    const closeNews = within(panelGrid).getByRole("button", { name: /close news panel/i });
    const closeAlerts = within(panelGrid).getByRole("button", { name: /close alerts panel/i });

    await user.click(closeChart);
    await user.click(closeNews);
    await user.click(closeAlerts);

    // WHY wait: three sequential state updates need to flush before the empty state renders
    await waitFor(() => {
      expect(screen.getByText(/no panels open/i)).toBeInTheDocument();
    });

    // The workspace grid should no longer be present after all panels are removed
    // (the empty state component replaces it)
    expect(panelGrid).not.toBeInTheDocument();
  });

  // ── Capacity hint ─────────────────────────────────────────────────────────────

  it("shows max-capacity hint when 4 panels are open", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper });

    // Add 4th panel to trigger the hint
    const addFundamentals = screen.getByRole("button", { name: /add fundamentals panel/i });
    await user.click(addFundamentals);

    await waitFor(() => {
      expect(screen.getByText(/maximum 4 panels reached/i)).toBeInTheDocument();
    });
  });

  it("hides max-capacity hint when a panel is removed below max via card close button", async () => {
    // WHY use card close button for removal: selector bar buttons ADD instances in
    // the multi-instance model. Removal is done via the card close (X) button.
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper });

    // Add a 4th panel to reach max capacity
    await user.click(screen.getByRole("button", { name: /add fundamentals panel/i }));
    await waitFor(() => {
      expect(screen.getByText(/maximum 4 panels reached/i)).toBeInTheDocument();
    });

    // Remove one panel via its card close button to go back below max
    const panelGrid = screen.getByRole("region", { name: /workspace panels/i });
    await user.click(within(panelGrid).getByRole("button", { name: /close chart panel/i }));
    await waitFor(() => {
      expect(screen.queryByText(/maximum 4 panels reached/i)).not.toBeInTheDocument();
    });
  });

  // ── Panel aria-label (accessibility) ─────────────────────────────────────────

  it("panel card close buttons have accessible aria-labels", () => {
    // WHY: Screen reader users need to know which panel the close button dismisses.
    // Without aria-label, all close buttons would announce as "X" with no context.
    render(<WorkspacePage />, { wrapper });

    const panelGrid = screen.getByRole("region", { name: /workspace panels/i });

    // Check each default panel has a close button with its name in the label
    expect(
      within(panelGrid).getByRole("button", { name: /close chart panel/i }),
    ).toBeInTheDocument();
    expect(
      within(panelGrid).getByRole("button", { name: /close news panel/i }),
    ).toBeInTheDocument();
    expect(
      within(panelGrid).getByRole("button", { name: /close alerts panel/i }),
    ).toBeInTheDocument();
  });

  // ── aria-pressed state ────────────────────────────────────────────────────────

  it("sets aria-pressed=true on selector buttons for active panels", () => {
    render(<WorkspacePage />, { wrapper });

    // Active panels (chart, news, alerts) should have aria-pressed="true"
    const removeChartBtn = screen.getByRole("button", { name: /remove chart panel/i });
    expect(removeChartBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("sets aria-pressed=false on selector buttons for inactive panels", () => {
    render(<WorkspacePage />, { wrapper });

    // "Screener" is not in the default panels — should have aria-pressed="false"
    const addScreenerBtn = screen.getByRole("button", { name: /add screener panel/i });
    expect(addScreenerBtn).toHaveAttribute("aria-pressed", "false");
  });
});
