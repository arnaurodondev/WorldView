/**
 * components/watchlist/WatchlistInsightsPanel.tsx — Compact watchlist-level insights card
 *
 * WHY THIS EXISTS: Portfolio overview pages need a dense, at-a-glance snapshot
 * of what is happening in a watchlist — top mover, biggest news headline, and
 * portfolio-weighted sentiment — without navigating to the full watchlist tab.
 * Three 22px rows give the trader actionable signals in under 70px of vertical
 * space.
 *
 * WHO USES IT: Portfolio overview page (B-2 section of PLAN-0091). Rendered
 * inside a card-style container per watchlist so the trader can scan all their
 * watchlists in one pass.
 *
 * DATA SOURCE: GET /v1/watchlists/{id}/insights via gateway.getWatchlistInsights().
 * The gateway composes this payload server-side from quotes + news + alerts,
 * so no parallel client-side fan-out is needed. Cache slot is per-watchlist.
 *
 * DESIGN REFERENCE: PLAN-0091 Wave B-2 — compact insights panel spec.
 *   - bg-[#131722] card with 1px muted border (dark terminal aesthetic)
 *   - 9px mono uppercase header label
 *   - Three 22px data rows (label left, value right)
 *   - Positive values: #26A69A (Bloomberg green), negative: #EF5350 (red)
 *   - Loading: 66px pulse skeleton (matches 3 × 22px rows)
 *   - Error: "Insights unavailable" in muted 10px mono
 *   - Empty (members_count === 0): "No insights yet"
 */

"use client";
// WHY "use client": uses useQuery (TanStack React Query) which requires
// browser-side React state. Server components cannot hold reactive subscriptions.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";

// ── Props ──────────────────────────────────────────────────────────────────────

export interface WatchlistInsightsPanelProps {
  /** UUID of the watchlist to fetch insights for. */
  watchlistId: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * formatChangePct — format a change_pct value (e.g. 1.5) as "+1.50%".
 *
 * WHY prefix: financial convention is to explicitly show + on gains so the
 * trader doesn't have to infer sign from the color alone (accessibility).
 */
function formatChangePct(v: number): string {
  const prefix = v >= 0 ? "+" : "";
  return `${prefix}${v.toFixed(2)}%`;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function WatchlistInsightsPanel({ watchlistId }: WatchlistInsightsPanelProps) {
  // WHY useAuth here: every gateway call needs a valid access token. We pull it
  // from the AuthContext (which gets it from Zitadel OIDC/PKCE) and pass it to
  // createGateway() so the API request carries the Authorization header.
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    // WHY query disabled without token OR watchlistId: if accessToken is undefined
    // (user not yet authenticated) we get 401; if watchlistId is empty string (parent
    // hasn't resolved the watchlist UUID yet) we get a malformed URL "/watchlists//insights".
    // Both guards are required — mirrors the pattern in ConcentrationWidget and SectorAttributionWidget.
    enabled: Boolean(accessToken) && !!watchlistId,
    queryKey: qk.watchlists.insights(watchlistId),
    queryFn: () => createGateway(accessToken!).getWatchlistInsights(watchlistId),
    // WHY 60_000ms stale + refetch: watchlist insights are a "dashboard pulse"
    // — once-a-minute is frequent enough for scan reads, infrequent enough to
    // avoid hammering the server during idle periods. Same cadence as the
    // HoldingLotsPanel and CashRow components for UI consistency.
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // ── Panel shell ────────────────────────────────────────────────────────────

  return (
    // WHY bg-[#131722]: matches the global dark terminal palette defined in the
    // design system. This is the "surface level 1" background — one step darker
    // than the card background so the panel recedes slightly and data pops.
    <div className="bg-[#131722] border border-muted/20 rounded p-2">
      {/* Header — 9px mono uppercase, muted colour. WHY uppercase mono:
          terminal finance convention — all section labels are uppercased so
          the trader's eye instantly distinguishes label from data. */}
      <div className="text-[9px] font-mono uppercase text-muted-foreground mb-1">
        WATCHLIST INSIGHTS
      </div>

      {/* ── Loading state ────────────────────────────────────────────────────
          WHY h-[66px]: 3 data rows × 22px = 66px. The skeleton matches the
          exact height of the content it replaces so there is no layout shift
          (CLS) when the data arrives. */}
      {isLoading && (
        <div className="h-[66px] bg-muted/20 animate-pulse rounded" />
      )}

      {/* ── Error state ──────────────────────────────────────────────────────
          WHY soft error (not a toast): insights are supplementary — a failure
          here should not interrupt the trader's primary workflow. A quiet
          inline message is enough. */}
      {isError && !isLoading && (
        <div className="text-[10px] font-mono text-muted-foreground">
          Insights unavailable
        </div>
      )}

      {/* ── Empty state ───────────────────────────────────────────────────────
          WHY members_count check (not movers.length): movers could be empty
          even with members if the market is closed; members_count === 0 is the
          definitive "watchlist has no instruments" signal. */}
      {!isLoading && !isError && data && data.members_count === 0 && (
        <div className="text-[10px] font-mono text-muted-foreground">
          No insights yet
        </div>
      )}

      {/* ── Data rows ──────────────────────────────────────────────────────
          Three rows rendered when data is available and watchlist has members.
          Each row is h-[22px] flex with label on the left, value on the right.
          This matches the 22px row-height token used across the terminal UI
          (SemanticHoldingsTable, CashRow, etc.). */}
      {!isLoading && !isError && data && data.members_count > 0 && (
        <div className="space-y-0">
          {/* Row 1 — Top mover: the member with the largest absolute change_pct.
              WHY largest absolute (not max): a -5% mover is equally as
              interesting as a +5% mover; directional extremes are newsworthy
              regardless of sign. */}
          <TopMoverRow movers={data.movers} />

          {/* Row 2 — Top news headline from biggest_news.
              WHY truncated title (not full): space constraint in a 22px row;
              hovering the element exposes the full title via the `title` attr. */}
          <BiggestNewsRow biggestNews={data.biggest_news} />

          {/* Row 3 — Watchlist-level weighted return (equal-weight average).
              WHY "WGTD RET": distinguishes this from any single-stock return
              so the trader doesn't mistake it for a position-level P&L figure. */}
          <WeightedReturnRow weightedReturn1d={data.weighted_return_1d} />
        </div>
      )}
    </div>
  );
}

// ── Sub-row components ─────────────────────────────────────────────────────────
// WHY extracted (not inline JSX): each row has conditional logic (null checks,
// sign-based coloring). Extracting them keeps the main component readable and
// makes the sub-rows independently testable.

import type { WatchlistMoverEnriched, WatchlistBiggestNews } from "@/types/api";

/** Shared row shell — 22px flex row with label on left, value on right. */
function InsightRow({
  label,
  value,
  valueClass,
  title,
}: {
  label: string;
  value: string;
  /** Optional extra class for the value span (e.g. text-[#26A69A]). */
  valueClass?: string;
  /** Full tooltip text for truncated values. */
  title?: string;
}) {
  return (
    // WHY h-[22px]: the 22px row-height token is a hard constraint from the
    // design spec — all terminal data rows must share this height for vertical
    // rhythm. items-center aligns text to the optical centre of the row.
    <div className="flex h-[22px] items-center justify-between">
      <span className="text-[9px] font-mono text-muted-foreground truncate">
        {label}
      </span>
      <span
        className={cn(
          "text-[10px] font-mono tabular-nums truncate ml-2",
          valueClass,
        )}
        title={title}
      >
        {value}
      </span>
    </div>
  );
}

/**
 * TopMoverRow — displays the watchlist member with the largest absolute daily change.
 *
 * WHY absolute value sort: a -5% drop is just as notable as a +5% gain.
 * Finding the extreme mover (regardless of direction) highlights the
 * most price-active instrument in the watchlist.
 */
function TopMoverRow({ movers }: { movers: WatchlistMoverEnriched[] }) {
  // Filter to movers that actually have a change_pct and find the extremum.
  const withChange = movers.filter((m) => m.change_pct !== null);
  if (withChange.length === 0) {
    return <InsightRow label="TOP MOVER" value="—" />;
  }

  // Sort by absolute change_pct descending; take the first.
  const top = [...withChange].sort(
    (a, b) => Math.abs(b.change_pct!) - Math.abs(a.change_pct!),
  )[0]!;

  const changePct = top.change_pct!;
  // WHY #26A69A / #EF5350: Bloomberg-terminal green/red palette from the
  // design system. These are used everywhere positive/negative values appear.
  const valueClass = changePct >= 0 ? "text-[#26A69A]" : "text-[#EF5350]";
  const value = `${top.ticker} ${formatChangePct(changePct)}`;

  return (
    <InsightRow
      label="TOP MOVER"
      value={value}
      valueClass={valueClass}
      title={`${top.name} — ${formatChangePct(changePct)}`}
    />
  );
}

/**
 * BiggestNewsRow — shows the highest-impact news article title for the watchlist.
 *
 * WHY "impact score" ordering (server-side): the gateway already picks the
 * biggest_news article by market_impact_score, so the client simply displays
 * what the server determined to be the most important article.
 */
function BiggestNewsRow({ biggestNews }: { biggestNews: WatchlistBiggestNews | null }) {
  if (!biggestNews || !biggestNews.title) {
    return <InsightRow label="TOP NEWS" value="—" />;
  }

  // Truncate to a reasonable display length; full title exposed via `title` attr.
  const displayTitle =
    biggestNews.title.length > 28
      ? `${biggestNews.title.slice(0, 28)}…`
      : biggestNews.title;

  return (
    <InsightRow
      label="TOP NEWS"
      value={displayTitle}
      title={biggestNews.title}
    />
  );
}

/**
 * WeightedReturnRow — equal-weighted 1-day return across all watchlist members.
 *
 * WHY "equal-weighted" (not market-cap): the watchlist is not a portfolio —
 * there are no position sizes. Equal-weighting gives each instrument the same
 * voice, which is the correct interpretation for a conviction-based watchlist.
 */
function WeightedReturnRow({ weightedReturn1d }: { weightedReturn1d: number | null }) {
  if (weightedReturn1d === null) {
    return <InsightRow label="WGTD RET 1D" value="—" />;
  }

  const valueClass =
    weightedReturn1d >= 0 ? "text-[#26A69A]" : "text-[#EF5350]";

  return (
    <InsightRow
      label="WGTD RET 1D"
      value={formatChangePct(weightedReturn1d)}
      valueClass={valueClass}
    />
  );
}
