/**
 * components/portfolio/__tests__/TransactionsBrokerageStatusBar.test.tsx
 *
 * WHY: Tests for TransactionsBrokerageStatusBar collapsed state, expansion
 * on click, brokerage list rendering, and status dot colour.
 *
 * MOCKED MODULES:
 *   - @/hooks/useAuth     → stub access token
 *   - @/lib/gateway       → stub getBrokerageConnections
 *
 * PRD-0089 SA-C Task 6.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { BrokerageConnection } from "@/types/api";

// ── Auth stub ─────────────────────────────────────────────────────────────────

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "u-001",
      tenant_id: "t-001",
      email: "trader@example.com",
      name: "Test Trader",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway stub ──────────────────────────────────────────────────────────────
// WHY mock @/lib/api-client (D1 fix): the SUT now uses useApiClient() instead
// of createGateway(token). Mocking the hook directly bypasses the
// ApiClientProvider requirement and keeps the test surface identical to before
// — every test still drives behaviour by stubbing getBrokerageConnections.

const mockGetBrokerageConnections = vi.fn();

vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => ({
    getBrokerageConnections: mockGetBrokerageConnections,
  })),
}));

// ── SUT import ────────────────────────────────────────────────────────────────

import { TransactionsBrokerageStatusBar } from "../TransactionsBrokerageStatusBar";

// ── Fixture factory ───────────────────────────────────────────────────────────

function makeConnection(
  overrides: Partial<BrokerageConnection> = {},
): BrokerageConnection {
  return {
    connection_id: "conn-1",
    portfolio_id: "p-1",
    brokerage_name: "Interactive Brokers",
    status: "active",
    last_synced_at: "2026-05-01T10:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// ── QueryClient wrapper ───────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        // WHY retry: 0 — tests should fail fast; retries add 5s+ delay
        retry: 0,
        // WHY gcTime: 0 — prevents caching between tests which would make
        // the gateway mock fire only once, causing false positives.
        gcTime: 0,
      },
    },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("TransactionsBrokerageStatusBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Collapsed state ──────────────────────────────────────────────────────

  it("renders collapsed by default", () => {
    mockGetBrokerageConnections.mockResolvedValue([]);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    // The status bar outer container should be present.
    expect(screen.getByTestId("brokerage-status-bar")).toBeDefined();

    // The expanded panel should NOT be visible by default.
    expect(screen.queryByTestId("brokerage-status-expanded")).toBeNull();
  });

  it("shows loading state initially while query is pending", () => {
    // Never resolves — simulates in-flight query
    mockGetBrokerageConnections.mockReturnValue(new Promise(() => {}));
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    // The button should be present even while loading.
    expect(screen.getByRole("button", { name: /brokerage/i })).toBeDefined();
  });

  // ── Connected state with brokerage list ───────────────────────────────────

  it("renders brokerage count when connections are loaded", async () => {
    const connections = [
      makeConnection({ connection_id: "conn-1", brokerage_name: "IBKR" }),
      makeConnection({ connection_id: "conn-2", brokerage_name: "Schwab", status: "active" }),
    ];
    mockGetBrokerageConnections.mockResolvedValue(connections);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    // Wait for query to resolve and component to re-render.
    await waitFor(() => {
      // When 2 connections present, the bar should show "2 connections".
      const text = screen.getByTestId("brokerage-status-bar").textContent ?? "";
      expect(text).toContain("2");
    });
  });

  it("expands on click to show brokerage list", async () => {
    const connections = [
      makeConnection({ brokerage_name: "Alpaca" }),
    ];
    mockGetBrokerageConnections.mockResolvedValue(connections);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    // Wait for query to settle.
    await waitFor(() => {
      expect(mockGetBrokerageConnections).toHaveBeenCalled();
    });

    // The expanded panel should not exist yet.
    expect(screen.queryByTestId("brokerage-status-expanded")).toBeNull();

    // Click the toggle button.
    const button = screen.getByRole("button", { name: /brokerage/i });
    fireEvent.click(button);

    // Now the expanded panel should be visible.
    await waitFor(() => {
      expect(screen.getByTestId("brokerage-status-expanded")).toBeDefined();
    });
  });

  it("shows connection details in expanded panel", async () => {
    const connections = [
      makeConnection({ brokerage_name: "Tradier", status: "active" }),
    ];
    mockGetBrokerageConnections.mockResolvedValue(connections);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    // Wait for data.
    await waitFor(() => {
      expect(mockGetBrokerageConnections).toHaveBeenCalled();
    });

    // Expand.
    fireEvent.click(screen.getByRole("button", { name: /brokerage/i }));

    // The connection row should be rendered.
    await waitFor(() => {
      expect(screen.getByTestId("brokerage-connection-conn-1")).toBeDefined();
    });

    // The broker name should appear.
    expect(screen.getByText("Tradier")).toBeDefined();
  });

  it("collapses again when clicked a second time", async () => {
    mockGetBrokerageConnections.mockResolvedValue([]);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    const button = screen.getByRole("button", { name: /brokerage/i });

    // Click to expand.
    fireEvent.click(button);
    await waitFor(() => {
      expect(screen.getByTestId("brokerage-status-expanded")).toBeDefined();
    });

    // Click to collapse.
    fireEvent.click(button);
    await waitFor(() => {
      expect(screen.queryByTestId("brokerage-status-expanded")).toBeNull();
    });
  });

  // ── Status dot colours ─────────────────────────────────────────────────────

  it("shows green dot when all connections are active", async () => {
    mockGetBrokerageConnections.mockResolvedValue([
      makeConnection({ status: "active" }),
    ]);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    await waitFor(() => {
      const dot = screen.getByTestId("brokerage-status-dot");
      // bg-positive is the green design token.
      expect(dot.className).toContain("bg-positive");
    });
  });

  it("shows yellow dot when a connection is pending", async () => {
    mockGetBrokerageConnections.mockResolvedValue([
      makeConnection({ status: "pending" }),
    ]);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    await waitFor(() => {
      const dot = screen.getByTestId("brokerage-status-dot");
      // bg-warning is the yellow/amber design token.
      expect(dot.className).toContain("bg-warning");
    });
  });

  it("shows red dot when at least one connection has an error", async () => {
    mockGetBrokerageConnections.mockResolvedValue([
      makeConnection({ connection_id: "c1", status: "active" }),
      makeConnection({ connection_id: "c2", status: "error" }),
    ]);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    await waitFor(() => {
      const dot = screen.getByTestId("brokerage-status-dot");
      // bg-negative is the red design token.
      expect(dot.className).toContain("bg-negative");
    });
  });

  it("shows muted dot when no connections exist", async () => {
    mockGetBrokerageConnections.mockResolvedValue([]);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    await waitFor(() => {
      const dot = screen.getByTestId("brokerage-status-dot");
      // bg-muted-foreground/50 is used for "no connections" state.
      expect(dot.className).toContain("bg-muted-foreground");
    });
  });

  // ── Empty expanded panel ───────────────────────────────────────────────────

  it("shows 'no connections' message in expanded panel when empty", async () => {
    mockGetBrokerageConnections.mockResolvedValue([]);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId="p-1" />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(mockGetBrokerageConnections).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByRole("button", { name: /brokerage/i }));

    await waitFor(() => {
      const panel = screen.getByTestId("brokerage-status-expanded");
      // Should contain guidance to connect a broker.
      expect(panel.textContent?.toLowerCase()).toContain("connect");
    });
  });

  // ── Disabled when no portfolioId ──────────────────────────────────────────

  it("does not call the API when portfolioId is null", async () => {
    mockGetBrokerageConnections.mockResolvedValue([]);
    const Wrapper = makeWrapper();
    render(<TransactionsBrokerageStatusBar portfolioId={null} />, { wrapper: Wrapper });

    // Wait a tick to ensure no query fired.
    await new Promise((r) => setTimeout(r, 50));
    expect(mockGetBrokerageConnections).not.toHaveBeenCalled();
  });
});
