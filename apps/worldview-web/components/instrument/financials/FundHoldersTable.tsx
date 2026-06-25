/**
 * components/instrument/financials/FundHoldersTable.tsx
 *
 * WHY THIS EXISTS (T-15): Mutual fund and ETF holders reveal whether index
 * inclusion or active fund management is driving price. A name dominated by
 * Vanguard / SPDR index funds has mechanical buy/sell flows on rebalancing;
 * one held by Cathie Wood's ARKK has more discretionary flow pressure.
 *
 * DATA FORMAT: Same dict-of-dicts EODHD pattern as InstitutionalHoldersTable.
 * Fund holders have identical fields (name, currentShares, currentPercent,
 * currentValue, change) — only the endpoint and section label differ.
 *
 * WHO USES IT: FinancialsTab.tsx — Block 6 of the left column (T-25 wiring).
 * DATA SOURCE: fundHoldersData from useFinancialsSidebarData →
 *   qk.instruments.fundHolders → S9 GET /v1/fundamentals/{id}/fund-holders.
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.7
 *
 * WAVE-4 ENHANCEMENT (de-static-ify): click-to-sort column headers (same
 * useSortableRows primitive as the institutional table) so an analyst can
 * re-rank "which fund added the most shares?" without scanning all 10 rows.
 */

"use client";
// WHY "use client" (changed): the column-sort hook is browser-only state.

import { PanelHeader } from "./PanelHeader";
import { SortableHeaderCell } from "./SortableHeaderCell";
import { useSortableRows, type SortAccessor } from "./useSortableRows";
import { formatMarketCap, formatPercent } from "@/lib/utils";
import { isDictOfDicts } from "@/lib/eohdUtils";
import type { FundamentalsSectionResponse } from "@/types/api";

// ── EODHD wire shape ──────────────────────────────────────────────────────────

interface EohdFundHolder {
  name?: string;
  date?: string;
  totalShares?: number | null;
  currentShares?: number | null;
  currentValue?: number | null;
  currentPercent?: number | null;
  change?: number | null;
  change_p?: number | null;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface FundHoldersTableProps {
  fundHoldersData: FundamentalsSectionResponse | undefined;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function extractHolders(data: FundamentalsSectionResponse | undefined): EohdFundHolder[] {
  const rawRecords = data?.records ?? [];
  if (rawRecords.length === 0) return [];

  const firstData = rawRecords[0]?.data as unknown;

  // WHY isDictOfDicts (shared): detects EODHD's {"0": {...}, "1": {...}} format.
  // The shared implementation rejects {}, {"0": {}}, and {"0": null} — all
  // cases that the previous local version mishandled (false positives / gaps).
  if (isDictOfDicts(firstData)) {
    return Object.values(firstData as Record<string, EohdFundHolder>).filter(Boolean).slice(0, 10);
  }

  // Legacy per-record format. Filter by name to exclude malformed/empty entries.
  return rawRecords
    .slice(0, 10)
    .map((r) => r.data as unknown as EohdFundHolder)
    .filter((h) => !!h.name);
}

function changeColor(change: number | null | undefined): string {
  if (change == null) return "text-muted-foreground/40";
  if (change > 0) return "text-positive";
  if (change < 0) return "text-negative";
  return "text-foreground";
}

function fmtShares(n: number | null | undefined): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(abs / 1_000).toFixed(1)}K`;
  return abs.toLocaleString();
}

function fmtChange(change: number | null | undefined): string {
  if (change == null) return "—";
  const abs = fmtShares(Math.abs(change));
  return change > 0 ? `+${abs}` : change < 0 ? `-${abs}` : abs;
}

// ── Sort wiring ───────────────────────────────────────────────────────────────
type FundSortKey = "name" | "shares" | "percent" | "value" | "change";

const ACCESSORS: Record<FundSortKey, SortAccessor<EohdFundHolder>> = {
  name: (h) => h.name ?? null,
  // Shares cell falls back to totalShares, so the sort key must too (keeps the
  // visible value and the sort key consistent — a silent mismatch otherwise).
  shares: (h) => h.currentShares ?? h.totalShares ?? null,
  percent: (h) => h.currentPercent ?? null,
  value: (h) => h.currentValue ?? null,
  change: (h) => h.change ?? null,
};

// ── Component ─────────────────────────────────────────────────────────────────

export function FundHoldersTable({
  fundHoldersData,
}: FundHoldersTableProps) {
  const holders = extractHolders(fundHoldersData);

  // Keep the endpoint's "top 10" order until a header click; name sorts A→Z.
  const { sortedRows, sort, toggleSort } = useSortableRows<EohdFundHolder, FundSortKey>({
    rows: holders,
    accessors: ACCESSORS,
    defaultDirections: { name: "asc" },
  });

  return (
    <div data-table-grid className="border-t border-border">
      {/* Wave-2 redesign: shared PanelHeader (24px accent-bar band) — every
          Financials panel carries identical chrome now (scope item 1). */}
      <PanelHeader label="FUND HOLDERS" meta="top 10 funds / ETFs · click a column to sort" />

      {holders.length === 0 ? (
        <div className="text-[11px] text-muted-foreground px-2 py-2">
          Fund holder data not available.
        </div>
      ) : (
        <table className="w-full text-[11px] font-mono" role="table" aria-label="Fund holders">
          <thead>
            {/* Wave-4: click-to-sort headers (SortableHeaderCell). */}
            <tr className="h-[22px]">
              <SortableHeaderCell label="Fund" align="left" active={sort.key === "name"} direction={sort.direction} onSort={() => toggleSort("name")} className="text-left" />
              <SortableHeaderCell label="Shares" align="right" active={sort.key === "shares"} direction={sort.direction} onSort={() => toggleSort("shares")} />
              <SortableHeaderCell label="% Held" align="right" active={sort.key === "percent"} direction={sort.direction} onSort={() => toggleSort("percent")} className="whitespace-nowrap" />
              <SortableHeaderCell label="Value" align="right" active={sort.key === "value"} direction={sort.direction} onSort={() => toggleSort("value")} />
              <SortableHeaderCell label="Change" align="right" active={sort.key === "change"} direction={sort.direction} onSort={() => toggleSort("change")} />
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {sortedRows.map((h, i) => (
              <tr key={i} className="h-[22px] hover:bg-muted/20 transition-colors">
                <td className="px-2 text-[11px] text-foreground truncate max-w-[140px]">
                  {h.name ?? "—"}
                </td>
                <td className="px-2 text-right tabular-nums text-foreground whitespace-nowrap">
                  {fmtShares(h.currentShares ?? h.totalShares)}
                </td>
                <td className="px-2 text-right tabular-nums text-foreground whitespace-nowrap">
                  {h.currentPercent != null ? formatPercent(h.currentPercent / 100) : "—"}
                </td>
                <td className="px-2 text-right tabular-nums text-foreground whitespace-nowrap">
                  {h.currentValue != null ? formatMarketCap(h.currentValue) : "—"}
                </td>
                <td className={`px-2 text-right tabular-nums whitespace-nowrap ${changeColor(h.change)}`}>
                  {fmtChange(h.change)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
