/**
 * statementData.test.ts — unit tests for the statement derivation helpers
 * (Round-2 Enhancement, item 2).
 *
 * WHY THESE TESTS: the Annual/TTM windowing + YoY maths is the part of the
 * statements feature where a subtle bug produces a CONFIDENT-LOOKING wrong
 * number (the worst failure class for a finance UI). We pin:
 *   - ANNUAL income: latest vs prior FY + YoY;
 *   - TTM flows: strict 4-quarter sums (and "—" when a window is short);
 *   - balance sheet: MRQ point-in-time vs the year-ago quarter;
 *   - cash-flow ANNUAL fallback (quarterly-only ingestion — the live DB
 *     state) labelled as quarter-sums, never as filed FY figures;
 *   - YoY suppression on missing / non-positive bases;
 *   - string-number coercion (EODHD serialises figures as strings).
 */

import { describe, it, expect } from "vitest";

import {
  buildStatementView,
  safeNum,
  yoy,
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

// ── safeNum / yoy primitives ──────────────────────────────────────────────────

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

describe("buildStatementView — income statement, ANNUAL", () => {
  const records = [
    rec("income_statement", "ANNUAL", "2024-09-30T00:00:00Z", {
      totalRevenue: "100",
      netIncome: 20,
    }),
    rec("income_statement", "ANNUAL", "2025-09-30T00:00:00Z", {
      totalRevenue: "120",
      netIncome: 30,
    }),
    // Decoy quarterly record — must be ignored in ANNUAL mode.
    ...quarterlyIncome([["2026-03-31T00:00:00Z", 999]]),
  ];

  it("uses latest vs prior FY with FY column labels", () => {
    const view = buildStatementView(records, "income_statement", "ANNUAL");
    expect(view).not.toBeNull();
    expect(view!.currentLabel).toBe("FY25");
    expect(view!.priorLabel).toBe("FY24");

    const revenue = view!.rows.find((r) => r.label === "Revenue")!;
    // String "120" must be coerced — not concatenated or dropped.
    expect(revenue.current).toBe(120);
    expect(revenue.prior).toBe(100);
    expect(revenue.yoyPct).toBeCloseTo(0.2);
  });

  it("renders null (em-dash) rows for line items absent from the data", () => {
    const view = buildStatementView(records, "income_statement", "ANNUAL");
    const ebitda = view!.rows.find((r) => r.label === "EBITDA")!;
    expect(ebitda.current).toBeNull();
    expect(ebitda.yoyPct).toBeNull();
  });
});

// ── TTM mode — strict 4-quarter windows ───────────────────────────────────────

describe("buildStatementView — income statement, TTM", () => {
  it("sums the last 4 quarters and compares against quarters 5–8", () => {
    const view = buildStatementView(EIGHT_QUARTERS, "income_statement", "TTM");
    const revenue = view!.rows.find((r) => r.label === "Revenue")!;
    expect(revenue.current).toBe(500); // 120+140+120+120
    expect(revenue.prior).toBe(400); // 90+110+100+100
    expect(revenue.yoyPct).toBeCloseTo(0.25);
    expect(view!.currentLabel).toBe("TTM");
  });

  it("returns null sums when fewer than 4 quarters exist (no partial TTM)", () => {
    const onlyThree = EIGHT_QUARTERS.slice(-3);
    const view = buildStatementView(onlyThree, "income_statement", "TTM");
    const revenue = view!.rows.find((r) => r.label === "Revenue")!;
    expect(revenue.current).toBeNull();
    expect(revenue.prior).toBeNull();
  });

  it("nulls the whole window if ANY quarter is missing the line item", () => {
    const withHole = [
      ...EIGHT_QUARTERS.slice(0, 7),
      rec("income_statement", "QUARTERLY", "2026-06-30T00:00:00Z", { netIncome: 12 }), // no revenue
    ];
    const view = buildStatementView(withHole, "income_statement", "TTM");
    const revenue = view!.rows.find((r) => r.label === "Revenue")!;
    // 3-of-4 quarters would understate the year — must be suppressed.
    expect(revenue.current).toBeNull();
  });
});

// ── Balance sheet — point-in-time semantics ───────────────────────────────────

describe("buildStatementView — balance sheet (quarterly-only ingestion)", () => {
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
    const view = buildStatementView(balanceQuarters, "balance_sheet", "TTM");
    const assets = view!.rows.find((r) => r.label === "Total Assets")!;
    expect(assets.current).toBe(340); // latest quarter — point-in-time
    expect(assets.prior).toBe(300); // same quarter one year earlier
    expect(assets.yoyPct).toBeCloseTo(340 / 300 - 1);
    expect(view!.currentLabel).toContain("MRQ");
  });

  it("ANNUAL mode without annual records: falls back to MRQ snapshot", () => {
    const view = buildStatementView(balanceQuarters, "balance_sheet", "ANNUAL");
    const assets = view!.rows.find((r) => r.label === "Total Assets")!;
    // A balance sheet is a stock variable: the latest reported quarter IS the
    // most recent balance sheet — never summed.
    expect(assets.current).toBe(340);
  });
});

// ── Cash flow — ANNUAL fallback labelling ─────────────────────────────────────

describe("buildStatementView — cash flow ANNUAL fallback (no annual records)", () => {
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

  it("sums 4-quarter fiscal windows and labels them as quarter-sums", () => {
    const view = buildStatementView(cfQuarters, "cash_flow", "ANNUAL");
    const ocf = view!.rows.find((r) => r.label === "Operating CF")!;
    expect(ocf.current).toBe(80);
    expect(ocf.prior).toBe(40);
    expect(ocf.yoyPct).toBeCloseTo(1.0);
    // The caption must NOT claim "FY" filed figures — these are quarter sums.
    expect(view!.currentLabel).toMatch(/^4Q TO /);
  });
});

// ── No-data sentinel ──────────────────────────────────────────────────────────

describe("buildStatementView — section with zero records", () => {
  it("returns null so the panel renders the named empty state", () => {
    expect(buildStatementView([], "balance_sheet", "ANNUAL")).toBeNull();
    expect(buildStatementView(undefined, "cash_flow", "TTM")).toBeNull();
  });
});
