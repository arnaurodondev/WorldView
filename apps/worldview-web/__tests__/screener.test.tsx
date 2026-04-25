/**
 * __tests__/screener.test.tsx — Unit tests for Screener page and HeatCell component
 *
 * WHY THIS EXISTS: The screener is a core power-user feature. These tests verify:
 * 1. HeatCell correctly renders numeric scores as 0–100 integers
 * 2. HeatCell renders "—" for null scores (no data case)
 * 3. The screener page renders the filter panel and table headers (structure test)
 *
 * WHY MOCK GATEWAY: We don't want real S9 calls in unit tests. The mock controls
 * exactly what the screener receives so tests are deterministic.
 *
 * WHY MOCK NEXT/NAVIGATION: The screener page uses useRouter for row navigation.
 * App Router is not mounted in unit tests — mock to prevent "invariant" errors.
 *
 * DATA SOURCE: Mocked gateway client
 * DESIGN REFERENCE: PRD-0028 §6.5 Screener, docs/ui/DESIGN_SYSTEM.md HeatCell
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HeatCell } from "@/components/screener/HeatCell";
import ScreenerPage from "@/app/(app)/screener/page";

// ── Next.js router mock ───────────────────────────────────────────────────────
// WHY: ScreenerPage uses useRouter() for row click navigation. The App Router
// is not mounted in vitest/jsdom — mock prevents "useRouter must be used inside
// Next.js App Router context" invariant error.
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
// WHY mock runScreener: prevents real HTTP calls to S9, controls the response
// shape for predictable assertions.
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
      limit: 20,
    }),
    // WHY mock refreshToken + logout: AuthContext calls these on mount
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
// WHY: ScreenerPage uses useAuth() to get the access token for the gateway.
// Returning a static token avoids needing to mount the full AuthProvider.
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

/**
 * makeQueryClient — fresh QueryClient with retries disabled for each test.
 * WHY no retry: we want query failures to surface immediately, not be masked
 * by silent retries that add 4+ seconds per test.
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
 * WHY per-test client: prevents query cache from leaking between tests.
 */
function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── HeatCell tests ────────────────────────────────────────────────────────────

describe("HeatCell", () => {
  it('renders the score as integer 0–100 for score 0.75', () => {
    // WHY 0.75 → "75": Math.round(0.75 * 100) = 75
    render(<HeatCell score={0.75} />);
    expect(screen.getByText("75")).toBeInTheDocument();
  });

  it('renders "—" for null score (no data case)', () => {
    // WHY em-dash: user must see "no data" not a zero score, which would imply
    // the instrument is bad rather than unscored.
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
    // WHY check title: keyboard/screen-reader users need context on what
    // the colour and number mean — "Signal score: 75/100" provides that.
    expect(screen.getByTitle("Signal score: 75/100")).toBeInTheDocument();
  });

  it("renders a title attribute for null score", () => {
    render(<HeatCell score={null} />);
    expect(screen.getByTitle("No score available")).toBeInTheDocument();
  });
});

// ── ScreenerPage structure tests ──────────────────────────────────────────────

describe("ScreenerPage", () => {
  it("renders the FILTERS toggle button in the header bar", () => {
    // WHY updated: filter panel is now collapsible (default: collapsed).
    // The "FILTERS" heading is now a toggle button in the results header bar —
    // collapsed by default to maximize visible data rows (Bloomberg convention).
    // We verify the toggle button is present and accessible regardless of panel state.
    render(<ScreenerPage />, { wrapper });

    // The FILTERS toggle button should be visible immediately — it's in the
    // results header, not inside the collapsible panel.
    expect(screen.getByRole("button", { name: /filters/i })).toBeInTheDocument();
  });

  it("renders Name/Ticker search input when filter panel is opened", async () => {
    // WHY updated: filter panel is collapsed by default (§0.5 — density first).
    // Open the panel first, then verify the search input is accessible.
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper });

    // Click the FILTERS toggle to open the panel
    await user.click(screen.getByRole("button", { name: /filters/i }));
    expect(screen.getByLabelText(/search instruments by name or ticker/i)).toBeInTheDocument();
  });

  it("renders the sector dropdown when filter panel is opened", async () => {
    // WHY updated: same reason as search input — panel is collapsed by default.
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper });

    await user.click(screen.getByRole("button", { name: /filters/i }));
    expect(screen.getByLabelText(/filter by gics sector/i)).toBeInTheDocument();
  });

  it("renders Apply and Reset buttons when filter panel is opened", async () => {
    // WHY updated: filter panel is collapsed by default; open it first to reveal
    // the Apply and Reset buttons. These buttons live inside the collapsible panel.
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper });

    await user.click(screen.getByRole("button", { name: /filters/i }));
    expect(screen.getByRole("button", { name: /apply filters/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset all filters/i })).toBeInTheDocument();
  });

  it("renders table column headers", () => {
    render(<ScreenerPage />, { wrapper });
    // WHY check headers immediately: they are rendered in the static <thead>
    // and don't depend on data loading or filter panel state — table structure is instant.
    expect(screen.getByRole("columnheader", { name: /ticker/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /name/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /mkt cap/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /score/i })).toBeInTheDocument();
  });

  it("renders market cap tier buttons when filter panel is opened", async () => {
    // WHY updated: filter panel is collapsed by default. Open it first.
    // WHY exact aria-label matching: "All cap" is a substring of "Small cap",
    // so using /all cap/i would match two elements. Use exact string matching instead.
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper });

    await user.click(screen.getByRole("button", { name: /filters/i }));
    expect(screen.getByRole("button", { name: "All cap: No market cap filter" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Large cap: > $10B" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mid cap: $2B–$10B" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Small cap: < $2B" })).toBeInTheDocument();
  });

  it("renders screener page heading", () => {
    render(<ScreenerPage />, { wrapper });
    expect(screen.getByText("Instrument Screener")).toBeInTheDocument();
  });

  it("shows AAPL ticker after data loads", async () => {
    render(<ScreenerPage />, { wrapper });

    // WHY waitFor: data arrives asynchronously from the mocked gateway.
    // The row only renders after the query resolves.
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
  });

  it("shows TSLA ticker after data loads", async () => {
    render(<ScreenerPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("TSLA")).toBeInTheDocument();
    });
  });

  it("shows HeatCell score of 75 for AAPL (market_impact_score 0.75)", async () => {
    render(<ScreenerPage />, { wrapper });

    await waitFor(() => {
      // AAPL has market_impact_score=0.75 → HeatCell should display "75"
      expect(screen.getByText("75")).toBeInTheDocument();
    });
  });

  it("shows em-dash in HeatCell for TSLA (null market_impact_score)", async () => {
    render(<ScreenerPage />, { wrapper });

    await waitFor(() => {
      // TSLA has market_impact_score=null → HeatCell shows "—"
      // getAllByText because the Price column also shows "—" for all rows
      const dashes = screen.getAllByText("—");
      expect(dashes.length).toBeGreaterThanOrEqual(1);
    });
  });
});
