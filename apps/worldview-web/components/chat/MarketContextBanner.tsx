"use client";
// WHY "use client": uses setInterval to keep the market-session label and
// clock live. Date.now() is a browser API that requires client execution.

/**
 * components/chat/MarketContextBanner.tsx — Market session status strip
 * above the Intelligence thread list.
 *
 * WHY THIS EXISTS (PLAN-0071 P2C-1): the chat page redesign requires
 * financial differentiation from a generic chatbot. This strip grounds the
 * intelligence thread list in real market context — US equity session status
 * and current Eastern-time clock — without any API call. The session state
 * is computed from the browser's clock, which is accurate enough for session
 * classification (off-by-a-second is irrelevant for a "PRE-MARKET" label).
 *
 * WHY NO API CALL: S9 has no market-hours endpoint. Computing session status
 * client-side from NYSE open/close rules avoids a gratuitous round-trip on
 * a UI that already makes several data fetches.
 *
 * WHY THE STATUS MATTERS FOR ANALYSTS: the session context changes what
 * questions are useful. "Why did AAPL gap up?" is only relevant post-open;
 * "What moves should I expect?" is a pre-market question. Surfacing session
 * status above the thread list primes users toward higher-value research.
 *
 * WHO USES IT: app/(app)/chat/page.tsx — top of the left thread-list sidebar.
 * DATA SOURCE: Browser clock (client-side only, no S9 dependency).
 * DESIGN REFERENCE: PLAN-0071 Phase 2C chat page redesign.
 */

import { useEffect, useState } from "react";

// ── Market session helpers ─────────────────────────────────────────────────────

/**
 * NYSE regular hours (Eastern time, 24h):
 *   Pre-market:   04:00 – 09:30
 *   Regular:      09:30 – 16:00
 *   After-hours:  16:00 – 20:00
 *   Closed:       20:00 – 04:00 (and all day Saturday/Sunday)
 */
function getMarketSession(now: Date): {
  label: string;
  color: string;
  dotColor: string;
} {
  // getDay(): 0 = Sunday, 6 = Saturday
  const dayOfWeek = now.getDay();
  if (dayOfWeek === 0 || dayOfWeek === 6) {
    return { label: "WEEKEND", color: "text-muted-foreground", dotColor: "bg-muted-foreground" };
  }

  // Convert current UTC time to Eastern (ET).
  // WHY manual UTC offset: Intl.DateTimeFormat resolves DST correctly but
  // returns a string — extracting hours/minutes from a formatted string is
  // brittle. Instead we get the ET offset via Intl and compute ET hours from it.
  const etFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "numeric",
    hour12: false,
  });
  const parts = etFormatter.formatToParts(now);
  const etHour = parseInt(parts.find((p) => p.type === "hour")?.value ?? "0", 10);
  const etMinute = parseInt(parts.find((p) => p.type === "minute")?.value ?? "0", 10);
  const etTotal = etHour * 60 + etMinute; // minutes since midnight ET

  const PRE_OPEN = 4 * 60;        // 04:00
  const OPEN = 9 * 60 + 30;       // 09:30
  const CLOSE = 16 * 60;          // 16:00
  const AFTER_CLOSE = 20 * 60;    // 20:00

  if (etTotal < PRE_OPEN || etTotal >= AFTER_CLOSE) {
    return { label: "CLOSED", color: "text-muted-foreground", dotColor: "bg-muted-foreground" };
  }
  if (etTotal < OPEN) {
    return { label: "PRE-MARKET", color: "text-warning", dotColor: "bg-warning" };
  }
  if (etTotal < CLOSE) {
    return { label: "US OPEN", color: "text-positive", dotColor: "bg-positive" };
  }
  return { label: "AFTER-HOURS", color: "text-warning", dotColor: "bg-warning" };
}

/**
 * formatEasternTime — returns "HH:MM ET" from a Date object.
 * Used in the banner so analysts know the current ET clock at a glance.
 */
function formatEasternTime(now: Date): string {
  return now.toLocaleTimeString("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }) + " ET";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketContextBanner() {
  // WHY 60s interval (not per-second): the session label changes at most once
  // per day. A 60-second tick is enough to catch the 09:30 / 16:00 transition
  // within 1 minute, which is acceptable UX for a session banner.
  const [now, setNow] = useState<Date>(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const session = getMarketSession(now);
  const clock = formatEasternTime(now);

  return (
    <div
      className="flex items-center justify-between border-b border-border/40 bg-muted/20 px-3 py-1.5"
      aria-label={`Market session: ${session.label}`}
    >
      {/* Session status — colored dot + label */}
      <div className="flex items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${session.dotColor}`}
          aria-hidden="true"
        />
        <span
          className={`font-mono text-[9px] font-semibold uppercase tracking-[0.10em] ${session.color}`}
        >
          {session.label}
        </span>
      </div>

      {/* Eastern time clock */}
      <span
        className="font-mono text-[9px] tabular-nums text-muted-foreground"
        aria-label={`Current time: ${clock}`}
      >
        {clock}
      </span>
    </div>
  );
}
