/**
 * components/screener/percentile-heat.ts — peer-percentile conditional formatting
 * for the screener result grid (UI competitive-roadmap item #5 / B3).
 *
 * WHY THIS EXISTS (Bloomberg / Capital IQ parity):
 *   Incumbent terminals (Bloomberg EQS, Capital IQ) signal a value's quality by
 *   its standing *within the current result set* — a P/E of 14 means nothing in
 *   isolation, but "cheaper than 80% of these peers" is an instant, premium
 *   signal. The roadmap calls this the *right* answer to the valuation-colour
 *   problem: context-aware heat instead of an absolute bull/bear tint that
 *   miscommunicates on non-directional metrics (a low P/E is not "bad/red").
 *
 * DESIGN CONSTRAINTS (docs/ui/DESIGN_SYSTEM.md):
 *   - Terminal-grade, NOT a rainbow. We use a SINGLE neutral hue (the muted
 *     surface tint) whose *opacity* scales with the peer percentile — a subtle
 *     "data-bar"/heat wash behind the number, never competing with the
 *     directional teal/red or the brand yellow.
 *   - The number itself keeps its existing colour + `font-mono tabular-nums`
 *     treatment. The percentile wash sits BEHIND it (cell background), so it
 *     never changes what the digits mean — it only ranks them.
 *   - Off by default and user-toggleable (see the store below): heat is an
 *     opt-in scanning aid, not a permanent decoration.
 *
 * WHY COMPUTED CLIENT-SIDE OVER LOADED ROWS:
 *   The backend has no peer-percentile projection. The screener already loads
 *   every result row into AG Grid, so the cell renderer can rank a value
 *   against the other *currently-loaded, post-filter* rows via the AG Grid API
 *   at render time — exactly the "peers in this screen" semantics we want
 *   (filtering to "US software" re-bases every percentile to that cohort).
 *
 * WHO USES IT: components/screener/ag-screener-columns.tsx (cell renderers wrap
 *   their value in a <PercentileHeat> background), components/screener/
 *   ScreenerHeader.tsx (the toggle button).
 */

"use client";

import { useSyncExternalStore } from "react";
import type { GridApi } from "ag-grid-community";

// ─────────────────────────────────────────────────────────────────────────────
// 1. Toggle store — a tiny external store so the heat on/off state is shared
//    between the toggle button (ScreenerHeader) and every cell renderer WITHOUT
//    threading a prop through the page (which this surface is not allowed to
//    edit). useSyncExternalStore keeps React in sync with the module-level flag
//    and with the persisted localStorage value across reloads.
// ─────────────────────────────────────────────────────────────────────────────

/** localStorage key for the user's peer-heat preference. */
const STORAGE_KEY = "worldview.screener.peerHeat";

/** In-memory mirror of the flag (source of truth for the current tab session). */
let enabled = readPersisted();

/** Subscriber callbacks registered via useSyncExternalStore. */
const listeners = new Set<() => void>();

/**
 * readPersisted — load the saved preference (default: OFF).
 *
 * WHY a try/catch: localStorage throws in private-mode / SSR contexts. A
 * scanning aid must never break the page, so any failure falls back to OFF.
 */
function readPersisted(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

/** Notify all React subscribers that the flag changed. */
function emit(): void {
  for (const l of listeners) l();
}

/** subscribe — useSyncExternalStore contract. Returns an unsubscribe fn. */
function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** getSnapshot — current flag value for the client. */
function getSnapshot(): boolean {
  return enabled;
}

/**
 * getServerSnapshot — SSR snapshot. Always OFF on the server so the first
 * client paint matches (no hydration mismatch); the real value is picked up on
 * the next store read after mount.
 */
function getServerSnapshot(): boolean {
  return false;
}

/**
 * setPeerHeatEnabled — flip the flag, persist it, and notify subscribers.
 * Exported so a non-React caller (or a test) can drive the store directly.
 */
export function setPeerHeatEnabled(next: boolean): void {
  enabled = next;
  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    }
  } catch {
    // Persistence is best-effort; the in-memory flag still drives this session.
  }
  emit();
}

/** isPeerHeatEnabled — non-reactive read (for cell renderers that re-run anyway). */
export function isPeerHeatEnabled(): boolean {
  return enabled;
}

/**
 * usePeerHeatEnabled — reactive hook for components that must re-render when the
 * toggle flips (the ScreenerHeader button's pressed state).
 */
export function usePeerHeatEnabled(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. Percentile maths — rank a value within the column's loaded peer values.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * percentileRank — fraction (0..1) of `values` that are STRICTLY LESS than `v`,
 * using the standard "less-than" empirical CDF. 0 = lowest in the set, ~1 =
 * highest.
 *
 * WHY strict-less (not ≤): ties should not push a value to the top of its own
 * cohort. With 5 identical values each ranks at 0 (none is below it), which
 * reads as "no standout" — the correct neutral signal for an undifferentiated
 * column.
 *
 * @param v       the value to rank (already known non-null by the caller)
 * @param values  the peer values (callers pass only the finite, non-null ones)
 */
export function percentileRank(v: number, values: number[]): number {
  // A single-element (or empty) cohort has no spread to rank against → 0
  // (neutral). Guards against divide-by-zero and a lone row glowing at 100%.
  if (values.length <= 1) return 0;
  let below = 0;
  for (const x of values) if (x < v) below += 1;
  return below / (values.length - 1);
}

/**
 * collectColumnValues — gather every finite numeric value for one AG Grid
 * column across the *post-filter* rows currently loaded in the grid.
 *
 * WHY post-filter (forEachNodeAfterFilter): the percentile must re-base to the
 * cohort the user is actually looking at. Filtering to "dividend payers"
 * re-ranks P/E against only those names — the whole point of peer-relative heat.
 *
 * WHY a `selector` (not a column field string): several heat columns are
 * DERIVED (e.g. analyst upside = target/price − 1) and have no single backing
 * field. A selector lets the caller reuse the exact same derivation the cell
 * renderer uses, so the ranked value always matches the displayed value.
 *
 * Returns [] when the api is unavailable (renderer called before grid-ready) —
 * the caller then skips the wash entirely (no peers ⇒ nothing to rank).
 */
export function collectColumnValues<TRow>(
  api: GridApi<TRow> | null | undefined,
  selector: (row: TRow) => number | null | undefined,
): number[] {
  if (!api) return [];
  const out: number[] = [];
  api.forEachNodeAfterFilter((node) => {
    const row = node.data;
    if (row == null) return;
    const val = selector(row);
    // Number.isFinite excludes null, undefined, and NaN in one check.
    if (typeof val === "number" && Number.isFinite(val)) out.push(val);
  });
  return out;
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. Heat style — map a percentile (0..1) to a subtle, single-hue background.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * peerHeatBackground — the inline `background` value for a cell at a given
 * percentile, or `undefined` when no wash should be drawn.
 *
 * DESIGN: a single neutral hue (the design-system `--foreground` zinc, expressed
 * via hsl with a low, percentile-scaled alpha). It reads as a data-bar wash that
 * gets brighter toward the top of the cohort — terminal-grade, monochrome, and
 * it never collides with the directional teal/red or the brand yellow.
 *
 *   percentile 0.00 → no wash (returns undefined; lowest peers stay clean)
 *   percentile 1.00 → ~14% alpha zinc wash (still subtle — the digit stays the
 *                     dominant element, the wash is peripheral context)
 *
 * WHY a floor (return undefined below MIN_VISIBLE): washing the bottom third at
 * ~1% alpha is invisible noise that just muddies the grid. We only paint the
 * upper band so "standout" rows pop and the rest stay clean — higher signal,
 * less ink (Tufte). MAX_ALPHA is deliberately low to stay tasteful.
 */
const MIN_VISIBLE = 0.5; // only the top half of the cohort gets any wash
const MAX_ALPHA = 0.14; // ceiling alpha at the 100th percentile

export function peerHeatBackground(percentile: number): string | undefined {
  if (percentile <= MIN_VISIBLE) return undefined;
  // Re-scale [MIN_VISIBLE..1] → [0..1] so the visible band uses the full alpha
  // ramp instead of being squashed into the top sliver.
  const t = (percentile - MIN_VISIBLE) / (1 - MIN_VISIBLE);
  const alpha = (MAX_ALPHA * t).toFixed(3);
  // 240 5% 90% == --foreground (zinc-200) from globals.css. Hardcoding the hsl
  // triplet (not a var) because we need a per-cell alpha, which CSS custom
  // properties can't carry through `hsl(var(--foreground) / a)` reliably in an
  // inline style across all the browsers the grid targets. Kept in sync with
  // the design token by comment, same pattern as HeatCell's hex source note.
  return `hsl(240 5% 90% / ${alpha})`;
}

/**
 * peerHeatStyle — convenience: full inline style object for a heat cell, or an
 * empty object when heat is off / value missing / below the visible band.
 *
 * Callers spread this onto the cell's wrapping <span> style so the percentile
 * wash sits behind the number. `display: block` + right padding preserve the
 * right-aligned numeric layout while letting the wash fill the cell width.
 */
export function peerHeatStyle(
  value: number | null | undefined,
  peers: number[],
): React.CSSProperties {
  // Heat only applies when the user has turned it on AND we have a value to rank.
  if (!isPeerHeatEnabled() || value == null || !Number.isFinite(value)) return {};
  const pct = percentileRank(value, peers);
  const bg = peerHeatBackground(pct);
  if (!bg) return {};
  return { backgroundColor: bg };
}
