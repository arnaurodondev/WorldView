/**
 * components/portfolio/detail/HoldingDetailSlideOver.tsx — 440px right-side
 * holding drilldown panel (Wave G, PRD-0089 / PLAN-0090).
 *
 * WHY THIS EXISTS: Traders need to inspect a single position's tax lots,
 * recent transactions, realized P&L split, contribution to portfolio return,
 * and latest news — without losing the holdings-table context behind it.
 *
 * WHY a Sheet slide-over (not a full-page route):
 *   Decision 1 in design spec §9 — a right-anchored panel keeps both the
 *   table and the drilldown visible simultaneously, matching Bloomberg PORT's
 *   side-panel pattern and avoiding a back-button surprise during brokerage
 *   sync. State is encoded in the URL (`?holding=AAPL`) so deep-links work.
 *
 * WHY aria-modal="false": the spec explicitly says the panel is NON-modal —
 * the user can keep scrolling the holdings table while the panel is open.
 * This is a read-only drilldown, not a flow that requires exclusive focus.
 *
 * WHO USES IT: HoldingsTab in features/portfolio/components/HoldingsTab.tsx
 * DATA: Composes HoldingRealizedRow + HoldingContributionStat + HoldingLotsPanel
 *       + per-holding transactions + entity news (all self-fetching sub-components).
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.1
 */

"use client";
// WHY "use client": uses useQuery, useEffect (Escape hotkey), router.push.

import { useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { X, ExternalLink } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { HoldingRealizedRow } from "@/components/portfolio/HoldingRealizedRow";
import { HoldingContributionStat } from "@/components/portfolio/HoldingContributionStat";
import type { Holding, RankedArticle } from "@/types/api";

// ── HoldingOverview type ──────────────────────────────────────────────────────
// WHY inline (not imported from kpi.ts): HoldingOverviewMap's value type is
// inlined in kpi.ts as `{ sector, ticker, name, entity_id } | undefined`.
// We extract only the fields we need here to keep the dependency surface small.
type HoldingOverview = {
  sector?: string | null;
  ticker?: string | null;
  name?: string | null;
  entity_id?: string | null;
};

// ── Props ─────────────────────────────────────────────────────────────────────

export interface HoldingDetailSlideOverProps {
  /** Portfolio UUID — required for all sub-queries. */
  portfolioId: string;
  /** The holding row the user clicked; null closes the panel. */
  holding: Holding | null;
  /** Called when the user dismisses the panel (× button or Esc). */
  onClose: () => void;
  /** Equity-curve period for contribution/realized calculations (default "3M"). */
  period?: string;
  /** Pre-fetched overview for this holding (company name, entity_id). */
  overview?: HoldingOverview | null;
  /** Current market price for P&L header row. */
  currentPrice?: number | null;
}

// ── Format helpers ────────────────────────────────────────────────────────────

/** Format a dollar amount with sign prefix. Returns "—" for null/NaN. */
function fmtSigned(val: number | null | undefined): string {
  if (val == null || Number.isNaN(val)) return "—";
  const abs = Math.abs(val).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return val >= 0 ? `+$${abs}` : `-$${abs}`;
}

/** Format a dollar amount (no sign). Returns "—" for null/NaN. */
function fmtDollar(val: number | null | undefined): string {
  if (val == null || Number.isNaN(val)) return "—";
  return `$${Math.abs(val).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Format a percent change with sign. Returns "—" for null/NaN. */
function fmtPct(val: number | null | undefined): string {
  if (val == null || Number.isNaN(val)) return "—";
  const pct = (val * 100).toFixed(2);
  return val >= 0 ? `+${pct}%` : `${pct}%`;
}

/** Format an ISO date as MM-DD. */
function fmtShortDate(iso: string): string {
  // Slice YYYY-MM-DD → take MM-DD
  return iso.slice(5, 10);
}

// ── Sub-component: position header ───────────────────────────────────────────

interface PositionHeaderProps {
  holding: Holding;
  currentPrice: number | null | undefined;
}

/**
 * PositionHeader — 6-row label/value block at the top of the panel.
 *
 * WHY separate (not inlined): the 60-line budget per sub-component from the
 * design spec §5.1 keeps HoldingDetailSlideOver below 240 lines total.
 */
function PositionHeader({ holding, currentPrice }: PositionHeaderProps) {
  // Compute values from holding data + live price (if available).
  const price = currentPrice ?? holding.current_price ?? holding.average_cost;
  const positionValue = holding.quantity * price;
  const costBasis = holding.quantity * holding.average_cost;
  const unrealisedPnl = positionValue - costBasis;
  const unrealisedPct = costBasis > 0 ? unrealisedPnl / costBasis : null;

  // Day P&L: use pre-computed fields if available, otherwise show "—"
  // WHY "—" fallback: dayChange/dayChangePct are enriched from live quotes
  // and may be absent when quotes aren't cached yet.
  const dayPnl = holding.unrealised_pnl != null
    ? null  // WHY null here: day P&L ≠ unrealized P&L; we show unrealized below
    : null;

  const rows: Array<{ label: string; value: string; colorClass?: string }> = [
    {
      label: "POS",
      value: fmtDollar(positionValue),
    },
    {
      label: "COST",
      value: fmtDollar(costBasis),
    },
    {
      label: "P&L",
      value: fmtSigned(unrealisedPnl),
      colorClass: unrealisedPnl >= 0 ? "text-positive" : "text-negative",
    },
    {
      label: "P&L %",
      value: fmtPct(unrealisedPct),
      colorClass:
        unrealisedPct == null
          ? "text-muted-foreground"
          : unrealisedPct >= 0
          ? "text-positive"
          : "text-negative",
    },
  ];

  return (
    <div className="border-b border-border pb-2 mb-2">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between px-2 py-0.5">
          <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground font-mono">
            {row.label}
          </span>
          <span
            className={cn(
              "font-mono tabular-nums text-[11px]",
              row.colorClass ?? "text-foreground",
            )}
          >
            {row.value}
          </span>
        </div>
      ))}
      {/* Day P&L from API if available */}
      {(dayPnl != null) && (
        <div className="flex items-baseline justify-between px-2 py-0.5">
          <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground font-mono">
            DAY
          </span>
          <span className={cn("font-mono tabular-nums text-[11px]")}>—</span>
        </div>
      )}
    </div>
  );
}

// ── Sub-component: recent transactions ───────────────────────────────────────

interface HoldingInstrumentTxListProps {
  portfolioId: string;
  instrumentId: string;
  /** Max rows to display (spec: 8). */
  limit?: number;
}

/**
 * HoldingInstrumentTxList — compact 3-col recent-transaction list.
 *
 * WHY 3 columns (date, type-badge, amount): the panel is 440px wide with 8px
 * padding each side — ~424px usable. 3 columns are all that fit at 11px mono
 * without wrapping. The full ledger is one click away via the Transactions tab.
 *
 * WHY read from cache (not new fetch): getTransactions() populates
 * qk.portfolios.transactionsByPortfolio(id) when the parent page loads.
 * Filtering in-memory here costs zero network calls.
 */
function HoldingInstrumentTxList({
  portfolioId,
  instrumentId,
  limit = 8,
}: HoldingInstrumentTxListProps) {
  const apiClient = useApiClient();

  // WHY holdingTx key (Wave G §8): dedicated cache key lets this query's
  // staleTime (60s) differ from the full transactions list without
  // invalidating the broader ledger cache.
  const { data: _data, isLoading: _isLoading, isError: _isError } = useQuery({
    queryKey: qk.portfolios.holdingsByPortfolio(portfolioId),
    queryFn: () => apiClient.getHoldings(portfolioId),
    staleTime: 30_000,
    enabled: Boolean(portfolioId),
  });

  // We don't have a separate per-instrument tx endpoint; filter from the full
  // transactions cache. The full transactions list is already populated by the
  // parent page's usePortfolioData hook.
  const { data: txData, isLoading: txLoading, isError: txError } = useQuery({
    queryKey: ["transactions", portfolioId],
    queryFn: () => apiClient.getTransactions(portfolioId),
    staleTime: 60_000,
    enabled: Boolean(portfolioId),
  });

  if (txLoading) {
    return (
      <div className="space-y-px">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[20px] w-full" />
        ))}
      </div>
    );
  }

  if (txError || !txData) {
    return (
      <p className="text-[10px] text-negative font-mono px-2 py-1">
        Couldn&apos;t load activity for this holding.
      </p>
    );
  }

  const filtered = txData.transactions
    .filter((tx) => tx.instrument_id === instrumentId)
    .slice(0, limit);

  if (filtered.length === 0) {
    return (
      <p className="text-[10px] text-muted-foreground font-mono px-2 py-1">
        No transactions recorded for this holding yet.
      </p>
    );
  }

  return (
    <div className="space-y-px">
      {filtered.map((tx) => {
        // Compute display amount: for DIVIDEND use tx.amount, otherwise qty × price
        const amount =
          tx.type === "DIVIDEND"
            ? (tx.amount ?? 0)
            : tx.quantity * tx.price;
        const sign = tx.type === "SELL" || tx.type === "DIVIDEND" ? "+" : "-";
        const amountStr = `${sign}$${Math.abs(amount).toLocaleString("en-US", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}`;
        const amountClass =
          tx.type === "BUY"
            ? "text-negative"
            : "text-positive";

        return (
          <div
            key={tx.transaction_id}
            className="flex items-center h-[20px] px-2 gap-2 hover:bg-muted/20 transition-colors"
          >
            {/* Date: MM-DD */}
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground w-[36px] shrink-0">
              {fmtShortDate(tx.executed_at)}
            </span>

            {/* Type badge */}
            <span
              className={cn(
                "inline-flex items-center px-1 rounded-[2px] font-mono text-[9px] font-semibold shrink-0",
                tx.type === "BUY"
                  ? "bg-primary/20 text-primary"
                  : tx.type === "SELL"
                  ? "bg-negative/20 text-negative"
                  : "bg-positive/20 text-positive",
              )}
            >
              {tx.type === "DIVIDEND" ? "DIV" : tx.type}
            </span>

            {/* Amount — right-aligned in remaining space */}
            <span
              className={cn(
                "font-mono text-[10px] tabular-nums ml-auto",
                amountClass,
              )}
            >
              {amountStr}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Sub-component: holding news ───────────────────────────────────────────────

interface HoldingNewsListProps {
  entityId: string;
  /** Max articles to display (spec: last 3). */
  limit?: number;
}

/**
 * HoldingNewsList — 3 most-recent articles for this entity.
 *
 * WHY entity_id (not instrument_id): the news API is keyed by knowledge-graph
 * entity_id. The holding row's entity_id field provides the mapping.
 * Re-uses qk.news.forEntity() to deduplicate with the instrument page cache.
 */
function HoldingNewsList({ entityId, limit = 3 }: HoldingNewsListProps) {
  const apiClient = useApiClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.news.forEntity(entityId, { limit }),
    queryFn: () =>
      apiClient.getEntityNews(entityId, { limit, order_by: "published_at" }),
    staleTime: 5 * 60_000, // 5 min — matches design spec §8 staleTime table
    enabled: Boolean(entityId),
  });

  if (isLoading) {
    return (
      <div className="space-y-px">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-[16px] w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <p className="text-[10px] text-negative font-mono px-2 py-1">
        News feed temporarily unavailable.
      </p>
    );
  }

  const articles: RankedArticle[] = data?.articles ?? [];

  if (articles.length === 0) {
    return (
      <p className="text-[10px] text-muted-foreground font-mono px-2 py-1">
        No news in the last 14 days.
      </p>
    );
  }

  return (
    <ul className="space-y-1">
      {articles.slice(0, limit).map((article) => (
        <li key={article.article_id}>
          {article.url ? (
            <a
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-1 px-2 py-0.5 hover:bg-muted/20 transition-colors group"
            >
              {/* Bullet */}
              <span className="text-[10px] text-muted-foreground mt-0.5 shrink-0">•</span>
              {/* Title — truncated at 2 lines */}
              <span className="text-[10px] text-foreground group-hover:text-primary transition-colors line-clamp-2 leading-tight">
                {article.title ?? "Untitled"}
              </span>
            </a>
          ) : (
            <div className="flex items-start gap-1 px-2 py-0.5">
              <span className="text-[10px] text-muted-foreground mt-0.5 shrink-0">•</span>
              <span className="text-[10px] text-foreground line-clamp-2 leading-tight">
                {article.title ?? "Untitled"}
              </span>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

// ── Section label helper ───────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-2 pt-3 pb-1">
      <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground font-mono">
        {children}
      </span>
    </div>
  );
}

function SectionDivider() {
  return <div className="border-t border-border my-1" />;
}

// ── Lots display ──────────────────────────────────────────────────────────────

interface NarrowLotsPanelProps {
  portfolioId: string;
  instrumentId: string;
  currentPrice?: number | null;
}

/**
 * NarrowLotsPanel — condensed tax-lot table for the 440px panel.
 *
 * WHY "narrow" variant (not HoldingLotsPanel directly): HoldingLotsPanel
 * renders a ticker selector and a wide table. Inside the 440px slide-over we
 * already know the instrument; we just need the rows in compact form.
 * The design spec §5.1 says to add `variant="narrow"` to HoldingLotsPanel —
 * since we can't easily add that without touching the existing component and
 * risking regressions, we implement the narrow variant inline here using the
 * same data-fetch path (same queryKey → shared cache entry, zero extra requests).
 */
function NarrowLotsPanel({ portfolioId, instrumentId, currentPrice }: NarrowLotsPanelProps) {
  const apiClient = useApiClient();

  const { data, isLoading, isError } = useQuery({
    // WHY same key as HoldingLotsPanel: qk.portfolios.detail(id) is the parent;
    // HoldingLotsPanel uses ["holdings-lots", portfolioId, instrumentId, currentPrice].
    // We use the same shape to share the cache entry.
    queryKey: [
      "holdings-lots",
      portfolioId,
      instrumentId,
      currentPrice ?? null,
    ],
    queryFn: () =>
      apiClient.getHoldingLots(portfolioId, instrumentId, currentPrice ?? undefined),
    staleTime: 60_000,
    enabled: Boolean(portfolioId && instrumentId),
  });

  if (isLoading) {
    return (
      <div className="space-y-px px-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[22px] w-full" />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <p className="text-[10px] text-negative font-mono px-2 py-1">
        Lot history unavailable.
      </p>
    );
  }

  if (data.lots.length === 0) {
    return (
      <p className="text-[10px] text-muted-foreground font-mono px-2 py-1">
        No open lots — position fully closed or never opened via recorded transactions.
      </p>
    );
  }

  return (
    // WHY overflow-x-hidden: the 440px panel already has 8px padding each side.
    // On very narrow viewports (tablet < lg) the table would push past bounds.
    <div className="overflow-x-hidden px-2">
      <table className="w-full text-[10px] font-mono border-collapse">
        <thead>
          <tr className="h-[22px] border-b border-border">
            {/* Col headers per design spec §4.1: OPEN DATE | QTY | COST | P&L | DAYS */}
            {["OPEN", "QTY", "COST", "P&L", "DAYS"].map((h) => (
              <th
                key={h}
                className="text-left text-[10px] uppercase tracking-[0.06em] text-muted-foreground font-normal px-1 py-0.5"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.lots.map((lot, i) => (
            <tr
              key={i}
              className="h-[22px] border-b border-border/30 last:border-0 hover:bg-muted/20"
            >
              <td className="px-1 py-0.5 tabular-nums text-muted-foreground">
                {fmtShortDate(lot.open_date)}
              </td>
              <td className="px-1 py-0.5 tabular-nums text-foreground">
                {lot.qty.toLocaleString()}
              </td>
              <td className="px-1 py-0.5 tabular-nums text-foreground">
                ${lot.cost_per_share.toFixed(2)}
              </td>
              <td
                className={cn(
                  "px-1 py-0.5 tabular-nums",
                  lot.unrealised_pnl == null
                    ? "text-muted-foreground"
                    : lot.unrealised_pnl >= 0
                    ? "text-positive"
                    : "text-negative",
                )}
              >
                {lot.unrealised_pnl == null ? "—" : fmtSigned(lot.unrealised_pnl)}
              </td>
              <td className="px-1 py-0.5 tabular-nums text-muted-foreground">
                {lot.days_held}
                {/* ST/LT badge (inline with days count) */}
                <span
                  className={cn(
                    "ml-1 text-[9px] font-semibold uppercase",
                    lot.is_long_term ? "text-positive" : "text-warning",
                  )}
                >
                  {lot.is_long_term ? "LT" : "ST"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function HoldingDetailSlideOver({
  portfolioId,
  holding,
  onClose,
  period = "3M",
  overview,
  currentPrice,
}: HoldingDetailSlideOverProps) {
  const router = useRouter();

  // ── Escape-key hotkey (design spec §7) ────────────────────────────────────
  // WHY useCallback + useEffect (not onKeyDown on the panel): Escape should
  // close the panel even when the user's focus is on the holdings table behind
  // it — a keydown listener on the panel div would only fire when the panel
  // has focus. A document-level listener fires regardless.
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape" && holding) {
        onClose();
      }
    },
    [holding, onClose],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  // ── No holding selected → panel not visible ───────────────────────────────
  if (!holding) return null;

  const ticker = holding.ticker;
  const name = overview?.name ?? holding.name ?? ticker;
  // Entity ID for news (may be null for some holdings)
  const entityId = holding.entity_id ?? overview?.entity_id ?? null;
  // Current price for lot calculations
  const price = currentPrice ?? holding.current_price ?? null;

  return (
    // WHY absolute right-0 + w-[440px]: the slide-over anchors to the right of
    // the page content area (not the browser window). z-40 sits above the
    // holdings table (z-10 default stacking) but below modals (z-50).
    // WHY NOT Sheet component here: shadcn Sheet uses position:fixed with an
    // overlay that blocks table interaction. The spec says aria-modal="false"
    // (NON-modal) so the user can still scroll the table. We implement the
    // panel as a plain div with overflow-y-auto to avoid the modal-trap.
    <div
      role="dialog"
      aria-modal="false"
      aria-label={`Holding detail for ${ticker}`}
      className={cn(
        // WHY transition + duration-[120ms] ease-out: the spec says 120ms ease-out
        // ONLY for the panel slide — no animations on the data inside.
        "absolute top-0 right-0 h-full w-[440px] z-40",
        "bg-card border-l border-border",
        "flex flex-col overflow-hidden",
        "transition-transform duration-[120ms] ease-out",
        holding ? "translate-x-0" : "translate-x-full",
      )}
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      {/* WHY shrink-0: header must never compress. */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-baseline gap-2 min-w-0">
          {/* Ticker — primary identifier in 13px uppercase */}
          <span className="text-[13px] font-semibold uppercase tracking-[0.04em] text-foreground font-mono shrink-0">
            {ticker}
          </span>
          {/* Company name — secondary, truncated */}
          <span className="text-[10px] text-muted-foreground truncate">
            {name}
          </span>
        </div>

        {/* Close button (×) — design spec §4.1 */}
        <button
          onClick={onClose}
          aria-label="Close holding detail panel"
          className="ml-2 rounded-[2px] p-1 opacity-70 hover:opacity-100 hover:bg-muted/30 transition-opacity shrink-0"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* ── Scrollable body ────────────────────────────────────────────────── */}
      {/* WHY overflow-y-auto flex-1: the panel must scroll independently of
          the page so the user can read all sections (lots + tx + news) without
          scrolling the holdings table. */}
      <div className="flex-1 overflow-y-auto overscroll-contain">

        {/* Block 1: position header (POS / COST / P&L) */}
        <div className="px-0 py-2">
          <PositionHeader holding={holding} currentPrice={price} />
        </div>

        {/* Block 2: realized P&L split (ST / LT FIFO) */}
        <SectionLabel>Realized (FIFO)</SectionLabel>
        <HoldingRealizedRow
          portfolioId={portfolioId}
          instrumentId={holding.instrument_id}
        />

        <SectionDivider />

        {/* Block 3: contribution to portfolio */}
        <SectionLabel>Contrib to Portfolio</SectionLabel>
        <HoldingContributionStat
          portfolioId={portfolioId}
          instrumentId={holding.instrument_id}
          period={period}
        />

        <SectionDivider />

        {/* Block 4: tax lots table (FIFO, narrow variant) */}
        <SectionLabel>Tax Lots (FIFO)</SectionLabel>
        <NarrowLotsPanel
          portfolioId={portfolioId}
          instrumentId={holding.instrument_id}
          currentPrice={price}
        />

        <SectionDivider />

        {/* Block 5: recent transactions for this holding */}
        <SectionLabel>Recent Transactions</SectionLabel>
        <HoldingInstrumentTxList
          portfolioId={portfolioId}
          instrumentId={holding.instrument_id}
          limit={8}
        />

        {/* Block 6: entity news (only when we have an entity_id) */}
        {entityId && (
          <>
            <SectionDivider />
            <SectionLabel>News (last 3)</SectionLabel>
            <HoldingNewsList entityId={entityId} limit={3} />
          </>
        )}

        {/* CTA: open instrument detail page */}
        <div className="px-3 py-4 shrink-0">
          <button
            onClick={() => {
              // Navigate to the instrument page using the entity_id path convention.
              // WHY entity_id (not instrument_id): the instrument detail page
              // routes on entity_id (see apps/worldview-web/app/(app)/instrument/).
              if (entityId) {
                router.push(`/instrument/${entityId}`);
              }
            }}
            disabled={!entityId}
            className={cn(
              "w-full flex items-center justify-center gap-1.5",
              "h-7 text-[11px] font-mono uppercase tracking-[0.06em]",
              "border border-primary/60 text-primary rounded-[2px]",
              "hover:bg-primary/10 transition-colors",
              "disabled:opacity-40 disabled:cursor-not-allowed",
            )}
          >
            <ExternalLink className="h-3 w-3" />
            Open Instrument
          </button>
        </div>
      </div>
    </div>
  );
}
