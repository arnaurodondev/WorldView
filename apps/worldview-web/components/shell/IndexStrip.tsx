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
// the URL path component); `displayName` populates the hover tooltip.
// Static priority-drop ranks were removed in W1.1 H-001 — with the marquee
// restored, cells scroll horizontally so every ticker becomes visible over
// one cycle regardless of viewport width. No need to hide cells at narrow
// viewports anymore.
interface IndexCell {
  readonly ticker: string;
  readonly label: string;          // visible cell label (strip ^ from ^TNX)
  readonly displayName: string;     // tooltip text
}

const INDEX_MANIFEST: readonly IndexCell[] = [
  { ticker: "SPY",     label: "SPY",  displayName: "S&P 500 ETF" },
  { ticker: "QQQ",     label: "QQQ",  displayName: "Nasdaq-100 ETF" },
  { ticker: "IWM",     label: "IWM",  displayName: "Russell 2000 ETF" },
  { ticker: "VIX",     label: "VIX",  displayName: "CBOE Volatility Index" },
  { ticker: "DIA",     label: "DIA",  displayName: "Dow Jones Industrial ETF" },
  { ticker: "TLT",     label: "TLT",  displayName: "20+ Year Treasury Bond ETF" },
  // ^TNX = CBOE 10-Year Treasury yield. ticker keeps the caret; label/URL
  // strip it so we render "TNX" and route to /indices/TNX.
  { ticker: "^TNX",    label: "TNX",  displayName: "10-Year Treasury Yield" },
  { ticker: "BTC-USD", label: "BTC",  displayName: "Bitcoin (USD)" },
  { ticker: "GLD",     label: "GLD",  displayName: "SPDR Gold Trust" },
  { ticker: "USO",     label: "USO",  displayName: "US Oil Fund" },
];

// Number of full-detail cells we always render (loading skeleton uses this so
// the strip never collapses to zero width while quotes resolve).
const FULL_CELL_COUNT = INDEX_MANIFEST.length;

// Per-cell width — 88px (was 60px in the static W1 version).
// User feedback Image #6: 60px butted the ticker label against the price text
// with no breathing room ("Q704.23" looked like a single token). 88px gives
// ~25px of gap between the ticker label and a 6-char price like "735.68",
// matching Bloomberg FNZX visual rhythm.
const CELL_WIDTH_PX = 88;

// Marquee cycle = 6s per visible cell (slow enough to read each one without
// the strip feeling rushed; matches the pre-W1 cadence the user remembered as
// the "previous moving approach"). 10 cells × 6s = 60s per full cycle.
const ANIMATION_DURATION_S = INDEX_MANIFEST.length * 6;

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
            className="flex h-6 shrink-0 flex-col justify-center bg-muted/30 px-1"
            style={{ width: CELL_WIDTH_PX }}
            aria-hidden
          />
        ))}
      </div>
    );
  }

  /**
   * Render a single cell. Extracted because we paint the manifest twice
   * (once for the visible pass, once for the seamless loop) and want each
   * instance to render identically.
   */
  function renderCell(cell: IndexCell, keySuffix = ""): React.ReactNode {
    const id = tickerToId?.[cell.ticker];
    const quote = id ? quotes[id] : undefined;
    // WHY ±0.005% deadband (matches PortfolioRail PNL_FLAT_EPSILON in
    // TopBar.tsx): floating-point dust should not paint a flat ticker
    // red or green. priceChangeClass handles its own zero check so we
    // simply pass the change_pct through.
    const change = quote?.change_pct ?? null;

    return (
      <Tooltip key={`${cell.ticker}${keySuffix}`}>
        <TooltipTrigger asChild>
          <button
            onClick={() => goToIndex(cell.label)}
            // gap-2 between ticker and price (user feedback Image #6 —
            // pre-fix the two glyphs visually merged into a single token).
            className="flex h-6 shrink-0 flex-col items-start justify-center px-1 text-left hover:bg-muted/20"
            style={{ width: CELL_WIDTH_PX }}
            aria-label={`${cell.displayName} — view index detail`}
            data-ticker={cell.ticker}
          >
            <span className="flex w-full items-center justify-between gap-2">
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
  }

  return (
    <TooltipProvider delayDuration={300}>
      {/*
        W1.1 H-001 — marquee restored per direct user feedback. Static
        strip was clipping cells at narrow viewports; the user explicitly
        asked for the moving values back.

        Outer wrapper:
          - hidden lg:flex: never render below 1024px (mobile = v1.1)
          - h-full items-center overflow-hidden: cells inherit 32px height
            and overflow is clipped at the wrapper edge so the right
            cluster's lane stays clean
          - role=marquee + aria-label: screen readers announce the region
            once instead of every animation frame
      */}
      <div
        className="hidden h-full w-full items-center overflow-hidden lg:flex"
        role="marquee"
        aria-label="Market index strip"
        data-testid="index-strip"
      >
        {/*
          Inner scrolling track:
            - flex w-max gap-2: every cell in one horizontal line, no wrap
            - marquee-strip: CSS class in app/globals.css owns the
              `worldview-ticker-scroll` keyframes (translate3d 0 → -50%)
            - w-max: prevents flex-wrap; track must be one unbroken line
              that the keyframe shifts left by exactly half its own width
              for a seamless loop
            - --marquee-duration: scales with cell count (6s × N)

          NOTE on aria: the outer wrapper carries role=marquee + aria-label
          to announce the region. The first cell pass stays in the
          accessibility tree (screen readers and keyboard nav can reach
          every button); only the second pass is `aria-hidden` so duplicate
          buttons do not announce twice.
        */}
        <div
          className="marquee-strip flex w-max items-center gap-2"
          style={{ "--marquee-duration": `${ANIMATION_DURATION_S}s` } as React.CSSProperties}
        >
          {/* First pass — the visible + announceable copy. */}
          {manifest.map((cell) => renderCell(cell))}
          {/* Second pass — pixel-identical duplicate so the -50% translate
              loops without a visible seam. aria-hidden + role=presentation
              so AT users never see double. The `.marquee-pass-second`
              class lets the reduced-motion media query hide this entire
              duplicate while leaving the first pass static. */}
          <div
            className="marquee-pass-second flex items-center gap-2"
            aria-hidden="true"
            role="presentation"
          >
            {manifest.map((cell) => renderCell(cell, "-2"))}
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
