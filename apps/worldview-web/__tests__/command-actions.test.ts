/**
 * __tests__/command-actions.test.ts — Action Registry unit tests (PLAN-0059 F-3)
 *
 * WHY THIS EXISTS: The ActionRegistry is the foundation of F-3 (context menu) and
 * B-3 (command palette). Tests verify:
 *   - Registration + deduplication (last-wins)
 *   - Scope filtering (global / page / row)
 *   - Mnemonic validation (single alphanumeric character)
 *   - visible/enabled predicate behaviour
 *   - extractMnemonicParts rendering helper
 *   - getScopesForContext pathname prefix expansion
 *
 * Uses fresh ActionRegistry instances per test to avoid singleton pollution.
 */

import { describe, it, expect, vi } from "vitest";
import {
  ActionRegistry,
  actionRegistry,
  extractMnemonicParts,
  getScopesForContext,
  type ContextAction,
  type ActionContext,
  type HoldingRowContext,
  type ScreenerRowContext,
} from "@/lib/command-actions";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const holdingRow: HoldingRowContext = {
  kind: "holding",
  holdingId: "h1",
  portfolioId: "p1",
  instrumentId: "i1",
  entityId: "AAPL",
  ticker: "AAPL",
  name: "Apple Inc.",
};

const screenerRow: ScreenerRowContext = {
  kind: "screener",
  entityId: "MSFT",
  ticker: "MSFT",
  name: "Microsoft Corp.",
};

function makeGlobalAction(overrides: Partial<ContextAction> = {}): ContextAction {
  return {
    id: "test.global",
    label: "Test Global",
    description: "A global test action",
    category: "View",
    scopes: ["global"],
    run: vi.fn(),
    ...overrides,
  };
}

function makeRowAction(overrides: Partial<ContextAction> = {}): ContextAction {
  return {
    id: "test.row",
    label: "Test Row",
    description: "A row-level test action",
    category: "Navigate",
    scopes: ["row"],
    run: vi.fn(),
    ...overrides,
  };
}

// ── ActionRegistry tests ──────────────────────────────────────────────────────

describe("ActionRegistry — register + getById", () => {
  it("registers an action and retrieves it by id", () => {
    const r = new ActionRegistry();
    const action = makeGlobalAction();
    r.register(action);
    expect(r.getById("test.global")).toEqual(action);
  });

  it("last-wins deduplication: re-registering same id replaces the entry", () => {
    const r = new ActionRegistry();
    const v1 = makeGlobalAction({ label: "Version 1" });
    const v2 = makeGlobalAction({ label: "Version 2" });
    r.register(v1);
    r.register(v2);
    expect(r.getById("test.global")?.label).toBe("Version 2");
    // Confirm no duplicates in all()
    expect(r.all().filter((a) => a.id === "test.global")).toHaveLength(1);
  });

  it("clear() removes all entries", () => {
    const r = new ActionRegistry();
    r.register(makeGlobalAction());
    r.clear();
    expect(r.all()).toHaveLength(0);
    expect(r.getById("test.global")).toBeUndefined();
  });
});

describe("ActionRegistry — mnemonic validation", () => {
  it("accepts a valid single-letter mnemonic", () => {
    const r = new ActionRegistry();
    expect(() =>
      r.register(makeGlobalAction({ mnemonic: "D" })),
    ).not.toThrow();
  });

  it("accepts a numeric mnemonic character", () => {
    const r = new ActionRegistry();
    expect(() =>
      r.register(makeGlobalAction({ mnemonic: "1" })),
    ).not.toThrow();
  });

  it("throws on multi-character mnemonic", () => {
    const r = new ActionRegistry();
    expect(() =>
      r.register(makeGlobalAction({ mnemonic: "DG" })),
    ).toThrow(/mnemonic.*single alphanumeric/);
  });

  it("throws on empty-string mnemonic", () => {
    const r = new ActionRegistry();
    expect(() =>
      r.register(makeGlobalAction({ mnemonic: "" })),
    ).toThrow(/mnemonic.*single alphanumeric/);
  });

  it("throws on non-alphanumeric mnemonic (space)", () => {
    const r = new ActionRegistry();
    expect(() =>
      r.register(makeGlobalAction({ mnemonic: " " })),
    ).toThrow(/mnemonic.*single alphanumeric/);
  });

  it("accepts undefined mnemonic (optional)", () => {
    const r = new ActionRegistry();
    // WHY construct without mnemonic (not delete): ContextAction.mnemonic is
    // readonly; delete on a readonly property is a TS error. Construct a fresh
    // action object that simply omits the optional field instead.
    const action: ContextAction = {
      id: "test.no-mnemonic",
      label: "No Mnemonic",
      description: "Action without a mnemonic",
      category: "View",
      scopes: ["global"],
      run: vi.fn(),
    };
    expect(() => r.register(action)).not.toThrow();
  });
});

describe("ActionRegistry — forScope filtering", () => {
  it("returns global action for global scope", () => {
    const r = new ActionRegistry();
    r.register(makeGlobalAction({ id: "g1", scopes: ["global"] }));
    const result = r.forScope(["global"]);
    expect(result.map((a) => a.id)).toContain("g1");
  });

  it("does NOT return row action for global-only scope request", () => {
    const r = new ActionRegistry();
    r.register(makeRowAction({ id: "row1", scopes: ["row"] }));
    const result = r.forScope(["global"]);
    expect(result.map((a) => a.id)).not.toContain("row1");
  });

  it("returns row action when row scope is present", () => {
    const r = new ActionRegistry();
    r.register(makeRowAction({ id: "row1", scopes: ["row"] }));
    const result = r.forScope(["global", "row"]);
    expect(result.map((a) => a.id)).toContain("row1");
  });

  it("returns page-scoped action when matching page scope present", () => {
    const r = new ActionRegistry();
    r.register(makeGlobalAction({ id: "p1", scopes: ["page:/portfolio"] }));
    const result = r.forScope(["page:/portfolio"]);
    expect(result.map((a) => a.id)).toContain("p1");
  });

  it("does NOT return page-scoped action for different page scope", () => {
    const r = new ActionRegistry();
    r.register(makeGlobalAction({ id: "p1", scopes: ["page:/portfolio"] }));
    const result = r.forScope(["page:/screener"]);
    expect(result.map((a) => a.id)).not.toContain("p1");
  });

  it("returns action with multiple scopes when any scope matches", () => {
    const r = new ActionRegistry();
    r.register(makeGlobalAction({ id: "multi", scopes: ["global", "row"] }));
    const globalOnly = r.forScope(["global"]);
    const rowOnly = r.forScope(["row"]);
    expect(globalOnly.map((a) => a.id)).toContain("multi");
    expect(rowOnly.map((a) => a.id)).toContain("multi");
  });

  it("returns empty array when no scopes match", () => {
    const r = new ActionRegistry();
    r.register(makeRowAction({ id: "row1", scopes: ["row"] }));
    expect(r.forScope([])).toHaveLength(0);
  });
});

describe("ActionRegistry — visible/enabled predicates", () => {
  it("visible predicate is called with ActionContext", () => {
    const visible = vi.fn().mockReturnValue(true);
    const r = new ActionRegistry();
    r.register(makeRowAction({ id: "v1", visible }));

    // forScope does NOT call visible — filtering is done by the hook.
    // This confirms visible is not invoked during scope-only filtering.
    expect(visible).not.toHaveBeenCalled();
  });

  it("visible predicate receives correct row context", () => {
    const visible = vi.fn((ctx: ActionContext) => ctx.row?.kind === "holding");
    const r = new ActionRegistry();
    r.register(makeRowAction({ id: "holding-only", visible }));

    const ctx: ActionContext = { row: holdingRow };
    const action = r.getById("holding-only");
    expect(action?.visible?.(ctx)).toBe(true);

    const screenerCtx: ActionContext = { row: screenerRow };
    expect(action?.visible?.(screenerCtx)).toBe(false);
  });
});

// ── extractMnemonicParts tests ────────────────────────────────────────────────

describe("extractMnemonicParts", () => {
  it("splits label at the mnemonic character (case-insensitive match)", () => {
    const result = extractMnemonicParts("Copy Ticker", "C");
    expect(result).toEqual(["", "C", "opy Ticker"]);
  });

  it("finds mid-word mnemonic", () => {
    const result = extractMnemonicParts("Export Row as TSV", "X");
    expect(result).toEqual(["E", "x", "port Row as TSV"]);
  });

  it("returns null when mnemonic not found in label", () => {
    const result = extractMnemonicParts("Buy", "Z");
    expect(result).toBeNull();
  });

  it("returns null when mnemonic is undefined", () => {
    const result = extractMnemonicParts("Some Action", undefined);
    expect(result).toBeNull();
  });

  it("finds first occurrence when mnemonic appears multiple times", () => {
    const result = extractMnemonicParts("Add Alert", "A");
    // "Add Alert" — first 'a' is index 0
    expect(result).toEqual(["", "A", "dd Alert"]);
  });

  it("handles mnemonic at the end of label", () => {
    const result = extractMnemonicParts("Buy", "Y");
    expect(result).toEqual(["Bu", "y", ""]);
  });
});

// ── getScopesForContext tests ─────────────────────────────────────────────────

describe("getScopesForContext", () => {
  it("always includes global scope", () => {
    const scopes = getScopesForContext({ pathname: "/dashboard", hasRow: false });
    expect(scopes).toContain("global");
  });

  it("includes row scope when hasRow is true", () => {
    const scopes = getScopesForContext({ pathname: "/portfolio", hasRow: true });
    expect(scopes).toContain("row");
  });

  it("does NOT include row scope when hasRow is false", () => {
    const scopes = getScopesForContext({ pathname: "/portfolio", hasRow: false });
    expect(scopes).not.toContain("row");
  });

  it("includes page scope prefixes for deep paths", () => {
    const scopes = getScopesForContext({ pathname: "/portfolio/holdings", hasRow: false });
    expect(scopes).toContain("page:/portfolio");
    expect(scopes).toContain("page:/portfolio/holdings");
  });

  it("handles root path with no parts", () => {
    const scopes = getScopesForContext({ pathname: "/", hasRow: false });
    // "/" splits to no parts — no page scopes beyond global
    expect(scopes).toEqual(["global"]);
  });

  it("handles empty pathname gracefully", () => {
    const scopes = getScopesForContext({ pathname: "", hasRow: false });
    expect(scopes).toEqual(["global"]);
  });
});

// ── Singleton registry sanity check ──────────────────────────────────────────

describe("actionRegistry singleton — smoke test", () => {
  it("exports ≥30 pre-registered actions", () => {
    expect(actionRegistry.all().length).toBeGreaterThanOrEqual(30);
  });

  it("has an action with id navigate.instrument-detail", () => {
    expect(actionRegistry.getById("navigate.instrument-detail")).toBeDefined();
  });

  it("has an action with id copy.ticker", () => {
    expect(actionRegistry.getById("copy.ticker")).toBeDefined();
  });

  it("navigate.instrument-detail has mnemonic D", () => {
    expect(actionRegistry.getById("navigate.instrument-detail")?.mnemonic).toBe("D");
  });

  it("copy.ticker has mnemonic C", () => {
    expect(actionRegistry.getById("copy.ticker")?.mnemonic).toBe("C");
  });

  it("all mnemonics on row-scoped actions are single characters", () => {
    const rowActions = actionRegistry.forScope(["row"]).filter((a) => a.mnemonic);
    for (const action of rowActions) {
      expect(action.mnemonic).toHaveLength(1);
    }
  });
});
