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
 * WHY TWO-STEP FETCH (resolve → overview per ticker): We need instrument_ids
 * to call getCompanyOverview(), but we only know tickers at build time. Step 1
 * resolves tickers → instrument_ids; Step 2 fans out CompanyOverview queries
 * (one per ticker) via useQueries — the overview quote leg uses the full
 * PriceSnapshot fallback chain (BP-463: bare batch-price returns price=0 for
 * equities without seeded OHLCV). Step 2b (2026-06-10 unified-resolution fix)
 * ADDS a single POST /v1/quotes/batch call as a per-row FALLBACK for
 * instruments whose overview has no quote (IWM/VIX) — the same path the
 * TopBar IndexStrip uses, so the two surfaces can never disagree again.
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
// Round 4 (item 1): named error state + Retry — a failed ticker-resolution
// fetch previously fell through to "instruments not yet ingested" (a lie:
// the data exists, the REQUEST failed) with no recovery path.
import { WidgetErrorState } from "@/components/dashboard/WidgetErrorState";
import { Activity } from "lucide-react";
import { cn } from "@/lib/utils";
// HF-10: locale-grouped USD price ("$4,892.11").
import { formatPrice } from "@/lib/format";
// Round 3 (item 6): transient tint on price change — discrete state, no
// keyframe animation (NFR-6 compliant), disabled under prefers-reduced-motion.
import { usePriceFlash } from "@/features/dashboard/hooks/usePriceFlash";

// ── Snapshot instrument groups ────────────────────────────────────────────────

/**
 * SNAPSHOT_GROUPS — ordered row groups for the snapshot widget.
 *
 * WHY groups:
 *   "INDICES" — market-level context. Round 1 foundation spec requires the
 *               4 core index proxies a US-equity analyst scans every morning:
 *               SPY (S&P 500), QQQ (Nasdaq-100), IWM (Russell 2000 small-caps),
 *               VIX (CBOE volatility — the "fear gauge"). BTC is retained as a
 *               5th row because crypto risk-appetite was already shipped here
 *               (SA-2 PLAN-0088) and removing working data is a regression.
 *   "EQUITIES" — core large-cap US equities the analyst likely owns/watches.
 *
 * WHY IWM + VIX added (Round 1, 2026-06-10): the previous QQQ/SPY/BTC list
 * had no small-cap breadth signal and no volatility signal — both are part
 * of the standard "4-index" morning scan (SPY/QQQ/IWM/VIX). If VIX has no
 * instrument row in S3 (specialized index feed not yet ingested), the row
 * truthfully renders "—" rather than $0.00 — see the hasPrice guard below.
 *
 * The group separator is a thin muted label row, same pattern as Bloomberg's
 * "SECTORS / INDICES" dividers in the monitor panel.
 */
/**
 * UNIFIED RESOLUTION FIX (user report 2026-06-10 — "IWM/BTC show — while the
 * TopBar strip shows real prices"): this widget and the IndexStrip resolved
 * instruments DIFFERENTLY, producing contradictory data on the same screen:
 *   1. Ticker symbol: this widget asked resolveTickersBatch for "BTC" which
 *      resolves to NULL on S3 — the canonical row is "BTC-USD" (verified live
 *      2026-06-10). The strip already used "BTC-USD" and worked. Fix: each
 *      row now carries a `canonicalTicker` (API symbol) + `label` (display).
 *   2. Quote path: this widget read ONLY overview.quote, which is null for
 *      IWM/VIX (S9 /v1/companies/{id}/overview has no quote leg for several
 *      index ETFs), while the strip's POST /v1/quotes/batch returns IWM
 *      285.21 fine. Fix: keep the overview chain (BP-463 — batch returns
 *      price=0 for some equities) but FALL BACK to the strip's batch-quote
 *      path whenever the overview quote is missing or non-positive. Both
 *      components now agree by construction: any price the strip can show,
 *      this widget shows too.
 */
interface SnapshotInstrument {
  /** Symbol sent to resolveTickersBatch AND used in quote lookups. */
  canonicalTicker: string;
  /** Short label rendered in the 40px row slot ("BTC", not "BTC-USD"). */
  label: string;
}

interface SnapshotGroup {
  label: string;
  instruments: readonly SnapshotInstrument[];
}

const SNAPSHOT_GROUPS: SnapshotGroup[] = [
  {
    label: "INDICES",
    instruments: [
      { canonicalTicker: "SPY", label: "SPY" },
      { canonicalTicker: "QQQ", label: "QQQ" },
      { canonicalTicker: "IWM", label: "IWM" },
      { canonicalTicker: "VIX", label: "VIX" },
      // WHY BTC-USD (was "BTC"): "BTC" resolves to null on S3 — the
      // instrument row's ticker is "BTC-USD" (same symbol the IndexStrip
      // uses). The label stays "BTC" for the 40px row slot.
      { canonicalTicker: "BTC-USD", label: "BTC" },
    ],
  },
  {
    label: "EQUITIES",
    instruments: [
      { canonicalTicker: "AAPL", label: "AAPL" },
      { canonicalTicker: "MSFT", label: "MSFT" },
      { canonicalTicker: "NVDA", label: "NVDA" },
      { canonicalTicker: "AMZN", label: "AMZN" },
      { canonicalTicker: "GOOGL", label: "GOOGL" },
      { canonicalTicker: "JPM", label: "JPM" },
    ],
  },
];

// Flat list for the instrument_id lookup query key + per-row overview fan-out.
const ALL_INSTRUMENTS = SNAPSHOT_GROUPS.flatMap((g) => [...g.instruments]);
const ALL_TICKERS = ALL_INSTRUMENTS.map((i) => i.canonicalTicker);

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketSnapshotWidget() {
  const { accessToken } = useAuth();

  // ── Step 1: Resolve ticker → instrument_id via parallel searches ──────────
  // WHY useQuery with Promise.all: we search for all tickers in a single
  // single batch round-trip rather than 9 parallel search calls. The query key
  // includes all tickers so the result is cached as a unit.
  // WHY resolveTickersBatch (not searchInstruments per ticker): searchInstruments
  // does ILIKE '%AAPL%' on S3 which takes 2-4s cold per ticker. resolveTickersBatch
  // calls GET /api/v1/instruments/lookup?symbol=X (exact indexed match, ~20ms) for
  // each ticker in parallel server-side, returning in one ~200ms round-trip.
  // WHY staleTime 30min: instrument_ids are stable — no need to refetch often.
  // Round 4 (item 1): isError + refetch destructured so the widget can render
  // a named error state with a working Retry instead of silently degrading.
  // The ids query is the LOAD-BEARING one — if it fails, no overview query
  // ever fires (all are gated on a resolved instrument id), so the whole
  // panel has nothing to show. Overview-leg failures, by contrast, degrade
  // per-row to "—" (acceptable partial data, no panel-level error).
  const {
    data: instrumentMap,
    isLoading: idsLoading,
    isError: idsError,
    refetch: refetchIds,
    isFetching: idsFetching,
  } = useQuery({
    queryKey: ["market-snapshot-ids", ...ALL_TICKERS],
    queryFn: () =>
      createGateway(accessToken)
        .resolveTickersBatch(ALL_TICKERS)
        .then((map) =>
          Object.fromEntries(
            Object.entries(map).filter(([, id]) => id !== null),
          ) as Record<string, string>,
        ),
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

  // ── Step 2b: Batch-quote fallback (unified-resolution fix, 2026-06-10) ────
  // The SAME call the IndexStrip makes (POST /v1/quotes/batch). For rows
  // where the overview has no usable quote (IWM/VIX — overview.quote is null
  // on S9), this supplies the price the strip already shows. One extra HTTP
  // request for the whole widget; 15s staleTime matches the platform quote
  // cadence (DEFAULT_STALE.quotes) so repeated mounts hit cache.
  const resolvedIds = useMemo(
    () => Object.values(instrumentMap ?? {}).filter((id): id is string => !!id),
    [instrumentMap],
  );
  const { data: batchQuotesData } = useQuery({
    queryKey: ["market-snapshot-batch-quotes", ...resolvedIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(resolvedIds),
    enabled: !!accessToken && resolvedIds.length > 0,
    staleTime: 15_000,
    refetchInterval: 60_000,
  });

  // WHY two loading signals:
  //   isLoading (strict) — true until ALL queries resolve; used to switch the
  //     skeleton-vs-data render branches so partial data never shows alongside
  //     placeholder rows.
  //   hasAnyData — true as soon as ONE overview query resolves; used for the
  //     LIVE badge (FR-1.5 HIGH-013) so the badge appears at first data arrival
  //     rather than waiting for every ticker to respond. A trader with 5/9
  //     tickers loaded should see LIVE, not a blank header.
  const isLoading = idsLoading || overviewQueries.some((q) => q.isLoading);
  // WHY .some (not .every): shows LIVE when at least one ticker is resolved.
  // The previous implicit behavior (tied to isLoading=false) required ALL
  // tickers to finish before the badge appeared — a single slow ticker (e.g.
  // BTC search taking 500ms) would suppress LIVE on an otherwise live widget.
  const hasAnyData = overviewQueries.some((q) => q.data != null);

  // Ticker → quote map built from stable ALL_TICKERS index ordering.
  // useMemo avoids map reconstruction on every render.
  //
  // RESOLUTION LADDER (unified-resolution fix, 2026-06-10):
  //   1. overview.quote with a positive price — the BP-463-safe chain
  //      (FRESH_QUOTE → BULK_QUOTE → INTRADAY → DAILY_CLOSE → STALE).
  //   2. batch quote with a positive price — the IndexStrip's working path;
  //      covers IWM/VIX where the overview returns quote: null.
  //   3. null → the row truthfully renders "—".
  // The positive-price guard on BOTH legs keeps the BP-463 "price=0 means no
  // OHLCV" semantics: a zero is never preferred over a real value from the
  // other leg, and a double-zero still renders as "—" downstream.
  const quoteByTicker = useMemo(() => {
    const map = new Map<string, { price: number; change: number; change_pct: number } | null>();
    ALL_INSTRUMENTS.forEach((inst, i) => {
      const overviewQuote = overviewQueries[i]?.data?.quote;
      if (overviewQuote && (overviewQuote.price ?? 0) > 0) {
        map.set(inst.canonicalTicker, overviewQuote);
        return;
      }
      // Fallback: the batch-quote leg, keyed by resolved instrument id.
      const instrumentId = instrumentMap?.[inst.canonicalTicker];
      const batchQuote = instrumentId
        ? batchQuotesData?.quotes?.[instrumentId]
        : undefined;
      if (batchQuote && (batchQuote.price ?? 0) > 0) {
        map.set(inst.canonicalTicker, {
          price: batchQuote.price,
          change: batchQuote.change ?? 0,
          change_pct: batchQuote.change_pct ?? 0,
        });
        return;
      }
      map.set(inst.canonicalTicker, null);
    });
    return map;
  }, [overviewQueries, instrumentMap, batchQuotesData]);

  // Build display rows per group — include instrumentId so SnapshotRow can navigate.
  const groupRows = SNAPSHOT_GROUPS.map((group) => ({
    label: group.label,
    rows: group.instruments.map((inst) => {
      const instrumentId = instrumentMap?.[inst.canonicalTicker];
      const quote = quoteByTicker.get(inst.canonicalTicker) ?? null;
      return {
        ticker: inst.label,
        instrumentId: instrumentId ?? null,
        quote,
      };
    }),
  }));

  return (
    // WHY bg-background (not bg-card): consistent with all other dashboard widgets.
    // bg-card (#18181b) while neighbours use bg-background (#09090b) creates a
    // "raised card" visual inconsistency that breaks the flat Bloomberg aesthetic.
    // Round 4 (item 2): role="region" + aria-label — landmark per widget so
    // SR users can jump between dashboard panels by name instead of crawling
    // the whole grid row by row.
    <div
      className="flex h-full flex-col bg-background"
      role="region"
      aria-label="Market snapshot"
    >

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      {/* WHY h-5: Row 2 is capped at 130px; compact header frees rows for data. */}
      <div className="flex h-5 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          MARKET SNAPSHOT
        </span>
        {/* LIVE badge — communicates that this widget shows real-time data.
            WHY hasAnyData (not !isLoading): shows LIVE as soon as the first
            ticker resolves rather than waiting for every ticker to finish.
            FR-1.5 HIGH-013: "some" not "every" for partial-success UX. */}
        {hasAnyData && (
          <span className="text-[10px] text-positive/70">LIVE</span>
        )}
      </div>

      {/* ── Grouped instrument rows ───────────────────────────────────────── */}
      {/* Round 4 (item 1): error branch FIRST — when the ticker-resolution
          query fails there are no rows to render and the previous fallthrough
          ("—" rows + "instruments not yet ingested" footer) misdiagnosed a
          network failure as a data gap. Retry re-runs the ids query; on
          success the overview queries un-gate automatically (enabled flips). */}
      <div className="flex flex-1 flex-col overflow-auto">
        {idsError ? (
          <WidgetErrorState
            copyKey="dashboard.snapshot-error"
            icon={Activity}
            onRetry={() => void refetchIds()}
            retrying={idsFetching}
          />
        ) : isLoading ? (
          // Loading skeletons — 2 groups × (1 label + N rows)
          // Round 3 (item 3): the skeleton mirrors the loaded layout EXACTLY —
          // including the two 18px group-label separator rows and the loaded
          // row's 4 column slots (ticker 40px · price flex · change-$ 52px ·
          // change-% 64px) — so data arrival causes zero layout shift.
          <div>
            {SNAPSHOT_GROUPS.map((group, gIdx) => (
              <div key={group.label}>
                {/* Group-label slot — same h-[18px] chrome as the loaded view. */}
                <div
                  className={cn(
                    "flex h-[18px] items-center border-b border-border/20 px-2",
                    gIdx > 0 && "border-t border-border/30",
                  )}
                >
                  <Skeleton className="h-2 w-[44px]" />
                </div>
                <div className="divide-y divide-border/30">
                  {/* WHY group.instruments.length: skeleton row count must match
                      the loaded row count per group (5 INDICES + 6 EQUITIES). */}
                  {group.instruments.map(({ canonicalTicker }) => (
                    <div key={canonicalTicker} className="flex h-[22px] items-center gap-1 px-2">
                      <Skeleton className="h-3 w-[40px] shrink-0" />
                      <span className="flex-1" />
                      <Skeleton className="h-3 w-[48px] shrink-0" />
                      <Skeleton className="h-3 w-[52px] shrink-0" />
                      <Skeleton className="h-3 w-[64px] shrink-0" />
                    </div>
                  ))}
                </div>
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
                <span className="text-[9px] uppercase tracking-[0.1em] text-muted-foreground-dim">
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
        <span className="text-[10px] text-muted-foreground-dim">
          {/* Round 4 (item 1): the error branch gets its own truthful caption —
              "instruments not yet ingested" claimed a DATA gap when the
              REQUEST failed, sending the trader to the wrong triage path. */}
          {idsError
            ? "snapshot feed error"
            : isLoading
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

  // ── Round 3 (item 6): price-tick flash ────────────────────────────────────
  // Returns "up" / "down" for ~900ms after the refetched price differs from
  // the previous one, null otherwise. DESIGN_SYSTEM/NFR-6 bans animations on
  // data surfaces, so this is a DISCRETE background-tint state (no keyframes,
  // no movement) that the row's existing Tier-1 `transition-colors` softens.
  // The hook itself returns null under prefers-reduced-motion — see
  // features/dashboard/hooks/usePriceFlash.ts for the full rationale.
  const flash = usePriceFlash(hasPrice ? quote.price : null);

  // WHY only navigate when instrumentId is resolved: if the search step hasn't
  // returned yet, clicking would navigate to /instruments/null — a broken URL.
  const canNavigate = !!instrumentId;

  // WHY heat tint: mirrors the SectorHeatmapWidget tile color convention.
  // Rows with a meaningful move (|change%| ≥ 0.5) get a faint directional
  // tint so the trader can scan direction at a glance without reading numbers.
  // /5 opacity is subtle — the ticker label and change% are still primary.
  // WHY suppressed while flashing: the flash tint (/10) and the heat tint (/5)
  // are different bg-* utility classes whose CSS-cascade order is not
  // guaranteed — applying both would make the winner unpredictable. The flash
  // is the stronger, more transient signal, so it takes the slot for 900ms.
  const heatClass =
    !flash && hasPrice && changePct != null && Math.abs(changePct) >= 0.5
      ? isPositive
        ? "bg-positive/5"
        : "bg-negative/5"
      : "";

  // Flash tint — direction-coloured at /10 (one step above the resting heat
  // tint, still terminal-subtle). Cleared back to heat/none after 900ms.
  const flashClass =
    flash === "up" ? "bg-positive/10" : flash === "down" ? "bg-negative/10" : "";

  return (
    <div
      className={cn(
        "flex h-[22px] items-center justify-between px-2",
        heatClass,
        flashClass,
        // WHY cursor-pointer + hover:bg-muted/30 only when navigable.
        canNavigate && "cursor-pointer transition-colors hover:bg-muted/20",
        // Round 3 (item 5): keyboard affordance — rows are tabbable buttons,
        // so they need a visible :focus-visible ring. ring-inset because the
        // row is flush inside an overflow-auto strip (an outset ring would be
        // clipped by the container edge). ring-ring = --ring token (yellow).
        canNavigate &&
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
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

      {/* Price — center, muted (context); change is the primary signal.
          WHY "—" when hasPrice is false: truthfulness principle — show
          a dash when we have no real price rather than $0.00. */}
      <span className="flex-1 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {hasPrice ? formatPrice(quote?.price) : "—"}
      </span>

      {/* Day change $ — Round 1 foundation: the spec requires BOTH the dollar
          move and the percent move (a 1% move on SPY ≈ $5; on BTC ≈ $800 —
          the $ figure carries magnitude the % alone hides).
          WHY w-[52px] fixed: keeps the $/% columns aligned across rows so the
          eye can scan them as columns (ADR-F-15 numeric column convention).
          WHY toFixed(2) with explicit sign (not formatPrice): formatPrice
          renders "$5.12" without a sign — for a CHANGE value the +/- sign IS
          the signal, so we format manually. */}
      <span
        className={cn(
          "w-[52px] shrink-0 text-right font-mono text-[10px] tabular-nums",
          isPositive && "text-positive",
          isNegative && "text-negative",
          !hasPrice && "text-muted-foreground",
        )}
      >
        {hasPrice && quote?.change != null
          ? `${quote.change >= 0 ? "+" : ""}${quote.change.toFixed(2)}`
          : "—"}
      </span>

      {/* Change % with directional arrow — right-aligned, colored by direction.
          WHY ▲/▼ glyphs (not lucide icons): a text glyph inherits the row's
          font-mono metrics and color for free, costs no extra DOM nodes per
          row (11 rows render in this widget), and reads identically in
          screen-reader output via the aria-label on the row container. */}
      <span
        className={cn(
          "w-[64px] shrink-0 text-right font-mono text-[11px] tabular-nums",
          isPositive && "text-positive",
          isNegative && "text-negative",
          !hasPrice && "text-muted-foreground",
        )}
      >
        {hasPrice && changePct != null
          ? `${isPositive ? "▲" : "▼"} ${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`
          : "—"}
      </span>
    </div>
  );
}
