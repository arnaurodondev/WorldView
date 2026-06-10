"use client";

/**
 * features/dashboard/hooks/usePriceFlash.ts — transient price-change indicator
 *
 * WHY THIS EXISTS (Round-3 polish, item 6): the Market Snapshot index strip
 * refetches quotes every 60s. Without any change indicator, a price tick is
 * invisible — the digits just swap and the trader can't tell whether the
 * widget is live. Bloomberg terminals flash the cell background on each tick
 * for exactly this reason.
 *
 * WHY A TRANSIENT CLASS, NOT A KEYFRAME ANIMATION:
 * PRD-0089 NFR-6 ("Animation policy: no animations on data surfaces — charts,
 * tables, mini-bars") bans keyframe animation on data rows, and the 4-tier
 * transition policy in tailwind.config.ts only whitelists short color-only
 * transitions (Tier-1, ≤100-150ms) for affordance feedback. So instead of
 * animating, this hook returns a DISCRETE state ("up" | "down" | null) that
 * the row maps to a static background tint class for ~900ms. The tint's
 * appearance/disappearance may ride the row's existing Tier-1
 * `transition-colors` (150ms ease-out) — a compliant chrome-state fade, not a
 * data animation. No translation, no scaling, no pulsing.
 *
 * WHY prefers-reduced-motion DISABLES IT ENTIRELY: even though the tint is
 * not "motion" in the translate/scale sense, a recurring background flash is
 * exactly the class of peripheral flicker the OS-level setting asks us to
 * suppress (WCAG 2.3.3 Animation from Interactions, applied conservatively).
 * Users with the preference still get the ▲/▼ glyph + signed change column —
 * the flash is redundant signal, so dropping it loses nothing.
 *
 * WHO USES IT: MarketSnapshotWidget SnapshotRow (index strip rows).
 */

import { useEffect, useRef, useState } from "react";

/** Direction of the most recent price change, or null when not flashing. */
export type PriceFlash = "up" | "down" | null;

/** How long the tint stays applied. ~900ms: long enough to catch in
 *  peripheral vision, short enough that two consecutive 60s ticks can never
 *  overlap and the dashboard never looks "permanently tinted". */
export const PRICE_FLASH_MS = 900;

/**
 * prefersReducedMotion — read the OS-level setting at flash time.
 *
 * WHY a function (not a module constant): the user can toggle the OS setting
 * mid-session; evaluating per flash honours the change without a reload.
 * WHY the typeof guard: matchMedia does not exist in SSR / jsdom-without-
 * stubs — treat "unknown" as "reduce" is too aggressive (every test env
 * would disable the feature), so default to NOT reduced, matching the
 * browser default.
 */
function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * usePriceFlash — returns "up" / "down" for PRICE_FLASH_MS after `value`
 * changes, null otherwise.
 *
 * @param value current price (null/undefined while loading or for "no data"
 *              rows — transitions from/to null never flash, because the first
 *              data arrival is a LOAD, not a price CHANGE).
 */
export function usePriceFlash(value: number | null | undefined): PriceFlash {
  const [flash, setFlash] = useState<PriceFlash>(null);
  // WHY useRef for the previous value: reading the prior render's value must
  // not itself trigger a render — refs persist across renders without doing so.
  const prevRef = useRef<number | null | undefined>(value);
  // Track the running timer so a rapid second change restarts the window
  // instead of the first timer clearing the second flash early.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = value;

    // First data arrival (prev == null) or data loss (value == null) is not
    // a tick — only a real number→number change flashes.
    if (prev == null || value == null || prev === value) return;

    // Reduced-motion users: keep the state machine silent — the ▲/▼ glyphs
    // already carry the direction signal without any flicker.
    if (prefersReducedMotion()) return;

    setFlash(value > prev ? "up" : "down");
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setFlash(null), PRICE_FLASH_MS);
  }, [value]);

  // Unmount cleanup — never leave a timer firing setState on a dead component.
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return flash;
}
