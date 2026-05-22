/**
 * components/instrument/quote/insider/InsiderActivityList.tsx
 * — Top-5 insider transactions mini-list (W5-T-16)
 *
 * DATA SOURCE: `data: FundamentalsSectionResponse | null` from the page-bundle
 *   `bundle.insider` field. Zero extra fetch — the bundle already carries the
 *   last 12 months of insider transactions for the instrument.
 *
 * STORAGE FORMAT (EODHD): The DB stores ALL insider transactions in a SINGLE
 *   FundamentalsRecord where `data` = `{"0": {date, ownerName, transactionCode,
 *   ...}, "1": {...}, ...}`. We detect this dict-of-dicts format by checking
 *   whether the first value is itself a plain object, then call Object.values()
 *   to get individual transactions.
 *
 * LEGACY FORMAT (unit-test fixtures / older cache entries): Individual records
 *   each carry their own flat `data` object in snake_case (owner_name,
 *   transaction_type). We fall back to per-record mapping when the first
 *   record's `data` is NOT a dict-of-dicts.
 *
 * DESIGN:
 *   - `<div data-table-grid="dense">` → 18px `--row-h` rows (Δ4).
 *   - `text-[10px]` labels (F1 floor, Δ2). No `rounded-*` (Δ3).
 *   - Rows: date (10px muted) | owner name truncated | type | value.
 *   - Type color: BUY → positive; SALE → negative; other → muted.
 *   - Max 5 rows; empty state: "No insider activity in last 12 months."
 *
 * WHO USES IT: QuoteTab.tsx (T-25 wiring pass).
 * LINE LIMIT: ≤ 200 LOC.
 */

// WHY no "use client": pure display — props only, no browser APIs.

import type { FundamentalsSectionResponse } from "@/types/api";
import { formatMarketCap } from "@/lib/utils";

// ── EODHD wire shape ──────────────────────────────────────────────────────────

/**
 * EohdInsiderTx — camelCase fields as returned verbatim by the EODHD
 * Insider Transactions API and stored in the DB `data` column.
 *
 * WHY camelCase: EODHD returns camelCase (ownerName, transactionCode) even
 * though our legacy InsiderTransaction interface used snake_case. The DB
 * stores the raw EODHD payload without any server-side transformation.
 */
interface EohdInsiderTx {
  date?: string;
  ownerName?: string;
  /** EODHD single-letter code: S=Sale, P=Purchase, A=Grant, D=Disposition, G=Gift, X=Option exercise. */
  transactionCode?: string;
  /** Number of shares in the transaction. */
  transactionAmount?: number | null;
  /** Per-share price at time of transaction. */
  transactionPrice?: number | null;
  transactionAcquiredDisposed?: string | null;
  transactionDate?: string | null;
  postTransactionAmount?: number | null;
  secLink?: string | null;
  ownerCik?: string | null;
}

/**
 * LegacyInsiderTx — snake_case shape used in unit-test fixtures and older
 * API responses cached before the EODHD camelCase migration.
 * Kept to avoid breaking existing tests (R19).
 */
interface LegacyInsiderTx {
  date?: string;
  owner_name?: string;
  transaction_type?: string; // e.g. "Buy", "Sale", "Option Exercise"
  shares?: number | null;
  value?: number | null; // USD total (pre-computed)
}

/** Normalised shape the component renders — format-agnostic. */
interface NormalisedTx {
  date: string | undefined;
  ownerName: string | undefined;
  /** Single-letter EODHD code after normalisation: P=Purchase, S=Sale, A/D/G/X=other. */
  code: string | undefined;
  /** USD total value (absolute); null when unavailable. */
  value: number | null;
}

// ── Extraction ────────────────────────────────────────────────────────────────

/**
 * isDictOfDicts — detects EODHD's dict-of-dicts storage format
 * `{"0": {...}, "1": {...}, ...}` by checking that the first value is a
 * plain object (not a string / number / null / array).
 */
function isDictOfDicts(obj: unknown): obj is Record<string, EohdInsiderTx> {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  const first = Object.values(obj as Record<string, unknown>)[0];
  return first !== null && typeof first === "object" && !Array.isArray(first);
}

/**
 * legacyTypeToCode — converts old free-text transaction_type values to
 * single-letter EODHD codes so txColor/txLabel work uniformly for both
 * storage formats.
 */
function legacyTypeToCode(type: string | undefined): string | undefined {
  if (!type) return undefined;
  const u = type.toUpperCase();
  if (u === "BUY" || u === "PURCHASE") return "P";
  if (u === "SALE" || u === "SELL") return "S";
  if (u.includes("OPTION")) return "X";
  return type.slice(0, 1).toUpperCase() || undefined;
}

/**
 * extractTransactions — detects storage format and returns up to 5 normalised
 * transactions from the FundamentalsSectionResponse.
 *
 * WHY two-branch logic:
 *   Real DB → ONE record whose `data` is a dict-of-dicts (EODHD camelCase).
 *   Test fixtures → multiple records each with a flat snake_case data object.
 */
function extractTransactions(data: FundamentalsSectionResponse | null | undefined): NormalisedTx[] {
  const rawRecords = data?.records ?? [];
  if (rawRecords.length === 0) return [];

  const firstData = rawRecords[0]?.data as unknown;

  if (isDictOfDicts(firstData)) {
    // EODHD dict-of-dicts: {"0": {ownerName, transactionCode, ...}, "1": ...}
    return Object.values(firstData)
      .filter(Boolean)
      .slice(0, 5)
      .map((tx) => ({
        date: tx.date ?? tx.transactionDate ?? undefined,
        ownerName: tx.ownerName ?? undefined,
        code: tx.transactionCode ?? undefined,
        // WHY multiply amount × price: EODHD provides share count and per-share
        // price separately. Total USD = transactionAmount * transactionPrice.
        value:
          tx.transactionAmount != null && tx.transactionPrice != null
            ? Math.abs(tx.transactionAmount * tx.transactionPrice)
            : null,
      }));
  }

  // Legacy flat format (unit-test fixtures, pre-migration cache entries):
  // Each record carries its own `data` object with snake_case fields.
  return rawRecords
    .slice(0, 5)
    .map((r) => {
      const tx = r.data as unknown as LegacyInsiderTx;
      return {
        date: tx.date ?? undefined,
        ownerName: tx.owner_name ?? undefined,
        code: legacyTypeToCode(tx.transaction_type),
        value: tx.value != null ? Math.abs(tx.value) : null,
      };
    })
    .filter((tx) => !!tx.date || !!tx.ownerName);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * txColor — semantic color for a single-letter EODHD transaction code.
 * P (Purchase) → positive green; S (Sale) → negative red; all others muted.
 *
 * WHY code-based (not string-based): normalising to single-letter codes in
 * extractTransactions means txColor/txLabel work identically for EODHD and
 * legacy formats with no branching at render time.
 */
function txColor(code: string | undefined): string {
  if (!code) return "text-muted-foreground";
  switch (code.toUpperCase()) {
    case "P": return "text-positive";
    case "S": return "text-negative";
    default:  return "text-muted-foreground";
  }
}

/**
 * txLabel — maps EODHD single-letter code to a ≤4-char display label.
 *
 * Codes: S=Sale, P=Purchase/Buy, A=Grant/Award, D=Disposition (non-sale),
 *        G=Gift, X=Option exercise.
 */
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

/** Format USD value as compact signed string (e.g. "+$2.8M", "-$2.8M"). */
function fmtValue(value: number | null, code: string | undefined): string | null {
  if (value == null) return null;
  const sign = code?.toUpperCase() === "P" ? "+" : "-";
  return `${sign}${formatMarketCap(Math.abs(value))}`;
}

/**
 * fmtDate — format ISO date string to "MMM D" (e.g. "Apr 30").
 * Returns "—" for undefined input or dates that fail to parse.
 * WHY isNaN check: new Date("garbage") doesn't throw — it returns Invalid Date.
 */
function fmtDate(dateStr: string | undefined): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return dateStr.slice(0, 10);
  }
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface InsiderActivityListProps {
  /** Insider transactions from bundle.insider (FundamentalsSectionResponse). */
  data: FundamentalsSectionResponse | null | undefined;
  /** True while bundle is loading — shows skeleton rows. */
  isLoading?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InsiderActivityList({ data, isLoading = false }: InsiderActivityListProps) {
  // WHY extractTransactions: transparently handles EODHD dict-of-dicts format
  // (ONE record with data={"0": {ownerName, transactionCode...}}) AND the
  // legacy flat format used in unit-test fixtures. See module-level JSDoc.
  const transactions = extractTransactions(data);
  const isEmpty = !isLoading && transactions.length === 0;

  return (
    <div className="border-t border-[hsl(var(--border-subtle))]">
      {/* Section header */}
      <div className="flex items-center h-[20px] px-3 border-b border-[hsl(var(--border-subtle))]">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">
          Insider Activity
        </span>
      </div>

      {/* WHY data-table-grid="dense": dense variant → --row-h=18px (Δ4).
          18px × 5 rows = 90px card height — compact enough to sit above the fold. */}
      <div data-table-grid="dense">
        {isLoading && Array.from({ length: 5 }).map((_, i) => (
          <div key={i} role="row" className="flex items-center h-[var(--row-h,18px)] px-3 gap-2">
            <span className="text-[10px] text-muted-foreground/30">—</span>
          </div>
        ))}

        {isEmpty && (
          <div className="px-3 py-2 text-[10px] text-muted-foreground/60">
            No insider activity in last 12 months.
          </div>
        )}

        {!isLoading && !isEmpty && transactions.map((tx, idx) => (
          <div
            key={idx}
            role="row"
            className="flex items-center h-[var(--row-h,18px)] px-3 gap-1.5"
          >
            {/* Date: MMM D */}
            <span className="text-[10px] text-muted-foreground shrink-0 w-[36px]">
              {fmtDate(tx.date)}
            </span>
            {/* Owner name: truncated to available space */}
            <span className="text-[10px] text-foreground truncate flex-1 min-w-0">
              {tx.ownerName ?? "—"}
            </span>
            {/* Type: BUY/SALE/OPT/etc in semantic color */}
            <span className={`text-[10px] font-mono shrink-0 ${txColor(tx.code)}`}>
              {txLabel(tx.code)}
            </span>
            {/* Value: +$2.8M / -$2.8M */}
            <span className={`text-[10px] font-mono tabular-nums shrink-0 ${txColor(tx.code)}`}>
              {fmtValue(tx.value, tx.code) ?? "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
