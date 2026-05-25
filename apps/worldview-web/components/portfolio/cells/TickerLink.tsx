/**
 * TickerLink — AG Grid cell renderer: ticker text as a navigation link.
 *
 * WHY THIS EXISTS: PRD-0089 F2 locked all instrument navigation to
 * /instruments/{ticker}. The holdings table ticker cell must navigate to the
 * instrument detail page on click, giving the PM a fast path from position to
 * fundamental/intelligence view.
 * WHO USES IT: ag-holdings-columns.tsx TICKER column cellRenderer (step 4.10).
 * DATA SOURCE: params.data?.h.ticker — ticker string from EnrichedHoldingRow.
 * DESIGN REFERENCE: PRD-0089 F2 step 11, W2 §4.10, V6
 */

import Link from "next/link";
import type { ICellRendererParams } from "ag-grid-community";
import type { EnrichedHoldingRow } from "@/components/portfolio/holdings-columns";

export function TickerLinkCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  // WHY pinned-row guard: the totals footer row (pinnedBottomRowData) has an
  // empty ticker ("") and should show "TOTAL" as a plain label, NOT a link.
  if (params.node?.rowPinned === "bottom") {
    return (
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-semibold">
        TOTAL
      </span>
    );
  }

  const ticker = params.data?.h.ticker;
  if (!ticker) return <span className="font-mono text-[11px] text-muted-foreground">—</span>;

  return (
    // WHY stopPropagation: AG Grid row click fires onRowClicked which also navigates.
    // Without stopPropagation, a link click would trigger both the Link href AND the
    // row click handler — double navigation attempt causing a visible flicker.
    <Link
      href={`/instruments/${encodeURIComponent(ticker)}`}
      onClick={(e) => e.stopPropagation()}
      className="font-mono text-[11px] text-primary hover:underline font-medium"
    >
      {ticker}
    </Link>
  );
}
