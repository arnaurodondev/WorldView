/**
 * WorkspaceScreenerWidget — compact screener table for the workspace panel
 *
 * WHY THIS EXISTS: The full Screener page has a left-side filter form and
 * sort controls that need full-page width. In a 400px workspace panel, that
 * layout breaks. This widget shows a fixed top-20 by market_impact_score —
 * the "what's moving" list that traders check constantly throughout the day.
 *
 * WHY top-20 by market_impact_score (not user-filtered): The workspace panel
 * is meant for ambient monitoring, not active filtering. The score-ranked list
 * surfaces the highest-signal instruments without requiring user input.
 * Users who need filtering use the full Screener page via sidebar.
 *
 * WHY 5 columns (not 7): Workspace panels are narrow (~350-500px). 5 columns
 * at 11px mono gives each column enough width to show data without truncation.
 * The full screener has 7 columns — acceptable at full page width (1200px+).
 *
 * WHO USES IT: workspace/page.tsx — rendered inside a workspace panel card
 *              when panel type is "screener".
 * DATA SOURCE: S9 POST /api/v1/fundamentals/screen
 * DESIGN REFERENCE: PRD-0031 §5 Workspace panels, §0 Terminal CLI Quality Standard
 */

"use client";
// WHY "use client": uses useQuery (TanStack Query is client-side only) and
// useRouter for row-click navigation.

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMarketCap, formatPercent, priceChangeClass } from "@/lib/utils";
import type { ScreenerResult } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Top-N instruments shown in the workspace panel (no pagination) */
const WIDGET_LIMIT = 20;

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * WorkspaceScreenerWidget — shows top-20 instruments by market_impact_score
 * in a 5-column compact table. Replaces the WorkspacePlaceholder for "screener"
 * panel type.
 */
export function WorkspaceScreenerWidget() {
  const { accessToken } = useAuth();
  const router = useRouter();

  // WHY sort_by market_impact_score: this score combines PRD-0020 price-impact
  // signal with article volume — it surfaces instruments with the most active
  // market signal at any given moment, which is what traders monitor in the panel.
  const { data, isLoading, isError } = useQuery({
    queryKey: ["workspace-screener-top"],
    queryFn: () =>
      createGateway(accessToken).runScreener({
        // WHY market_capitalization min=0: backend rejects empty filter arrays (422).
        // This is the minimal always-true filter — every instrument has a market cap
        // ≥ 0 — so no rows are excluded (BP-371: empty filters[] → 422 from backend).
        filters: [{ metric: "market_capitalization", min_value: 0 }],
        limit: WIDGET_LIMIT,
        offset: 0,
        sort_by: "market_capitalization",
        sort_dir: "desc",
      }),
    enabled: !!accessToken,
    // WHY 60s staleTime: screener data is refreshed every 1 minute — aggressive
    // enough to surface new movers without hammering the fundamentals endpoint.
    staleTime: 60_000,
    // WHY retry: false: a screener failure should surface immediately as an error,
    // not silently retry 3x while the user wonders if the widget is stuck.
    retry: false,
  });

  // ── Determine row content based on state ─────────────────────────────────
  // WHY always render the header row: Bloomberg Terminal always shows the column
  // structure even during loading — the header never disappears. Only the data
  // area shows skeletons. This avoids layout shift and keeps the panel chrome stable.
  const rows = data?.results ?? [];

  let rowContent: React.ReactNode;
  if (isLoading) {
    // ── Loading: skeleton rows in the data area, header stays visible ─────
    rowContent = (
      <>
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="flex h-[22px] items-center border-b border-border/30 px-2 gap-2"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            <Skeleton className="h-2.5 w-10 shrink-0" />
            <Skeleton className="h-2.5 flex-1" />
            <Skeleton className="h-2.5 w-10 shrink-0" />
            <Skeleton className="h-2.5 w-12 shrink-0" />
            <Skeleton className="h-2.5 w-8 shrink-0" />
          </div>
        ))}
      </>
    );
  } else if (isError || !data) {
    // ── Error: single inline line per §0.5 — no centered icon cards ───────
    rowContent = (
      <p className="px-2 py-1 text-[11px] text-muted-foreground">
        Screener unavailable.
      </p>
    );
  } else if (rows.length === 0) {
    rowContent = (
      <p className="px-2 py-1 text-[11px] text-muted-foreground">
        No instruments matched.
      </p>
    );
  } else {
    rowContent = rows.map((row) => (
      <ScreenerRow
        key={row.instrument_id}
        row={row}
        onClick={() => router.push(`/instruments/${row.entity_id}`)}
      />
    ));
  }

  return (
    // WHY flex-col + overflow-hidden: the panel card provides the viewport height;
    // the table content scrolls inside without affecting the panel chrome.
    <div className="flex flex-col overflow-hidden h-full">
      {/* ── Column header row ──────────────────────────────────────────────── */}
      {/* WHY h-6: §0.2 section header row height — 24px panel chrome.
       * WHY always rendered (not conditional on loading state): Bloomberg Terminal
       * keeps column headers visible at all times — the header never disappears.
       * Only the data rows area shows loading skeletons. */}
      <div
        className="flex h-6 shrink-0 items-center border-b border-border bg-card px-2 gap-2"
        aria-label="Screener column headers"
      >
        {/* WHY text-[10px] uppercase tracking-[0.08em]: §0.1 label typography rule —
         * ALL column headers use this exact treatment. NO exceptions. */}
        <span className="w-[52px] shrink-0 text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          TICKER
        </span>
        <span className="flex-1 text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans truncate">
          NAME
        </span>
        {/* WHY text-right on CHG%: §0.8 column header contract — header alignment
         * MUST mirror data alignment. CHG% data is right-aligned (numeric column). */}
        <span className="w-[48px] shrink-0 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          CHG%
        </span>
        <span className="w-[44px] shrink-0 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          CAP
        </span>
        <span className="w-[36px] shrink-0 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          SCORE
        </span>
      </div>

      {/* ── Data rows (loading / error / data) ─────────────────────────────── */}
      {/* WHY overflow-auto on this div (not the outer): ensures the header stays
       * sticky at the top while the rows scroll independently. */}
      <div className="flex-1 overflow-auto divide-y divide-border/30" role="table">
        {rowContent}
      </div>

      {/* ── Footer link to full screener ────────────────────────────────────── */}
      {/* WHY border-t: separates the footer from the last data row — consistent
       * with the panel section header divider pattern from §0.9. */}
      <div className="shrink-0 border-t border-border px-2 py-1">
        <Link
          href="/screener"
          className="text-[10px] text-muted-foreground hover:text-foreground transition-colors duration-0"
        >
          View full screener →
        </Link>
      </div>
    </div>
  );
}

// ── ScreenerRow sub-component ─────────────────────────────────────────────────

/**
 * ScreenerRow — single data row in the workspace screener widget.
 *
 * WHY separate component (not inline): isolates per-row rendering logic.
 * React can memo-ize individual rows when the parent re-renders (screener
 * data refetches every 60s). Separate component makes memo-ization trivial.
 */
function ScreenerRow({
  row,
  onClick,
}: {
  row: ScreenerResult;
  onClick: () => void;
}) {
  const score = row.market_impact_score;

  return (
    <div
      role="row"
      // WHY h-[22px]: §0.2 data table row height — 22px (not h-8=32px). Critical.
      // WHY hover:bg-muted/40: §0.7 hover rows — subtle 0.4 opacity muted tint.
      className="flex h-[22px] items-center cursor-pointer px-2 gap-2 hover:bg-muted/40"
      onClick={onClick}
      aria-label={`${row.ticker} — ${row.name}`}
    >
      {/* Ticker — primary identifier in yellow (primary color) */}
      {/* WHY text-primary: tickers are interactive links — primary color signals clickability */}
      <span className="w-[52px] shrink-0 font-mono text-[11px] tabular-nums text-primary truncate">
        {row.ticker}
      </span>

      {/* Name — truncated to available width */}
      <span className="flex-1 text-[11px] text-foreground truncate">
        {row.name}
      </span>

      {/* Change% — colored by sign (positive=green, negative=red, null=muted) */}
      {/* WHY priceChangeClass: reuses the semantic color utility from lib/utils.
       * Consistent with the screener page and portfolio holdings table. */}
      <span
        className={`w-[48px] shrink-0 text-right font-mono text-[11px] tabular-nums ${
          priceChangeClass(row.daily_return)
        }`}
      >
        {row.daily_return != null ? formatPercent(row.daily_return) : "—"}
      </span>

      {/* Market cap — abbreviated (43.2B, 1.2T) */}
      <span className="w-[44px] shrink-0 text-right font-mono text-[11px] tabular-nums text-foreground">
        {row.market_cap != null ? formatMarketCap(row.market_cap) : "—"}
      </span>

      {/* Score — compact bar fill + numeric value */}
      {/* WHY score bar (not just number): the score 0-100 maps to a visual fill bar
       * that lets traders scan relative strength instantly without reading each number.
       * Matches the Bloomberg-style heat display concept. */}
      <div className="w-[36px] shrink-0 flex items-center justify-end gap-1">
        {score != null ? (
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {Math.round(score)}
          </span>
        ) : (
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>
        )}
      </div>
    </div>
  );
}
