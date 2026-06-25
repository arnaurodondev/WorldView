/**
 * RecentActivityStrip — compact 20px-row strip showing last 5 transactions.
 *
 * WHY THIS EXISTS: The design spec (PRD-0089 §4.1) places a "RECENT ACTIVITY"
 * column in the bottom strip cluster, showing the last 5 transactions in a
 * compact one-line format. The existing RecentActivityFeed is a full-height
 * scrollable panel (max-h-[340px], 28px rows) — it's too tall for the 96px
 * bottom strip slot. This component renders the same data at 20px row height
 * with 10px mono font, targeting the specific compact slot in the overview.
 *
 * WHY SEPARATE FROM RecentActivityFeed (not a prop variant):
 *   1. Row height: 20px vs 28px — a different DOM structure, not a prop toggle.
 *   2. Item count: 5 vs 20 — different API call limit.
 *   3. No sync events: the strip shows only trades, not broker-sync events
 *      (the overview strip has no room for infrastructure rows).
 *   4. Link on click: each row navigates to the portfolio detail page.
 *
 * WHO USES IT: BottomInfoStrip (below SemanticHoldingsTable in the overview).
 * DATA SOURCE: GET /api/v1/transactions?portfolio_id=…&limit=5 (same gateway.getTransactions).
 * TanStack queryKey: qk.portfolios.transactions(portfolioId, { limit: 5 })
 * DESIGN REFERENCE: PRD-0089 §4.1 bottom strip cluster, §6.1 row spec.
 */

"use client";
// WHY "use client": TanStack Query hook (useQuery), Link navigation.

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { formatPrice, formatRelativeTime } from "@/lib/utils";
import { cn } from "@/lib/utils";

// ── Internals ─────────────────────────────────────────────────────────────────

// WHY 5: the strip slot is 96px tall − 22px header = 74px for data.
// At 20px per row, 3-4 rows fit comfortably. 5 rows at ~15px gives a denser
// feed (spec says "last 8 transactions" for the full slot; we cap at 5 to avoid
// vertical overflow in the default layout).
const STRIP_LIMIT = 5;

// ── Side badge helper ─────────────────────────────────────────────────────────

/**
 * SideBadge — BUY / SELL / DIV inline badge.
 *
 * WHY font-mono uppercase tracking: matches the Bloomberg PORT activity column
 * — every fill type is rendered in monospaced caps so columns align vertically
 * even when "SELL" is 4 chars and "DIV" is 3 chars.
 */
function SideBadge({ type }: { type: "BUY" | "SELL" | "DIVIDEND" }) {
  const cls = {
    BUY: "text-positive",
    SELL: "text-negative",
    DIVIDEND: "text-primary",
  }[type];

  const label = type === "DIVIDEND" ? "DIV" : type;

  return (
    <span className={cn("font-mono text-[10px] uppercase w-[26px] shrink-0", cls)}>
      {label}
    </span>
  );
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 3 }).map((_, i) => (
        // WHY bg-muted/30 for skeletons (not Skeleton component): the Skeleton
        // component has a pulse animation — the design spec bans animations on
        // portfolio data surfaces (§6.5). A static muted bar is sufficient.
        <div
          key={i}
          className="flex h-5 items-center px-2 gap-1"
          aria-hidden="true"
        >
          <div className="h-2 w-[26px] rounded-[2px] bg-muted/30" />
          <div className="h-2 flex-1 rounded-[2px] bg-muted/20" />
          <div className="h-2 w-[48px] rounded-[2px] bg-muted/15" />
        </div>
      ))}
    </>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

interface RecentActivityStripProps {
  /**
   * Portfolio UUID. Component renders null when portfolioId is null/undefined.
   * WHY null-safe: the strip is conditionally rendered in the bottom cluster
   * only when an active portfolio is selected; the portfolioId can briefly be
   * null on initial mount before the active portfolio is resolved.
   */
  portfolioId: string | null | undefined;
}

export function RecentActivityStrip({ portfolioId }: RecentActivityStripProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    enabled: Boolean(portfolioId && accessToken),
    // WHY filters object in key: qk.portfolios.transactions includes the limit
    // filter so this query is a distinct cache entry from the Transactions tab
    // query (which fetches up to 100 rows with various filter combinations).
    // Cache identity: two consumers requesting limit:5 share this entry; a
    // consumer requesting limit:100 gets its own entry — no cross-contamination.
    queryKey: qk.portfolios.transactions(portfolioId ?? "", { limit: STRIP_LIMIT }),
    queryFn: () =>
      createGateway(accessToken!).getTransactions(portfolioId!, {
        limit: STRIP_LIMIT,
        offset: 0,
      }),
    staleTime: 30_000,
    // WHY 30s: transactions change only on broker sync (every few hours) but
    // the strip is visible permanently — 30s is a reasonable staleness window
    // that matches the Holdings tab's 30s staleTime for visual consistency.
  });

  if (!portfolioId) return null;

  const transactions = data?.transactions ?? [];

  return (
    <div className="flex flex-col bg-card border-t-0 h-full">
      {/* Section header — matches ContributorsStrip and the design §4.1 */}
      <div className="flex h-[22px] shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
          Recent Activity
        </span>
      </div>

      {/* Transaction rows */}
      {isLoading && <SkeletonRows />}

      {!isLoading && transactions.length === 0 && (
        <div className="flex flex-1 items-center px-2">
          <span className="font-mono text-[10px] text-muted-foreground">
            No recent activity.
            <br />
            <span className="text-[9px]">Transactions appear here after broker sync.</span>
          </span>
        </div>
      )}

      {!isLoading && transactions.length > 0 && (
        <div className="flex flex-col">
          {transactions.slice(0, STRIP_LIMIT).map((tx) => {
            // WHY Link to /portfolio?tab=transactions: clicking an activity row
            // should navigate to the full transactions tab (with that transaction
            // visible), not to the instrument page. The overview strip is a "quick
            // look" surface; deep investigation belongs in the Transactions tab.
            //
            // 2026-06-10 alignment fix: the old layout used a flex row where the
            // QTY cell was OMITTED for dividends, so DIV rows' tickers shifted
            // left and nothing lined up vertically; the 36px time cell also
            // clipped "Yest"-style labels. A fixed-template grid renders every
            // cell in every row (em-dash when N/A) so all five columns align
            // column-perfect across BUY/SELL/DIV rows.
            return (
              <Link
                key={tx.transaction_id}
                href={`/portfolio?tab=transactions`}
                // Grid template: time(42) badge(28) qty(1fr right) ticker(44) price(64 right)
                className="grid h-5 grid-cols-[42px_28px_minmax(0,1fr)_44px_64px] items-center gap-1 px-2 hover:bg-muted/30"
              >
                {/* Date — relative time (e.g. "2h", "Yest").
                    WHY w-42px + nowrap: the previous 36px cell clipped longer
                    relative labels (screenshot bug). whitespace-nowrap stops
                    the label wrapping inside the 20px row. */}
                <span className="whitespace-nowrap font-mono text-[9px] tabular-nums text-muted-foreground">
                  {/* WHY formatRelativeTime: a trader cares about "how recent?" not
                      the exact ISO timestamp. "2h" and "Yest" answer the question
                      in 2-4 chars, leaving more room for ticker + price. */}
                  {formatRelativeTime(tx.executed_at)}
                </span>

                {/* BUY / SELL / DIV badge */}
                <SideBadge type={tx.type} />

                {/* Quantity — ALWAYS rendered (em-dash for dividends, which
                    report qty≈0) so the ticker column never drifts. Right-
                    aligned: quantities are numbers (ADR-F-15 scan rule). */}
                <span className="text-right font-mono text-[10px] tabular-nums text-foreground truncate">
                  {tx.type === "DIVIDEND" ? "—" : tx.quantity.toLocaleString("en-US")}
                </span>

                {/* Ticker — primary colour for quick scan, same as the holdings table */}
                <span className="font-mono text-[10px] text-primary font-medium truncate">
                  {tx.ticker || "—"}
                </span>

                {/* Price or dividend amount — fixed right-aligned column */}
                <span className="text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                  {tx.type === "DIVIDEND"
                    ? formatPrice(tx.amount ?? 0)
                    : formatPrice(tx.price)}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
