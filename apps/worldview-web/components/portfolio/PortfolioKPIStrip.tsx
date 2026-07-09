/**
 * components/portfolio/PortfolioKPIStrip.tsx — 8-tile KPI bar for the portfolio page
 *
 * WHY THIS EXISTS: Traders need an instant snapshot of their book's health without
 * clicking through tabs. Eight KPI tiles answer the key "how am I doing?" questions
 * in one horizontal bar, always visible above the tab content.
 *
 * WHY 8 TILES (W2, was 7): PRD-0089 W2 §4.2 adds CASH and BUYING POWER tiles and
 * removes the "# Positions" tile (which moves to the header scope sub-line).
 *   Old: Total Value | Day P&L | Unrealised P&L | Realized P&L | Top Gainer | Top Loser | # Positions
 *   New: Total Value | Day P&L | Unrealised P&L | Realized P&L | CASH | BUYING PWR | Top Gainer | Top Loser
 * CASH comes from exposure.cash; BUYING PWR = CASH for v1 (margin accounts are v2).
 *
 * WHY divide-x (not gap/grid): divide-x produces 1px vertical separators between tiles
 * with no risk of tile widths diverging. It's the terminal-native way to subdivide
 * a horizontal band — see Bloomberg's port header or Refinitiv's portfolio overview.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — always rendered above Tabs
 * DATA SOURCE: Computed from holdings + live quotes + transactions + exposure in the parent page
 * DESIGN REFERENCE: PRD-0031 §8.1 Portfolio KPI Strip, PRD-0089 W2 §4.2
 */

"use client";
// WHY "use client": cn() is fine server-side, but this file is always rendered
// inside a "use client" page (portfolio/page.tsx), so it inherits that boundary.
// Also: useQueryClient (TanStack) is a client-only hook.

import { cn } from "@/lib/utils";
import { formatPrice, formatPercent } from "@/lib/utils";
// F-P-012 (PLAN-0051 W6): the Day P&L tile uses Skeleton when the value is
// genuinely unknown (no quote yet) so users don't read "$0.00" as "market
// is flat" when in fact we just haven't received data yet.
import { Skeleton } from "@/components/ui/skeleton";
// HIGH-016: RefreshCw button on the (approx) badge lets traders force a
// holdings recalculation when the FIFO endpoint was unavailable at page load.
import { RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/query/keys";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PortfolioKPIStripProps {
  /**
   * Portfolio ID used to invalidate the holdings query when the trader clicks
   * the refresh button on the (approx) badge (HIGH-016). Optional: when omitted
   * the refresh button is not rendered even if realizedPnlApprox is true.
   */
  portfolioId?: string | null;
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
  /**
   * @deprecated W2 §4.2: # Positions tile removed — it now lives in the
   * header scope sub-line. The prop is kept optional to avoid breaking the
   * call site in portfolio/page.tsx until step 4.19 rewrites the page.
   */
  positionCount?: number;
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
  /**
   * Cash balance from the exposure endpoint (ExposureResponse.cash).
   * null when not yet loaded. Renders "—" when null.
   * WHY here: cash is a top-of-book KPI — portfolio managers check cash
   * before sizing new positions. W2 §4.2 adds it adjacent to buying power.
   */
  cash?: number | null;
  /**
   * Buying power — for v1 cash accounts this equals cash. Margin accounts
   * (v2) will compute: settled_cash + margin_available.
   * null renders "—". WHY here: institutional traders monitor buying power
   * constantly to avoid over-allocation.
   */
  buyingPower?: number | null;
  /**
   * PLAN-0122 W-B (T-A-B-01): the portfolio detail level, driving how many
   * tiles render.
   *   • "advanced" (default) → all 8 tiles, EXACTLY today's output — the prop
   *     default keeps every existing caller/test byte-identical (R19).
   *   • "simple" → only the 4 casual-investor tiles: Total Value, Day P&L,
   *     Unrealised P&L (with %), Cash. WHY those four: they answer the casual
   *     "what's it worth / how'd it do today / total gain / free cash?" question
   *     (PRD-0122 §6.1, OQ-3) without the expert Realized/Buying-Pwr/Top-mover
   *     tiles. This is a RENDERING GATE, never a fork: the Advanced arm is
   *     unchanged and guarded by the W-A anti-fork snapshot.
   */
  variant?: "simple" | "advanced";
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * signedPrice — explicit "+$X" / "-$X" rendering for P&L values.
 *
 * WHY explicit sign (R1 sprint): colour alone is not enough — colour-blind
 * users and anyone scanning quickly needs the +/- prefix to read direction
 * (formatPercent already does this for percentages; this brings dollar P&L
 * values in line). formatPrice() already emits "-$X" for negatives, so we
 * only need to prepend "+" for strictly positive values.
 *
 * WHY zero stays unsigned ("$0.00", not "+$0.00"): a flat day has no
 * direction — signing it would falsely imply a gain.
 *
 * R3 polish: EXPORTED so every other portfolio surface that renders a
 * dollar P&L (e.g. the watchlist CHG$ column) uses the exact same sign
 * convention instead of re-implementing `v >= 0 ? "+" : ""` (which wrongly
 * signs zero). Single source of truth for the signed-dollar display.
 */
export function signedPrice(value: number): string {
  return value > 0 ? `+${formatPrice(value)}` : formatPrice(value);
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
  /**
   * Optional React node rendered inline after the suffix text.
   * HIGH-016: used by the Realized P&L tile to append a RefreshCw icon
   * button when showing the (approx) fallback value, without requiring
   * a structural change to the tile layout.
   */
  suffixAction?: React.ReactNode;
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
  suffixAction,
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
      // R4 hardening (a11y): role="group" + aria-label NAME the tile so the
      // value below is announced under its label ("Day P&L, group, +$120").
      // Visually the 10px caps label sits above the value, but with no
      // programmatic association a screen reader linearising the strip heard
      // 8 labels and 8 values as 16 disconnected strings. role="group" is
      // required for the aria-label to be exposed at all (a bare div with
      // aria-label has no role and most AT ignores the name).
      role="group"
      aria-label={label}
    >
      {/* Label: 10px ALL CAPS muted — consistent with table header style */}
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground truncate">
        {label}
      </span>
      {/* Value: 13px mono — NOT text-primary for P&L (only tickers use text-primary).
          WHY text-[13px] (was text-[14px]): Bloomberg portfolio strip uses 13px for KPI band
          values — 14px is reserved for live price display in instrument headers to maintain
          visual hierarchy. The 1px reduction keeps the strip compact while still readable.
          F-P-012: when ``valueNode`` is provided (e.g. Skeleton placeholder for
          the Day P&L unknown state) we render that instead of the string. The
          colour classes still apply but become a no-op for the Skeleton. */}
      <span
        className={cn(
          "font-mono text-[13px] tabular-nums font-medium truncate",
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
        {/* suffixAction renders immediately after the suffix text — e.g. the
            HIGH-016 RefreshCw icon button on the (approx) P&L badge. */}
        {suffixAction}
      </span>
    </div>
  );
}

// ── PortfolioKPIStrip ─────────────────────────────────────────────────────────

export function PortfolioKPIStrip({
  portfolioId,
  totalValue,
  dayPnl,
  unrealisedPnl,
  unrealisedPnlPct,
  topGainer,
  topLoser,
  // positionCount intentionally omitted from destructuring — tile removed in W2 §4.2
  realizedPnl,
  realizedPnlApprox = false,
  realizedPnlLongTerm = null,
  realizedPnlShortTerm = null,
  cash = null,
  buyingPower = null,
  // PLAN-0122 W-B: default "advanced" so an un-migrated caller renders all 8
  // tiles exactly as today. Only the page passes variant={mode}.
  variant = "advanced",
}: PortfolioKPIStripProps) {
  // WHY a single boolean read once: every advanced-only tile below gates on the
  // SAME value so a reviewer can see the Simple set is precisely {Total Value,
  // Day P&L, Unrealised P&L, Cash} — the four tiles NOT wrapped in `isAdvanced`.
  const isAdvanced = variant === "advanced";
  // F-201 fix (PLAN-0048 QA iter-1): formatPercent already prepends "+" for
  // positive values (lib/utils.ts:81). The previous "+${formatPercent()}" wrap
  // produced "++30.92%" in the UNREALISED P&L tile. Just call formatPercent
  // directly — its sign output is already correct for traders' expectations.
  const pnlPctFormatted = formatPercent(unrealisedPnlPct);

  // HIGH-016: queryClient.invalidateQueries forces a re-fetch of the holdings
  // query. WHY holdings (not realizedPnL): the realizedPnL endpoint failure
  // is usually transient — invalidating holdings causes the portfolio data
  // hook to retry both the holdings fetch and the downstream realizedPnL
  // query, clearing the (approx) badge when the FIFO endpoint recovers.
  const queryClient = useQueryClient();

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
        // R1 sprint: signedPrice gives the explicit "+" prefix on gains so
        // direction is readable without relying on colour alone.
        value={dayPnl == null ? "" : signedPrice(dayPnl)}
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

      {/* Tile 3: Unrealised P&L — absolute amount + percentage.
          R1 sprint: the dollar amount is now explicitly signed (signedPrice)
          to match the percentage (formatPercent has always signed). Before,
          "$2,500.00 (+2.50%)" mixed an unsigned dollar with a signed percent. */}
      <KPITile
        label="Unrealised P&L"
        value={`${signedPrice(unrealisedPnl)} (${pnlPctFormatted})`}
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
      {/* PLAN-0122 W-B: Realized P&L is an ADVANCED-only tile. Gating it here
          (rather than after the Cash tile) is what makes the Simple set render
          in the exact order Total Value → Day P&L → Unrealised → Cash. */}
      {isAdvanced && (() => {
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
        // R1 sprint: signedPrice for consistency with the Day/Unrealised
        // tiles — every P&L dollar value in the strip now carries its sign.
        const display =
          realizedPnl == null ? "—" : signedPrice(realizedPnl);

        return (
          <KPITile
            label="Realized P&L"
            value={display}
            positive={realizedPnl != null && realizedPnl > 0}
            negative={realizedPnl != null && realizedPnl < 0}
            hoverTitle={tooltip}
            suffix={realizedPnlApprox ? "(approx)" : undefined}
            suffixAction={
              // HIGH-016: show refresh button when approximation is active AND
              // a portfolioId is available to scope the invalidation.
              // WHY guard on portfolioId: without it we'd have to invalidate
              // qk.portfolios.all (too broad — refreshes every portfolio in the
              // list) or skip the button entirely. The caller is responsible for
              // passing the active portfolio's ID.
              realizedPnlApprox && portfolioId ? (
                <button
                  type="button"
                  onClick={() => {
                    // Invalidate the holdings query to trigger a re-fetch of
                    // both holdings AND the downstream realizedPnL endpoint.
                    // WHY holdings (not realizedPnL key directly): the FIFO
                    // endpoint is downstream of holdings; invalidating holdings
                    // ensures the whole data chain reruns.
                    void queryClient.invalidateQueries({
                      queryKey: qk.portfolios.holdings(portfolioId),
                    });
                  }}
                  className="ml-1 inline-flex items-center text-muted-foreground hover:text-foreground"
                  title="Refresh P&L calculation"
                  aria-label="Refresh P&L calculation"
                  data-testid="kpi-realized-pnl-refresh"
                >
                  <RefreshCw className="size-2.5" strokeWidth={1.5} />
                </button>
              ) : undefined
            }
            dataTestId="kpi-realized-pnl"
          />
        );
      })()}

      {/* Tile 5: Cash — broker-reported cash balance from exposure endpoint.
          WHY here: cash is the first question a PM asks before sizing a new
          trade. Adjacent to buying power so the two are read as a pair. */}
      <KPITile
        label="Cash"
        value={cash != null ? formatPrice(cash) : "—"}
        dataTestId="kpi-cash"
      />

      {/* Tile 6: Buying Power — v1: equals cash (cash accounts only).
          WHY separate tile from Cash: v2 margin accounts will show a different
          value (settled_cash + margin). Keeping them distinct future-proofs the
          layout so v2 doesn't require a tile restructure.
          PLAN-0122 W-B: ADVANCED-only — casual users read "Cash" (tile 5), not
          the margin-oriented buying-power distinction. */}
      {isAdvanced && (
        <KPITile
          label="Buying Pwr"
          value={buyingPower != null ? formatPrice(buyingPower) : "—"}
          dataTestId="kpi-buying-pwr"
        />
      )}

      {/* Tile 7: Top Gainer — best performer in the book; always green when present
          WHY pnlPct / 100: the stored value is already a percentage (e.g. 4.82),
          so formatPercent (which multiplies by 100) would over-scale it.
          PLAN-0122 W-B: ADVANCED-only — a single-position highlight is expert
          signal, not a headline number for the casual overview. */}
      {isAdvanced && (
        <KPITile
          label="Top Gain"
          value={
            topGainer
              // WHY no leading "+": formatPercent already prefixes positive values
              // with "+" (lib/utils.ts:81). Adding another "+" produced "++143.70%".
              ? `${topGainer.ticker} ${formatPercent(topGainer.pnlPct / 100)}`
              : "—"
          }
          positive={topGainer != null}
        />
      )}

      {/* Tile 8: Top Loser — worst performer; always red when present.
          PLAN-0122 W-B: ADVANCED-only (pairs with Top Gain). */}
      {isAdvanced && (
        <KPITile
          label="Top Lose"
          value={
            topLoser
              ? `${topLoser.ticker} ${formatPercent(topLoser.pnlPct / 100)}`
              : "—"
          }
          negative={topLoser != null}
        />
      )}
    </div>
  );
}
