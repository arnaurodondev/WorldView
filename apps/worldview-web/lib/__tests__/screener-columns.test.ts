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
  SCORE_HIDDEN_MIGRATION_KEY,
} from "@/lib/screener-columns";

describe("screener-columns DEFAULT_COLUMNS", () => {
  // ── §6.3 density-cap regression guard ──────────────────────────────────────
  // WHY a hard equality (not "≤ 14"): it forces an intentional decision on
  // every change. If you need to ship a new default-visible column, drop an
  // existing one in the same PR and update this number with rationale in the
  // commit body.
  // WHY 13 (was 14, Wave-2 2026-06-10): the SCORE column was demoted to
  // opt-in because market_impact_score has NO backend data source (the column
  // rendered "—" on 100% of rows). The cap REMAINS ≤14 — 13 leaves exactly
  // one slot of headroom for the next default-visible column.
  it("exposes exactly 13 default-visible columns (PRD-0089 §6.3 density cap)", () => {
    const visibleCount = DEFAULT_COLUMNS.filter((c) => c.visible).length;
    expect(visibleCount).toBe(13);
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

  // ── Wave-2: SCORE demoted to opt-in (no backend data source) ──────────────
  // Same safety-net pattern as forwardPe: the catalogue entry MUST survive so
  // ColumnSettingsPopover can offer the column once the backend ships
  // market_impact_score data. Deleting it would also orphan any saved column
  // order that includes "score".
  it("retains score as a hidden-by-default opt-in column (Wave-2 — no data source)", () => {
    const score = DEFAULT_COLUMNS.find((c) => c.key === "score");
    expect(score).toBeDefined();
    expect(score?.visible).toBe(false);
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

// ── Wave-2: one-time SCORE-hidden migration ───────────────────────────────────
//
// WHY THIS BLOCK: the SCORE default flipped visible:true → false (no backend
// data source), but loadColumnPrefs keeps the USER's stored `visible` choice
// authoritative by design — so prefs saved under the old default would pin the
// dead column visible forever. The migration coerces it hidden exactly once
// (marker key), after which a deliberate re-enable sticks across reloads.

describe("loadColumnPrefs — Wave-2 score-hidden migration", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it("coerces a stale visible:true score pref to hidden on first read", () => {
    // Simulate prefs written while score defaulted to visible:true.
    window.localStorage.setItem(
      SCREENER_COLUMNS_KEY,
      JSON.stringify([{ key: "score", visible: true }]),
    );
    const cols = loadColumnPrefs();
    expect(cols.find((c) => c.key === "score")?.visible).toBe(false);
    // The migration marker is set so the coercion never re-runs…
    expect(window.localStorage.getItem(SCORE_HIDDEN_MIGRATION_KEY)).not.toBeNull();
    // …and the migrated state is PERSISTED (a session that never opens the
    // popover must still read score-hidden on its next load).
    const persisted = JSON.parse(
      window.localStorage.getItem(SCREENER_COLUMNS_KEY) ?? "[]",
    ) as Array<{ key: string; visible: boolean }>;
    expect(persisted.find((c) => c.key === "score")?.visible).toBe(false);
  });

  it("respects a deliberate post-migration re-enable (marker present → user wins)", () => {
    // The user opted back into score AFTER the migration ran (e.g. backend
    // shipped the data). Their choice must survive every subsequent load.
    window.localStorage.setItem(SCORE_HIDDEN_MIGRATION_KEY, "1");
    window.localStorage.setItem(
      SCREENER_COLUMNS_KEY,
      JSON.stringify([{ key: "score", visible: true }]),
    );
    const cols = loadColumnPrefs();
    expect(cols.find((c) => c.key === "score")?.visible).toBe(true);
  });

  it("sets the marker on a fresh (no stored prefs) load so future re-enables stick", () => {
    expect(window.localStorage.getItem(SCORE_HIDDEN_MIGRATION_KEY)).toBeNull();
    const cols = loadColumnPrefs();
    // Fresh defaults already hide score…
    expect(cols.find((c) => c.key === "score")?.visible).toBe(false);
    // …and the marker is set immediately, so a later save with score:true is
    // never clobbered by the one-time coercion.
    expect(window.localStorage.getItem(SCORE_HIDDEN_MIGRATION_KEY)).not.toBeNull();
  });
});
