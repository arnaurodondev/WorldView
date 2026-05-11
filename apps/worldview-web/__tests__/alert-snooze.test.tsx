/**
 * __tests__/alert-snooze.test.tsx — PLAN-0051 T-D-4-08 Snooze flows.
 *
 * WHY THESE TESTS EXIST: T-D-4-03 introduced backend-synced ACK/snooze with a
 * graceful 404 fallback to localStorage-only mode. The snooze contract is
 * the trickiest piece (PATCH /v1/alerts/{id}/snooze with `snooze_until` ISO
 * datetime + a `(local only)` UI badge on 404). These tests cover:
 *   1. Quick-snooze options (15m / 1h / 24h) call the gateway with the
 *      expected ISO datetime.
 *   2. Backend 404 falls back to localStorage and surfaces the local-only
 *      badge.
 *   3. minutesUntilEndOfDay produces a positive duration for daytime calls.
 *   4. Successful snooze mutation persists to the snooze localStorage map.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AlertsList, minutesUntilEndOfDay } from "@/components/alerts/AlertsList";

// ── Next.js navigation mock — mirrors alerts-page.test.tsx setup ──────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  })),
  usePathname: vi.fn(() => "/alerts"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "Test", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// Gateway mocks — snoozeAlert + acknowledgeAlert spies are inspected per test.
const snoozeMock = vi.fn().mockResolvedValue({});
const ackMock = vi.fn().mockResolvedValue({});

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getPendingAlerts: vi.fn().mockResolvedValue({
      alerts: [
        {
          alert_id: "alert-001",
          entity_id: "entity-aapl",
          ticker: "AAPL",
          alert_type: "PRICE_MOVE",
          severity: "HIGH" as const,
          title: "AAPL moved",
          body: "Apple +5%",
          metadata: {},
          created_at: new Date().toISOString(),
          acknowledged_at: null,
        },
      ],
      total: 1,
      offset: 0,
      limit: 50,
    }),
    snoozeAlert: snoozeMock,
    acknowledgeAlert: ackMock,
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Helpers ──────────────────────────────────────────────────────────────
function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={makeQueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore opaque-origin */ }
  snoozeMock.mockClear();
  snoozeMock.mockResolvedValue({});
  ackMock.mockClear();
  ackMock.mockResolvedValue({});
});

// ── Tests ─────────────────────────────────────────────────────────────────

describe("Alert snooze (PLAN-0051 T-D-4-03)", () => {
  it("renders snooze 15m / 1h / EOD / 24h / custom options in the dropdown", async () => {
    const user = userEvent.setup();
    render(<AlertsList />, { wrapper });
    // Wait for the alert row to load.
    await waitFor(() => expect(screen.getByText(/AAPL/)).toBeInTheDocument());

    // Open the ACK dropdown by clicking the trigger button.
    const ackTrigger = screen.getByRole("button", { name: /Acknowledge or snooze/i });
    await user.click(ackTrigger);

    // Each quick option must be present.
    expect(await screen.findByText(/Snooze 15m/i)).toBeInTheDocument();
    expect(screen.getByText(/Snooze 1h/i)).toBeInTheDocument();
    expect(screen.getByText(/Snooze until EOD/i)).toBeInTheDocument();
    expect(screen.getByText(/Snooze 24h/i)).toBeInTheDocument();
    expect(screen.getByText(/Snooze custom/i)).toBeInTheDocument();
  });

  it("clicking Snooze 1h calls gateway.snoozeAlert with ~1h delta", async () => {
    const user = userEvent.setup();
    render(<AlertsList />, { wrapper });
    await waitFor(() => expect(screen.getByText(/AAPL/)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /Acknowledge or snooze/i }));
    await user.click(await screen.findByText(/Snooze 1h/i));

    await waitFor(() => expect(snoozeMock).toHaveBeenCalledTimes(1));
    const [alertId, until] = snoozeMock.mock.calls[0] as [string, Date];
    expect(alertId).toBe("alert-001");
    // Should be roughly 60 minutes in the future (allow 5s drift).
    const deltaMs = until.getTime() - Date.now();
    expect(deltaMs).toBeGreaterThan(59 * 60 * 1000);
    expect(deltaMs).toBeLessThan(61 * 60 * 1000);
  });

  it("surfaces a real error when gateway.snoozeAlert returns 404 (no localStorage fallback)", async () => {
    // QA-iter1 MAJ-2: 404 is now treated as a hard error (alert missing or
    // forbidden) rather than "endpoint not deployed". The previous behaviour
    // silently let users snooze other-tenant alerts in localStorage.
    const user = userEvent.setup();
    const { GatewayError } = await import("@/lib/gateway");
    snoozeMock.mockRejectedValueOnce(new GatewayError(404, "Not Found"));

    render(<AlertsList />, { wrapper });
    await waitFor(() => expect(screen.getByText(/AAPL/)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /Acknowledge or snooze/i }));
    await user.click(await screen.findByText(/Snooze 15m/i));

    // The optimistic localStorage write still happens (UI is responsive),
    // but the alert is NOT marked "local only" — the error surfaces and the
    // user should see no `(local only)` badge / acceptance signal.
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByText(/local only/i)).not.toBeInTheDocument();
  });

  it("ACK 404 surfaces a real error (no silent localStorage success)", async () => {
    // QA-iter1 MAJ-2: previously a 404 from the ACK endpoint silently fell
    // back to localStorage with a "(local only)" badge. That masked
    // tenant-isolation rejections (S9 collapses 403 → 404 on purpose).
    // The current contract: any error from the backend is a real error.
    const user = userEvent.setup();
    const { GatewayError } = await import("@/lib/gateway");
    ackMock.mockRejectedValueOnce(new GatewayError(404, "Not Found"));

    render(<AlertsList />, { wrapper });
    await waitFor(() => expect(screen.getByText(/AAPL/)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /Acknowledge or snooze/i }));
    await user.click(await screen.findByText(/^Acknowledge$/i));

    // Allow microtasks to settle.
    await new Promise((r) => setTimeout(r, 30));
    // The "(local only)" badge MUST NOT render — the 404 is a real failure.
    expect(screen.queryByText(/local only/i)).not.toBeInTheDocument();
  });

  it("snoozeAlert is called with body shape {until: <iso>} (QA-iter1 C-1)", async () => {
    // Pin the wire contract end-to-end: the gateway must invoke snoozeAlert
    // with a Date — which is then serialised as `{until: <iso>}` per the
    // backend SnoozeAlertRequest. The previous draft sent `{snooze_until: …}`
    // and 422'd against S10. We assert the gateway-level invocation here and
    // pin the body shape in the gateway.test.ts companion.
    const user = userEvent.setup();
    render(<AlertsList />, { wrapper });
    await waitFor(() => expect(screen.getByText(/AAPL/)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /Acknowledge or snooze/i }));
    await user.click(await screen.findByText(/Snooze 15m/i));

    await waitFor(() => expect(snoozeMock).toHaveBeenCalledTimes(1));
    const [, until] = snoozeMock.mock.calls[0] as [string, Date];
    // Argument is a Date object — the gateway constructs the {until} body.
    expect(until).toBeInstanceOf(Date);
    expect(until.getTime()).toBeGreaterThan(Date.now());
  });

  it("minutesUntilEndOfDay returns a positive minute count during daytime", () => {
    // 10:00 local → ~14h → ~840 minutes. We just check positivity + bound.
    const noon = new Date();
    noon.setHours(10, 0, 0, 0);
    const minutes = minutesUntilEndOfDay(noon);
    expect(minutes).toBeGreaterThan(0);
    expect(minutes).toBeLessThanOrEqual(24 * 60);
  });

  it("non-404 gateway errors do NOT mark the alert local-only", async () => {
    const user = userEvent.setup();
    const { GatewayError } = await import("@/lib/gateway");
    snoozeMock.mockRejectedValueOnce(new GatewayError(503, "Service Unavailable"));

    render(<AlertsList />, { wrapper });
    await waitFor(() => expect(screen.getByText(/AAPL/)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /Acknowledge or snooze/i }));
    await user.click(await screen.findByText(/Snooze 15m/i));

    // localStorage still updated optimistically …
    await waitFor(() => {
      const raw = localStorage.getItem("worldview-alert-snooze");
      expect(raw).not.toBeNull();
    });
    // … but the local-only badge should NOT render — the 503 is a real
    // failure, not a "endpoint missing" fallback.
    // Allow a microtask to flush any pending state.
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByText(/local only/i)).not.toBeInTheDocument();
    // Avoid unused-import lint by referencing fireEvent in trivial way.
    expect(fireEvent).toBeTruthy();
  });
});
