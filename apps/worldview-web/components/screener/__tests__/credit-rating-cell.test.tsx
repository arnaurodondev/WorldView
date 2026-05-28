/**
 * components/screener/__tests__/credit-rating-cell.test.tsx — Vitest
 * for the credit-rating badge cell + creditRatingTone helper
 * (PRD-0089 Wave I-B Block IB-L2, T-IB-07 / T-IB-08).
 *
 * WHY THIS EXISTS:
 *   The credit-rating column drives compliance decisions ("is this issuer
 *   investment grade?") and screen colour ("amber means watch, red means
 *   distressed"). A boundary bug — e.g. classifying BBB- as warning
 *   instead of positive — would silently misrank holdings against fund
 *   investment policies.
 *
 * SCALE BOUNDARIES (S&P long-term):
 *   AAA / AA± / A± / BBB± → INVESTMENT GRADE (positive)
 *   BBB-                  → LOWEST INV GRADE  (positive — boundary)
 *   BB+                   → TOP OF SPECULATIVE (warning — boundary)
 *   BB± / BB-             → SPECULATIVE / JUNK (warning)
 *   B± / CCC± / CC / C / D → DEEP JUNK / DISTRESSED (negative)
 *   B+                    → DEEP JUNK BOUNDARY (negative — boundary)
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { creditRatingTone, CREDIT_RATING_VALUES } from "@/lib/screener/credit-rating";
import { createAgScreenerColumns } from "@/components/screener/ag-screener-columns";
import type { ScreenerResult } from "@/types/api";
import type { ColDef, ColGroupDef, ICellRendererParams } from "ag-grid-community";

// ── Helpers (mirrored from fundamentals-columns.test.tsx) ────────────────────

function flatten(
  defs: (ColDef<ScreenerResult> | ColGroupDef<ScreenerResult>)[],
): ColDef<ScreenerResult>[] {
  const out: ColDef<ScreenerResult>[] = [];
  for (const d of defs) {
    if ("children" in d && Array.isArray(d.children)) {
      out.push(...(d.children as ColDef<ScreenerResult>[]));
    } else {
      out.push(d as ColDef<ScreenerResult>);
    }
  }
  return out;
}

function renderCredit(rating: string | null | undefined) {
  const cols = flatten(createAgScreenerColumns({}, false));
  const col = cols.find((c) => c.colId === "creditRating");
  if (!col?.cellRenderer) throw new Error("creditRating column missing");
  const Renderer = col.cellRenderer as React.ComponentType<
    ICellRendererParams<ScreenerResult>
  >;
  const params = {
    data: { credit_rating: rating } as unknown as ScreenerResult,
  } as ICellRendererParams<ScreenerResult>;
  return render(<Renderer {...params} />);
}

// ── creditRatingTone helper ──────────────────────────────────────────────────

describe("creditRatingTone — tier mapping", () => {
  // ── Investment grade (positive) ─────────────────────────────────────────
  it("AAA → positive", () => {
    expect(creditRatingTone("AAA")).toBe("positive");
  });
  it("AA- → positive", () => {
    expect(creditRatingTone("AA-")).toBe("positive");
  });
  it("BBB- → positive (lowest investment grade — boundary)", () => {
    // BOUNDARY: BBB- is the lowest investment-grade rung. Misclassifying
    // it as warning would force institutional funds to flag every BBB-
    // holding as out-of-policy.
    expect(creditRatingTone("BBB-")).toBe("positive");
  });

  // ── Speculative grade (warning) ─────────────────────────────────────────
  it("BB+ → warning (top of speculative — boundary)", () => {
    // BOUNDARY: BB+ is the FIRST rating below investment grade. The cell
    // colour must escalate from green to amber here.
    expect(creditRatingTone("BB+")).toBe("warning");
  });
  it("BB → warning", () => {
    expect(creditRatingTone("BB")).toBe("warning");
  });
  it("BB- → warning", () => {
    expect(creditRatingTone("BB-")).toBe("warning");
  });

  // ── Deep junk (negative) ─────────────────────────────────────────────────
  it("B+ → negative (deep junk boundary)", () => {
    // BOUNDARY: B+ is below BB- and signals serious credit stress.
    // A naive "starts with B" rule would mis-bucket this as warning.
    expect(creditRatingTone("B+")).toBe("negative");
  });
  it("CCC → negative", () => {
    expect(creditRatingTone("CCC")).toBe("negative");
  });
  it("D → negative (default)", () => {
    expect(creditRatingTone("D")).toBe("negative");
  });

  // ── Defensive cases ──────────────────────────────────────────────────────
  // WHY these assert "muted" (not "negative") — QA #3 fix:
  //   The previous tone for null/empty/undefined was "negative" (red). That
  //   painted unrated instruments as if they were near default — a finance
  //   UX bug that misled compliance triage. The corrected behaviour is to
  //   return a neutral "muted" tone, which the renderer maps to
  //   `text-muted-foreground`. See lib/screener/credit-rating.ts.
  it("null → muted (missing rating is unknown, not distressed)", () => {
    expect(creditRatingTone(null)).toBe("muted");
  });
  it("undefined → muted", () => {
    expect(creditRatingTone(undefined)).toBe("muted");
  });
  it("empty string → muted (backend sent 'no rating on file' sentinel)", () => {
    expect(creditRatingTone("")).toBe("muted");
  });
  it("whitespace-only string → muted (normalises to empty)", () => {
    // Defensive: " " trims to "" — same UX as the empty-string case.
    expect(creditRatingTone("   ")).toBe("muted");
  });
  it("normalises 'aa-' to 'AA-' → positive", () => {
    expect(creditRatingTone("aa-")).toBe("positive");
  });
  it("normalises whitespace: ' BBB+ ' → positive", () => {
    expect(creditRatingTone(" BBB+ ")).toBe("positive");
  });
  it("unknown 'XYZ' → negative", () => {
    expect(creditRatingTone("XYZ")).toBe("negative");
  });
});

// ── CreditRatingCellRenderer ─────────────────────────────────────────────────

describe("CreditRatingCellRenderer — DOM rendering", () => {
  it("renders 'AA-' with positive tone classes", () => {
    const { container } = renderCredit("AA-");
    const span = container.querySelector("span");
    expect(span?.textContent).toBe("AA-");
    expect(span?.className).toMatch(/text-positive/);
    expect(span?.className).toMatch(/bg-positive\/10/);
  });

  it("renders 'BB+' with warning tone classes", () => {
    const { container } = renderCredit("BB+");
    const span = container.querySelector("span");
    expect(span?.textContent).toBe("BB+");
    expect(span?.className).toMatch(/text-warning/);
  });

  it("renders 'CCC' with negative tone classes", () => {
    const { container } = renderCredit("CCC");
    const span = container.querySelector("span");
    expect(span?.textContent).toBe("CCC");
    expect(span?.className).toMatch(/text-negative/);
  });

  it("renders null as the universal '—' missing-data sentinel", () => {
    const { container } = renderCredit(null);
    // Falls through to <_Em /> which uses muted-foreground, NOT a tone tint.
    expect(container.textContent).toBe("—");
    const span = container.querySelector("span");
    expect(span?.className).toMatch(/text-muted-foreground/);
    // QA #3 regression guard: the cell MUST NOT use the negative (red) tone
    // for unrated instruments. Painting unrated bonds red implies distress
    // and misleads compliance triage. See creditRatingTone() doc-comment.
    expect(span?.className).not.toMatch(/text-negative/);
    expect(span?.className).not.toMatch(/bg-negative/);
  });

  it("renders empty string as '—'", () => {
    const { container } = renderCredit("");
    expect(container.textContent).toBe("—");
  });

  it("uses font-mono tabular-nums (column alignment guarantee)", () => {
    const { container } = renderCredit("AA");
    const span = container.querySelector("span");
    expect(span?.className).toMatch(/font-mono/);
    expect(span?.className).toMatch(/tabular-nums/);
  });
});

// ── Rating ladder length sanity ─────────────────────────────────────────────

describe("CREDIT_RATING_VALUES", () => {
  it("exposes the 22-rung S&P ladder AAA→D", () => {
    expect(CREDIT_RATING_VALUES.length).toBe(22);
    expect(CREDIT_RATING_VALUES[0]).toBe("AAA");
    expect(CREDIT_RATING_VALUES[CREDIT_RATING_VALUES.length - 1]).toBe("D");
  });

  it("each rating maps to a tone (no UnreachableRating bugs)", () => {
    for (const r of CREDIT_RATING_VALUES) {
      const tone = creditRatingTone(r);
      // WHY no "muted" allowed here: CREDIT_RATING_VALUES contains only real
      // S&P ratings (AAA..D). "muted" is reserved for null/empty/undefined
      // input — i.e. "the backend told us there's no rating". A concrete
      // rating string must always classify into a tier tone.
      expect(["positive", "warning", "negative"]).toContain(tone);
    }
  });
});
