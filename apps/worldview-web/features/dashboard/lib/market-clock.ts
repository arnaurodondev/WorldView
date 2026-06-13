/**
 * features/dashboard/lib/market-clock.ts — US-equity session-state engine
 *
 * WHY THIS EXISTS (Round 2 enhancement, 2026-06-10): the MarketClockWidget
 * needs to answer two questions every minute:
 *   1. "What session is the US equity market in RIGHT NOW?"
 *      (Pre-market / Regular / After-hours / Closed)
 *   2. "When is the next transition, so we can show a countdown?"
 *
 * WHY A PURE MODULE (no React, no Date.now() inside): the session math is
 * the part most likely to be wrong (time zones, weekends, holidays, DST).
 * Keeping it a pure `Date in → SessionInfo out` function makes every branch
 * unit-testable with a fixed instant — the widget just calls it on a timer.
 *
 * WHY Intl APIs (no date library): the project rule for this widget is "no
 * new deps". `Intl.DateTimeFormat` with `timeZone: "America/New_York"` gives
 * us correct Eastern wall-clock components for ANY instant, including DST
 * switches, because the browser/Node ship the IANA tz database. We never
 * hardcode a UTC offset (-5/-4) — that's the classic DST bug.
 *
 * SESSION SCHEDULE (regular NYSE/Nasdaq trading day, all times Eastern):
 *   04:00–09:30  Pre-market
 *   09:30–16:00  Regular session
 *   16:00–20:00  After-hours
 *   20:00–04:00  Closed (overnight) — plus all day on weekends & holidays
 */

// ── Holiday calendar ──────────────────────────────────────────────────────────

/**
 * NYSE FULL-DAY holidays for 2026, as "YYYY-MM-DD" in Eastern time.
 *
 * ⚠ MAINTENANCE NEEDED: this static list covers 2026 ONLY and must be
 * extended each year (NYSE publishes the schedule ~2 years ahead at
 * nyse.com/markets/hours-calendars). Dates outside this list are treated as
 * normal trading days — so an un-maintained list fails "open" (shows the
 * market as open on a holiday) rather than crashing.
 *
 * NOT COVERED (deliberate scope cut): early-close half days (e.g. the day
 * after Thanksgiving closes at 13:00). Modelling them needs a second
 * schedule table; the clock will show "Market open" until 16:00 on those
 * 3 days/year. Acceptable for a dashboard glance widget.
 */
export const NYSE_FULL_HOLIDAYS_2026: ReadonlySet<string> = new Set([
  "2026-01-01", // New Year's Day (Thu)
  "2026-01-19", // Martin Luther King Jr. Day (3rd Mon Jan)
  "2026-02-16", // Washington's Birthday / Presidents' Day (3rd Mon Feb)
  "2026-04-03", // Good Friday
  "2026-05-25", // Memorial Day (last Mon May)
  "2026-06-19", // Juneteenth (Fri)
  "2026-07-03", // Independence Day — observed (Jul 4 falls on Saturday)
  "2026-09-07", // Labor Day (1st Mon Sep)
  "2026-11-26", // Thanksgiving Day (4th Thu Nov)
  "2026-12-25", // Christmas Day (Fri)
]);

// ── Types ─────────────────────────────────────────────────────────────────────

/** The four states a US equity trading day cycles through. */
export type MarketSessionState = "pre" | "regular" | "after" | "closed";

/** Why the market is closed — drives the small context caption. */
export type ClosedReason = "weekend" | "holiday" | "overnight";

export interface MarketSessionInfo {
  state: MarketSessionState;
  /**
   * UTC instant of the NEXT state transition (e.g. while "regular" this is
   * today's 16:00 ET expressed in UTC). The widget derives the countdown as
   * `nextTransition - now` — an absolute instant keeps the countdown correct
   * even across a DST switch between now and the transition.
   */
  nextTransition: Date;
  /** Human label for what the next transition IS, e.g. "opens" / "closes". */
  nextLabel: string;
  /** Only present when state === "closed". */
  closedReason?: ClosedReason;
}

// ── Session boundaries (minutes since midnight, Eastern wall clock) ──────────

const PRE_OPEN_MIN = 4 * 60; //  04:00 ET
const REG_OPEN_MIN = 9 * 60 + 30; //  09:30 ET
const REG_CLOSE_MIN = 16 * 60; //  16:00 ET
const AFTER_CLOSE_MIN = 20 * 60; //  20:00 ET

const NY_TZ = "America/New_York";

// ── Eastern wall-clock extraction ─────────────────────────────────────────────

// WHY a module-level formatter: Intl.DateTimeFormat construction is expensive
// (~1ms — it loads locale + tz data). The widget calls getMarketSession every
// second, so we build the formatter once and reuse it.
// WHY hourCycle "h23": guarantees hour comes back 0–23 (never "24" at
// midnight, never 12-hour), so `hour * 60 + minute` arithmetic is safe.
const NY_PARTS_FMT = new Intl.DateTimeFormat("en-US", {
  timeZone: NY_TZ,
  hourCycle: "h23",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

interface NyParts {
  year: number;
  month: number; // 1–12
  day: number; // 1–31
  hour: number; // 0–23
  minute: number;
  second: number;
}

/** Decompose a UTC instant into its Eastern wall-clock components. */
function getNyParts(instant: Date): NyParts {
  // formatToParts gives labelled fields — order-independent, unlike parsing
  // a formatted string (which broke other projects when ICU changed
  // separators between Node versions).
  const map: Record<string, string> = {};
  for (const part of NY_PARTS_FMT.formatToParts(instant)) {
    if (part.type !== "literal") map[part.type] = part.value;
  }
  return {
    year: Number(map.year),
    month: Number(map.month),
    day: Number(map.day),
    hour: Number(map.hour),
    minute: Number(map.minute),
    second: Number(map.second),
  };
}

// ── Calendar-date helpers (no time zone involved) ─────────────────────────────

/**
 * A calendar date treated as pure y/m/d arithmetic. We deliberately do the
 * "which day is it / is it a weekend / what's tomorrow" math on Date.UTC
 * timestamps of midnight-UTC: at midnight UTC there is no DST, so adding
 * 86_400_000 ms is ALWAYS exactly one calendar day. (Doing the same with
 * local-time Dates breaks twice a year when a day is 23h or 25h long.)
 */
function calendarKey(y: number, m: number, d: number): string {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/** 0=Sunday … 6=Saturday for a pure calendar date. */
function weekdayOf(y: number, m: number, d: number): number {
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}

/** Is this Eastern calendar date a full NYSE trading day? */
export function isTradingDay(y: number, m: number, d: number): boolean {
  const wd = weekdayOf(y, m, d);
  if (wd === 0 || wd === 6) return false; // weekend
  return !NYSE_FULL_HOLIDAYS_2026.has(calendarKey(y, m, d));
}

/** Advance a pure calendar date by `days` (DST-proof — see calendarKey WHY). */
function addDays(y: number, m: number, d: number, days: number): { y: number; m: number; d: number } {
  const t = new Date(Date.UTC(y, m - 1, d) + days * 86_400_000);
  return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() };
}

// ── Eastern wall time → UTC instant ──────────────────────────────────────────

/**
 * Convert an Eastern wall-clock time (e.g. "2026-06-10 09:30") to the UTC
 * instant at which that wall time occurs.
 *
 * WHY THE ITERATIVE TRICK: JavaScript has no built-in "zoned time → UTC"
 * (Temporal will fix this; it's not shipped everywhere yet). The standard
 * library-free algorithm:
 *   1. Guess: pretend the wall time IS UTC.
 *   2. Ask Intl what wall time that guess actually shows in New York.
 *   3. Shift the guess by the difference. One pass lands exactly unless the
 *      first guess straddles a DST change; a second pass fixes that.
 * Session boundaries (04:00/09:30/16:00/20:00) never coincide with the
 * 02:00-local DST jump, so two passes are always sufficient here.
 */
export function nyWallTimeToUtc(y: number, m: number, d: number, hour: number, minute: number): Date {
  const targetAsUtc = Date.UTC(y, m - 1, d, hour, minute, 0, 0);
  let ts = targetAsUtc;
  for (let i = 0; i < 2; i++) {
    const p = getNyParts(new Date(ts));
    const shownAsUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
    ts += targetAsUtc - shownAsUtc;
  }
  return new Date(ts);
}

// ── Main API ──────────────────────────────────────────────────────────────────

/**
 * getMarketSession — classify a UTC instant into a US-equity session state
 * and compute the next transition instant.
 *
 * Pure function: same `now` in → same result out. The widget owns the timer.
 */
export function getMarketSession(now: Date): MarketSessionInfo {
  const ny = getNyParts(now);
  const minutes = ny.hour * 60 + ny.minute;
  const trading = isTradingDay(ny.year, ny.month, ny.day);

  if (trading) {
    if (minutes >= PRE_OPEN_MIN && minutes < REG_OPEN_MIN) {
      return {
        state: "pre",
        nextTransition: nyWallTimeToUtc(ny.year, ny.month, ny.day, 9, 30),
        nextLabel: "opens",
      };
    }
    if (minutes >= REG_OPEN_MIN && minutes < REG_CLOSE_MIN) {
      return {
        state: "regular",
        nextTransition: nyWallTimeToUtc(ny.year, ny.month, ny.day, 16, 0),
        nextLabel: "closes",
      };
    }
    if (minutes >= REG_CLOSE_MIN && minutes < AFTER_CLOSE_MIN) {
      return {
        state: "after",
        nextTransition: nyWallTimeToUtc(ny.year, ny.month, ny.day, 20, 0),
        // W4 (user report 2026-06-12 "bug in the market clock"): the widget
        // renders `${nextLabel} in ${countdown}`. Every other label is a VERB
        // ("opens"/"closes"/"pre-market opens") that reads correctly; the
        // OLD value "after-hours end" was a noun phrase, producing the broken
        // "after-hours end in 28m". Verb form → "after-hours ends in 28m".
        nextLabel: "after-hours ends",
      };
    }
  }

  // ── Closed: overnight (before 04:00 / after 20:00), weekend, or holiday ──
  // The next transition is the NEXT trading day's 04:00 ET pre-market open.
  // WHY classify the reason from TODAY (not the next open day): the caption
  // answers "why is it closed right now?" — on a Saturday that's "weekend"
  // even though the next open is Monday.
  const wd = weekdayOf(ny.year, ny.month, ny.day);
  let closedReason: ClosedReason;
  if (wd === 0 || wd === 6) {
    closedReason = "weekend";
  } else if (NYSE_FULL_HOLIDAYS_2026.has(calendarKey(ny.year, ny.month, ny.day))) {
    closedReason = "holiday";
  } else {
    closedReason = "overnight";
  }

  // Before 04:00 on a trading day, the next pre-market open is TODAY.
  if (trading && minutes < PRE_OPEN_MIN) {
    return {
      state: "closed",
      nextTransition: nyWallTimeToUtc(ny.year, ny.month, ny.day, 4, 0),
      nextLabel: "pre-market opens",
      closedReason,
    };
  }

  // Otherwise scan forward (bounded loop — a 10-day window always contains a
  // trading day even across the longest holiday+weekend cluster).
  let cursor = { y: ny.year, m: ny.month, d: ny.day };
  for (let i = 0; i < 10; i++) {
    cursor = addDays(cursor.y, cursor.m, cursor.d, 1);
    if (isTradingDay(cursor.y, cursor.m, cursor.d)) break;
  }
  return {
    state: "closed",
    nextTransition: nyWallTimeToUtc(cursor.y, cursor.m, cursor.d, 4, 0),
    nextLabel: "pre-market opens",
    closedReason,
  };
}

// ── Display helpers ───────────────────────────────────────────────────────────

/** Terminal-style label per state (uppercase, matches §0.9 header chrome). */
export const SESSION_LABEL: Record<MarketSessionState, string> = {
  pre: "PRE-MARKET",
  regular: "MARKET OPEN",
  after: "AFTER HOURS",
  closed: "CLOSED",
};

/**
 * formatCountdown — "2h 14m" / "14m" / "<1m" from a millisecond delta.
 *
 * WHY minute granularity (no seconds): the widget ticks every second for the
 * clock readout, but a seconds-level countdown to an event hours away is
 * visual noise. WHY Math.ceil: "opens in 0m" while still closed reads as a
 * bug — ceiling guarantees the countdown only reaches the floor label
 * ("<1m") in the final minute.
 */
export function formatCountdown(ms: number): string {
  if (ms <= 0) return "now";
  // WHY a dedicated sub-minute branch (not relying on ceil): ceil(any
  // positive ms / 60000) is always ≥ 1, so without this branch "<1m" would
  // be unreachable and the final minute would read "1m" until the very end.
  if (ms < 60_000) return "<1m";
  const totalMinutes = Math.ceil(ms / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes}m`;
  // Days only matter over long weekends — fold them into hours ("52h 10m")?
  // No: "2d 4h" scans faster than "52h". Show days when ≥ 24h.
  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    return `${days}d ${hours % 24}h`;
  }
  return `${hours}h ${minutes}m`;
}

/**
 * formatNyClock — "14:32:05 ET" readout for the widget's big clock line.
 * Kept here (not in the component) so tests can pin the exact format.
 */
const NY_CLOCK_FMT = new Intl.DateTimeFormat("en-US", {
  timeZone: NY_TZ,
  hourCycle: "h23",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function formatNyClock(now: Date): string {
  return `${NY_CLOCK_FMT.format(now)} ET`;
}
