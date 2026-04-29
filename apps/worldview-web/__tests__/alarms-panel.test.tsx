/**
 * __tests__/alarms-panel.test.tsx — PLAN-0049 T-D-4-05 regression coverage.
 *
 * WHY THIS EXISTS: AlarmsPanel sits in the sidebar shell — it must NEVER
 * drift from RecentAlerts on (a) the alert title fallback chain or (b) the
 * deep-link ``?selected={id}`` contract. F-303 was the last drift incident
 * (RecentAlerts had deep-links, AlarmsPanel didn't). PLAN-0049 T-D-4-04
 * unified the two via lib/alerts/format and ``router.push("/alerts?selected=...")``.
 * This test pins both contracts on the AlarmsPanel surface specifically.
 *
 * SCOPE: 2 specs:
 *   1. Title fallback chain — same fallback as RecentAlerts (delegated to
 *      ``formatAlertTitle``), proving the surfaces share the same formatter.
 *   2. Deep-link parity — clicking a row calls ``router.push`` with the
 *      ``/alerts?selected={id}`` URL.
 *
 * WHY MOCK GATEWAY + next/navigation: AlarmsPanel calls
 * ``createGateway(token).getPendingAlerts({ limit: 20 })`` and uses
 * ``useRouter().push`` for navigation. Both must be deterministic.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Alert } from "@/types/api";

// ── Navigation mock — capture router.push calls ──────────────────────────────
const mockRouterPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: mockRouterPush,
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
const mockGetPendingAlerts = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({ getPendingAlerts: mockGetPendingAlerts })),
}));

import { AlarmsPanel } from "@/components/shell/AlarmsPanel";

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Typed Alert builder — see recent-alerts.test.tsx for rationale ───────────
function makeAlert(overrides: Partial<Alert>): Alert {
  return {
    alert_id: "a-1",
    entity_id: "e-1",
    ticker: null,
    alert_type: "graph_change",
    severity: "LOW",
    title: null,
    body: "",
    entity_name: null,
    signal_label: null,
    payload: {},
    metadata: {},
    created_at: new Date().toISOString(),
    acknowledged_at: null,
    ...overrides,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AlarmsPanel — PLAN-0049 T-D-4-04 fallback parity + deep-links", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses the same title fallback chain as RecentAlerts", async () => {
    // WHY this is a parity test (not just "renders title"): F-303 was caused
    // by the two surfaces drifting. Both must delegate to ``formatAlertTitle``
    // — the contract is "same input → same rendered title". One alert per
    // fallback rung verifies the chain end-to-end.
    const alerts: Alert[] = [
      // Title rung
      makeAlert({
        alert_id: "alm-1",
        title: "Apple Inc.: Q1 beat",
        ticker: "AAPL",
      }),
      // Signal label rung
      makeAlert({
        alert_id: "alm-2",
        signal_label: "Volatility spike",
      }),
      // Entity name rung
      makeAlert({
        alert_id: "alm-3",
        entity_name: "Microsoft Corp.",
      }),
      // Humanised alert_type rung
      makeAlert({
        alert_id: "alm-4",
        alert_type: "graph_change",
      }),
    ];
    mockGetPendingAlerts.mockResolvedValueOnce({
      alerts,
      total: alerts.length,
      offset: 0,
      limit: 20,
    });

    render(wrap(<AlarmsPanel />));

    await waitFor(() => {
      expect(screen.getByText("Apple Inc.: Q1 beat")).toBeInTheDocument();
    });
    expect(screen.getByText("Volatility spike")).toBeInTheDocument();
    expect(screen.getByText("Microsoft Corp.")).toBeInTheDocument();
    expect(screen.getByText("Graph Change alert")).toBeInTheDocument();

    // Negative regex: ensure none of the bare-severity strings leaked.
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("LOW signal");
    expect(text).not.toContain("LOW alert");
  });

  it("clicking a row navigates to /alerts?selected={id} (deep-link parity)", async () => {
    // F-303 deep-link parity test — clicking the row in the sidebar must take
    // the user directly to the AlertDetailSheet, same as RecentAlerts. Without
    // this, the sidebar drops users on the bare list.
    const alert = makeAlert({
      alert_id: "deadbeef-1234-5678-9abc-def012345678",
      title: "Apple: Bullish guidance",
      ticker: "AAPL",
      severity: "HIGH",
    });
    mockGetPendingAlerts.mockResolvedValueOnce({
      alerts: [alert],
      total: 1,
      offset: 0,
      limit: 20,
    });

    const user = userEvent.setup();
    render(wrap(<AlarmsPanel />));

    const row = await screen.findByText("Apple: Bullish guidance");
    // Click the row's parent (the panel uses a div onClick — not a Link).
    await user.click(row);

    // router.push must be called with the deep-link URL.
    expect(mockRouterPush).toHaveBeenCalledWith(
      `/alerts?selected=${encodeURIComponent(alert.alert_id)}`,
    );
  });
});
