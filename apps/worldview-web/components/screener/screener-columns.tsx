/**
 * components/screener/screener-columns.tsx — TanStack ColumnDef factory for the screener
 *
 * WHY THIS EXISTS: The universal DataTable primitive (components/ui/data-table)
 * requires ColumnDef<TData>[] rather than the bespoke ScreenerColumn[] shape that
 * the old ScreenerTable used. This factory maps all 13 screener columns to
 * TanStack ColumnDef objects with correct accessorFns, sort config, cell renderers,
 * and pixel sizes — keeping cell logic centralised so instruments/page.tsx and
 * screener/page.tsx share the same rendering without re-implementing it.
 *
 * WHY FACTORY FUNCTION (not constant array): the sparkline column needs access to
 * a per-instrument OHLCV bars map that is fetched asynchronously. The factory
 * captures `sparklines` in a closure; callers wrap it in `useMemo` so the columns
 * array only re-creates when sparklines change (not on every render).
 *
 * WHY sortUndefined: "last" + null→undefined in accessorFn: TanStack Table's
 * `sortUndefined` config places undefined values at the end in BOTH asc and desc
 * directions — matching the "nulls last" contract of the previous sortResults()
 * helper. We coerce null→undefined so TanStack treats both as "no data".
 *
 * WHY TYPES RE-EXPORTED HERE: SortState, SortDir, SortableKey were previously
 * in ScreenerTable.tsx. Moving them here avoids a now-deleted dependency while
 * keeping instruments/page.tsx and screener/page.tsx imports one line change.
 *
 * WHO USES IT: app/(app)/screener/page.tsx, app/(app)/instruments/page.tsx
 * DATA SOURCE: POST /v1/fundamentals/screen + POST /v1/quotes/bars/batch (sparklines)
 * DESIGN REFERENCE: PRD-0031 §7 Screener columns
 */

import type { ColumnDef } from "@tanstack/react-table";
import type { ScreenerResult, OHLCVBar } from "@/types/api";
import { HeatCell } from "./HeatCell";
import { MiniChart } from "./MiniChart";
import { cn } from "@/lib/utils";
// PLAN-0059 C-5: canonical compact formatter (1-decimal adaptive style like ScreenerTable).
import { formatCompact } from "@/lib/format";

// ── Sort types (re-exported from previous ScreenerTable home) ─────────────────

/** SortDir — the three states a column sort cycles through */
export type SortDir = "asc" | "desc" | null;

/** SortState — current sort key + direction; null/null = unsorted */
export interface SortState {
  key: SortableKey | null;
  dir: SortDir;
}

/**
 * SortableKey — column keys that the screener supports sorting by.
 *
 * WHY not keyof ScreenerResult: the table column keys ("price", "change")
 * differ from the API field names ("current_price", "daily_return"). TanStack
 * sorts via accessorFn which maps these to the correct ScreenerResult fields.
 */
export type SortableKey =
  | "ticker"
  | "name"
  | "sector"
  | "price"
  | "change"
  | "marketCap"
  | "pe"
  | "revenue"
  | "beta"
  | "score";

// ── Internal helpers ──────────────────────────────────────────────────────────

/**
 * formatCap — abbreviated market cap / revenue (e.g. 2.3T, 450B, 8.5M).
 * Delegates to canonical formatCompact with 1-decimal adaptive style.
 */
function formatCap(val: number | null | undefined): string {
  return formatCompact(val, { adaptive: true, maxDecimals: 1 });
}

// ── Column pixel widths ───────────────────────────────────────────────────────

/**
 * COLUMN_PIXEL_WIDTHS — fixed pixel widths per column key (number, not "Npx").
 *
 * WHY pixel-fixed (not flex): financial tables need horizontal alignment that
 * doesn't shift when filtering changes the data. Pixel-fixed columns keep
 * "9.43" sitting in the same x-position as "12.70" across all rows.
 * TanStack Table `size` accepts a number (DataTable converts to px via style).
 */
export const COLUMN_PIXEL_WIDTHS: Record<string, number> = {
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
};

/**
 * HEADER_TITLES — native browser tooltip copy for abbreviated column headers.
 * Shown on hover via HTML `title` attribute — no JS tooltip library needed
 * for headers since users hover column names while learning the screener.
 */
const HEADER_TITLES: Partial<Record<string, string>> = {
  pe: "Price-to-Earnings Ratio (TTM)",
  score: "Market Impact Score (0–1)",
  range52w: "52-Week Price Range (backend pending)",
  volume: "Average Volume (backend pending)",
  sparkline: "30-day Price Trend",
  beta: "Beta vs S&P 500",
};

// ── Column factory ────────────────────────────────────────────────────────────

/**
 * createScreenerColumns — build the 13 TanStack ColumnDef objects for the
 * screener result table.
 *
 * @param sparklines - Map from instrument_id → 30d OHLCV bars. Pass {} when
 *   the sparkline column is hidden or suppressed (>200 rows).
 */
export function createScreenerColumns(
  sparklines: Record<string, OHLCVBar[]>,
): ColumnDef<ScreenerResult>[] {
  return [
    // ── TICKER ──────────────────────────────────────────────────────────────
    {
      id: "ticker",
      // WHY accessorFn: TanStack needs the sort value separate from the cell
      // renderer. accessorFn returns the raw string; `cell` renders styled JSX.
      accessorFn: (row) => row.ticker,
      // WHY sortUndefined: "last": if ticker is ever undefined/null, put it at
      // the bottom of the list (same as sortResults() null-last contract).
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.ticker,
      enableSorting: true,
      header: () => <span title={HEADER_TITLES.ticker}>TICKER</span>,
      cell: ({ row }) => (
        // WHY text-primary: ticker is the navigation key — primary color signals
        // clickability to traders used to Bloomberg's amber action links.
        <span className="font-mono text-[11px] tabular-nums text-primary truncate">
          {row.original.ticker}
        </span>
      ),
    },

    // ── NAME ────────────────────────────────────────────────────────────────
    {
      id: "name",
      accessorFn: (row) => row.name,
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.name,
      enableSorting: true,
      header: () => <span>NAME</span>,
      cell: ({ row }) => (
        <span className="text-[11px] text-foreground truncate">{row.original.name}</span>
      ),
    },

    // ── SECTOR ──────────────────────────────────────────────────────────────
    {
      id: "sector",
      // WHY null→undefined: gics_sector is nullable; coerce to undefined so
      // sortUndefined: "last" handles it (TanStack only checks for undefined,
      // not null, when applying the sortUndefined config).
      accessorFn: (row) => row.gics_sector ?? undefined,
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.sector,
      enableSorting: true,
      header: () => <span>SECTOR</span>,
      cell: ({ row }) => (
        <span className="text-[11px] text-muted-foreground truncate">
          {row.original.gics_sector ?? "—"}
        </span>
      ),
    },

    // ── PRICE ───────────────────────────────────────────────────────────────
    {
      id: "price",
      accessorFn: (row) => row.current_price ?? undefined,
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.price,
      enableSorting: true,
      header: () => <span>PRICE</span>,
      cell: ({ row }) => {
        const v = row.original.current_price;
        return (
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            {v != null ? `$${v.toFixed(2)}` : "—"}
          </span>
        );
      },
    },

    // ── CHANGE% ─────────────────────────────────────────────────────────────
    {
      id: "change",
      accessorFn: (row) => row.daily_return ?? undefined,
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.change,
      enableSorting: true,
      header: () => <span>CHG%</span>,
      cell: ({ row }) => {
        const v = row.original.daily_return;
        if (v == null) {
          return (
            <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>
          );
        }
        const pct = v * 100;
        const isPos = pct > 0;
        const isNeg = pct < 0;
        return (
          // WHY pill with bg-tint: directional change pills are an institutional
          // convention (tastytrade, TradingView). The bg-tint communicates direction
          // in peripheral vision before the trader reads the digits.
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
      },
    },

    // ── MARKET CAP ──────────────────────────────────────────────────────────
    {
      id: "marketCap",
      accessorFn: (row) => row.market_cap ?? undefined,
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.marketCap,
      enableSorting: true,
      header: () => <span>MKT CAP</span>,
      cell: ({ row }) => (
        <span className="font-mono text-[11px] tabular-nums text-foreground">
          {formatCap(row.original.market_cap)}
        </span>
      ),
    },

    // ── P/E ─────────────────────────────────────────────────────────────────
    {
      id: "pe",
      accessorFn: (row) => row.pe_ratio ?? undefined,
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.pe,
      enableSorting: true,
      // WHY title attribute: the column header "P/E" is an abbreviation that
      // novice analysts may not recognise. Native browser tooltip on hover
      // provides the full label without additional UI weight.
      header: () => <span title={HEADER_TITLES.pe}>P/E</span>,
      cell: ({ row }) => (
        <span className="font-mono text-[11px] tabular-nums text-foreground">
          {row.original.pe_ratio != null ? row.original.pe_ratio.toFixed(1) : "—"}
        </span>
      ),
    },

    // ── REVENUE ─────────────────────────────────────────────────────────────
    {
      id: "revenue",
      accessorFn: (row) => row.revenue ?? undefined,
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.revenue,
      enableSorting: true,
      header: () => <span>REVENUE</span>,
      cell: ({ row }) => (
        <span className="font-mono text-[11px] tabular-nums text-foreground">
          {row.original.revenue != null ? formatCap(row.original.revenue) : "—"}
        </span>
      ),
    },

    // ── BETA ────────────────────────────────────────────────────────────────
    {
      id: "beta",
      accessorFn: (row) => row.beta ?? undefined,
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.beta,
      enableSorting: true,
      header: () => <span title={HEADER_TITLES.beta}>BETA</span>,
      cell: ({ row }) => {
        const v = row.original.beta;
        if (v == null) {
          return (
            <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>
          );
        }
        // WHY color-coded beta: > 1.5 = high risk (warning); < 0.5 = defensive (muted).
        // Allows instant visual triage during a screener scan.
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
      },
    },

    // ── SCORE ───────────────────────────────────────────────────────────────
    {
      id: "score",
      accessorFn: (row) => row.market_impact_score ?? undefined,
      sortUndefined: "last",
      size: COLUMN_PIXEL_WIDTHS.score,
      enableSorting: true,
      header: () => <span title={HEADER_TITLES.score}>SCORE</span>,
      // WHY HeatCell: the 0–1 score maps to a heat color strip that lets traders
      // rank relative signal strength at a glance without parsing individual numbers.
      cell: ({ row }) => <HeatCell score={row.original.market_impact_score} />,
    },

    // ── 52W RANGE ───────────────────────────────────────────────────────────
    {
      id: "range52w",
      // WHY no accessorFn: backend-pending field — no ScreenerResult property yet.
      size: COLUMN_PIXEL_WIDTHS.range52w,
      enableSorting: false,
      // WHY enableResizing: false — this placeholder column has no real data
      // and will be replaced when the backend delivers the 52W range endpoint.
      // Allowing resize would let users expand an empty column, which is confusing.
      enableResizing: false,
      header: () => <span title={HEADER_TITLES.range52w}>52W RANGE</span>,
      cell: () => (
        // WHY placeholder bar (not "—"): the range bar conveys intent — a visual
        // channel exists here and will be populated by real data. A dash would
        // suggest the column is intentionally empty, not pending.
        <div className="h-1 bg-border rounded-none overflow-hidden w-full" title="Backend pending">
          <div className="h-full bg-muted-foreground/20 w-0" />
        </div>
      ),
    },

    // ── VOLUME ──────────────────────────────────────────────────────────────
    {
      id: "volume",
      // WHY no accessorFn: backend-pending field.
      size: COLUMN_PIXEL_WIDTHS.volume,
      enableSorting: false,
      header: () => <span title={HEADER_TITLES.volume}>VOLUME</span>,
      cell: () => (
        <span
          className="font-mono text-[11px] tabular-nums text-muted-foreground"
          title="Backend pending"
        >
          —
        </span>
      ),
    },

    // ── SPARKLINE ───────────────────────────────────────────────────────────
    {
      id: "sparkline",
      // WHY no accessorFn: sparklines are NOT part of ScreenerResult — they come
      // from a separate /quotes/bars/batch fetch. The closure captures the current
      // sparklines map (updated via useMemo in the page when the batch response changes).
      size: COLUMN_PIXEL_WIDTHS.sparkline,
      enableSorting: false,
      enableResizing: false,
      header: () => <span title={HEADER_TITLES.sparkline}>TREND (30D)</span>,
      cell: ({ row }) => (
        <MiniChart
          bars={sparklines[row.original.instrument_id]}
          ariaLabel={`${row.original.ticker} 30-day price trend`}
        />
      ),
    },
  ];
}
