/**
 * statementData.test.ts — unit tests for the multi-period statement derivation
 * (Wave-2 Financials redesign, scope item 2).
 *
 * PORTED FROM the Round-2 `buildStatementView` suite (this file's previous
 * revision) — every Round-2 semantic contract is re-pinned against the new
 * `buildStatementTable` API:
 *   - ANNUAL income: latest vs prior FY values + YoY + FY column labels;
 *   - TTM flows: strict 4-quarter sums (and null when a window is short or
 *     holed — never a partial "TTM");
 *   - balance sheet: MRQ point-in-time vs the year-ago quarter (never summed);
 *   - cash-flow ANNUAL fallback (quarterly-only ingestion — the live DB
 *     state) labelled "4Q TO …", never as filed FY figures;
 *   - YoY suppression on missing / non-positive bases;
 *   - string-number coercion (EODHD serialises figures as strings);
 *   - zero-records → null sentinel (named empty state upstream).
 *
 * NEW Wave-2 contracts:
 *   - multi-period columns (up to 5 FYs annual / 8 quarters quarterly);
 *   - QUARTERLY mode YoY = latest vs the SAME quarter one year ago;
 *   - shared per-table unit scaling (deriveUnit);
 *   - quarterly sparkline series only on flagged rows.
 */

import { describe, it, expect } from "vitest";

import {
  buildStatementTable,
  deriveUnit,
  safeNum,
  yoy,
  quarterLabel,
  type StatementRowView,
  type StatementSection,
} from "../statementData";
import type { FundamentalsRecord } from "@/types/api";

// ── Fixture builders ──────────────────────────────────────────────────────────

let idCounter = 0;

function rec(
  section: StatementSection,
  periodType: "ANNUAL" | "QUARTERLY",
  periodEnd: string,
  data: Record<string, unknown>,
): FundamentalsRecord {
  idCounter += 1;
  return {
    id: `r${idCounter}`,
    security_id: "sec-1",
    section,
    period_end: periodEnd,
    period_type: periodType,
    data,
    source: "eodhd",
    ingested_at: "2026-06-01T00:00:00Z",
  } as FundamentalsRecord;
}

/** N quarterly income records ending at the given quarters, revenue per index. */
function quarterlyIncome(quarters: Array<[string, number]>): FundamentalsRecord[] {
  return quarters.map(([end, revenue]) =>
    rec("income_statement", "QUARTERLY", end, { totalRevenue: revenue, netIncome: revenue / 10 }),
  );
}

// 8 quarters: prior-TTM quarters sum to 400, latest-TTM quarters sum to 500.
const EIGHT_QUARTERS = quarterlyIncome([
  ["2024-09-30T00:00:00Z", 90],
  ["2024-12-31T00:00:00Z", 110],
  ["2025-03-31T00:00:00Z", 100],
  ["2025-06-30T00:00:00Z", 100],
  ["2025-09-30T00:00:00Z", 120],
  ["2025-12-31T00:00:00Z", 140],
  ["2026-03-31T00:00:00Z", 120],
  ["2026-06-30T00:00:00Z", 120],
]);

/** Convenience: a row by label + its latest / prior-comparable values. */
function row(view: { rows: ReadonlyArray<StatementRowView> }, label: string): StatementRowView {
  const found = view.rows.find((r) => r.label === label);
  if (!found) throw new Error(`row ${label} not found`);
  return found;
}

function latest(r: StatementRowView): number | null {
  return r.values[r.values.length - 1] ?? null;
}

// ── safeNum / yoy primitives (ported verbatim) ────────────────────────────────

describe("safeNum", () => {
  it("coerces EODHD string figures to numbers", () => {
    expect(safeNum("379297000000.00")).toBe(379297000000);
  });

  it("maps null / empty / 'None' / NaN to null", () => {
    expect(safeNum(null)).toBeNull();
    expect(safeNum("")).toBeNull();
    expect(safeNum("None")).toBeNull();
    expect(safeNum("not-a-number")).toBeNull();
  });
});

describe("yoy", () => {
  it("computes the decimal delta", () => {
    expect(yoy(120, 100)).toBeCloseTo(0.2);
  });

  it("suppresses the delta when either side is missing", () => {
    expect(yoy(null, 100)).toBeNull();
    expect(yoy(120, null)).toBeNull();
  });

  it("suppresses the delta on a non-positive base (sign-flip nonsense)", () => {
    expect(yoy(50, -50)).toBeNull();
    expect(yoy(50, 0)).toBeNull();
  });
});

// ── ANNUAL mode — income statement (real annual records) ─────────────────────

describe("buildStatementTable — income statement, ANNUAL", () => {
  const records = [
    rec("income_statement", "ANNUAL", "2024-09-30T00:00:00Z", {
      totalRevenue: "100",
      netIncome: 20,
    }),
    rec("income_statement", "ANNUAL", "2025-09-30T00:00:00Z", {
      totalRevenue: "120",
      netIncome: 30,
    }),
    // Decoy quarterly record — must NOT appear as an annual column.
    ...quarterlyIncome([["2026-03-31T00:00:00Z", 999]]),
  ];

  it("uses chronological FY columns with FY labels and computes YoY latest-vs-prior", () => {
    const view = buildStatementTable(records, "income_statement", "ANNUAL");
    expect(view).not.toBeNull();
    expect(view!.columns.map((c) => c.label)).toEqual(["FY24", "FY25"]);

    const revenue = row(view!, "Revenue");
    // String "120" must be coerced — not concatenated or dropped.
    expect(revenue.values).toEqual([100, 120]);
    expect(revenue.yoyPct).toBeCloseTo(0.2);
  });

  it("caps annual columns at 5 fiscal years (latest kept)", () => {
    const sevenYears = Array.from({ length: 7 }, (_, i) =>
      rec("income_statement", "ANNUAL", `${2019 + i}-09-30T00:00:00Z`, {
        totalRevenue: 100 + i,
      }),
    );
    const view = buildStatementTable(sevenYears, "income_statement", "ANNUAL");
    expect(view!.columns).toHaveLength(5);
    expect(view!.columns[view!.columns.length - 1]!.label).toBe("FY25");
    expect(latest(row(view!, "Revenue"))).toBe(106);
  });

  it("renders null (em-dash) values for line items absent from the data", () => {
    const view = buildStatementTable(records, "income_statement", "ANNUAL");
    const ebitda = row(view!, "EBITDA");
    expect(latest(ebitda)).toBeNull();
    expect(ebitda.yoyPct).toBeNull();
  });
});

// ── QUARTERLY mode (new in Wave-2) ────────────────────────────────────────────

describe("buildStatementTable — income statement, QUARTERLY", () => {
  it("renders the last 8 quarters as columns with Qx'yy labels", () => {
    const view = buildStatementTable(EIGHT_QUARTERS, "income_statement", "QUARTERLY");
    expect(view!.columns).toHaveLength(8);
    expect(view!.columns[0]!.label).toBe("Q3'24");
    expect(view!.columns[7]!.label).toBe("Q2'26");
    expect(row(view!, "Revenue").values).toEqual([90, 110, 100, 100, 120, 140, 120, 120]);
  });

  it("YoY compares the latest quarter against the SAME quarter one year ago", () => {
    const view = buildStatementTable(EIGHT_QUARTERS, "income_statement", "QUARTERLY");
    // Q2'26 = 120 vs Q2'25 = 100 → +20%. QoQ (120 vs 120 → 0%) would be the
    // seasonality-distorted wrong comparison.
    expect(row(view!, "Revenue").yoyPct).toBeCloseTo(0.2);
  });

  it("suppresses YoY when fewer than 5 quarters exist (no year-ago comparable)", () => {
    const view = buildStatementTable(EIGHT_QUARTERS.slice(-4), "income_statement", "QUARTERLY");
    expect(view!.columns).toHaveLength(4);
    expect(row(view!, "Revenue").yoyPct).toBeNull();
  });
});

// ── TTM mode — strict 4-quarter windows (ported) ─────────────────────────────

describe("buildStatementTable — income statement, TTM", () => {
  it("sums the last 4 quarters and compares against quarters 5–8", () => {
    const view = buildStatementTable(EIGHT_QUARTERS, "income_statement", "TTM");
    const revenue = row(view!, "Revenue");
    expect(revenue.values).toEqual([400, 500]); // [prior TTM, TTM]
    expect(revenue.yoyPct).toBeCloseTo(0.25);
    expect(view!.columns.map((c) => c.label)).toEqual(["PRIOR TTM", "TTM"]);
  });

  it("returns null sums when fewer than 4 quarters exist (no partial TTM)", () => {
    const onlyThree = EIGHT_QUARTERS.slice(-3);
    const view = buildStatementTable(onlyThree, "income_statement", "TTM");
    const revenue = row(view!, "Revenue");
    expect(revenue.values).toEqual([null, null]);
  });

  it("nulls the whole window if ANY quarter is missing the line item", () => {
    const withHole = [
      ...EIGHT_QUARTERS.slice(0, 7),
      rec("income_statement", "QUARTERLY", "2026-06-30T00:00:00Z", { netIncome: 12 }), // no revenue
    ];
    const view = buildStatementTable(withHole, "income_statement", "TTM");
    // 3-of-4 quarters would understate the year — must be suppressed.
    expect(latest(row(view!, "Revenue"))).toBeNull();
  });
});

// ── Balance sheet — point-in-time semantics (ported) ──────────────────────────

describe("buildStatementTable — balance sheet (quarterly-only ingestion)", () => {
  const balanceQuarters = [
    ["2024-09-30T00:00:00Z", 300],
    ["2024-12-31T00:00:00Z", 310],
    ["2025-03-31T00:00:00Z", 320],
    ["2025-06-30T00:00:00Z", 330],
    ["2025-09-30T00:00:00Z", 340],
  ].map(([end, assets]) =>
    rec("balance_sheet", "QUARTERLY", end as string, { totalAssets: assets }),
  );

  it("TTM mode: MRQ vs the quarter 4 periods back (NOT a sum)", () => {
    const view = buildStatementTable(balanceQuarters, "balance_sheet", "TTM");
    const assets = row(view!, "Total Assets");
    expect(assets.values).toEqual([300, 340]); // [year-ago point, MRQ point]
    expect(assets.yoyPct).toBeCloseTo(340 / 300 - 1);
    expect(view!.columns[view!.columns.length - 1]!.label).toContain("MRQ");
  });

  it("ANNUAL mode without annual records: every-4th-quarter snapshots, never summed", () => {
    const view = buildStatementTable(balanceQuarters, "balance_sheet", "ANNUAL");
    const assets = row(view!, "Total Assets");
    // A balance sheet is a stock variable: the latest reported quarter IS the
    // most recent balance sheet. With 5 quarters → 2 snapshots (MRQ + yr-ago).
    expect(assets.values).toEqual([300, 340]);
    // Captions are point-in-time dates — NOT "FY" (no filed annual record).
    expect(view!.columns[1]!.label).toBe("SEP 25");
  });

  it("QUARTERLY mode: one column per quarter (point values)", () => {
    const view = buildStatementTable(balanceQuarters, "balance_sheet", "QUARTERLY");
    expect(view!.columns).toHaveLength(5);
    expect(row(view!, "Total Assets").values).toEqual([300, 310, 320, 330, 340]);
  });
});

// ── Cash flow — ANNUAL fallback labelling (ported) ────────────────────────────

describe("buildStatementTable — cash flow ANNUAL fallback (no annual records)", () => {
  const cfQuarters = [
    ["2024-09-30T00:00:00Z", 10],
    ["2024-12-31T00:00:00Z", 10],
    ["2025-03-31T00:00:00Z", 10],
    ["2025-06-30T00:00:00Z", 10],
    ["2025-09-30T00:00:00Z", 20],
    ["2025-12-31T00:00:00Z", 20],
    ["2026-03-31T00:00:00Z", 20],
    ["2026-06-30T00:00:00Z", 20],
  ].map(([end, ocf]) =>
    rec("cash_flow", "QUARTERLY", end as string, {
      totalCashFromOperatingActivities: ocf,
    }),
  );

  it("sums non-overlapping 4-quarter windows and labels them as quarter-sums", () => {
    const view = buildStatementTable(cfQuarters, "cash_flow", "ANNUAL");
    const ocf = row(view!, "Operating CF");
    expect(ocf.values).toEqual([40, 80]); // two complete windows, oldest first
    expect(ocf.yoyPct).toBeCloseTo(1.0);
    // Captions must NOT claim "FY" filed figures — these are quarter sums.
    for (const col of view!.columns) {
      expect(col.label).toMatch(/^4Q TO /);
    }
  });

  it("drops incomplete leading windows (never a 3-quarter 'year')", () => {
    const view = buildStatementTable(cfQuarters.slice(1), "cash_flow", "ANNUAL");
    // 7 quarters → only ONE complete trailing window.
    expect(view!.columns).toHaveLength(1);
    expect(latest(row(view!, "Operating CF"))).toBe(80);
  });
});

// ── No-data sentinel (ported) ─────────────────────────────────────────────────

describe("buildStatementTable — section with zero records", () => {
  it("returns null so the section renders the named empty state", () => {
    expect(buildStatementTable([], "balance_sheet", "ANNUAL")).toBeNull();
    expect(buildStatementTable(undefined, "cash_flow", "TTM")).toBeNull();
  });
});

// ── Unit scaling (new in Wave-2) ─────────────────────────────────────────────

describe("deriveUnit — shared per-table magnitude", () => {
  function rowsWithMax(maxAbs: number): StatementRowView[] {
    return [{ label: "X", values: [maxAbs, 1], yoyPct: null, spark: null }];
  }

  it("picks billions / millions / thousands / raw by the largest magnitude", () => {
    expect(deriveUnit(rowsWithMax(394e9))).toEqual({ label: "USD B", divisor: 1e9 });
    expect(deriveUnit(rowsWithMax(87e6))).toEqual({ label: "USD M", divisor: 1e6 });
    expect(deriveUnit(rowsWithMax(5e3))).toEqual({ label: "USD K", divisor: 1e3 });
    expect(deriveUnit(rowsWithMax(12))).toEqual({ label: "USD", divisor: 1 });
  });

  it("uses absolute magnitude (negative FCF still scales the table)", () => {
    expect(deriveUnit(rowsWithMax(-2e9))).toEqual({ label: "USD B", divisor: 1e9 });
  });

  it("flows into buildStatementTable views", () => {
    const records = quarterlyIncome([
      ["2026-03-31T00:00:00Z", 50e9],
      ["2026-06-30T00:00:00Z", 60e9],
    ]);
    const view = buildStatementTable(records, "income_statement", "QUARTERLY");
    expect(view!.unit).toEqual({ label: "USD B", divisor: 1e9 });
  });
});

// ── Sparkline series (new in Wave-2, scope item 3) ────────────────────────────

describe("buildStatementTable — quarterly sparkline series", () => {
  it("attaches a dense quarterly series to flagged rows in ANY mode", () => {
    const view = buildStatementTable(EIGHT_QUARTERS, "income_statement", "TTM");
    const revenue = row(view!, "Revenue");
    // Trend is always the QUARTERLY series (scope item 3) even in TTM mode.
    expect(revenue.spark).toEqual([90, 110, 100, 100, 120, 140, 120, 120]);
  });

  it("leaves spark null on rows not flagged for trends", () => {
    const view = buildStatementTable(EIGHT_QUARTERS, "income_statement", "ANNUAL");
    expect(row(view!, "Gross Profit").spark).toBeNull();
  });

  it("leaves spark null when fewer than 2 quarterly points exist", () => {
    const one = quarterlyIncome([["2026-06-30T00:00:00Z", 100]]);
    const view = buildStatementTable(one, "income_statement", "QUARTERLY");
    expect(row(view!, "Revenue").spark).toBeNull();
  });
});

// ── quarterLabel helper ───────────────────────────────────────────────────────

describe("quarterLabel", () => {
  it("maps period-end months to calendar quarters", () => {
    expect(quarterLabel("2026-03-31T00:00:00Z")).toBe("Q1'26");
    expect(quarterLabel("2025-12-31")).toBe("Q4'25");
    expect(quarterLabel(undefined)).toBe("—");
  });
});
