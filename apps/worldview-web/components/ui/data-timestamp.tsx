/**
 * components/ui/data-timestamp.tsx — Data freshness indicator
 *
 * WHY THIS EXISTS: Almost every dashboard widget shows when its data was
 * last updated. The age of that data is itself a signal:
 *   - <5 minutes  — fresh, all green (positive token)
 *   - 5–30 min    — slightly stale, amber/warning
 *   - 30 min–1h   — stale, muted
 *   - >1h         — very stale, muted (no extra emphasis)
 *
 * Centralising the relative-time formatting + colour coding here means every
 * widget shows freshness consistently, and updating the thresholds (e.g. for
 * a faster data feed) is a single-file change.
 *
 * COMPLEMENTS: components/ui/StaleBadge.tsx renders a fixed "STALE" badge
 * when data is past a hard threshold; DataTimestamp is the always-on label
 * that conveys exact age.
 */

"use client";
// WHY "use client": the relative-time string must update over time (a 30s
// interval re-render keeps "2m ago" → "3m ago" honest). That requires
// useEffect + setInterval which only run client-side.

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface DataTimestampProps {
  /**
   * The timestamp the data was produced at. Accepts Date or any string
   * Date can parse (ISO 8601 recommended).
   */
  timestamp: Date | string;
  /**
   * Display style.
   * - "relative" (default) — "2m ago" / "1h ago" / "Just now"
   * - "absolute"           — "2026-04-28 10:32 UTC"
   */
  format?: "relative" | "absolute";
  /** Optional extra Tailwind classes for the wrapper. */
  className?: string;
}

// ── Internal helpers ──────────────────────────────────────────────────────────

/**
 * formatRelative — human-readable age string.
 * WHY thresholds: <30s "Just now" reads cleaner than "0m ago"; minutes/hours
 * are truncated (not rounded up) so freshness is never overstated.
 */
function formatRelative(diffMs: number): string {
  // Negative diff (clock skew) → treat as just-now to avoid showing "in 3s".
  if (diffMs < 30_000) return "Just now";
  const min = Math.floor(diffMs / 60_000);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(diffMs / 3_600_000);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(diffMs / 86_400_000);
  return `${day}d ago`;
}

/**
 * formatAbsolute — "YYYY-MM-DD HH:MM UTC" — short, sortable, deterministic.
 */
function formatAbsolute(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  );
}

/** Pick the colour token for a given age in milliseconds. */
function colourFor(diffMs: number): string {
  if (diffMs < 5 * 60_000) return "text-positive";
  if (diffMs < 30 * 60_000) return "text-warning";
  if (diffMs < 60 * 60_000) return "text-muted-foreground";
  return "text-muted-foreground/70";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function DataTimestamp({
  timestamp,
  format = "relative",
  className,
}: DataTimestampProps): ReactNode {
  // Normalise incoming value once. Date objects are passed through; strings
  // go through the Date constructor (which handles ISO 8601 correctly).
  const dateObj = timestamp instanceof Date ? timestamp : new Date(timestamp);

  // WHY tick state: we re-render once a minute so "2m ago" → "3m ago"
  // updates without parent intervention. 30s gives sub-minute granularity
  // around the "Just now → 1m" boundary.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (format !== "relative") return;
    const id = window.setInterval(() => setTick((n) => n + 1), 30_000);
    return () => window.clearInterval(id);
  }, [format]);

  // Compute age + label every render — cheap enough that memo would just add
  // boilerplate.
  const diffMs = Date.now() - dateObj.getTime();
  const label =
    format === "absolute" ? formatAbsolute(dateObj) : formatRelative(diffMs);
  const colour = colourFor(diffMs);

  return (
    <span
      // WHY title attr with absolute time: relative format hides the exact
      // timestamp; users can hover for the exact UTC value when they need it.
      title={formatAbsolute(dateObj)}
      className={cn(
        "font-mono text-[10px] tabular-nums",
        colour,
        className,
      )}
    >
      {label}
    </span>
  );
}
