/**
 * app/(public)/status/page.tsx — Public platform status page
 *
 * WHY THIS EXISTS:
 *   Analysts who see an error in worldview need a public URL to check whether
 *   the platform is down or whether the problem is on their end. This page
 *   shows live uptime for the last 30 days, drawn from UptimeRobot monitors
 *   via a server-only Route Handler (UPTIMEROBOT_READONLY_API_KEY is never
 *   exposed to the client).
 *
 * ARCHITECTURE — why a Server Component (not "use client"):
 *   The page fetches /api/uptime from the same origin, which is the Route
 *   Handler in ./api/uptime/route.ts. Server Components can do this directly
 *   without needing React state or useEffect. The result is fully rendered
 *   HTML delivered to the browser, with no UptimeRobot API key in the JS bundle.
 *
 * DEFENSE-IN-DEPTH:
 *   The Route Handler strips sensitive fields. This page renders ONLY the
 *   whitelisted fields (monitor_id, friendly_name, component_label, status,
 *   custom_uptime_ratio, daily_buckets). It never spreads the response object
 *   directly into JSX — only explicit field references are rendered.
 *
 * PUBLIC ROUTE — no auth required:
 *   This page lives in the (public) route group, which has no auth middleware.
 *   Anyone can view it, which is the entire point of a status page.
 *
 * PLAN-0065 T-E-02, PRD-0034 §3 FR-T3-1
 */

// Server Component — runs on the server, no "use client" directive
import { CheckCircle2, AlertTriangle, XCircle, PauseCircle } from "lucide-react";
import type { MonitorSummary, Incident, UptimePayload, MonitorStatus } from "./components";
import { statusInfo } from "./components";

// ─── Data fetching ─────────────────────────────────────────────────────────

/**
 * Fetch uptime data from our own Route Handler.
 *
 * WHY fetch("/api/uptime") not UptimeRobot directly:
 *   The server-side Route Handler holds the API key and applies the whitelisted
 *   projection. This component never sees the key.
 */
async function fetchUptimeData(): Promise<UptimePayload> {
  // In server components, Next.js requires an absolute URL for fetch().
  // VERCEL_URL is set in production; fall back to localhost for local dev.
  const base = process.env.VERCEL_URL
    ? `https://${process.env.VERCEL_URL}`
    : "http://localhost:3000";

  try {
    const res = await fetch(`${base}/status/api/uptime`, {
      // 60-second cache — matches Route Handler revalidate
      next: { revalidate: 60 },
    });
    if (!res.ok) throw new Error(`uptime API ${res.status}`);
    return (await res.json()) as UptimePayload;
  } catch {
    // Fail gracefully — return empty data rather than crashing the page.
    // An analyst must always be able to load the page.
    return { monitors: [], incidents: [] };
  }
}

// ─── Sub-components ─────────────────────────────────────────────────────────

/** Icon for the current monitor status. */
function StatusIcon({ status }: { status: MonitorStatus }) {
  // WHY icons alongside color: color alone fails WCAG SC 1.4.1 (color not sole means)
  switch (status) {
    case 2:
      return <CheckCircle2 className="h-4 w-4 text-green-500" aria-hidden />;
    case 8:
      return <AlertTriangle className="h-4 w-4 text-amber-500" aria-hidden />;
    case 9:
      return <XCircle className="h-4 w-4 text-red-500" aria-hidden />;
    default:
      return <PauseCircle className="h-4 w-4 text-zinc-500" aria-hidden />;
  }
}

/**
 * 30-day daily uptime strip — one cell per day, green=up, red=down.
 *
 * WHY 30 cells: standard industry pattern (Atlassian Statuspage, Instatus).
 * Gives analysts a quick "has this been flaky recently" visual at a glance.
 */
function DayStrip({ buckets }: { buckets: MonitorSummary["daily_buckets"] }) {
  return (
    // aria-label gives screen readers the full context
    <div
      className="flex gap-0.5"
      aria-label={`30-day uptime history — ${buckets.filter((b) => b.up).length} of 30 days up`}
    >
      {buckets.map((bucket) => (
        <div
          key={bucket.date}
          title={`${bucket.date}: ${bucket.up ? "up" : "down"}`}
          aria-label={`${bucket.date} ${bucket.up ? "up" : "down"}`}
          className={[
            "h-5 w-1.5 rounded-sm",
            bucket.up ? "bg-green-500/80" : "bg-red-500/80",
          ].join(" ")}
        />
      ))}
    </div>
  );
}

/** Single monitor pill — label, status badge, 30-day strip, uptime %. */
function MonitorPill({ monitor }: { monitor: MonitorSummary }) {
  // Render ONLY whitelisted fields — never spread monitor into JSX.
  const { label, colorClass } = statusInfo(monitor.status);

  return (
    <div className="rounded-[2px] border border-border/60 bg-card/60 p-4">
      {/* Top row: component label + status badge */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <StatusIcon status={monitor.status} />
          {/* Use component_label (Sam-facing), NOT friendly_name (internal) */}
          <span className="text-sm font-medium text-foreground">
            {monitor.component_label}
          </span>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium text-white ${colorClass}`}
        >
          {label}
        </span>
      </div>

      {/* 30-day strip */}
      <div className="mt-3">
        <DayStrip buckets={monitor.daily_buckets} />
      </div>

      {/* 30-day uptime % */}
      <div className="mt-1.5 text-right text-[11px] text-muted-foreground">
        {parseFloat(monitor.custom_uptime_ratio).toFixed(2)}% uptime (30d)
      </div>
    </div>
  );
}

/**
 * Incident banner — shown above the monitor grid when incidents.json is non-empty.
 *
 * WHY in-tree incidents.json (not a CMS): a 15-line file commit is the cheapest
 * way to publish "AI brief generation degraded — investigating" to Sam without
 * standing up a CMS. The file is edited by hand during real incidents.
 */
function IncidentBanner({ incidents }: { incidents: Incident[] }) {
  // Only show ongoing incidents (resolved_at === null) or resolved in the last 24h
  const activeIncidents = incidents.filter((inc) => {
    if (!inc.resolved_at) return true; // ongoing
    const resolvedMs = new Date(inc.resolved_at).getTime();
    return Date.now() - resolvedMs < 86_400_000; // resolved within 24h
  });

  if (activeIncidents.length === 0) return null;

  return (
    <div role="alert" aria-live="assertive" className="mb-6 space-y-2">
      {activeIncidents.map((inc, i) => {
        // Map severity to a background color
        const bg =
          inc.severity === "critical"
            ? "bg-red-950/50 border-red-500/40"
            : inc.severity === "warn"
              ? "bg-amber-950/50 border-amber-500/40"
              : "bg-blue-950/50 border-blue-500/40";
        const icon =
          inc.severity === "critical" ? "🔴" : inc.severity === "warn" ? "🟡" : "🔵";

        return (
          <div
            key={i}
            className={`rounded-[2px] border px-4 py-3 text-sm ${bg}`}
          >
            <div className="flex items-baseline gap-2">
              <span aria-hidden>{icon}</span>
              <strong className="text-foreground">{inc.title}</strong>
              <span className="text-xs text-muted-foreground">
                {inc.resolved_at ? "Resolved" : "Ongoing"} ·{" "}
                {new Date(inc.started_at).toUTCString()}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function StatusPage() {
  // Data is fetched server-side — no useEffect, no client state.
  const data = await fetchUptimeData();

  // Overall system status = worst monitor status
  // 9=down > 8=degraded > 0=paused > 2=up
  const worstStatus: MonitorStatus = data.monitors.reduce<MonitorStatus>(
    (worst, m) => {
      const priority: Record<MonitorStatus, number> = { 9: 4, 8: 3, 0: 2, 2: 1 };
      return (priority[m.status as MonitorStatus] ?? 0) > (priority[worst] ?? 0)
        ? (m.status as MonitorStatus)
        : worst;
    },
    2, // default: operational
  );

  const { label: overallLabel } = statusInfo(worstStatus);

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      {/* Page header */}
      <div className="mb-8 text-center">
        <h1 className="text-xl font-semibold text-foreground">System Status</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Worldview platform uptime — last 30 days
        </p>
        {/* Overall status badge */}
        <div className="mt-4 flex items-center justify-center gap-2">
          <StatusIcon status={worstStatus} />
          <span
            className="text-base font-medium text-foreground"
            // aria-live so screen readers announce status on page load
            aria-live="polite"
          >
            {overallLabel}
          </span>
        </div>
      </div>

      {/* Incident banners (if any) */}
      <IncidentBanner incidents={data.incidents} />

      {/* Monitor pills grid */}
      {data.monitors.length === 0 ? (
        <p className="text-center text-sm text-muted-foreground">
          No monitors configured yet.
        </p>
      ) : (
        <div className="space-y-3">
          {data.monitors.map((monitor) => (
            // Render ONLY the whitelisted MonitorSummary shape — no spread
            <MonitorPill key={monitor.monitor_id} monitor={monitor} />
          ))}
        </div>
      )}

      {/* Footer note */}
      <p className="mt-8 text-center text-[11px] text-muted-foreground">
        Monitored by{" "}
        <span className="font-medium">UptimeRobot</span> · Refreshes every 60 s
      </p>
    </main>
  );
}
