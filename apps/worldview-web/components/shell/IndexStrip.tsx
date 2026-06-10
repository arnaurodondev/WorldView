/**
 * components/shell/IndexStrip.tsx — Static 10-ticker index strip for TopBar.
 *
 * WHY THIS EXISTS: Replaces the animated TopBarMarquee. Bloomberg Terminal's
 * fixed-header conventions show key index prices in a static row — no animation.
 * Traders scan a static row faster than a scrolling one because the values
 * don't require anticipating animation phase. The marquee also consumed the
 * entire center slot with CSS animation; a static row of 10 cells allows a
 * predictable 60px-per-cell layout that yields exactly when to truncate under
 * width pressure.
 *
 * WHY STATIC TICKER LIST (not user-customisable in v1):
 * The manifest covers the 5 major asset classes an institutional PM watches:
 *   US Equities: SPY, QQQ, IWM, DIA
 *   Volatility:  VIX
 *   Fixed income: TLT, ^TNX (10-year Treasury yield)
 *   Commodities: GLD, USO
 *   Crypto:      BTC-USD
 * Custom manifests are a v1.1 feature.
 *
 * WHY priority-drop (not truncate) at narrow viewports:
 * Truncating a ticker mid-label ("SP…") is unusable for trading.
 * Instead we drop lower-priority tickers completely as viewport narrows so
 * every visible ticker shows its full three-field (ticker / price / chg%).
 * At <1024px the strip hides entirely — mobile UX is v1.1.
 *
 * DATA FLOW (two-step, same as the former marquee):
 *   1. Resolve 10 ticker symbols → instrument_id UUIDs via resolveTickersBatch.
 *      staleTime=30min (instrument IDs are stable identifiers).
 *   2. Batch-quote resolved UUIDs every 15s via POST /v1/quotes/batch.
 *
 * WHO USES IT: components/shell/TopBar.tsx (center slot).
 * DESIGN REFERENCE: PRD-0089 W1 §4.1; lock §3 (C-10, C-33, FU-4.3).
 */

"use client";
// WHY "use client": uses TanStack Query (browser-only) + useRouter (navigation).

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";

// ── Ticker manifest (locked per plan §4.1 + FU-4.3) ──────────────────────────

/**
 * INDEX_STRIP_TICKERS — 10-cell manifest, left-to-right display order.
 *
 * priority: lower number = dropped last as viewport narrows.
 *   Priority 1-4 (equity indices) survive down to ~760px wide TopBar.
 *   Priority 5-10 drop in reverse order as the row gets shorter.
 * canonicalTicker: the key used for resolveTickersBatch AND as the URL segment.
 * displayLabel:    short label rendered in the cell (drops "^" which looks odd in the strip).
 * fullName:        Tooltip text shown on hover (Radix-free, just title= for v1 simplicity).
 */
interface TickerConfig {
  canonicalTicker: string; // used for API resolution (e.g. "^TNX")
  displayLabel: string;    // label in the 60px cell (e.g. "TNX")
  fullName: string;        // tooltip / aria-label
  priority: number;        // 1 = highest priority (dropped last)
}

const INDEX_STRIP_TICKERS: readonly TickerConfig[] = [
  { canonicalTicker: "SPY",     displayLabel: "SPY",     fullName: "SPDR S&P 500 ETF",         priority: 1 },
  { canonicalTicker: "QQQ",     displayLabel: "QQQ",     fullName: "Invesco QQQ (Nasdaq-100)",  priority: 2 },
  { canonicalTicker: "IWM",     displayLabel: "IWM",     fullName: "iShares Russell 2000",      priority: 3 },
  { canonicalTicker: "DIA",     displayLabel: "DIA",     fullName: "SPDR Dow Jones ETF",        priority: 4 },
  { canonicalTicker: "VIX",     displayLabel: "VIX",     fullName: "CBOE Volatility Index",     priority: 5 },
  { canonicalTicker: "TLT",     displayLabel: "TLT",     fullName: "iShares 20+ Year Treasury", priority: 6 },
  { canonicalTicker: "^TNX",    displayLabel: "TNX",     fullName: "10-Year Treasury Yield",    priority: 7 },
  { canonicalTicker: "GLD",     displayLabel: "GLD",     fullName: "SPDR Gold Shares",          priority: 8 },
  { canonicalTicker: "USO",     displayLabel: "USO",     fullName: "United States Oil Fund",    priority: 9 },
  { canonicalTicker: "BTC-USD", displayLabel: "BTC",     fullName: "Bitcoin / USD",             priority: 10 },
];

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
 * architecture test (no-off-palette-colors.test.ts). `text-positive` and
 * `text-negative` resolve to the correct hue from the global CSS tokens.
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
 * formatPrice — compact price for the 60px cell.
 * >10,000: compact "10K" / "1.2M". ≤9,999: two decimals.
 *
 * WHY not `formatPrice` from lib/utils: the lib version always shows two decimal
 * places which overflows the 60px cell for BTC ($65,234.12 → "65.2K" is fine).
 */
function formatIndexPrice(price: number | undefined): string {
  if (price == null) return "—";
  if (price >= 1_000_000) return `${(price / 1_000_000).toFixed(1)}M`;
  if (price >= 10_000) return `${(price / 1_000).toFixed(1)}K`;
  return price.toFixed(2);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IndexStrip() {
  const { accessToken } = useAuth();
  const router = useRouter();

  // ── Step 1: Resolve ticker symbols → instrument_id UUIDs ─────────────────
  // WHY resolveTickersBatch (not individual searchInstruments): exact-match
  // lookup avoids the "TLT → CTLT" substring-match bug from IndexTicker.tsx.
  // One batch call vs. 10 serial calls is also ~8× faster.
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
  // WHY always render 10 skeleton cells (not 0): preventing layout shift is
  // critical in the TopBar — the skeleton pre-allocates the same horizontal
  // space that the real data will occupy. If we rendered nothing, the
  // PortfolioRail + right cluster would shift on hydration.
  if (isLoading || !tickerToId) {
    return (
      <div
        className="hidden xl:flex items-center gap-1.5 overflow-hidden"
        aria-label="Loading market index prices"
        aria-busy="true"
      >
        {INDEX_STRIP_TICKERS.map((t) => (
          <div
            key={t.canonicalTicker}
            // WHY static (no animate-pulse): Terminal Dark skeletons are STATIC
            // muted blocks — Bloomberg-style. Round-3 polish removed the
            // animate-pulse that slipped in here; see DESIGN_SYSTEM.md §6.2
            // (only the slow opt-in `animate-skeleton-pulse` is permitted, and
            // never raw Tailwind `animate-pulse`).
            className="h-[22px] w-[60px] shrink-0 rounded-[2px] bg-muted/30"
            aria-hidden
          />
        ))}
      </div>
    );
  }

  return (
    /*
     * WHY hidden xl:flex (not hidden lg:flex):
     * The full 10-cell strip needs ~680px. At xl (1280px) the TopBar has enough
     * slack after search + PortfolioSwitcher + right cluster. Below 1024px the
     * strip hides entirely (mobile = v1.1 per plan §12). We use `xl:flex` as the
     * breakpoint; priority-drop CSS handles in-between sizes via the cell-level
     * hidden/flex classes below.
     *
     * WHY overflow-hidden: stops the strip from causing TopBar horizontal scroll.
     * The flex layout truncates the strip at the container boundary — hidden cells
     * simply don't render their slot at narrower viewports.
     */
    <div
      className="hidden xl:flex items-center gap-1.5 overflow-hidden shrink-0"
      role="region"
      aria-label="Market index strip"
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
            aria-label={`${ticker.fullName}: ${formatIndexPrice(quote?.price)} (${formatChg(quote?.change_pct)})`}
            // WHY w-[60px] shrink-0: each cell is a fixed 60px slot so the strip
            // width is predictable and priority-drop breakpoints are deterministic.
            // shrink-0 prevents the flex container from squeezing cells.
            //
            // WHY priority-drop visibility classes:
            // We use responsive hidden/flex utilities on the cells to drop them
            // in priority order as the viewport narrows. The outer xl:flex container
            // already hides below 1280px — these breakpoints are for ultra-narrow
            // within the xl+ range (e.g. 1280px laptop with sidebar expanded).
            className={cn(
              "flex w-[60px] shrink-0 flex-col items-start px-0.5 hover:bg-muted/20",
              // Priority 9 (USO) + 10 (BTC) drop first — hide below 2xl (1536px)
              ticker.priority >= 9 && "hidden 2xl:flex",
              // Priority 7-8 (TNX, GLD) hide below a custom 1440px breakpoint.
              // We use a responsive class defined via the xl range for simplicity.
              // (In practice these stay visible at xl=1280 but drop first within xl)
              ticker.priority === 7 || ticker.priority === 8 ? "hidden [@media(min-width:1440px)]:flex" : "",
            )}
          >
            {/* Ticker label — monospace, medium weight, foreground */}
            <span className="font-mono font-medium text-[11px] text-foreground leading-none">
              {ticker.displayLabel}
            </span>
            {/* Price + chg% on the same 11px/10px line — stacked vertically */}
            <span className="font-mono tabular-nums text-[11px] text-foreground leading-none">
              {formatIndexPrice(quote?.price)}
            </span>
            <span className={cn("font-mono tabular-nums text-[10px] leading-none", chgClass(quote?.change_pct))}>
              {formatChg(quote?.change_pct)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
