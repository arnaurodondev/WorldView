/**
 * group-signals.test.ts — unit tests for the pure per-entity grouping logic.
 *
 * WHY a separate pure-function test file: groupSignalsByEntity is the
 * widget's only data transform; testing it without rendering pins the
 * grouping contract (order, top-signal promotion, ticker/name backfill)
 * far more precisely than DOM assertions could.
 */

import { describe, it, expect } from "vitest";

import { groupSignalsByEntity } from "../group-signals";
import type { EnrichedAiSignal } from "../types";

/** Factory — newest-first lists are built by the caller (mirrors S9 order). */
function sig(overrides: Partial<EnrichedAiSignal>): EnrichedAiSignal {
  return {
    signal_id: "sig-1",
    entity_id: "ent-1",
    ticker: "AAPL",
    label: "NEUTRAL",
    score: 0.95,
    article_title: "Some headline",
    created_at: "2026-06-10T12:00:00Z",
    entity_name: "Apple Inc.",
    signal_type: "EARNINGS_RELEASE",
    signal_type_label: "Earnings",
    polarity: "neutral",
    article_url: "https://example.com/a",
    ...overrides,
  };
}

describe("groupSignalsByEntity", () => {
  it("groups multiple signals for the same entity into one group, newest first", () => {
    const groups = groupSignalsByEntity([
      sig({ signal_id: "a", entity_id: "e1" }),
      sig({ signal_id: "b", entity_id: "e1" }),
      sig({ signal_id: "c", entity_id: "e2", ticker: "MSFT" }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0].signals.map((s) => s.signal_id)).toEqual(["a", "b"]);
    expect(groups[1].ticker).toBe("MSFT");
  });

  it("orders groups by each entity's newest signal (input order preserved)", () => {
    const groups = groupSignalsByEntity([
      sig({ signal_id: "newest", entity_id: "e2", ticker: "GILD" }),
      sig({ signal_id: "older", entity_id: "e1" }),
      sig({ signal_id: "oldest", entity_id: "e2", ticker: "GILD" }),
    ]);
    // e2 appeared first (its newest signal is the global newest) → first group.
    expect(groups.map((g) => g.entityId)).toEqual(["e2", "e1"]);
  });

  it("promotes the newest DIRECTIONAL signal to top over an earlier NEUTRAL", () => {
    // GILD live pattern: newest row neutral, older row positive — the
    // collapsed row should lead with the direction we actually know.
    const groups = groupSignalsByEntity([
      sig({ signal_id: "neutral-new", label: "NEUTRAL" }),
      sig({ signal_id: "pos-old", label: "POSITIVE" }),
    ]);
    expect(groups[0].top.signal_id).toBe("pos-old");
  });

  it("never demotes a directional top (first directional seen is the newest)", () => {
    const groups = groupSignalsByEntity([
      sig({ signal_id: "neg-new", label: "NEGATIVE" }),
      sig({ signal_id: "pos-old", label: "POSITIVE" }),
    ]);
    expect(groups[0].top.signal_id).toBe("neg-new");
  });

  it("backfills ticker and name from later rows when the first row lacks them", () => {
    const groups = groupSignalsByEntity([
      sig({ signal_id: "a", ticker: null, entity_name: null }),
      sig({ signal_id: "b", ticker: "AAPL", entity_name: "Apple Inc." }),
    ]);
    expect(groups[0].ticker).toBe("AAPL");
    expect(groups[0].name).toBe("Apple Inc.");
  });

  it("skips rows with no entity_id and returns [] for empty input", () => {
    expect(groupSignalsByEntity([])).toEqual([]);
    expect(groupSignalsByEntity([sig({ entity_id: "" })])).toEqual([]);
  });

  it("handles legacy payloads without enriched fields (no entity_name)", () => {
    // A legacy AiSignal has no entity_name/signal_type — grouping must not throw.
    const legacy = {
      signal_id: "l1",
      entity_id: "e9",
      ticker: null,
      label: "NEUTRAL",
      score: 0.9,
      article_title: null,
      created_at: "2026-06-10T12:00:00Z",
    } as EnrichedAiSignal;
    const groups = groupSignalsByEntity([legacy]);
    expect(groups).toHaveLength(1);
    expect(groups[0].name).toBeNull();
    expect(groups[0].ticker).toBeNull();
  });
});
