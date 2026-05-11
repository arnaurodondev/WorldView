/**
 * components/portfolio/HoldingLotsPanel.tsx — FIFO open-lots drilldown
 * (PLAN-0088 Wave E E-2).
 *
 * Standalone panel — not an inline AG Grid row expansion. Why standalone:
 * the existing SemanticHoldingsTable wires onRowClicked to navigate to the
 * instrument detail page; injecting an inline expansion would either take
 * over that navigation (breaking the muscle-memory of "click row →
 * instrument page") or require a per-row expander icon column. The audit
 * explicitly cites Fidelity Active Trader Pro's "Lot Lookup" pattern,
 * which IS a separate table — so this matches the institutional reference.
 *
 * The panel renders below the holdings table with a ticker selector. When
 * the user picks AAPL/MSFT/etc. it fetches GET /v1/portfolios/{id}/holdings/
 * {instrument_id}/lots and shows: open-date, qty, cost-per-share, days-held,
 * ST/LT badge, unrealised P&L.
 *
 * DATA: GET /v1/portfolios/{id}/holdings/{instrument_id}/lots
 *
 * WHO USES IT: HoldingsTab below the holdings table.
 * DESIGN REFERENCE: PLAN-0088 §Wave E task E-2.
 */

"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent } from "@/lib/utils";
import type { Holding, BatchQuoteResponse } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface HoldingLotsPanelProps {
  /** Portfolio UUID. Null/undefined hides the panel. */
  portfolioId: string | null | undefined;
  /** Already-enriched holdings rows so we have the ticker list to choose from. */
  holdings: Holding[];
  /** Live quote map; used to compute per-lot unrealised on the server. */
  quotes: BatchQuoteResponse["quotes"];
}

// ── Component ────────────────────────────────────────────────────────────────

export function HoldingLotsPanel({
  portfolioId,
  holdings,
  quotes,
}: HoldingLotsPanelProps) {
  const { accessToken } = useAuth();

  // Default selection: largest position (matches the row-1 instinct on the
  // table above). Users override via the select control.
  const initialSelection = useMemo(() => {
    if (holdings.length === 0) return null;
    const sorted = [...holdings].sort(
      (a, b) =>
        Number(b.quantity) * (quotes[b.instrument_id]?.price ?? Number(b.average_cost)) -
        Number(a.quantity) * (quotes[a.instrument_id]?.price ?? Number(a.average_cost)),
    );
    return sorted[0]?.instrument_id ?? null;
  }, [holdings, quotes]);
  const [selectedInstrumentId, setSelectedInstrumentId] = useState<string | null>(
    initialSelection,
  );

  // Pull the live price for the selected instrument so the backend can
  // compute unrealised_pnl per lot in one round-trip.
  const currentPrice = selectedInstrumentId
    ? quotes[selectedInstrumentId]?.price
    : undefined;

  const { data, isLoading } = useQuery({
    enabled: Boolean(portfolioId && accessToken && selectedInstrumentId),
    queryKey: ["holding-lots", portfolioId, selectedInstrumentId, currentPrice],
    queryFn: () =>
      createGateway(accessToken!).getHoldingLots(
        portfolioId!,
        selectedInstrumentId!,
        currentPrice,
      ),
    staleTime: 60_000,
  });

  if (!portfolioId || holdings.length === 0) {
    // Nothing to show — keep the page clean rather than showing a stub.
    return null;
  }

  return (
    // WHY border-y: panel renders edge-to-edge (no px-2 wrapper in parent).
    // border-y provides the visual separator from the table above and strip below.
    <div className="border-y border-border bg-card">
      {/* Header strip: title + ticker dropdown + summary stats. */}
      <div className="flex h-7 items-center px-3 gap-3 border-b border-border bg-muted/20 font-mono text-[11px]">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          TAX LOTS
        </span>
        {/* Ticker selector — shadcn Select would be nicer but adds a portal +
            keyboard-nav surface we don't need here. A native select is one
            line of code, fully accessible, and matches the dense terminal
            aesthetic. */}
        <select
          className="bg-card border border-border rounded-sm px-2 py-px text-[11px] font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          value={selectedInstrumentId ?? ""}
          onChange={(e) => setSelectedInstrumentId(e.target.value || null)}
        >
          {holdings.map((h) => (
            <option key={h.instrument_id} value={h.instrument_id}>
              {h.ticker || h.instrument_id.slice(0, 8)}
            </option>
          ))}
        </select>

        {/* Header summary — ST/LT split and total cost. Empty until data lands. */}
        {data && (
          <div className="ml-auto flex items-center gap-3 text-[10px] text-muted-foreground">
            <span>
              <span className="uppercase tracking-[0.06em]">ST </span>
              <span className="tabular-nums text-foreground">
                {data.short_term_qty.toFixed(2)}
              </span>
            </span>
            <span>
              <span className="uppercase tracking-[0.06em]">LT </span>
              <span className="tabular-nums text-foreground">
                {data.long_term_qty.toFixed(2)}
              </span>
            </span>
            <span>
              <span className="uppercase tracking-[0.06em]">COST </span>
              <span className="tabular-nums text-foreground">
                {formatPrice(data.total_cost)}
              </span>
            </span>
          </div>
        )}
      </div>

      {/* Lot table — fixed-column terminal style. WHY a CSS grid (not AG
          Grid): the lot list is small (≤ ~20 rows even for an active
          trader), grid is leaner, and we don't need the column-state /
          context-menu surface AG Grid provides. */}
      <div className="overflow-y-auto max-h-[180px]">
        {isLoading ? (
          <div className="p-2 space-y-px">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[22px] w-full" />
            ))}
          </div>
        ) : !data || data.lots.length === 0 ? (
          <div className="px-3 py-2 text-[11px] text-muted-foreground font-mono">
            No open lots — position has been fully closed or never opened via
            recorded transactions. (For SnapTrade-synced positions, lots are
            derived from the transaction stream — historical fills before the
            first sync may be absent.)
          </div>
        ) : (
          <div className="font-mono text-[11px]">
            {/* Column header row. */}
            {/* WHY 110px last column (was 90px): the UNREAL cell renders both
                a dollar value (+$X,XXX.XX) and a percentage sub-label in a
                text-[9px] span (+XX.XX%). Combined they exceed 90px on most
                lots, causing visible overflow. 110px fits the widest case. */}
            <div className="grid grid-cols-[100px_70px_90px_70px_70px_110px] gap-2 px-3 py-1 text-[9px] uppercase tracking-[0.08em] text-muted-foreground border-b border-border bg-muted/10">
              <div>OPEN DATE</div>
              <div className="text-right">QTY</div>
              <div className="text-right">COST/SHR</div>
              <div className="text-right">DAYS</div>
              <div className="text-right">TERM</div>
              <div className="text-right">UNREAL</div>
            </div>
            {data.lots.map((lot, i) => (
              <div
                key={`${lot.open_date}-${i}`}
                className="grid grid-cols-[100px_70px_90px_70px_70px_110px] gap-2 px-3 h-[22px] items-center hover:bg-muted/20 border-b border-border/50"
              >
                <div className="tabular-nums text-foreground">{lot.open_date}</div>
                <div className="text-right tabular-nums text-foreground">
                  {lot.qty.toFixed(2)}
                </div>
                <div className="text-right tabular-nums text-foreground">
                  {formatPrice(lot.cost_per_share)}
                </div>
                <div className="text-right tabular-nums text-muted-foreground">
                  {lot.days_held}d
                </div>
                <div className="text-right">
                  {/* Tiny ST/LT badge — same colour cue as the FIFO realised
                      P&L breakdown elsewhere on the page (LT is muted /
                      green-leaning because long-term gains are tax-favoured). */}
                  <span
                    className={cn(
                      "px-1 py-px rounded-sm text-[9px] uppercase tracking-[0.06em] border",
                      lot.is_long_term
                        ? "bg-positive/10 text-positive border-positive/30"
                        : "bg-warning/10 text-warning border-warning/30",
                    )}
                  >
                    {lot.is_long_term ? "LT" : "ST"}
                  </span>
                </div>
                <div
                  className={cn(
                    "text-right tabular-nums",
                    lot.unrealised_pnl == null
                      ? "text-muted-foreground"
                      : lot.unrealised_pnl >= 0
                        ? "text-positive"
                        : "text-negative",
                  )}
                >
                  {/* Show the absolute $ figure + a percent of cost for
                      relative-magnitude scanning. WHY % alongside $: a $50
                      gain on a $5,000 lot is barely 1%; a $50 gain on a
                      $200 lot is 25% — both numbers are useful. */}
                  {lot.unrealised_pnl == null
                    ? "—"
                    : (
                        <>
                          {lot.unrealised_pnl >= 0 ? "+" : ""}
                          {formatPrice(lot.unrealised_pnl)}
                          {lot.cost_per_share > 0 && (
                            <span className="text-[9px] ml-1 text-muted-foreground">
                              {formatPercent(
                                lot.unrealised_pnl /
                                  (lot.cost_per_share * lot.qty),
                              )}
                            </span>
                          )}
                        </>
                      )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
