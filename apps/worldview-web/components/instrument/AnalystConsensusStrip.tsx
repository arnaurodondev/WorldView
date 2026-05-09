/**
 * components/instrument/AnalystConsensusStrip.tsx — Analyst consensus row
 *
 * WHY THIS EXISTS: The Fundamentals tab needs an Analyst Consensus section above
 * the metrics grid. Analyst Strong Buy / Buy / Hold / Sell / Strong Sell counts
 * plus the consensus 12-month price target are critical for institutional
 * decision-making (Bloomberg BEST function equivalent, Finviz "Recom" pill).
 *
 * AUDIT 2026-05-09: Until this revision, the component rendered the literal
 * string "Analyst consensus data unavailable" unconditionally — even when the
 * underlying API DID return analyst_consensus data. The fix below:
 *   1) reads the new analyst_* fields off the Fundamentals shape (now
 *      populated by the getFundamentals transformer);
 *   2) renders a horizontal stacked-bar of the 5 consensus buckets with
 *      Bloomberg-style colour coding (Strong Buy = vivid green … Strong Sell
 *      = vivid red);
 *   3) shows the consensus 12-month price target with a delta vs the current
 *      price.
 *
 * WHY ALWAYS RENDER (not return null when no data): The section header should
 * always appear so analysts know the category is tracked. When the data is
 * genuinely missing (newly listed stocks, ADRs without coverage) we render an
 * empty-state strip so the layout remains visually consistent.
 *
 * WHO USES IT: FundamentalsTab.tsx (full-width section above the metrics grid)
 * DATA SOURCE: Props (Fundamentals.analyst_*) — assembled by S3 from EODHD's
 *              analyst_consensus section and surfaced through S9.
 */

// WHY no "use client": pure display component — no hooks, no browser APIs.

import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { formatPrice, formatPercent } from "@/lib/utils";
import type { Fundamentals } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface AnalystConsensusStripProps {
  fundamentals: Fundamentals | null;
  /**
   * Current market price — used to compute the upside/downside delta vs the
   * consensus 12-month target. When null, the delta column is omitted.
   */
  currentPrice?: number | null;
}

// Bloomberg-style 5-bucket recommendation palette. Five hex literals, one per
// bucket, ordered Strong Buy → Strong Sell. WHY hex (not CSS vars): SVG
// rendering and inline style backgroundColor don't resolve CSS variables.
const BUCKET_COLORS = [
  "#16A34A", // Strong Buy   — vivid green
  "#65A30D", // Buy          — lime
  "#A1A1AA", // Hold         — neutral grey
  "#EA580C", // Sell         — orange
  "#DC2626", // Strong Sell  — vivid red
] as const;

const BUCKET_LABELS = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"] as const;

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalystConsensusStrip({
  fundamentals,
  currentPrice,
}: AnalystConsensusStripProps) {
  // Header is always rendered (Bloomberg convention).
  const Header = (
    <div className="flex items-center border-b border-border px-2 h-6">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        ANALYST CONSENSUS
      </span>
    </div>
  );

  // ── No fundamentals object at all — typically still loading ─────────────────
  if (!fundamentals) {
    return (
      <div>
        {Header}
        <InlineEmptyState
          message="Analyst consensus data pending"
          className="px-2 py-1.5 text-[11px]"
        />
      </div>
    );
  }

  // Build the 5 buckets. We treat null counts as 0 for the bar geometry but
  // also track whether ANY count was non-null — if all are null, EODHD has no
  // coverage for this ticker and we render a friendly empty state.
  // WHY const buckets: keeps the source-of-truth in one place so the bar
  // segments and the legend pills can iterate over the same array.
  const buckets = [
    { label: BUCKET_LABELS[0], color: BUCKET_COLORS[0], count: fundamentals.analyst_strong_buy_count },
    { label: BUCKET_LABELS[1], color: BUCKET_COLORS[1], count: fundamentals.analyst_buy_count },
    { label: BUCKET_LABELS[2], color: BUCKET_COLORS[2], count: fundamentals.analyst_hold_count },
    { label: BUCKET_LABELS[3], color: BUCKET_COLORS[3], count: fundamentals.analyst_sell_count },
    { label: BUCKET_LABELS[4], color: BUCKET_COLORS[4], count: fundamentals.analyst_strong_sell_count },
  ];

  const totalCount = buckets.reduce((sum, b) => sum + (b.count ?? 0), 0);
  const anyData = buckets.some((b) => b.count != null && b.count > 0);

  // ── No coverage — render empty state but keep the section header ───────────
  if (!anyData) {
    return (
      <div>
        {Header}
        <InlineEmptyState
          message="No analyst coverage available for this ticker"
          className="px-2 py-1.5 text-[11px]"
        />
      </div>
    );
  }

  // ── Target price delta vs current price ────────────────────────────────────
  // Only render when we have BOTH a target and a current price; otherwise we'd
  // mislead the user with a partial number.
  const target = fundamentals.analyst_target_price;
  const tgtDelta =
    target != null && currentPrice != null && currentPrice > 0
      ? (target - currentPrice) / currentPrice
      : null;
  const tgtDeltaClass =
    tgtDelta == null
      ? "text-muted-foreground"
      : tgtDelta > 0
        ? "text-positive"
        : tgtDelta < 0
          ? "text-negative"
          : "text-foreground";

  return (
    <div>
      {Header}

      {/* Two-row layout — bar on top, legend + target-price line below.
          WHY two rows (not one): the 5-bucket legend is too wide to fit
          alongside the bar at 1280px viewport. Stacking gives every bucket
          room to breathe and keeps the bar full-width. */}
      <div className="px-2 py-1.5 space-y-1.5">
        {/* ── Stacked horizontal bar ──────────────────────────────────────
            One <span> per non-zero bucket. Width is proportional to the
            bucket's share of total analysts. Zero-count buckets are simply
            omitted (don't render a 0%-width segment that browsers may still
            paint as 1px). The flex container with h-2 sets the bar height. */}
        <div className="flex h-2 w-full overflow-hidden rounded-[2px] bg-muted/40">
          {buckets.map((b) => {
            const count = b.count ?? 0;
            if (count <= 0) return null;
            const widthPct = (count / totalCount) * 100;
            return (
              <span
                key={b.label}
                style={{ width: `${widthPct}%`, backgroundColor: b.color }}
                title={`${b.label}: ${count}`}
              />
            );
          })}
        </div>

        {/* ── Legend + target price row ───────────────────────────────────
            Legend pills on the left, target price + delta on the right.
            Tabular-nums on the right column keeps prices column-aligned. */}
        <div className="flex items-center gap-3 text-[10px] font-mono">
          {/* Legend — only buckets with non-zero counts */}
          <div className="flex items-center gap-2 flex-wrap">
            {buckets.map((b) => {
              const count = b.count ?? 0;
              if (count <= 0) return null;
              return (
                <div key={b.label} className="flex items-center gap-1">
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-[1px]"
                    style={{ backgroundColor: b.color }}
                  />
                  <span className="text-muted-foreground uppercase tracking-[0.06em]">
                    {b.label}
                  </span>
                  <span className="text-foreground tabular-nums">{count}</span>
                </div>
              );
            })}
            {/* Total count anchor — useful at a glance for "thinly covered" tickers */}
            <span className="text-muted-foreground/70">
              · {totalCount} analyst{totalCount === 1 ? "" : "s"}
            </span>
          </div>

          {/* ── Right-aligned target price block ─────────────────────────── */}
          {target != null && (
            <div className="ml-auto flex items-center gap-2 tabular-nums">
              <span className="text-muted-foreground uppercase tracking-[0.06em]">
                Target
              </span>
              <span className="text-foreground">{formatPrice(target)}</span>
              {tgtDelta != null && (
                <span className={tgtDeltaClass}>
                  {tgtDelta >= 0 ? "▲" : "▼"} {formatPercent(Math.abs(tgtDelta))}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
