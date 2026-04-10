import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAlertStream, MAX_CRITICAL_QUEUE } from "../src/hooks/useAlertStream";
import type { AlertPayload } from "../src/hooks/useAlertStream";

// ── Mock WebSocket ────────────────────────────────────────────────────────────

type WsEventHandler = (event: { data: string }) => void;

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  onopen: (() => void) | null = null;
  onmessage: WsEventHandler | null = null;
  onclose: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  readyState = 1; // OPEN

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  close() {
    this.readyState = 3; // CLOSED
    this.onclose?.();
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

  it("onclose_triggers_reconnect_after_delay", () => {
    vi.useFakeTimers();
    try {
      renderHook(() => useAlertStream("user-uuid-123"));
      expect(MockWebSocket.instances).toHaveLength(1);

      const ws1 = MockWebSocket.instances[0];
      // Simulate server closing the connection (without going through cleanup)
      act(() => {
        ws1.readyState = 3;
        ws1.onclose?.();
      });

      // No new WS yet — reconnect is scheduled after 1s delay
      expect(MockWebSocket.instances).toHaveLength(1);

      act(() => {
        vi.advanceTimersByTime(1000);
      });

      // After the delay a new WS is created
      expect(MockWebSocket.instances).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("onerror_calls_close_and_does_not_crash", () => {
    renderHook(() => useAlertStream("user-uuid-123"));
    const ws = MockWebSocket.instances[0];

    // Should not throw; onerror delegates to ws.close()
    expect(() => {
      act(() => {
        ws.onerror?.(new Event("error"));
      });
    }).not.toThrow();

    expect(ws.readyState).toBe(3); // CLOSED by onerror handler
  });

  it("critical_queue_capped_at_MAX_CRITICAL_QUEUE", () => {
    const { result } = renderHook(() => useAlertStream("user-uuid-123"));
    const ws = MockWebSocket.instances[0];

    const total = MAX_CRITICAL_QUEUE + 5; // 15 alerts

    act(() => {
      for (let i = 0; i < total; i++) {
        ws.simulateMessage(
          makeAlert({ alert_id: `a${i}`, severity: "critical" }),
        );
      }
    });

    expect(result.current.criticalQueue).toHaveLength(MAX_CRITICAL_QUEUE);
    // Most recent 10 should be kept (a5 … a14)
    expect(result.current.criticalQueue[0].alert_id).toBe("a5");
    expect(result.current.criticalQueue[MAX_CRITICAL_QUEUE - 1].alert_id).toBe(
      `a${total - 1}`,
    );
  });
});
