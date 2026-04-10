import { useState, useEffect, useCallback } from "react"

export type AlertSeverity = "low" | "medium" | "high" | "critical"

export interface AlertPayload {
  alert_id: string;
  entity_id: string;
  alert_type: string;
  topic: string;
  occurred_at: string;
  severity: AlertSeverity;
}

const MAX_CRITICAL_QUEUE = 10

/**
 * Manages a WebSocket connection to the S10 alert stream.
 * Routes CRITICAL alerts to a FIFO queue (for FlashOverlay) and
 * non-critical alerts to a capped recent-alerts feed.
 *
 * Reconnects automatically with exponential backoff (1s → 30s cap) on
 * close/error.  The `cancelled` flag prevents reconnect after unmount.
 */
export function useAlertStream(userId: string | null): {
  criticalQueue: AlertPayload[];
  recentAlerts: AlertPayload[];
  dequeueCritical: () => void;
} {
  const [criticalQueue, setCriticalQueue] = useState<AlertPayload[]>([]);
  const [recentAlerts, setRecentAlerts] = useState<AlertPayload[]>([]);

  useEffect(() => {
    if (!userId) return;

    let cancelled = false;
    let retryDelay = 1000;
    let currentWs: WebSocket | null = null;

    function connect() {
      if (cancelled) return;
      const ws = new WebSocket(`/api/v1/alerts/stream?user_id=${userId}`);
      currentWs = ws;

      ws.onopen = () => {
        retryDelay = 1000; // reset backoff on successful connect
      };

      ws.onmessage = (event: MessageEvent) => {
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(event.data as string) as Record<string, unknown>;
        } catch {
          // Malformed frame (e.g. proxy keepalive, partial flush) — skip silently.
          return;
        }
        // Ignore heartbeat pings
        if (data["type"] === "ping") return;

        const alert = data as unknown as AlertPayload;
        if (alert.severity === "critical") {
          setCriticalQueue((q) => {
            const next = [...q, alert];
            return next.length > MAX_CRITICAL_QUEUE
              ? next.slice(next.length - MAX_CRITICAL_QUEUE)
              : next;
          });
        } else {
          setRecentAlerts((prev) => [alert, ...prev].slice(0, 50));
        }
      };

      ws.onclose = () => {
        if (!cancelled) {
          setTimeout(connect, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 30_000);
        }
      };

      ws.onerror = () => {
        ws.close(); // triggers onclose which handles retry
      };
    }

    connect();

    return () => {
      cancelled = true;
      currentWs?.close();
    };
  }, [userId]);

  const dequeueCritical = useCallback(
    () => setCriticalQueue((q) => q.slice(1)),
    [],
  );

  return { criticalQueue, recentAlerts, dequeueCritical };
}

export { MAX_CRITICAL_QUEUE };
