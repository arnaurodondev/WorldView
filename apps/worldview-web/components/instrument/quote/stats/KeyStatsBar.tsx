/**
 * components/instrument/quote/stats/KeyStatsBar.tsx — Key Stats bar below the chart
 * (Round-2 Enhancement, Instrument Detail surface, item 1).
 *
 * WHY THIS EXISTS: the Quote tab's right rail (MetricsTable) carries 26 rows of
 * statistics, but the five numbers a trader checks FIRST (Market Cap, P/E, EPS,
 * Dividend Yield, Beta) sit below the fold of that rail on small screens and
 * require an eye-jump away from the chart. A single scannable strip directly
 * under the chart puts the "is this big / expensive / risky?" triage right in
 * the chart's reading path — the Bloomberg DES-row convention.
 *
 * DATA SOURCES — ZERO new network fetches (hard requirement):
 *   - fundamentals (Market Cap, P/E, Div Yield): passive subscription to
 *     qk.instruments.fundamentals(instrumentId). The Quote tab's MetricsTable
 *     (always mounted alongside this bar) owns the ACTIVE fetch through
 *     useMetricsTableData — this component only reads whatever lands in the
 *     shared cache slot (`enabled: false` → never fires its own request).
 *   - snapshot (EPS TTM, Beta): same passive pattern against
 *     qk.instruments.fundamentalsSnapshot(instrumentId). That key is pre-seeded
 *     by InstrumentPageClient from the page bundle (PLAN-0099 follow-up G), so
 *     EPS/Beta are typically available on first paint.
 *   - prop fallbacks: the slim page-bundle `overview.fundamentals` (5 fields:
 *     market_cap, pe_ratio, …) and `fundamentals_snapshot` cover the window
 *     before the rich cache entries hydrate — avoids an em-dash flash for the
 *     two fields the slim shape does carry.
 *
 * WHY passive useQuery (enabled:false) instead of calling useMetricsTableData:
 * that hook subscribes to FOUR queries (incl. technicals + shareStats) we don't
 * need. A bare cache subscription keeps this component's reactive surface to
 * exactly the two slots it renders from, mirroring QuoteTab's own passive OHLCV
 * subscription pattern.
 *
 * WHO USES IT: QuoteTab (left column, directly below the OHLCVChart).
 * DESIGN: 22px strip — same density unit as SessionStatsStrip; muted uppercase
 * mono labels + font-mono tabular values (ADR-F-15); em-dash for nulls.
 */

"use client";
// WHY "use client": useQuery (cache subscription) requires the browser runtime.

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query/keys";
import { formatMarketCap, formatPercentUnsigned, formatPrice, formatRatio } from "@/lib/utils";
import type { Fundamentals, FundamentalsSnapshot } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface KeyStatsBarProps {
  /** S3 instrument_id — cache-key handle for the two passive subscriptions. */
  readonly instrumentId: string;
  /**
   * Slim page-bundle fundamentals (market_cap + pe_ratio populated; most other
   * fields null). Used ONLY until the rich /v1/fundamentals/{id} transform
   * lands in cache — the cache value always wins (it carries dividend_yield).
   */
  readonly fundamentals?: Fundamentals | null;
  /** Page-bundle snapshot (eps_ttm, beta) — same fallback-until-cache role. */
  readonly snapshot?: FundamentalsSnapshot | null;
}

// ── Single stat cell ─────────────────────────────────────────────────────────

/**
 * StatCell — one LABEL value pair.
 *
 * WHY a sub-component (not inline JSX × 5): guarantees the five cells stay
 * typographically identical — label 10px uppercase muted mono, value 11px
 * mono tabular. Mirrors SessionStatsStrip's `Stat` for visual continuity
 * (the two strips stack directly on top of each other).
 */
function StatCell({ label, value, pending }: { label: string; value: string; pending?: boolean }) {
  return (
    <span className="flex items-baseline gap-1 shrink-0">
      <span className="text-[10px] uppercase text-muted-foreground font-mono">
        {label}
      </span>
      {/* Round-3 item 4 (shape-matched skeletons): while the SHARED cache
          fetch is in flight and this cell has no value yet, render a pulsing
          value-width bar instead of an em-dash — "—" reads as "no data
          exists" (a final state), which is a lie during the ~300ms before
          MetricsTable's fetch lands. w-10 ≈ a 5-char mono value, so the strip
          doesn't reflow when the real number replaces the bar. */}
      {pending ? (
        <span aria-hidden className="h-[11px] w-10 animate-pulse rounded-[1px] bg-muted/40 self-center" />
      ) : (
        // WHY font-mono tabular-nums: ADR-F-15 — every numeric in the app is
        // monospaced so columns/strips don't jitter as live values update.
        <span className="text-[11px] font-mono tabular-nums text-foreground">
          {value}
        </span>
      )}
    </span>
  );
}

/** Thin vertical rule between cells — same glyph as SessionStatsStrip. */
function Rule() {
  return (
    <span className="text-[10px] text-border" aria-hidden="true">
      │
    </span>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export function KeyStatsBar({
  instrumentId,
  fundamentals: fundamentalsProp,
  snapshot: snapshotProp,
}: KeyStatsBarProps) {
  // Passive subscription to the RICH fundamentals transform that MetricsTable's
  // useMetricsTableData actively fetches. `enabled: false` → this observer
  // NEVER issues a network request; it only re-renders when the shared cache
  // slot fills/refreshes. (Same pattern as QuoteTab's OHLCV cache peek.)
  // WHY also read isFetching (Round-3 item 4): fetchStatus is QUERY-level
  // state shared across all observers of the key — even with enabled:false,
  // this passive observer reports isFetching=true while MetricsTable's ACTIVE
  // observer has the request in flight. That gives us an honest "loading vs
  // genuinely-no-data" signal without issuing any request ourselves: skeleton
  // bars only ever pulse while a real fetch is pending, so instruments with
  // no fundamentals settle on "—" instead of pulsing forever.
  const { data: cachedFundamentals, isFetching: fundamentalsFetching } = useQuery<Fundamentals>({
    queryKey: qk.instruments.fundamentals(instrumentId),
    enabled: false,
  });

  // Snapshot slot — pre-seeded from the page bundle by InstrumentPageClient,
  // then kept fresh by useMetricsTableData's active query. Passive here too.
  const { data: cachedSnapshot, isFetching: snapshotFetching } = useQuery<FundamentalsSnapshot>({
    queryKey: qk.instruments.fundamentalsSnapshot(instrumentId),
    enabled: false,
  });

  // WHY cache-wins coalesce: the cache value is the rich, fresher shape; the
  // prop is the slim bundle seed that exists purely to avoid an em-dash flash
  // on cold first paint. Same precedence rule MetricsTable uses for its
  // fundamentals prop.
  const f: Fundamentals | null = cachedFundamentals ?? fundamentalsProp ?? null;
  const s: FundamentalsSnapshot | null = cachedSnapshot ?? snapshotProp ?? null;

  // Per-source pending flags: a cell is "pending" only while its backing
  // query is actually in flight AND no value (cache or bundle seed) exists
  // yet. Once any value is present we show it immediately — the background
  // refetch must never regress a real number back to a skeleton bar.
  const fPending = fundamentalsFetching && f == null;
  const sPending = snapshotFetching && s == null;

  return (
    // WHY h-[22px] + border-t: stacks flush under the chart at the same
    // density unit as SessionStatsStrip below it. overflow-x-auto keeps the
    // five cells reachable on tablet widths instead of clipping.
    <div
      className="flex h-[22px] min-w-0 items-center gap-4 overflow-x-auto border-t border-border/50 bg-background px-3"
      aria-label="Key statistics"
    >
      {/* Market Cap — compact currency ($4.31T). Null → "—" via formatter. */}
      <StatCell label="MKT CAP" value={formatMarketCap(f?.market_cap)} pending={fPending} />
      <Rule />

      {/* P/E (trailing) — ratio with no suffix; "35.47" reads cleaner than
          "35.47x" in a strip this dense (the label already says P/E). */}
      <StatCell label="P/E" value={formatRatio(f?.pe_ratio, "")} pending={fPending} />
      <Rule />

      {/* EPS TTM — currency-precision price format ($8.27). Sourced from the
          snapshot leg (the flat Fundamentals shape has no EPS field). */}
      <StatCell label="EPS" value={formatPrice(s?.eps_ttm)} pending={sPending} />
      <Rule />

      {/* Dividend Yield — stored as a decimal (0.004 = 0.4%); the formatter
          multiplies by 100. WHY unsigned: a yield is an allocation-style
          percentage — a "+" prefix would mis-read as a price change. Null for
          non-payers → "—" (honest: no dividend data ≠ 0% yield). */}
      <StatCell label="DIV YLD" value={formatPercentUnsigned(f?.dividend_yield)} pending={fPending} />
      <Rule />

      {/* Beta — plain 2-dp ratio (1.09). From the snapshot leg. */}
      <StatCell label="BETA" value={formatRatio(s?.beta, "")} pending={sPending} />
    </div>
  );
}
