import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAlertStream } from "../src/hooks/useAlertStream";
import type { AlertPayload } from "../src/hooks/useAlertStream";

// ── Mock WebSocket ────────────────────────────────────────────────────────────

type WsEventHandler = (event: { data: string }) => void;

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  onmessage: WsEventHandler | null = null;
  onclose: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  readyState = 1; // OPEN

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  close() {
    this.readyState = 3; // CLOSED
  }

  /** Helper: simulate server pushing a message to this socket. */
  simulateMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function makeAlert(overrides: Partial<AlertPayload> = {}): AlertPayload {
  return {
    alert_id: "a1",
    entity_id: "e1",
    alert_type: "price_surge",
    topic: "test",
    occurred_at: "2026-04-10T10:00:00Z",
    severity: "low",
    ...overrides,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("useAlertStream", () => {
  it("critical_routes_to_queue", () => {
    const { result } = renderHook(() => useAlertStream("user-uuid-123"));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.simulateMessage(makeAlert({ severity: "critical" }));
    });

    expect(result.current.criticalQueue).toHaveLength(1);
    expect(result.current.criticalQueue[0].severity).toBe("critical");
    expect(result.current.recentAlerts).toHaveLength(0);
  });

  it("non_critical_routes_to_feed", () => {
    const { result } = renderHook(() => useAlertStream("user-uuid-123"));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.simulateMessage(makeAlert({ severity: "high" }));
    });

    expect(result.current.recentAlerts).toHaveLength(1);
    expect(result.current.recentAlerts[0].severity).toBe("high");
    expect(result.current.criticalQueue).toHaveLength(0);
  });

  it("ignores_ping_messages", () => {
    const { result } = renderHook(() => useAlertStream("user-uuid-123"));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.simulateMessage({ type: "ping" });
    });

    expect(result.current.criticalQueue).toHaveLength(0);
    expect(result.current.recentAlerts).toHaveLength(0);
  });

  it("dequeue_critical_removes_head", () => {
    const { result } = renderHook(() => useAlertStream("user-uuid-123"));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.simulateMessage(makeAlert({ alert_id: "a1", severity: "critical" }));
      ws.simulateMessage(makeAlert({ alert_id: "a2", severity: "critical" }));
    });

    expect(result.current.criticalQueue).toHaveLength(2);

    act(() => {
      result.current.dequeueCritical();
    });

    expect(result.current.criticalQueue).toHaveLength(1);
    expect(result.current.criticalQueue[0].alert_id).toBe("a2");
  });

  it("no_op_when_userId_is_null", () => {
    renderHook(() => useAlertStream(null));
    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it("closes_ws_on_unmount", () => {
    const { unmount } = renderHook(() => useAlertStream("user-uuid-123"));
    const ws = MockWebSocket.instances[0];
    expect(ws.readyState).toBe(1);

    unmount();

    expect(ws.readyState).toBe(3); // CLOSED
  });
});
