/**
 * lib/portfolio/__tests__/holdings-column-groups.test.ts — PLAN-0122 W-E (T-A-E-01).
 *
 * Guards the Core/Portfolio/Advanced group membership (PRD §6.7), the locked
 * anchors (ticker + actions), the divYld self-hidden carve-out, the visibility
 * partition maths, and the localStorage round-trip (corrupt/absent → default).
 *
 * WHY it also cross-checks the ColDef array: the AG-Grid ColDef `group` field and
 * this module's COLUMN_GROUPS map must agree, and EVERY colId must be assigned to
 * exactly one group (no orphan) — the #1 risk when a future column is added.
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  COLUMN_GROUPS,
  LOCKED_COL_IDS,
  SELF_HIDDEN_COL_IDS,
  HOLDINGS_COL_GROUPS_KEY,
  ADVANCED_GROUP_DEFAULT,
  SIMPLE_GROUPS,
  colIdsForGroups,
  computeGroupVisibility,
  groupStateForMode,
  loadGroupState,
  saveGroupState,
  type HoldingsColGroups,
} from "../holdings-column-groups";
import { holdingsAgColumns } from "@/components/portfolio/ag-holdings-columns";

describe("PLAN-0122 W-E · holdings-column-groups membership (R-24)", () => {
  it("test_column_groups_membership_and_lock: §6.7 groups + locked anchors", () => {
    // Exact membership per PRD §6.7.
    const byGroup = (g: string) =>
      Object.keys(COLUMN_GROUPS)
        .filter((id) => COLUMN_GROUPS[id] === g)
        .sort();
    expect(byGroup("core")).toEqual(
      ["actions", "avg_cost", "current", "pnl", "qty", "ticker", "value"].sort(),
    );
    expect(byGroup("portfolio")).toEqual(
      ["dayChange", "dayChangePct", "name", "pnlPct", "weight"].sort(),
    );
    expect(byGroup("advanced")).toEqual(
      ["asset", "divYld", "sector", "spark"].sort(),
    );
    // ticker + actions are the locked-visible anchors.
    expect([...LOCKED_COL_IDS].sort()).toEqual(["actions", "ticker"]);
    // divYld is the only self-hidden column.
    expect([...SELF_HIDDEN_COL_IDS]).toEqual(["divYld"]);
  });

  it("every ColDef colId is mapped to a group and no colId is orphaned", () => {
    // The ColDef array and COLUMN_GROUPS must be in 1:1 agreement — this is the
    // guard that a newly-added column is consciously grouped (never dropped).
    const colDefIds = holdingsAgColumns.map((c) => c.colId!).sort();
    const groupIds = Object.keys(COLUMN_GROUPS).sort();
    expect(groupIds).toEqual(colDefIds);
    // And each ColDef's own `group` field matches the map (locality vs source).
    for (const col of holdingsAgColumns) {
      expect(
        col.group,
        `ColDef "${col.colId}" group must match COLUMN_GROUPS`,
      ).toBe(COLUMN_GROUPS[col.colId!]);
    }
  });

  it("test_colids_for_groups: union of enabled groups only", () => {
    // {core, portfolio} → core + portfolio colIds, NO advanced ones.
    const ids = colIdsForGroups({ core: true, portfolio: true, advanced: false });
    expect(ids).toContain("qty"); // core
    expect(ids).toContain("name"); // portfolio
    expect(ids).not.toContain("spark"); // advanced (excluded)
    expect(ids).not.toContain("divYld"); // advanced (excluded)
    // Core-only → exactly the 7 core colIds.
    expect(colIdsForGroups(SIMPLE_GROUPS).sort()).toEqual(
      ["actions", "avg_cost", "current", "pnl", "qty", "ticker", "value"].sort(),
    );
  });

  it("core is coerced on even when a caller passes core:false", () => {
    const ids = colIdsForGroups({ core: false, portfolio: false, advanced: false });
    expect(ids).toContain("ticker");
    expect(ids).toContain("actions");
  });
});

describe("PLAN-0122 W-E · computeGroupVisibility partition", () => {
  it("Advanced default shows every column except divYld (today's layout)", () => {
    const { show, hide } = computeGroupVisibility(ADVANCED_GROUP_DEFAULT);
    // Locked anchors never appear in either list (table force-shows them).
    expect(show).not.toContain("ticker");
    expect(show).not.toContain("actions");
    // Every non-locked, non-divYld column is shown.
    expect(show.sort()).toEqual(
      [
        "name", "dayChange", "dayChangePct", "pnlPct", "weight",
        "spark", "sector", "asset", "qty", "avg_cost", "current", "value", "pnl",
      ].sort(),
    );
    // divYld is never force-shown; with Advanced ON it is left alone (not hidden).
    expect(show).not.toContain("divYld");
    expect(hide).not.toContain("divYld");
  });

  it("Portfolio off hides its columns; Core stays shown", () => {
    const { show, hide } = computeGroupVisibility({
      core: true,
      portfolio: false,
      advanced: true,
    });
    for (const id of ["name", "dayChange", "dayChangePct", "pnlPct", "weight"]) {
      expect(hide).toContain(id);
      expect(show).not.toContain(id);
    }
    // Core still shown.
    expect(show).toContain("qty");
  });

  it("Advanced off hides its columns AND divYld", () => {
    const { hide } = computeGroupVisibility(SIMPLE_GROUPS);
    for (const id of ["spark", "sector", "asset", "divYld"]) {
      expect(hide).toContain(id);
    }
  });
});

describe("PLAN-0122 W-E · groupStateForMode (R-26)", () => {
  it("simple always forces Core-only regardless of saved state", () => {
    expect(groupStateForMode("simple", ADVANCED_GROUP_DEFAULT)).toEqual(SIMPLE_GROUPS);
  });
  it("advanced uses the provided saved state", () => {
    const saved: HoldingsColGroups = { core: true, portfolio: false, advanced: true };
    expect(groupStateForMode("advanced", saved)).toEqual(saved);
  });
});

describe("PLAN-0122 W-E · persistence round-trip (R-25)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("test_load_group_state_corrupt_falls_back: absent/corrupt → Advanced default", () => {
    // Absent.
    expect(loadGroupState()).toEqual(ADVANCED_GROUP_DEFAULT);
    // Corrupt JSON.
    window.localStorage.setItem(HOLDINGS_COL_GROUPS_KEY, "{not-json");
    expect(loadGroupState()).toEqual(ADVANCED_GROUP_DEFAULT);
    // Wrong shape (not an object).
    window.localStorage.setItem(HOLDINGS_COL_GROUPS_KEY, "42");
    expect(loadGroupState()).toEqual(ADVANCED_GROUP_DEFAULT);
  });

  it("save→load round-trips the toggle state (core normalised on)", () => {
    saveGroupState({ core: true, portfolio: false, advanced: true });
    expect(loadGroupState()).toEqual({ core: true, portfolio: false, advanced: true });
    // Even if a caller tries to persist core:false, it is stored as true.
    saveGroupState({ core: false, portfolio: true, advanced: false });
    const raw = JSON.parse(window.localStorage.getItem(HOLDINGS_COL_GROUPS_KEY)!);
    expect(raw.core).toBe(true);
    expect(loadGroupState()).toEqual({ core: true, portfolio: true, advanced: false });
  });

  it("a partial saved blob fills missing groups with the default (true)", () => {
    window.localStorage.setItem(
      HOLDINGS_COL_GROUPS_KEY,
      JSON.stringify({ portfolio: false }),
    );
    expect(loadGroupState()).toEqual({ core: true, portfolio: false, advanced: true });
  });
});
