/**
 * components/dashboard/MarketSnapshotWidget.tsx — Live market snapshot widget
 *
 * WHY THIS EXISTS: The dashboard morning routine starts with a macro scan.
 * This widget shows live prices for key market bellwethers in two groups:
 *   GROUP 1 — Market index ETFs (QQQ, SPY) and a crypto reference (BTC)
 *   GROUP 2 — Core large-cap equities (AAPL, MSFT, NVDA, AMZN, GOOGL, JPM)
 *
 * SA-2 PLAN-0088 Demo P1 REWRITE: extended from "6 large-cap equities" to
 * a richer snapshot grouping. The original version showed AAPL/MSFT/NVDA/
 * AMZN/GOOGL/JPM — a fine watchlist, but not a "market snapshot". Traders
 * want macro context (QQQ = tech index, BTC = risk appetite) alongside names.
 *
 * WHY QQQ AND BTC: both are seeded in market_data_db with real OHLCV prices.
 * SPY is included but may show "—" until OHLCV is ingested (no daily price).
 * VIX, 10Y yield, DXY, gold require specialized data sources not yet integrated.
 *
 * WHY TWO-STEP FETCH (search → overview per ticker): We need instrument_ids
 * to call getCompanyOverview(), but we only know tickers at build time. Step 1
 * resolves tickers → instrument_ids; Step 2 fans out CompanyOverview queries
 * (one per ticker) via useQueries. getBatchQuotes was replaced because it hits
 * S3 batch-price which returns price=0 for equities without seeded OHLCV data
 * (BP-463). getCompanyOverview uses the full PriceSnapshot fallback chain.
 *
 * WHY SHOW CHANGE% + PRICE: price tells the trader the absolute level;
 * change% tells them today's move. Both are required for a quick morning scan.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 2, col-span-3)
 * DATA SOURCE: S9 /v1/search/instruments + /v1/quotes/batch
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7; SA-2 PLAN-0088 Demo P1
 */

"use client";
// WHY "use client": uses useQuery, useAuth, and useRouter (for row click navigation).

import { useQuery, useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
// HF-10: locale-grouped USD price ("$4,892.11").
import { formatPrice } from "@/lib/format";

// ── Snapshot instrument groups ────────────────────────────────────────────────

/**
 * SNAPSHOT_GROUPS — ordered row groups for the snapshot widget.
 *
 * WHY groups:
 *   "INDICES" — market-level context. QQQ = tech ETF (daily benchmark),
 *               BTC = crypto risk-on signal. SPY is present as a slot but
 *               may show "—" until OHLCV data is ingested for that instrument.
 *   "EQUITIES" — core large-cap US equities the analyst likely owns/watches.
 *
 * WHY BTC in "INDICES" group: BTC has become a macro risk-on/risk-off signal
 * that institutional traders check alongside equity indices. Its daily change
 * correlates with growth/tech sentiment at market open.
 *
 * The group separator is a thin muted label row, same pattern as Bloomberg's
 * "SECTORS / INDICES" dividers in the monitor panel.
 */
interface SnapshotGroup {
  label: string;
  tickers: readonly string[];
}

const SNAPSHOT_GROUPS: SnapshotGroup[] = [
  { label: "INDICES", tickers: ["QQQ", "SPY", "BTC"] },
  { label: "EQUITIES", tickers: ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "JPM"] },
];

// Flat list for the instrument_id lookup query key + Promise.all
const ALL_TICKERS = SNAPSHOT_GROUPS.flatMap((g) => [...g.tickers]);

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketSnapshotWidget() {
  const { accessToken } = useAuth();

  // ── Step 1: Resolve ticker → instrument_id via parallel searches ──────────
  // WHY useQuery with Promise.all: we search for all tickers in a single
  // concurrent batch rather than serial queries. The query key includes all
  // tickers so the result is cached as a unit.
  // WHY staleTime 30min: instrument_ids are stable — no need to refetch often.
  const { data: instrumentMap, isLoading: idsLoading } = useQuery({
    queryKey: ["market-snapshot-ids", ...ALL_TICKERS],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      const results = await Promise.all(
        ALL_TICKERS.map((ticker) =>
          gw.searchInstruments(ticker, 1).then((resp) => ({
            ticker,
            // WHY first-result only: our seeded instruments have unique tickers.
            // The first result from a single-ticker search is always the canonical match.
            instrument_id: resp.results?.[0]?.instrument_id ?? null,
          })),
        ),
      );
      return Object.fromEntries(
        results
          .filter((r) => r.instrument_id !== null)
          .map((r) => [r.ticker, r.instrument_id as string]),
      ) as Record<string, string>;
    },
    enabled: !!accessToken,
    staleTime: 30 * 60_000,
  });

  // ── Step 2: Fetch CompanyOverview per ticker (parallel, one per instrument) ─
  // WHY useQueries not getBatchQuotes: getBatchQuotes → S3 batch-price returns
  // price=0 for equities that have no seeded OHLCV data (BP-463). By contrast,
  // getCompanyOverview → S9 /v1/companies/{id}/overview → S3 single-instrument
  // price uses the full PriceSnapshot fallback chain (FRESH_QUOTE → BULK_QUOTE
  // → INTRADAY → DAILY_CLOSE → STALE), giving us the best available price.
  // WHY staleTime 5min + refetchInterval 60s: overview sub-resources (fundamentals,
  // ohlcv) are slow-moving and can stay cached; the quote is refetched live.
  const overviewQueries = useQueries({
    queries: ALL_TICKERS.map((ticker) => {
      const instrumentId = instrumentMap?.[ticker] ?? null;
      return {
        queryKey: ["market-snapshot-overview", instrumentId ?? ticker],
        queryFn: () =>
          createGateway(accessToken).getCompanyOverview(instrumentId!),
        enabled: !!accessToken && !!instrumentId,
        staleTime: 5 * 60_000,
        refetchInterval: 60_000,
      };
    }),
  });

  const isLoading = idsLoading || overviewQueries.some((q) => q.isLoading);

  // Ticker → quote map built from stable ALL_TICKERS index ordering.
  // useMemo avoids map reconstruction on every render.
  const quoteByTicker = useMemo(() => {
    const map = new Map<string, { price: number; change: number; change_pct: number } | null>();
    ALL_TICKERS.forEach((ticker, i) => {
      const q = overviewQueries[i]?.data?.quote;
      map.set(ticker, q ?? null);
    });
    return map;
  }, [overviewQueries]);

  // Build display rows per group — include instrumentId so SnapshotRow can navigate.
  const groupRows = SNAPSHOT_GROUPS.map((group) => ({
    label: group.label,
    rows: group.tickers.map((ticker) => {
      const instrumentId = instrumentMap?.[ticker];
      const quote = quoteByTicker.get(ticker) ?? null;
      return { ticker, instrumentId: instrumentId ?? null, quote };
    }),
  }));

  return (
    // WHY bg-background (not bg-card): consistent with all other dashboard widgets.
    // bg-card (#18181b) while neighbours use bg-background (#09090b) creates a
    // "raised card" visual inconsistency that breaks the flat Bloomberg aesthetic.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      {/* WHY h-5: Row 2 is capped at 130px; compact header frees rows for data. */}
      <div className="flex h-5 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          MARKET SNAPSHOT
        </span>
        {/* LIVE badge — communicates that this widget shows real-time data,
            not static placeholders. */}
        {!isLoading && Object.keys(instrumentMap ?? {}).length > 0 && (
          <span className="text-[10px] text-positive/70">LIVE</span>
        )}
      </div>

      {/* ── Grouped instrument rows ───────────────────────────────────────── */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          // Loading skeletons — 2 groups × (1 label + N rows)
          <div className="divide-y divide-border/30">
            {Array.from({ length: 9 }).map((_, i) => (
              <div key={i} className="flex h-[22px] items-center justify-between px-2">
                <Skeleton className="h-3 w-[48px]" />
                <Skeleton className="h-3 w-[64px]" />
              </div>
            ))}
          </div>
        ) : (
          groupRows.map((group, gIdx) => (
            <div key={group.label}>
              {/* Group label row — thin muted divider following Bloomberg convention.
                  WHY h-[18px] (not 22px): group labels are section separators, not
                  data rows. Shorter height signals "this is chrome, not data". */}
              <div
                className={cn(
                  "flex h-[18px] items-center border-b border-border/20 px-2",
                  gIdx > 0 && "border-t border-border/30",
                )}
              >
                <span className="text-[9px] uppercase tracking-[0.1em] text-muted-foreground/50">
                  {group.label}
                </span>
              </div>

              {/* Data rows for this group */}
              <div className="divide-y divide-border/30">
                {group.rows.map(({ ticker, instrumentId, quote }) => (
                  <SnapshotRow
                    key={ticker}
                    ticker={ticker}
                    instrumentId={instrumentId}
                    quote={quote}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
        <span className="text-[10px] text-muted-foreground/60">
          {isLoading
            ? "loading..."
            : Object.keys(instrumentMap ?? {}).length === 0
              ? "instruments not yet ingested"
              : "indices · equities · prior session"}
        </span>
      </div>

    </div>
  );
}

// ── SnapshotRow ───────────────────────────────────────────────────────────────

interface SnapshotRowProps {
  ticker: string;
  // WHY instrumentId: needed for navigation to instrument detail page.
  // null when search hasn't resolved this ticker yet (widget is loading).
  instrumentId: string | null;
  quote?: { price: number; change: number; change_pct: number } | null;
}

function SnapshotRow({ ticker, instrumentId, quote }: SnapshotRowProps) {
  const router = useRouter();
  const changePct = quote?.change_pct;
  const isPositive = changePct != null && changePct >= 0;
  const isNegative = changePct != null && changePct < 0;

  // WHY hasPrice guard: a quote with price=0 means no OHLCV data was ingested
  // (SPY currently returns 0.0). Show "—" for both price and change% in that
  // case so the trader sees "no data" rather than "$0.00 +0.00%".
  const hasPrice = quote != null && (quote.price ?? 0) > 0;

  // WHY only navigate when instrumentId is resolved: if the search step hasn't
  // returned yet, clicking would navigate to /instruments/null — a broken URL.
  const canNavigate = !!instrumentId;

  // WHY heat tint: mirrors the SectorHeatmapWidget tile color convention.
  // Rows with a meaningful move (|change%| ≥ 0.5) get a faint directional
  // tint so the trader can scan direction at a glance without reading numbers.
  // /5 opacity is subtle — the ticker label and change% are still primary.
  const heatClass =
    hasPrice && changePct != null && Math.abs(changePct) >= 0.5
      ? isPositive
        ? "bg-positive/5"
        : "bg-negative/5"
      : "";

  return (
    <div
      className={cn(
        "flex h-[22px] items-center justify-between px-2",
        heatClass,
        // WHY cursor-pointer + hover:bg-muted/30 only when navigable.
        canNavigate && "cursor-pointer transition-colors hover:bg-muted/20",
      )}
      onClick={() => {
        if (canNavigate) router.push(`/instruments/${instrumentId}`);
      }}
      onKeyDown={(e) => {
        if (canNavigate && e.key === "Enter") router.push(`/instruments/${instrumentId}`);
      }}
      role={canNavigate ? "button" : undefined}
      tabIndex={canNavigate ? 0 : undefined}
      aria-label={canNavigate ? `Navigate to ${ticker} instrument page` : ticker}
      title={ticker}
    >
      {/* Ticker label — left-aligned, monospace, primary color */}
      <span className="w-[40px] shrink-0 font-mono text-[11px] tabular-nums text-foreground">
        {ticker}
      </span>

      {/* Price — center, muted (context); change% is the primary signal.
          WHY "—" when hasPrice is false: truthfulness principle — show
          a dash when we have no real price rather than $0.00. */}
      <span className="flex-1 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {hasPrice ? formatPrice(quote?.price) : "—"}
      </span>

      {/* Change % — right-aligned, colored by direction */}
      <span
        className={cn(
          "w-[56px] shrink-0 text-right font-mono text-[11px] tabular-nums",
          isPositive && "text-positive",
          isNegative && "text-negative",
          !hasPrice && "text-muted-foreground",
        )}
      >
        {hasPrice && changePct != null
          ? `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`
          : "—"}
      </span>
    </div>
  );
}
