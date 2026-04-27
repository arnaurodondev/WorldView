/**
 * components/dashboard/MarketSnapshotWidget.tsx — Live equity snapshot widget
 *
 * WHY THIS EXISTS: The dashboard morning routine starts with a macro scan.
 * Without futures data (ES/NQ require EODHD macro integration not yet built),
 * we show live prices for the 6 most-watched equities in the portfolio — AAPL,
 * MSFT, NVDA, AMZN, GOOGL, JPM — as a representative market snapshot.
 *
 * WHY TWO-STEP FETCH (search → batch quotes): We need instrument_ids to call
 * getBatchQuotes(), but we only know tickers at build time. A single screener
 * pass returns instrument_ids for each ticker; we then batch-quote them.
 * WHY enabled guard on batchQuotes: only fetch quotes once instrument_ids
 * are resolved from the screener — avoids an empty batch-quote POST.
 *
 * WHY SHOW CHANGE% + PRICE: price tells the trader the absolute level;
 * change% tells them today's move. Both are required for a quick morning scan.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 2, col-span-4)
 * DATA SOURCE: S9 /v1/search/instruments (instrument_id lookup) + /v1/quotes/batch
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

"use client";
// WHY "use client": uses useQuery, useAuth, and useRouter (for row click navigation).

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// ── Snapshot instruments ──────────────────────────────────────────────────────

// WHY these 6 tickers: they are the 6 most-commonly watched large-cap US equities
// and represent a cross-section of sectors (Tech: AAPL/MSFT/NVDA/GOOGL/AMZN,
// Financials: JPM). All 6 are seeded in market_data_db.
const SNAPSHOT_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "JPM"] as const;

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketSnapshotWidget() {
  const { accessToken } = useAuth();

  // ── Step 1: Resolve ticker → instrument_id via parallel searches ──────────
  // WHY useQuery with Promise.all: we search for all 6 tickers in a single
  // concurrent batch rather than 6 serial queries. The query key includes all
  // tickers so the result is cached as a unit.
  const { data: instrumentMap, isLoading: idsLoading } = useQuery({
    queryKey: ["market-snapshot-ids", ...SNAPSHOT_TICKERS],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      // Search for each ticker in parallel, take first result's instrument_id
      const results = await Promise.all(
        SNAPSHOT_TICKERS.map((ticker) =>
          gw.searchInstruments(ticker, 1).then((resp) => ({
            ticker,
            instrument_id: resp.results?.[0]?.instrument_id ?? null,
          })),
        ),
      );
      // Build ticker → instrument_id map; drop any not found in S3
      return Object.fromEntries(
        results
          .filter((r) => r.instrument_id !== null)
          .map((r) => [r.ticker, r.instrument_id as string]),
      ) as Record<string, string>;
    },
    enabled: !!accessToken,
    // WHY 30min staleTime: instrument_ids are stable — no need to refetch often.
    staleTime: 30 * 60_000,
  });

  // ── Step 2: Batch-quote all resolved instrument_ids ───────────────────────
  const instrumentIds = Object.values(instrumentMap ?? {});

  const { data: quotesData, isLoading: quotesLoading } = useQuery({
    queryKey: ["market-snapshot-quotes", instrumentIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(instrumentIds),
    enabled: !!accessToken && instrumentIds.length > 0,
    // WHY 60s refetch: snapshot is a live market pulse; refresh every minute
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const isLoading = idsLoading || quotesLoading;

  // Build display rows: ticker → resolved quote (or undefined if not available)
  // WHY include instrumentId in row: SnapshotRow needs it to navigate to the instrument
  // detail page on click. The instrument detail page accepts instrument_id as the URL
  // segment (S9 overview accepts entity_id or instrument_id — see ADR-F-12 note).
  const rows = SNAPSHOT_TICKERS.map((ticker) => {
    const instrumentId = instrumentMap?.[ticker];
    const quote = instrumentId ? quotesData?.quotes?.[instrumentId] : undefined;
    return { ticker, instrumentId: instrumentId ?? null, quote };
  });

  return (
    // WHY bg-background (not bg-card): all other dashboard widgets use bg-background
    // so their surface level is uniform. bg-card (#18181b) while neighbours use
    // bg-background (#09090b) creates a visible "raised card" inconsistency that
    // breaks the flat Bloomberg terminal aesthetic. bg-background here makes the
    // widget visually flush with its neighbours in the gap-px grid.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      {/* WHY h-5 (A-2): Row 2 is capped at 130px. Reducing header from h-6 (24px)
          to h-5 (20px) frees 4px — lets one more data row be fully visible. */}
      <div className="flex h-5 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          MARKET SNAPSHOT
        </span>
        {/* WHY LIVE badge: communicates that this widget shows real-time data,
            not static placeholders like the previous version */}
        {!isLoading && instrumentIds.length > 0 && (
          <span className="text-[10px] text-positive/70">LIVE</span>
        )}
      </div>

      {/* ── Instrument rows ───────────────────────────────────────────────── */}
      <div className="flex-1 divide-y divide-border/30 overflow-auto">
        {isLoading
          ? Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex h-[22px] items-center justify-between px-2">
                <Skeleton className="h-3 w-[48px]" />
                <Skeleton className="h-3 w-[64px]" />
              </div>
            ))
          : rows.map(({ ticker, instrumentId, quote }) => (
              <SnapshotRow key={ticker} ticker={ticker} instrumentId={instrumentId} quote={quote} />
            ))}
      </div>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
        <span className="text-[10px] text-muted-foreground/60">
          {isLoading
            ? "loading…"
            : instrumentIds.length === 0
              ? "instruments not yet ingested"
              : "US large-cap equities · prior session"}
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

  // WHY only navigate when instrumentId is resolved: if the search step hasn't
  // returned yet, clicking would navigate to /instruments/null — a broken URL.
  // Disabling the cursor when not resolved avoids a confusing no-op.
  const canNavigate = !!instrumentId;

  return (
    <div
      className={cn(
        "flex h-[22px] items-center justify-between px-2",
        // WHY cursor-pointer + hover:bg-muted/30 only when navigable: shows
        // interactivity cue only once the instrument_id is resolved.
        // terminal hover-state convention: faint tint, no transition delay.
        canNavigate && "cursor-pointer transition-colors hover:bg-muted/30",
      )}
      onClick={() => {
        // WHY instrument_id in URL: the S9 /v1/companies/{id}/overview endpoint
        // accepts both entity_id and instrument_id. Since the search step returns
        // instrument_id, we use it here; the detail page resolves it correctly.
        if (canNavigate) router.push(`/instruments/${instrumentId}`);
      }}
      onKeyDown={(e) => {
        if (canNavigate && e.key === "Enter") router.push(`/instruments/${instrumentId}`);
      }}
      role={canNavigate ? "button" : undefined}
      tabIndex={canNavigate ? 0 : undefined}
      aria-label={canNavigate ? `Navigate to ${ticker} instrument page` : ticker}
      // WHY title: tooltip shows full ticker for future expansion when labels
      // are abbreviated (e.g., if we add sector labels)
      title={ticker}
    >
      {/* Ticker label — left-aligned, monospace, primary color */}
      <span className="w-[48px] shrink-0 font-mono text-[11px] tabular-nums text-foreground">
        {ticker}
      </span>

      {/* Price — center, muted (context); change% is the primary signal */}
      <span className="flex-1 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {quote?.price != null ? `$${quote.price.toFixed(2)}` : "—"}
      </span>

      {/* Change % — right-aligned, colored by direction */}
      <span
        className={cn(
          "w-[56px] shrink-0 text-right font-mono text-[11px] tabular-nums",
          isPositive && "text-positive",
          isNegative && "text-negative",
          !quote && "text-muted-foreground",
        )}
      >
        {changePct != null
          ? `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`
          : "—"}
      </span>
    </div>
  );
}
