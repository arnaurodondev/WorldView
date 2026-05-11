/**
 * components/shell/UtcClock.tsx — Live UTC clock for TopBar
 *
 * WHY THIS EXISTS: Finance professionals always want to know what time it is in UTC.
 * Market hours, economic releases, and event timestamps are all expressed in UTC.
 * A persistent UTC clock eliminates the mental math of "what's my timezone offset?".
 *
 * WHY seconds precision: Option order entry and news events are time-stamped to
 * the second. A clock showing HH:MM:SS lets traders correlate events to their
 * news feed timestamps without ambiguity.
 *
 * WHY client-side only: Time is inherently runtime state — the server-rendered
 * timestamp would be stale by the time it reaches the browser.
 *
 * PLAN-0059 W0 F-CODE-NEW-004 fix: REMOVED the `useState(() => formatUtcTime(new Date()))`
 * lazy initializer pattern. With Next.js App Router this guarantees a hydration
 * mismatch — the lazy initializer runs on the server with the server's clock during
 * SSR, then runs on the client with the client's clock during hydration. The two
 * values WILL differ, which forces React to discard server HTML and re-render
 * (small but real perf cost + DOM diff repaint).
 *
 * Now: SSR renders an empty span (no time). useEffect populates after mount.
 * `suppressHydrationWarning` removed — no mismatch to suppress now. The fix
 * pattern: empty string SSR + useEffect set on mount + interval. Standard
 * React 19 / Next.js 15 idiom for browser-only state.
 *
 * WHO USES IT: components/shell/TopBar.tsx (right side)
 * DATA SOURCE: system clock (no S9 calls)
 * DESIGN REFERENCE: PRD-0028 §6.5 TopBar
 */

"use client";
// WHY "use client": Uses setInterval (browser-only side effect) and updates
// state every second. Server Components cannot have time-based state.

import { useEffect, useState } from "react";
// PLAN-0059-C C-4: replaced raw setInterval with the Abramov-pattern
// useInterval hook. Functionally identical here (the callback has no
// closed-over state), but using the shared hook keeps the timer pattern
// consistent across the app and protects against future refactors that
// might add stale-closure-prone state.
import { useInterval } from "@/hooks/useInterval";

/**
 * formatUtcTime — format a Date as HH:MM:SS UTC
 *
 * WHY toISOString().slice(11, 19):
 * ISO 8601 format is `YYYY-MM-DDTHH:MM:SS.mmmZ`. The UTC time is always at
 * positions 11–18 (zero-indexed). This slice is simpler and faster than
 * constructing the string from getUTCHours/Minutes/Seconds individually.
 * The `Z` suffix in the original confirms it's UTC — we strip it and add " UTC".
 */
function formatUtcTime(date: Date): string {
  return `${date.toISOString().slice(11, 19)} UTC`;
}

export function UtcClock() {
  // PLAN-0059 W0: SSR renders empty string; useEffect populates after mount.
  // No hydration mismatch because server and client both initially render "".
  const [time, setTime] = useState<string>("");

  // Set immediately on mount so the user sees the time without 1s delay
  useEffect(() => {
    setTime(formatUtcTime(new Date()));
  }, []);

  // Update every second — fine-grained enough for second-precision timestamps.
  // useInterval handles cleanup + stale-closure safety internally.
  useInterval(() => {
    setTime(formatUtcTime(new Date()));
  }, 1000);

  return (
    // WHY font-mono (ADR-F-15): Monospace font for all numeric/time displays ensures
    // the clock width is stable — digits don't cause layout shift as they change.
    // PLAN-0059 W0: removed suppressHydrationWarning — there is no longer a mismatch.
    // The empty initial state is byte-for-byte identical between SSR and first hydration.
    // Pre-allocate width via tabular-nums + min-width so the empty -> populated
    // transition doesn't shift TopBar layout.
    <span
      className="inline-block min-w-[80px] font-mono text-xs tabular-nums text-muted-foreground"
    >
      {time}
    </span>
  );
}
