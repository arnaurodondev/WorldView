/**
 * lib/hooks/useFormattedTimestamp.ts — Unified timestamp formatter.
 *
 * WHY THIS EXISTS (FR-10.7):
 * Three separate inline implementations existed for relative time ("2h ago"),
 * absolute timestamps, and short dates. They used different approaches
 * (string manipulation vs Date methods vs Intl) producing inconsistent output.
 * A single hook:
 *   1. Enforces the timestamp conventions from DESIGN_SYSTEM §6.4.
 *   2. Can be extended (e.g. live relative-time updates) in one place.
 *   3. Returns "—" consistently for null/undefined instead of "Invalid Date".
 *
 * USAGE:
 *   const label = useFormattedTimestamp("2026-05-19T14:32:00Z", "relative"); // "2h ago"
 *   const label = useFormattedTimestamp(someDate, "absolute"); // "May 19, 2026, 14:32"
 *   const label = useFormattedTimestamp(null, "short"); // "—"
 *
 * WHY a hook (not a plain function):
 * The current implementation is pure (no subscriptions) so it could be a
 * plain function. Using `use*` naming reserves the ability to add an internal
 * `useInterval` for live relative-time updates (e.g. update "2m ago" every
 * minute) without changing every call site.
 *
 * NOTE: Deliberate no external date library. date-fns / dayjs would add
 * ~15KB to the bundle for formatting logic we can express in 50 lines. The
 * implementation covers the narrow set of formats used in the UI (§6.4).
 */

"use client";
// WHY "use client": useEffect + useState for live relative-time ticking require
// the browser runtime. Server components cannot call this hook.

import { useState, useEffect } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

export type TimestampFormat = "relative" | "absolute" | "short";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Parse any supported timestamp input into a Date (or null if invalid). */
function toDate(value: string | Date | null | undefined): Date | null {
  if (value == null) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  // WHY Date constructor (not manual parsing): handles ISO 8601 strings,
  // epoch milliseconds as strings, and most date formats. Manual parsing
  // would need to cover too many edge cases.
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * formatRelative — produce a human-readable "time ago" string.
 *
 * Thresholds (DESIGN_SYSTEM §6.4 "Article card, event list"):
 *   < 1 min  → "just now"
 *   < 1 hr   → "Nm ago"
 *   < 24 hr  → "Nh ago"
 *   < 7 days → "Nd ago"
 *   otherwise → short absolute (e.g. "May 12")
 *
 * WHY NOT Intl.RelativeTimeFormat: it requires knowing the correct unit
 * (seconds/minutes/hours/days), which means we still need to compute the
 * thresholds ourselves. At that point, Intl.RelativeTimeFormat adds only
 * localisation overhead for a UI that targets English-only (finance terminals
 * use English regardless of locale — PRD-0027 §2).
 */
function formatRelative(date: Date): string {
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.floor(diffMs / 1_000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffSec < 60) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  // Beyond 7 days: fall back to "Mon DD" — still readable without the year.
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * formatAbsolute — full date + time for detail view headers.
 *
 * Output: "May 19, 2026, 14:32" (DESIGN_SYSTEM §6.4 "Detail view header").
 * WHY no seconds: seconds clutter the display without adding actionable info
 * for the contexts where absolute time is shown (article detail, event header).
 * WHY 24-hour: finance professionals expect 24h clock; am/pm is ambiguous
 * in multi-timezone workflows.
 */
function formatAbsolute(date: Date): string {
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * formatShort — locale date without time for table rows.
 *
 * Output: "May 19, 2026" (DESIGN_SYSTEM §6.4 "Table row").
 */
function formatShort(date: Date): string {
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useFormattedTimestamp — format a timestamp string or Date per DESIGN_SYSTEM §6.4.
 *
 * Returns "—" for null/undefined/invalid inputs so callers never see
 * "Invalid Date" or empty strings in the UI.
 *
 * FE-004 fix: when format === "relative" the hook ticks every 60 s so the
 * displayed label stays accurate without a page reload. For example, a badge
 * showing "4h ago" automatically updates to "5h ago" after the threshold
 * passes — important for trust in the LastSyncedBadge stale-data indicator.
 *
 * WHY 60 000 ms interval (not 1 000 ms): the minimum bucket in formatRelative
 * is "Nm ago" (minute precision). Ticking every second would re-render 59
 * times per minute with no visible change and waste React reconciliation cycles.
 *
 * WHY only for "relative": "absolute" and "short" formats don't change over
 * time so they don't need an interval — we return them synchronously without
 * subscribing to any timer.
 */
export function useFormattedTimestamp(
  timestamp: string | Date | null | undefined,
  format: TimestampFormat = "relative",
): string {
  const date = toDate(timestamp);

  // For non-relative formats (absolute, short) compute synchronously — no
  // timer subscription needed.  This branch is also used when date is null so
  // the early-return path is reachable without calling any hooks conditionally.
  // WHY compute eagerly here: useState requires an initial value before any
  // useEffect fires, and we need the same computation for the initial render
  // AND for the interval update, so we factor it out as a helper closure.
  function compute(): string {
    if (!date) return "—";
    switch (format) {
      case "relative":
        return formatRelative(date);
      case "absolute":
        return formatAbsolute(date);
      case "short":
        return formatShort(date);
    }
  }

  // FE-004: for relative format, keep the displayed value in state so React
  // can trigger a re-render when the interval fires.  For other formats we
  // still call useState/useEffect unconditionally (React rules of hooks) but
  // the interval is not started (effect returns early).
  const [label, setLabel] = useState<string>(compute);

  useEffect(() => {
    // Recompute once immediately (handles the case where timestamp prop changes
    // between renders — the initial useState call above used the old value via
    // lazy initialiser only on mount).
    setLabel(compute());

    // Only start a live-update timer for relative format — the other formats
    // are static and do not benefit from polling.
    if (format !== "relative") return;

    const id = setInterval(() => {
      setLabel(compute());
    }, 60_000); // 60 s — matches the minimum visible bucket ("Nm ago")

    return () => clearInterval(id);
    // WHY `date` and `format` in deps: if the parent passes a new timestamp or
    // switches format, the effect must re-run to restart the interval with the
    // new target.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date?.getTime(), format]);

  return label;
}
