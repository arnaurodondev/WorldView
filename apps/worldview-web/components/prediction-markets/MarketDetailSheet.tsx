/**
 * components/prediction-markets/MarketDetailSheet.tsx — market detail surface
 * (PLAN-0056 Wave E2, task 3).
 *
 * ── WHY A SHEET (not a /prediction-markets/[conditionId] route) ──
 * The list is an infinite-scroll surface with category + search filter state.
 * A route push would UNMOUNT that list — the trader would lose their scroll
 * position and active filter on every drill-in/back. A right-side Sheet overlays
 * the detail WITHOUT tearing down the list, so closing it returns the trader
 * exactly where they were. It also needs no new data-loading route boundary. The
 * app already ships the shadcn Sheet (used by AlertsList), so this is the
 * established in-app "inspect one row" idiom here. Documented in
 * docs/apps/worldview-web.md.
 *
 * CONTENT: probability chart (interval toggle) · current YES/NO odds · liquidity
 * / open-interest / volume stats · recent-flow strip (trades) · a signal badge ·
 * and the canonical external Polymarket link (via buildPolymarketUrl).
 */

"use client";
// WHY "use client": query hooks + interactive Sheet state.

import { useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ProbabilityChart, type ProbabilityInterval } from "./ProbabilityChart";
import { SignalBadge } from "./SignalBadge";
import { computeYesDeltaPp } from "./probability-series";
import {
  usePredictionMarketPriceHistory,
  usePredictionMarketTrades,
} from "@/lib/api/prediction-markets-hooks";
import { buildPolymarketUrl } from "@/lib/prediction-markets";
import { formatCompactCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ExternalLink, ArrowUpRight, ArrowDownRight } from "lucide-react";
import type { PredictionMarket } from "@/types/api";

interface MarketDetailSheetProps {
  /** The selected market, or null when nothing is open. */
  market: PredictionMarket | null;
  /** Controlled open state. */
  open: boolean;
  /** Close handler (Radix passes false on ESC/overlay/X). */
  onOpenChange: (open: boolean) => void;
}

// ── Small stat cell ────────────────────────────────────────────────────────────
function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-[2px] border border-border/40 bg-muted/20 px-2 py-1.5">
      <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="font-mono text-[13px] tabular-nums text-foreground">{value}</p>
      {sub && <p className="font-mono text-[9px] text-muted-foreground/70">{sub}</p>}
    </div>
  );
}

export function MarketDetailSheet({ market, open, onOpenChange }: MarketDetailSheetProps) {
  // Interval mirrored from the chart so the SignalBadge's "moving" delta is
  // measured over the SAME window the trader is looking at. Both this hook and
  // the chart's hook use identical (conditionId, interval) args ⇒ ONE network
  // fetch, shared via the TanStack cache.
  const [interval, setInterval] = useState<ProbabilityInterval>("1d");

  const conditionId = market?.market_id ?? "";
  const { data: history } = usePredictionMarketPriceHistory(conditionId, interval);
  const { data: trades } = usePredictionMarketTrades(conditionId);

  // Guard: render an empty Sheet shell when no market (Radix keeps it mounted
  // for exit animation). Everything below assumes `market` exists.
  const yesPct = market ? Math.round(Math.min(1, Math.max(0, market.yes_probability)) * 100) : 0;
  const noPct = market ? Math.round(Math.min(1, Math.max(0, market.no_probability)) * 100) : 0;

  // "moving" delta from the visible interval's YES series (null → no move shown).
  const deltaPp = history ? computeYesDeltaPp(history.points) : null;

  // Liquidity: interval bars don't carry it yet (only raw snapshots do), so this
  // surfaces the value if the feed ever populates it, else "—". Volume comes from
  // the list summary (24h). Open interest is NOT in S3's payload — shown as "n/a"
  // rather than fabricated. Documented in docs/apps/worldview-web.md.
  const liquidity =
    history?.points.map((p) => p.liquidity).find((l) => l != null) ?? null;

  // Recent flow: aggregate the loaded trades into a one-line read (buy/sell
  // notional + count) so the trader sees the last flow burst at a glance.
  const flow = (trades?.items ?? []).reduce(
    (acc, t) => {
      const usd = t.size_usd ?? 0;
      if (t.side.toLowerCase() === "sell") acc.sell += usd;
      else acc.buy += usd;
      acc.count += 1;
      return acc;
    },
    { buy: 0, sell: 0, count: 0 },
  );

  const externalUrl = market
    ? market.url && market.url.length > 0
      ? market.url
      : buildPolymarketUrl(market.market_slug, market.title ?? "")
    : "#";

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md" data-testid="market-detail-sheet">
        {market && (
          <>
            <SheetHeader className="pr-6 text-left">
              <div className="flex items-start gap-2">
                <SheetTitle className="text-[13px] leading-snug text-foreground">
                  {market.title}
                </SheetTitle>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {market.category && (
                  <span className="rounded-[2px] bg-muted/40 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                    {market.category}
                  </span>
                )}
                {/* Signal badge — resolved/closed from status, or a measured
                    "moving" from the visible-interval YES delta. */}
                <SignalBadge status={market.status} deltaPp={deltaPp} />
              </div>
            </SheetHeader>

            <div className="mt-3 space-y-4">
              {/* ── Probability chart ─────────────────────────────────────── */}
              <ProbabilityChart
                conditionId={conditionId}
                defaultInterval={interval}
                onIntervalChange={setInterval}
              />

              {/* ── Current odds ──────────────────────────────────────────── */}
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-[2px] border border-positive/30 bg-positive/5 px-2 py-1.5">
                  <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">Yes</p>
                  <p className="font-mono text-[15px] tabular-nums text-positive">{yesPct}%</p>
                </div>
                <div className="rounded-[2px] border border-negative/30 bg-negative/5 px-2 py-1.5">
                  <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">No</p>
                  <p className="font-mono text-[15px] tabular-nums text-negative">{noPct}%</p>
                </div>
              </div>

              {/* ── Liquidity / OI / Volume stats ─────────────────────────── */}
              <div className="grid grid-cols-3 gap-2">
                <Stat
                  label="Volume 24h"
                  value={formatCompactCurrency(market.volume_usd ?? 0, "USD", { maxDecimals: 1 })}
                />
                <Stat
                  label="Liquidity"
                  value={liquidity != null ? formatCompactCurrency(liquidity, "USD", { maxDecimals: 1 }) : "—"}
                />
                {/* WHY "n/a": S3 does not yet expose open interest on any
                    prediction-market payload. We label it honestly rather than
                    render a fake number. */}
                <Stat label="Open Int." value="—" sub="n/a" />
              </div>

              {/* ── Recent flow strip ─────────────────────────────────────── */}
              <div>
                <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  Recent flow
                </p>
                {flow.count === 0 ? (
                  <p data-testid="recent-flow-empty" className="font-mono text-[10px] text-muted-foreground/70">
                    No recent trades
                  </p>
                ) : (
                  <div data-testid="recent-flow" className="space-y-1">
                    {/* Aggregate summary line */}
                    <div className="flex items-center gap-3 font-mono text-[10px] tabular-nums">
                      <span className="flex items-center gap-1 text-positive">
                        <ArrowUpRight className="h-3 w-3" strokeWidth={2} />
                        {formatCompactCurrency(flow.buy, "USD", { maxDecimals: 1 })} buy
                      </span>
                      <span className="flex items-center gap-1 text-negative">
                        <ArrowDownRight className="h-3 w-3" strokeWidth={2} />
                        {formatCompactCurrency(flow.sell, "USD", { maxDecimals: 1 })} sell
                      </span>
                      <span className="ml-auto text-muted-foreground/70">{flow.count} fills</span>
                    </div>
                    {/* Last few fills */}
                    <div className="space-y-0.5">
                      {(trades?.items ?? []).slice(0, 6).map((t, i) => {
                        const sell = t.side.toLowerCase() === "sell";
                        return (
                          <div
                            key={`${t.ts}-${i}`}
                            className="flex items-center justify-between font-mono text-[9px] tabular-nums text-muted-foreground"
                          >
                            <span className={cn(sell ? "text-negative" : "text-positive")}>
                              {sell ? "SELL" : "BUY"}
                            </span>
                            <span>{Math.round(t.price * 100)}%</span>
                            <span>
                              {t.size_usd != null
                                ? formatCompactCurrency(t.size_usd, "USD", { maxDecimals: 1 })
                                : "—"}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {/* ── External link ─────────────────────────────────────────── */}
              <a
                href={externalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-primary hover:underline"
              >
                View on Polymarket
                <ExternalLink className="h-3 w-3" strokeWidth={1.5} />
              </a>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
