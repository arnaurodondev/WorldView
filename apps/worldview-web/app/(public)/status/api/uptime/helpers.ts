/**
 * app/(public)/status/api/uptime/helpers.ts — pure helper functions
 *
 * WHY SEPARATE FROM route.ts:
 *   The Route Handler itself uses Next.js server APIs (NextResponse, next/server)
 *   that require the full Next.js runtime to import. Extracting the pure logic
 *   here allows Vitest to test the security-critical projection and incident
 *   reading without needing to mock the entire Next.js framework.
 *
 * Exported from route.ts for test access — these are the functions that
 * enforce the security contract (whitelisted projection, fail-open incidents).
 *
 * PLAN-0065 T-E-02, PRD-0034 §3 FR-T3-1 §9 (security)
 */

import * as fs from "fs";
import * as path from "path";
import { resolveComponentLabel } from "../../components";
import type { MonitorSummary, Incident, MonitorStatus } from "../../components";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Shape of a single monitor in UptimeRobot's getMonitors response.
 *  Exported so tests can build realistic fixtures without hard-coding fields.
 */
export interface RawMonitor {
  id: number;
  friendly_name: string;
  status: number;
  custom_uptime_ratio?: string;
  logs?: Array<{
    type: number; // 1=down, 2=up, 98=paused, 99=started
    datetime: number; // unix timestamp (seconds)
    duration: number; // seconds the state lasted
  }>;
  // Sensitive fields that MUST be stripped in projectMonitor()
  url?: string;
  alert_contacts?: unknown[];
  interval?: number;
  keyword_value?: string;
  keyword_type?: number;
  last_error_time?: number;
  [key: string]: unknown;
}

// ─── Daily bucket builder ─────────────────────────────────────────────────────

/**
 * Convert UptimeRobot change logs into a 30-day daily bucket array.
 *
 * WHY DERIVE LOCALLY: UptimeRobot's getMonitors endpoint doesn't return
 * per-day buckets directly. We build a 30-day calendar where each bucket
 * is `up` if there was no down (type=1) log overlapping that UTC day.
 */
export function buildDailyBuckets(
  logs: RawMonitor["logs"],
): Array<{ date: string; up: boolean }> {
  const buckets: Array<{ date: string; up: boolean }> = [];
  const now = Date.now();

  for (let i = 29; i >= 0; i--) {
    const dayStart = now - i * 86_400_000;
    const dateStr = new Date(dayStart).toISOString().slice(0, 10);

    if (!logs || logs.length === 0) {
      buckets.push({ date: dateStr, up: true });
      continue;
    }

    const dayEnd = dayStart + 86_400_000;
    const hasDowntime = logs.some((log) => {
      if (log.type !== 1) return false;
      const logStart = log.datetime * 1000;
      const logEnd = logStart + log.duration * 1000;
      return logStart < dayEnd && logEnd > dayStart;
    });

    buckets.push({ date: dateStr, up: !hasDowntime });
  }

  return buckets;
}

// ─── Whitelisted projection ───────────────────────────────────────────────────

/**
 * Whitelisted projection of a raw UptimeRobot monitor.
 *
 * Returns ONLY the fields that are safe to expose to the client. All other
 * fields (url, alert_contacts, interval, keyword_value, etc.) are stripped.
 * This is the canonical strip point; the page component applies a second strip
 * as defense-in-depth.
 *
 * WHY explicit field list (not Object.pick or spread): an explicit list makes
 * it impossible to accidentally forward a new field that UptimeRobot adds to
 * their API response. The security contract is captured in code, not docs.
 */
export function projectMonitor(m: RawMonitor): MonitorSummary {
  return {
    monitor_id: m.id,
    friendly_name: m.friendly_name,
    component_label: resolveComponentLabel(m.friendly_name),
    status: (m.status as MonitorStatus) ?? 0,
    custom_uptime_ratio: m.custom_uptime_ratio ?? "0",
    daily_buckets: buildDailyBuckets(m.logs),
    // EXPLICITLY NOT included (strip list):
    //   url, alert_contacts, interval, keyword_value, keyword_type,
    //   last_error_time, create_datetime, monitor_type, sub_type,
    //   http_method, http_auth_type, http_username, http_password,
    //   http_ignore_ssl_errors, response_times_minimum, ...
  };
}

// ─── Incident file reader ─────────────────────────────────────────────────────

/**
 * Read incidents.json synchronously from a given path.
 *
 * WHY FAIL-OPEN: incidents.json is an optional in-tree file. In fresh
 * checkouts or new environments it won't exist — that's fine. The status
 * page must always render, even if the incident banner is unavailable.
 *
 * WHY SYNC (not async): Next.js Server Component rendering is already async;
 * a sync fs read avoids extra async plumbing in the route handler for a file
 * that is at most a few KB committed to the repo.
 *
 * @param filePath Absolute path to incidents.json (injectable for testing)
 */
export function readIncidentsSync(filePath: string): Incident[] {
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as Incident[];
  } catch {
    // ENOENT (file missing), EISDIR, JSON parse error — all fail-open
    return [];
  }
}

/** Default incidents.json path — relative to Next.js project root (process.cwd()). */
export function defaultIncidentsPath(): string {
  return path.join(process.cwd(), "app/(public)/status/incidents.json");
}
