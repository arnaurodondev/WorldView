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
 *     usePortfolioMetrics (TopBar rail) resolves this to the backend ROOT
 *     portfolio when provisioned, else aggregates client-side across all
 *     portfolios (2026-06-10 PortfolioSwitcher fix). Single-portfolio
 *     widgets (useResolvedPortfolioId) still fall back to `portfolios[0]`.
 *   - `activePortfolioId === <uuid>` means scope to that portfolio only.
 *
 * MOUNT: app/providers.tsx (root client provider tree). It MUST stay an
 *   ancestor of app/(app)/layout.tsx because the layout itself calls
 *   usePortfolioMetrics — pinned by
 *   __tests__/active-portfolio-provider-mount.test.ts.
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

/**
 * UUID v1-v5 regex (any variant). The platform mints UUIDv7 for
 * portfolio ids via `common.ids.new_uuid7()`, which is structurally
 * indistinguishable from UUIDv4 here (8-4-4-4-12 hex). We accept ANY
 * RFC-4122 UUID rather than locking to v7 so that test fixtures and
 * future variants (UUIDv8 / UUIDv6) still validate.
 *
 * QA-2026-05-21 Sec F-001: validate that the persisted value LOOKS like
 * a UUID before writing to localStorage or returning to consumers. A
 * future buggy caller passing a non-UUID would otherwise persist
 * garbage that downstream code (usePortfolioMetrics' portfolio-exists
 * guard) silently filters but leaves in storage.
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// ── Helpers ────────────────────────────────────────────────────────────────

function readPersistedActiveId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(ACTIVE_PORTFOLIO_LS_KEY);
    if (raw == null) return null;
    // Sec F-001: reject malformed persisted values (truncated UUIDs, junk
    // from a prior buggy version, tampered localStorage). Returning null
    // routes consumers to the fallback (portfolios[0]) which is the
    // correct behaviour for "no valid selection".
    return UUID_RE.test(raw) ? raw : null;
  } catch {
    return null;
  }
}

function writePersistedActiveId(id: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (id) {
      // Sec F-001: refuse to persist non-UUID values. Silently drop —
      // the in-memory state already updated, so the dev never sees an
      // observable regression. A console.warn helps diagnose if a
      // bad caller appears.
      if (!UUID_RE.test(id)) {
        if (typeof process !== "undefined" && process.env.NODE_ENV !== "production") {
          console.warn(
            `[ActivePortfolioContext] refusing to persist non-UUID id: ${JSON.stringify(id)}`,
          );
        }
        return;
      }
      window.localStorage.setItem(ACTIVE_PORTFOLIO_LS_KEY, id);
    } else {
      window.localStorage.removeItem(ACTIVE_PORTFOLIO_LS_KEY);
    }
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
 *
 * Arch F-006 (QA 2026-05-21): the noop is safe for READS (returns
 * `null` → consumers fall back to `portfolios[0]`) but a silent noop
 * SETTER is a footgun — a future component rendered outside the
 * provider would appear to flip the active portfolio but the selection
 * vanishes with no error trail. We log a single dev warning on the
 * first noop setter call so the missing provider surfaces loudly in
 * development without breaking production. The wrapper is module-scoped
 * (one warning per process) to avoid spamming consoles.
 */
let _noopSetterWarned = false;

function noopSetter(_id: string | null): void {
  if (_noopSetterWarned) return;
  if (typeof process !== "undefined" && process.env.NODE_ENV !== "production") {
    _noopSetterWarned = true;
    console.warn(
      "[ActivePortfolioContext] useActivePortfolio().setActivePortfolio called outside <ActivePortfolioProvider>. " +
        "Selection will not persist. Wrap the consumer tree in the provider — see app/providers.tsx for the canonical mount.",
    );
  }
}

export function useActivePortfolio(): ActivePortfolioContextValue {
  const ctx = useContext(ActivePortfolioContext);
  if (ctx) return ctx;
  // Stable noop fallback — referentially-equal across renders so consumers
  // that depend on the setter in useEffect don't re-fire.
  return NOOP_CONTEXT;
}

const NOOP_CONTEXT: ActivePortfolioContextValue = Object.freeze({
  activePortfolioId: null,
  setActivePortfolio: noopSetter,
});
