/**
 * lib/market-schedule.ts — Pure UTC market status computation
 *
 * WHY THIS EXISTS: The MarketStatusPill in TopBar shows whether the major equity
 * markets are currently open, closed, or in pre/after-hours. This module computes
 * that status from UTC time alone — no API call needed.
 *
 * WHY PURE (no API calls, no side effects):
 * Market hours are static rules, not dynamic data. Computing them locally avoids
 * a round-trip on every TopBar render and gives instant updates on the 60s interval.
 *
 * WHY UTC ONLY:
 * JavaScript's `Date.getHours()` uses the browser's local timezone — unreliable
 * when users are in different timezones. `Date.getUTCHours()` always returns
 * the hour in UTC regardless of where the user is. Market hours are defined in
 * UTC for this exact reason.
 *
 * WHO USES IT: hooks/useMarketStatus.ts → components/shell/MarketStatusPill.tsx
 * DATA SOURCE: Static rules (no S9 calls)
 * DESIGN REFERENCE: PRD-0028 §6.5.1 MarketStatusPill
 */

// ── Types ─────────────────────────────────────────────────────────────────────

export type MarketSessionStatus = "open" | "pre-market" | "after-hours" | "closed";

export interface ExchangeStatus {
  /** Human-readable exchange name */
  name: string;
  /** Current session status */
  status: MarketSessionStatus;
  /** Regular session open in UTC (HH:MM) */
  utcOpen: string;
  /** Regular session close in UTC (HH:MM) */
  utcClose: string;
  /** Trading days description */
  days: string;
}

export interface MarketStatusResult {
  /**
   * Aggregate status across all equity markets:
   * - "open" → at least one major equity exchange is in regular session
   * - "pre-after-hours" → NYSE/NASDAQ is in pre-market or after-hours ONLY
   * - "closed" → no equity market in regular session
   *
   * WHY these three states: The TopBar pill only needs 3 colors (green/amber/red).
   * A more granular status would require per-exchange awareness from the user,
   * which belongs in the popover (not the pill itself).
   */
  overall: "open" | "pre-after-hours" | "closed";
  /** Per-exchange breakdown for the popover table */
  exchanges: ExchangeStatus[];
}

// ── Time helpers ──────────────────────────────────────────────────────────────

/**
 * toUtcMinutes — convert UTC HH:MM string to minutes since midnight
 *
 * WHY minutes (not hours): Comparing with </>= on fractional minutes (e.g., 14:30)
 * is cleaner than converting to floats (14.5). Integer arithmetic avoids float
 * precision issues.
 */
function toUtcMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + (m ?? 0);
}

/**
 * currentUtcMinutes — get current time as minutes since midnight UTC
 * WHY separate function: Makes computeMarketStatus() pure/testable by accepting
 * a Date argument. Tests can inject a fixed Date.
 */
function currentUtcMinutes(utcNow: Date): number {
  return utcNow.getUTCHours() * 60 + utcNow.getUTCMinutes();
}

/**
 * isWeekdayUtc — check if utcNow is a weekday (Mon=1 … Fri=5)
 * WHY getUTCDay() not getDay(): getDay() uses local timezone, which can shift
 * the weekday. A server in US/Eastern at 23:30 on Friday is Saturday UTC.
 */
function isWeekdayUtc(utcNow: Date): boolean {
  const day = utcNow.getUTCDay(); // 0=Sun, 1=Mon, ..., 6=Sat
  return day >= 1 && day <= 5;
}

/**
 * isSundayOrLaterUtc — true from Sunday 00:00 through Friday 23:59 UTC
 * Used for FOREX/CME which trade nearly continuously Sun–Fri
 */
function isSundayOrLaterUtc(utcNow: Date): boolean {
  const day = utcNow.getUTCDay();
  return day !== 6; // Saturday = closed
}

// ── Exchange rules ────────────────────────────────────────────────────────────

/**
 * computeNyseStatus — NYSE/NASDAQ market status
 *
 * Regular session: 14:30–21:00 UTC (Mon–Fri)
 * Pre-market: 10:00–14:30 UTC (Mon–Fri)
 * After-hours: 21:00–00:00 UTC (Mon–Fri)
 *
 * WHY pre/after-hours: Institutional traders actively trade in extended sessions.
 * Showing "after-hours" rather than "closed" communicates that prices are still moving.
 */
function computeNyseStatus(utcNow: Date): MarketSessionStatus {
  if (!isWeekdayUtc(utcNow)) return "closed";

  const mins = currentUtcMinutes(utcNow);
  const OPEN = toUtcMinutes("14:30");   // 9:30 ET = 14:30 UTC
  const CLOSE = toUtcMinutes("21:00");  // 16:00 ET = 21:00 UTC
  const PRE_OPEN = toUtcMinutes("10:00"); // 5:00 ET = 10:00 UTC
  const AFTER_CLOSE = toUtcMinutes("00:00"); // midnight UTC
  const AFTER_END = toUtcMinutes("01:00"); // 1:00 UTC = 20:00 ET previous day (not perfect, but safe)

  if (mins >= OPEN && mins < CLOSE) return "open";
  if (mins >= PRE_OPEN && mins < OPEN) return "pre-market";
  // After-hours: 21:00–24:00 UTC on weekdays
  if (mins >= CLOSE) return "after-hours";
  // Early morning 00:00–01:00 UTC (after-hours continuation from previous day)
  if (mins >= AFTER_CLOSE && mins < AFTER_END) return "after-hours";

  return "closed";
}

/**
 * computeSimpleStatus — generic open/closed check for a single time window
 * Used by exchanges that don't have pre/after-hours sessions.
 */
function computeSimpleStatus(
  utcNow: Date,
  openHHMM: string,
  closeHHMM: string,
  requiresWeekday: boolean,
  lunchStart?: string,
  lunchEnd?: string,
): MarketSessionStatus {
  if (requiresWeekday && !isWeekdayUtc(utcNow)) return "closed";

  const mins = currentUtcMinutes(utcNow);
  const open = toUtcMinutes(openHHMM);
  const close = toUtcMinutes(closeHHMM);

  if (mins < open || mins >= close) return "closed";

  // Check lunch break (some Asian exchanges close for lunch)
  if (lunchStart && lunchEnd) {
    const lunchS = toUtcMinutes(lunchStart);
    const lunchE = toUtcMinutes(lunchEnd);
    if (mins >= lunchS && mins < lunchE) return "closed"; // WHY "closed" not "break": simpler for user
  }

  return "open";
}

// ── Main export ───────────────────────────────────────────────────────────────

/**
 * computeMarketStatus — derive market status from a UTC timestamp
 *
 * WHY accepts utcNow (not reads Date.now()):
 * Pure function design — makes unit testing trivial. The hook calls this with
 * `new Date()` but tests can pass any fixed timestamp.
 *
 * Exchange hours (all UTC):
 * | Exchange     | Regular Session   | Days     | Notes               |
 * |-------------|-------------------|----------|---------------------|
 * | NYSE/NASDAQ  | 14:30–21:00       | Mon–Fri  | Pre: 10:00; AH: 21:00+ |
 * | LSE          | 08:00–16:30       | Mon–Fri  |                     |
 * | TSE          | 00:00–02:30, 03:30–06:00 | Mon–Fri | Lunch 02:30–03:30 |
 * | HKEX         | 01:30–04:00, 05:00–08:00 | Mon–Fri | Lunch 04:00–05:00 |
 * | Euronext     | 08:00–16:30       | Mon–Fri  |                     |
 * | CME Futures  | ~23:00 Sun – 22:00 Fri | ~24/5 | Simplified as open weekdays + Sun |
 * | FOREX        | 22:00 Sun – 22:00 Fri | ~24/5  | Simplified as open non-Saturday |
 * | Crypto       | 24/7              | Always  |                     |
 */
export function computeMarketStatus(utcNow: Date): MarketStatusResult {
  const nyse = computeNyseStatus(utcNow);

  const exchanges: ExchangeStatus[] = [
    {
      name: "NYSE / NASDAQ",
      status: nyse,
      utcOpen: "14:30",
      utcClose: "21:00",
      days: "Mon–Fri",
    },
    {
      name: "LSE (London)",
      status: computeSimpleStatus(utcNow, "08:00", "16:30", true),
      utcOpen: "08:00",
      utcClose: "16:30",
      days: "Mon–Fri",
    },
    {
      name: "TSE (Tokyo)",
      // TSE has a lunch break 02:30–03:30 UTC (11:30–12:30 JST)
      // WHY two windows: morning session 00:00–02:30 + afternoon 03:30–06:00
      status: ((): MarketSessionStatus => {
        if (!isWeekdayUtc(utcNow)) return "closed";
        const m = currentUtcMinutes(utcNow);
        if ((m >= 0 && m < toUtcMinutes("02:30")) || (m >= toUtcMinutes("03:30") && m < toUtcMinutes("06:00"))) {
          return "open";
        }
        return "closed";
      })(),
      utcOpen: "00:00",
      utcClose: "06:00",
      days: "Mon–Fri",
    },
    {
      name: "HKEX",
      // Lunch break 04:00–05:00 UTC (12:00–13:00 HKT)
      status: ((): MarketSessionStatus => {
        if (!isWeekdayUtc(utcNow)) return "closed";
        const m = currentUtcMinutes(utcNow);
        if ((m >= toUtcMinutes("01:30") && m < toUtcMinutes("04:00")) || (m >= toUtcMinutes("05:00") && m < toUtcMinutes("08:00"))) {
          return "open";
        }
        return "closed";
      })(),
      utcOpen: "01:30",
      utcClose: "08:00",
      days: "Mon–Fri",
    },
    {
      name: "Euronext",
      status: computeSimpleStatus(utcNow, "08:00", "16:30", true),
      utcOpen: "08:00",
      utcClose: "16:30",
      days: "Mon–Fri",
    },
    {
      name: "CME Futures",
      // Simplified: open Mon–Fri during core hours
      status: ((): MarketSessionStatus => {
        if (!isSundayOrLaterUtc(utcNow)) return "closed";
        return "open"; // WHY simplify: futures nearly 24/5; full DST-aware calc is overkill for MVP
      })(),
      utcOpen: "23:00",
      utcClose: "22:00",
      days: "Sun–Fri",
    },
    {
      name: "FOREX",
      // Forex is open from Sunday 22:00 UTC to Friday 22:00 UTC
      status: isSundayOrLaterUtc(utcNow) ? "open" : "closed",
      utcOpen: "22:00",
      utcClose: "22:00",
      days: "Sun–Fri",
    },
    {
      name: "Crypto",
      // Crypto never closes — 24/7/365
      status: "open",
      utcOpen: "00:00",
      utcClose: "24:00",
      days: "24/7",
    },
  ];

  // Derive aggregate overall status (NYSE-first priority):
  //
  // WHY NYSE drives the pill: Our users are primarily US-focused institutional traders.
  // NYSE/NASDAQ status determines the amber "pre-after-hours" state — telling the trader
  // that US markets are in extended hours, regardless of whether LSE or Euronext is open.
  // LSE/HKEX/etc. status is surfaced in the popover, not the pill color.
  //
  // Priority order:
  //   1. NYSE open → green "open"
  //   2. NYSE pre/after-hours → amber "pre-after-hours"
  //   3. NYSE closed but other equity exchange open → green "open"
  //   4. Everything closed → red "closed"
  const nonNyseEquities = exchanges.slice(1, 5); // LSE, TSE, HKEX, Euronext
  const anyOtherEquityOpen = nonNyseEquities.some((ex) => ex.status === "open");

  let overall: MarketStatusResult["overall"];
  if (nyse === "open") {
    overall = "open";
  } else if (nyse === "pre-market" || nyse === "after-hours") {
    overall = "pre-after-hours";
  } else if (anyOtherEquityOpen) {
    overall = "open";
  } else {
    overall = "closed";
  }

  return { overall, exchanges };
}
