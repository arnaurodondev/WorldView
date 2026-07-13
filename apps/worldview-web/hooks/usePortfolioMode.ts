/**
 * hooks/usePortfolioMode.ts — Single source of the portfolio detail-level mode
 * (PLAN-0122 W-A, PRD-0122 §6.1).
 *
 * WHY THIS EXISTS: the portfolio page has two "shapes" — a casual **Simple**
 * overview and today's power-user **Advanced** layout. To keep that a *rendering
 * gate and never a fork*, exactly ONE value ("simple" | "advanced") is resolved
 * here and threaded down as a prop. Every component reads the mode from this hook
 * (via a prop); nothing else reads/writes the mode. That single-source rule is
 * what lets the Advanced-parity snapshot test guarantee no drift.
 *
 * TWO PERSISTENCE SINKS, on purpose:
 *   • URL param `?mode=` — makes a view **shareable** ("open my portfolio in
 *     Advanced"). It is also the highest-precedence source for a given render so
 *     a shared link always wins.
 *   • localStorage `worldview:portfolioMode:v1` — makes the choice **sticky**
 *     across reloads even without a `?mode=` in the URL.
 *
 * PRECEDENCE (documented because it is subtle): URL param → localStorage →
 * default. WHY URL beats localStorage: a shared/deep link must render what the
 * link says regardless of what THIS browser last chose locally.
 *
 * DEFAULT: derived from the `PORTFOLIO_SIMPLE_DEFAULT` rollout flag. While the
 * flag is `false` (W-A) an unset user resolves to "advanced" (production
 * unchanged); W-B flips the flag so an unset user gets "simple".
 *
 * SSR-SAFETY: localStorage is read only inside `useEffect` (never during render).
 * The first render hydrates from URL-or-default (identical on server and client),
 * then an effect reconciles with localStorage. This "default-first, reconcile-in-
 * effect" pattern avoids a hydration mismatch (server has no `window`).
 */

"use client";
// WHY "use client": nuqs `useQueryState` depends on the Next.js router (browser
// only) and we touch `window.localStorage` — neither exists in a server render.

import { useCallback, useEffect, useState } from "react";
import { parseAsStringLiteral, useQueryState } from "nuqs";

import { PORTFOLIO_SIMPLE_DEFAULT } from "@/lib/portfolio/mode-flag";

// ── Types ───────────────────────────────────────────────────────────────────

/** The two portfolio detail levels. Kept as a literal union so the value is
 *  validated at both the URL boundary (nuqs) and the localStorage boundary. */
export type PortfolioMode = "simple" | "advanced";

/** The allowed values, shared by the nuqs parser and the localStorage guard so
 *  there is one source of truth for "what is a valid mode string". */
const PORTFOLIO_MODES = ["simple", "advanced"] as const satisfies readonly PortfolioMode[];

/** localStorage key. Versioned (`:v1`) so a future shape change can migrate
 *  without colliding with old values (matches the repo's `worldview:*:vN` keys). */
export const PORTFOLIO_MODE_STORAGE_KEY = "worldview:portfolioMode:v1";

// ── Hook ────────────────────────────────────────────────────────────────────

export interface UsePortfolioModeResult {
  /** The resolved mode for this render (URL → localStorage → default). */
  mode: PortfolioMode;
  /** Set the mode; writes BOTH sinks (URL param + localStorage) so the choice
   *  is simultaneously shareable and sticky. */
  setMode: (mode: PortfolioMode) => void;
  /**
   * `false` until the localStorage-reconciling effect has run once, `true`
   * thereafter (QA item 12). WHY expose it: on the first render `mode` is
   * URL-or-default (localStorage is intentionally NOT read during render, for
   * SSR-safety). A user whose sticky choice is "advanced" therefore resolves to
   * the flag default ("simple") on that first paint, and only flips to
   * "advanced" after this effect runs. Callers can gate a heavy mode-dependent
   * subtree on `hydrated` (keep showing the mode-aware loading skeleton) so the
   * Advanced strips don't briefly mount then tear down. It is a hydration-flash
   * guard, not a correctness gate — `mode` is always usable.
   */
  hydrated: boolean;
}

/**
 * usePortfolioMode — resolve + persist the portfolio detail level.
 *
 * @returns `{ mode, setMode }` — `mode` is always a concrete literal (never
 *          null); `setMode` writes the URL param and localStorage together.
 */
export function usePortfolioMode(): UsePortfolioModeResult {
  // ── URL sink ──────────────────────────────────────────────────────────────
  // WHY no `.withDefault(...)`: we deliberately let the parser return `null` when
  // `?mode=` is ABSENT. That absence is what lets URL take precedence *only when
  // the user actually specified a mode* — otherwise we fall through to
  // localStorage. `clearOnDefault` (default = null) means `setUrlMode(null)`
  // would drop the param; an explicit "simple"/"advanced" is always written so a
  // chosen view stays shareable even when it equals the flag default.
  const [urlMode, setUrlMode] = useQueryState(
    "mode",
    parseAsStringLiteral(PORTFOLIO_MODES).withOptions({ clearOnDefault: true }),
  );

  // ── localStorage sink (read in an effect, never during render) ─────────────
  // `null` = "not yet read" or "nothing stored". We keep it in React state so a
  // reconcile (or a `setMode` call) re-renders with the sticky value.
  const [storageMode, setStorageMode] = useState<PortfolioMode | null>(null);
  // `hydrated` flips true after the reconcile effect runs (QA item 12). Kept in
  // state so a caller re-renders when hydration completes.
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    // WHY inside useEffect: effects run only on the client, after paint — so the
    // server render and the first client render both used URL-or-default and
    // agree (no hydration warning). Here we reconcile with the sticky value.
    try {
      const raw = window.localStorage.getItem(PORTFOLIO_MODE_STORAGE_KEY);
      // Guard against a corrupted/legacy value: only accept a known literal,
      // otherwise fall back to `null` so the default (via the flag) applies.
      setStorageMode(raw === "simple" || raw === "advanced" ? raw : null);
    } catch {
      // localStorage can throw (private-mode quota, disabled storage). Treat any
      // failure as "no sticky value" — the default still resolves the mode.
      setStorageMode(null);
    } finally {
      // Mark hydration complete regardless of outcome — the sticky value (or its
      // absence) has now been reconciled, so `mode` is stable from here.
      setHydrated(true);
    }
  }, []);

  // ── Resolve ────────────────────────────────────────────────────────────────
  // WHY compute the default here (inside the hook body, each render): the rollout
  // flag can flip between W-A and W-B; reading it here keeps the default live.
  const defaultMode: PortfolioMode = PORTFOLIO_SIMPLE_DEFAULT ? "simple" : "advanced";
  // Precedence: explicit URL param → sticky localStorage → flag default.
  const mode: PortfolioMode = urlMode ?? storageMode ?? defaultMode;

  // ── Setter (writes both sinks) ─────────────────────────────────────────────
  const setMode = useCallback(
    (next: PortfolioMode) => {
      // Shareable: reflect the choice in the URL immediately.
      void setUrlMode(next);
      // Sticky: persist across reloads. Also update local state synchronously so
      // this render's `mode` reflects the choice without waiting for the effect.
      try {
        window.localStorage.setItem(PORTFOLIO_MODE_STORAGE_KEY, next);
      } catch {
        // Best-effort persistence — a storage failure must not break the toggle.
      }
      setStorageMode(next);
    },
    [setUrlMode],
  );

  return { mode, setMode, hydrated };
}
