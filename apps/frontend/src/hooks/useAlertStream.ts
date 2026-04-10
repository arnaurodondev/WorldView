import { useState, useEffect, useCallback } from "react";

export type AlertSeverity = "low" | "medium" | "high" | "critical";

export interface AlertPayload {
  alert_id: string;
  entity_id: string;
  alert_type: string;
  topic: string;
  occurred_at: string;
  severity: AlertSeverity;
}

/**
 * Manages a WebSocket connection to the S10 alert stream.
 * Routes CRITICAL alerts to a FIFO queue (for FlashOverlay) and
 * non-critical alerts to a capped recent-alerts feed.
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

    const ws = new WebSocket(`/api/v1/alerts/stream?user_id=${userId}`);

    ws.onmessage = (event: MessageEvent) => {
      const data = JSON.parse(event.data as string) as Record<string, unknown>;
      // Ignore heartbeat pings
      if (data["type"] === "ping") return;

      const alert = data as unknown as AlertPayload;
      if (alert.severity === "critical") {
        setCriticalQueue((q) => [...q, alert]);
      } else {
        setRecentAlerts((prev) => [alert, ...prev].slice(0, 50));
      }
    };

    return () => ws.close();
  }, [userId]);

  const dequeueCritical = useCallback(
    () => setCriticalQueue((q) => q.slice(1)),
    [],
  );

  return { criticalQueue, recentAlerts, dequeueCritical };
}
