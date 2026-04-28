/**
 * components/portfolio/PortfolioKPIStrip.tsx — 6-tile KPI bar for the portfolio page
 *
 * WHY THIS EXISTS: Traders need an instant snapshot of their book's health without
 * clicking through tabs. Six KPI tiles — total value, day P&L, unrealised P&L,
 * top gainer, top loser, and position count — answer the four key "how am I doing?"
 * questions in one horizontal bar, always visible above the tab content.
 *
 * WHY 6 TILES (not 4): Bloomberg's portfolio header shows similar density. The
 * previous PnlSummaryRow (4 tiles) omitted Top Gainer/Top Loser and position count,
 * which are the most actionable pieces of information for an active portfolio manager.
 *
 * WHY divide-x (not gap/grid): divide-x produces 1px vertical separators between tiles
 * with no risk of tile widths diverging. It's the terminal-native way to subdivide
 * a horizontal band — see Bloomberg's port header or Refinitiv's portfolio overview.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — always rendered above Tabs
 * DATA SOURCE: Computed from holdings + live quotes + transactions in the parent page
 * DESIGN REFERENCE: PRD-0031 §8.1 Portfolio KPI Strip, Wave 4
 */

"use client";
// WHY "use client": cn() is fine server-side, but this file is always rendered
// inside a "use client" page (portfolio/page.tsx), so it inherits that boundary.

import { cn } from "@/lib/utils";
import { formatPrice, formatPercent } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PortfolioKPIStripProps {
  /** Total market value of all holdings (qty × live price) */
  totalValue: number;
  /** Absolute day P&L across all positions; null when quotes not yet loaded */
  dayPnl: number | null;
  /** Unrealised P&L = total value − total cost basis */
  unrealisedPnl: number;
  /** Unrealised P&L as a fraction (e.g. 0.0482 = +4.82%) */
  unrealisedPnlPct: number;
  /** Holding with highest unrealised P&L% (top winner); null when no holdings */
  topGainer: { ticker: string; pnlPct: number } | null;
  /** Holding with lowest unrealised P&L% (biggest loser); null when no holdings */
  topLoser: { ticker: string; pnlPct: number } | null;
  /** Number of open positions */
  positionCount: number;
  /**
   * Realized P&L summed across all SELL transactions (price − avg_cost) × qty.
   * null when transactions have not yet loaded or cannot be computed.
   * WHY optional/null: transactions query may not have resolved; the tile shows "—"
   * rather than a misleading $0 in that case.
   */
  realizedPnl?: number | null;
}

// ── KPI tile ──────────────────────────────────────────────────────────────────

/**
 * KPITile — single tile in the strip
 *
 * WHY `flex-1 min-w-0`: flex-1 spreads tiles evenly; min-w-0 prevents a long
 * value string from pushing the tile wider than its share of the strip.
 */
interface KPITileProps {
  label: string;
  value: string;
  /** Whether to color the value with text-positive (green) */
  positive?: boolean;
  /** Whether to color the value with text-negative (red) */
  negative?: boolean;
}

function KPITile({ label, value, positive, negative }: KPITileProps) {
  return (
    <div className="flex flex-col px-3 py-1.5 flex-1 min-w-0">
      {/* Label: 10px ALL CAPS muted — consistent with table header style */}
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground truncate">
        {label}
      </span>
      {/* Value: 14px mono — NOT text-primary for P&L (only tickers use text-primary) */}
      <span
        className={cn(
          "font-mono text-[14px] tabular-nums font-medium truncate",
          positive && "text-positive",
          negative && "text-negative",
          !positive && !negative && "text-foreground",
        )}
      >
        {value}
      </span>
    </div>
  );
}

// ── PortfolioKPIStrip ─────────────────────────────────────────────────────────

export function PortfolioKPIStrip({
  totalValue,
  dayPnl,
  unrealisedPnl,
  unrealisedPnlPct,
  topGainer,
  topLoser,
  positionCount,
  realizedPnl,
}: PortfolioKPIStripProps) {
  // WHY format unrealisedPnlPct with explicit sign:
  // Traders expect +4.82% not 4.82% — the sign is part of the meaning.
  const pnlPctFormatted =
    unrealisedPnlPct >= 0
      ? `+${formatPercent(unrealisedPnlPct)}`
      : formatPercent(unrealisedPnlPct);

  return (
    // WHY border-b: the KPI strip sits between the page header and the tab bar.
    // A bottom border creates the visual divider expected by terminal UX patterns.
    // WHY divide-x divide-border: 1px separator between each tile — no gaps, no cards.
    // WHY bg-card: now that the parent page is bg-background (#09090B) the strip
    // needs an explicit panel-tone background so the 7-tile band reads as a
    // distinct chrome surface, not a darker continuation of the page. Same
    // pattern as the dashboard KPI strip.
    <div className="flex divide-x divide-border border-b border-border shrink-0 bg-card">
      {/* Tile 1: Total Value — no color (neutral fact) */}
      <KPITile
        label="Total Value"
        value={formatPrice(totalValue)}
      />

      {/* Tile 2: Day P&L — colored positive/negative; "—" when quotes not yet available */}
      <KPITile
        label="Day P&L"
        value={dayPnl == null ? "—" : formatPrice(dayPnl)}
        positive={dayPnl != null && dayPnl > 0}
        negative={dayPnl != null && dayPnl < 0}
      />

      {/* Tile 3: Unrealised P&L — absolute amount + percentage */}
      <KPITile
        label="Unrealised P&L"
        value={`${formatPrice(unrealisedPnl)} (${pnlPctFormatted})`}
        positive={unrealisedPnl > 0}
        negative={unrealisedPnl < 0}
      />

      {/* Tile 4: Realized P&L — sum of (sell_price − avg_cost) × qty across all SELL
          transactions. Distinct from Unrealised P&L: it captures what has already
          been locked in, not the mark-to-market on open positions. Shows "—" while
          the transactions query is still loading (null) so traders aren't misled by $0. */}
      <KPITile
        label="Realized P&L"
        value={realizedPnl == null ? "—" : formatPrice(realizedPnl)}
        positive={realizedPnl != null && realizedPnl > 0}
        negative={realizedPnl != null && realizedPnl < 0}
      />

      {/* Tile 5: Top Gainer — best performer in the book; always green when present
          WHY pnlPct / 100: the stored value is already a percentage (e.g. 4.82),
          so formatPercent (which multiplies by 100) would over-scale it. */}
      <KPITile
        label="Top Gainer"
        value={
          topGainer
            // WHY no leading "+": formatPercent already prefixes positive values
            // with "+" (lib/utils.ts:81). Adding another "+" produced "++143.70%".
            ? `${topGainer.ticker} ${formatPercent(topGainer.pnlPct / 100)}`
            : "—"
        }
        positive={topGainer != null}
      />

      {/* Tile 6: Top Loser — worst performer; always red when present */}
      <KPITile
        label="Top Loser"
        value={
          topLoser
            ? `${topLoser.ticker} ${formatPercent(topLoser.pnlPct / 100)}`
            : "—"
        }
        negative={topLoser != null}
      />

      {/* Tile 7: # Positions — quick book-size reference */}
      <KPITile
        label="# Positions"
        value={String(positionCount)}
      />
    </div>
  );
}
