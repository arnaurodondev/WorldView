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
 * Standalone: TICKER (pinned left), NAME, SECTOR, SCORE, 52W RANGE, VOLUME,
 * TREND (30D).
 *
 * WHO USES IT: app/(app)/screener/page.tsx
 */

import type { ColDef, ColGroupDef, ICellRendererParams } from "ag-grid-community";
import type { ScreenerResult, OHLCVBar } from "@/types/api";
import { HeatCell } from "./HeatCell";
import { MiniChart } from "./MiniChart";
import { cn } from "@/lib/utils";
// HF-10: formatPrice for locale-grouped USD output ("$4,892.11" not "$4892.11").
import { formatCompact, formatCompactCurrency, formatPrice } from "@/lib/format";
// PRD-0089 Wave I-B Block IB-L2 (T-IB-05/T-IB-07): credit rating tone helper —
// shared between the badge column cell renderer and the future filter chip
// active-selection display in ScreenerFilterBar.
import { creditRatingTone } from "@/lib/screener/credit-rating";

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
  // PRD-0089 Wave I-B Block IB-L2 (T-IB-05): 6 opt-in fundamentals snapshot
  // columns + 1 credit-rating badge column. Widths chosen so a fully-loaded
  // dense layout (≤14 visible columns) still fits in a 1440px viewport
  // without horizontal scroll — see plan §6.3.
  avgVol: 80,           // "50M"     compact integer
  epsTtm: 70,           // "6.32"    2dp
  fcf: 80,              // "$1.2B"   compact currency
  fcfMargin: 80,        // "28.4%"   percent 1dp
  interestCoverage: 80, // "2.1×"    multiple
  netDebtToEbitda: 90,  // "2.1×"    multiple (header is wider so 90px not 80)
  creditRating: 80,     // "AA-"     badge
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
  // > 1.5 = elevated risk (warning tint); < 0.5 = defensive (muted).
  const isHigh = v > 1.5;
  const isLow = v < 0.5;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isHigh ? "text-warning" : isLow ? "text-muted-foreground" : "text-foreground",
      )}
    >
      {v.toFixed(2)}
    </span>
  );
}

function ScoreCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  return <HeatCell score={data?.market_impact_score ?? null} />;
}

function Range52wCellRenderer() {
  return (
    <div
      className="h-1 bg-border rounded-none overflow-hidden w-full"
      title="Backend pending"
    >
      <div className="h-full bg-muted-foreground/20 w-0" />
    </div>
  );
}

function VolumeCellRenderer() {
  return (
    <span
      className="font-mono text-[11px] tabular-nums text-muted-foreground"
      title="Backend pending"
    >
      —
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

// ── PRD-0089 Wave I-B Block IB-L2 — fundamentals snapshot cell renderers ─────
// All six renderers below read from `instrument_fundamentals_snapshot` via
// Wave L-2 backend (commits e1a0193f / 39058058 / 4ce5feec). The S9 gateway
// `_flatten_screener_result` (services/api-gateway/.../routes/market.py)
// already promotes nested `metrics.{key}` to top-level fields on the
// ScreenerResult row, so we read `data?.avg_volume_30d` etc directly.
//
// Every cell honours finance-grade UX requirements:
//   - `font-mono tabular-nums` so digits align across rows (column scanning).
//   - `text-[11px]` matches the rest of the screener for visual density.
//   - Null → "—" (em-dash) — the platform-wide "data not available" sentinel.
//   - NO off-palette greens / ambers / reds — only Terminal Dark `text-*`
//     semantic tokens (positive / warning / negative / muted-foreground).

function _Em() {
  // WHY a sub-component: keeps the dash rendering one line per cell renderer
  // below. The styling matches existing renderers (PeCellRenderer etc).
  return (
    <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>
  );
}

// AVG VOL → compact integer ("50M"). WHY no currency: it's a share count.
function AvgVolCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  // `as` cast: TypeScript indexer on ScreenerResult is `unknown` because of
  // the [key:string]: unknown wildcard. We narrow to number|null|undefined
  // here at the boundary — the format helpers do their own runtime check.
  const v = data?.avg_volume_30d as number | null | undefined;
  if (v == null) return <_Em />;
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground">
      {formatCompact(v, { adaptive: true, maxDecimals: 0 })}
    </span>
  );
}

// EPS (TTM) → 2 decimal places. WHY 2dp: institutional convention for
// earnings-per-share. EPS rarely needs more than two significant digits at
// a glance. Negative EPS is tinted negative to flag loss-makers immediately.
function EpsTtmCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.eps_ttm as number | null | undefined;
  if (v == null) return <_Em />;
  const isLoss = v < 0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isLoss ? "text-negative" : "text-foreground",
      )}
    >
      {v.toFixed(2)}
    </span>
  );
}

// FCF → compact USD currency ("$1.2B"). Negative FCF is tinted negative —
// burn-rate signal at row-scan time.
function FcfCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.free_cash_flow as number | null | undefined;
  if (v == null) return <_Em />;
  const isBurn = v < 0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isBurn ? "text-negative" : "text-foreground",
      )}
    >
      {formatCompactCurrency(v, "USD", { adaptive: true, maxDecimals: 1 })}
    </span>
  );
}

// FCF MGN% → percent, 1dp. WHY assume backend sends fraction (0.284) not
// percent (28.4): the backend `fcf_margin` is computed as fcf/revenue, both
// raw USD figures, so the ratio is a fraction. Consistent with the existing
// `dividend_yield` UI which the FilterBar treats as a decimal. If S3 ever
// flips to percent we update this single multiplier.
function FcfMarginCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const v = data?.fcf_margin as number | null | undefined;
  if (v == null) return <_Em />;
  // WHY heuristic |v| > 1.5: a margin of 150% is unrealistic — if we ever
  // see one we assume the backend sent percent (28.4) not fraction (0.284)
  // and skip the *100. Defensive guard against silent contract drift.
  const pct = Math.abs(v) > 1.5 ? v : v * 100;
  const isNegative = pct < 0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isNegative ? "text-negative" : "text-foreground",
      )}
    >
      {pct.toFixed(1)}%
    </span>
  );
}

// INT COV → multiple ("2.1×"). Below 1.0 = EBIT can't cover interest → red.
function InterestCoverageCellRenderer({
  data,
}: ICellRendererParams<ScreenerResult>) {
  const v = data?.interest_coverage as number | null | undefined;
  if (v == null) return <_Em />;
  // <1.0 means earnings don't even cover the interest bill — distress signal.
  const isDistress = v < 1.0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums",
        isDistress ? "text-negative" : "text-foreground",
      )}
    >
      {v.toFixed(1)}×
    </span>
  );
}

// ND/EBITDA → multiple. Conventional thresholds:
//   - <0    → net cash (very safe) — muted foreground (not "positive" to
//             avoid over-claiming; cash-rich balance sheet is good but the
//             column also returns positive #s for net debt). We keep all
//             non-distressed values neutral.
//   - >4    → highly levered, restructuring risk — warning
//   - >6    → distressed — negative
function NetDebtEbitdaCellRenderer({
  data,
}: ICellRendererParams<ScreenerResult>) {
  const v = data?.net_debt_to_ebitda as number | null | undefined;
  if (v == null) return <_Em />;
  const tone =
    v > 6 ? "text-negative" : v > 4 ? "text-warning" : "text-foreground";
  return (
    <span className={cn("font-mono text-[11px] tabular-nums", tone)}>
      {v.toFixed(1)}×
    </span>
  );
}

// CREDIT RATING → badge cell. WHY a coloured pill (not raw text): credit
// analysts read AA- as "investment grade safe" and CCC as "imminent default"
// at a glance — the tone tier is the load-bearing signal, the rating string
// is the supporting detail. The pill mirrors the CHG% styling so the visual
// rhythm of "tinted background + tinted text" stays consistent.
function CreditRatingCellRenderer({ data }: ICellRendererParams<ScreenerResult>) {
  const raw = data?.credit_rating as string | null | undefined;
  if (raw == null || raw === "") return <_Em />;
  const tone = creditRatingTone(raw);
  // WHY explicit className-per-tone (not template literal): Tailwind's
  // content-scan can't resolve `text-${tone}` dynamically. Listing each
  // string literally ensures the JIT compiler emits the CSS.
  const toneClass =
    tone === "positive"
      ? "bg-positive/10 text-positive"
      : tone === "warning"
        ? "bg-warning/10 text-warning"
        : "bg-negative/10 text-negative";
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center font-mono text-[10px] tabular-nums px-1 rounded-[2px]",
        toneClass,
      )}
    >
      {raw}
    </span>
  );
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
  return [
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

    // ── SCORE ─────────────────────────────────────────────────────────────────
    {
      colId: "score",
      headerName: "SCORE",
      headerTooltip: "Market Impact Score (0–1)",
      field: "market_impact_score",
      sortable: true,
      width: SCREENER_AG_COL_WIDTHS.score,
      cellRenderer: ScoreCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    // ── 52W RANGE ─────────────────────────────────────────────────────────────
    {
      colId: "range52w",
      headerName: "52W RANGE",
      headerTooltip: "52-Week Price Range (backend pending)",
      sortable: false,
      resizable: false,
      width: SCREENER_AG_COL_WIDTHS.range52w,
      cellRenderer: Range52wCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    // ── VOLUME ────────────────────────────────────────────────────────────────
    {
      colId: "volume",
      headerName: "VOLUME",
      headerTooltip: "Average Volume (backend pending)",
      sortable: false,
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

    // ── PRD-0089 Wave I-B Block IB-L2 opt-in columns ─────────────────────────
    // All seven below are HIDDEN BY DEFAULT in `lib/screener-columns.ts` via
    // the visible:false flag. The user reveals them through the
    // ColumnSettingsPopover (⚙ icon). AG-Grid still creates the ColDef so
    // toggling visibility doesn't require a column-array re-build — only a
    // visibility flip via `gridApi.setColumnsVisible`.
    //
    // SORTABILITY: the Wave L-2 backend (`fundamental_metrics_query.py:348`)
    // recognises all 6 numeric snap field names as valid `sort_by` values.
    // `credit_rating` is not numerically sortable today (alpha-only order
    // would be misleading "AA" < "BB") — left non-sortable.

    {
      colId: "avgVol",
      headerName: "AVG VOL",
      headerTooltip: "Average daily trading volume over the past 30 days",
      field: "avg_volume_30d",
      sortable: true,
      width: SCREENER_AG_COL_WIDTHS.avgVol,
      cellRenderer: AvgVolCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    {
      colId: "epsTtm",
      headerName: "EPS (TTM)",
      headerTooltip: "Earnings per share — trailing twelve months",
      field: "eps_ttm",
      sortable: true,
      width: SCREENER_AG_COL_WIDTHS.epsTtm,
      cellRenderer: EpsTtmCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    {
      colId: "fcf",
      headerName: "FCF",
      headerTooltip: "Free Cash Flow (operating cash flow minus capex)",
      field: "free_cash_flow",
      sortable: true,
      width: SCREENER_AG_COL_WIDTHS.fcf,
      cellRenderer: FcfCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    {
      colId: "fcfMargin",
      headerName: "FCF MGN%",
      headerTooltip: "Free cash flow as a percentage of revenue",
      field: "fcf_margin",
      sortable: true,
      width: SCREENER_AG_COL_WIDTHS.fcfMargin,
      cellRenderer: FcfMarginCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    {
      colId: "interestCoverage",
      headerName: "INT COV",
      headerTooltip: "EBIT ÷ interest expense; <1× indicates earnings don't cover interest",
      field: "interest_coverage",
      sortable: true,
      width: SCREENER_AG_COL_WIDTHS.interestCoverage,
      cellRenderer: InterestCoverageCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    {
      colId: "netDebtToEbitda",
      headerName: "ND/EBITDA",
      headerTooltip: "(Total debt − cash) ÷ EBITDA; negative = net cash position",
      field: "net_debt_to_ebitda",
      sortable: true,
      width: SCREENER_AG_COL_WIDTHS.netDebtToEbitda,
      cellRenderer: NetDebtEbitdaCellRenderer,
    } satisfies ColDef<ScreenerResult>,

    {
      colId: "creditRating",
      headerName: "CREDIT",
      headerTooltip: "S&P / EODHD credit rating (AAA…D)",
      field: "credit_rating",
      // WHY non-sortable: a lexical sort would order "AA" before "BB" before
      // "CCC" but lose the credit-tier semantics ("AA-" < "B+" is wrong if
      // compared alphabetically because '-' < '+' in ASCII). Wave L-2's
      // `sort_by` whitelist correctly excludes credit_rating.
      sortable: false,
      width: SCREENER_AG_COL_WIDTHS.creditRating,
      cellRenderer: CreditRatingCellRenderer,
    } satisfies ColDef<ScreenerResult>,
  ];
}
