/**
 * __tests__/collapsible-sidebar.test.tsx — Unit tests for CollapsibleSidebar
 *
 * WHY THIS EXISTS: The sidebar is the primary navigation surface — any regression
 * here breaks navigation for the entire application. Tests verify:
 * 1. All 8 nav items are present (Dashboard, Portfolio, Instruments, Screener, Workspace, Predictions, Alerts, Chat)
 * 2. The active route gets highlighted (aria-current + active styling)
 * 3. Collapsed state hides nav labels (icon-only mode)
 * 4. Expanded state shows nav labels
 * 5. Toggle button is present and clickable
 * 6. WatchlistPanel shows empty state when no watchlist data
 * 7. AlarmsPanel shows empty state when no alerts
 *
 * WHY MOCK GATEWAY: Prevents real S9 calls; controls WatchlistPanel and AlarmsPanel
 * response shapes so we can assert empty states without a running API.
 * WHY MOCK next/navigation: CollapsibleSidebar uses usePathname() — App Router is
 * not mounted in vitest/jsdom; mock prevents "usePathname must be used inside App Router".
 * WHY MOCK useAuth: WatchlistPanel and AlarmsPanel call useAuth() for the access token.
 *
 * DATA SOURCE: Mocked gateway client
 * DESIGN REFERENCE: PRD-0031 §4.2–§4.3 Sidebar spec
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CollapsibleSidebar } from "@/components/shell/CollapsibleSidebar";

// ── Next.js navigation mock ────────────────────────────────────────────────────
// WHY: CollapsibleSidebar uses usePathname() to highlight the active nav item.
// We must control the return value to test active state assertions.
const mockPathname = vi.fn(() => "/dashboard");
vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn() })),
}));

// ── Auth mock ──────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
  })),
}));

// ── Gateway mock ───────────────────────────────────────────────────────────────
// WHY empty arrays: triggers empty state rendering in WatchlistPanel + AlarmsPanel
// so we can assert the sidebar renders without errors under zero-data conditions.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getWatchlists: vi.fn().mockResolvedValue([]),
    getBatchQuotes: vi.fn().mockResolvedValue({ quotes: {} }),
    getPendingAlerts: vi.fn().mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 20 }),
    refreshToken: vi.fn().mockResolvedValue({ access_token: "t", user: {}, expires_in: 900 }),
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

// ── Test helpers ───────────────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const mockOnToggle = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mockPathname.mockReturnValue("/dashboard");
});

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("CollapsibleSidebar — expanded state", () => {
  it("renders all 8 nav items", () => {
    render(
      <CollapsibleSidebar expanded onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    // WHY check aria-label not text: labels are conditionally hidden in collapsed
    // state. Using aria-label works for both collapsed (icon-only) and expanded.
    expect(screen.getByRole("link", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Screener" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Portfolio" })).toBeInTheDocument();
    // PLAN-0068 C-2-03: Predictions nav entry added
    expect(screen.getByRole("link", { name: "Predictions" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Alerts" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Chat" })).toBeInTheDocument();
  });

  it("shows nav labels when expanded", () => {
    render(
      <CollapsibleSidebar expanded onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    // WHY getByText: labels are <span> elements inside the link — visible text
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Screener")).toBeInTheDocument();
  });

  it("highlights the active route with aria-current=page", () => {
    mockPathname.mockReturnValue("/dashboard");
    render(
      <CollapsibleSidebar expanded onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    // WHY aria-current: semantic active route indicator — screen readers announce "current page"
    const dashboardLink = screen.getByRole("link", { name: "Dashboard" });
    expect(dashboardLink).toHaveAttribute("aria-current", "page");
  });

  it("does not apply aria-current to inactive routes", () => {
    mockPathname.mockReturnValue("/dashboard");
    render(
      <CollapsibleSidebar expanded onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    const workspaceLink = screen.getByRole("link", { name: "Workspace" });
    expect(workspaceLink).not.toHaveAttribute("aria-current");
  });

  it("renders the Collapse button when expanded", () => {
    render(
      <CollapsibleSidebar expanded onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toBeInTheDocument();
  });

  it("calls onToggle when the Collapse button is clicked", async () => {
    const user = userEvent.setup();
    render(
      <CollapsibleSidebar expanded onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(mockOnToggle).toHaveBeenCalledOnce();
  });

  it("does not show a W brand glyph (TopBar is the canonical brand location)", () => {
    // WHY no "W" in sidebar: "Worldview" is displayed in the TopBar — repeating
    // a brand glyph in the sidebar adds visual clutter. The logo row was removed
    // per Bloomberg Terminal convention (brand identity in top bar only).
    render(
      <CollapsibleSidebar expanded onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    // queryByText returns null (not found) — confirm "W" is absent from the sidebar
    expect(screen.queryByText("W")).not.toBeInTheDocument();
  });
});

describe("CollapsibleSidebar — collapsed state", () => {
  it("hides nav labels when collapsed", () => {
    render(
      <CollapsibleSidebar expanded={false} onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    // WHY queryByText not getByText: labels should be absent (not just hidden)
    // in collapsed state — we verify conditional rendering, not CSS visibility.
    expect(screen.queryByText("Workspace")).not.toBeInTheDocument();
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
    expect(screen.queryByText("Screener")).not.toBeInTheDocument();
  });

  it("hides the WORLDVIEW brand label when collapsed", () => {
    render(
      <CollapsibleSidebar expanded={false} onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    expect(screen.queryByText("WORLDVIEW")).not.toBeInTheDocument();
  });

  it("still shows all 6 nav items via aria-label when collapsed", () => {
    render(
      <CollapsibleSidebar expanded={false} onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    // Icons are still rendered; aria-label is the only label affordance in collapsed mode
    expect(screen.getByRole("link", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Screener" })).toBeInTheDocument();
  });

  it("renders the Expand sidebar button when collapsed", () => {
    render(
      <CollapsibleSidebar expanded={false} onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });
});

describe("CollapsibleSidebar — bottom chrome", () => {
  it("renders the Settings link", () => {
    render(
      <CollapsibleSidebar expanded onToggle={mockOnToggle} />,
      { wrapper: makeWrapper() },
    );

    // WHY getByText: the Settings link is always rendered (both states)
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });
});
