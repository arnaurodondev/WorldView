import { useAlertStream } from "../hooks/useAlertStream";
import { AlertCard } from "../components/alerts/AlertCard";

export function DashboardPage() {
  // userId is null until auth is wired — hook no-ops gracefully.
  const { recentAlerts } = useAlertStream(null);

  return (
    <div>
      <h2>Dashboard</h2>
      <p style={{ color: "var(--text-secondary)" }}>
        Overview of portfolio performance, market signals, and top news.
      </p>

      <section style={{ marginTop: "1.5rem" }}>
        <h3 style={{ marginBottom: "0.5rem" }}>Recent Alerts</h3>
        {recentAlerts.length === 0 ? (
          <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>
            No recent alerts.
          </p>
        ) : (
          <div
            style={{
              border: "1px solid var(--border)",
              borderRadius: "0.375rem",
              overflow: "hidden",
            }}
          >
            {recentAlerts.map((alert) => (
              <AlertCard key={alert.alert_id} alert={alert} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
