/**
 * components/instrument/financials/InstitutionalHoldersTable.tsx
 *
 * WHY THIS EXISTS (T-14): The top 10 institutional holders on the Financials tab
 * give analysts a concise view of the major ownership concentration — a heavily
 * Vanguard/BlackRock-owned stock behaves differently in a sell-off than one with
 * active hedge fund ownership. This block answers "who owns it and how much?"
 *
 * DATA FORMAT: EODHD returns institutional holders in a single FundamentalsRecord
 * whose `data` is a dict-of-dicts: `{"0": {name, currentShares, ...}, "1": {...}}`.
 * This mirrors the insider transactions format (same detection logic).
 *
 * WHO USES IT: FinancialsTab.tsx — Block 5 of the left column (T-25 wiring).
 * DATA SOURCE: institutionalData from useFinancialsSidebarData →
 *   qk.instruments.institutionalHolders → S9 GET /v1/fundamentals/{id}/institutional-holders.
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.6
 *
 * WAVE-4 ENHANCEMENT (de-static-ify): every column header is now click-to-sort
 * via useSortableRows + SortableHeaderCell. The default order stays "top 10 by
 * shares held" (the endpoint's natural ranking), but an analyst can instantly
 * re-rank by % Held, Value, or Change ("who's BUYING / SELLING the most?") —
 * the first question a reader asks of an ownership table. This required
 * promoting the file to a client component (sort state lives in the hook).
 */

"use client";
// WHY "use client" (changed): useSortableRows uses useState/useMemo for the
// interactive column sort, which must run in the browser.

import { PanelHeader } from "./PanelHeader";
import { SortableHeaderCell } from "./SortableHeaderCell";
import { useSortableRows, type SortAccessor } from "./useSortableRows";
import { formatMarketCap, formatPercent } from "@/lib/utils";
import { isDictOfDicts } from "@/lib/eohdUtils";
import type { FundamentalsSectionResponse } from "@/types/api";

// ── EODHD wire shape ──────────────────────────────────────────────────────────

interface EohdHolder {
  name?: string;
  date?: string;
  /** Shares held (integer). */
  currentShares?: number | null;
  /** USD market value of position. */
  currentValue?: number | null;
  /** % of total shares outstanding held by this institution. */
  currentPercent?: number | null;
  /** Change in shares since last filing. */
  change?: number | null;
  /** % change in shares since last filing. */
  change_p?: number | null;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface InstitutionalHoldersTableProps {
  institutionalData: FundamentalsSectionResponse | undefined;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function extractHolders(data: FundamentalsSectionResponse | undefined): EohdHolder[] {
  const rawRecords = data?.records ?? [];
  if (rawRecords.length === 0) return [];

  const firstData = rawRecords[0]?.data as unknown;

  // WHY isDictOfDicts (shared): rejects {}, {"0": {}}, {"0": null} — all EODHD
  // empty-data patterns. The previous local copy mishandled {"0": {}}.
  if (isDictOfDicts(firstData)) {
    return Object.values(firstData as Record<string, EohdHolder>).filter(Boolean).slice(0, 10);
  }

  // Legacy per-record format. Filter by name to exclude empty/malformed entries.
  return rawRecords
    .slice(0, 10)
    .map((r) => r.data as unknown as EohdHolder)
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
// Column keys must match the SortableHeaderCell usages below. The HOLDER column
// sorts alphabetically (text); the four numeric columns sort by magnitude.
type HolderSortKey = "name" | "shares" | "percent" | "value" | "change";

// Per-column value extractors. Numbers compare numerically; name compares
// case-insensitively (handled inside the hook's comparator).
const ACCESSORS: Record<HolderSortKey, SortAccessor<EohdHolder>> = {
  name: (h) => h.name ?? null,
  shares: (h) => h.currentShares ?? null,
  percent: (h) => h.currentPercent ?? null,
  value: (h) => h.currentValue ?? null,
  change: (h) => h.change ?? null,
};

// ── Component ─────────────────────────────────────────────────────────────────

export function InstitutionalHoldersTable({
  institutionalData,
}: InstitutionalHoldersTableProps) {
  const holders = extractHolders(institutionalData);

  // Sortable rows. No initialSort → keep the endpoint's "top 10 by shares"
  // order until the user clicks a header. Name defaults to ascending (A→Z);
  // numeric columns default to descending (biggest-first = what "sort by
  // shares" means to a reader).
  const { sortedRows, sort, toggleSort } = useSortableRows<EohdHolder, HolderSortKey>({
    rows: holders,
    accessors: ACCESSORS,
    defaultDirections: { name: "asc" },
  });

  return (
    <div data-table-grid className="border-t border-border">
      {/* Wave-2 redesign: shared PanelHeader (24px accent-bar band) — every
          Financials panel carries identical chrome now (scope item 1). */}
      <PanelHeader label="INSTITUTIONAL HOLDERS" meta="top 10 · click a column to sort" />

      {holders.length === 0 ? (
        <div className="text-[11px] text-muted-foreground px-2 py-2">
          Institutional holder data not available.
        </div>
      ) : (
        <table className="w-full text-[11px] font-mono" role="table" aria-label="Institutional holders">
          <thead>
            {/* Wave-4: headers are now click-to-sort (SortableHeaderCell). */}
            <tr className="h-[22px]">
              <SortableHeaderCell label="Holder" align="left" active={sort.key === "name"} direction={sort.direction} onSort={() => toggleSort("name")} className="text-left" />
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
                  {fmtShares(h.currentShares)}
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
