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

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_COLUMNS,
  loadColumnPrefs,
  SCREENER_COLUMNS_KEY,
} from "@/lib/screener-columns";

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

// ── Round-4 item 1: corrupted localStorage prefs heal on read ────────────────
//
// WHY THIS BLOCK: loadColumnPrefs() has always healed corrupt storage (try/
// catch + Array guard + per-entry shape checks + ESSENTIAL coercion), but
// none of that was pinned by tests — a refactor could silently drop a guard
// and the screener would crash at mount for any user with a stale/corrupt
// "worldview:screenerColumns:v1" key. These tests verify each healing path.

describe("loadColumnPrefs — corrupted localStorage healing (Round 4)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  /** The full default catalogue, as loadColumnPrefs returns it with no storage. */
  function defaults() {
    window.localStorage.removeItem(SCREENER_COLUMNS_KEY);
    return loadColumnPrefs();
  }

  it("returns defaults (no throw) for syntactically invalid JSON", () => {
    window.localStorage.setItem(SCREENER_COLUMNS_KEY, "{not valid json!!");
    expect(loadColumnPrefs()).toEqual(defaults());
  });

  it("returns defaults for valid JSON that is not an array", () => {
    window.localStorage.setItem(SCREENER_COLUMNS_KEY, JSON.stringify({ key: "ticker" }));
    expect(loadColumnPrefs()).toEqual(defaults());
  });

  it("skips garbage entries (null / non-object / numeric key) but keeps valid ones", () => {
    window.localStorage.setItem(
      SCREENER_COLUMNS_KEY,
      JSON.stringify([
        null,                       // garbage: null entry
        42,                         // garbage: primitive entry
        { key: 123 },               // garbage: non-string key
        { key: "ghostColumn" },     // dropped: key no longer in DEFAULT_COLUMNS
        { key: "pe", visible: false }, // valid: user hid P/E
      ]),
    );
    const cols = loadColumnPrefs();
    // No garbage leaked into the result…
    expect(cols.every((c) => typeof c.key === "string")).toBe(true);
    expect(cols.find((c) => c.key === "ghostColumn")).toBeUndefined();
    // …the valid user choice survived…
    expect(cols.find((c) => c.key === "pe")?.visible).toBe(false);
    // …and every default column is still present (merge-with-defaults).
    expect(cols.length).toBe(DEFAULT_COLUMNS.length);
  });

  it("coerces ESSENTIAL columns (ticker/name) back to visible from stale prefs", () => {
    // Prefs written BEFORE the Round-2 non-hideable rule could carry
    // visible:false for ticker — healing on READ means no migration needed.
    window.localStorage.setItem(
      SCREENER_COLUMNS_KEY,
      JSON.stringify([
        { key: "ticker", visible: false },
        { key: "name", visible: false },
      ]),
    );
    const cols = loadColumnPrefs();
    expect(cols.find((c) => c.key === "ticker")?.visible).toBe(true);
    expect(cols.find((c) => c.key === "name")?.visible).toBe(true);
  });
});
