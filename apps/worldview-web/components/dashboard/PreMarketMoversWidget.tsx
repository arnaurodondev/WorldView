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
// WHY "use client": uses useQuery, useAuth, useState for period selector, and useRouter for nav.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";
import type { Mover } from "@/types/api";

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

  // WHY fetch gainers and get a combined list: getTopMovers returns one side at
  // a time. For the dashboard we need both — we make two queries (gainers + losers)
  // so each side can be independently cached and refetched.
  // WHY period in queryKey: ensures a cache miss and re-fetch when the user
  // switches between 1D, 1W, and 1M — otherwise stale 1D results would persist.
  const { data: gainersData, isLoading: gainersLoading } = useQuery({
    queryKey: ["dashboard-top-movers-gainers", period],
    queryFn: () => createGateway(accessToken).getTopMovers("gainers", 10, period),
    enabled: !!accessToken,
    // WHY 60_000: top movers is a real-time feed; 1-min refresh is appropriate
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const { data: losersData, isLoading: losersLoading } = useQuery({
    queryKey: ["dashboard-top-movers-losers", period],
    queryFn: () => createGateway(accessToken).getTopMovers("losers", 10, period),
    enabled: !!accessToken,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const isLoading = gainersLoading || losersLoading;

  // Take top 5 from each side
  const gainers = (gainersData?.movers ?? []).slice(0, 5);
  const losers = (losersData?.movers ?? []).slice(0, 5);

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

        {/* Empty state — shown only when not loading and both lists are empty */}
        {!isLoading && gainers.length === 0 && losers.length === 0 && (
          <div className="flex-1 px-2">
            <InlineEmptyState message="Market mover data loading…" />
          </div>
        )}

        {/* ── Gainers column ─────────────────────────────────────────────── */}
        {!isLoading && (
          <div className="flex-1 divide-y divide-border/30">
            {gainers.map((mover) => (
              <MoverRow key={mover.instrument_id} mover={mover} side="gainer" />
            ))}
            {gainers.length === 0 && (
              <div className="px-2">
                <InlineEmptyState message="No gainers" />
              </div>
            )}
          </div>
        )}

        {/* ── Losers column ──────────────────────────────────────────────── */}
        {!isLoading && (
          <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
            {losers.map((mover) => (
              <MoverRow key={mover.instrument_id} mover={mover} side="loser" />
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
        <span className="text-[10px] text-muted-foreground/60">
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

  // WHY prefer entity_id over instrument_id: ADR-F-12 — entity_id is the stable
  // cross-system identifier used in all instrument detail URLs. instrument_id is
  // accepted as fallback by S9's overview endpoint until entity linking is complete.
  const navId = mover.entity_id ?? mover.instrument_id;

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
        {mover.price != null ? `$${mover.price.toFixed(2)}` : "—"}
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
