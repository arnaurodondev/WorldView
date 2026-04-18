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
 * timestamp would be stale by the time it reaches the browser. The hydration
 * mismatch is suppressed with suppressHydrationWarning on the <span>.
 *
 * WHO USES IT: components/shell/TopBar.tsx (right side)
 * DATA SOURCE: system clock (no S9 calls)
 * DESIGN REFERENCE: PRD-0028 §6.5 TopBar
 */

"use client";
// WHY "use client": Uses setInterval (browser-only side effect) and updates
// state every second. Server Components cannot have time-based state.

import { useEffect, useState } from "react";

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
  // WHY initializer function: avoids hydration mismatch warning.
  // The server renders an empty string; the client immediately shows the correct
  // time on mount without a flash of "00:00:00 UTC".
  const [time, setTime] = useState<string>(() => formatUtcTime(new Date()));

  useEffect(() => {
    // Update every second — fine-grained enough for second-precision timestamps
    const id = setInterval(() => {
      setTime(formatUtcTime(new Date()));
    }, 1000);

    // WHY cleanup: interval would fire after unmount if not cleared,
    // causing "setState on unmounted component" in strict mode dev logging
    return () => clearInterval(id);
  }, []); // Empty deps: set up once, run for component lifetime

  return (
    // WHY font-mono (ADR-F-15): Monospace font for all numeric/time displays ensures
    // the clock width is stable — digits don't cause layout shift as they change.
    // suppressHydrationWarning: the time differs between server and client render;
    // this attribute tells React to skip the mismatch check for this element.
    <span
      className="font-mono text-xs tabular-nums text-muted-foreground"
      suppressHydrationWarning
    >
      {time}
    </span>
  );
}
