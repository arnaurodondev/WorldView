/**
 * components/instrument/financials/statements/statementData.ts
 * Pure derivation helpers for the Financial Statements tables
 * (Wave-2 Financials redesign, scope item 2 — multi-period upgrade).
 *
 * WHY A PURE MODULE (no React, no fetch): the statement maths (period
 * selection, TTM summation, YoY deltas, unit scaling) is the part most
 * likely to be wrong in subtle ways — keeping it framework-free makes it
 * directly unit-testable and lets the presentational table stay dumb.
 *
 * WHAT CHANGED vs the Round-2 "mini" version (buildStatementView): the
 * 2-column (latest vs year-ago) view is replaced by a MULTI-PERIOD table —
 * up to 5 fiscal years or 8 quarters as columns, plus a QUARTERLY mode and
 * a shared per-table unit (auto-scaled to K/M/B, labelled once in the
 * header instead of "$394.3B" repeated in every cell). The Annual/TTM
 * window semantics from Round-2 are PRESERVED verbatim (the ported tests
 * in __tests__/statementData.test.ts pin them).
 *
 * DATA SOURCE SHAPE: S3 fundamentals records ({section, period_type,
 * period_end, data}), reachable through EITHER the financials-bundle
 * `fundamentals` leg OR the Wave-1 dedicated endpoints
 * (GET /v1/fundamentals/{id}/{income-statement,balance-sheet,cash-flow}).
 * Verified live 2026-06-10 against the dev stack (AAPL):
 *   - income_statement: ANNUAL (41) + QUARTERLY (163) records
 *   - balance_sheet:    QUARTERLY only (163) — NO ANNUAL records ingested
 *   - cash_flow:        QUARTERLY only (146) — NO ANNUAL records ingested
 *   - data keys are EODHD camelCase; values may be number OR string
 *     ("379297000000.00"); `eps` is NEVER present (the old
 *     IncomeStatementTable's EPS row rendered "—" forever — dropped here).
 *
 * MODE SEMANTICS:
 *   - ANNUAL (up to 5 columns):
 *       · flow statements with real ANNUAL records (income): per-FY values.
 *       · flow statements with quarterly-only ingestion (cash flow): each
 *         column is the SUM of a non-overlapping 4-quarter window anchored
 *         to the latest quarter — emitted only when all 4 quarters exist
 *         (never extrapolated) and labelled "4Q TO <MMM YY>" so the caption
 *         never claims filed 10-K figures.
 *       · balance sheet (stock variable): the point-in-time snapshot every
 *         4 quarters back from the MRQ (exact — a balance sheet IS its date).
 *   - QUARTERLY (up to 8 columns): raw quarterly records; YoY compares the
 *     latest quarter against the SAME quarter one year earlier (4 back) —
 *     QoQ would be distorted by seasonality (Apple's Q1 holiday peak).
 *   - TTM (2 columns): flow = last-4-quarter sum vs quarters 5–8 (strict —
 *     partial windows render "—"); balance = MRQ vs the year-ago quarter.
 *
 * WHY YoY suppression on prior ≤ 0: a −50 → +50 swing is "+200%" by formula
 * but reads as nonsense; "—" with both absolute columns visible is the
 * honest presentation.
 */

import type { FundamentalsRecord } from "@/types/api";

// ── Public types ──────────────────────────────────────────────────────────────

/** Toggle modes for the statements section (`p` chord cycles them). */
export type StatementMode = "ANNUAL" | "QUARTERLY" | "TTM";

/** Which of the three statements a table renders. */
export type StatementSection = "income_statement" | "balance_sheet" | "cash_flow";

/** One configured line item: display label + the data-dict keys carrying it. */
export interface StatementLineItem {
  readonly label: string;
  /**
   * Candidate keys, first non-null wins. EODHD emits camelCase; snake_case
   * aliases mirror S3's metric_extractor tolerance (defensive, costs nothing).
   */
  readonly keys: readonly string[];
  /** Render a quarterly-series sparkline next to this row (scope item 3). */
  readonly spark?: boolean;
}

/** One period column of the table. */
export interface StatementColumn {
  /** Stable key (period_end or synthetic window id) for React lists. */
  readonly key: string;
  /** Caption, e.g. "FY25", "Q1'26", "TTM", "4Q TO MAR 26", "MRQ MAR 26". */
  readonly label: string;
}

/** One derived row: values aligned to columns + YoY + sparkline series. */
export interface StatementRowView {
  readonly label: string;
  /** Per-column values (chronological, oldest → newest). null renders "—". */
  readonly values: ReadonlyArray<number | null>;
  /**
   * YoY delta of the LATEST column vs its year-ago comparable, as a decimal
   * (+0.12 = +12%). null = missing data or non-positive base (suppressed).
   */
  readonly yoyPct: number | null;
  /**
   * Dense quarterly trend series (last 8 quarters, nulls dropped) for the
   * sparkline microchart. null for rows not flagged `spark` or with <2 pts.
   */
  readonly spark: ReadonlyArray<number> | null;
}

/** Shared per-table magnitude unit (scope item 2: ONE unit per table). */
export interface StatementUnit {
  /** Header caption, e.g. "USD B". */
  readonly label: string;
  /** Divide raw values by this before rendering (1e9 for billions, …). */
  readonly divisor: number;
}

/** A fully derived statement table. */
export interface StatementTableView {
  readonly columns: ReadonlyArray<StatementColumn>;
  readonly rows: ReadonlyArray<StatementRowView>;
  readonly unit: StatementUnit;
}

// ── Line-item configuration ───────────────────────────────────────────────────
//
// WHY ~6 items per statement: a proper compact statement, not a data dump —
// the ladder an analyst actually walks. All keys verified against live AAPL
// records (see module header). EPS deliberately ABSENT (key never ingested).

export const INCOME_ITEMS: readonly StatementLineItem[] = [
  { label: "Revenue", keys: ["totalRevenue", "total_revenue"], spark: true },
  { label: "Gross Profit", keys: ["grossProfit", "gross_profit"] },
  { label: "Operating Income", keys: ["operatingIncome", "operating_income"] },
  { label: "EBITDA", keys: ["ebitda"] },
  { label: "R&D Expense", keys: ["researchDevelopment", "research_development"] },
  { label: "Net Income", keys: ["netIncome", "net_income"], spark: true },
];

export const BALANCE_ITEMS: readonly StatementLineItem[] = [
  { label: "Total Assets", keys: ["totalAssets", "total_assets"] },
  { label: "Cash & ST Invest", keys: ["cashAndShortTermInvestments", "cash_and_short_term_investments", "cash"] },
  { label: "Total Liabilities", keys: ["totalLiab", "total_liab"] },
  { label: "Long-Term Debt", keys: ["longTermDebtTotal", "longTermDebt", "long_term_debt"] },
  { label: "Total Equity", keys: ["totalStockholderEquity", "total_equity"] },
  { label: "Net Debt", keys: ["netDebt", "net_debt"] },
];

export const CASH_FLOW_ITEMS: readonly StatementLineItem[] = [
  {
    label: "Operating CF",
    keys: ["totalCashFromOperatingActivities", "operatingCashFlow", "operating_cash_flow"],
    spark: true,
  },
  { label: "CapEx", keys: ["capitalExpenditures", "capital_expenditures"] },
  { label: "Free Cash Flow", keys: ["freeCashFlow", "free_cash_flow"], spark: true },
  { label: "Investing CF", keys: ["totalCashflowsFromInvestingActivities", "investing_cash_flow"] },
  { label: "Financing CF", keys: ["totalCashFromFinancingActivities", "financing_cash_flow"] },
  { label: "Dividends Paid", keys: ["dividendsPaid", "dividends_paid"] },
];

/** Column caps per mode — enough to see a trend without crushing the layout. */
export const MAX_ANNUAL_COLUMNS = 5;
export const MAX_QUARTERLY_COLUMNS = 8;

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
function extract(
  data: Record<string, unknown> | null | undefined,
  keys: readonly string[],
): number | null {
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
  return `FY${periodEnd.slice(2, 4)}`;
}

/**
 * quarterLabel — "2026-03-31…" → "Q1'26" (calendar quarter from end month).
 * EODHD period_end dates ARE the fiscal-quarter ends; mapping by month is the
 * same convention the legacy IncomeStatementTable used.
 */
export function quarterLabel(periodEnd: string | undefined): string {
  if (!periodEnd) return "—";
  const d = new Date(periodEnd.includes("T") ? periodEnd : `${periodEnd}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return periodEnd.slice(0, 7);
  const month = d.getUTCMonth() + 1;
  const q = month <= 3 ? 1 : month <= 6 ? 2 : month <= 9 ? 3 : 4;
  return `Q${q}'${String(d.getUTCFullYear()).slice(2)}`;
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

/**
 * trailingWindows — non-overlapping 4-quarter windows walking back from the
 * latest quarter, returned OLDEST-FIRST. Only complete windows are kept
 * (strict — see sumWindow rationale). Used for the cash-flow ANNUAL fallback
 * where no filed annual records exist.
 */
function trailingWindows(
  quarterly: readonly FundamentalsRecord[],
  maxWindows: number,
): FundamentalsRecord[][] {
  const windows: FundamentalsRecord[][] = [];
  for (let i = 0; i < maxWindows; i++) {
    const end = quarterly.length - i * 4;
    const start = end - 4;
    if (start < 0) break; // incomplete window → stop (never partial)
    windows.unshift(quarterly.slice(start, end));
  }
  return windows;
}

// ── Sparkline series ──────────────────────────────────────────────────────────

/**
 * quarterlySpark — dense last-8-quarter series for one line item, regardless
 * of the table's mode (scope item 3: trends come "from the quarterly series").
 * Nulls are dropped (Sparkline expects a dense array); <2 points → null.
 */
function quarterlySpark(
  quarterly: readonly FundamentalsRecord[],
  item: StatementLineItem,
): number[] | null {
  if (!item.spark) return null;
  const series = quarterly
    .slice(-MAX_QUARTERLY_COLUMNS)
    .map((q) => extract(q.data as Record<string, unknown>, item.keys))
    .filter((v): v is number => v != null);
  return series.length >= 2 ? series : null;
}

// ── Unit scaling ──────────────────────────────────────────────────────────────

/**
 * deriveUnit — ONE shared magnitude unit per table (scope item 2). Scanning a
 * column where one cell says "$394.3B" and the next "$87.9M" forces a mental
 * unit conversion per cell; scaling the whole table by the LARGEST magnitude
 * and labelling it once in the header removes that tax (10-K convention:
 * "in millions, except per-share data").
 */
export function deriveUnit(rows: ReadonlyArray<StatementRowView>): StatementUnit {
  let maxAbs = 0;
  for (const row of rows) {
    for (const v of row.values) {
      if (v != null && Math.abs(v) > maxAbs) maxAbs = Math.abs(v);
    }
  }
  if (maxAbs >= 1e9) return { label: "USD B", divisor: 1e9 };
  if (maxAbs >= 1e6) return { label: "USD M", divisor: 1e6 };
  if (maxAbs >= 1e3) return { label: "USD K", divisor: 1e3 };
  return { label: "USD", divisor: 1 };
}

// ── Row assembly ──────────────────────────────────────────────────────────────

/**
 * buildRows — map line items over a list of per-column extractors.
 * `yoyIndices` selects which two columns the YoY delta compares
 * ([priorIdx, currentIdx]); null when no valid comparison exists.
 */
function buildRows(
  items: readonly StatementLineItem[],
  columnValues: ReadonlyArray<(keys: readonly string[]) => number | null>,
  yoyIndices: readonly [number, number] | null,
  quarterly: readonly FundamentalsRecord[],
): StatementRowView[] {
  return items.map((item) => {
    const values = columnValues.map((get) => get(item.keys));
    const yoyPct =
      yoyIndices == null
        ? null
        : yoy(values[yoyIndices[1]] ?? null, values[yoyIndices[0]] ?? null);
    return {
      label: item.label,
      values,
      yoyPct,
      spark: quarterlySpark(quarterly, item),
    };
  });
}

/** Value-getter for a single record (point value, not a sum). */
function recordGetter(record: FundamentalsRecord | undefined) {
  return (keys: readonly string[]) =>
    extract(record?.data as Record<string, unknown> | undefined, keys);
}

/** Value-getter for a strict 4-quarter window sum. */
function windowGetter(window: readonly FundamentalsRecord[]) {
  return (keys: readonly string[]) => sumWindow(window, keys);
}

// ── Mode-specific view builders ───────────────────────────────────────────────

/**
 * buildFlowTable — income statement & cash flow (flow variables: sums over time).
 */
function buildFlowTable(
  annual: readonly FundamentalsRecord[],
  quarterly: readonly FundamentalsRecord[],
  items: readonly StatementLineItem[],
  mode: StatementMode,
): StatementTableView {
  if (mode === "TTM") {
    // Strict windows: a 3-quarter "TTM" is not trailing-twelve-months.
    const last4 = quarterly.slice(-4);
    const prior4 = quarterly.slice(-8, -4);
    const cur4 = last4.length === 4 ? last4 : [];
    const pri4 = prior4.length === 4 ? prior4 : [];
    const columns: StatementColumn[] = [
      { key: "prior-ttm", label: "PRIOR TTM" },
      { key: "ttm", label: "TTM" },
    ];
    const rows = buildRows(
      items,
      [windowGetter(pri4), windowGetter(cur4)],
      [0, 1],
      quarterly,
    );
    return { columns, rows, unit: deriveUnit(rows) };
  }

  if (mode === "QUARTERLY") {
    const cols = quarterly.slice(-MAX_QUARTERLY_COLUMNS);
    const columns = cols.map((r) => ({ key: r.period_end, label: quarterLabel(r.period_end) }));
    // YoY = latest quarter vs the SAME quarter one year ago (4 columns back).
    const yoyIdx: [number, number] | null =
      cols.length >= 5 ? [cols.length - 5, cols.length - 1] : null;
    const rows = buildRows(items, cols.map(recordGetter), yoyIdx, quarterly);
    return { columns, rows, unit: deriveUnit(rows) };
  }

  // ANNUAL — real annual records when the section has them (income).
  if (annual.length > 0) {
    const cols = annual.slice(-MAX_ANNUAL_COLUMNS);
    const columns = cols.map((r) => ({ key: r.period_end, label: fyLabel(r.period_end) }));
    const yoyIdx: [number, number] | null =
      cols.length >= 2 ? [cols.length - 2, cols.length - 1] : null;
    const rows = buildRows(items, cols.map(recordGetter), yoyIdx, quarterly);
    return { columns, rows, unit: deriveUnit(rows) };
  }

  // ANNUAL fallback for quarterly-only ingestion (cash_flow live state):
  // non-overlapping 4-quarter sums anchored to the latest quarter. The
  // explicit "4Q TO <date>" caption never pretends these are filed 10-K
  // figures (they are quarter-sums — exact, but differently sourced).
  const windows = trailingWindows(quarterly, MAX_ANNUAL_COLUMNS);
  const columns = windows.map((w) => {
    const end = w[w.length - 1]?.period_end;
    return { key: `4q-${end}`, label: `4Q TO ${shortPeriod(end)}` };
  });
  const yoyIdx: [number, number] | null =
    windows.length >= 2 ? [windows.length - 2, windows.length - 1] : null;
  const rows = buildRows(items, windows.map(windowGetter), yoyIdx, quarterly);
  return { columns, rows, unit: deriveUnit(rows) };
}

/**
 * buildBalanceTable — balance sheet (point-in-time stock variable: NEVER
 * summed; the record at a date IS the balance sheet for that date).
 */
function buildBalanceTable(
  annual: readonly FundamentalsRecord[],
  quarterly: readonly FundamentalsRecord[],
  items: readonly StatementLineItem[],
  mode: StatementMode,
): StatementTableView {
  if (mode === "TTM") {
    // MRQ vs the same point-in-time one year earlier.
    const latest = quarterly[quarterly.length - 1];
    const prior = quarterly[quarterly.length - 5];
    const columns: StatementColumn[] = [
      { key: "yr-ago", label: prior ? `YR-AGO ${shortPeriod(prior.period_end)}` : "YR-AGO" },
      { key: "mrq", label: latest ? `MRQ ${shortPeriod(latest.period_end)}` : "MRQ" },
    ];
    const rows = buildRows(items, [recordGetter(prior), recordGetter(latest)], [0, 1], quarterly);
    return { columns, rows, unit: deriveUnit(rows) };
  }

  if (mode === "QUARTERLY") {
    const cols = quarterly.slice(-MAX_QUARTERLY_COLUMNS);
    const columns = cols.map((r) => ({ key: r.period_end, label: quarterLabel(r.period_end) }));
    const yoyIdx: [number, number] | null =
      cols.length >= 5 ? [cols.length - 5, cols.length - 1] : null;
    const rows = buildRows(items, cols.map(recordGetter), yoyIdx, quarterly);
    return { columns, rows, unit: deriveUnit(rows) };
  }

  // ANNUAL — real annual records when present; otherwise FY-end proxies:
  // every 4th quarterly record walking back from the MRQ (the latest
  // reported balance sheet IS the most recent "annual" snapshot).
  if (annual.length > 0) {
    const cols = annual.slice(-MAX_ANNUAL_COLUMNS);
    const columns = cols.map((r) => ({ key: r.period_end, label: fyLabel(r.period_end) }));
    const yoyIdx: [number, number] | null =
      cols.length >= 2 ? [cols.length - 2, cols.length - 1] : null;
    const rows = buildRows(items, cols.map(recordGetter), yoyIdx, quarterly);
    return { columns, rows, unit: deriveUnit(rows) };
  }

  const snapshots: FundamentalsRecord[] = [];
  for (let i = 0; i < MAX_ANNUAL_COLUMNS; i++) {
    const idx = quarterly.length - 1 - i * 4;
    if (idx < 0) break;
    snapshots.unshift(quarterly[idx]);
  }
  // Point-in-time dates as captions — "MAR 26" is honest; "FY26" would
  // wrongly imply a filed annual balance sheet.
  const columns = snapshots.map((r) => ({ key: r.period_end, label: shortPeriod(r.period_end) }));
  const yoyIdx: [number, number] | null =
    snapshots.length >= 2 ? [snapshots.length - 2, snapshots.length - 1] : null;
  const rows = buildRows(items, snapshots.map(recordGetter), yoyIdx, quarterly);
  return { columns, rows, unit: deriveUnit(rows) };
}

// ── Public entry point ────────────────────────────────────────────────────────

/**
 * buildStatementTable — derive one multi-period table from raw section records.
 * Returns null when the section has NO records at all (caller renders the
 * named empty state instead of a table of em-dashes).
 */
export function buildStatementTable(
  records: readonly FundamentalsRecord[] | undefined,
  section: StatementSection,
  mode: StatementMode,
): StatementTableView | null {
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
    ? buildBalanceTable(annual, quarterly, items, mode)
    : buildFlowTable(annual, quarterly, items, mode);
}
