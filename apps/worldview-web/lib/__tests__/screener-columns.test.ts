/**
 * screener-columns.test.ts — regression guards for the screener column catalogue.
 *
 * WHY THIS FILE EXISTS (PRD-0089 Wave I-B QA finding #1):
 *   The screener column defaults are easy to nudge upward over time as new
 *   metrics ship — each new column "feels small in isolation" but collectively
 *   they push past the §6.3 density budget (≤14 default-visible columns above
 *   the fold at 1440×900, matching the 240–280 cell target with 20 rows).
 *   Wave I-B QA caught us at 15. This test pins the count so the next column
 *   addition either replaces an existing default or is shipped as opt-in.
 */

import { describe, expect, it } from "vitest";
import { DEFAULT_COLUMNS } from "@/lib/screener-columns";

describe("screener-columns DEFAULT_COLUMNS", () => {
  // ── §6.3 14-cap regression guard ───────────────────────────────────────────
  // WHY 14 exactly (not "≤ 14"): a hard equality is strictly stronger than the
  // PRD bound and forces an intentional decision on every change. If you need
  // to ship a new default-visible column, drop an existing one in the same PR
  // and update this number with rationale in the commit body.
  it("exposes exactly 14 default-visible columns (PRD-0089 §6.3 density cap)", () => {
    const visibleCount = DEFAULT_COLUMNS.filter((c) => c.visible).length;
    expect(visibleCount).toBe(14);
  });

  // ── Opt-in safety net ──────────────────────────────────────────────────────
  // forwardPe was demoted from default-visible to opt-in to hit the 14 cap.
  // It MUST still be present in the catalogue so ColumnSettingsPopover can
  // surface it under "Valuation" — silently dropping the entry would orphan
  // any user who saved a screen including Fwd P/E.
  it("retains forwardPe as a hidden-by-default opt-in column", () => {
    const fwd = DEFAULT_COLUMNS.find((c) => c.key === "forwardPe");
    expect(fwd).toBeDefined();
    expect(fwd?.visible).toBe(false);
  });

  // ── Catalogue uniqueness ───────────────────────────────────────────────────
  // The merge logic in loadColumnPrefs() de-duplicates by key on read, but a
  // duplicate in DEFAULT_COLUMNS itself would silently break the "append new
  // columns to existing users" path. Pin uniqueness here.
  it("has unique column keys", () => {
    const keys = DEFAULT_COLUMNS.map((c) => c.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});
