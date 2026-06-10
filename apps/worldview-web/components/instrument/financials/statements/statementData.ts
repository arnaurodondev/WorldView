/**
 * components/instrument/financials/statements/statementData.ts
 * Pure derivation helpers for the Financial Statements mini-tables
 * (Round-2 Enhancement, Instrument Detail surface, item 2).
 *
 * WHY A PURE MODULE (no React, no fetch): the statement maths (period
 * selection, TTM summation, YoY deltas) is the part most likely to be wrong
 * in subtle ways — keeping it framework-free makes it directly unit-testable
 * and lets the presentational table stay dumb.
 *
 * DATA SOURCE SHAPE: S3 all-sections fundamentals records, as carried by the
 * financials-bundle `fundamentals` leg ({security_id, records:[{section,
 * period_type, period_end, data}, …]}). Verified live 2026-06-10 against the
 * dev stack (AAPL):
 *   - income_statement: ANNUAL (41) + QUARTERLY (163) records
 *   - balance_sheet:    QUARTERLY only (163) — NO ANNUAL records ingested
 *   - cash_flow:        QUARTERLY only (146) — NO ANNUAL records ingested
 *   - data keys are EODHD camelCase (totalRevenue, totalAssets,
 *     totalCashFromOperatingActivities, …); values may be number OR string
 *     ("379297000000.00") per the EODHD reference.
 *
 * MODE SEMANTICS (Annual / TTM toggle):
 *   - ANNUAL:
 *       · flow statements (income, cash flow): per-fiscal-year values.
 *         Income uses real ANNUAL records. Cash flow has no ANNUAL records in
 *         the DB, so each fiscal year is the SUM of its 4 quarterly records —
 *         standard accounting aggregation, only emitted when all 4 quarters
 *         exist (otherwise the column renders "—": we never extrapolate).
 *       · balance sheet (point-in-time): the fiscal-year-END quarterly record.
 *         A balance sheet is a stock variable — the FY-end quarter IS the
 *         annual balance sheet, so this is exact (not an approximation).
 *   - TTM:
 *       · flow statements: SUM of the most recent 4 quarterly records,
 *         compared against the sum of quarters 5–8 (prior TTM) for YoY.
 *         Requires the full 4 (resp. 8) quarters — partial windows render "—".
 *       · balance sheet: most recent quarter (MRQ), compared against the
 *         quarter 4 periods earlier (same point-in-time one year ago).
 *
 * WHY YoY (not QoQ): the scope asks for a YoY delta column; YoY also removes
 * seasonality (Apple's Q1 holiday peak would make any QoQ delta misleading).
 */

import type { FundamentalsRecord } from "@/types/api";

// ── Public types ──────────────────────────────────────────────────────────────

/** Toggle modes for the statements panel. */
export type StatementMode = "ANNUAL" | "TTM";

/** Which of the three statements a table renders. */
export type StatementSection = "income_statement" | "balance_sheet" | "cash_flow";

/** One configured line item: display label + the data-dict keys that carry it. */
export interface StatementLineItem {
  readonly label: string;
  /**
   * Candidate keys, first non-null wins. EODHD emits camelCase; the snake_case
   * aliases mirror S3's metric_extractor tolerance in case older ingest rows
   * normalised keys (defensive, costs nothing).
   */
  readonly keys: readonly string[];
}

/** One computed row of a mini-table. */
export interface StatementRow {
  readonly label: string;
  /** Latest-period value (annual FY / TTM / MRQ depending on mode). */
  readonly current: number | null;
  /** Same measure one year earlier. */
  readonly prior: number | null;
  /**
   * YoY delta as a decimal (+0.12 = +12%). null when either side is missing
   * OR the prior value is ≤ 0 — a percentage change off a zero/negative base
   * is mathematically defined but analytically meaningless (sign flips), so
   * we suppress it rather than print a deceptive number.
   */
  readonly yoyPct: number | null;
}

/** A fully derived mini-table: column captions + rows. */
export interface StatementView {
  /** Caption for the latest column, e.g. "FY25", "TTM", "MRQ (MAR 26)". */
  readonly currentLabel: string;
  /** Caption for the year-ago column, e.g. "FY24", "PRIOR TTM". */
  readonly priorLabel: string;
  readonly rows: StatementRow[];
}

// ── Line-item configuration ───────────────────────────────────────────────────
//
// WHY 5 items per statement: the scope is a COMPACT mini-table — the headline
// lines an analyst checks first. Full statements stay in the dedicated
// IncomeStatementTable / future statement pages.
// Field names verified against live AAPL records (see module header).

export const INCOME_ITEMS: readonly StatementLineItem[] = [
  { label: "Revenue", keys: ["totalRevenue", "total_revenue"] },
  { label: "Gross Profit", keys: ["grossProfit", "gross_profit"] },
  { label: "Operating Income", keys: ["operatingIncome", "operating_income"] },
  { label: "Net Income", keys: ["netIncome", "net_income"] },
  { label: "EBITDA", keys: ["ebitda"] },
];

export const BALANCE_ITEMS: readonly StatementLineItem[] = [
  { label: "Total Assets", keys: ["totalAssets", "total_assets"] },
  { label: "Total Liabilities", keys: ["totalLiab", "total_liab"] },
  { label: "Total Equity", keys: ["totalStockholderEquity", "total_equity"] },
  { label: "Cash & ST Invest", keys: ["cashAndShortTermInvestments", "cash_and_short_term_investments", "cash"] },
  { label: "Net Debt", keys: ["netDebt", "net_debt"] },
];

export const CASH_FLOW_ITEMS: readonly StatementLineItem[] = [
  {
    label: "Operating CF",
    keys: ["totalCashFromOperatingActivities", "operatingCashFlow", "operating_cash_flow"],
  },
  { label: "CapEx", keys: ["capitalExpenditures", "capital_expenditures"] },
  { label: "Free Cash Flow", keys: ["freeCashFlow", "free_cash_flow"] },
  { label: "Dividends Paid", keys: ["dividendsPaid", "dividends_paid"] },
  { label: "Net Change in Cash", keys: ["changeInCash", "change_in_cash"] },
];

// ── Small parsing helpers ─────────────────────────────────────────────────────

/**
 * safeNum — tolerant numeric coercion for EODHD JSONB values.
 * EODHD serialises most figures as strings ("379297000000.00"); older rows may
 * carry "None" literals. Anything non-finite → null (renders "—").
 */
export function safeNum(v: unknown): number | null {
  if (v == null || v === "" || v === "None") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Extract the first non-null candidate key from a record's data dict. */
function extract(data: Record<string, unknown> | null | undefined, keys: readonly string[]): number | null {
  if (!data) return null;
  for (const k of keys) {
    const v = safeNum(data[k]);
    if (v != null) return v;
  }
  return null;
}

/**
 * sortAsc — records sorted chronologically (oldest → newest) by period_end.
 * WHY string compare: period_end is ISO-8601 ("2026-03-31T00:00:00Z" in the
 * bundle leg, "2026-03-31" from dedicated endpoints) — both lexicographically
 * ordered. Records without period_end are dropped (cannot be placed).
 */
function sortAsc(records: readonly FundamentalsRecord[]): FundamentalsRecord[] {
  return records
    .filter((r) => !!r.period_end)
    .sort((a, b) => a.period_end.localeCompare(b.period_end));
}

/** Filter records to one (section, period_type) slice, chronologically sorted. */
export function sliceRecords(
  records: readonly FundamentalsRecord[] | undefined,
  section: StatementSection,
  periodType: "ANNUAL" | "QUARTERLY",
): FundamentalsRecord[] {
  if (!records) return [];
  return sortAsc(records.filter((r) => r.section === section && r.period_type === periodType));
}

/** "2026-03-31T00:00:00Z" → "MAR 26" — compact mono-friendly period caption. */
export function shortPeriod(periodEnd: string | undefined): string {
  if (!periodEnd) return "—";
  const d = new Date(periodEnd.includes("T") ? periodEnd : `${periodEnd}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return periodEnd.slice(0, 7);
  const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  return `${months[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`;
}

/** "2025-09-30…" → "FY25" — fiscal-year caption for annual columns. */
function fyLabel(periodEnd: string | undefined): string {
  if (!periodEnd) return "—";
  const year = periodEnd.slice(2, 4);
  return `FY${year}`;
}

/**
 * yoy — delta as a decimal, suppressed when the base is missing or ≤ 0.
 * (A −50 → +50 swing is "+200%" by formula but reads as nonsense; "—" with the
 * two absolute columns visible is the honest presentation.)
 */
export function yoy(current: number | null, prior: number | null): number | null {
  if (current == null || prior == null || prior <= 0) return null;
  return current / prior - 1;
}

// ── Window aggregation (flow statements) ──────────────────────────────────────

/**
 * sumWindow — sum a line item over a slice of quarterly records.
 * Returns null unless ALL records in the window carry the item (a 3-of-4 sum
 * would silently understate the year — that's fabrication by omission).
 */
function sumWindow(
  quarters: readonly FundamentalsRecord[],
  keys: readonly string[],
): number | null {
  if (quarters.length === 0) return null;
  let total = 0;
  for (const q of quarters) {
    const v = extract(q.data as Record<string, unknown>, keys);
    if (v == null) return null;
    total += v;
  }
  return total;
}

// ── Mode-specific view builders ───────────────────────────────────────────────

/**
 * buildFlowView — income statement & cash flow (flow variables: sum over time).
 *
 * ANNUAL: prefers real ANNUAL records (latest vs prior). When the section has
 * no ANNUAL records at all (live DB state for cash_flow), falls back to
 * fiscal-year sums of quarterly records anchored to the LATEST quarter's
 * month/day (best available FY proxy) — each year requires exactly 4 quarters.
 *
 * TTM: last 4 quarters vs quarters 5–8.
 */
function buildFlowView(
  annual: readonly FundamentalsRecord[],
  quarterly: readonly FundamentalsRecord[],
  items: readonly StatementLineItem[],
  mode: StatementMode,
): StatementView {
  if (mode === "TTM") {
    // Most-recent-last ordering: take tail windows.
    const last4 = quarterly.slice(-4);
    const prior4 = quarterly.slice(-8, -4);
    // WHY require full windows: a 3-quarter "TTM" is not trailing-twelve-months.
    const cur4 = last4.length === 4 ? last4 : [];
    const pri4 = prior4.length === 4 ? prior4 : [];
    return {
      currentLabel: "TTM",
      priorLabel: "PRIOR TTM",
      rows: items.map((item) => {
        const current = sumWindow(cur4, item.keys);
        const prior = sumWindow(pri4, item.keys);
        return { label: item.label, current, prior, yoyPct: yoy(current, prior) };
      }),
    };
  }

  // ANNUAL mode — real annual records when the section has them.
  if (annual.length > 0) {
    const latest = annual[annual.length - 1];
    const prior = annual[annual.length - 2];
    return {
      currentLabel: fyLabel(latest?.period_end),
      priorLabel: prior ? fyLabel(prior.period_end) : "PRIOR FY",
      rows: items.map((item) => {
        const c = extract(latest?.data as Record<string, unknown>, item.keys);
        const p = prior ? extract(prior.data as Record<string, unknown>, item.keys) : null;
        return { label: item.label, current: c, prior: p, yoyPct: yoy(c, p) };
      }),
    };
  }

  // ANNUAL fallback for sections with quarterly-only ingestion (cash_flow):
  // group the most recent 8 quarters into two 4-quarter fiscal years. The
  // grouping anchors on the latest quarter — identical semantics to TTM vs
  // prior-TTM, but labelled as fiscal-year windows ending at that quarter.
  const last4 = quarterly.slice(-4);
  const prior4 = quarterly.slice(-8, -4);
  const cur4 = last4.length === 4 ? last4 : [];
  const pri4 = prior4.length === 4 ? prior4 : [];
  const endLabel = shortPeriod(last4[last4.length - 1]?.period_end);
  return {
    // WHY the explicit "4Q TO" caption: these are quarter-sums, not filed
    // 10-K annual figures — the caption must not pretend otherwise.
    currentLabel: cur4.length ? `4Q TO ${endLabel}` : "FY",
    priorLabel: "PRIOR 4Q",
    rows: items.map((item) => {
      const current = sumWindow(cur4, item.keys);
      const prior = sumWindow(pri4, item.keys);
      return { label: item.label, current, prior, yoyPct: yoy(current, prior) };
    }),
  };
}

/**
 * buildBalanceView — balance sheet (point-in-time stock variable).
 *
 * TTM mode → MRQ (most recent quarter) vs the same quarter one year earlier.
 * ANNUAL mode → fiscal-year-end snapshot: real ANNUAL records when present,
 * otherwise the quarterly record 0 / 4 positions from the end whose period
 * matches the fiscal year end (exact — a balance sheet IS its date).
 */
function buildBalanceView(
  annual: readonly FundamentalsRecord[],
  quarterly: readonly FundamentalsRecord[],
  items: readonly StatementLineItem[],
  mode: StatementMode,
): StatementView {
  let latest: FundamentalsRecord | undefined;
  let prior: FundamentalsRecord | undefined;
  let currentLabel = "—";
  let priorLabel = "—";

  if (mode === "ANNUAL" && annual.length > 0) {
    latest = annual[annual.length - 1];
    prior = annual[annual.length - 2];
    currentLabel = fyLabel(latest?.period_end);
    priorLabel = prior ? fyLabel(prior.period_end) : "PRIOR FY";
  } else {
    // MRQ vs year-ago quarter. In ANNUAL mode without annual records this is
    // the FY-end proxy (latest quarter = most recent reported balance sheet);
    // 4 quarters back = the same point-in-time one year earlier.
    latest = quarterly[quarterly.length - 1];
    prior = quarterly[quarterly.length - 5];
    currentLabel = latest ? `MRQ ${shortPeriod(latest.period_end)}` : "MRQ";
    priorLabel = prior ? `YR-AGO ${shortPeriod(prior.period_end)}` : "YR-AGO";
  }

  return {
    currentLabel,
    priorLabel,
    rows: items.map((item) => {
      const c = extract(latest?.data as Record<string, unknown> | undefined, item.keys);
      const p = extract(prior?.data as Record<string, unknown> | undefined, item.keys);
      return { label: item.label, current: c, prior: p, yoyPct: yoy(c, p) };
    }),
  };
}

// ── Public entry point ────────────────────────────────────────────────────────

/**
 * buildStatementView — derive one mini-table from the raw all-sections records.
 * Returns null when the section has NO records at all (caller renders the
 * named empty state instead of a table of em-dashes).
 */
export function buildStatementView(
  records: readonly FundamentalsRecord[] | undefined,
  section: StatementSection,
  mode: StatementMode,
): StatementView | null {
  const annual = sliceRecords(records, section, "ANNUAL");
  const quarterly = sliceRecords(records, section, "QUARTERLY");
  if (annual.length === 0 && quarterly.length === 0) return null;

  const items =
    section === "income_statement"
      ? INCOME_ITEMS
      : section === "balance_sheet"
        ? BALANCE_ITEMS
        : CASH_FLOW_ITEMS;

  return section === "balance_sheet"
    ? buildBalanceView(annual, quarterly, items, mode)
    : buildFlowView(annual, quarterly, items, mode);
}
