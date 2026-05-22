/**
 * RecentActivityStrip — compact last-8-transactions feed.
 *
 * WHY THIS EXISTS: The old layout had overlapping text because flex children
 * lacked `min-w-0` and truncation — each span expanded to its intrinsic
 * content width and overflowed into neighbours (C-34, density pass 2026-05-21).
 * This rewrite uses a CSS grid with explicit column widths so each field
 * occupies a fixed slot and text truncates cleanly.
 *
 * COLUMN LAYOUT: DATE(48px) | TYPE(36px) | TICKER(52px) | QTY(flex) | PRICE(flex)
 * WHY grid (not flex): grid column templates enforce widths even when content
 * is shorter — flex columns can shrink to zero if `shrink-0` is forgotten.
 *
 * WHO USES IT: BottomInfoStrip (3-column grid below SemanticHoldingsTable).
 * DATA SOURCE: GET /v1/portfolios/{id}/transactions?limit=8 (via TanStack Query).
 * DESIGN REFERENCE: PRD-0089 W2 §4.14, C-34, C-35, density pass 2026-05-21
 */
"use client";
// WHY "use client": useQuery (TanStack) requires React context; date formatting uses Date.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice } from "@/lib/utils";
// WHY qk.portfolios.transactions: centralised key factory keeps cache entries
// consistent across all call sites (PLAN-0059-C C-2 migration).
import { QK_VERSION } from "@/lib/query/keys";

interface RecentActivityStripProps {
  portfolioId: string | null | undefined;
}

// C-35 date format: "12:18" today / "Yest" yesterday / "Xd ago" ≤7d / "Jan 12" older
function formatActivityDate(isoUtc: string): string {
  const txDate = new Date(isoUtc);
  const now = new Date();
  const diffMs = now.getTime() - txDate.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) {
    // Same calendar day — show time
    return txDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  if (diffDays === 1) return "Yest";
  if (diffDays <= 7) return `${diffDays}d`;
  return txDate.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function RecentActivityStrip({ portfolioId }: RecentActivityStripProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    // WHY separate key from full transactions: this strip fetches limit=8 only;
    // sharing the full transactions key would overwrite the paginated cache entry.
    queryKey: portfolioId
      ? ([QK_VERSION, "portfolios", "detail", portfolioId, "transactions", "recent-8"] as const)
      : (["disabled"] as const),
    queryFn: () => createGateway(accessToken).getTransactions(portfolioId!, { limit: 8 }),
    enabled: !!portfolioId && !!accessToken,
    staleTime: 60_000,
  });

  const rows = data?.transactions ?? [];

  if (!portfolioId) return null;

  return (
    <div className="flex flex-col bg-card border-b border-border h-full">
      {/* Section header — fixed 22px matches the rest of the portfolio page chrome */}
      <div className="flex h-[22px] shrink-0 items-center border-b border-border px-3">
        <span className="text-[10px] uppercase tracking-[0.06em] text-neutral-500">
          Recent Activity
        </span>
      </div>

      {/* Column headers — match the data grid widths below */}
      {/* WHY grid-cols template: aligns headers with data rows at zero cost.
          The template mirrors the data row template exactly. */}
      <div
        className="grid h-[18px] items-center border-b border-border/40 px-3"
        style={{ gridTemplateColumns: "48px 40px 52px 1fr 1fr" }}
      >
        <span className="font-mono text-[10px] text-muted-foreground">DATE</span>
        <span className="font-mono text-[10px] text-muted-foreground">TYPE</span>
        <span className="font-mono text-[10px] text-muted-foreground">TICKER</span>
        <span className="font-mono text-[10px] text-muted-foreground">QTY</span>
        <span className="font-mono text-[10px] text-right text-muted-foreground">PRICE</span>
      </div>

      {/* Body */}
      {isLoading ? (
        <div className="flex h-[22px] items-center px-3">
          <span className="font-mono text-[11px] text-muted-foreground">loading…</span>
        </div>
      ) : rows.length === 0 ? (
        <div className="flex h-[22px] items-center px-3">
          <span className="font-mono text-[11px] text-muted-foreground">No transactions yet</span>
        </div>
      ) : (
        rows.map((tx) => (
          // WHY grid (not flex): grid template columns enforce widths and prevent
          // children from overflowing into neighbours — fixes the text overlap bug
          // that appeared with the old `flex gap-3` layout (no min-w-0 on children).
          <div
            key={tx.transaction_id}
            className="grid h-[22px] items-center px-3"
            style={{ gridTemplateColumns: "48px 40px 52px 1fr 1fr" }}
          >
            {/* DATE — fixed 48px, tabular nums for alignment */}
            <span className="font-mono text-[11px] tabular-nums text-neutral-500 truncate">
              {formatActivityDate(tx.executed_at)}
            </span>

            {/* TYPE — color-coded BUY/SELL/DIVIDEND */}
            {/* WHY truncate: "DIVIDEND" is 8 chars; the 40px column clips it to "DIVID…"
                which is still readable. A full "DIVIDEND" label would overflow the slot. */}
            <span
              className={`font-mono text-[11px] truncate ${
                tx.type === "BUY"
                  ? "text-positive"
                  : tx.type === "SELL"
                    ? "text-negative"
                    : "text-neutral-500"
              }`}
            >
              {tx.type}
            </span>

            {/* TICKER — primary colour, links to instrument */}
            <span className="font-mono text-[11px] text-neutral-100 truncate">
              {tx.ticker || "—"}
            </span>

            {/* QTY — right-aligned tabular nums, flex-1 so it fills the remaining space */}
            <span className="font-mono text-[11px] tabular-nums text-neutral-500 truncate">
              {tx.type === "DIVIDEND" ? "—" : tx.quantity.toLocaleString()}
            </span>

            {/* PRICE — right-aligned */}
            <span className="font-mono text-[11px] tabular-nums text-neutral-100 text-right truncate">
              {tx.type === "DIVIDEND"
                ? formatPrice(tx.amount ?? 0)
                : formatPrice(tx.price)}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
