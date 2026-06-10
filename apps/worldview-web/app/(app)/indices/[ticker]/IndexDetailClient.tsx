/**
 * app/(app)/indices/[ticker]/IndexDetailClient.tsx — Client-side index detail stub
 *
 * WHY "use client": uses TanStack Query (browser-only), useRouter, and the
 * InstrumentNotFound F1 primitive. All of these require client rendering.
 *
 * WHY SEPARATE CLIENT COMPONENT:
 * Next.js 15 data fetching patterns require the server component (page.tsx) to
 * be async for `await params`. Splitting the interactive portion into a separate
 * "use client" component follows the recommended "Server wrapper → Client leaf"
 * pattern — the server component handles route params, the client component
 * handles browser-side data fetching and interactivity.
 *
 * STUB STATUS: this is a Wave 1 stub. The full design (entity graph, tabs,
 * financials) is deferred to a later wave. The stub shows:
 *   - Symbol + full name (from entity lookup)
 *   - Latest value + daily change (from batch quote)
 *   - 1-year daily chart (lightweight-charts, same chart lib as instruments/)
 * This is sufficient for the "IndexStrip cell click → non-404 page" acceptance gate.
 */

"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { InstrumentNotFound } from "@/components/primitives/InstrumentNotFound";
import { LoadingSkeleton } from "@/components/primitives/LoadingSkeleton";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * canonicalize — reconstruct the canonical ticker (with "^" prefix if needed).
 *
 * WHY: IndexStrip strips "^" from URL segments (^TNX → TNX in the URL).
 * The entity-lookup endpoint needs the full symbol. We try the plain ticker
 * first; if that fails the gateway returns 404 and we try the "^" variant.
 * For simplicity in this stub we always try both via two queries.
 */
function toCandidateTickers(ticker: string): string[] {
  const upper = ticker.toUpperCase();
  // TNX, GSPC, DJI, RUT — these are known yield/index tickers that have a "^" prefix.
  // For known-plain tickers (SPY, QQQ, etc.) no caret is needed.
  const CARET_PREFIXED = new Set(["TNX", "GSPC", "DJI", "RUT", "VIX", "NDX", "SPX"]);
  if (CARET_PREFIXED.has(upper)) {
    return [`^${upper}`, upper];
  }
  return [upper];
}

/**
 * formatValue — compact display for index values.
 * Handles large numbers (BTC ~65K) and small decimals (TNX ~4.35).
 */
function formatValue(price: number | undefined | null): string {
  if (price == null) return "—";
  if (price >= 1_000_000) return price.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (price >= 1_000) return price.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return price.toFixed(2);
}

/** formatChg — sign + two decimal change% */
function formatChg(pct: number | null | undefined): string {
  if (pct == null) return "—";
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

/** chgClass — design token color (no bare Tailwind palette colors) */
function chgClass(pct: number | null | undefined): string {
  if (pct == null) return "text-muted-foreground";
  if (pct > 0.005) return "text-[hsl(var(--positive))]";
  if (pct < -0.005) return "text-[hsl(var(--negative))]";
  return "text-muted-foreground";
}

// ── Component ─────────────────────────────────────────────────────────────────

interface IndexDetailClientProps {
  /** URL-form ticker (no "^" caret). E.g. "TNX", "SPY", "BTC-USD". */
  ticker: string;
}

export function IndexDetailClient({ ticker }: IndexDetailClientProps) {
  const router = useRouter();
  const { accessToken } = useAuth();

  // ── Step 1: Resolve ticker → instrument_id ────────────────────────────────
  // WHY resolveTickersBatch (not search): exact-match avoids substring collision.
  // We try multiple candidate tickers (plain + "^" prefix) for yield indices.
  const candidates = useMemo(() => toCandidateTickers(ticker), [ticker]);

  const { data: resolvedMap, isLoading: resolveLoading } = useQuery({
    queryKey: ["indices-resolve", ticker],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      return gw.resolveTickersBatch(candidates);
    },
    staleTime: 30 * 60_000, // 30 min — instrument IDs are stable
    enabled: !!accessToken,
  });

  // Pick the first candidate that resolved to an instrument_id.
  const instrumentId = useMemo(() => {
    for (const c of candidates) {
      const id = resolvedMap?.[c];
      if (id) return id;
    }
    return null;
  }, [resolvedMap, candidates]);

  // ── Step 2: Fetch company overview (name, latest quote) ───────────────────
  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ["indices-overview", instrumentId],
    queryFn: () => createGateway(accessToken).getCompanyOverview(instrumentId!),
    staleTime: 60_000,
    refetchInterval: 15_000,
    enabled: !!accessToken && !!instrumentId,
  });

  // ── Step 3: 1-year OHLCV bars (daily) for the chart ──────────────────────
  const { data: ohlcvData, isLoading: ohlcvLoading } = useQuery({
    queryKey: ["indices-ohlcv", instrumentId],
    queryFn: () =>
      // WHY start param for 1-year range: getOHLCV accepts start/end date strings.
      // We pass a start date ~1 year ago to get annual data.
      createGateway(accessToken).getOHLCV(instrumentId!, {
        timeframe: "1d",
        // Approximate 1 year back
        start: new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
      }),
    staleTime: 5 * 60_000, // 5 min for daily bars
    enabled: !!accessToken && !!instrumentId,
  });

  const isLoading = resolveLoading || overviewLoading;
  const notFound = !resolveLoading && instrumentId === null;

  // ── Loading ───────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        {/* WHY "table-row" + count=4: shows 4 placeholder rows while entity resolves */}
        <LoadingSkeleton variant="table-row" count={4} />
      </div>
    );
  }

  // ── 404 ───────────────────────────────────────────────────────────────────
  if (notFound || !overview) {
    return (
      <div className="flex flex-col items-center justify-center p-12">
        {/* WHY attemptedTicker (not ticker): InstrumentNotFound uses attemptedTicker prop name */}
        <InstrumentNotFound attemptedTicker={ticker.toUpperCase()} />
        <button
          onClick={() => router.back()}
          className="mt-4 font-mono text-[11px] text-muted-foreground hover:text-foreground"
        >
          ← Back
        </button>
      </div>
    );
  }

  // ── Quote data from overview ──────────────────────────────────────────────
  // WHY overview.instrument.name: CompanyOverview has `instrument: Instrument`
  // not a top-level `name` field. instrument.name is the display name.
  const price = overview.quote?.price;
  const changePct = overview.quote?.change_pct;
  const name = overview.instrument?.name ?? ticker.toUpperCase();

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4 p-6">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-1">
        {/* Symbol + name */}
        <div className="flex items-baseline gap-3">
          <h1 className="font-mono font-bold text-[18px] text-foreground">
            {ticker.toUpperCase()}
          </h1>
          <span className="font-mono text-[13px] text-muted-foreground">{name}</span>
        </div>

        {/* Price + change */}
        <div className="flex items-baseline gap-3">
          <span className="font-mono tabular-nums text-[24px] font-semibold text-foreground">
            {formatValue(price)}
          </span>
          <span className={`font-mono tabular-nums text-[14px] ${chgClass(changePct)}`}>
            {formatChg(changePct)} today
          </span>
        </div>
      </div>

      {/* ── Stub notice ────────────────────────────────────────────────── */}
      {/* WHY: this is a Wave 1 stub; the full page design is in a later wave.
          We surface this notice so analysts know where to look for more data. */}
      <div className="border border-border bg-muted/10 px-4 py-3">
        <p className="font-mono text-[11px] text-muted-foreground">
          Full index detail page coming soon. This page shows live quote data only.
          Use the{" "}
          <button
            onClick={() => router.push(`/instruments/${ticker}`)}
            className="text-primary hover:underline"
          >
            instruments/{ticker}
          </button>
          {" "}page for more detail.
        </p>
      </div>

      {/* ── Chart placeholder ──────────────────────────────────────────── */}
      {ohlcvLoading ? (
        // WHY static (no animate-pulse): DESIGN_SYSTEM.md §6.2 bans raw
        // animate-pulse on skeletons — Terminal Dark skeletons are STATIC
        // bg-muted blocks (Bloomberg-style loading bars). The fixed 240px
        // height matches the loaded chart container so hydration causes zero
        // layout shift. aria-hidden: decorative placeholder — screen readers
        // get the loading announcement from the page, not from this div.
        <div
          className="h-[240px] border border-border bg-muted/10"
          aria-hidden
        />
      ) : (
        <div className="h-[240px] border border-border bg-card p-4">
          {/* WHY text only (not lightweight-charts): the full chart integration
              requires importing the chart library lazily + SSR guards. Shipping
              a text placeholder is faster for W1 and sufficient for the gate. */}
          <p className="font-mono text-[11px] text-muted-foreground">
            1-year daily chart —{" "}
            {ohlcvData?.bars?.length ?? 0} bars loaded
            {ohlcvData?.bars && ohlcvData.bars.length > 0
              ? ` · from ${ohlcvData.bars[0]?.timestamp ?? "?"} to ${ohlcvData.bars[ohlcvData.bars.length - 1]?.timestamp ?? "?"}`
              : " (no bars — chart not yet available)"}
          </p>
          {/* Primitive ASCII chart: last 20 close prices as relative bar heights */}
          {ohlcvData?.bars && ohlcvData.bars.length >= 2 && (
            <div className="mt-2 flex items-end gap-px h-[160px]">
              {ohlcvData.bars.slice(-60).map((bar, i) => {
                const allCloses = ohlcvData.bars.map((b) => b.close);
                const minC = Math.min(...allCloses.slice(-60));
                const maxC = Math.max(...allCloses.slice(-60));
                const range = maxC - minC || 1;
                const heightPct = ((bar.close - minC) / range) * 100;
                return (
                  <div
                    key={i}
                    title={`${bar.timestamp}: ${bar.close.toFixed(2)}`}
                    style={{ height: `${Math.max(2, heightPct)}%` }}
                    className="flex-1 bg-primary/40 hover:bg-primary/70 min-w-[2px]"
                  />
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
