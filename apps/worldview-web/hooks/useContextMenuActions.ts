/**
 * hooks/useContextMenuActions.ts — Filter + rank context menu actions for current scope
 *
 * WHY THIS EXISTS: The action registry holds ~30 actions covering all six Bloomberg
 * categories. A right-click on a holdings row should only show row-scoped actions
 * (not global navigation). This hook encapsulates the filtering logic, mnemonic
 * collision detection, and group ordering so context menu components stay thin.
 *
 * WHO USES IT: context-menu.tsx (RowContextMenu component) and the B-3 command
 * palette `>action` mode.
 *
 * DATA SOURCE: Client-side only — reads from actionRegistry singleton.
 * DESIGN REFERENCE: Plan 0059 F-3.
 */

"use client";
// WHY "use client": uses usePathname() which is a Next.js client-only hook that
// reads the current browser URL. Cannot be called in Server Components.

import { useMemo } from "react";
import { usePathname } from "next/navigation";
import {
  actionRegistry,
  type ActionContext,
  type ActionCategory,
  type ContextAction,
  type RowContextKind,
  getScopesForContext,
  type ActionRegistry,
} from "@/lib/command-actions";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * CATEGORY_ORDER — display order for context menu sections.
 *
 * WHY this ordering: Navigate (go somewhere) is the most frequent action from
 * a table row. Copy/Export is next (analysts frequently copy tickers). Trade
 * actions are placed after informational actions to reduce accidental clicks.
 * Alert and Watchlist are utility actions placed last.
 */
const CATEGORY_ORDER: ActionCategory[] = [
  "Navigate",
  "Copy/Export",
  "Trade",
  "Alert",
  "Watchlist",
  "View",
];

// ── Types ─────────────────────────────────────────────────────────────────────

export interface GroupedActions {
  category: ActionCategory;
  actions: ContextAction[];
}

export interface UseContextMenuActionsReturn {
  /** Actions grouped by category in display order. Empty groups are omitted. */
  groups: GroupedActions[];
  /** Flat list of all visible + enabled-aware actions (for keyboard nav). */
  flat: ContextAction[];
  /**
   * All mnemonics present in the current action list.
   * The context menu uses this to intercept single-key presses.
   * WHY exposed: the RowContextMenu component needs the full set to wire
   * onKeyDown without re-computing it.
   */
  mnemonicMap: Map<string, ContextAction>;
}

// ── Hook ─────────────────────────────────────────────────────────────────────

/**
 * useContextMenuActions — returns the filtered + ranked action list for the
 * current scope (pathname + optional row context).
 *
 * @param row      The row context if triggered from a table row. Omit for page-level menus.
 * @param registry Override the singleton for testing. Defaults to actionRegistry.
 */
export function useContextMenuActions(
  row?: RowContextKind,
  registry: ActionRegistry = actionRegistry,
): UseContextMenuActionsReturn {
  const pathname = usePathname() ?? "";

  return useMemo(() => {
    const ctx: ActionContext = {
      row,
      // WHY no navigate/toast here: those are passed at call time (when run()
      // is invoked by the menu component), not at filter time. The filter
      // only needs row + pathname to determine visibility.
    };

    const scopes = getScopesForContext({ pathname, hasRow: !!row });

    // 1. Get all actions that match at least one active scope.
    const candidates = registry.forScope(scopes);

    // 2. Filter by visible predicate (default: visible = true).
    const visible = candidates.filter((a) => {
      if (a.visible) return a.visible(ctx);
      return true;
    });

    // 3. Group by category in display order.
    const grouped = new Map<ActionCategory, ContextAction[]>();
    for (const cat of CATEGORY_ORDER) {
      grouped.set(cat, []);
    }
    for (const action of visible) {
      const arr = grouped.get(action.category);
      if (arr) arr.push(action);
      // WHY silently ignore unknown categories: if a future action introduces a
      // new category before CATEGORY_ORDER is updated, it appears nowhere rather
      // than crashing. The test suite will catch this gap before prod.
    }

    const groups: GroupedActions[] = [];
    const flat: ContextAction[] = [];

    for (const cat of CATEGORY_ORDER) {
      const actions = grouped.get(cat) ?? [];
      if (actions.length === 0) continue;
      groups.push({ category: cat, actions });
      flat.push(...actions);
    }

    // 4. Build mnemonic map — last-one-wins on collision (not expected, but safe).
    // WHY Map<string, ContextAction>: the menu's onKeyDown handler looks up by
    // the pressed key character. Map gives O(1) lookup vs iterating flat.
    const mnemonicMap = new Map<string, ContextAction>();
    for (const action of flat) {
      if (action.mnemonic) {
        mnemonicMap.set(action.mnemonic.toLowerCase(), action);
      }
    }

    return { groups, flat, mnemonicMap };
  }, [pathname, row, registry]);
}
