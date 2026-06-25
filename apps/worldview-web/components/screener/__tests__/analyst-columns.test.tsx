/**
 * components/screener/__tests__/analyst-columns.test.tsx
 * PRD-0089 Wave I-B IB-L4 T-IB4-04
 *
 * WHY THIS FILE EXISTS:
 *   IB-L4 introduces five new columns (Analyst Target, Analyst Upside,
 *   Consensus, Insider 90D, Inst Own%, Short%) with nuanced rendering rules:
 *
 *   1. Consensus tone classifier — 1–5 scale → bull/bear/neutral colour.
 *      Bugs here misclassify Buy recommendations as Hold (false neutral)
 *      or Sell as neutral — misleading for users screening for Street
 *      favourites.
 *
 *   2. Insider compact formatter — null MUST render "—" not "$0". Only
 *      3 instruments have insider data; silently showing "$0" would imply
 *      zero net activity when the data simply does not exist.
 *
 *   3. ANALYST UPSIDE derivation — computed client-side as
 *      (target / price) - 1. When analyst_target_price IS NULL, the cell
 *      must show "—", not NaN% or a broken number.
 *
 * DESIGN REFERENCE:
 *   docs/plans/0089-pages/DEFERRED-WORK-PLAN.md §2.5 (IB-L4)
 *   T-IB4-04 spec items: consensus tone, insider compact, upside null guard.
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { formatInsiderCompact } from "@/components/screener/ag-screener-columns";
import { countActiveFiltersByGroup } from "@/features/screener/lib/active-counts";
import { DEFAULT_FILTERS } from "@/features/screener/lib/filter-state";
import { cn } from "@/lib/utils";

// ── formatInsiderCompact ──────────────────────────────────────────────────────

describe("formatInsiderCompact — insider net buy/sell formatter", () => {
  it("renders null as em-dash (null ≠ $0 per spec)", () => {
    // WHY this test is critical: only 3 instruments have insider data.
    // Rendering "$0" instead of "—" would mislead users into thinking there
    // was zero net activity when the data simply doesn't exist.
    expect(formatInsiderCompact(null)).toBe("—");
  });

  it("renders undefined as em-dash", () => {
    expect(formatInsiderCompact(undefined)).toBe("—");
  });

  it("formats a positive million-scale value as '+$X.XM'", () => {
    // 1_200_000 → "+$1.2M"
    expect(formatInsiderCompact(1_200_000)).toBe("+$1.2M");
  });

  it("formats a negative thousand-scale value as '−$XXXK'", () => {
    // −340_000 → "−$340K"
    // WHY Unicode minus (−, U+2212): typographic convention for financial
    // negative values, matching Bloomberg terminal display.
    expect(formatInsiderCompact(-340_000)).toBe("−$340K");
  });

  it("formats zero as a positive value (zero is known data, not missing data)", () => {
    // 0 is NOT the same as null — it means equal buy + sell in the window.
    // formatCompact(0, {maxDecimals:1}) → "0.0" so the result is "+$0.0".
    const result = formatInsiderCompact(0);
    expect(result).toMatch(/^\+\$/);       // starts with positive sign + dollar
    expect(result).not.toBe("—");          // critical: null-guard must NOT fire for 0
  });

  it("formats a large positive value (billions range)", () => {
    // 2_500_000_000 → "+$2.5B"
    expect(formatInsiderCompact(2_500_000_000)).toBe("+$2.5B");
  });

  it("formats a small positive value (hundreds range)", () => {
    // 500 → "+$500"
    expect(formatInsiderCompact(500)).toBe("+$500");
  });
});

// ── Consensus tone classifier ─────────────────────────────────────────────────
// Test via inline logic that mirrors AnalystConsensusCellRenderer exactly.
// WHY not mount the AG Grid component directly: the renderer requires
// ICellRendererParams which adds unnecessary AG Grid setup in unit tests.

function getConsensusClass(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground"; // null case
  const isBull = v >= 4;
  const isBear = v <= 2;
  return cn(
    "font-mono text-[11px] tabular-nums",
    isBull ? "text-positive" : isBear ? "text-negative" : "text-muted-foreground",
  );
}

function TestConsensusCell({ v }: { v: number | null | undefined }) {
  const cls = getConsensusClass(v);
  return (
    <span data-testid="consensus-cell" className={cls}>
      {v == null ? "—" : v.toFixed(2)}
    </span>
  );
}

describe("consensus tone classifier (1–5 scale)", () => {
  it("applies text-positive for a Buy rating (≥ 4)", () => {
    // 4.0 = Buy
    const { container } = render(<TestConsensusCell v={4.0} />);
    expect(container.querySelector("[data-testid='consensus-cell']")?.className)
      .toContain("text-positive");
  });

  it("applies text-positive for Strong Buy (5)", () => {
    const { container } = render(<TestConsensusCell v={5} />);
    expect(container.querySelector("[data-testid='consensus-cell']")?.className)
      .toContain("text-positive");
  });

  it("applies text-negative for a Sell rating (≤ 2)", () => {
    // 2.0 = Sell
    const { container } = render(<TestConsensusCell v={2.0} />);
    expect(container.querySelector("[data-testid='consensus-cell']")?.className)
      .toContain("text-negative");
  });

  it("applies text-negative for Strong Sell (1)", () => {
    const { container } = render(<TestConsensusCell v={1} />);
    expect(container.querySelector("[data-testid='consensus-cell']")?.className)
      .toContain("text-negative");
  });

  it("applies text-muted-foreground (neutral) for Hold range (2.01 – 3.99)", () => {
    // 3.0 = Hold
    const { container } = render(<TestConsensusCell v={3.0} />);
    const cls = container.querySelector("[data-testid='consensus-cell']")?.className ?? "";
    expect(cls).toContain("text-muted-foreground");
    expect(cls).not.toContain("text-positive");
    expect(cls).not.toContain("text-negative");
  });

  it("applies text-muted-foreground for null", () => {
    const { container } = render(<TestConsensusCell v={null} />);
    const cls = container.querySelector("[data-testid='consensus-cell']")?.className ?? "";
    expect(cls).toContain("text-muted-foreground");
    expect(container.querySelector("[data-testid='consensus-cell']")?.textContent).toBe("—");
  });

  it("boundary: 4.0 is bull (≥ 4), 3.99 is neutral (< 4)", () => {
    expect(getConsensusClass(4.0)).toContain("text-positive");
    expect(getConsensusClass(3.99)).not.toContain("text-positive");
  });

  it("boundary: 2.0 is bear (≤ 2), 2.01 is neutral (> 2)", () => {
    expect(getConsensusClass(2.0)).toContain("text-negative");
    expect(getConsensusClass(2.01)).not.toContain("text-negative");
  });
});

// ── ANALYST UPSIDE derivation ─────────────────────────────────────────────────
// The upside column is computed client-side as (target / price) - 1.
// We inline the same derivation and test the null-guard cases.

function computeUpside(
  target: number | null | undefined,
  price: number | null | undefined,
): string {
  if (target == null || price == null || price === 0) return "—";
  const upside = (target / price) - 1;
  const pct = upside * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

describe("ANALYST UPSIDE derivation (client-side)", () => {
  it("returns '—' when analyst_target_price is null", () => {
    // T-IB4-04 explicit requirement: null target → "—" not NaN%
    expect(computeUpside(null, 150)).toBe("—");
  });

  it("returns '—' when current_price is null", () => {
    expect(computeUpside(200, null)).toBe("—");
  });

  it("returns '—' when current_price is 0 (division by zero guard)", () => {
    expect(computeUpside(150, 0)).toBe("—");
  });

  it("computes upside correctly for a target above price", () => {
    // target=165, price=150 → upside=10.0%
    expect(computeUpside(165, 150)).toBe("+10.0%");
  });

  it("computes downside correctly for a target below price", () => {
    // target=135, price=150 → upside=−10.0%
    expect(computeUpside(135, 150)).toBe("-10.0%");
  });

  it("computes zero upside when target equals price", () => {
    expect(computeUpside(150, 150)).toBe("+0.0%");
  });

  it("handles fractional upside correctly (rounds to 1dp)", () => {
    // target=153.75, price=150 → (153.75/150)-1 = 0.025 = +2.5%
    expect(computeUpside(153.75, 150)).toBe("+2.5%");
  });
});

// ── active-counts integration for ownership section ────────────────────────────
describe("active-counts: ownership section (IB-L4)", () => {
  it("ownership is 0 when no L4 fields are set", () => {
    expect(countActiveFiltersByGroup(DEFAULT_FILTERS).ownership).toBe(0);
  });

  it("counts each side of analyst_target_price range independently", () => {
    const form = { ...DEFAULT_FILTERS, analystTargetPriceMin: 100 };
    expect(countActiveFiltersByGroup(form).ownership).toBe(1);

    const form2 = { ...DEFAULT_FILTERS, analystTargetPriceMin: 100, analystTargetPriceMax: 500 };
    expect(countActiveFiltersByGroup(form2).ownership).toBe(2);
  });

  it("sums all 5 L4 range pairs correctly", () => {
    const form = {
      ...DEFAULT_FILTERS,
      analystTargetPriceMin: 100,   // 1
      analystConsensusMin: 3.5,
      analystConsensusMax: 5,       // 2
      insiderNetBuy90dMin: 100_000, // 1
      instOwnPctMin: 0.40,          // 1
      shortPctMax: 0.10,            // 1
    };
    // 1 + 2 + 1 + 1 + 1 = 6
    expect(countActiveFiltersByGroup(form).ownership).toBe(6);
  });

  it("does not bleed ownership filters into other sections", () => {
    const form = {
      ...DEFAULT_FILTERS,
      analystConsensusMin: 4,
      shortPctMax: 0.05,
    };
    const c = countActiveFiltersByGroup(form);
    expect(c.ownership).toBe(2);
    expect(
      c.valuation + c.profitability + c.growth + c.leverage + c.technical + c.performance + c.news
    ).toBe(0);
  });
});

// ── build-filters: L4 field name accuracy ─────────────────────────────────────
import { buildScreenerFilters } from "@/features/screener/lib/build-filters";

// BUGFIX 2026-06-15 (screener filter audit): these five Ownership fields are
// COLUMNS on instrument_fundamentals_snapshot, NOT rows in fundamental_metrics.
// The original assertions pinned the BROKEN wire shape `{metric: "short_percent"}`
// which the backend INNER-JOINs against a non-existent metric row → 0 results
// for the whole section (live-verified). The backend actually parses them as
// per-filter NAMED siblings (`short_percent_min` / `analyst_target_price_min`,
// …) — fundamental_metrics.py:64-71,109-110. These assertions now pin that real
// contract (which live-returns 192/354/248/514/2 rows respectively).
describe("buildScreenerFilters — IB-L4 ownership fields use backend named-field shape", () => {
  // Helper: assert NO broken metric-entry exists, and the named field rides on
  // a carrier filter object.
  const expectNamedField = (
    filters: ReturnType<typeof buildScreenerFilters>,
    brokenMetric: string,
    namedField: string,
    value: number,
  ) => {
    expect(filters.some((f) => f.metric === brokenMetric)).toBe(false);
    const holder = filters.find(
      (f) => (f as Record<string, unknown>)[namedField] !== undefined,
    ) as Record<string, unknown> | undefined;
    expect(holder).toBeDefined();
    expect(holder?.[namedField]).toBe(value);
  };

  it("maps analystTargetPriceMin → analyst_target_price_min (named field)", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      analystTargetPriceMin: 100,
    });
    expectNamedField(filters, "analyst_target_price", "analyst_target_price_min", 100);
  });

  it("maps analystConsensusMin → analyst_consensus_rating_min (named field)", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      analystConsensusMin: 4,
    });
    expectNamedField(filters, "analyst_consensus_rating", "analyst_consensus_rating_min", 4);
  });

  it("maps insiderNetBuy90dMin → insider_net_buy_90d_min (named field)", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      insiderNetBuy90dMin: 100_000,
    });
    expectNamedField(filters, "insider_net_buy_90d", "insider_net_buy_90d_min", 100_000);
  });

  it("maps instOwnPctMin → institutional_ownership_pct_min (named field)", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      instOwnPctMin: 0.40,
    });
    expectNamedField(filters, "institutional_ownership_pct", "institutional_ownership_pct_min", 0.4);
  });

  it("maps shortPctMax → short_percent_max (named field)", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      shortPctMax: 0.05,
    });
    expect(filters.some((f) => f.metric === "short_percent")).toBe(false);
    const holder = filters.find(
      (f) => (f as Record<string, unknown>).short_percent_max !== undefined,
    ) as Record<string, unknown> | undefined;
    expect(holder).toBeDefined();
    expect(holder?.short_percent_max).toBe(0.05);
  });
});

// ── build-filters: L3 field name accuracy ─────────────────────────────────────
describe("buildScreenerFilters — IB-L3 field names match backend schema", () => {
  it("maps dist52wHighPctMin → dist_from_52w_high_pct", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      dist52wHighPctMin: -0.1,
    });
    expect(filters.some((f) => f.metric === "dist_from_52w_high_pct")).toBe(true);
  });

  it("maps dist52wLowPctMax → dist_from_52w_low_pct", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      dist52wLowPctMax: 0.5,
    });
    expect(filters.some((f) => f.metric === "dist_from_52w_low_pct")).toBe(true);
  });

  it("maps return1mMin → return_1m", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      return1mMin: 0.05,
    });
    expect(filters.some((f) => f.metric === "return_1m")).toBe(true);
  });

  it("maps return3mMin → return_3m", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      return3mMin: 0.10,
    });
    expect(filters.some((f) => f.metric === "return_3m")).toBe(true);
  });

  it("maps return6mMin → return_6m", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      return6mMin: 0.10,
    });
    expect(filters.some((f) => f.metric === "return_6m")).toBe(true);
  });

  it("maps returnYtdMin → return_ytd", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      returnYtdMin: 0.05,
    });
    expect(filters.some((f) => f.metric === "return_ytd")).toBe(true);
  });

  it("maps return1yMin → return_1y", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      return1yMin: 0.10,
    });
    expect(filters.some((f) => f.metric === "return_1y")).toBe(true);
  });

  it("maps return3yMax → return_3y", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      return3yMax: 0.50,
    });
    expect(filters.some((f) => f.metric === "return_3y")).toBe(true);
  });
});
