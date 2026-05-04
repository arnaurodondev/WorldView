/**
 * app/(public)/status/api/uptime/route.ts — server-only UptimeRobot proxy
 *
 * WHY A SERVER-ONLY ROUTE HANDLER (not client-side fetch):
 *   The UptimeRobot read-only API key, even though monitor-scoped, must never
 *   appear in browser network logs. Exposing it allows:
 *     (a) rate-limit exhaustion on the free tier
 *     (b) enumeration of alert-contact PII from the monitor config
 *     (c) extraction of internal probe paths or staging hostnames
 *   This Route Handler is the ONLY place the key is read. The key is NEVER set
 *   as NEXT_PUBLIC_* (which would bundle it into client JS).
 *
 * SECURITY: the whitelisted projection is applied in projectMonitor() (helpers.ts).
 * The page component applies a second strip as defense-in-depth.
 *
 * CACHE: 60-second revalidation so we don't hammer UptimeRobot's free quota.
 *
 * PLAN-0065 T-E-02, PRD-0034 §3 FR-T3-1
 */

import { NextResponse } from "next/server";
import {
  projectMonitor,
  readIncidentsSync,
  defaultIncidentsPath,
  type RawMonitor,
} from "./helpers";
import type { UptimePayload } from "../../components";

// 60-second server-side cache — revalidate at most once per minute.
export const revalidate = 60;

export async function GET(): Promise<NextResponse> {
  const apiKey = process.env.UPTIMEROBOT_READONLY_API_KEY;

  // In production, a missing key is a configuration error.
  // In development/test, return a stub so the page renders without a real account.
  if (!apiKey) {
    if (process.env.NODE_ENV === "production") {
      return NextResponse.json(
        { error: "status page misconfigured" },
        { status: 500 },
      );
    }

    // Development stub — one "up" monitor so developers see the page layout
    const stub: UptimePayload = {
      monitors: [
        {
          monitor_id: 0,
          friendly_name: "API Gateway — liveness (dev stub)",
          component_label: "Platform",
          status: 2,
          custom_uptime_ratio: "100.000",
          daily_buckets: Array.from({ length: 30 }, (_, i) => ({
            date: new Date(Date.now() - (29 - i) * 86_400_000)
              .toISOString()
              .slice(0, 10),
            up: true,
          })),
        },
      ],
      incidents: readIncidentsSync(defaultIncidentsPath()),
    };
    return NextResponse.json(stub);
  }

  // Call UptimeRobot getMonitors API
  let rawMonitors: RawMonitor[] = [];
  try {
    const res = await fetch("https://api.uptimerobot.com/v2/getMonitors", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        api_key: apiKey,
        format: "json",
        custom_uptime_ratios: "30",
        logs: "1", // needed for buildDailyBuckets()
      }).toString(),
      next: { revalidate: 60 },
    });

    if (!res.ok) {
      return NextResponse.json({ error: "upstream error" }, { status: 502 });
    }

    const body = (await res.json()) as {
      stat: string;
      monitors?: RawMonitor[];
    };

    if (body.stat !== "ok" || !Array.isArray(body.monitors)) {
      return NextResponse.json({ error: "unexpected response shape" }, { status: 502 });
    }

    rawMonitors = body.monitors;
  } catch {
    return NextResponse.json({ error: "upstream unreachable" }, { status: 502 });
  }

  const payload: UptimePayload = {
    monitors: rawMonitors.map(projectMonitor),
    incidents: readIncidentsSync(defaultIncidentsPath()),
  };

  return NextResponse.json(payload);
}
