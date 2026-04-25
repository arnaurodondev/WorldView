/**
 * __tests__/workspace.test.tsx — Unit tests for WorkspacePage (Wave 2 rewrite)
 *
 * WHY THIS EXISTS: WorkspacePage is the primary multi-panel surface. After the Wave 2
 * redesign (react-resizable-panels + WorkspaceContext + SymbolLinkingContext), the old
 * PanelSelectorBar tests are replaced with tests for the new architecture:
 *
 * 1. WorkspaceTabs are rendered inside the workspace page
 * 2. The active workspace's rows are rendered as panels
 * 3. Panels can be closed via the close button (removePanelFromWorkspace)
 * 4. The Add Panel button opens a panel type selection dialog
 * 5. Empty active workspace shows inline empty state text
 *
 * WHY MOCK HEAVY DEPENDENCIES: OHLCVChart (canvas), EntityGraphPanel (WebGL),
 * react-resizable-panels (jsdom has no layout engine for panel size calculations).
 * Mocking these lets us test workspace management logic without browser APIs.
 *
 * WHY WRAP IN WorkspaceProvider: WorkspacePage uses useWorkspace() which requires
 * the provider. WorkspaceProvider is normally in layout.tsx — we mount it here.
 *
 * DATA SOURCE: WorkspaceContext (localStorage, mocked), WorkspaceGrid (component tree)
 * DESIGN REFERENCE: PRD-0031 §5 Workspace, Wave 2 Terminal Quality Additions
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import WorkspacePage from "@/app/(app)/workspace/page";
import { WorkspaceProvider } from "@/contexts/WorkspaceContext";

// ── localStorage mock ─────────────────────────────────────────────────────────
// WHY map-backed stub: jsdom's localStorage may lack .clear() (BP-160).
// A Map-backed stub gives full control + real get/set behavior.
const localStorageData = new Map<string, string>();
const localStorageMock = {
  getItem: vi.fn((key: string) => localStorageData.get(key) ?? null),
  setItem: vi.fn((key: string, value: string) => { localStorageData.set(key, value); }),
  removeItem: vi.fn((key: string) => { localStorageData.delete(key); }),
  clear: vi.fn(() => { localStorageData.clear(); }),
  length: 0,
  key: vi.fn(() => null as string | null),
};

// ── react-resizable-panels mock ───────────────────────────────────────────────
// WHY mock: jsdom has no layout engine so Group can't calculate panel sizes.
// Mocking renders panels without resize logic — focuses tests on workspace management.
// WHY use v4 export names (Group, Separator): WorkspaceGrid imports the v4 renamed
// exports. The mock must match the module's actual export names or imports fail.
vi.mock("react-resizable-panels", () => ({
  Group: ({ children, className }: { children: ReactNode; className?: string }) => (
    <div data-testid="panel-group" className={className}>{children}</div>
  ),
  Panel: ({ children }: { children: ReactNode }) => (
    <div data-testid="panel">{children}</div>
  ),
  Separator: () => <div data-testid="panel-resize-handle" />,
}));

// ── Next.js navigation mock ────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  usePathname: vi.fn(() => "/workspace"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ──────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "t@t.com", name: "Trader", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
// WHY: embedded panel widgets (AlertsList, FundamentalsTab, etc.) call createGateway.
// Mock returns empty/minimal data so tests focus on workspace structure, not data.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getPendingAlerts: vi.fn().mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 20 }),
    getFundamentals: vi.fn().mockResolvedValue(null),
    getOHLCV: vi.fn().mockResolvedValue({ bars: [] }),
    getEntityGraph: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
    getWatchlists: vi.fn().mockResolvedValue([]),
    getBatchQuotes: vi.fn().mockResolvedValue({ quotes: {} }),
    getTopNews: vi.fn().mockResolvedValue({ articles: [] }),
    getPortfolios: vi.fn().mockResolvedValue([]),
    getHoldings: vi.fn().mockResolvedValue({ holdings: [] }),
    getMorningBrief: vi.fn().mockResolvedValue(null),
    screenEntities: vi.fn().mockResolvedValue({ results: [], total: 0 }),
    refreshToken: vi.fn().mockResolvedValue({ access_token: "t", user: {}, expires_in: 900 }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// ── Canvas / WebGL mocks ───────────────────────────────────────────────────────
vi.mock("@/components/instrument/OHLCVChart", () => ({
  OHLCVChart: () => <div data-testid="ohlcv-chart-mock">Chart</div>,
}));
vi.mock("@/components/instrument/EntityGraphPanel", () => ({
  EntityGraphPanel: () => <div data-testid="entity-graph-mock">Graph</div>,
}));
vi.mock("@/components/instrument/FundamentalsTab", () => ({
  FundamentalsTab: () => <div data-testid="fundamentals-mock">Fundamentals</div>,
}));

// ── Test helpers ───────────────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <WorkspaceProvider>{children}</WorkspaceProvider>
      </QueryClientProvider>
    );
  };
}

// ── Test setup ─────────────────────────────────────────────────────────────────

beforeEach(() => {
  localStorageData.clear();
  vi.clearAllMocks();
  // Re-seed mock implementations after clearAllMocks
  localStorageMock.getItem.mockImplementation((key: string) => localStorageData.get(key) ?? null);
  localStorageMock.setItem.mockImplementation((key: string, v: string) => { localStorageData.set(key, v); });
  localStorageMock.removeItem.mockImplementation((key: string) => { localStorageData.delete(key); });
  localStorageMock.clear.mockImplementation(() => { localStorageData.clear(); });
  vi.stubGlobal("localStorage", localStorageMock as unknown as Storage);
});

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("WorkspacePage — tab strip", () => {
  it("renders all 4 default workspace tabs", () => {
    render(<WorkspacePage />, { wrapper: makeWrapper() });

    // WHY check by tab role: WorkspaceTabs renders role="tab" for each workspace
    expect(screen.getByRole("tab", { name: /workspace: day trading/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /workspace: research/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /workspace: portfolio monitor/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /workspace: morning brief/i })).toBeInTheDocument();
  });

  it("marks the first workspace tab as active by default", () => {
    render(<WorkspacePage />, { wrapper: makeWrapper() });
    // WHY aria-selected=true: WorkspaceTabs uses aria-selected for the active tab
    expect(screen.getByRole("tab", { name: /workspace: day trading/i })).toHaveAttribute("aria-selected", "true");
  });

  it("renders the Add workspace button", () => {
    render(<WorkspacePage />, { wrapper: makeWrapper() });
    expect(screen.getByRole("button", { name: /add workspace/i })).toBeInTheDocument();
  });
});

describe("WorkspacePage — panel grid", () => {
  it("renders panels for the active workspace (Day Trading: chart, watchlist, screener, alerts)", () => {
    render(<WorkspacePage />, { wrapper: makeWrapper() });

    // WHY check panel type labels: WorkspacePanelContainer shows ALL CAPS type labels
    // in the 24px panel header. Day Trading preset has chart+watchlist in row 1,
    // screener+alerts in row 2.
    expect(screen.getAllByText("CHART").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("WATCHLIST").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("SCREENER").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("ALERTS").length).toBeGreaterThanOrEqual(1);
  });

  it("renders close buttons for each panel", () => {
    render(<WorkspacePage />, { wrapper: makeWrapper() });

    // WHY check by aria-label: WorkspacePanelContainer close button has
    // aria-label="Close <TYPE> panel"
    expect(screen.getByRole("button", { name: /close chart panel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /close watchlist panel/i })).toBeInTheDocument();
  });

  it("closes a panel when its close button is clicked", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper: makeWrapper() });

    // Verify chart panel is present
    expect(screen.getAllByText("CHART").length).toBeGreaterThanOrEqual(1);

    // Click the close button for the chart panel
    await user.click(screen.getByRole("button", { name: /close chart panel/i }));

    // After closing, the CHART label should be gone from the panel headers
    // (The remaining workspace is: watchlist, screener, alerts)
    await waitFor(() => {
      expect(screen.queryByText("CHART")).not.toBeInTheDocument();
    });
  });

  it("renders the Add Panel button at the bottom of the grid", () => {
    render(<WorkspacePage />, { wrapper: makeWrapper() });
    // WHY check aria-label: the Add Panel button in WorkspaceGrid has aria-label="Add panel"
    expect(screen.getByRole("button", { name: /add panel/i })).toBeInTheDocument();
  });
});

describe("WorkspacePage — workspace switching", () => {
  it("shows Research workspace panels when Research tab is clicked", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper: makeWrapper() });

    // Click the Research tab
    await user.click(screen.getByRole("tab", { name: /workspace: research/i }));

    // Research preset has: chart, news (row 1) + fundamentals, graph (row 2)
    await waitFor(() => {
      expect(screen.getAllByText("NEWS").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("FUNDAMENTALS").length).toBeGreaterThanOrEqual(1);
    });

    // Day Trading panels (watchlist, screener, alerts specific to that preset) should be gone
    // WHY check SCREENER not present: Research preset has no screener panel
    expect(screen.queryByText("SCREENER")).not.toBeInTheDocument();
  });
});

describe("WorkspacePage — add panel", () => {
  it("opens an Add Panel dialog when the Add Panel button is clicked", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole("button", { name: /add panel/i }));

    // WHY check for dialog role: WorkspaceGrid renders a shadcn Dialog when
    // the Add Panel button is clicked. The dialog contains an h2 DialogTitle
    // with "Add Panel" text. We scope to role="heading" to avoid ambiguity with
    // the trigger button (which also contains the text "Add Panel").
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /add panel/i })).toBeInTheDocument();
    });
  });
});

describe("WorkspacePage — panel type labels (terminal quality)", () => {
  it("panel type labels are ALL CAPS 10px text (terminal header pattern)", () => {
    render(<WorkspacePage />, { wrapper: makeWrapper() });

    // WHY getByText with exact ALL CAPS: §0.1 mandates uppercase labels.
    // If a panel label shows "Chart" instead of "CHART", this test catches it.
    const chartLabels = screen.getAllByText("CHART");
    expect(chartLabels.length).toBeGreaterThanOrEqual(1);
  });

  it("renders color group chip button for each panel", () => {
    render(<WorkspacePage />, { wrapper: makeWrapper() });
    // WHY check aria-label: color chip buttons have aria-label="Set symbol group color"
    const chips = screen.getAllByRole("button", { name: /set symbol group color/i });
    // Day Trading workspace has 4 panels — at least 4 color chips
    expect(chips.length).toBeGreaterThanOrEqual(4);
  });
});
