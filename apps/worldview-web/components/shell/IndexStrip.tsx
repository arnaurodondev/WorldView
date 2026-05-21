/**
 * components/shell/IndexStrip.tsx — Static 10-cell index row for the TopBar.
 *
 * WHY THIS EXISTS: Bloomberg's FNZX strip is the reference — every benchmark
 *   always visible, instantly scannable, zero motion. A hedge-fund PM
 *   glancing at the TopBar should be able to read SPY's price immediately
 *   without waiting for any animation to bring it into view. PRD-0089 W1
 *   replaced the prior animated ticker scroller with this static row
 *   because animation violates prefers-reduced-motion and steals cognitive
 *   bandwidth on a densely-packed terminal.
 *
 * WHO USES IT: components/shell/TopBar.tsx (single slot between
 *   PortfolioSwitcher and UtcClock).
 *
 * DATA SOURCE:
 *   1) `searchInstruments(ticker, 1)` x 10 in parallel → instrument_id UUIDs
 *      cached 30 min (qk.shell.indexResolveIds).
 *   2) `getBatchQuotes(ids)` every 15 s (qk.shell.indexQuotes).
 *
 * DESIGN REFERENCE: PRD-0089 W1 plan §4.1 + design §6 "TopBar — IndexStrip".
 *   - Manifest: SPY / QQQ / IWM / DIA / VIX / TLT / ^TNX / GLD / USO / BTC-USD
 *     (^TNX swapped in for second-USO per FU-4.3).
 *   - 60px per cell, font-mono tabular-nums.
 *   - Click → /indices/{ticker} (strip `^` for URL safety).
 *   - Hover → Radix Tooltip 300ms with full instrument name.
 *   - Narrow-viewport priority drop: USO → GLD → BTC → TLT → DIA → VIX
 *     (DXY referenced in plan but not in manifest, so omitted from drop list).
 *   - Hide entire strip below 1024px (mobile = v1.1).
 *   - Loading: 10 placeholder cells, never collapse to zero (no layout shift).
 */

"use client";
// WHY "use client": uses TanStack Query (browser-only) + Next router push for
// navigation on click; both forbid Server Components.

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { priceChangeClass, formatPercentDirect } from "@/lib/utils";

// ── Manifest ────────────────────────────────────────────────────────────────
// `ticker` is the canonical symbol (the form the resolver searches with and
// the URL path component); `displayName` populates the hover tooltip; `drop`
// is the rank used by the responsive trim (lower = drop sooner). Cells with
// drop=null are pinned (SPY/QQQ/IWM are always shown if the strip renders).
interface IndexCell {
  readonly ticker: string;
  readonly label: string;          // visible cell label (strip ^ from ^TNX)
  readonly displayName: string;     // tooltip text
  readonly drop: number | null;     // priority drop rank; null = pinned
}

const INDEX_MANIFEST: readonly IndexCell[] = [
  { ticker: "SPY",     label: "SPY",  displayName: "S&P 500 ETF",                drop: null },
  { ticker: "QQQ",     label: "QQQ",  displayName: "Nasdaq-100 ETF",             drop: null },
  { ticker: "IWM",     label: "IWM",  displayName: "Russell 2000 ETF",           drop: null },
  // VIX last among the pinned-ish — drop=6 means it survives all but the
  // tightest viewport.
  { ticker: "VIX",     label: "VIX",  displayName: "CBOE Volatility Index",       drop: 6 },
  { ticker: "DIA",     label: "DIA",  displayName: "Dow Jones Industrial ETF",   drop: 5 },
  { ticker: "TLT",     label: "TLT",  displayName: "20+ Year Treasury Bond ETF", drop: 4 },
  // ^TNX = CBOE 10-Year Treasury yield. ticker keeps the caret; label/URL
  // strip it so we render "TNX" and route to /indices/TNX.
  { ticker: "^TNX",    label: "TNX",  displayName: "10-Year Treasury Yield",     drop: 3 },
  { ticker: "BTC-USD", label: "BTC",  displayName: "Bitcoin (USD)",              drop: 2 },
  { ticker: "GLD",     label: "GLD",  displayName: "SPDR Gold Trust",             drop: 1 },
  // USO drops first under width pressure — single-commodity ETF, lowest
  // signal-to-bytes ratio of any cell.
  { ticker: "USO",     label: "USO",  displayName: "US Oil Fund",                 drop: 0 },
];

// Number of full-detail cells we always render (loading skeleton uses this so
// the strip never collapses to zero width while quotes resolve).
const FULL_CELL_COUNT = INDEX_MANIFEST.length;

// Tailwind breakpoints we honour. We rely on Tailwind's class-based responsive
// utilities (hidden / lg:flex) so the SSR markup matches; everything below the
// `lg` breakpoint (1024px) hides via `hidden lg:flex`. Priority drop within the
// lg+ range is handled with `xl:`/`2xl:` visibility on individual cells.
//   - lg  (≥1024): drops everything with drop ≤ 3 (USO/GLD/BTC/TNX hidden)
//   - xl  (≥1280): drops everything with drop ≤ 1 (USO/GLD hidden)
//   - 2xl (≥1536): everything visible
function visibilityClass(cell: IndexCell): string {
  if (cell.drop === null) return "flex";       // always visible (within lg+)
  if (cell.drop >= 5) return "hidden lg:flex"; // VIX/DIA — visible from lg up
  if (cell.drop >= 3) return "hidden xl:flex"; // TLT/^TNX — visible from xl up
  return "hidden 2xl:flex";                    // BTC/GLD/USO — only at 2xl
}

/** Compact-format a price so >10K values fit the 60px cell. */
function formatPrice(price: number | null | undefined): string {
  if (price == null || Number.isNaN(price)) return "—";
  const abs = Math.abs(price);
  if (abs >= 1_000_000) return `${(price / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `${(price / 1_000).toFixed(0)}K`;
  if (abs >= 1_000) return `${(price / 1_000).toFixed(1)}K`;
  return price.toFixed(2);
}

interface IndexStripProps {
  /** Test seam: override the manifest (used by unit tests for narrow viewport). */
  readonly manifest?: readonly IndexCell[];
}

export function IndexStrip({ manifest = INDEX_MANIFEST }: IndexStripProps = {}) {
  const router = useRouter();
  const { accessToken } = useAuth();

  // ── Resolve tickers → instrument UUIDs (cached 30 min) ───────────────────
  // WHY Promise.allSettled: one failed lookup must not blank the whole strip.
  // The cells whose resolution failed render with em-dash placeholders rather
  // than disappearing — matches Bloomberg's "data outage" behaviour.
  //
  // QA F-004 (2026-05-21): caret-prefixed tickers like `^TNX` do not match
  // anything in the S1 search index — searchInstruments returns zero
  // results. We strip a leading `^` and try the canonical form first
  // (`TNX`); if that misses we retry with the literal caret form so any
  // future backend that DOES index caret-prefixed symbols still resolves.
  const { data: tickerToId, isLoading: idsLoading } = useQuery({
    queryKey: qk.shell.indexResolveIds(),
    queryFn: async () => {
      const gw = createGateway(accessToken);
      const resolveOne = async (canonicalTicker: string): Promise<string | null> => {
        // Try the caret-stripped form first (matches how S1 indexes most rates symbols).
        const stripped = canonicalTicker.replace(/^\^/, "");
        if (stripped !== canonicalTicker) {
          const r = await gw.searchInstruments(stripped, 1);
          const id = r.results?.[0]?.instrument_id ?? null;
          if (id) return id;
        }
        // Fall back to the literal form (with caret if originally present).
        const r2 = await gw.searchInstruments(canonicalTicker, 1);
        return r2.results?.[0]?.instrument_id ?? null;
      };
      const settled = await Promise.allSettled(
        manifest.map(async (cell) => ({
          ticker: cell.ticker,
          id: await resolveOne(cell.ticker),
        })),
      );
      const map: Record<string, string | null> = {};
      for (const r of settled) {
        if (r.status === "fulfilled") map[r.value.ticker] = r.value.id;
      }
      return map;
    },
    staleTime: 30 * 60_000,
    enabled: !!accessToken,
  });

  // ── Batch quotes ─────────────────────────────────────────────────────────
  // Stable sorted list of resolved ids — derived via useMemo so the queryKey
  // tuple equality holds across renders (TanStack would otherwise refetch on
  // every parent re-render).
  const resolvedIds = useMemo(() => {
    if (!tickerToId) return [] as string[];
    return manifest
      .map((cell) => tickerToId[cell.ticker])
      .filter((id): id is string => !!id);
  }, [manifest, tickerToId]);

  const { data: quotesResp } = useQuery({
    queryKey: qk.shell.indexQuotes(resolvedIds),
    queryFn: () => createGateway(accessToken).getBatchQuotes(resolvedIds),
    enabled: !!accessToken && resolvedIds.length > 0,
    refetchInterval: 15_000,
    staleTime: 0,
  });
  const quotes = quotesResp?.quotes ?? {};

  // Click → /indices/{label}. We strip `^` (label already has it removed) so
  // the URL form is clean — `^TNX` becomes `/indices/TNX`. Per plan §4.1.
  const goToIndex = (label: string) => router.push(`/indices/${label}`);

  // ── Loading skeleton ──────────────────────────────────────────────────────
  // WHY 10 placeholder cells (not a single skeleton bar): the cells reserve
  // the same horizontal slot the loaded strip will occupy. No layout shift
  // when the data arrives.
  if (idsLoading) {
    return (
      <div
        className="hidden h-full items-center gap-2 lg:flex"
        aria-label="Loading market index strip"
        data-testid="index-strip-loading"
      >
        {Array.from({ length: FULL_CELL_COUNT }).map((_, i) => (
          <div
            key={i}
            className="flex h-6 w-[60px] shrink-0 flex-col justify-center bg-muted/30 px-1"
            aria-hidden
          />
        ))}
      </div>
    );
  }

  return (
    <TooltipProvider delayDuration={300}>
      {/*
        Outer wrapper:
          - hidden lg:flex: never render below 1024px (mobile = v1.1).
          - h-full items-center: cells inherit the 32px TopBar height.
          - gap-2: matches the rest of the TopBar inter-cell rhythm.
          - data-testid: drives narrow-viewport Playwright spec.
      */}
      <div
        className="hidden h-full items-center gap-2 lg:flex"
        aria-label="Market index strip"
        data-testid="index-strip"
      >
        {manifest.map((cell) => {
          const id = tickerToId?.[cell.ticker];
          const quote = id ? quotes[id] : undefined;
          // WHY ±0.005% deadband (matches PortfolioRail PNL_FLAT_EPSILON in
          // TopBar.tsx): floating-point dust should not paint a flat ticker
          // red or green. priceChangeClass handles its own zero check so we
          // simply pass the change_pct through.
          const change = quote?.change_pct ?? null;

          return (
            <Tooltip key={cell.ticker}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => goToIndex(cell.label)}
                  className={`${visibilityClass(cell)} h-6 w-[60px] shrink-0 flex-col items-start justify-center px-1 text-left hover:bg-muted/20`}
                  aria-label={`${cell.displayName} — view index detail`}
                  data-ticker={cell.ticker}
                >
                  <span className="flex w-full items-center justify-between">
                    <span className="font-mono text-[11px] font-medium text-foreground">
                      {cell.label}
                    </span>
                    <span className="font-mono text-[11px] tabular-nums text-foreground">
                      {formatPrice(quote?.price)}
                    </span>
                  </span>
                  <span
                    className={`block w-full text-right font-mono text-[10px] tabular-nums ${
                      change != null ? priceChangeClass(change) : "text-muted-foreground"
                    }`}
                  >
                    {change != null ? formatPercentDirect(change) : "—"}
                  </span>
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="font-mono text-[10px]">
                {cell.displayName} ({cell.ticker})
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}
