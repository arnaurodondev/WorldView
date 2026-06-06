/**
 * PLAN-0049 T-D-4-04 regression: dashboard alert rows must NEVER render bare
 * "<SEVERITY> signal" / "<SEVERITY> alert" strings (F-D-006 / F-X-201).
 *
 * The fallback chain must always produce something more useful — either the
 * backend-composed title, or a humanised alert_type, or the entity/ticker
 * subject — never the raw severity string. Pin the contract here so any
 * regression in RecentAlerts trips the test suite immediately.
 */
import { describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// AlertStreamContext mock — copied from dashboard.test.tsx pattern.
vi.mock("@/contexts/AlertStreamContext", () => ({
  useAlertStream: vi.fn(() => ({
    recentAlerts: [],
    unreadCount: 0,
    connectionStatus: "disconnected" as const,
    markAllRead: vi.fn(),
  })),
  AlertStreamProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// Auth hook mock — RecentAlerts imports `useAuth` from "@/hooks/useAuth".
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    user: { user_id: "u-1", email: "t@t" },
    accessToken: "tok",
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  })),
}));

// Gateway mock — RecentAlerts calls getAlertHistory via createGateway().
// WHY getAlertHistory (not getPendingAlerts): the component was refactored in
// PLAN-0049 F-5 to use getAlertHistory (reads `alerts` table directly — the
// authoritative store) instead of getPendingAlerts (reads delivery queue, empty
// for seeded alerts). Tests must mock the same method the component actually calls.
const mockGetAlertHistory = vi.fn();
vi.mock("@/lib/gateway", () => ({
  // RecentAlerts calls getPendingAlerts; alias to the same mock so existing
  // mockResolvedValueOnce setups continue to drive the test.
  createGateway: vi.fn(() => ({
    getAlertHistory: mockGetAlertHistory,
    getPendingAlerts: mockGetAlertHistory,
  })),
}));

import { RecentAlerts } from "@/components/dashboard/RecentAlerts";

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("RecentAlerts — no bare-severity strings (F-D-006)", () => {
  it("never renders bare 'LOW signal' / 'MEDIUM alert' strings for naked alerts", async () => {
    // Worst case: alert with neither title, signal_label, ticker, nor entity_name.
    // Old code rendered "LOW alert"; new code must humanise alert_type instead.
    mockGetAlertHistory.mockResolvedValueOnce({
      alerts: [
        {
          alert_id: "00000000-0000-0000-0000-000000000001",
          entity_id: "e1",
          alert_type: "graph_change",
          severity: "low",
          title: null,
          ticker: null,
          entity_name: null,
          signal_label: null,
          payload: {},
          created_at: new Date().toISOString(),
          source_topic: "",
        },
      ],
      total: 1,
      offset: 0,
      limit: 8,
    });

    render(wrap(<RecentAlerts />));

    // Wait for async query resolution, then assert no bare-severity strings.
    await waitFor(() => {
      const text = document.body.textContent ?? "";
      expect(text).not.toMatch(/^(LOW|MEDIUM|HIGH|CRITICAL)\s+(signal|alert)$/m);
      expect(text).not.toContain("LOW signal");
      expect(text).not.toContain("MEDIUM signal");
      expect(text).not.toContain("HIGH signal");
      expect(text).not.toContain("CRITICAL signal");
    });
  });

  it("uses backend-composed title when present", async () => {
    mockGetAlertHistory.mockResolvedValueOnce({
      alerts: [
        {
          alert_id: "00000000-0000-0000-0000-000000000002",
          entity_id: "e2",
          alert_type: "signal",
          severity: "high",
          title: "Apple Inc.: Bullish guidance",
          ticker: "AAPL",
          entity_name: "Apple Inc.",
          signal_label: "Bullish guidance",
          payload: {},
          created_at: new Date().toISOString(),
          source_topic: "",
        },
      ],
      total: 1,
      offset: 0,
      limit: 8,
    });

    const { findByText } = render(wrap(<RecentAlerts />));
    expect(await findByText(/Apple Inc.: Bullish guidance/)).toBeInTheDocument();
  });
});
