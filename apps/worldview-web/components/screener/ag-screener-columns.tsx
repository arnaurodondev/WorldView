/**
 * components/screener/ag-screener-columns.tsx — AG Grid ColDef factory for
 * the screener result table (Phase 5 AG Grid migration).
 *
 * WHY PARALLEL FILE (not replacing screener-columns.tsx): screener-columns.tsx
 * is still imported by instruments/page.tsx for the instruments table. Keeping
 * both files lets the screener migrate to AG Grid independently without
 * breaking the instrument table. screener-columns.tsx will be removed when all
 * consumers have migrated.
 *
 * WHY FACTORY FUNCTION: the sparkline column needs the per-instrument OHLCV
 * bars map fetched asynchronously. The factory closes over `sparklines`; the
 * caller wraps it in useMemo so columns only re-create when sparklines change.
 *
 * COLUMN GROUPS (Phase 5 requirement):
 *   Price group       — PRICE, CHG%
 *   Fundamentals group — MKT CAP, P/E, REVENUE, BETA
 * Standalone: TICKER (pinned left), NAME, SECTOR, SCORE (opt-in since Wave-2 —
 * no backend data source), 52W RANGE, VOLUME (latest 1d volume, brightness vs
 * 30d average), TREND (30D).
 *
 * WHO USES IT: app/(app)/screener/page.tsx
 */

import type { ColDef, ColGroupDef, ICellRendererParams } from "ag-grid-community";
import type { ScreenerResult, OHLCVBar } from "@/types/api";
// Wave-2 (2026-06-10): typed view of the new flat backend fields
// (volume, high_52w, low_52w). See lib/api/screener.ts for why the extension
// interface lives in the screener surface instead of types/api.ts.
import type { ScreenerRowEnriched } from "@/lib/api/screener";
import { HeatCell } from "./HeatCell";
import { MiniChart } from "./MiniChart";
import { cn } from "@/lib/utils";
// HF-10: formatPrice for locale-grouped USD output ("$4,892.11" not "$4892.11").
import { formatCompact, formatPrice } from "@/lib/format";

// ── IB-L3/L4 format helpers ───────────────────────────────────────────────────

/**
 * formatReturnPct — renders a decimal return (0.124 = +12.4%) as a signed
 * percent string with 1 decimal place.
 *
 * WHY this helper (not inline): eight return columns share the same format
 * rule. Centralising avoids eight copy-pastes and makes the threshold easy
 * to adjust. Returns "—" for null/undefined, which is consistent with every
 * other screener column (never shows "0%" for missing data).
 */
export function formatReturnPct(v: number | null | undefined): string {
  if (v == null) return "—";
  const pct = v * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

/**
 * formatInsiderCompact — renders an insider net buy/sell (USD) in compact
 * form with sign prefix.
 *
 * WHY null → "—" not "$0": only 3 instruments have insider data; null means
 * "no data" NOT "no transactions". Rendering "$0" for null would mislead
 * users into thinking there was zero net activity when it is simply unknown.
 *
 * Examples: 1_200_000 → "+$1.2M", -340_000 → "−$340K", null → "—"
 */
export function formatInsiderCompact(v: number | null | undefined): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const compact = formatCompact(abs, { adaptive: true, maxDecimals: 1 });
  // WHY Unicode minus (−) not hyphen: typographic convention for financial
  // negative values (matches Bloomberg terminal display).
  return v >= 0 ? `+$${compact}` : `−$${compact}`;
}

// ── Internal helper ───────────────────────────────────────────────────────────

function formatCap(val: number | null | undefined): string {
  return formatCompact(val, { adaptive: true, maxDecimals: 1 });
}

// ── Column pixel widths ───────────────────────────────────────────────────────

export const SCREENER_AG_COL_WIDTHS: Record<string, number> = {
  ticker: 70,
  name: 160,
  sector: 100,
  price: 80,
  change: 70,
  marketCap: 80,
  pe: 60,
  revenue: 80,
  beta: 55,
  score: 70,
  range52w: 100,
  volume: 80,
  sparkline: 70,
  // PRD-0089 Wave I new columns (design §3.4 mandatory new columns)
  divYield: 64,
  forwardPe: 64,
  roe: 64,
  revenueGrowth: 76,
  opMargin: 72,
  // IB-L3 — Returns + 52W distance (opt-in, not default visible)
  dist52wHigh: 68,
  dist52wLow: 68,
  return1m: 64,
  return3m: 64,
  return6m: 64,
  returnYtd: 64,
  return1y: 64,
  return3y: 64,
  // IB-L4 — Analyst / Insider / Ownership (opt-in)
  analystTarget: 76,
  analystUpside: 72,
  analystConsensus: 72,
  insiderNet90d: 76,
  instOwn: 68,
  shortPct: 64,
  // IB-L5 — Intelligence rollup (default visible: news7d + briefScore)
  news7d: 64,
  briefScore: 68,
};

// ── Cell renderer components ──────────────────────────────────────────────────
// Each is a plain React function. AG Grid calls them with ICellRendererParams.

function TickerCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  return (
    <span className="font-mono text-[11px] tabular-nums text-primary truncate">
      {data?.ticker}
    </span>
  );
}

function NameCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  return (
    <span className="text-[11px] text-foreground truncate">{data?.name}</span>
  );
}

function SectorCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  return (
    <span className="text-[11px] text-muted-foreground truncate">
      {data?.gics_sector ?? "—"}
    </span>
  );
}

function PriceCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.current_price;
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground">
      {formatPrice(v)}
    </span>
  );
}

function ChangeCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.daily_return;
  if (v == null) {
    return (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>
    );
  }
  const pct = v * 100;
  const isPos = pct > 0;
  const isNeg = pct < 0;
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center font-mono text-[10px] tabular-nums px-1 rounded-[2px]",
        isPos && "bg-positive/10 text-positive",
        isNeg && "bg-negative/10 text-negative",
        !isPos && !isNeg && "text-muted-foreground",
      )}
    >
      {pct >= 0 ? "+" : ""}
      {pct.toFixed(2)}%
    </span>
  );
}

function MarketCapCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground">
      {formatCap(data?.market_cap)}
    </span>
  );
}

function PeCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground">
      {data?.pe_ratio != null ? data.pe_ratio.toFixed(1) : "—"}
    </span>
  );
}

function RevenueCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground">
      {data?.revenue != null ? formatCap(data.revenue) : "—"}
    </span>
  );
}

function BetaCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.beta;
  if (v == null) {
    return (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>
    );
  }
  // DESIGN-QA S-4 (2026-06-18) — BETA is NON-DIRECTIONAL: render it NEUTRAL.
  //
  // WHY: beta was previously tinted `text-warning` (amber) at >1.5. Amber is
  // visually near-identical to the brand/active `--primary` yellow, so a "high
  // beta" heat signal collided with the column-active / preset-active yellow
  // and read ambiguously. More fundamentally, beta is a magnitude (volatility
  // vs the market), not a direction — there is no "good" or "bad" end the way
  // there is for a return. The design rule is to reserve teal/red/amber for
  // genuinely directional values (returns, day change, %-change) and keep
  // level metrics in neutral `text-foreground` tabular numbers. Users who want
  // to surface high-beta names can sort the column; colour is no longer doing
  // (ambiguous) double-duty.
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground">
      {v.toFixed(2)}
    </span>
  );
}

function ScoreCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  return <HeatCell score={data?.market_impact_score ?? null} />;
}

/**
 * Range52wCellRenderer — visual position bar showing where the current price
 * sits between the 52-week low and 52-week high.
 *
 * WHY percent bar (not min/max values): the screener column is only 100px wide;
 * showing two prices would be unreadable. A proportional bar communicates the
 * relative position (near high vs near low) at a glance — same idiom as
 * Finviz's 52W column.
 *
 * DERIVATION: the backend stores `dist_from_52w_low_pct` (positive = % above
 * 52w low) and `dist_from_52w_high_pct` (negative = % below 52w high). The
 * bar fill is calculated as:
 *   fill% = dist_low / (dist_low + |dist_high|)
 * which equals 100% when price == 52w high, 0% when price == 52w low.
 * If both distances are zero (at the high), fill% = 100%.
 */
function Range52wCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const distLow = data?.dist_from_52w_low_pct;
  const distHigh = data?.dist_from_52w_high_pct;

  // Both fields must be non-null to calculate a meaningful position.
  //
  // ROUND-1 FIX (2026-06-10): the null case used to render an EMPTY grey bar
  // track, which looks like "price is at the 52W low" — actively misleading.
  // Every other screener column renders an explicit "—" for missing data; the
  // 52W RANGE column now follows the same convention so the user can tell
  // "no data" apart from "at the low" at a glance.
  //
  // WHY this is usually null today (backend gap): dist_from_52w_low_pct /
  // dist_from_52w_high_pct are fundamental_metrics rows (section=
  // computed_returns), but the backend's no-filter `key_metrics` projection
  // in fundamental_metrics_query.py does NOT include them — they only appear
  // when the user actively filters on them. Until the backend adds them to
  // key_metrics this column shows "—" in the default view.
  if (distLow == null || distHigh == null) {
    return (
      <span
        className="font-mono text-[11px] tabular-nums text-muted-foreground"
        title="No 52W range data"
      >
        —
      </span>
    );
  }

  // distLow >= 0 (above low), distHigh <= 0 (below high, stored as negative fraction).
  // Total range = dist from low + dist from high (in absolute terms).
  const range = distLow + Math.abs(distHigh);
  // When price == 52w high both distances are 0; show 100%.
  const fillPct = range === 0 ? 100 : Math.min(100, Math.max(0, (distLow / range) * 100));

  // Colour: green when near high (>= 70%), amber in the middle, red near low (<= 30%).
  // All three are semantic design-system tokens (NEVER hardcoded hex) so the
  // bar follows the Terminal Dark palette automatically.
  const fillClass =
    fillPct >= 70
      ? "bg-positive/70"
      : fillPct <= 30
      ? "bg-negative/70"
      // WHY bg-warning/70 (not bg-amber-*): design system enforces palette
      // tokens; bg-warning maps to Bloomberg amber (#FFB000) — appropriate
      // for a "mid-range" position signal (not bullish/bearish).
      : "bg-warning/70";

  // ── Tooltip: exact 52W low / high prices (Wave-2: REAL values) ────────────
  // Wave-2 (2026-06-10): the Wave-1 backend now ships the ABSOLUTE 52W
  // high/low prices (`high_52w` / `low_52w`) on every row — default AND
  // filtered views (live coverage 200/200). Prefer them: the old derivation
  // (low = price / (1 + dist_low), high = price / (1 + dist_high)) needed a
  // live `current_price`, which only ~7% of instruments have — so the dollar
  // range was silently missing from almost every tooltip.
  //
  // WHY keep the derivation as a FALLBACK (not delete it): older cached
  // payloads / a backend rollback would otherwise lose the dollar range
  // entirely; the formula is still correct whenever a live price exists.
  const enriched = data as ScreenerRowEnriched | undefined;
  const realLow = enriched?.low_52w;
  const realHigh = enriched?.high_52w;
  const price = data?.current_price;
  let exactRange = "";
  if (realLow != null && realHigh != null) {
    // Primary path: absolute values straight from the backend.
    exactRange = ` | 52W low ${formatPrice(realLow)} — high ${formatPrice(realHigh)}`;
  } else if (price != null && 1 + distLow > 0 && 1 + distHigh > 0) {
    // Fallback path: derive from the live quote + relative distances.
    // (dist_high is stored as a negative fraction, so 1 + dist_high < 1 and
    // the derived high is correctly ABOVE the current price. The 1+x > 0
    // guards prevent division by ~0 when a distance is exactly -1.)
    const low52w = price / (1 + distLow);
    const high52w = price / (1 + distHigh);
    exactRange = ` | 52W low ${formatPrice(low52w)} — high ${formatPrice(high52w)}`;
  }

  const tooltipText = `52W position: ${fillPct.toFixed(0)}% of range (${(distLow * 100).toFixed(1)}% above low, ${(Math.abs(distHigh) * 100).toFixed(1)}% below high)${exactRange}`;

  return (
    // WHY a wrapper with title (not AG Grid tooltipField): tooltipField only
    // supports a single raw field; our tooltip is derived from three fields.
    // The native `title` attribute gives a browser hover tooltip with zero
    // extra dependencies — same idiom as the old implementation.
    <div className="h-1 bg-border rounded-none overflow-hidden w-full" title={tooltipText}>
      <div className={`h-full ${fillClass}`} style={{ width: `${fillPct}%` }} />
    </div>
  );
}

/**
 * volumeBrightnessClass — semantic text class for the VOLUME cell, driven by
 * the latest-volume / 30d-average ratio.
 *
 * WHY exported: the brightness rule is load-bearing UX (a dim cell must mean
 * "below-average activity", never a styling accident) — exporting lets the
 * unit tests pin the thresholds without mounting AG Grid.
 *
 * RULES (Wave-2, 2026-06-10):
 *   ratio ≥ 1   → "text-foreground"        (above/at average — full opacity,
 *                                            the row "lights up" on unusual
 *                                            activity, same idiom as Finviz's
 *                                            relative-volume highlighting)
 *   ratio < 1   → "text-muted-foreground"  (below average — dimmed, quiet day)
 *   no ratio    → "text-foreground"        (avg_volume_30d missing/zero: we
 *                                            cannot judge, so render neutral
 *                                            full opacity rather than implying
 *                                            "quiet" with a dim cell)
 *
 * WHY palette tokens (not opacity-NN utilities): the design system mandates
 * semantic tokens; text-muted-foreground IS the canonical "dimmed data" tint
 * used by every other muted cell in the screener.
 */
export function volumeBrightnessClass(
  volume: number | null | undefined,
  avgVolume30d: number | null | undefined,
): string {
  if (volume == null) return "text-muted-foreground"; // the "—" dash itself
  if (avgVolume30d == null || avgVolume30d <= 0) return "text-foreground";
  return volume / avgVolume30d >= 1 ? "text-foreground" : "text-muted-foreground";
}

/**
 * VolumeCellRenderer — displays the LATEST 1-day `volume` (Wave-2).
 *
 * WHY `volume` now (was avg_volume_30d): the Wave-1 backend added the latest
 * 1d bar volume to the screener payload — "VOLUME" meaning today's tape is
 * the universal terminal convention (Bloomberg/Finviz both show latest volume
 * in the VOLUME column and keep the average as a separate opt-in). The 30-day
 * average still rides along on every row (`avg_volume_30d`) and powers the
 * brightness signal below.
 *
 * BRIGHTNESS (Wave-2 requirement): cells render at full opacity when volume
 * is at/above the 30-day average and dimmed when below — an at-a-glance
 * "where is the action today" scan across the column. Exact thresholds live
 * in volumeBrightnessClass (exported for tests).
 *
 * DATA REALITY NOTE (2026-06-10): in the current seed dataset the latest 1d
 * bar volumes (~10³–10⁵) are orders of magnitude below the snapshot's
 * avg_volume_30d (~10⁶–10⁸ real-world figures), so most cells render dim.
 * That is the truthful output of the rule — flagged as a backend data-scale
 * gap in the Wave-2 report, NOT something to paper over here.
 */
function VolumeCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const row = data as ScreenerRowEnriched | undefined;
  const v = row?.volume;
  if (v == null) {
    return (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>
    );
  }
  const avg = row?.avg_volume_30d;
  // Hover detail: exact ratio so a power user can see HOW far above/below
  // average today's tape is (the colour alone is a 1-bit signal).
  const ratio = avg != null && avg > 0 ? v / avg : null;
  const title =
    ratio != null
      ? `Latest volume ${formatCompact(v, { adaptive: true, maxDecimals: 1 })} — ${ratio.toFixed(2)}× 30d avg`
      : `Latest volume ${formatCompact(v, { adaptive: true, maxDecimals: 1 })} (no 30d average to compare)`;
  // Compact format: 1_200_000 → "1.2M", 340_000 → "340K"
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        volumeBrightnessClass(v, avg),
      )}
      title={title}
    >
      {formatCompact(v, { adaptive: true, maxDecimals: 1 })}
    </span>
  );
}

// ── PRD-0089 Wave I: new fundamental column renderers ─────────────────────────
// All follow the "10px mono right-aligned, toFixed(1) + % suffix" design spec
// (docs/designs/0089/08-screener.md §3.4). Show "—" when value is null/undefined.

function DivYieldCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  // dividend_yield stored as decimal (0.015 = 1.5%); display as "1.5%"
  const v = data?.dividend_yield;
  if (v == null) {
    return <span className="font-mono text-[10px] tabular-nums text-muted-foreground">—</span>;
  }
  return (
    <span className="font-mono text-[10px] tabular-nums text-foreground">
      {(v * 100).toFixed(2)}%
    </span>
  );
}

function ForwardPeCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.forward_pe;
  if (v == null) {
    return <span className="font-mono text-[10px] tabular-nums text-muted-foreground">—</span>;
  }
  return (
    <span className="font-mono text-[10px] tabular-nums text-foreground">
      {v.toFixed(1)}
    </span>
  );
}

function RoeCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  // roe stored as decimal (0.15 = 15%); colour: green > 15%, red < 0%
  const v = data?.roe;
  if (v == null) {
    return <span className="font-mono text-[10px] tabular-nums text-muted-foreground">—</span>;
  }
  const pct = v * 100;
  // WHY color thresholds from design §6.3: ROE > 15 = productive equity use;
  // ROE < 0 = company is destroying value (losses).
  const isHigh = pct > 15;
  const isNeg = pct < 0;
  return (
    <span
      className={cn(
        "font-mono text-[10px] tabular-nums",
        isHigh ? "text-positive" : isNeg ? "text-negative" : "text-foreground",
      )}
    >
      {pct.toFixed(1)}%
    </span>
  );
}

function RevenueGrowthCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  // revenue_growth_yoy stored as decimal (0.124 = +12.4%); green > 0, red < 0
  const v = data?.revenue_growth_yoy;
  if (v == null) {
    return <span className="font-mono text-[10px] tabular-nums text-muted-foreground">—</span>;
  }
  const pct = v * 100;
  const isPos = pct > 0;
  const isNeg = pct < 0;
  return (
    <span
      className={cn(
        "font-mono text-[10px] tabular-nums",
        isPos ? "text-positive" : isNeg ? "text-negative" : "text-foreground",
      )}
    >
      {pct >= 0 ? "+" : ""}
      {pct.toFixed(1)}%
    </span>
  );
}

function OpMarginCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  // operating_margin stored as decimal; green > 20% (design §3.4)
  const v = data?.operating_margin;
  if (v == null) {
    return <span className="font-mono text-[10px] tabular-nums text-muted-foreground">—</span>;
  }
  const pct = v * 100;
  // WHY > 20%: operating margins above 20% signal strong competitive moat
  // (Apple ~30%, Google ~26%). Below 20% is typical/competitive; below 0 = loss-making.
  const isHigh = pct > 20;
  const isNeg = pct < 0;
  return (
    <span
      className={cn(
        "font-mono text-[10px] tabular-nums",
        isHigh ? "text-positive" : isNeg ? "text-negative" : "text-foreground",
      )}
    >
      {pct.toFixed(1)}%
    </span>
  );
}

// ── IB-L3 — Returns + 52W distance renderers ─────────────────────────────────
// All 8 follow the same "signed percent, +12.4% / −3.4% / —" pattern.
// Positive → text-positive (bull green), negative → text-negative (bear red).
// WHY text-[11px] (not text-[10px] as in IB-L2): the signed % glyphs are
// narrower than basis-point numbers; 11px keeps the column readable at 20px row height.

function ReturnPctCellRenderer({
  value,
}: {
  value: number | null | undefined;
}) {
  // WHY early-return for null: the backend may omit the field for instruments
  // computed before the nightly refresh. Show "—" to distinguish from 0%.
  if (value == null) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
  }
  const pct = value * 100;
  const isPos = pct > 0;
  const isNeg = pct < 0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isPos ? "text-positive" : isNeg ? "text-negative" : "text-foreground",
      )}
    >
      {formatReturnPct(value)}
    </span>
  );
}

// Individual wrappers read from the named AG Grid field prop. AG Grid passes
// `value` (the `field` accessor result) as a prop to cellRenderer functions.
function Dist52wHighCellRenderer(p: ICellRendererParams<ScreenerResult>) {
  return <ReturnPctCellRenderer value={p.data?.dist_from_52w_high_pct} />;
}
function Dist52wLowCellRenderer(p: ICellRendererParams<ScreenerResult>) {
  return <ReturnPctCellRenderer value={p.data?.dist_from_52w_low_pct} />;
}
function Return1mCellRenderer(p: ICellRendererParams<ScreenerResult>) {
  return <ReturnPctCellRenderer value={p.data?.return_1m} />;
}
function Return3mCellRenderer(p: ICellRendererParams<ScreenerResult>) {
  return <ReturnPctCellRenderer value={p.data?.return_3m} />;
}
function Return6mCellRenderer(p: ICellRendererParams<ScreenerResult>) {
  return <ReturnPctCellRenderer value={p.data?.return_6m} />;
}
function ReturnYtdCellRenderer(p: ICellRendererParams<ScreenerResult>) {
  return <ReturnPctCellRenderer value={p.data?.return_ytd} />;
}
function Return1yCellRenderer(p: ICellRendererParams<ScreenerResult>) {
  return <ReturnPctCellRenderer value={p.data?.return_1y} />;
}
function Return3yCellRenderer(p: ICellRendererParams<ScreenerResult>) {
  return <ReturnPctCellRenderer value={p.data?.return_3y} />;
}

// ── IB-L4 — Analyst / Insider / Ownership renderers ──────────────────────────

function AnalystTargetCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.analyst_target_price;
  if (v == null) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
  }
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground">
      {formatPrice(v)}
    </span>
  );
}

/**
 * AnalystUpsideCellRenderer — ANALYST UPSIDE is derived client-side.
 *
 * WHY client-side: the backend does NOT expose a pre-computed upside field.
 * The formula is (analyst_target_price / current_price) - 1. We need both
 * fields to be non-null; if either is missing we show "—".
 */
function AnalystUpsideCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const target = data?.analyst_target_price;
  const price = data?.current_price;
  if (target == null || price == null || price === 0) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
  }
  const upside = (target / price) - 1;
  const pct = upside * 100;
  const isPos = pct > 0;
  const isNeg = pct < 0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isPos ? "text-positive" : isNeg ? "text-negative" : "text-foreground",
      )}
    >
      {formatReturnPct(upside)}
    </span>
  );
}

/**
 * AnalystConsensusCellRenderer — 1–5 scale colour logic.
 *
 * WHY colour thresholds ≥4 / ≤2 (not a binary midpoint): the 1–5 analyst
 * scale maps to: 1=Strong Sell, 2=Sell, 3=Hold, 4=Buy, 5=Strong Buy.
 * ≥4 signals active Buy conviction; ≤2 signals active Sell conviction.
 * Hold (2.5–3.5) is left muted to avoid false signals on neutral ratings.
 */
function AnalystConsensusCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.analyst_consensus_rating;
  if (v == null) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
  }
  const isBull = v >= 4;
  const isBear = v <= 2;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isBull ? "text-positive" : isBear ? "text-negative" : "text-muted-foreground",
      )}
    >
      {v.toFixed(2)}
    </span>
  );
}

function InsiderNet90dCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.insider_net_buy_90d;
  // WHY null check before zero check: null means "no insider data" (only 3
  // instruments have coverage); 0 means "equal buy + sell in the 90d window".
  // They must render differently — "—" vs "$0" — to avoid misleading users.
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        v != null && v > 0 ? "text-positive"
          : v != null && v < 0 ? "text-negative"
          : "text-muted-foreground",
      )}
    >
      {formatInsiderCompact(v)}
    </span>
  );
}

function InstOwnCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  // institutional_ownership_pct stored as fraction (0.65 = 65%)
  const v = data?.institutional_ownership_pct;
  if (v == null) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
  }
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground">
      {(v * 100).toFixed(1)}%
    </span>
  );
}

function ShortPctCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  // short_percent stored as fraction (0.05 = 5%)
  const v = data?.short_percent;
  if (v == null) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
  }
  // WHY warning tint above 10%: elevated short interest (>10%) can signal
  // institutional skepticism OR a squeeze setup — flagging it without hiding
  // lets the user decide. Below 5% is standard (muted); 5–10% is elevated.
  const isHigh = v > 0.1;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isHigh ? "text-warning" : "text-foreground",
      )}
    >
      {(v * 100).toFixed(1)}%
    </span>
  );
}

// ── IB-L5 — Intelligence rollup renderers ────────────────────────────────────
// These two columns are DEFAULT VISIBLE (no `hide: true`). The rest of the
// IB-L5 fields (llm_relevance_7d_max, recent_contradiction_count, has_*)
// are filterable but have no dedicated column — the user can sort by them
// once the filter is active. Adding columns for all 7 would exceed DS-013's
// 14-column horizontal-scroll limit at 1440 px.

/**
 * News7dCellRenderer — displays `news_count_7d` (integer article count).
 *
 * WHY colour thresholds: ≥5 articles in 7 days is "active coverage" (positive
 * signal for liquidity / analyst attention). 0 articles = no coverage (muted).
 * The exact thresholds mirror the S6 "high-velocity" bucket definition.
 */
function News7dCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.news_count_7d;
  if (v == null) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
  }
  // DESIGN-QA S-3 (2026-06-18) — a news COUNT is NON-DIRECTIONAL: do not tint
  // it bull-green.
  //
  // WHY: this column was rendered `text-positive` (teal) at ≥5 articles. Teal
  // means "up / bullish" everywhere else in the terminal, so a high article
  // count looked like a positive *price* signal — it is not. High coverage can
  // be good (liquidity/attention) OR bad (a scandal breaking). Reusing the
  // bull/bear palette here dilutes what green/red mean on the columns where
  // they ARE directional (returns, CHG%).
  //
  // WHAT WE KEEP: a single NEUTRAL emphasis split — full-strength foreground
  // for any coverage, and a dimmed tint for the "dark" (0 articles) case so a
  // no-coverage row visibly recedes. This is brightness/heat, not bull/bear
  // colour, so it carries the "where is the action" scan value the audit
  // endorses without overloading the directional palette.
  const isDark = v === 0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isDark ? "text-muted-foreground/50" : "text-foreground",
      )}
    >
      {v}
    </span>
  );
}

/**
 * BriefScoreCellRenderer — displays `display_relevance_7d_weighted` (0–1 float).
 *
 * WHY 2 decimals: the score is a weighted blend of market impact + LLM relevance
 * + routing score (PRD-0026 §4.2). Two decimal places gives sufficient resolution
 * (0.85 vs 0.86) without implying false precision. Rendered as a plain decimal,
 * NOT as a percent — users already know it's a 0–1 score from the column header.
 *
 * Colour thresholds: ≥0.70 = high relevance (positive tint); <0.30 = low (muted).
 */
function BriefScoreCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.display_relevance_7d_weighted;
  if (v == null) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
  }
  // DESIGN-QA S-3 (2026-06-18) — the brief/relevance score is NON-DIRECTIONAL:
  // do not tint it bull-green.
  //
  // WHY: a high relevance score (0.84) was rendered `text-positive` (teal),
  // making it read as a bullish price signal. Relevance is a 0–1 quality
  // measure of how much active-narrative coverage an instrument has — high
  // relevance is just as likely to flag a name in crisis as one rallying. Same
  // reasoning as News7d above: reserve teal/red for directional values.
  //
  // WHAT WE KEEP: a neutral brightness split only — full foreground for any
  // score, dimmed for the low-relevance (<0.30) tail so quiet rows recede.
  const isLow = v < 0.3;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isLow ? "text-muted-foreground/60" : "text-foreground",
      )}
    >
      {v.toFixed(2)}
    </span>
  );
}

// Sparkline needs the sparklines map and a suppressed flag — built via factory
// closure so callers don't have to thread them through cellRendererParams.
//
// WHY suppressed parameter (FR-4.5 / DS-013): when >200 rows are loaded, we skip
// fetching sparkline data to avoid hammering S9 with 200+ OHLCV requests. Previously
// this left an empty flat grey line in the cell. Now we render an em-dash — consistent
// with every other "data not available" cell in the screener (price, beta, P/E all
// use "—"). The dash signals "intentionally not shown" vs the flat line which looks
// like broken data.
function createSparklineCellRenderer(
  sparklines: Record<string, OHLCVBar[]>,
  suppressed: boolean,
) {
  function SparklineCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
    // When suppressed (>200 rows), show an em-dash instead of an empty chart.
    // The dash communicates "intentionally omitted" rather than "no data" (flat line).
    if (suppressed) {
      return (
        <span className="font-mono text-[10px] text-muted-foreground/50">—</span>
      );
    }
    return (
      <MiniChart
        bars={sparklines[data?.instrument_id ?? ""]}
        ariaLabel={`${data?.ticker ?? ""} 30-day price trend`}
      />
    );
  }
  SparklineCellRenderer.displayName = "SparklineCellRenderer";
  return SparklineCellRenderer;
}

// ── Numeric column alignment (ROUND-1 item 4) ─────────────────────────────────

/**
 * NUMERIC_COL_IDS — every leaf column whose cell content is a number.
 *
 * WHY a Set + post-processing pass (not `type: "rightAligned"` repeated on 27
 * ColDefs): a single source of truth makes "is this column numeric?" auditable
 * at a glance and impossible to forget on one column. The post-processing pass
 * in `withNumericAlignment` applies AG Grid's built-in `rightAligned` column
 * type — which adds the `ag-right-aligned-cell` / `ag-right-aligned-header`
 * classes shipped in ag-grid.css — to each member.
 *
 * WHY right-aligned at all (finance convention): numbers in a column must share
 * a decimal axis so magnitudes compare vertically ("$1,234.56" vs "$12.34").
 * Left-aligned numerics make the leading digits line up instead, which hides
 * order-of-magnitude differences. Every terminal (Bloomberg, Finviz, Koyfin)
 * right-aligns numerics for this reason. ADR-F-15 additionally mandates
 * font-mono — already applied per-renderer via the `font-mono tabular-nums`
 * classes.
 *
 * Deliberately NOT in this set:
 *   ticker / name / sector — text, left-aligned
 *   score                  — HeatCell visual badge (centred by its own layout)
 *   range52w               — proportional bar fills the full cell width
 *   sparkline              — chart fills the full cell width
 */
export const NUMERIC_COL_IDS: ReadonlySet<string> = new Set([
  "price",
  "change",
  "marketCap",
  "pe",
  "revenue",
  "beta",
  "divYield",
  "forwardPe",
  "roe",
  "revenueGrowth",
  "opMargin",
  "dist52wHigh",
  "dist52wLow",
  "return1m",
  "return3m",
  "return6m",
  "returnYtd",
  "return1y",
  "return3y",
  "analystTarget",
  "analystUpside",
  "analystConsensus",
  "insiderNet90d",
  "instOwn",
  "shortPct",
  "news7d",
  "briefScore",
  "volume",
]);

/**
 * withNumericAlignment — apply `type: "rightAligned"` to every leaf ColDef
 * whose colId is in NUMERIC_COL_IDS. Recurses one level into column groups
 * (the screener has no nested groups beyond depth 1).
 *
 * WHY mutate copies (spread) instead of in-place: the input array is built
 * fresh on every factory call, but copying keeps this function pure so tests
 * can call it with fixture ColDefs without surprising shared-state effects.
 */
function withNumericAlignment(
  defs: (ColDef<ScreenerResult> | ColGroupDef<ScreenerResult>)[],
): (ColDef<ScreenerResult> | ColGroupDef<ScreenerResult>)[] {
  const alignLeaf = (col: ColDef<ScreenerResult>): ColDef<ScreenerResult> =>
    col.colId && NUMERIC_COL_IDS.has(col.colId)
      ? { ...col, type: "rightAligned" }
      : col;

  return defs.map((def) => {
    // ColGroupDef is distinguished by the presence of `children`.
    if ("children" in def) {
      return {
        ...def,
        children: def.children.map((child) => alignLeaf(child as ColDef<ScreenerResult>)),
      };
    }
    return alignLeaf(def);
  });
}

// ── Column factory ────────────────────────────────────────────────────────────

/**
 * createAgScreenerColumns — build the AG Grid ColDef list for the screener.
 *
 * @param sparklines   Map from instrument_id → 30d OHLCV bars.
 *                     Pass {} when the sparkline column is hidden or suppressed
 *                     (>200 rows). Same contract as the TanStack factory.
 * @param suppressed   When true (>200 rows loaded), the sparkline cell renders
 *                     an em-dash instead of a flat grey line. Communicates
 *                     "intentionally omitted" rather than "data missing"
 *                     (FR-4.5 / DS-013).
 *
 * Column layout:
 *   TICKER (pinned-left) | NAME | SECTOR | [Price: PRICE CHG%] |
 *   [Fundamentals: MKT CAP P/E REVENUE BETA] | SCORE | 52W RANGE | VOLUME |
 *   TREND (30D)
 */
export function createAgScreenerColumns(
  sparklines: Record<string, OHLCVBar[]>,
  suppressed = false,
): (ColDef<ScreenerResult> | ColGroupDef<ScreenerResult>)[] {
  // WHY withNumericAlignment wrapper: applies AG Grid's built-in
  // `rightAligned` column type to every numeric column in one auditable pass
  // (ROUND-1 item 4 — see NUMERIC_COL_IDS above for the rationale).
  return withNumericAlignment([
    // ── TICKER — pinned left, not movable ────────────────────────────────────
    {
      colId: "ticker",
      headerName: "TICKER",
      field: "ticker",
      pinned: "left" as const,
      lockPinned: true,
      suppressMovable: true,
      sortable: true,
      resizable: false,
      width: SCREENER_AG_COL_WIDTHS.ticker,
      cellRenderer: TickerCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    // ── NAME ─────────────────────────────────────────────────────────────────
    {
      colId: "name",
      headerName: "NAME",
      field: "name",
      sortable: true,
      // DESIGN-QA S-2 (2026-06-18) — fill the right-side whitespace.
      //
      // WHY flex on NAME: with the default column set the summed fixed widths
      // stopped well short of the viewport, leaving ~35-40% of the grid as a
      // black void on the right — the audit's most "unfinished" look. AG Grid
      // distributes leftover horizontal space to any column with `flex`, so
      // marking NAME flexible makes the grid ALWAYS span the full container
      // width regardless of how many columns the user has toggled on. NAME is
      // the natural absorber: company names are variable-length text that
      // genuinely benefit from extra room (less truncation), unlike the
      // fixed-width numeric columns where a stretched cell would just add dead
      // padding around a right-aligned number.
      //
      // WHY keep `width` as the flex BASIS + a minWidth floor: `width` still
      // seeds the initial/basis size and minWidth stops NAME from collapsing
      // below readability when many opt-in columns are enabled and the grid
      // overflows into horizontal scroll (at which point flex yields and the
      // fixed minimum applies). When few columns are shown, NAME simply grows
      // to consume the slack instead of leaving a gutter.
      flex: 1,
      minWidth: SCREENER_AG_COL_WIDTHS.name,
      width: SCREENER_AG_COL_WIDTHS.name,
      cellRenderer: NameCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    // ── SECTOR ───────────────────────────────────────────────────────────────
    {
      colId: "sector",
      headerName: "SECTOR",
      field: "gics_sector",
      sortable: true,
      width: SCREENER_AG_COL_WIDTHS.sector,
      cellRenderer: SectorCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    // ── PRICE group ──────────────────────────────────────────────────────────
    {
      headerName: "PRICE",
      groupId: "priceGroup",
      children: [
        {
          colId: "price",
          headerName: "PRICE",
          field: "current_price",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.price,
          cellRenderer: PriceCellRenderer,
        },
        {
          colId: "change",
          headerName: "CHG%",
          field: "daily_return",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.change,
          cellRenderer: ChangeCellRenderer,
        },
      ],
    } satisfies ColGroupDef<ScreenerResult>,

    // ── FUNDAMENTALS group ────────────────────────────────────────────────────
    {
      headerName: "FUNDAMENTALS",
      groupId: "fundamentalsGroup",
      children: [
        {
          colId: "marketCap",
          headerName: "MKT CAP",
          field: "market_cap",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.marketCap,
          cellRenderer: MarketCapCellRenderer,
        },
        {
          colId: "pe",
          headerName: "P/E",
          headerTooltip: "Price-to-Earnings Ratio (TTM)",
          field: "pe_ratio",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.pe,
          cellRenderer: PeCellRenderer,
        },
        {
          colId: "revenue",
          headerName: "REVENUE",
          field: "revenue",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.revenue,
          cellRenderer: RevenueCellRenderer,
        },
        {
          colId: "beta",
          headerName: "BETA",
          headerTooltip: "Beta vs S&P 500",
          field: "beta",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.beta,
          cellRenderer: BetaCellRenderer,
        },
      ],
    } satisfies ColGroupDef<ScreenerResult>,

    // ── PRD-0089 Wave I: new fundamental columns ─────────────────────────────
    // These columns are in the FUNDAMENTALS group per design §4 wireframe.
    // They are added as a separate group to maintain the existing group structure.
    {
      headerName: "RATIOS",
      groupId: "ratiosGroup",
      // WHY a second group (not inline in FUNDAMENTALS): the design spec §4
      // places DIV Y, FWD PE, ROE, REV YoY, OP MGN in columns 8-12 while
      // MKT CAP, P/E, BETA stay in the FUNDAMENTALS group (cols 6-7, 11).
      // Keeping them separate lets ColumnSettingsPopover hide/show each group.
      children: [
        {
          colId: "divYield",
          headerName: "DIV Y%",
          headerTooltip: "Annual Dividend Yield",
          field: "dividend_yield",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.divYield,
          cellRenderer: DivYieldCellRenderer,
        },
        {
          colId: "forwardPe",
          headerName: "FWD PE",
          headerTooltip: "Forward Price-to-Earnings (NTM)",
          field: "forward_pe",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.forwardPe,
          cellRenderer: ForwardPeCellRenderer,
        },
        {
          colId: "roe",
          headerName: "ROE%",
          headerTooltip: "Return on Equity (TTM)",
          field: "roe",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.roe,
          cellRenderer: RoeCellRenderer,
        },
        {
          colId: "revenueGrowth",
          headerName: "REV YoY",
          headerTooltip: "Quarterly Revenue Growth Year-over-Year",
          field: "revenue_growth_yoy",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.revenueGrowth,
          cellRenderer: RevenueGrowthCellRenderer,
        },
        {
          colId: "opMargin",
          headerName: "OP MGN%",
          headerTooltip: "Operating Margin (TTM)",
          field: "operating_margin",
          sortable: true,
          width: SCREENER_AG_COL_WIDTHS.opMargin,
          cellRenderer: OpMarginCellRenderer,
        },
      ],
    } satisfies ColGroupDef<ScreenerResult>,

    // ── PERFORMANCE / TECHNICAL group (IB-L3) ───────────────────────────────
    // All 8 columns are opt-in (not default visible). They live in a separate
    // group so ColumnSettingsPopover can show/hide them as a block.
    // WHY "Performance / Technical": the group name mirrors Bloomberg's
    // "PERF" section, covering both absolute returns and 52W position metrics.
    {
      headerName: "PERFORMANCE",
      groupId: "performanceGroup",
      children: [
        {
          colId: "dist52wHigh",
          headerName: "52W%↑",
          headerTooltip: "% distance from 52-week high (negative = below high)",
          field: "dist_from_52w_high_pct",
          sortable: true,
          // WHY hide: opt-in column — showing all 8 by default would exceed the
          // 14-column horizontal-scroll limit at 1440px (DS-013 guard).
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.dist52wHigh,
          cellRenderer: Dist52wHighCellRenderer,
        },
        {
          colId: "dist52wLow",
          headerName: "52W%↓",
          headerTooltip: "% distance from 52-week low (positive = above low)",
          field: "dist_from_52w_low_pct",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.dist52wLow,
          cellRenderer: Dist52wLowCellRenderer,
        },
        {
          colId: "return1m",
          headerName: "1M RTN",
          headerTooltip: "1-month total return",
          field: "return_1m",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.return1m,
          cellRenderer: Return1mCellRenderer,
        },
        {
          colId: "return3m",
          headerName: "3M RTN",
          headerTooltip: "3-month total return",
          field: "return_3m",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.return3m,
          cellRenderer: Return3mCellRenderer,
        },
        {
          colId: "return6m",
          headerName: "6M RTN",
          headerTooltip: "6-month total return",
          field: "return_6m",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.return6m,
          cellRenderer: Return6mCellRenderer,
        },
        {
          colId: "returnYtd",
          headerName: "YTD RTN",
          headerTooltip: "Year-to-date total return",
          field: "return_ytd",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.returnYtd,
          cellRenderer: ReturnYtdCellRenderer,
        },
        {
          colId: "return1y",
          headerName: "1Y RTN",
          headerTooltip: "1-year total return",
          field: "return_1y",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.return1y,
          cellRenderer: Return1yCellRenderer,
        },
        {
          colId: "return3y",
          headerName: "3Y RTN",
          headerTooltip: "3-year total return",
          field: "return_3y",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.return3y,
          cellRenderer: Return3yCellRenderer,
        },
      ],
    } satisfies ColGroupDef<ScreenerResult>,

    // ── ANALYST / INSIDER / OWNERSHIP group (IB-L4) ─────────────────────────
    // 5 backend fields + 1 client-side derived (ANALYST UPSIDE). All opt-in.
    // WHY ANALYST UPSIDE in the same group: it depends on analyst_target_price
    // and current_price (both available in the row payload); co-locating it
    // with the target column makes the relationship clear.
    {
      headerName: "OWNERSHIP",
      groupId: "ownershipGroup",
      children: [
        {
          colId: "analystTarget",
          // DESIGN-QA S-5 (2026-06-18): "ANALYST TGT" + "ANALYST UPSIDE" both
          // truncated to "ANALYST …" in the 76/72px columns, leaving two
          // indistinguishable headers. Use short, distinct labels that fit:
          // the group band already reads OWNERSHIP, so the per-column unit is
          // what disambiguates ("TGT $" = target price, "UPSIDE %" = upside).
          headerName: "TGT $",
          headerTooltip: "Analyst consensus target price (USD)",
          field: "analyst_target_price",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.analystTarget,
          cellRenderer: AnalystTargetCellRenderer,
        },
        {
          colId: "analystUpside",
          // DESIGN-QA S-5: distinct short label (see analystTarget above).
          headerName: "UPSIDE %",
          headerTooltip: "Analyst upside: (target / price) - 1. Derived client-side.",
          // ROUND-1 item 5 (2026-06-10): previously `sortable: false` because
          // there is no single backend field to sort on. AG Grid's valueGetter
          // solves this — it computes the derived value per row, and the grid
          // sorts on the computed result. This makes EVERY numeric column
          // sortable, as the round spec requires. (Filtering on upside is
          // still deferred to v2 per the design spec — only sort is enabled.)
          valueGetter: (p) => {
            const target = p.data?.analyst_target_price;
            const price = p.data?.current_price;
            // null (not 0) when underivable so AG Grid sorts missing values
            // together rather than interleaving them with real 0% upsides.
            if (target == null || price == null || price === 0) return null;
            return target / price - 1;
          },
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.analystUpside,
          cellRenderer: AnalystUpsideCellRenderer,
        },
        {
          colId: "analystConsensus",
          headerName: "CONSENSUS",
          headerTooltip: "Analyst consensus rating (1=Strong Sell → 5=Strong Buy)",
          field: "analyst_consensus_rating",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.analystConsensus,
          cellRenderer: AnalystConsensusCellRenderer,
        },
        {
          colId: "insiderNet90d",
          headerName: "INSIDER 90D",
          headerTooltip: "Net insider buy/sell (USD) over past 90 days. — = no data.",
          field: "insider_net_buy_90d",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.insiderNet90d,
          cellRenderer: InsiderNet90dCellRenderer,
        },
        {
          colId: "instOwn",
          headerName: "INST OWN%",
          headerTooltip: "Institutional ownership as % of float",
          field: "institutional_ownership_pct",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.instOwn,
          cellRenderer: InstOwnCellRenderer,
        },
        {
          colId: "shortPct",
          headerName: "SHORT %",
          headerTooltip: "Short interest as % of float. >10% = elevated (warning tint).",
          field: "short_percent",
          sortable: true,
          hide: true,
          width: SCREENER_AG_COL_WIDTHS.shortPct,
          cellRenderer: ShortPctCellRenderer,
        },
      ],
    } satisfies ColGroupDef<ScreenerResult>,

    // ── INTELLIGENCE group (IB-L5) ───────────────────────────────────────────
    // WHY 2 columns default-visible (no `hide: true`): NEWS 7D and BRIEF SCORE
    // are the highest-signal outputs of the intelligence rollup — surfacing them
    // by default shows the value of IB-L5 without overwhelming the 14-column
    // horizontal-scroll limit (DS-013). The remaining IB-L5 fields are available
    // as filter constraints (see build-filters.ts) but have no dedicated column.
    {
      headerName: "INTELLIGENCE",
      groupId: "intelligenceGroup",
      children: [
        {
          colId: "news7d",
          headerName: "NEWS 7D",
          headerTooltip: "Article count in the past 7 days (from S6 content-store rollup)",
          field: "news_count_7d",
          sortable: true,
          // WHY no `hide`: default-visible per IB-L5 spec. Shows coverage signal
          // immediately without requiring the user to enable a column first.
          width: SCREENER_AG_COL_WIDTHS.news7d,
          cellRenderer: News7dCellRenderer,
        },
        {
          colId: "briefScore",
          headerName: "BRIEF SCORE",
          headerTooltip:
            "Weighted display relevance (0–1): blend of market impact + LLM relevance + routing score (PRD-0026 §4.2). Higher = more relevant to active market narratives.",
          field: "display_relevance_7d_weighted",
          sortable: true,
          // WHY no `hide`: default-visible — this is the primary intelligence
          // quality signal the L-5b rollup produces, worth showing by default.
          width: SCREENER_AG_COL_WIDTHS.briefScore,
          cellRenderer: BriefScoreCellRenderer,
        },
      ],
    } satisfies ColGroupDef<ScreenerResult>,

    // ── SCORE — HIDDEN BY DEFAULT (Wave-2 decision, 2026-06-10) ──────────────
    // market_impact_score has NO data source anywhere in the backend (confirmed
    // during the Wave-2 audit: the field is absent from every live row, default
    // AND filtered — the PRD-0020 price-impact labelling pipeline that was meant
    // to feed it never shipped a projection into the screener payload). A
    // column that is permanently "—" for 100% of rows erodes trust in every
    // OTHER dash in the table ("is that one fake too?"), so it must not ship
    // in the default view.
    //
    // WHY hide:true here AND visible:false in lib/screener-columns.ts:
    //   - `hide: true` makes the DEFAULT deterministic at first paint (the
    //     header-count tests assert synchronously, before onGridReady applies
    //     localStorage prefs).
    //   - The prefs entry keeps the column in ColumnSettingsPopover so a user
    //     can still opt in once the backend ships the score (the ColDef +
    //     HeatCell renderer are fully functional — only the data is missing).
    {
      colId: "score",
      headerName: "SCORE",
      headerTooltip:
        "Market Impact Score (0–1) — no backend data source yet; column is opt-in until the scoring pipeline ships.",
      field: "market_impact_score",
      sortable: true,
      hide: true,
      width: SCREENER_AG_COL_WIDTHS.score,
      cellRenderer: ScoreCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    // ── 52W RANGE ─────────────────────────────────────────────────────────────
    {
      colId: "range52w",
      headerName: "52W RANGE",
      headerTooltip: "52-Week Price Range — proportional bar showing position between 52W low (left) and 52W high (right). Data from nightly OHLCV-derived snapshot.",
      // WHY no field: cell renderer reads two fields (dist_from_52w_low_pct and
      // dist_from_52w_high_pct) to draw the bar. AG Grid field accessor is
      // single-field; a valueGetter computes the derived position instead.
      // ROUND-1 item 5: valueGetter returns the position-in-range fraction
      // (0 = at 52W low, 1 = at 52W high) so the column is sortable — sorting
      // ranks instruments by how close they trade to their yearly high.
      valueGetter: (p) => {
        const lo = p.data?.dist_from_52w_low_pct;
        const hi = p.data?.dist_from_52w_high_pct;
        if (lo == null || hi == null) return null;
        const span = lo + Math.abs(hi);
        return span === 0 ? 1 : Math.min(1, Math.max(0, lo / span));
      },
      sortable: true,
      resizable: false,
      width: SCREENER_AG_COL_WIDTHS.range52w,
      cellRenderer: Range52wCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    // ── VOLUME ────────────────────────────────────────────────────────────────
    // Wave-2: field switched avg_volume_30d → volume (latest 1d bar volume,
    // new in the Wave-1 backend payload). Sorting therefore ranks by today's
    // tape; brightness (full vs dim) encodes today-vs-30d-average — see
    // VolumeCellRenderer.
    {
      colId: "volume",
      headerName: "VOLUME",
      headerTooltip:
        "Latest daily volume. Bright = at/above 30-day average volume; dim = below average.",
      field: "volume",
      sortable: true,
      width: SCREENER_AG_COL_WIDTHS.volume,
      cellRenderer: VolumeCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    // ── SPARKLINE ─────────────────────────────────────────────────────────────
    {
      colId: "sparkline",
      headerName: "TREND (30D)",
      headerTooltip: "30-day Price Trend",
      sortable: false,
      resizable: false,
      width: SCREENER_AG_COL_WIDTHS.sparkline,
      // Pass suppressed flag so the renderer shows "—" instead of an empty flat
      // line when >200 rows are loaded (FR-4.5 / DS-013).
      cellRenderer: createSparklineCellRenderer(sparklines, suppressed),
    } satisfies ColDef<ScreenerResult>,
  ]);
}
