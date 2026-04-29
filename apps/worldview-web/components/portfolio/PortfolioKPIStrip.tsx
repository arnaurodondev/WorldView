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
// F-P-012 (PLAN-0051 W6): the Day P&L tile uses Skeleton when the value is
// genuinely unknown (no quote yet) so users don't read "$0.00" as "market
// is flat" when in fact we just haven't received data yet.
import { Skeleton } from "@/components/ui/skeleton";

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
   *
   * PLAN-0051 T-A-1-05: this is now sourced from the S1
   * `/realized-pnl` endpoint via useRealizedPnL(); see the page wrapper
   * for the dispatch logic. When `realizedPnlApprox === true` the tile
   * appends a small "(approx)" badge so traders know the FIFO endpoint
   * was unavailable and they're looking at the legacy client-side
   * approximation (current-avg-cost basis, ignores closed positions).
   */
  realizedPnl?: number | null;
  /**
   * When true, the realized P&L value comes from the legacy client-side
   * approximation rather than the FIFO endpoint. Renders an "(approx)"
   * suffix on the tile. Default false.
   */
  realizedPnlApprox?: boolean;
  /** Long-term portion of realized P&L for the tooltip. Optional. */
  realizedPnlLongTerm?: number | null;
  /** Short-term portion of realized P&L for the tooltip. Optional. */
  realizedPnlShortTerm?: number | null;
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
  /**
   * F-P-012 (PLAN-0051 W6): optional ReactNode that overrides the string
   * value. Used by tiles that need to render a Skeleton (or any other
   * non-text element) when the value is unknown vs the genuine zero case.
   */
  valueNode?: React.ReactNode;
  /** Whether to color the value with text-positive (green) */
  positive?: boolean;
  /** Whether to color the value with text-negative (red) */
  negative?: boolean;
  /**
   * Optional native HTML title — renders as a hover tooltip. Used by the
   * Realized P&L tile to surface the long-term vs short-term breakdown
   * without occupying additional pixels in the tight 7-tile strip. Native
   * `title` is intentional rather than a Radix Tooltip: it requires zero
   * additional DOM, no portal, and surfaces in screen readers for free.
   */
  hoverTitle?: string;
  /**
   * Optional small muted suffix displayed inline after the value, e.g.
   * "(approx)" when the realized-P&L FIFO endpoint is unavailable and
   * we're showing the client-side approximation. Renders one font size
   * smaller and in muted-foreground so it doesn't dominate the tile.
   */
  suffix?: string;
  /** Test id passthrough so unit tests can target individual tiles. */
  dataTestId?: string;
}

function KPITile({
  label,
  value,
  valueNode,
  positive,
  negative,
  hoverTitle,
  suffix,
  dataTestId,
}: KPITileProps) {
  return (
    // F-P-017 (PLAN-0051 W6): consistent KPI tile padding.
    // The 6 tiles share py-1.5 (vertical) + px-3 (horizontal). DO NOT
    // diverge per-tile — the divide-x separators rely on identical tile
    // widths, and tighter/looser padding on one tile would visibly shift
    // the divider lines.
    <div
      className="flex flex-col px-3 py-1.5 flex-1 min-w-0"
      title={hoverTitle}
      data-testid={dataTestId}
    >
      {/* Label: 10px ALL CAPS muted — consistent with table header style */}
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground truncate">
        {label}
      </span>
      {/* Value: 14px mono — NOT text-primary for P&L (only tickers use text-primary).
          F-P-012: when ``valueNode`` is provided (e.g. Skeleton placeholder for
          the Day P&L unknown state) we render that instead of the string. The
          colour classes still apply but become a no-op for the Skeleton. */}
      <span
        className={cn(
          "font-mono text-[14px] tabular-nums font-medium truncate",
          positive && "text-positive",
          negative && "text-negative",
          !positive && !negative && "text-foreground",
        )}
      >
        {valueNode ?? value}
        {suffix && (
          // WHY ml-1 + smaller / muted: keep the headline number visually
          // dominant; the badge is metadata that shouldn't compete for
          // attention. tabular-nums isn't needed on a non-numeric badge.
          <span className="ml-1 text-[10px] font-normal text-muted-foreground">
            {suffix}
          </span>
        )}
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
  realizedPnlApprox = false,
  realizedPnlLongTerm = null,
  realizedPnlShortTerm = null,
}: PortfolioKPIStripProps) {
  // F-201 fix (PLAN-0048 QA iter-1): formatPercent already prepends "+" for
  // positive values (lib/utils.ts:81). The previous "+${formatPercent()}" wrap
  // produced "++30.92%" in the UNREALISED P&L tile. Just call formatPercent
  // directly — its sign output is already correct for traders' expectations.
  const pnlPctFormatted = formatPercent(unrealisedPnlPct);

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

      {/* Tile 2: Day P&L
          F-P-012 (PLAN-0051 W6): distinguish three states.
            - dayPnl === null/undefined → quotes haven't arrived yet → render
              a skeleton placeholder. Reading "$0.00" in this state previously
              misled users into thinking "market is flat" when in fact we
              just hadn't received data. The skeleton communicates "we're
              still working on it".
            - dayPnl === 0 → market is genuinely flat → render "$0.00" with
              neutral foreground colour (no positive/negative tint).
            - non-zero → coloured positive/negative.
          The render uses a custom valueNode prop so we can drop in a
          Skeleton element without coercing it to a string.
       */}
      <KPITile
        label="Day P&L"
        value={dayPnl == null ? "" : formatPrice(dayPnl)}
        valueNode={
          dayPnl == null ? (
            // WHY h-3 w-16: matches the ~14px font-medium height of the
            // populated value so the tile doesn't shift when data arrives.
            <Skeleton className="h-3 w-16" data-testid="kpi-day-pnl-skeleton" />
          ) : undefined
        }
        positive={dayPnl != null && dayPnl > 0}
        negative={dayPnl != null && dayPnl < 0}
        dataTestId="kpi-day-pnl"
      />

      {/* Tile 3: Unrealised P&L — absolute amount + percentage */}
      <KPITile
        label="Unrealised P&L"
        value={`${formatPrice(unrealisedPnl)} (${pnlPctFormatted})`}
        positive={unrealisedPnl > 0}
        negative={unrealisedPnl < 0}
      />

      {/* Tile 4: Realized P&L — FIFO-computed cumulative gain/loss across all
          SELL transactions in the date window (default = current calendar year).
          Distinct from Unrealised P&L: it captures what has already been locked
          in, not the mark-to-market on open positions. Shows "—" while the query
          is still loading (null) so traders aren't misled by $0.

          PLAN-0051 T-A-1-05:
            - The (approx) badge appears when the S1 endpoint errored and we
              fell back to the client-side approximation. The hover tooltip
              explains the degradation so traders don't silently trust a wrong
              number.
            - When the endpoint succeeds, the tooltip surfaces the long-term
              vs short-term breakdown for tax estimation, without spending
              another tile in the tight 7-tile strip. */}
      {(() => {
        // Build the tooltip text once. WHY in-line IIFE: keeps this branchy
        // string-building logic next to the tile it serves — easier to
        // read than a top-of-file helper that's only used once.
        let tooltip: string | undefined;
        if (realizedPnlApprox) {
          tooltip =
            "Backend unavailable — showing client-side approximation. " +
            "Closed positions and FIFO long/short-term split are not included.";
        } else if (
          realizedPnl != null &&
          (realizedPnlLongTerm != null || realizedPnlShortTerm != null)
        ) {
          const lt = realizedPnlLongTerm ?? 0;
          const st = realizedPnlShortTerm ?? 0;
          tooltip =
            `Long-term (>1y held): ${formatPrice(lt)}\n` +
            `Short-term (≤1y held): ${formatPrice(st)}`;
        }

        // WHY display "—" on approx + null: the requested behaviour from
        // T-A-1-05 — gracefully fall back to em-dash when the endpoint
        // erroed AND the client couldn't compute anything either. Showing
        // "$0" would mislead.
        const display =
          realizedPnl == null ? "—" : formatPrice(realizedPnl);

        return (
          <KPITile
            label="Realized P&L"
            value={display}
            positive={realizedPnl != null && realizedPnl > 0}
            negative={realizedPnl != null && realizedPnl < 0}
            hoverTitle={tooltip}
            suffix={realizedPnlApprox ? "(approx)" : undefined}
            dataTestId="kpi-realized-pnl"
          />
        );
      })()}

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
