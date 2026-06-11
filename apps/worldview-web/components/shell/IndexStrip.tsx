/**
 * components/shell/IndexStrip.tsx — Scrolling market ticker tape for the TopBar.
 *
 * WHY A MARQUEE AGAIN (user feedback 2026-06-10): the static 10-cell row
 * (PRD-0089 W1) could only fit ~10 instruments before priority-dropping cells
 * at narrow viewports. The user explicitly asked for "moving tickers; this way
 * we have a larger set" — a continuously scrolling tape lets us carry 16+
 * instruments (indices, vol, rates, commodities, sector ETFs, crypto) in the
 * same horizontal slot.
 *
 * ── NFR-6 EXCEPTION (sanctioned) ────────────────────────────────────────────
 * DESIGN_SYSTEM NFR-6 bans animation on data surfaces. The ticker tape is the
 * ONE sanctioned exception (user-requested, 2026-06-10): the animation is a
 * continuous constant-velocity transform (no easing, no attention-grabbing
 * keyframe), it PAUSES on hover/focus-within so values can be read, and it is
 * FULLY DISABLED under prefers-reduced-motion (a static, horizontally
 * scrollable row is shown instead). The DESIGN_SYSTEM.md note documenting this
 * exception is owned by the design-system owner — flagged in the wave report.
 * ────────────────────────────────────────────────────────────────────────────
 *
 * IMPLEMENTATION (reuses the PLAN-0052 QA-R6 marquee CSS in app/globals.css):
 *   - `.marquee-strip` — `worldview-ticker-scroll` keyframes translating the
 *     track from 0 → -50% of its own width; duration via --marquee-duration.
 *   - The track holds TWO identical copies of the cell list. Because the
 *     animation target is exactly -50%, the loop is seamless when each copy's
 *     width (including its trailing pr-1.5 gap) is identical.
 *   - Copy #2 is aria-hidden + inert (tabIndex -1) — screen readers and
 *     keyboard users interact with copy #1 only; the duplicate is pure visual
 *     continuity.
 *   - `.marquee-strip:hover / :focus-within` → animation-play-state: paused.
 *   - Under prefers-reduced-motion the animated track is display:none and the
 *     `.marquee-static-fallback` row (single copy, overflow-x-auto) shows —
 *     motion-sensitive users get a normal static scrollable price bar.
 *
 * DATA FLOW (unchanged two-step):
 *   1. Resolve ticker symbols → instrument_id UUIDs via resolveTickersBatch
 *      (staleTime 30min — instrument IDs are stable identifiers).
 *   2. Batch-quote resolved UUIDs every 15s via POST /v1/quotes/batch.
 *
 * WHO USES IT: components/shell/TopBar.tsx (center slot).
 * DESIGN REFERENCE: PRD-0089 W1 §4.1 (cells); user feedback 2026-06-10 (tape).
 */

"use client";
// WHY "use client": uses TanStack Query (browser-only) + useRouter (navigation).

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";

// ── Ticker manifest ───────────────────────────────────────────────────────────

/**
 * INDEX_STRIP_TICKERS — 16-cell manifest, left-to-right tape order.
 *
 * WHY 16 (was 10): the marquee removes the fixed-width constraint, so the tape
 * now covers the full institutional morning scan:
 *   US Equities:   SPY, QQQ, IWM, DIA
 *   Volatility:    VIX
 *   Fixed income:  TLT, ^TNX (10-year Treasury yield)
 *   Commodities:   GLD, SLV, USO
 *   Sector ETFs:   XLK (tech), XLE (energy), XLF (financials)
 *   International: EEM (emerging markets)
 *   Crypto:        BTC-USD, ETH-USD
 * Every ticker was verified to resolve via /v1/instruments/resolve-tickers on
 * the live stack (2026-06-10) EXCEPT ^TNX (no instrument row yet — renders "—"
 * truthfully; kept because the 10Y yield is core to the scan and lights up the
 * moment ingestion lands).
 *
 * canonicalTicker: the key used for resolveTickersBatch AND the URL segment.
 * displayLabel:    short label rendered in the cell ("^" dropped, "-USD" dropped).
 * fullName:        tooltip / aria-label text.
 */
interface TickerConfig {
  canonicalTicker: string; // used for API resolution (e.g. "^TNX")
  displayLabel: string;    // label in the 60px cell (e.g. "TNX")
  fullName: string;        // tooltip / aria-label
}

export const INDEX_STRIP_TICKERS: readonly TickerConfig[] = [
  { canonicalTicker: "SPY",     displayLabel: "SPY", fullName: "SPDR S&P 500 ETF" },
  { canonicalTicker: "QQQ",     displayLabel: "QQQ", fullName: "Invesco QQQ (Nasdaq-100)" },
  { canonicalTicker: "IWM",     displayLabel: "IWM", fullName: "iShares Russell 2000" },
  { canonicalTicker: "DIA",     displayLabel: "DIA", fullName: "SPDR Dow Jones ETF" },
  { canonicalTicker: "VIX",     displayLabel: "VIX", fullName: "CBOE Volatility Index" },
  { canonicalTicker: "TLT",     displayLabel: "TLT", fullName: "iShares 20+ Year Treasury" },
  { canonicalTicker: "^TNX",    displayLabel: "TNX", fullName: "10-Year Treasury Yield" },
  { canonicalTicker: "GLD",     displayLabel: "GLD", fullName: "SPDR Gold Shares" },
  { canonicalTicker: "SLV",     displayLabel: "SLV", fullName: "iShares Silver Trust" },
  { canonicalTicker: "USO",     displayLabel: "USO", fullName: "United States Oil Fund" },
  { canonicalTicker: "XLK",     displayLabel: "XLK", fullName: "Technology Select Sector SPDR" },
  { canonicalTicker: "XLE",     displayLabel: "XLE", fullName: "Energy Select Sector SPDR" },
  { canonicalTicker: "XLF",     displayLabel: "XLF", fullName: "Financial Select Sector SPDR" },
  { canonicalTicker: "EEM",     displayLabel: "EEM", fullName: "iShares MSCI Emerging Markets" },
  { canonicalTicker: "BTC-USD", displayLabel: "BTC", fullName: "Bitcoin / USD" },
  { canonicalTicker: "ETH-USD", displayLabel: "ETH", fullName: "Ethereum / USD" },
];

/**
 * MARQUEE_SECONDS_PER_CELL — tape speed control.
 *
 * The CSS animation translates the track by one full copy-width per
 * --marquee-duration. Scaling duration with cell count keeps the PIXEL
 * velocity constant (~27px/s at 60px cells + 6px gap) no matter how many
 * tickers the manifest carries — adding instruments never speeds up the tape.
 */
const MARQUEE_SECONDS_PER_CELL = 2.5;

// ── Quote shape from the batch endpoint ──────────────────────────────────────

interface IndexQuote {
  price?: number;
  change_pct?: number | null;
  freshness_status?: string;
}

// ── Deadband for change% color (plan §4.1): ±0.005% is genuinely flat ────────
const CHG_FLAT_EPSILON = 0.005;

/**
 * chgClass — map a change% value to a design-token color class.
 *
 * WHY design tokens (not `text-green-*`):
 * F1 locked the palette — bare Tailwind palette classes are banned by the
 * architecture test (no-off-palette-colors.test.ts). The hsl(var(--positive))
 * / hsl(var(--negative)) forms resolve from the global CSS tokens.
 */
function chgClass(pct: number | null | undefined): string {
  if (pct == null) return "text-muted-foreground";
  if (pct > CHG_FLAT_EPSILON) return "text-[hsl(var(--positive))]";
  if (pct < -CHG_FLAT_EPSILON) return "text-[hsl(var(--negative))]";
  return "text-muted-foreground";
}

/**
 * formatChg — compact change% for the 60px cell (e.g. "+1.23%").
 * Two decimal places is the Bloomberg convention for intraday change%.
 */
function formatChg(pct: number | null | undefined): string {
  if (pct == null) return "—";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

/**
 * formatIndexPrice — compact price for the 60px cell.
 * >10,000: compact "76.7K" / "1.2M". ≤9,999: two decimals.
 *
 * WHY not `formatPrice` from lib/utils: the lib version always shows two decimal
 * places which overflows the 60px cell for BTC ($76,736.46 → "76.7K" fits).
 */
function formatIndexPrice(price: number | undefined): string {
  if (price == null) return "—";
  if (price >= 1_000_000) return `${(price / 1_000_000).toFixed(1)}M`;
  if (price >= 10_000) return `${(price / 1_000).toFixed(1)}K`;
  return price.toFixed(2);
}

// ── Cell list (one tape copy) ─────────────────────────────────────────────────

/**
 * TickerCells — one full copy of the manifest as a row of clickable cells.
 *
 * Rendered up to three times:
 *   1. animated track copy #1 (interactive)
 *   2. animated track copy #2 (aria-hidden duplicate for the seamless loop)
 *   3. static reduced-motion fallback (interactive)
 *
 * WHY pr-1.5 on the copy container (and NO gap on the track): for the -50%
 * keyframe target to land exactly at the start of copy #2, each copy's width
 * must include its trailing inter-copy gap. A `gap` on the track would add
 * 6px BETWEEN copies but not after the last one → visible jump every loop.
 *
 * @param inert  true for the visual duplicate — strips it from the a11y tree
 *               and the tab order (aria-hidden alone does NOT remove buttons
 *               from keyboard focus; tabIndex -1 does).
 */
function TickerCells({
  tickerToId,
  quotes,
  inert = false,
}: {
  tickerToId: Record<string, string | null>;
  quotes: Record<string, IndexQuote | undefined>;
  inert?: boolean;
}) {
  const router = useRouter();

  return (
    <div
      className="flex items-center gap-1.5 pr-1.5"
      aria-hidden={inert || undefined}
      data-testid={inert ? "index-strip-copy-duplicate" : "index-strip-copy"}
    >
      {INDEX_STRIP_TICKERS.map((ticker) => {
        const instrumentId = tickerToId[ticker.canonicalTicker];
        const quote: IndexQuote | undefined = instrumentId ? quotes[instrumentId] : undefined;

        // Build the route: strip "^" from the URL segment (^TNX → TNX).
        // WHY strip caret: "^" is a URL meta-character and looks odd in routes.
        // The canonical form with caret is kept in state; only the URL drops it.
        const urlTicker = ticker.canonicalTicker.replace(/^\^/, "");

        return (
          <button
            key={ticker.canonicalTicker}
            type="button"
            onClick={() => router.push(`/indices/${urlTicker}`)}
            title={ticker.fullName}
            // The duplicate copy must not be reachable by keyboard — it exists
            // purely for visual loop continuity (see TickerCells docstring).
            tabIndex={inert ? -1 : undefined}
            aria-label={`${ticker.fullName}: ${formatIndexPrice(quote?.price)} (${formatChg(quote?.change_pct)})`}
            // WHY w-[60px] shrink-0: fixed cell width keeps the tape's total
            // width (and therefore the loop period) deterministic regardless
            // of price digit count. shrink-0 prevents flex squeeze.
            className="flex w-[60px] shrink-0 flex-col items-start px-0.5 hover:bg-muted/20"
          >
            {/* Ticker label — monospace, medium weight, foreground */}
            <span className="font-mono font-medium text-[11px] text-foreground leading-none">
              {ticker.displayLabel}
            </span>
            {/* Price — mono tabular so digits don't jitter on refetch */}
            <span className="font-mono tabular-nums text-[11px] text-foreground leading-none">
              {formatIndexPrice(quote?.price)}
            </span>
            {/* Change% — color-coded by direction via design tokens */}
            <span className={cn("font-mono tabular-nums text-[10px] leading-none", chgClass(quote?.change_pct))}>
              {formatChg(quote?.change_pct)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IndexStrip() {
  const { accessToken } = useAuth();

  // ── Step 1: Resolve ticker symbols → instrument_id UUIDs ─────────────────
  // WHY resolveTickersBatch (not individual searchInstruments): exact-match
  // lookup avoids the "TLT → CTLT" substring-match bug from IndexTicker.tsx.
  // One batch call vs. 16 serial calls is also ~10× faster.
  const { data: tickerToId } = useQuery({
    queryKey: qk.shell.indexResolveIds(),
    queryFn: async () => {
      const gw = createGateway(accessToken);
      const tickers = INDEX_STRIP_TICKERS.map((t) => t.canonicalTicker);
      const result = await gw.resolveTickersBatch(tickers);
      // Build a map from canonical ticker → instrument_id (null = not found).
      const map: Record<string, string | null> = {};
      tickers.forEach((t) => { map[t] = result[t] ?? null; });
      return map;
    },
    staleTime: 30 * 60_000, // 30 min — instrument IDs are stable
    enabled: !!accessToken,
  });

  // ── Step 2: Batch-quote resolved UUIDs every 15s ─────────────────────────
  const resolvedIds = Object.values(tickerToId ?? {}).filter((id): id is string => !!id);

  const { data, isLoading } = useQuery({
    queryKey: qk.shell.indexQuotes(),
    queryFn: async () => {
      const gw = createGateway(accessToken);
      return gw.getBatchQuotes(resolvedIds);
    },
    refetchInterval: 15_000, // 15s refresh matches data freshness window
    staleTime: 0,            // always serve from network (staleTime 0 = always stale)
    enabled: !!accessToken && resolvedIds.length > 0,
  });

  const quotes = data?.quotes ?? {};

  // ── Loading state — skeleton cells ───────────────────────────────────────
  // WHY render a row of skeleton cells (not nothing): preventing layout shift
  // is critical in the TopBar — the skeletons pre-allocate the horizontal
  // space the tape will occupy. No duplicate copy while loading (no animation
  // until real data exists — skeletons must stay static per §6.2).
  if (isLoading || !tickerToId) {
    return (
      <div
        className="hidden xl:flex w-full items-center gap-1.5 overflow-hidden"
        aria-label="Loading market index prices"
        aria-busy="true"
      >
        {INDEX_STRIP_TICKERS.map((t) => (
          <div
            key={t.canonicalTicker}
            // WHY static (no animate-pulse): Terminal Dark skeletons are STATIC
            // muted blocks — Bloomberg-style. See DESIGN_SYSTEM.md §6.2 (only
            // the slow opt-in `animate-skeleton-pulse` is permitted, and never
            // raw Tailwind `animate-pulse`).
            className="h-[22px] w-[60px] shrink-0 rounded-[2px] bg-muted/30"
            aria-hidden
          />
        ))}
      </div>
    );
  }

  // One full content-width pass per duration; scaled per-cell so the pixel
  // velocity is constant regardless of manifest size (see constant docstring).
  const marqueeDuration = `${Math.round(INDEX_STRIP_TICKERS.length * MARQUEE_SECONDS_PER_CELL)}s`;

  return (
    /*
     * WHY hidden xl:block: below 1280px the TopBar has no room for the tape
     * after search + PortfolioSwitcher + right cluster (mobile = v1.1).
     * WHY w-full + overflow-hidden: the tape fills the entire flex-1 center
     * slot and clips the moving track at its boundary — the track itself is
     * w-max (wider than the container by design).
     */
    <div
      className="hidden xl:block w-full min-w-0 overflow-hidden"
      role="region"
      aria-label="Market index tape"
    >
      {/*
       * Animated track — two identical copies, translating 0 → -50%.
       * `.marquee-strip` (app/globals.css) supplies the keyframes, the
       * hover/focus-within pause, and the reduced-motion display:none.
       * w-max lets the track size to its content (2 × copy width) instead of
       * being squeezed by the overflow-hidden parent.
       */}
      <div
        className="marquee-strip flex w-max items-center"
        style={{ "--marquee-duration": marqueeDuration } as React.CSSProperties}
        data-testid="index-strip-marquee"
      >
        <TickerCells tickerToId={tickerToId} quotes={quotes} />
        {/* Visual duplicate — aria-hidden + tabIndex -1 (see TickerCells). */}
        <TickerCells tickerToId={tickerToId} quotes={quotes} inert />
      </div>

      {/*
       * Reduced-motion fallback — hidden by default; the global
       * `@media (prefers-reduced-motion: reduce)` block flips it to
       * display:flex (and hides .marquee-strip). A SINGLE copy with
       * overflow-x-auto: motion-sensitive users get a normal static row they
       * can scroll horizontally — never a frozen half-loop frame.
       */}
      <div
        className="marquee-static-fallback hidden w-full items-center overflow-x-auto"
        data-testid="index-strip-static-fallback"
      >
        <TickerCells tickerToId={tickerToId} quotes={quotes} />
      </div>
    </div>
  );
}
