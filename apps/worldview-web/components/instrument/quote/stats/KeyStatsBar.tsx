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
function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1 shrink-0">
      <span className="text-[10px] uppercase text-muted-foreground font-mono">
        {label}
      </span>
      {/* WHY font-mono tabular-nums: ADR-F-15 — every numeric in the app is
          monospaced so columns/strips don't jitter as live values update. */}
      <span className="text-[11px] font-mono tabular-nums text-foreground">
        {value}
      </span>
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
  const { data: cachedFundamentals } = useQuery<Fundamentals>({
    queryKey: qk.instruments.fundamentals(instrumentId),
    enabled: false,
  });

  // Snapshot slot — pre-seeded from the page bundle by InstrumentPageClient,
  // then kept fresh by useMetricsTableData's active query. Passive here too.
  const { data: cachedSnapshot } = useQuery<FundamentalsSnapshot>({
    queryKey: qk.instruments.fundamentalsSnapshot(instrumentId),
    enabled: false,
  });

  // WHY cache-wins coalesce: the cache value is the rich, fresher shape; the
  // prop is the slim bundle seed that exists purely to avoid an em-dash flash
  // on cold first paint. Same precedence rule MetricsTable uses for its
  // fundamentals prop.
  const f: Fundamentals | null = cachedFundamentals ?? fundamentalsProp ?? null;
  const s: FundamentalsSnapshot | null = cachedSnapshot ?? snapshotProp ?? null;

  return (
    // WHY h-[22px] + border-t: stacks flush under the chart at the same
    // density unit as SessionStatsStrip below it. overflow-x-auto keeps the
    // five cells reachable on tablet widths instead of clipping.
    <div
      className="flex h-[22px] min-w-0 items-center gap-4 overflow-x-auto border-t border-border/50 bg-background px-3"
      aria-label="Key statistics"
    >
      {/* Market Cap — compact currency ($4.31T). Null → "—" via formatter. */}
      <StatCell label="MKT CAP" value={formatMarketCap(f?.market_cap)} />
      <Rule />

      {/* P/E (trailing) — ratio with no suffix; "35.47" reads cleaner than
          "35.47x" in a strip this dense (the label already says P/E). */}
      <StatCell label="P/E" value={formatRatio(f?.pe_ratio, "")} />
      <Rule />

      {/* EPS TTM — currency-precision price format ($8.27). Sourced from the
          snapshot leg (the flat Fundamentals shape has no EPS field). */}
      <StatCell label="EPS" value={formatPrice(s?.eps_ttm)} />
      <Rule />

      {/* Dividend Yield — stored as a decimal (0.004 = 0.4%); the formatter
          multiplies by 100. WHY unsigned: a yield is an allocation-style
          percentage — a "+" prefix would mis-read as a price change. Null for
          non-payers → "—" (honest: no dividend data ≠ 0% yield). */}
      <StatCell label="DIV YLD" value={formatPercentUnsigned(f?.dividend_yield)} />
      <Rule />

      {/* Beta — plain 2-dp ratio (1.09). From the snapshot leg. */}
      <StatCell label="BETA" value={formatRatio(s?.beta, "")} />
    </div>
  );
}
