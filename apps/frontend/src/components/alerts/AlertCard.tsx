import { SeverityBadge } from "./SeverityBadge";
import type { AlertPayload } from "../../hooks/useAlertStream";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AlertCard({ alert }: { alert: AlertPayload }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        padding: "0.5rem 0.75rem",
        borderBottom: "1px solid var(--border)",
        fontSize: "0.875rem",
      }}
    >
      <SeverityBadge severity={alert.severity} />
      <span style={{ fontWeight: 500 }}>{alert.alert_type}</span>
      <span
        style={{ color: "var(--text-secondary)", fontFamily: "monospace" }}
        title={alert.entity_id}
      >
        {alert.entity_id.slice(0, 8)}…
      </span>
      <span style={{ marginLeft: "auto", color: "var(--text-secondary)" }}>
        {formatTime(alert.occurred_at)}
      </span>
    </div>
  );
}
