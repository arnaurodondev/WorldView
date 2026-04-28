/**
 * hooks/useCopyState.ts — clipboard-with-success-feedback hook
 *
 * WHY THIS EXISTS (PLAN-0050 QA F-QA-02 + F-QA-03 + F-QA-13):
 * - F-QA-02: the inline `setTimeout(reset, 1200)` pattern in the prior
 *   `CompactInstrumentHeader` and `RefreshAllButton` leaked timers across
 *   unmount and was duplicated in two components.
 * - F-QA-03: the prior `safeCopy` returned Promise.resolve() on
 *   missing-clipboard but the caller still flipped to a "Copied!" success
 *   state — users were getting a green check while their clipboard was
 *   actually empty (HTTP origin, denied permissions, jsdom).
 * - F-QA-13: identical state-machine logic in two components — extract.
 *
 * Contract:
 *   const { state, copy } = useCopyState();
 *   await copy(value, "ticker"); // → state === "ticker" only on real success
 *
 * - `state` is one of "idle" | "<key you passed>" | "error"
 * - On unmount, any pending reset is cancelled (no leak)
 * - When clipboard API is unavailable, `state` flips to "error" — caller
 *   can render an inline "Unable to copy" tooltip
 * - `copy()` returns a boolean for callers that want to chain (e.g.
 *   firing a tracking event only on success).
 */

"use client";
// WHY "use client": uses useState + useRef + useEffect cleanup.

import { useCallback, useEffect, useRef, useState } from "react";

/** ms before the success state auto-resets to "idle". 1.2s matches the user's
 *  typical paste-after-copy gesture without feeling sluggish. */
const RESET_AFTER_MS = 1200;

export type CopyState<K extends string> = "idle" | K | "error";

export function useCopyState<K extends string>() {
  const [state, setState] = useState<CopyState<K>>("idle");
  // useRef holds the active timer id so we can cancel it on click-during-active
  // and on unmount. window.setTimeout returns number in browser context.
  const timerRef = useRef<number | null>(null);
  // F-QA2-03 fix: track mounted-ness so the post-`await navigator.clipboard`
  // synchronous setState cannot run on a dead component (route change during
  // the in-flight clipboard promise). React 18 silently ignores it but the
  // closure leak is real and StrictMode dev re-warns.
  const mountedRef = useRef(true);

  // Cleanup: cancel pending reset and mark unmounted.
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  const safeSetState = useCallback((next: CopyState<K>) => {
    if (mountedRef.current) setState(next);
  }, []);

  const scheduleReset = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => {
      safeSetState("idle");
      timerRef.current = null;
    }, RESET_AFTER_MS);
  }, [safeSetState]);

  const copy = useCallback(
    async (value: string, key: K): Promise<boolean> => {
      // Defensive: clipboard API is undefined in insecure contexts (HTTP),
      // jsdom test envs, and on permission-denied. Telling the user the truth
      // is more important than the tiny convenience of pretending it worked.
      if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
        safeSetState("error");
        scheduleReset();
        return false;
      }
      try {
        await navigator.clipboard.writeText(value);
        safeSetState(key);
        scheduleReset();
        return true;
      } catch {
        // Permission denied at runtime — same UX as missing API.
        safeSetState("error");
        scheduleReset();
        return false;
      }
    },
    [safeSetState, scheduleReset],
  );

  return { state, copy };
}
