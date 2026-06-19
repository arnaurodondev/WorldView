/**
 * column-catalogue-parity.test.ts — desync guard for the screener column lists.
 *
 * WHY THIS FILE EXISTS (screener-frontend audit §2.5, 2026-06-18):
 *   The screener has TWO column lists that MUST agree:
 *     1. The AG-Grid ColDefs  (components/screener/ag-screener-columns.tsx) —
 *        define which columns actually render + their cell renderers.
 *     2. The DEFAULT_COLUMNS catalogue (lib/screener-columns.ts) — the ONLY list
 *        ColumnSettingsPopover shows the user, and the ONLY set of colIds
 *        page.tsx feeds to gridApi.applyColumnState() to toggle visibility.
 *
 *   They had silently drifted: 16 real ColDefs (all IB-L3/L4/L5 columns plus
 *   revenue + volume) were ABSENT from the catalogue → unreachable via the
 *   popover, and 8 catalogue keys (avgVol, epsTtm, fcf, …) had NO ColDef →
 *   toggling them was a no-op. The audit called this "the highest-leverage fix
 *   in the whole §2 scope".
 *
 *   This test pins the invariant: the set of leaf ColDef colIds MUST EXACTLY
 *   equal the set of catalogue keys. Either drift direction fails loudly here,
 *   so the desync can never silently regress again.
 */

import { describe, expect, it } from "vitest";
import type { ColDef, ColGroupDef } from "ag-grid-community";
import { createAgScreenerColumns } from "@/components/screener/ag-screener-columns";
import { DEFAULT_COLUMNS } from "@/lib/screener-columns";
import type { ScreenerResult } from "@/types/api";

/**
 * collectLeafColIds — walk the factory output (which mixes leaf ColDefs and
 * one-level-deep ColGroupDefs) and return every leaf column's colId.
 *
 * WHY recurse only one level: the screener has no nested groups beyond depth 1
 * (see ag-screener-columns.tsx). A `"children" in def` check distinguishes a
 * group from a leaf — the same discriminator the factory's withNumericAlignment
 * helper uses.
 */
function collectLeafColIds(
  defs: (ColDef<ScreenerResult> | ColGroupDef<ScreenerResult>)[],
): string[] {
  const ids: string[] = [];
  for (const def of defs) {
    if ("children" in def) {
      for (const child of def.children) {
        const leaf = child as ColDef<ScreenerResult>;
        if (leaf.colId) ids.push(leaf.colId);
      }
    } else if (def.colId) {
      ids.push(def.colId);
    }
  }
  return ids;
}

describe("screener column catalogue parity (ColDef ⇔ DEFAULT_COLUMNS)", () => {
  // Build the columns with an empty sparklines map — colIds are independent of
  // the sparkline data, so {} is sufficient for a structural comparison.
  const colDefIds = collectLeafColIds(createAgScreenerColumns({}));
  const catalogueKeys = DEFAULT_COLUMNS.map((c) => c.key);

  it("every AG-Grid ColDef is selectable in the popover catalogue", () => {
    // A ColDef without a catalogue entry is a permanently-hidden dead column
    // (the user can never reveal it). This is the bug the audit flagged for the
    // 16 IB-L3/L4/L5 + revenue + volume columns.
    const missingFromCatalogue = colDefIds.filter((id) => !catalogueKeys.includes(id));
    expect(missingFromCatalogue).toEqual([]);
  });

  it("every popover catalogue key maps to a real ColDef", () => {
    // A catalogue key without a ColDef is a silent no-op toggle (nothing to
    // show/hide). This is the bug the audit flagged for the 8 IB-L2 orphan keys.
    const orphanKeys = catalogueKeys.filter((k) => !colDefIds.includes(k));
    expect(orphanKeys).toEqual([]);
  });

  it("the two column sets are EXACTLY equal (no drift in either direction)", () => {
    // Strongest form of the invariant: order-independent set equality. Sorting
    // both lists makes the failure message show precisely which colIds differ.
    expect([...colDefIds].sort()).toEqual([...catalogueKeys].sort());
  });

  it("has no duplicate colIds in the factory output", () => {
    // A duplicate ColDef colId would break applyColumnState (AG-Grid keys state
    // by colId) and silently corrupt the parity comparison above.
    expect(new Set(colDefIds).size).toBe(colDefIds.length);
  });
});
