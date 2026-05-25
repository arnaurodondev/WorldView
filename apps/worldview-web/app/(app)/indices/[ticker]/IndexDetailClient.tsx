/**
 * app/(app)/indices/[ticker]/IndexDetailClient.tsx — Index detail client.
 *
 * WHY split from page.tsx: the server entry awaits the params Promise; the
 * actual data fetching uses TanStack Query which is client-only. Keeping
 * the client component in its own file makes the boundary explicit.
 *
 * DESIGN REFERENCE: PRD-0089 W1 plan §4.9 — quote-style summary with
 * ticker / full name / latest value / daily change / 1-day intraday line.
 * Richer surface (full chart, technicals, correlations) ships in a later
 * wave; this stub exists so the TopBar IndexStrip cells land somewhere
 * useful instead of 404-ing.
 */

"use client";
// WHY "use client": TanStack Query + the F1 Sparkline primitive both need
// to render in the browser to read the cache + dispatch fetches.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { Sparkline } from "@/components/primitives/Sparkline";
import { InstrumentNotFound } from "@/components/primitives/InstrumentNotFound";
import { formatPrice } from "@/lib/format";
import { priceChangeClass, formatPercentDirect } from "@/lib/utils";

// ── Friendly-name lookup for the 10 manifest tickers ───────────────────────
//
// IndexStrip resolves these to instrument_id; here we just want a display
// name without round-tripping. Tickers not in the table fall back to the
// raw symbol — the gateway resolution is still authoritative for the
// quote value, so a missing label entry only impacts the heading text.
const FRIENDLY_NAME: Record<string, string> = {
  SPY: "S&P 500 ETF",
  QQQ: "Nasdaq-100 ETF",
  IWM: "Russell 2000 ETF",
  DIA: "Dow Jones Industrial ETF",
  VIX: "CBOE Volatility Index",
  TLT: "20+ Year Treasury Bond ETF",
  TNX: "10-Year Treasury Yield",
  GLD: "SPDR Gold Trust",
  USO: "US Oil Fund",
  "BTC-USD": "Bitcoin (USD)",
};

interface IndexDetailClientProps {
  readonly ticker: string;
}

export function IndexDetailClient({ ticker }: IndexDetailClientProps) {
  const { accessToken } = useAuth();
  const friendlyName = FRIENDLY_NAME[ticker] ?? ticker;

  // Resolve ticker → instrument_id. searchInstruments is the same path
  // IndexStrip uses so the resolution cache is shared across the two
  // surfaces (cached 30 min in TanStack — IndexStrip primes it on first
  // render).
  const { data: searchResult, isLoading: searchLoading } = useQuery({
    queryKey: qk.search.query(ticker, "index-lookup"),
    queryFn: () => createGateway(accessToken).searchInstruments(ticker, 1),
    enabled: !!accessToken,
    staleTime: 30 * 60_000,
  });
  const instrumentId = searchResult?.results?.[0]?.instrument_id ?? null;

  // Latest quote — 15 s polling matches IndexStrip so we never duplicate
  // the network round trip.
  const { data: quotesResp } = useQuery({
    queryKey: qk.shell.indexQuotes(instrumentId ? [instrumentId] : []),
    queryFn: () => createGateway(accessToken).getBatchQuotes([instrumentId!]),
    enabled: !!accessToken && !!instrumentId,
    refetchInterval: 15_000,
    staleTime: 0,
  });
  const quote = instrumentId ? quotesResp?.quotes?.[instrumentId] : undefined;

  // 1-day intraday line — 78 bars × 5m = full US session, same key namespace
  // as the WatchlistPanel so the cache is shared when this ticker is also
  // in the user's watchlist.
  const { data: barsResp } = useQuery({
    queryKey: qk.instruments.ohlcvBatch(instrumentId ? [ticker] : [], "5m", 78),
    queryFn: () =>
      createGateway(accessToken).getBatchOhlcvBars({
        instrument_ids: [instrumentId!],
        timeframe: "5m",
        limit: 78,
      }),
    enabled: !!accessToken && !!instrumentId,
    refetchInterval: 60_000,
    staleTime: 60_000,
  });
  const closeSeries = useMemo<number[]>(() => {
    const r = barsResp?.results?.[0];
    return r?.bars.map((b) => b.close) ?? [];
  }, [barsResp]);

  // No resolution → render the F1 not-found surface, identical to the
  // /instruments/{ticker} treatment so the user gets a consistent error UX.
  if (!searchLoading && !instrumentId) {
    return (
      <main className="flex h-full w-full items-center justify-center px-6 py-12">
        <InstrumentNotFound attemptedTicker={ticker} />
      </main>
    );
  }

  return (
    <main
      id="main"
      className="mx-auto flex max-w-4xl flex-col gap-4 px-6 py-8"
      aria-labelledby="index-heading"
    >
      {/* ── Header ────────────────────────────────────────── */}
      <header className="flex flex-col gap-1">
        <div className="flex items-baseline gap-3">
          <h1
            id="index-heading"
            className="font-mono text-[24px] font-semibold text-foreground"
          >
            {ticker}
          </h1>
          <span className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
            {friendlyName}
          </span>
        </div>
        {/* Latest spot value + daily change. tabular-nums so the numbers
            stay column-aligned as digits update each tick. */}
        <div className="flex items-baseline gap-4">
          <span className="font-mono text-[32px] tabular-nums text-foreground">
            {quote != null ? formatPrice(quote.price) : "—"}
          </span>
          <span
            className={`font-mono text-[14px] tabular-nums ${
              quote != null ? priceChangeClass(quote.change_pct) : "text-muted-foreground"
            }`}
          >
            {quote != null
              ? `${quote.change >= 0 ? "+" : ""}${quote.change.toFixed(2)} (${formatPercentDirect(quote.change_pct)})`
              : "—"}
          </span>
        </div>
      </header>

      {/* ── Intraday line (stub — 1-day, 78 5m bars) ─────────
          We deliberately render the F1 Sparkline primitive at scale
          (480×120) rather than mounting lightweight-charts for the
          stub. The richer chart (1Y daily, technical overlays, volume
          profile) ships in a later wave. */}
      <section className="flex flex-col gap-2" aria-label="Intraday chart">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Intraday (1d / 5m)
        </span>
        <div className="border border-border bg-card px-3 py-3">
          <Sparkline data={closeSeries} trend="auto" width={480} height={120} />
        </div>
        <p className="text-[10px] text-muted-foreground">
          Full chart, technicals, and correlations ship in a later wave —
          this page is a Wave 1 stub so IndexStrip cells land somewhere
          useful instead of 404-ing.
        </p>
      </section>
    </main>
  );
}
