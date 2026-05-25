/**
 * AssetTypeBadgeCellRenderer — AG Grid cell renderer: single-letter asset class chip.
 *
 * WHY THIS EXISTS: Institutional PMs scan by asset class (E=equity, F=fund, B=bond,
 * C=crypto) to quickly identify concentration in a single asset type. A 48px column
 * with a single char chip is the most space-efficient way to surface this.
 * WHO USES IT: ag-holdings-columns.tsx ASSET column cellRenderer.
 * DATA SOURCE: params.data?.h.asset_class from Holding (e.g. "equity", "etf").
 * DESIGN REFERENCE: PRD-0089 W2 §4.12, V8
 */

import type { ICellRendererParams } from "ag-grid-community";
import type { EnrichedHoldingRow } from "@/components/portfolio/holdings-columns";
import { cn } from "@/lib/utils";

// Map from asset_class string to single-char chip label.
// WHY one char: 48px column budget; single char is scannable at 10px font.
const ASSET_CLASS_CHAR: Record<string, string> = {
  equity: "E",
  etf: "F",    // F = Fund (covers both etf and fund)
  fund: "F",
  bond: "B",
  fixed_income: "B",
  crypto: "C",
  cryptocurrency: "C",
};

function toChip(assetClass: string | null | undefined): string {
  if (!assetClass) return "—";
  return ASSET_CLASS_CHAR[assetClass.toLowerCase()] ?? "O"; // O = Other
}

export function AssetTypeBadgeCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  // WHY pinned-row guard: totals row is not a real instrument — no asset class.
  if (params.node?.rowPinned === "bottom") return null;

  const assetClass = params.data?.h.asset_class;
  const chip = toChip(assetClass);
  // WHY text-primary for equity: equity is the dominant asset class in most
  // portfolios. Highlighting it with the accent colour helps PMs spot non-equity
  // rows (bonds, crypto) quickly against the baseline.
  const isEquity = assetClass?.toLowerCase() === "equity";

  return (
    <div className="flex items-center justify-center h-full">
      <span
        className={cn(
          "font-mono text-[10px] uppercase tabular-nums",
          isEquity ? "text-primary" : "text-muted-foreground",
        )}
      >
        {chip}
      </span>
    </div>
  );
}
