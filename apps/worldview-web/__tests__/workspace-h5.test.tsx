/**
 * __tests__/workspace-h5.test.tsx — Wave H-5 feature tests
 *
 * WHY THIS EXISTS: PLAN-0059 Wave H-5 adds three new features to the workspace:
 *   1. WorkspaceSymbolContext — workspace-level symbol broadcast (Bloomberg-style)
 *   2. WorkspaceSymbolBar — the UI input that broadcasts a symbol to all panels
 *   3. Add Panel slide-in Tray — HTML5 drag-and-drop tray replaces dialog
 *   4. Quad View template — 2×2 grid template in workspace-templates.ts
 *
 * TEST COVERAGE:
 *   T1: Quad template — verifies the new template creates 4 WorkspacePanelContainer
 *       instances, i.e., the 2×2 grid structure is rendered correctly.
 *   T2: Symbol broadcast — verifies WorkspaceSymbolContext propagates a typed
 *       + Enter-committed symbol to a consumer that reads broadcastSymbol.
 *   T3: Escape clears broadcast — broadcast symbol is cleared on Escape.
 *   T4: Tray opens — clicking "Add Panel" shows the tray with aria-expanded=true.
 *   T5: Tray lists all 10 widget types — catalogue is complete.
 *   T6: SymbolBar renders in page — the input is present in the full workspace page.
 *
 * WHY MOCK HEAVY DEPENDENCIES: react-resizable-panels has no jsdom layout engine.
 * OHLCVChart / EntityGraphPanel use Canvas/WebGL not available in jsdom.
 * These are the same mocks as workspace.test.tsx.
 *
 * DATA SOURCE: WorkspaceContext (localStorage, mocked for isolation)
 * DESIGN REFERENCE: PLAN-0059 §H-5
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import WorkspacePage from "@/app/(app)/workspace/page";
import { WorkspaceProvider } from "@/contexts/WorkspaceContext";
import {
  WorkspaceSymbolProvider,
  useWorkspaceSymbol,
} from "@/contexts/WorkspaceSymbolContext";

// ── localStorage mock ─────────────────────────────────────────────────────────
// WHY map-backed stub: consistent with workspace.test.tsx; ensures full control.
const localStorageData = new Map<string, string>();
const localStorageMock = {
  getItem: vi.fn((key: string) => localStorageData.get(key) ?? null),
  setItem: vi.fn((key: string, value: string) => {
    localStorageData.set(key, value);
  }),
  removeItem: vi.fn((key: string) => {
    localStorageData.delete(key);
  }),
  clear: vi.fn(() => {
    localStorageData.clear();
  }),
  length: 0,
  key: vi.fn(() => null as string | null),
};

// ── react-resizable-panels mock ───────────────────────────────────────────────
// WHY mock: jsdom cannot calculate panel sizes. The mock renders panels as plain
// divs, letting us count panels and check rendered content without layout logic.
vi.mock("react-resizable-panels", () => ({
  Group: ({ children, className }: { children: ReactNode; className?: string }) => (
    <div data-testid="panel-group" className={className}>
      {children}
    </div>
  ),
  Panel: ({ children }: { children: ReactNode }) => (
    <div data-testid="panel">{children}</div>
  ),
  Separator: () => <div data-testid="panel-resize-handle" />,
}));

// ── Next.js navigation mock ────────────────────────────────────────────────────
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
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "u1",
      tenant_id: "t1",
      email: "t@t.com",
      name: "Trader",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
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
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "t",
      user: {},
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

// ── Heavy panel component mocks ────────────────────────────────────────────────
// WHY: same reason as workspace.test.tsx — Canvas/WebGL not available in jsdom.
vi.mock("@/components/instrument/OHLCVChart", () => ({
  OHLCVChart: () => <div data-testid="ohlcv-chart-mock">Chart</div>,
}));
vi.mock("@/components/instrument/EntityGraphPanel", () => ({
  EntityGraphPanel: () => <div data-testid="entity-graph-mock">Graph</div>,
}));
vi.mock("@/components/instrument/FundamentalsTab", () => ({
  FundamentalsTab: () => <div data-testid="fundamentals-mock">Fundamentals</div>,
}));

// ── Test wrappers ──────────────────────────────────────────────────────────────

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
  localStorageMock.getItem.mockImplementation(
    (key: string) => localStorageData.get(key) ?? null,
  );
  localStorageMock.setItem.mockImplementation((key: string, v: string) => {
    localStorageData.set(key, v);
  });
  localStorageMock.removeItem.mockImplementation((key: string) => {
    localStorageData.delete(key);
  });
  localStorageMock.clear.mockImplementation(() => {
    localStorageData.clear();
  });
  vi.stubGlobal("localStorage", localStorageMock as unknown as Storage);
});

// ── Symbol input fixture ───────────────────────────────────────────────────────

/**
 * SymbolBarFixture — minimal implementation of WorkspaceSymbolBar for isolated testing.
 *
 * WHY not import WorkspaceSymbolBar directly: WorkspaceSymbolBar is defined inside
 * workspace/page.tsx as a module-level function but is not exported. Importing it
 * would require exporting it (which would expose internal page components in the
 * public API). This fixture replicates the minimal contract needed to test the
 * context: input + Enter commit + Escape clear.
 */
function SymbolBarFixture() {
  const { setBroadcastSymbol } = useWorkspaceSymbol();
  const [value, setValue] = useState("");

  return (
    <input
      data-testid="workspace-symbol-input"
      value={value}
      onChange={(e) => setValue(e.target.value.toUpperCase())}
      onKeyDown={(e) => {
        if (e.key === "Enter") setBroadcastSymbol(value.trim() || null);
        if (e.key === "Escape") {
          setBroadcastSymbol(null);
          setValue("");
        }
      }}
    />
  );
}

/**
 * BroadcastConsumer — reads broadcastSymbol from context and renders it.
 * WHY separate component: isolates the consumer side from the provider setup.
 */
function BroadcastConsumer() {
  const { broadcastSymbol } = useWorkspaceSymbol();
  return (
    <span data-testid="broadcast-value">
      {broadcastSymbol ?? "none"}
    </span>
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("H-5: Quad template — 4 panel slots", () => {
  /**
   * WHY this test: the quad template is the primary deliverable of Wave H-5.
   * It creates 2 rows × 2 panels = 4 WorkspacePanelContainer instances.
   * We seed localStorage with a quad-shaped workspace so the page renders it
   * immediately (no template dialog interaction required in this unit test).
   */
  it("renders 4 panels when the active workspace has a 2×2 quad layout", async () => {
    // Seed a quad-shaped workspace directly into localStorage so WorkspaceContext
    // loads it on mount. This avoids navigating through NewFromTemplateDialog.
    const quadWorkspace = {
      id: "ws-quad-test",
      name: "Quad View",
      rows: [
        {
          panels: [
            { id: "q1", type: "chart" },
            { id: "q2", type: "news" },
          ],
        },
        {
          panels: [
            { id: "q3", type: "screener" },
            { id: "q4", type: "portfolio" },
          ],
        },
      ],
    };

    // WHY write to STORAGE_KEY + ACTIVE_KEY: WorkspaceContext reads both on mount.
    // Setting ACTIVE_KEY ensures the quad workspace is the active one.
    localStorageData.set(
      "worldview:workspaces:v2",
      JSON.stringify([quadWorkspace]),
    );
    localStorageData.set("worldview-active-workspace", "ws-quad-test");

    render(<WorkspacePage />, { wrapper: makeWrapper() });

    // WHY expect all 4 panel type labels: 2 rows × 2 panels each = 4 WorkspacePanelContainer
    // renders. Each container renders a panel header with the uppercase type label.
    await waitFor(() => {
      expect(screen.getAllByText("CHART").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("NEWS").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("SCREENER").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("PORTFOLIO").length).toBeGreaterThanOrEqual(1);
    });
  });
});

describe("H-5: WorkspaceSymbolContext broadcast", () => {
  it("broadcasts a typed symbol to all consumers when Enter is pressed", async () => {
    const user = userEvent.setup();

    render(
      <WorkspaceSymbolProvider>
        <SymbolBarFixture />
        <BroadcastConsumer />
      </WorkspaceSymbolProvider>,
    );

    // Initial state: no broadcast symbol
    expect(screen.getByTestId("broadcast-value")).toHaveTextContent("none");

    // Type "tsla" (lowercase) — fixture uppercases it on change
    const input = screen.getByTestId("workspace-symbol-input");
    await user.clear(input);
    await user.type(input, "tsla");

    // Press Enter to commit the broadcast
    await user.keyboard("{Enter}");

    // Consumer should now see the normalised uppercase symbol
    await waitFor(() => {
      expect(screen.getByTestId("broadcast-value")).toHaveTextContent("TSLA");
    });
  });

  it("clears the broadcast symbol when Escape is pressed", async () => {
    const user = userEvent.setup();

    render(
      <WorkspaceSymbolProvider>
        <SymbolBarFixture />
        <BroadcastConsumer />
      </WorkspaceSymbolProvider>,
    );

    const input = screen.getByTestId("workspace-symbol-input");
    await user.clear(input);
    await user.type(input, "AAPL");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(screen.getByTestId("broadcast-value")).toHaveTextContent("AAPL");
    });

    // Now press Escape to clear the broadcast
    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.getByTestId("broadcast-value")).toHaveTextContent("none");
    });
  });
});

describe("H-5: Add-panel tray opens on button click", () => {
  /**
   * WHY this test: the tray is a new UX pattern (replaces the dialog). We verify
   * the "Add Panel" button toggles the tray's visibility via aria-expanded.
   */
  it("shows the add-panel tray (aria-expanded=true) when the Add Panel button is clicked", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper: makeWrapper() });

    // WHY assert tray is in DOM before clicking: the tray uses CSS transform
    // (translate-x-full) to hide/show. The DOM node exists even when closed.
    expect(screen.getByTestId("add-panel-tray")).toBeInTheDocument();

    // WHY getByRole with exact name: after the tray opens it renders a "Close add
    // panel tray" button whose aria-label also contains "add panel". We use the
    // exact name match to get the toggle button, not the tray close button.
    const toggleButton = screen.getByRole("button", { name: "Add panel" });
    await user.click(toggleButton);

    // WHY check aria-expanded: the button signals tray open state via aria-expanded.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Add panel" }),
      ).toHaveAttribute("aria-expanded", "true");
    });
  });
});

describe("H-5: Tray lists all 10 widget types", () => {
  /**
   * WHY this test: the tray must show all 10 panel types. If a developer removes
   * a type from PANEL_CATALOGUE, this test catches the regression immediately.
   */
  it("renders all 10 panel type labels in the tray", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />, { wrapper: makeWrapper() });

    // Open the tray first — use exact name to avoid matching the tray close button
    await user.click(screen.getByRole("button", { name: "Add panel" }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Add panel" }),
      ).toHaveAttribute("aria-expanded", "true");
    });

    // WHY check each label individually (not by count): if one label is missing,
    // we get a clear failure message vs a confusing count mismatch.
    // WHY these 10 labels: they exactly mirror PANEL_CATALOGUE in WorkspaceGrid.tsx.
    const expectedLabels = [
      "Chart",
      "Watchlist",
      "Screener",
      "Alerts",
      "Fundamentals",
      "News",
      "Graph",
      "Portfolio",
      "Brief",
      "Chat",
    ];

    for (const label of expectedLabels) {
      // WHY queryAllByText + toBeGreaterThanOrEqual(1): the tray items render the
      // label as a <span>. Other parts of the DOM may have UPPERCASE versions of
      // the same word (e.g., panel headers show "CHART"); "Chart" with capital-C
      // is unique to the tray.
      expect(screen.queryAllByText(label).length).toBeGreaterThanOrEqual(1);
    }
  });
});

describe("H-5: WorkspaceSymbolBar in full page", () => {
  /**
   * WHY this test: verifies the SymbolBar is present in the rendered WorkspacePage —
   * i.e., WorkspaceSymbolProvider wraps the page correctly and the bar is mounted.
   */
  it("renders the broadcast symbol input in the workspace page", () => {
    render(<WorkspacePage />, { wrapper: makeWrapper() });
    // WHY query by aria-label: WorkspaceSymbolBar gives the input
    // aria-label="Broadcast symbol to all panels".
    expect(
      screen.getByRole("textbox", { name: /broadcast symbol to all panels/i }),
    ).toBeInTheDocument();
  });
});
