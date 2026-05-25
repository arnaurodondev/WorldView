/**
 * components/workspace/WorkspacePortfolioPanel.tsx — Compact portfolio holdings for workspace
 *
 * WHY THIS EXISTS: Traders who monitor a portfolio alongside charts and news need
 * their holdings P&L visible at a glance without navigating to a separate page.
 * This panel shows the first portfolio's holdings as 22px compact rows — the right
 * density for a workspace panel that shares the screen with other data surfaces.
 *
 * WHY FIRST PORTFOLIO ONLY: Workspace MVP shows one portfolio per panel. A future
 * wave adds a portfolio picker per panel so users with multiple portfolios can choose.
 *
 * WHO USES IT: WorkspacePanelContainer when panel.type === "portfolio"
 * DATA SOURCE: GET /v1/portfolios, GET /v1/portfolios/{id}/holdings (S9 gateway)
 * DESIGN REFERENCE: PRD-0031 §5.4 Panel widgets, §0.2 22px row height
 */

"use client";
// WHY "use client": uses TanStack Query (browser-only state management)

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatMarketCap } from "@/lib/utils";
// QA A-F-001/F-002 (2026-05-21): central key factory + shared selection
// helper so this widget joins the same cache namespace as PortfolioSwitcher
// and respects the chip's active-portfolio selection.
import { qk } from "@/lib/query/keys";
import { useResolvedPortfolioId } from "@/hooks/useResolvedPortfolioId";

export function WorkspacePortfolioPanel() {
  const { accessToken } = useAuth();

  // QA A-F-001 (2026-05-21): central qk.portfolios.list() so this widget
  // shares the cache with the PortfolioSwitcher chip and usePortfolioMetrics
  // (was firing a duplicate /v1/portfolios request).
  const { data: portfolios, isLoading: portfoliosLoading } = useQuery({
    queryKey: qk.portfolios.list(),
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 5 * 60_000,
  });

  // QA A-F-002 (2026-05-21): respect the chip selection (was picking
  // portfolios[0] unconditionally).
  const firstPortfolioId = useResolvedPortfolioId(portfolios);

  // BP-497 / HR-060 (2026-05-21): use qk.portfolios.holdingsByPortfolio
  // — the existing "flat legacy-shape" key documented in lib/query/keys.ts
  // that usePortfolioMetrics already consumes. Same cache entry across
  // both consumers; no duplicate /v1/portfolios/{id}/holdings fetch.
  const { data: holdingsResp, isLoading: holdingsLoading } = useQuery({
    queryKey: firstPortfolioId
      ? qk.portfolios.holdingsByPortfolio(firstPortfolioId)
      : ["holdings", "no-portfolio"],
    queryFn: () => createGateway(accessToken).getHoldings(firstPortfolioId!),
    enabled: !!accessToken && !!firstPortfolioId,
    staleTime: 5 * 60_000,
  });

  const isLoading = portfoliosLoading || holdingsLoading;

  if (isLoading) {
    return (
      <div className="space-y-px">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center justify-between gap-2 px-2 h-[22px]">
            <Skeleton className="h-2.5 w-12" style={{ animationDelay: `${i * 40}ms` }} />
            <Skeleton className="h-2.5 w-16" style={{ animationDelay: `${i * 40 + 20}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  if (!portfolios?.length) {
    return (
      <p className="px-2 py-1 text-[11px] text-muted-foreground">
        No portfolio.{" "}
        <Link href="/portfolio" className="text-primary hover:text-primary/80">
          Set up →
        </Link>
      </p>
    );
  }

  const holdings = holdingsResp?.holdings ?? [];

  if (holdings.length === 0) {
    return (
      <p className="px-2 py-1 text-[11px] text-muted-foreground">
        No holdings in portfolio.
      </p>
    );
  }

  return (
    <div className="divide-y divide-border/30">
      {/* Section header (§0.9 pattern) */}
      <div className="flex h-6 items-center border-b border-border px-2">
        {/* WHY font-mono: ADR-F-15 — section labels use IBM Plex Mono */}
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          {portfolios[0].name}
        </span>
      </div>

      {/* Column header row */}
      <div className="flex items-center gap-2 px-2 h-[22px] border-b border-border">
        <span className="w-14 shrink-0 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Ticker</span>
        <span className="flex-1 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Qty</span>
        <span className="w-16 shrink-0 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Value</span>
        <span className="w-14 shrink-0 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground">P&L</span>
      </div>

      {/* Holdings rows — 22px each */}
      {holdings.slice(0, 12).map((h) => {
        const unrealizedPnl = h.unrealised_pnl ?? 0;
        const pnlColor =
          unrealizedPnl > 0
            ? "text-positive"
            : unrealizedPnl < 0
              ? "text-negative"
              : "text-muted-foreground";

        // PRD-0089 F2 §6.6: post-F2 URL slug is the ticker only. A bare UUID
        // slug would 404 (the middleware case-canonicalises + alias-redirects
        // but does NOT resolve UUIDs). Holdings on a real portfolio always
        // carry a ticker; if for some reason ticker is empty, render a
        // non-link row so we never serve a guaranteed-404 URL.
        const rowClass = "flex items-center gap-2 px-2 h-[22px] hover:bg-muted/40 text-foreground";
        const rowContent = (
          <>
            {/* Ticker — monospace, left-aligned */}
            <span className="w-14 shrink-0 font-mono text-[11px] tabular-nums font-medium text-foreground">
              {h.ticker}
            </span>
            {/* Quantity */}
            <span className="flex-1 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
              {h.quantity}
            </span>
            {/* Market value */}
            <span className="w-16 shrink-0 text-right font-mono text-[11px] tabular-nums text-foreground">
              {h.current_price != null
                ? formatMarketCap(h.current_price * h.quantity)
                : "—"}
            </span>
            {/* P&L */}
            <span className={`w-14 shrink-0 text-right font-mono text-[11px] tabular-nums ${pnlColor}`}>
              {h.unrealised_pnl != null
                ? `${unrealizedPnl >= 0 ? "+" : ""}${unrealizedPnl.toFixed(0)}`
                : "—"}
            </span>
          </>
        );
        if (!h.ticker) {
          return (
            <div key={h.holding_id} className={rowClass}>
              {rowContent}
            </div>
          );
        }
        return (
          // WHY Link (not div): clicking a holding row should navigate to the instrument
          // detail page. A real <a> element gives keyboard navigation, screen-reader
          // semantics, and middle-click / open-in-new-tab for free.
          // WHY h-[22px]: §0.2 row height mandate. py-0: row height controls vertical
          // spacing entirely. px-2: 8px horizontal gutter per §0.2 cell padding spec.
          <Link
            key={h.holding_id}
            href={`/instruments/${h.ticker}`}
            className={rowClass}
          >
            {rowContent}
          </Link>
        );
      })}

      {/* Footer — link to full portfolio page */}
      <div className="flex h-[22px] items-center px-2 border-t border-border/30">
        <Link
          href="/portfolio"
          className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground"
        >
          Full portfolio →
        </Link>
      </div>
    </div>
  );
}
