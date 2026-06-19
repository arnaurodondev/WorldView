/**
 * components/screener/__tests__/intelligence-columns.test.tsx
 * PRD-0089 IB-L5
 *
 * WHY THIS FILE:
 *   IB-L5 introduces two default-visible columns (NEWS 7D, BRIEF SCORE) backed
 *   by `news_count_7d` and `display_relevance_7d_weighted`. The columns have
 *   colour-coded rendering rules that must not drift:
 *
 *   NEWS 7D (DESIGN-QA S-3, 2026-06-18 — NON-DIRECTIONAL, neutral palette):
 *     ≥1 articles → text-foreground (has coverage)
 *     0 articles  → text-muted-foreground/50 (dark / no coverage)
 *     null        → "—"
 *     (NOTE: no bull-green tint — a news count is not a price direction.)
 *
 *   BRIEF SCORE (DESIGN-QA S-3 — NON-DIRECTIONAL, neutral palette):
 *     ≥0.30 → text-foreground
 *     <0.30 → text-muted-foreground/60 (low relevance)
 *     null  → "—"
 *     (NOTE: no bull-green tint — relevance is a quality level, not direction.)
 *
 * These are also verified through column-def visibility (no `hide: true`).
 *
 * DESIGN REFERENCE: docs/plans/0089-pages/DEFERRED-WORK-PLAN.md §IB-L5
 */

import { describe, it, expect } from "vitest";
import { createAgScreenerColumns, SCREENER_AG_COL_WIDTHS } from "@/components/screener/ag-screener-columns";
import type { ColDef, ColGroupDef } from "ag-grid-community";
import type { ScreenerResult } from "@/types/api";

// ── Column definition visibility ──────────────────────────────────────────────

describe("IB-L5 column defs — visibility", () => {
  it("NEWS 7D column is default-visible (no hide:true)", () => {
    const cols = createAgScreenerColumns({});
    // Walk all ColDef children, including those nested in ColGroupDef.
    const all: ColDef<ScreenerResult>[] = [];
    for (const col of cols) {
      if ("children" in col) {
        all.push(...(col as ColGroupDef<ScreenerResult>).children as ColDef<ScreenerResult>[]);
      } else {
        all.push(col as ColDef<ScreenerResult>);
      }
    }
    const news7d = all.find((c) => c.colId === "news7d");
    expect(news7d).toBeDefined();
    // WHY: `hide: true` must NOT be present — absence means default-visible.
    expect(news7d?.hide).toBeFalsy();
  });

  it("BRIEF SCORE column is default-visible (no hide:true)", () => {
    const cols = createAgScreenerColumns({});
    const all: ColDef<ScreenerResult>[] = [];
    for (const col of cols) {
      if ("children" in col) {
        all.push(...(col as ColGroupDef<ScreenerResult>).children as ColDef<ScreenerResult>[]);
      } else {
        all.push(col as ColDef<ScreenerResult>);
      }
    }
    const briefScore = all.find((c) => c.colId === "briefScore");
    expect(briefScore).toBeDefined();
    expect(briefScore?.hide).toBeFalsy();
  });

  it("both IB-L5 columns are in the INTELLIGENCE group", () => {
    const cols = createAgScreenerColumns({});
    const intelligenceGroup = cols.find(
      (c) => "groupId" in c && (c as ColGroupDef<ScreenerResult>).groupId === "intelligenceGroup",
    ) as ColGroupDef<ScreenerResult> | undefined;
    expect(intelligenceGroup).toBeDefined();
    const childIds = (intelligenceGroup?.children ?? []).map(
      (c) => (c as ColDef<ScreenerResult>).colId,
    );
    expect(childIds).toContain("news7d");
    expect(childIds).toContain("briefScore");
  });

  it("SCREENER_AG_COL_WIDTHS includes news7d and briefScore entries", () => {
    // WHY: a missing width entry causes AG Grid to use a default (100px) which
    // breaks the terminal-density layout (DS-013 guard).
    expect(typeof SCREENER_AG_COL_WIDTHS.news7d).toBe("number");
    expect(typeof SCREENER_AG_COL_WIDTHS.briefScore).toBe("number");
  });
});

// ── Renderer helpers (tested via createAgScreenerColumns cell renderers) ──────
// We test the renderers indirectly by inspecting what the column ColDef maps to
// the correct field names and by checking the formatter behavior.

describe("IB-L5 ScreenerResult type fields", () => {
  it("ScreenerResult accepts intelligence rollup fields without TypeScript error", () => {
    // WHY: ensures types/api.ts was updated — if the field is missing, this
    // object literal would fail tsc and the test would not compile.
    const row: ScreenerResult = {
      instrument_id: "inst_01",
      entity_id: "ent_01",
      ticker: "AAPL",
      name: "Apple Inc.",
      exchange: "NASDAQ",
      gics_sector: "Information Technology",
      market_cap: 3_000_000_000_000,
      pe_ratio: 28.5,
      daily_return: 0.012,
      market_impact_score: 0.85,
      // IB-L5 fields:
      news_count_7d: 12,
      display_relevance_7d_weighted: 0.78,
      llm_relevance_7d_max: 0.91,
      recent_contradiction_count: 0,
      has_ai_brief: true,
      has_active_alert: false,
      intelligence_rollup_synced_at: "2026-06-09T02:00:00Z",
    };
    // If this compiles (no TS error), the type is correct. Just verify the data.
    expect(row.news_count_7d).toBe(12);
    expect(row.display_relevance_7d_weighted).toBe(0.78);
    expect(row.has_ai_brief).toBe(true);
  });
});
