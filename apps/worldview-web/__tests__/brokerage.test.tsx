/**
 * __tests__/brokerage.test.tsx — Unit tests for the brokerage integration components
 *
 * WHY THIS EXISTS: The brokerage components have several conditional rendering paths
 * (loading/error/empty/loaded for the list; checkbox gate for the modal; error-count
 * display for the banner) that need deterministic verification. Tests here confirm
 * the UI behaves correctly for each state without requiring a live S9 instance.
 *
 * WHAT IS TESTED:
 *   1. useBrokerageConnections — renders loading, then resolves to data
 *   2. ConnectBrokerageModal — renders content; checkbox enables Connect button
 *   3. ConnectedBrokeragesList — renders connections; Sync Now present for ACTIVE
 *   4. SyncErrorsBanner — null when no errors; shows count when errors exist
 *
 * WHY MOCK GATEWAY: deterministic data; no network dependency; fast test runs.
 * WHY MOCK useAuth: eliminates AuthContext dependency for unit-test isolation.
 *
 * DATA SOURCE: Mocked gateway client and hooks
 * DESIGN REFERENCE: PRD-0022 §6.6
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Next.js navigation mock ────────────────────────────────────────────────────
// WHY: some brokerage components (callback page) use useRouter.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
// WHY: all hooks call useAuth() to get the access token.
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
// WHY: deterministic data for each gateway method; avoids live S9 dependency.
const mockGetBrokerageConnections = vi.fn();
const mockInitiateBrokerageConnection = vi.fn();
const mockDisconnectBrokerageConnection = vi.fn();
const mockTriggerBrokerageSync = vi.fn();
const mockGetSyncErrors = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getBrokerageConnections: mockGetBrokerageConnections,
    initiateBrokerageConnection: mockInitiateBrokerageConnection,
    disconnectBrokerageConnection: mockDisconnectBrokerageConnection,
    triggerBrokerageSync: mockTriggerBrokerageSync,
    getSyncErrors: mockGetSyncErrors,
    // Auth plumbing required by AuthContext
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "test-token",
      user: { user_id: "u1", tenant_id: "t1", email: "t@e.com", name: "T", avatar_url: null },
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

// ── Sample fixtures ────────────────────────────────────────────────────────────

const ACTIVE_CONNECTION = {
  connection_id: "conn-1",
  portfolio_id: "port-1",
  brokerage_name: "Interactive Brokers",
  status: "active" as const,
  last_synced_at: "2026-04-22T10:00:00Z",
  created_at: "2026-04-01T00:00:00Z",
};

const ERROR_CONNECTION = {
  connection_id: "conn-2",
  portfolio_id: "port-1",
  brokerage_name: "Robinhood",
  status: "error" as const,
  last_synced_at: "2026-04-20T08:00:00Z",
  created_at: "2026-04-01T00:00:00Z",
};

const SAMPLE_SYNC_ERRORS = [
  {
    id: "err-1",
    connection_id: "conn-1",
    snaptrade_transaction_id: "snaptrade-tx-abc123",
    error_type: "unknown_instrument" as const,
    error_detail: "Instrument FAKECOIN not found in database",
    created_at: "2026-04-22T10:01:00Z",
  },
  {
    id: "err-2",
    connection_id: "conn-1",
    snaptrade_transaction_id: "snaptrade-tx-def456",
    error_type: "validation_error" as const,
    error_detail: "Quantity must be positive",
    created_at: "2026-04-22T09:55:00Z",
  },
];

// ── Test helpers ───────────────────────────────────────────────────────────────

/**
 * makeQueryClient — fresh QueryClient per test
 * WHY retry: false: prevents hanging tests due to TanStack Query's default retry delays.
 */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

/**
 * wrapper — QueryClientProvider wrapper for all tests
 * WHY: TanStack Query hooks require QueryClientProvider in the tree.
 */
function makeWrapper() {
  const qc = makeQueryClient();
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── ConnectBrokerageModal tests ───────────────────────────────────────────────

// WHY import here (not at top): avoids hoisting issues with vi.mock().
// The mock must be set up before the module is imported in tests.
const { ConnectBrokerageModal } = await import(
  "@/components/brokerage/ConnectBrokerageModal"
);

describe("ConnectBrokerageModal", () => {
  beforeEach(() => {
    mockInitiateBrokerageConnection.mockResolvedValue({
      connection_id: "conn-new",
      redirect_uri: "https://connect.snaptrade.com/oauth?...",
    });
  });

  it("renders modal title when open", () => {
    render(
      <ConnectBrokerageModal
        portfolioId="port-1"
        portfolioName="My Portfolio"
        open={true}
        onOpenChange={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    );

    expect(screen.getByText("Connect Brokerage Account")).toBeInTheDocument();
  });

  it("renders the portfolio name badge", () => {
    render(
      <ConnectBrokerageModal
        portfolioId="port-1"
        portfolioName="My Portfolio"
        open={true}
        onOpenChange={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    );

    // WHY check badge text: the user should know which portfolio gets the transactions
    expect(screen.getByText("My Portfolio")).toBeInTheDocument();
  });

  it("Connect button is disabled before ToS checkbox is ticked", () => {
    render(
      <ConnectBrokerageModal
        portfolioId="port-1"
        open={true}
        onOpenChange={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    );

    // The Connect button should be disabled until the checkbox is ticked
    const connectBtn = screen.getByRole("button", { name: /connect/i });
    expect(connectBtn).toBeDisabled();
  });

  it("Connect button becomes enabled after ticking the ToS checkbox", async () => {
    const user = userEvent.setup();

    render(
      <ConnectBrokerageModal
        portfolioId="port-1"
        open={true}
        onOpenChange={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    );

    // Find and tick the consent checkbox
    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);

    // WHY waitFor: checkbox state update is async with userEvent
    await waitFor(() => {
      const connectBtn = screen.getByRole("button", { name: /connect/i });
      // After ticking, the button should be enabled
      expect(connectBtn).not.toBeDisabled();
    });
  });

  it("shows SnapTrade ToS link", () => {
    render(
      <ConnectBrokerageModal
        portfolioId="port-1"
        open={true}
        onOpenChange={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    );

    // WHY check link: ToS link is a legal/compliance requirement
    const tosLink = screen.getByRole("link", { name: /SnapTrade.*Terms of Service/i });
    expect(tosLink).toHaveAttribute("href", "https://snaptrade.com/tos");
    expect(tosLink).toHaveAttribute("target", "_blank");
  });
});

// ── ConnectedBrokeragesList tests ─────────────────────────────────────────────

const { ConnectedBrokeragesList } = await import(
  "@/components/brokerage/ConnectedBrokeragesList"
);

describe("ConnectedBrokeragesList", () => {
  beforeEach(() => {
    // Default: empty sync errors so SyncErrorsBanner renders nothing
    mockGetSyncErrors.mockResolvedValue([]);
    mockTriggerBrokerageSync.mockResolvedValue({
      status: "syncing",
      connection_id: "conn-1",
    });
    mockDisconnectBrokerageConnection.mockResolvedValue(undefined);
  });

  it("shows loading skeletons initially", () => {
    // WHY never resolve: keeps the component in loading state for this test
    mockGetBrokerageConnections.mockReturnValue(new Promise(() => {}));

    const { container } = render(
      <ConnectedBrokeragesList portfolioId="port-1" />,
      { wrapper: makeWrapper() },
    );

    // WHY aria-busy: the skeleton container has aria-busy="true" while loading
    expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument();
  });

  it("renders brokerage names after data loads", async () => {
    mockGetBrokerageConnections.mockResolvedValue([
      ACTIVE_CONNECTION,
      ERROR_CONNECTION,
    ]);

    render(
      <ConnectedBrokeragesList portfolioId="port-1" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("Interactive Brokers")).toBeInTheDocument();
      expect(screen.getByText("Robinhood")).toBeInTheDocument();
    });
  });

  it("shows Sync Now button for ACTIVE connection", async () => {
    mockGetBrokerageConnections.mockResolvedValue([ACTIVE_CONNECTION]);

    render(
      <ConnectedBrokeragesList portfolioId="port-1" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      // WHY find by text: the Sync Now button has visible text
      expect(screen.getByText("Sync Now")).toBeInTheDocument();
    });
  });

  it("shows Sync Now button for ERROR connection", async () => {
    mockGetBrokerageConnections.mockResolvedValue([ERROR_CONNECTION]);

    render(
      <ConnectedBrokeragesList portfolioId="port-1" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      // WHY getByRole not getByText: the recovery hint paragraph also contains the
      // text "Sync Now" as a styled span. getByRole('button') targets the actionable
      // element specifically, avoiding the "Found multiple elements" ambiguity.
      expect(screen.getByRole("button", { name: /Sync Now/i })).toBeInTheDocument();
    });
  });

  it("renders empty state when no connections exist", async () => {
    mockGetBrokerageConnections.mockResolvedValue([]);

    render(
      <ConnectedBrokeragesList portfolioId="port-1" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText(/No brokerages connected/)).toBeInTheDocument();
    });
  });

  it("renders error state when query fails", async () => {
    mockGetBrokerageConnections.mockRejectedValue(new Error("Network error"));

    render(
      <ConnectedBrokeragesList portfolioId="port-1" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(
        screen.getByText("Failed to load brokerage connections. Please refresh."),
      ).toBeInTheDocument();
    });
  });

  it("shows status badge for active connection", async () => {
    mockGetBrokerageConnections.mockResolvedValue([ACTIVE_CONNECTION]);

    render(
      <ConnectedBrokeragesList portfolioId="port-1" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      // WHY find by text ACTIVE: the StatusBadge renders the status string as label
      expect(screen.getByText("ACTIVE")).toBeInTheDocument();
    });
  });
});

// ── SyncErrorsBanner tests ────────────────────────────────────────────────────

const { SyncErrorsBanner } = await import(
  "@/components/brokerage/SyncErrorsBanner"
);

describe("SyncErrorsBanner", () => {
  it("renders nothing when there are no sync errors", async () => {
    mockGetSyncErrors.mockResolvedValue([]);

    const { container } = render(
      <SyncErrorsBanner connectionId="conn-1" />,
      { wrapper: makeWrapper() },
    );

    // WHY waitFor: query is async; must wait for it to resolve
    await waitFor(() => {
      // The banner should render no content when errors array is empty
      expect(container.firstChild).toBeNull();
    });
  });

  it("renders nothing while loading (no loading skeleton flicker)", () => {
    // Keep the query pending to test the loading state
    mockGetSyncErrors.mockReturnValue(new Promise(() => {}));

    const { container } = render(
      <SyncErrorsBanner connectionId="conn-1" />,
      { wrapper: makeWrapper() },
    );

    // WHY null: the banner deliberately renders nothing while loading to
    // avoid distracting skeleton UI for secondary information
    expect(container.firstChild).toBeNull();
  });

  it("shows error count when sync errors exist", async () => {
    mockGetSyncErrors.mockResolvedValue(SAMPLE_SYNC_ERRORS);

    render(
      <SyncErrorsBanner connectionId="conn-1" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      // Should show "2 sync errors" (SAMPLE_SYNC_ERRORS has 2 items)
      expect(screen.getByText(/2 sync errors?/i)).toBeInTheDocument();
    });
  });

  it("shows error type summary in collapsed header", async () => {
    mockGetSyncErrors.mockResolvedValue(SAMPLE_SYNC_ERRORS);

    render(
      <SyncErrorsBanner connectionId="conn-1" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      // WHY check for "unknown instruments": SAMPLE_SYNC_ERRORS has 1 unknown_instrument error
      // and 1 validation_error; the summary should include both types
      expect(screen.getByText(/unknown instruments/i)).toBeInTheDocument();
    });
  });

  it("expands to show error details on click", async () => {
    const user = userEvent.setup();
    mockGetSyncErrors.mockResolvedValue(SAMPLE_SYNC_ERRORS);

    render(
      <SyncErrorsBanner connectionId="conn-1" />,
      { wrapper: makeWrapper() },
    );

    // Wait for data to load
    await waitFor(() => {
      expect(screen.getByText(/2 sync errors?/i)).toBeInTheDocument();
    });

    // WHY click the expand button: details are hidden in collapsed state
    const expandBtn = screen.getByRole("button", { name: /expand sync errors/i });
    await user.click(expandBtn);

    await waitFor(() => {
      // Error detail text should now be visible
      expect(
        screen.getByText("Instrument FAKECOIN not found in database"),
      ).toBeInTheDocument();
    });
  });

  it("does not render when connectionId is empty string", () => {
    // WHY empty string test: useSyncErrors has an enabled guard for empty connectionId.
    // This test verifies the banner doesn't try to fetch for an invalid ID.
    const { container } = render(
      <SyncErrorsBanner connectionId="" />,
      { wrapper: makeWrapper() },
    );

    // enabled: false → query never fires → banner stays null
    expect(container.firstChild).toBeNull();
  });
});
