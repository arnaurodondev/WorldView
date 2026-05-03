/**
 * contexts/WorkspaceSymbolContext.tsx — Workspace-level symbol broadcast
 *
 * WHY THIS EXISTS: Bloomberg Terminal has a "Security" input at the top of each
 * workspace. Typing a symbol there pushes it to ALL panels simultaneously — chart,
 * fundamentals, news, etc. all update. This context replicates that pattern.
 *
 * WHY separate from SymbolLinkingContext: SymbolLinkingContext handles color-group
 * symbol linking (panel A's blue group links to panel B's blue group). This context
 * is simpler: one global symbol, broadcast to all panels equally. It is the
 * workspace-wide "master symbol" that takes precedence over per-panel linked symbols
 * when set.
 *
 * HOW IT WORKS:
 *   1. WorkspaceSymbolBar (in workspace/page.tsx) provides an input field at the
 *      top of the page. User types a ticker and presses Enter.
 *   2. setBroadcastSymbol() normalises to uppercase + trims whitespace, then saves.
 *   3. Any panel widget that calls useWorkspaceSymbol() receives broadcastSymbol.
 *   4. Panel widgets use broadcastSymbol ?? their own linked symbol as effectiveTicker.
 *   5. User can clear the broadcast symbol (Escape key or ×  button) to restore
 *      per-panel symbol-linking behaviour.
 *
 * WHO USES IT:
 *   - workspace/page.tsx (WorkspaceSymbolProvider + WorkspaceSymbolBar)
 *   - WorkspaceChartWidget (consumer: overrides ticker prop when set)
 *
 * DATA SOURCE: React state only (no localStorage — broadcast symbol is session-local).
 * DESIGN REFERENCE: PRD-0031 §5 Workspace; PLAN-0059 Wave H-5
 */

"use client";
// WHY "use client": uses React state and context — both browser-only APIs.
// Server components cannot hold mutable state or provide context values.

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

// ── Types ──────────────────────────────────────────────────────────────────────

interface WorkspaceSymbolContextValue {
  /**
   * Currently broadcast symbol (e.g., "AAPL"), null if none set.
   *
   * WHY nullable (not ""): null is an explicit "no broadcast" sentinel. An empty
   * string is ambiguous — it could mean "user typed nothing" or "symbol was cleared".
   * Null is unambiguous: panels receive null and know to fall back to their own state.
   */
  broadcastSymbol: string | null;

  /**
   * Set the broadcast symbol — called from WorkspaceSymbolBar on Enter.
   * Passing null or empty string clears the broadcast (panels revert to own state).
   *
   * WHY a setter function (not direct setState): the setter normalises input
   * (uppercase + trim) before storing. Hiding normalisation behind the API
   * prevents callers from accidentally storing un-normalised symbols.
   */
  setBroadcastSymbol: (symbol: string | null) => void;
}

// ── Context ───────────────────────────────────────────────────────────────────

/**
 * WHY a default value of no-op functions (not null):
 * Creating the context with a no-op default means components that forget to
 * wrap with WorkspaceSymbolProvider get a safe fallback (broadcastSymbol = null,
 * setBroadcastSymbol = () => {}) rather than crashing on null dereference.
 * The useWorkspaceSymbol hook still throws to catch programmer errors explicitly.
 */
const WorkspaceSymbolContext = createContext<WorkspaceSymbolContextValue>({
  broadcastSymbol: null,
  setBroadcastSymbol: () => {},
});

// ── Provider ──────────────────────────────────────────────────────────────────

/**
 * WorkspaceSymbolProvider — wraps the workspace page to provide broadcast state.
 *
 * WHY NOT in layout.tsx: broadcast symbol is workspace-session-local (not global
 * across the whole app). Placing the provider in workspace/page.tsx means symbol
 * state is reset when the user leaves the workspace route — correct behaviour.
 *
 * WHY useCallback on setBroadcastSymbol: the setter is passed as a prop to
 * WorkspaceSymbolBar, which renders on every parent re-render. useCallback gives
 * a stable reference so the Bar avoids spurious re-renders.
 */
export function WorkspaceSymbolProvider({ children }: { children: ReactNode }) {
  const [broadcastSymbol, setBroadcastSymbolRaw] = useState<string | null>(null);

  const setBroadcastSymbol = useCallback((symbol: string | null) => {
    // WHY toUpperCase + trim: financial tickers are always uppercase. Normalise
    // here so consumers never see "aapl" — they always see "AAPL". Trimming
    // removes accidental leading/trailing spaces from keyboard entry.
    setBroadcastSymbolRaw(symbol ? symbol.toUpperCase().trim() || null : null);
  }, []);

  return (
    <WorkspaceSymbolContext.Provider value={{ broadcastSymbol, setBroadcastSymbol }}>
      {children}
    </WorkspaceSymbolContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useWorkspaceSymbol — consume the workspace-level broadcast symbol.
 *
 * WHY does this NOT throw on missing provider: WorkspaceSymbolContext has a safe
 * default value (null, no-op setter). Components used outside a workspace (e.g.,
 * in Storybook or tests without the full page tree) degrade gracefully — they just
 * see broadcastSymbol = null and behave as if no broadcast is active.
 *
 * Usage:
 *   const { broadcastSymbol } = useWorkspaceSymbol();
 *   const effectiveTicker = broadcastSymbol ?? ticker;  // prop fallback
 */
export function useWorkspaceSymbol(): WorkspaceSymbolContextValue {
  return useContext(WorkspaceSymbolContext);
}
