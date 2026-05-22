/**
 * components/instrument/financials/InsiderTransactionsTable.tsx
 *
 * WHY THIS EXISTS (T-13): The insider transactions block on the Financials tab
 * shows 8 most-recent Form 4 filings in a full-width table. Unlike the 4-row
 * mini-list (InsiderActivityList on the Quote tab), this table includes the
 * per-share price and a direct SEC link — giving analysts enough detail to
 * distinguish programmatic 10b5-1 sales from discretionary ones.
 *
 * WHY PROP DATA (not self-fetch): useFinancialsSidebarData (T-04) already
 * fires the ownership query. Receiving `insiderData` as a prop means this
 * component joins the in-flight TanStack Query request at zero extra cost.
 *
 * DATA FORMAT: EODHD returns insider transactions as a single FundamentalsRecord
 * whose `data` = `{"0": {ownerName, transactionCode, ...}, "1": {...}, ...}`.
 * We detect this dict-of-dicts format and fall back to legacy per-record format
 * for test fixtures (identical handling to InsiderActivityList).
 *
 * WHO USES IT: FinancialsTab.tsx — Block 4 of the left column (T-25 wiring).
 * DATA SOURCE: insiderData from useFinancialsSidebarData → qk.instruments.ownership.
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.5
 */

"use client";
// WHY "use client": useRouter for the "View all" link navigation.

import { useRouter } from "next/navigation";
import { formatMarketCap, formatPrice } from "@/lib/utils";
import type { FundamentalsSectionResponse } from "@/types/api";

// ── EODHD wire shapes ─────────────────────────────────────────────────────────

interface EohdInsiderTx {
  date?: string;
  ownerName?: string;
  transactionCode?: string;
  transactionAmount?: number | null;
  transactionPrice?: number | null;
  transactionDate?: string | null;
  secLink?: string | null;
}

interface LegacyInsiderTx {
  date?: string;
  owner_name?: string;
  transaction_type?: string;
  shares?: number | null;
  value?: number | null;
}

interface NormalisedTx {
  date: string | undefined;
  ownerName: string | undefined;
  code: string | undefined;
  shares: number | null;
  price: number | null;
  value: number | null;
  secLink: string | null | undefined;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface InsiderTransactionsTableProps {
  insiderData: FundamentalsSectionResponse | undefined;
  /** Ticker used to construct the "View all" stub route. */
  ticker: string | null | undefined;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function isDictOfDicts(obj: unknown): obj is Record<string, EohdInsiderTx> {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  const first = Object.values(obj as Record<string, unknown>)[0];
  return first !== null && typeof first === "object" && !Array.isArray(first);
}

function legacyTypeToCode(type: string | undefined): string | undefined {
  if (!type) return undefined;
  const u = type.toUpperCase();
  if (u === "BUY" || u === "PURCHASE") return "P";
  if (u === "SALE" || u === "SELL") return "S";
  if (u.includes("OPTION")) return "X";
  return type.slice(0, 1).toUpperCase() || undefined;
}

function extractTransactions(data: FundamentalsSectionResponse | undefined): NormalisedTx[] {
  const rawRecords = data?.records ?? [];
  if (rawRecords.length === 0) return [];

  const firstData = rawRecords[0]?.data as unknown;

  if (isDictOfDicts(firstData)) {
    return Object.values(firstData)
      .filter(Boolean)
      .slice(0, 8)
      .map((tx) => ({
        date: tx.date ?? tx.transactionDate ?? undefined,
        ownerName: tx.ownerName ?? undefined,
        code: tx.transactionCode ?? undefined,
        shares: tx.transactionAmount ?? null,
        price: tx.transactionPrice ?? null,
        value:
          tx.transactionAmount != null && tx.transactionPrice != null
            ? Math.abs(tx.transactionAmount * tx.transactionPrice)
            : null,
        secLink: tx.secLink ?? null,
      }));
  }

  // Legacy flat format — unit-test fixtures and pre-migration cache entries.
  return rawRecords
    .slice(0, 8)
    .map((r) => {
      const tx = r.data as unknown as LegacyInsiderTx;
      return {
        date: tx.date ?? undefined,
        ownerName: tx.owner_name ?? undefined,
        code: legacyTypeToCode(tx.transaction_type),
        shares: tx.shares ?? null,
        price: null,
        value: tx.value != null ? Math.abs(tx.value) : null,
        secLink: null,
      };
    })
    .filter((tx) => !!tx.date || !!tx.ownerName);
}

function txColor(code: string | undefined): string {
  if (!code) return "text-muted-foreground";
  switch (code.toUpperCase()) {
    case "P": return "text-positive";
    case "S": return "text-negative";
    default:  return "text-muted-foreground";
  }
}

function txLabel(code: string | undefined): string {
  if (!code) return "—";
  switch (code.toUpperCase()) {
    case "P": return "BUY";
    case "S": return "SALE";
    case "A": return "GRNT";
    case "D": return "DISP";
    case "G": return "GIFT";
    case "X": return "OPT";
    default:  return code.slice(0, 4).toUpperCase();
  }
}

function fmtDate(dateStr: string | undefined): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr + (dateStr.length === 10 ? "T00:00:00Z" : ""));
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" });
  } catch {
    return dateStr.slice(0, 10);
  }
}

function fmtShares(n: number | null): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(abs / 1_000).toFixed(1)}K`;
  return abs.toLocaleString();
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InsiderTransactionsTable({
  insiderData,
  ticker,
}: InsiderTransactionsTableProps) {
  const router = useRouter();
  const transactions = extractTransactions(insiderData);

  return (
    <div data-table-grid className="border-t border-border">
      {/* Section header with "View all" stub link. */}
      <div className="flex items-center justify-between h-[var(--row-h,20px)] px-2 border-b border-border bg-muted/20">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
          INSIDER TRANSACTIONS
        </span>
        {ticker && (
          <button
            className="text-[9px] text-muted-foreground/50 hover:text-muted-foreground transition-colors cursor-pointer"
            onClick={() => router.push(`/instruments/${ticker}/insiders`)}
          >
            View all →
          </button>
        )}
      </div>

      {transactions.length === 0 ? (
        <div className="text-[11px] text-muted-foreground px-2 py-2">
          No insider activity in last 12 months.
        </div>
      ) : (
        <table className="w-full text-[11px] font-mono" role="table" aria-label="Insider transactions">
          <thead>
            <tr className="h-[var(--row-h,20px)]">
              <th scope="col" className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">Date</th>
              <th scope="col" className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Insider</th>
              <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Type</th>
              <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Shares</th>
              <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Price</th>
              <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Value</th>
              <th scope="col" className="px-2 text-center text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">SEC</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {transactions.map((tx, i) => (
              <tr key={i} className="h-[var(--row-h,20px)] hover:bg-muted/20 transition-colors">
                <td className="px-2 text-[10px] text-muted-foreground whitespace-nowrap tabular-nums">
                  {fmtDate(tx.date)}
                </td>
                <td className="px-2 text-[11px] text-foreground truncate max-w-[110px]">
                  {tx.ownerName ?? "—"}
                </td>
                <td className={`px-2 text-right tabular-nums font-semibold ${txColor(tx.code)}`}>
                  {txLabel(tx.code)}
                </td>
                <td className="px-2 text-right tabular-nums text-foreground whitespace-nowrap">
                  {fmtShares(tx.shares)}
                </td>
                <td className="px-2 text-right tabular-nums text-foreground whitespace-nowrap">
                  {tx.price != null ? formatPrice(tx.price) : "—"}
                </td>
                <td className={`px-2 text-right tabular-nums whitespace-nowrap ${txColor(tx.code)}`}>
                  {tx.value != null ? formatMarketCap(tx.value) : "—"}
                </td>
                <td className="px-2 text-center">
                  {tx.secLink && tx.secLink.startsWith("https://") ? (
                    <a
                      href={tx.secLink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[10px] text-muted-foreground/50 hover:text-primary transition-colors"
                      onClick={(e) => e.stopPropagation()}
                    >
                      SEC
                    </a>
                  ) : (
                    <span className="text-[10px] text-muted-foreground/30">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
