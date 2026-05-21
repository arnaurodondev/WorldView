/**
 * contexts/ActivePortfolioContext.tsx — Active-portfolio selection shared
 * across the shell (TopBar / Dashboard / Portfolio page).
 *
 * WHY THIS EXISTS (PRD-0089 W1.1 / QA F-002): the W1 PortfolioSwitcher
 *   persists its selection to localStorage but no other surface reads it.
 *   The TopBar's PortfolioRail still pulls metrics for `portfolios[0]`
 *   regardless of what the user picks. Adding a single React context
 *   moves the selection into one place; the switcher writes it, the
 *   metrics hook reads it. ~50 LOC of plumbing buys the user a working
 *   chip without scope-creeping W1's commit history.
 *
 * SEMANTICS:
 *   - `activePortfolioId === null` means "All Portfolios" (ROOT sentinel).
 *     Today consumers fall back to `portfolios[0]` for this case — true
 *     ROOT aggregation (sum-across-all-portfolios) is deferred to the
 *     dedicated Portfolio Overview wave per the QA recommendation.
 *   - `activePortfolioId === <uuid>` means scope to that portfolio only.
 *
 * PERSISTENCE:
 *   - Reads/writes `localStorage.shell.activePortfolioId` (same key the
 *     W1 PortfolioSwitcher already wrote to — drop-in compatible).
 *   - Lazy initialiser so we don't flash the wrong selection on first paint.
 *   - Try/catch around localStorage access (Safari Private mode throws).
 *
 * MULTI-TAB: deliberately NOT wired to `storage` events — switching the
 *   active portfolio in tab A should not magically change what tab B is
 *   showing the user (different workflow on each tab is intentional).
 */

"use client";
// WHY "use client": uses React state + localStorage (both browser-only).

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// ── Constants ──────────────────────────────────────────────────────────────

/** localStorage key. Kept identical to the W1 PortfolioSwitcher's key so
 *  the chip's pre-context writes still load on first mount. */
const ACTIVE_PORTFOLIO_LS_KEY = "shell.activePortfolioId";

// ── Helpers ────────────────────────────────────────────────────────────────

function readPersistedActiveId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACTIVE_PORTFOLIO_LS_KEY);
  } catch {
    return null;
  }
}

function writePersistedActiveId(id: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (id) window.localStorage.setItem(ACTIVE_PORTFOLIO_LS_KEY, id);
    else window.localStorage.removeItem(ACTIVE_PORTFOLIO_LS_KEY);
  } catch {
    /* private mode — silently drop */
  }
}

// ── Context shape ──────────────────────────────────────────────────────────

export interface ActivePortfolioContextValue {
  /** Currently-selected portfolio_id, or null when "All Portfolios" is active. */
  readonly activePortfolioId: string | null;
  /** Setter — passing null sets the active portfolio to ROOT/All. */
  readonly setActivePortfolio: (id: string | null) => void;
}

const ActivePortfolioContext = createContext<ActivePortfolioContextValue | null>(null);

// ── Provider ───────────────────────────────────────────────────────────────

interface ActivePortfolioProviderProps {
  readonly children: ReactNode;
  /** Test override — pre-seed the active id without touching localStorage. */
  readonly initialActiveId?: string | null;
}

export function ActivePortfolioProvider({
  children,
  initialActiveId,
}: ActivePortfolioProviderProps) {
  // Lazy initialiser: read localStorage exactly once at mount to avoid
  // hydration flicker. The override is for tests.
  const [activePortfolioId, setActivePortfolioIdState] = useState<string | null>(() =>
    initialActiveId !== undefined ? initialActiveId : readPersistedActiveId(),
  );

  const setActivePortfolio = useCallback((id: string | null) => {
    setActivePortfolioIdState(id);
    writePersistedActiveId(id);
  }, []);

  const value = useMemo<ActivePortfolioContextValue>(
    () => ({ activePortfolioId, setActivePortfolio }),
    [activePortfolioId, setActivePortfolio],
  );

  return (
    <ActivePortfolioContext.Provider value={value}>
      {children}
    </ActivePortfolioContext.Provider>
  );
}

// ── Hook ───────────────────────────────────────────────────────────────────

/**
 * useActivePortfolio — read the current active-portfolio id + setter.
 *
 * Returns a stable noop context when called outside the provider (rather
 * than throwing). The fallback lets consumers like usePortfolioMetrics
 * compile in pre-provider environments (older tests, Storybook) without
 * forcing every caller to wrap in <ActivePortfolioProvider>. The
 * provider is mounted at the (app) layout root so every authenticated
 * surface gets the real value.
 */
export function useActivePortfolio(): ActivePortfolioContextValue {
  const ctx = useContext(ActivePortfolioContext);
  if (ctx) return ctx;
  // Stable noop fallback — referentially-equal across renders so consumers
  // that depend on the setter in useEffect don't re-fire.
  return NOOP_CONTEXT;
}

const NOOP_CONTEXT: ActivePortfolioContextValue = Object.freeze({
  activePortfolioId: null,
  setActivePortfolio: () => undefined,
});
