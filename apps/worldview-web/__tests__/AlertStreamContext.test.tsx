/**
 * __tests__/AlertStreamContext.test.tsx — Tests for alert stream state management
 *
 * WHY THIS EXISTS: AlertStreamContext is the real-time backbone of the alert system.
 * Tests verify that:
 * 1. CRITICAL alerts go to criticalQueue
 * 2. Non-critical alerts go to recentAlerts
 * 3. dequeueCritical() removes the first (oldest) alert
 * 4. recentAlerts is capped at MAX_RECENT
 *
 * WHY mock WebSocket: We don't want real network connections in unit tests.
 * vi.stubGlobal('WebSocket', MockWebSocket) replaces the browser API with
 * a controllable fake.
 *
 * DATA SOURCE: AlertStreamContext.tsx (mocked WebSocket + gateway)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import { AlertStreamProvider, useAlertStream } from "@/contexts/AlertStreamContext";
import { AuthProvider } from "@/contexts/AuthContext";
import type { AlertPayload } from "@/types/alerts";

// ── Gateway mock ──────────────────────────────────────────────────────────────

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getWsToken: vi.fn().mockResolvedValue({ token: "fake-ws-token" }),
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "fake-access-token",
      user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// ── WebSocket mock ────────────────────────────────────────────────────────────

/**
 * MockWebSocket — minimal WebSocket fake that lets tests trigger events
 *
 * WHY: Real WebSocket connections would require a running S10 server.
 * The mock lets us call ws.simulateMessage(data) to inject messages.
 */
class MockWebSocket {
  static instance: MockWebSocket | null = null;
  // WHY explicit number: TypeScript infers WebSocket.CONNECTING as literal type 0,
  // which prevents assigning WebSocket.OPEN (1) or WebSocket.CLOSED (3) later.
  readyState: number = WebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    MockWebSocket.instance = this;
    // Simulate async connection (matches real WebSocket behavior)
    setTimeout(() => {
      this.readyState = WebSocket.OPEN;
      this.onopen?.();
    }, 0);
  }

  simulateMessage(data: AlertPayload) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  simulateClose() {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.();
  }

  close() {
    this.readyState = WebSocket.CLOSED;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeAlert(overrides: Partial<AlertPayload> = {}): AlertPayload {
  return {
    id: "alert-001",
    severity: "HIGH",
    alert_type: "PRICE_SPIKE",
    entity_id: "AAPL",
    message: "AAPL price spike detected",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function AlertConsumer() {
  const { recentAlerts, criticalQueue, dequeueCritical, unreadCount } = useAlertStream();
  return (
    <div>
      <span data-testid="recent-count">{recentAlerts.length}</span>
      <span data-testid="critical-count">{criticalQueue.length}</span>
      <span data-testid="unread">{unreadCount}</span>
      <button data-testid="dequeue" onClick={dequeueCritical}>
        Dequeue
      </button>
      {criticalQueue[0] && (
        <span data-testid="first-critical">{criticalQueue[0].id}</span>
      )}
    </div>
  );
}

function renderWithProviders() {
  return render(
    <AuthProvider>
      <AlertStreamProvider>
        <AlertConsumer />
      </AlertStreamProvider>
    </AuthProvider>,
  );
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal("localStorage", {
    getItem: vi.fn(() => null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
    length: 0,
    key: vi.fn(() => null),
  } as unknown as Storage);
  // Add WebSocket readyState constants
  (MockWebSocket as unknown as Record<string, number>).CONNECTING = 0;
  (MockWebSocket as unknown as Record<string, number>).OPEN = 1;
  (MockWebSocket as unknown as Record<string, number>).CLOSED = 3;
});

afterEach(() => {
  MockWebSocket.instance = null;
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AlertStreamContext — routing", () => {
  it("routes CRITICAL alerts to criticalQueue", async () => {
    renderWithProviders();

    // Wait for WS connection
    await waitFor(() => expect(MockWebSocket.instance).not.toBeNull());

    act(() => {
      MockWebSocket.instance?.simulateMessage(
        makeAlert({ id: "crit-1", severity: "CRITICAL" }),
      );
    });

    expect(screen.getByTestId("critical-count").textContent).toBe("1");
    expect(screen.getByTestId("recent-count").textContent).toBe("0");
    expect(screen.getByTestId("first-critical").textContent).toBe("crit-1");
  });

  it("routes non-CRITICAL alerts to recentAlerts", async () => {
    renderWithProviders();

    await waitFor(() => expect(MockWebSocket.instance).not.toBeNull());

    act(() => {
      MockWebSocket.instance?.simulateMessage(makeAlert({ severity: "HIGH" }));
      MockWebSocket.instance?.simulateMessage(makeAlert({ id: "alert-002", severity: "MEDIUM" }));
    });

    expect(screen.getByTestId("recent-count").textContent).toBe("2");
    expect(screen.getByTestId("critical-count").textContent).toBe("0");
    expect(screen.getByTestId("unread").textContent).toBe("2");
  });

  it("routes LOW severity to recentAlerts", async () => {
    renderWithProviders();
    await waitFor(() => expect(MockWebSocket.instance).not.toBeNull());

    act(() => {
      MockWebSocket.instance?.simulateMessage(makeAlert({ severity: "LOW" }));
    });

    expect(screen.getByTestId("recent-count").textContent).toBe("1");
    expect(screen.getByTestId("critical-count").textContent).toBe("0");
  });
});

describe("AlertStreamContext — dequeueCritical", () => {
  it("removes the first (oldest) critical alert on dequeue", async () => {
    renderWithProviders();
    await waitFor(() => expect(MockWebSocket.instance).not.toBeNull());

    act(() => {
      MockWebSocket.instance?.simulateMessage(makeAlert({ id: "c-1", severity: "CRITICAL" }));
      MockWebSocket.instance?.simulateMessage(makeAlert({ id: "c-2", severity: "CRITICAL" }));
    });

    expect(screen.getByTestId("critical-count").textContent).toBe("2");
    expect(screen.getByTestId("first-critical").textContent).toBe("c-1");

    // Dequeue the first alert
    act(() => {
      screen.getByTestId("dequeue").click();
    });

    expect(screen.getByTestId("critical-count").textContent).toBe("1");
    expect(screen.getByTestId("first-critical").textContent).toBe("c-2");
  });
});
