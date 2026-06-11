/**
 * components/dashboard/PreMarketMoversWidget.tsx — Top gainers + losers side-by-side
 *
 * WHY THIS EXISTS: Traders scan for outliers every morning — stocks with unusual
 * daily moves signal events worth investigating. Showing gainers and losers
 * simultaneously (two columns) lets the trader assess both sides of the market
 * in a single scan, more efficiently than a tab-toggle approach.
 *
 * WHY TWO COLUMNS (not tabs): Unlike the full TopMovers widget that has pagination
 * and detail, this dashboard widget is read-only context. Two static columns fill
 * the col-span-5 cell and give equal visual weight to both directions.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 3, col-span-5)
 * DATA SOURCE: S9 GET /api/v1/market/top-movers via createGateway().getTopMovers()
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

"use client";
// WHY "use client": uses useQuery, useQueries, useAuth, useState for period selector + sector pills, and useRouter for nav.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/query/keys";
import { useRouter } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";
// HF-10: locale-grouped USD price ("$4,892.11").
import { formatPrice } from "@/lib/format";
import type { Mover } from "@/types/api";
// PLAN-0048 Wave F-2: shared sector pill list (re-used by F-1 SectorHeatmap and
// future Wave E WatchlistMoversWidget) so all three widgets keep identical
// pill ordering, labels, and matching logic.
import {
  SECTOR_PILLS,
  ALL_SECTORS_VALUE,
  matchesSectorFilter,
} from "@/lib/sectors";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * PreMarketMoversWidget — shows top 5 gainers | losers from getTopMovers().
 * Uses a single query and sorts client-side to avoid two round-trips.
 */
// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * WHY 1D/1W/1M period selector:
 * Traders care about movers over different horizons. 1D = today's session,
 * 1W = weekly trend, 1M = monthly momentum. The period state is local for now —
 * the API call will be wired to filter by period in a future wave when S9 exposes
 * a period parameter on the top-movers endpoint.
 */
type MoverPeriod = "1D" | "1W" | "1M";

export function PreMarketMoversWidget() {
  const { accessToken } = useAuth();

  // WHY local state (not URL param): the period selection is scoped to this widget
  // and doesn't need to be bookmarkable or synced with other components.
  // Default 1D (today's session) is the most relevant view at market open.
  const [period, setPeriod] = useState<MoverPeriod>("1D");

  // PLAN-0048 Wave F-2: sector filter pill state. Default "all" (no filter).
  // WHY local state: like `period`, this is widget-scoped — no need to share
  // it across the dashboard. Other movers widgets (e.g. WatchlistMoversWidget)
  // each maintain their own selection so users can narrow them independently.
  const [selectedSector, setSelectedSector] = useState<string>(ALL_SECTORS_VALUE);

  // WHY fetch gainers and get a combined list: getTopMovers returns one side at
  // a time. For the dashboard we need both — we make two queries (gainers + losers)
  // so each side can be independently cached and refetched.
  // WHY period in queryKey: ensures a cache miss and re-fetch when the user
  // switches between 1D, 1W, and 1M — otherwise stale 1D results would persist.
  const { data: gainersData, isLoading: gainersLoading, isError: gainersError, refetch: refetchGainers } = useQuery({
    queryKey: ["dashboard-top-movers-gainers", period],
    queryFn: () => createGateway(accessToken).getTopMovers("gainers", 10, period),
    enabled: !!accessToken,
    // WHY 60_000: top movers is a real-time feed; 1-min refresh is appropriate
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const { data: losersData, isLoading: losersLoading, isError: losersError, refetch: refetchLosers } = useQuery({
    queryKey: ["dashboard-top-movers-losers", period],
    queryFn: () => createGateway(accessToken).getTopMovers("losers", 10, period),
    enabled: !!accessToken,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const isLoading = gainersLoading || losersLoading;
  // WHY isError from both queries: either leg failing means the two-column
  // layout would render half-empty. We treat either error as a widget-level
  // failure and surface a single Retry that re-fetches both sides.
  const isError = gainersError || losersError;
  // WHY extracted function (not inline): void-wrapping two calls in JSX onClick
  // would require an IIFE which is harder to read. A named function keeps the
  // JSX one-liner and satisfies the no-floating-promises lint rule.
  const refetchAll = () => { void refetchGainers(); void refetchLosers(); };

  // ── Pre-filter raw lists ────────────────────────────────────────────────
  // WHY overfetch (10 then slice to 5): once the sector filter is active,
  // many of the 10 candidates may not match. Starting from 10 gives the
  // filter enough headroom to still show 5 rows post-filter for the most
  // common cases. If the user picks an obscure sector with <5 names in the
  // top-10, we render whatever fits (better than blank).
  // WHY useMemo wrappers: `?? []` would create a fresh array reference on
  // every render, which would invalidate every downstream useMemo /
  // useQueries dep. Memoising on the underlying `data?.movers` reference
  // gives us a stable empty-array fallback.
  const allGainers = useMemo(() => gainersData?.movers ?? [], [gainersData]);
  const allLosers = useMemo(() => losersData?.movers ?? [], [losersData]);

  // ── Sector lookup via per-mover company-overview fetches ───────────────
  // PLAN-0048 F-2: we filter rows client-side by `gics_sector` from the
  // company overview endpoint. The Mover payload itself does not include
  // sector, so we fan out one overview query per ticker.
  // WHY useQueries: hooks can't be called inside `.map()`; useQueries does
  // the fan-out at the top level and returns an aligned result array.
  // WHY staleTime 600_000 (10min): a company's GICS sector almost never
  // changes — caching aggressively avoids a round-trip storm when the user
  // clicks between sector pills.
  // WHY combine gainers + losers in one fan-out: keeps a single source of
  // truth for the "instrument_id → sector" map without two parallel state
  // structures. We slice the result back into gainer/loser arrays below.
  // WHY dedupe by instrument_id: a ticker could in theory appear in both
  // lists (e.g. mid-day swing); duplicate query keys trigger a TanStack
  // "Duplicate Queries" warning and waste a network call.
  const allCandidates = useMemo(() => {
    const seen = new Set<string>();
    const merged: Mover[] = [];
    for (const m of [...allGainers, ...allLosers]) {
      if (seen.has(m.instrument_id)) continue;
      seen.add(m.instrument_id);
      merged.push(m);
    }
    return merged;
  }, [allGainers, allLosers]);

  // FIX F-1 (2026-06-05): collapse N parallel /v1/companies/{id}/overview calls
  // into ONE POST /v1/companies/overviews:batch. Previously this widget fired up
  // to 20 parallel HTTP round-trips via useQueries — now it's a single request.
  // The batch endpoint returns `{ <uuid>: CompanyOverview | null }` so a single
  // failing leg degrades to null instead of tanking the whole fan-out.
  const candidateIds = useMemo(
    () => allCandidates.map((m) => m.instrument_id).filter(Boolean),
    [allCandidates],
  );
  const { data: overviewsMap } = useQuery({
    queryKey: qk.instruments.overviewsBatch(candidateIds),
    queryFn: () =>
      createGateway(accessToken).getCompanyOverviewsBatch(candidateIds),
    enabled: !!accessToken && candidateIds.length > 0,
    // WHY staleTime 10min: a company's GICS sector + last price change very
    // rarely on this widget's timescale. Aggressive caching avoids round-trip
    // storms when the user clicks between sector pills.
    staleTime: 600_000,
  });

  // WHY a stable empty-object fallback: useMemo consumers below depend on
  // `overviewByid` referentially — `?? {}` inline would mint a new object on
  // every render and invalidate every downstream memo.
  const overviewByid = useMemo(() => overviewsMap ?? {}, [overviewsMap]);

  // Build instrument_id → sector map for O(1) lookup during filtering.
  const sectorByInstrumentId = useMemo(() => {
    const map = new Map<string, string | null | undefined>();
    allCandidates.forEach((m) => {
      // WHY `undefined` when the leg failed (null) OR is still loading
      // (missing key): downstream filter treats `undefined` as "show the row"
      // — see applyFilter() below.
      const ov = overviewByid[m.instrument_id];
      map.set(m.instrument_id, ov?.instrument?.gics_sector);
    });
    return map;
  }, [allCandidates, overviewByid]);

  // WHY priceByInstrumentId: the S3 fundamentals screener only returns metrics stored
  // in the fundamentals table (daily_return, pe_ratio, etc.) — price lives in the
  // OHLCV table and is NOT included in screener metrics. Every mover therefore shows
  // $0.00 from the screener alone. We extract quote.price from the same batched
  // overview map (zero extra network cost) so the mover rows show a real last-trade
  // price.
  const priceByInstrumentId = useMemo(() => {
    const map = new Map<string, number>();
    allCandidates.forEach((m) => {
      const price = overviewByid[m.instrument_id]?.quote?.price;
      if (typeof price === "number" && price > 0) map.set(m.instrument_id, price);
    });
    return map;
  }, [allCandidates, overviewByid]);

  // ── Filter helper ───────────────────────────────────────────────────────
  // WHY graceful "still loading" behaviour: if a row's overview hasn't
  // resolved yet (no entry in the map), we DON'T hide the row — that would
  // make the list flicker as overviews stream in. Spec: "If overviews are
  // still loading, show all rows (don't block). When `All`, no filter."
  function applyFilter(rows: Mover[]): Mover[] {
    if (selectedSector === ALL_SECTORS_VALUE) return rows;
    return rows.filter((m) => {
      const sector = sectorByInstrumentId.get(m.instrument_id);
      // `undefined` means "overview not loaded yet" → keep the row visible.
      if (sector === undefined) return true;
      return matchesSectorFilter(sector, selectedSector);
    });
  }

  // Show all rows after sector filter (up to the limit requested from the API).
  const gainers = applyFilter(allGainers);
  const losers = applyFilter(allLosers);

  return (
    // WHY bg-background: see PortfolioNewsWidget for rationale — consistent with
    // all other dashboard widgets. gap-px grid provides hairline panel borders.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern with period selector ─────────────── */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          TOP MOVERS
        </span>
        {/* WHY period buttons in header: follows Bloomberg convention — time period
            controls live in the panel header, not below the data, so traders can
            see the selector without scrolling to the bottom of a long list.
            WHY gap-px (not gap-1): hairline between buttons matches the grid seam
            aesthetic — consistent with all other panel-separator patterns in the app. */}
        <div className="flex gap-px">
          {(["1D", "1W", "1M"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              // WHY px-1.5 text-[9px]: minimal footprint — period buttons live in a
              // 24px header row alongside a label. At 9px they're clearly readable
              // without competing with the section title for vertical space.
              className={cn(
                "px-1.5 text-[9px] font-mono uppercase transition-colors",
                period === p
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              // WHY aria-pressed: these are toggle buttons (one is always active).
              // aria-pressed communicates the selected state to screen readers.
              aria-pressed={period === p}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* ── Sector filter pills (PLAN-0048 Wave F-2) ─────────────────────── */}
      {/* WHY this lives between the header and the GAINERS|LOSERS sub-header:
          it visually scopes the data below it. Putting it inside either
          column would imply it filters only that column.
          WHY -mx-2 px-2: bleed the scroll container to the panel edges so
          horizontally-scrolled pills can extend full width without the
          parent's padding clipping them visually mid-scroll.
          WHY overflow-x-auto + flex (not flex-wrap): a single horizontal
          row keeps vertical real estate dense; users scroll with the
          trackpad/wheel rather than have pills wrap and steal a second row. */}
      <div
        className="-mx-2 flex shrink-0 gap-1 overflow-x-auto border-b border-border/30 px-2 pb-1 pt-1"
        // role="tablist": pills act like a one-of-many selector — tablist is
        // the closest ARIA pattern (radio-group implies form semantics we
        // don't have here).
        role="tablist"
        aria-label="Filter movers by sector"
      >
        {SECTOR_PILLS.map((pill) => {
          const isSelected = selectedSector === pill.value;
          return (
            <button
              key={pill.value}
              role="tab"
              aria-selected={isSelected}
              onClick={() => setSelectedSector(pill.value)}
              className={cn(
                // Base style — small mono-uppercase text matches the rest of
                // the terminal's chrome. tracking-wider keeps the letters
                // legible at 10px.
                // WHY rounded-[2px]: design system mandates 2px radius; bare `rounded` = 4px default
                "shrink-0 rounded-[2px] border border-border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors",
                isSelected
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
            >
              {pill.label}
            </button>
          );
        })}
      </div>

      {/* ── Sub-headers: GAINERS | LOSERS ─────────────────────────────────── */}
      {/* WHY separate sub-header row: makes the two-column split explicit at a
          glance without relying on color alone — supports color-blind traders */}
      <div className="flex shrink-0 border-b border-border/30">
        <div className="flex h-[22px] flex-1 items-center px-2">
          {/* WHY text-positive: column label signals green/up direction */}
          <span className="text-[10px] uppercase tracking-[0.08em] text-positive/70">
            GAINERS
          </span>
        </div>
        {/* WHY border-l: vertical hairline separates the two columns */}
        <div className="flex h-[22px] flex-1 items-center border-l border-border/30 px-2">
          <span className="text-[10px] uppercase tracking-[0.08em] text-negative/70">
            LOSERS
          </span>
        </div>
      </div>

      {/* ── Content area ──────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-auto">

        {/* Loading state */}
        {isLoading && (
          <div className="flex flex-1 gap-0">
            <div className="flex-1 divide-y divide-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex h-[22px] items-center gap-2 px-2">
                  <Skeleton className="h-3 w-[40px]" />
                  <Skeleton className="h-3 w-[40px]" />
                </div>
              ))}
            </div>
            <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex h-[22px] items-center gap-2 px-2">
                  <Skeleton className="h-3 w-[40px]" />
                  <Skeleton className="h-3 w-[40px]" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Error state ────────────────────────────────────────────────── */}
        {/* WHY shown when !isLoading: a loading skeleton takes precedence —
            we only show the error once the failed state is confirmed.
            WHY min-h-[110px]: 5 rows × 22px each = 110px; matches the skeleton
            height so the widget footprint doesn't collapse on error. */}
        {!isLoading && isError && (
          <div className="flex flex-1 min-h-[110px] items-center justify-center gap-2">
            <AlertTriangle className="h-3 w-3 text-destructive" strokeWidth={1.5} />
            <span className="text-xs text-muted-foreground">Failed to load</span>
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={refetchAll}>
              Retry
            </Button>
          </div>
        )}

        {/* Empty state — shown only when not loading and both lists are empty */}
        {!isLoading && !isError && gainers.length === 0 && losers.length === 0 && (
          <div className="flex-1 px-2">
            <InlineEmptyState message="Market mover data loading…" />
          </div>
        )}

        {/* ── Gainers column ─────────────────────────────────────────────── */}
        {!isLoading && !isError && (
          <div className="flex-1 divide-y divide-border/30">
            {gainers.map((mover) => (
              <MoverRow
                key={mover.instrument_id}
                // WHY spread with priceOverride: overview query already fetched quote.price
                // for sector filtering — reuse it so the row shows a real price instead of $0.00.
                mover={{ ...mover, price: priceByInstrumentId.get(mover.instrument_id) ?? mover.price }}
                side="gainer"
              />
            ))}
            {gainers.length === 0 && (
              <div className="px-2">
                <InlineEmptyState message="No gainers" />
              </div>
            )}
          </div>
        )}

        {/* ── Losers column ──────────────────────────────────────────────── */}
        {!isLoading && !isError && (
          <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
            {losers.map((mover) => (
              <MoverRow
                key={mover.instrument_id}
                mover={{ ...mover, price: priceByInstrumentId.get(mover.instrument_id) ?? mover.price }}
                side="loser"
              />
            ))}
            {losers.length === 0 && (
              <div className="px-2">
                <InlineEmptyState message="No losers" />
              </div>
            )}
          </div>
        )}

      </div>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
        <span className="text-[10px] text-muted-foreground-dim">
          prior session data
        </span>
      </div>

    </div>
  );
}

// ── MoverRow sub-component ────────────────────────────────────────────────────

interface MoverRowProps {
  mover: Mover;
  side: "gainer" | "loser";
}

/**
 * MoverRow — single mover entry: ticker + price + change%.
 *
 * WHY show price alongside change%: institutional traders always want to see
 * the absolute price alongside the percentage move. "AAPL +3.2%" without the
 * price is incomplete — a 3.2% move on a $5 stock is very different from $190.
 * The col-span-5 cell is wide enough to fit both in 22px rows (tested at 1280px).
 *
 * WHY clickable: rows navigate to the instrument detail page so traders can
 * dive directly from the mover list into the full chart + fundamentals view.
 * ADR-F-12: prefer entity_id in the URL; fall back to instrument_id (S9 overview
 * accepts either).
 */
function MoverRow({ mover, side }: MoverRowProps) {
  const router = useRouter();

  // PRD-0089 F2 step 11 (§6.6): ticker-first URL. F2 superseded ADR-F-12 —
  // entity_id === instrument_id (M-017) for tradable kinds, so the URL slug is
  // now the analyst-friendly ticker symbol. Fallback chain (ticker → entity_id
  // → instrument_id) preserves resilience: a missing ticker is rare but the
  // middleware will still resolve a UUID via resolve_security_id.
  const navId = mover.ticker || mover.entity_id || mover.instrument_id;

  return (
    // WHY h-[22px]: §0 Terminal Quality Rules mandate 22px data rows
    // WHY cursor-pointer + hover:bg-muted/30: signals clickability to the user;
    // faint hover tint follows the terminal hover-state convention.
    // WHY role="button" + tabIndex: keyboard nav — traders can Tab and Enter to navigate.
    <div
      className="flex h-[22px] cursor-pointer items-center gap-1.5 px-2 transition-colors hover:bg-muted/30"
      onClick={() => router.push(`/instruments/${navId}`)}
      onKeyDown={(e) => { if (e.key === "Enter") router.push(`/instruments/${navId}`); }}
      role="button"
      tabIndex={0}
      aria-label={`Navigate to ${mover.ticker} instrument page`}
    >

      {/* Ticker — fixed 38px for column alignment */}
      <span className="w-[38px] shrink-0 font-mono text-[11px] tabular-nums text-foreground">
        {mover.ticker}
      </span>

      {/* Price — right-aligned in a fixed slot; muted so % change remains primary */}
      {/* WHY text-muted-foreground: price is context, change% is the signal */}
      <span className="w-[48px] shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {formatPrice(mover.price)}
      </span>

      {/* Spacer — pushes the change% to the right edge */}
      <span className="flex-1" />

      {/* Change % — right-aligned, colored by direction */}
      <span
        className={cn(
          "shrink-0 font-mono text-[11px] tabular-nums",
          // WHY explicit side check rather than mover.change_pct sign:
          // the API already segregated gainers/losers by type; trust that.
          side === "gainer" ? "text-positive" : "text-negative",
        )}
      >
        {mover.change_pct >= 0 ? "+" : ""}
        {mover.change_pct.toFixed(2)}%
      </span>

    </div>
  );
}
