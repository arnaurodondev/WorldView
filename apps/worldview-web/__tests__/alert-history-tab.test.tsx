/**
 * __tests__/alert-history-tab.test.tsx — PLAN-0051 T-D-4-04 history table.
 *
 * Covers the new History tab on /alerts:
 *   - Filter pills (severity) call the gateway with the right param.
 *   - Date / entity inputs flow into the gateway query.
 *   - Pagination "Load more" appends rows.
 *   - Empty + error states.
 *   - Status badge rendering for active / acked / snoozed rows.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AlertHistoryTab } from "@/components/alerts/AlertHistoryTab";

// ── Navigation + auth mocks ────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  usePathname: vi.fn(() => "/alerts"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "T", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// Gateway mock — getAlertHistory returns paginated rows.
const historyMock = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getAlertHistory: historyMock,
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={makeQueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  historyMock.mockReset();
});

function makeRows(count: number, overrides: Partial<{ status: string }> = {}) {
  return Array.from({ length: count }).map((_, i) => ({
    alert_id: `alert-${i + 1}`,
    entity_id: `entity-${i + 1}`,
    ticker: `TKR${i + 1}`,
    alert_type: "PRICE_MOVE",
    severity: "HIGH" as const,
    title: `Alert ${i + 1}`,
    body: "",
    metadata: {},
    created_at: new Date(Date.now() - i * 60_000).toISOString(),
    acknowledged_at: overrides.status === "ack" ? new Date().toISOString() : null,
    snooze_until:
      overrides.status === "snoozed" ? new Date(Date.now() + 60 * 60_000).toISOString() : null,
  }));
}

describe("AlertHistoryTab", () => {
  it("renders rows and severity filter pills", async () => {
    historyMock.mockResolvedValue({ alerts: makeRows(2), total: 2, offset: 0, limit: 50 });
    render(<AlertHistoryTab />, { wrapper });

    expect(await screen.findByText(/TKR1/)).toBeInTheDocument();
    expect(screen.getByText(/TKR2/)).toBeInTheDocument();
    // Filter pills present
    expect(screen.getByRole("button", { name: /^ALL$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^CRITICAL$/ })).toBeInTheDocument();
  });

  it("clicking a severity pill calls gateway with that severity", async () => {
    historyMock.mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 50 });
    const user = userEvent.setup();
    render(<AlertHistoryTab />, { wrapper });

    await waitFor(() => expect(historyMock).toHaveBeenCalled());
    historyMock.mockClear();
    await user.click(screen.getByRole("button", { name: /^HIGH$/ }));

    await waitFor(() => {
      const lastCall = historyMock.mock.calls.at(-1);
      expect(lastCall?.[0]?.severity).toBe("HIGH");
    });
  });

  it("date range inputs are forwarded to the gateway", async () => {
    historyMock.mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 50 });
    const user = userEvent.setup();
    render(<AlertHistoryTab />, { wrapper });
    await waitFor(() => expect(historyMock).toHaveBeenCalled());

    historyMock.mockClear();
    await user.type(screen.getByLabelText(/From date/i), "2026-04-01");

    await waitFor(() => {
      const lastCall = historyMock.mock.calls.at(-1);
      expect(lastCall?.[0]?.from).toBeDefined();
    });
  });

  it("renders the empty-state message when gateway returns []", async () => {
    historyMock.mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 50 });
    render(<AlertHistoryTab />, { wrapper });
    expect(await screen.findByText(/No alerts match the current filters/i)).toBeInTheDocument();
  });

  it("renders the error state when gateway rejects", async () => {
    historyMock.mockRejectedValueOnce(new Error("boom"));
    render(<AlertHistoryTab />, { wrapper });
    expect(await screen.findByText(/Failed to load alert history/i)).toBeInTheDocument();
  });

  it("Load more appears when total > rows.length and increases page size", async () => {
    // First call returns 50, total 100. Second returns 100.
    historyMock
      .mockResolvedValueOnce({ alerts: makeRows(50), total: 100, offset: 0, limit: 50 })
      .mockResolvedValueOnce({ alerts: makeRows(100), total: 100, offset: 0, limit: 100 });
    const user = userEvent.setup();
    render(<AlertHistoryTab />, { wrapper });

    const loadMore = await screen.findByRole("button", { name: /Load more/i });
    expect(loadMore).toBeInTheDocument();
    await user.click(loadMore);

    await waitFor(() => {
      const lastCall = historyMock.mock.calls.at(-1);
      expect(lastCall?.[0]?.limit).toBe(100);
    });
  });

  it("renders ack / snoozed status badges", async () => {
    historyMock.mockResolvedValue({
      alerts: [
        ...makeRows(1, { status: "ack" }),
        ...makeRows(1, { status: "snoozed" }).map((r, i) => ({ ...r, alert_id: `s-${i}` })),
      ],
      total: 2,
      offset: 0,
      limit: 50,
    });
    render(<AlertHistoryTab />, { wrapper });

    expect(await screen.findByText(/ack/i)).toBeInTheDocument();
    expect(screen.getByText(/snoozed/i)).toBeInTheDocument();
  });

  it("fixedStatus prop is propagated to the gateway query", async () => {
    historyMock.mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 50 });
    render(<AlertHistoryTab fixedStatus="acknowledged" />, { wrapper });

    await waitFor(() => {
      const firstCall = historyMock.mock.calls.at(0);
      expect(firstCall?.[0]?.status).toBe("acknowledged");
    });
  });
});
