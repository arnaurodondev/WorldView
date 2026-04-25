/**
 * contexts/SymbolLinkingContext.tsx — Per-workspace symbol linking for synchronized panels
 *
 * WHY THIS EXISTS: Institutional traders need multiple panels watching the same symbol
 * simultaneously — e.g., a chart, fundamentals panel, and news feed all locked to AAPL.
 * Symbol linking (inspired by Bloomberg's color-coded group links) solves this: panels
 * in the same color group automatically update when any panel in that group changes symbol.
 *
 * WHY SCOPED PER WORKSPACE PAGE (not layout.tsx): Each workspace has independent symbol
 * linking state. The provider lives inside workspace/page.tsx so switching workspaces
 * resets symbol links without polluting the global shell state.
 *
 * HOW IT WORKS:
 *   1. User sets a color on a panel via the color chip in the panel header
 *   2. User changes the symbol in that panel's SymbolSelector
 *   3. setSymbol(color, newSymbol) is called → all panels sharing that color re-read
 *      getSymbol(color) and re-render with the new symbol
 *
 * WHO USES IT: WorkspacePanelContainer (reads color + calls setSymbol on symbol change),
 *              widget components (call getSymbol to know which symbol to display)
 * DATA SOURCE: Internal state only — no S9 calls
 * DESIGN REFERENCE: PRD-0031 §5.3 Symbol linking
 */

"use client";
// WHY "use client": uses React state and context — only available in browser

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

// ── Types ──────────────────────────────────────────────────────────────────────

/**
 * GroupColor — the 5 panel link colors plus null (unlinked).
 * WHY 5 colors: matches Bloomberg Terminal's 5 group link colors — a standard
 * that institutional traders recognize from prior workflows.
 * null = panel is not linked to any group (independent, shows its own symbol).
 */
export type GroupColor = "red" | "green" | "blue" | "yellow" | "purple" | null;

/**
 * GROUP_COLOR_HEX — CSS hex values for the 6px group color chip dots.
 * WHY explicit hex (not Tailwind arbitrary values): Tailwind's class-based purging
 * would strip dynamic `bg-[#EF5350]` values generated at runtime. Inline styles
 * with these hex values are always applied correctly regardless of build.
 */
export const GROUP_COLOR_HEX: Record<NonNullable<GroupColor>, string> = {
  red: "#EF5350",       // --negative (reused for red link group)
  green: "#26A69A",     // --positive (reused for green link group)
  blue: "#3B82F6",      // standard blue (distinct from --primary #FFD60A)
  yellow: "#FFD60A",    // --primary
  purple: "#A855F7",    // violet accent
};

interface SymbolLinkingContextValue {
  /** Get the current symbol for a given group color. Returns undefined for null (unlinked) */
  getSymbol: (color: GroupColor) => string | undefined;
  /** Set the symbol for a given group color — propagates to all panels in that group */
  setSymbol: (color: GroupColor, symbol: string) => void;
}

// ── Context ───────────────────────────────────────────────────────────────────

const SymbolLinkingContext = createContext<SymbolLinkingContextValue | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────────

export function SymbolLinkingProvider({ children }: { children: ReactNode }) {
  // WHY Map<string, string>: GroupColor→symbol mapping. Map handles the closed
  // set of 5 colors cleanly — get/set semantics are clearer than Object[key].
  // New Map() = all groups start unset (independent panels see undefined symbol).
  const [symbolMap, setSymbolMap] = useState<Map<string, string>>(() => new Map());

  const getSymbol = useCallback(
    (color: GroupColor): string | undefined => {
      // WHY guard null: unlinked panels (color=null) have no group symbol
      if (!color) return undefined;
      return symbolMap.get(color);
    },
    [symbolMap],
  );

  const setSymbol = useCallback((color: GroupColor, symbol: string) => {
    // WHY guard null: unlinked panels don't participate in group symbol linking
    if (!color) return;
    setSymbolMap((prev) => {
      const next = new Map(prev);
      next.set(color, symbol);
      return next;
    });
  }, []);

  return (
    <SymbolLinkingContext.Provider value={{ getSymbol, setSymbol }}>
      {children}
    </SymbolLinkingContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useSymbolLinking — access symbol linking state from a workspace panel.
 * WHY throw on missing provider: fails fast with a clear message instead of
 * silently returning undefined and causing a cryptic downstream null dereference.
 */
export function useSymbolLinking(): SymbolLinkingContextValue {
  const ctx = useContext(SymbolLinkingContext);
  if (!ctx) {
    throw new Error("useSymbolLinking must be used inside <SymbolLinkingProvider>");
  }
  return ctx;
}
