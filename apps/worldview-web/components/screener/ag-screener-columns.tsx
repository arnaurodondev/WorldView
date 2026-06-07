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
import { formatCompact, formatPrice } from "@/lib/format";

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
  ];
}
