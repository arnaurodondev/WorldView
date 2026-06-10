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
 */

// WHY no "use client": pure presentational — no hooks, no browser APIs.

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

// ── Component ─────────────────────────────────────────────────────────────────

export function FundHoldersTable({
  fundHoldersData,
}: FundHoldersTableProps) {
  const holders = extractHolders(fundHoldersData);

  return (
    <div data-table-grid className="border-t border-border">
      {/* Round-3 item 2: border-l-2 border-l-primary completes the uniform
          accent-bar header treatment (Round-1 DenseMetricsGrid pattern). */}
      <div className="flex items-center h-[var(--row-h,20px)] px-2 border-b border-border border-l-2 border-l-primary bg-muted/20">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
          FUND HOLDERS
        </span>
      </div>

      {holders.length === 0 ? (
        <div className="text-[11px] text-muted-foreground px-2 py-2">
          Fund holder data not available.
        </div>
      ) : (
        <table className="w-full text-[11px] font-mono" role="table" aria-label="Fund holders">
          <thead>
            <tr className="h-[var(--row-h,20px)]">
              <th scope="col" className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Fund</th>
              <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Shares</th>
              <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">% Held</th>
              <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Value</th>
              <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {holders.map((h, i) => (
              <tr key={i} className="h-[var(--row-h,20px)] hover:bg-muted/20 transition-colors">
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
