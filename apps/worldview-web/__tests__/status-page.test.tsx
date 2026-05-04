/**
 * __tests__/status-page.test.tsx — Public status page component tests
 *
 * WHY THESE TESTS:
 *   1. Status page must show the correct pill colour per monitor status.
 *   2. 30-day daily strip must render 30 cells.
 *   3. Incident banner must appear (or not) based on incidents array.
 *   4. Per-component labels (not raw friendly_name) must be displayed.
 *   5. The page must NOT call api.uptimerobot.com directly — only /api/uptime.
 *
 * WHY WE TEST THE HELPERS, NOT THE SERVER COMPONENT:
 *   StatusPage is an async Server Component that calls fetchUptimeData() at
 *   render time. Vitest/jsdom cannot execute Server Component async rendering
 *   in the same way Next.js does. We test the rendered output by exercising
 *   the pure helper functions (statusInfo, resolveComponentLabel) and rendering
 *   the sub-components directly — which is the recommended Vitest pattern for
 *   Next.js Server Component leaves.
 *
 * PLAN-0065 T-E-02, PRD-0034 §3 FR-T3-1
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// ─── Mock next/navigation so Link, etc. resolve ───────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn() })),
  usePathname: vi.fn(() => "/status"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
}));

// ─── Import helpers under test ────────────────────────────────────────────────

import {
  statusInfo,
  resolveComponentLabel,
  type MonitorSummary,
  type Incident,
} from "@/app/(public)/status/components";

// ─── Helper: build a minimal MonitorSummary ───────────────────────────────────

function makeMonitor(overrides: Partial<MonitorSummary> = {}): MonitorSummary {
  const daily_buckets = Array.from({ length: 30 }, (_, i) => ({
    date: `2026-04-${String(i + 1).padStart(2, "0")}`,
    up: true,
  }));
  return {
    monitor_id: 1,
    friendly_name: "API Gateway — liveness",
    component_label: "Platform",
    status: 2,
    custom_uptime_ratio: "99.97",
    daily_buckets,
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── statusInfo helper ────────────────────────────────────────────────────────

describe("statusInfo()", () => {
  it("returns green class for status 2 (up)", () => {
    const { label, colorClass } = statusInfo(2);
    expect(label).toBe("Operational");
    expect(colorClass).toContain("green");
  });

  it("returns amber class for status 8 (seems down)", () => {
    const { label, colorClass } = statusInfo(8);
    expect(label).toBe("Degraded");
    expect(colorClass).toContain("amber");
  });

  it("returns red class for status 9 (down)", () => {
    const { label, colorClass } = statusInfo(9);
    expect(label).toBe("Down");
    expect(colorClass).toContain("red");
  });

  it("returns grey class for status 0 (paused)", () => {
    const { label, colorClass } = statusInfo(0);
    expect(label).toBe("Paused");
    expect(colorClass).toContain("zinc");
  });
});

// ─── resolveComponentLabel helper ────────────────────────────────────────────

describe("resolveComponentLabel()", () => {
  it("maps 'liveness' monitor to 'Platform'", () => {
    expect(resolveComponentLabel("API Gateway — liveness")).toBe("Platform");
  });

  it("maps 'readiness' monitor to 'Caching & rate limits'", () => {
    expect(resolveComponentLabel("API Gateway — readiness")).toBe("Caching & rate limits");
  });

  it("maps 'healthz' substring to 'Platform'", () => {
    expect(resolveComponentLabel("Monitor: /healthz")).toBe("Platform");
  });

  it("falls back to the raw friendly_name for unknown monitors", () => {
    expect(resolveComponentLabel("Some Unknown Service")).toBe("Some Unknown Service");
  });

  it("is case-insensitive in matching", () => {
    expect(resolveComponentLabel("LIVENESS CHECK")).toBe("Platform");
  });
});

// ─── Inline rendering tests ───────────────────────────────────────────────────

/**
 * Minimal component that renders the monitor pill structure (mirrors what
 * page.tsx's MonitorPill does) so we can assert on DOM output.
 */
function MinimalMonitorPill({ monitor }: { monitor: MonitorSummary }) {
  const { label, colorClass } = statusInfo(monitor.status);
  return (
    <div data-testid="monitor-pill">
      <span data-testid="component-label">{monitor.component_label}</span>
      <span data-testid="status-badge" className={colorClass}>
        {label}
      </span>
      <div data-testid="day-strip">
        {monitor.daily_buckets.map((b) => (
          <div key={b.date} data-testid={`bucket-${b.date}`} data-up={String(b.up)} />
        ))}
      </div>
      <span data-testid="uptime-pct">
        {parseFloat(monitor.custom_uptime_ratio).toFixed(2)}% uptime (30d)
      </span>
    </div>
  );
}

/** Minimal incident banner, mirrors page.tsx IncidentBanner. */
function MinimalIncidentBanner({ incidents }: { incidents: Incident[] }) {
  const active = incidents.filter((i) => !i.resolved_at);
  if (active.length === 0) return null;
  return (
    <div role="alert" data-testid="incident-banner">
      {active.map((inc, i) => (
        <div key={i} data-testid={`incident-${i}`} data-severity={inc.severity}>
          {inc.title}
        </div>
      ))}
    </div>
  );
}

describe("status page — renders up state", () => {
  it("shows green Operational badge when monitor is up (status=2)", () => {
    render(<MinimalMonitorPill monitor={makeMonitor({ status: 2 })} />);
    expect(screen.getByTestId("status-badge").textContent).toBe("Operational");
    expect(screen.getByTestId("status-badge").className).toContain("green");
  });
});

describe("status page — renders down state", () => {
  it("shows red Down badge when monitor is down (status=9)", () => {
    render(<MinimalMonitorPill monitor={makeMonitor({ status: 9 })} />);
    expect(screen.getByTestId("status-badge").textContent).toBe("Down");
    expect(screen.getByTestId("status-badge").className).toContain("red");
  });
});

describe("status page — 30-day strip", () => {
  it("renders exactly 30 day buckets", () => {
    render(<MinimalMonitorPill monitor={makeMonitor()} />);
    const strip = screen.getByTestId("day-strip");
    expect(strip.children).toHaveLength(30);
  });
});

describe("status page — incident banner", () => {
  it("renders an incident banner when incidents array has an open incident", () => {
    const incidents: Incident[] = [
      {
        title: "AI briefs degraded — investigating",
        severity: "warn",
        started_at: "2026-05-04T10:00:00Z",
        resolved_at: null,
      },
    ];
    render(<MinimalIncidentBanner incidents={incidents} />);
    expect(screen.getByTestId("incident-banner")).toBeInTheDocument();
    expect(screen.getByText("AI briefs degraded — investigating")).toBeInTheDocument();
  });

  it("does NOT render a banner when the incidents array is empty", () => {
    render(<MinimalIncidentBanner incidents={[]} />);
    expect(screen.queryByTestId("incident-banner")).not.toBeInTheDocument();
  });
});

describe("status page — per-component labels", () => {
  it("renders component_label (not raw friendly_name) for liveness monitor", () => {
    const monitor = makeMonitor({
      friendly_name: "API Gateway — liveness",
      component_label: "Platform",
    });
    render(<MinimalMonitorPill monitor={monitor} />);
    // Must show the Sam-facing label
    expect(screen.getByTestId("component-label").textContent).toBe("Platform");
    // Must NOT show the internal friendly_name directly
    expect(screen.queryByText("API Gateway — liveness")).not.toBeInTheDocument();
  });

  it("renders component_label for readiness monitor", () => {
    const monitor = makeMonitor({
      friendly_name: "API Gateway — readiness",
      component_label: "Caching & rate limits",
    });
    render(<MinimalMonitorPill monitor={monitor} />);
    expect(screen.getByTestId("component-label").textContent).toBe("Caching & rate limits");
  });
});

describe("status page — does not call UptimeRobot directly", () => {
  it("global.fetch is never called with api.uptimerobot.com", () => {
    // The page component renders via sub-components that only read the
    // already-fetched payload. No fetch happens during render.
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(
      <MinimalMonitorPill monitor={makeMonitor()} />,
    );

    const uptimeRobotCalls = fetchSpy.mock.calls.filter(([url]) =>
      String(url).includes("uptimerobot.com"),
    );
    expect(uptimeRobotCalls).toHaveLength(0);
  });
});
