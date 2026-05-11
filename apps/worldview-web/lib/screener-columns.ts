/**
 * lib/screener-columns.ts — User-customizable column preferences for the screener
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-06): Different users want different columns
 * visible. A long-only equity investor cares about P/E and dividend yield.
 * A momentum trader cares about CHG% and volume. Forcing one fixed layout on
 * everyone is a Bloomberg-anti-pattern: terminals let users hide/reorder
 * columns to match their workflow. This module is the persistence layer for
 * those preferences.
 *
 * WHY localStorage (same reasoning as lib/saved-screens.ts):
 *   - Synchronous reads (no flash-of-default-columns on mount).
 *   - 5MB quota is plenty for ~15 column records.
 *   - Survives page reloads, tab close, browser restart.
 *
 * WHY DEFAULT_COLUMNS is exported AND deeply frozen:
 *   - The component imports it as the canonical "out of the box" set so the
 *     ColumnSettingsPopover's "Reset" button can restore it without reaching
 *     into private state.
 *   - Object.freeze prevents accidental mutation by some unrelated module
 *     that imports it, which would silently corrupt the defaults for the
 *     whole bundle (a footgun we've hit before with global config arrays).
 *
 * WHY MERGE-WITH-DEFAULTS ON READ (loadColumnPrefs):
 *   - When we ADD a new column to the catalogue (say, "Dividend Yield" in a
 *     future plan), users with stored prefs from BEFORE that column existed
 *     would simply not see it. Merging the defaults catches every new key,
 *     defaulting to visible:true at the end of the order. This is the same
 *     pattern Chrome uses for new toolbar items.
 *
 * WHY visible + order combined into one array (not two separate maps):
 *   - One source of truth for "render this column at this position with
 *     visibility X". Two maps invariably drift in tests.
 *   - Order is implicit in the array index — drag-and-drop in the popover
 *     just reorders the array.
 *
 * WHO USES IT:
 *   - components/screener/ScreenerTable.tsx (consumes columns prop)
 *   - components/screener/ColumnSettingsPopover.tsx (CRUD UI)
 *   - app/(app)/screener/page.tsx (loads prefs, passes to table, persists on change)
 */

// ── Storage key (versioned) ──────────────────────────────────────────────────

/**
 * Versioned key — bump suffix if we change ScreenerColumn shape.
 * Older keys can be migrated lazily on first read.
 */
export const SCREENER_COLUMNS_KEY = "worldview:screenerColumns:v1";

// ── Public type ──────────────────────────────────────────────────────────────

/**
 * ScreenerColumn — single column descriptor.
 *
 * WHY all fields explicit (not derived):
 *   - The popover UI needs the label string verbatim ("Mkt Cap", not "MKT CAP").
 *   - Sortable is a column-level decision the table can't infer at runtime.
 *   - Align/formatter let one renderer handle every column type uniformly,
 *     so adding a new column means adding one record to DEFAULT_COLUMNS, not
 *     editing ScreenerTable.tsx.
 */
export interface ScreenerColumn {
  /** Stable identifier — used both for React keys and ScreenerResult lookup. */
  key: string;
  /** Display label shown in the table header AND the settings popover. */
  label: string;
  /** Whether the user can click the header to sort by this column. */
  sortable: boolean;
  /** "left" for text columns, "right" for numerics (institutional convention). */
  align: "left" | "right";
  /**
   * Optional formatter hint — the table picks its renderer from this string.
   *   - "price" → "$XX.XX"
   *   - "percent" → "+1.24%" (signed, color-tinted)
   *   - "number" → "12.34" (fixed 2dp)
   *   - "compact" → "3.0T" / "450B" (for market cap / revenue)
   *   - "text" → raw string
   *   - undefined → custom render path (e.g. SCORE column uses HeatCell)
   */
  formatter?: "price" | "percent" | "number" | "compact" | "text";
  /** Whether this column is currently shown in the table. */
  visible: boolean;
}

// ── Defaults ─────────────────────────────────────────────────────────────────

/**
 * DEFAULT_COLUMNS — the out-of-the-box screener column set.
 *
 * WHY FROZEN: see file-level "WHY DEFAULT_COLUMNS is exported AND deeply frozen".
 * Object.freeze covers the array; we deep-freeze each element to prevent
 * mutation of nested fields like `align`. This is cheap (one-time freeze at
 * module load) and catches mistakes early in dev.
 *
 * COLUMN ORDER MIRRORS PRD-0031 §7.1 — keeps the legacy default layout intact
 * for existing users while still allowing them to rearrange via the popover.
 *
 * WHY include "sparkline" by default (T-B-2-09):
 *   - The mini-chart adds significant value to the row scan (instant trend
 *     read) and matches Finviz/TradingView screener density expectations.
 *   - Users can hide it via the settings popover if they prefer pure data.
 */
export const DEFAULT_COLUMNS: readonly ScreenerColumn[] = Object.freeze([
  Object.freeze({ key: "ticker",     label: "Ticker",     sortable: true,  align: "left",  formatter: "text" as const,    visible: true }),
  Object.freeze({ key: "name",       label: "Name",       sortable: true,  align: "left",  formatter: "text" as const,    visible: true }),
  Object.freeze({ key: "sector",     label: "Sector",     sortable: true,  align: "left",  formatter: "text" as const,    visible: true }),
  Object.freeze({ key: "price",      label: "Price",      sortable: true,  align: "right", formatter: "price" as const,   visible: true }),
  Object.freeze({ key: "change",     label: "Chg%",       sortable: true,  align: "right", formatter: "percent" as const, visible: true }),
  Object.freeze({ key: "marketCap",  label: "Mkt Cap",    sortable: true,  align: "right", formatter: "compact" as const, visible: true }),
  Object.freeze({ key: "pe",         label: "P/E",        sortable: true,  align: "right", formatter: "number" as const,  visible: true }),
  Object.freeze({ key: "revenue",    label: "Revenue",    sortable: true,  align: "right", formatter: "compact" as const, visible: true }),
  Object.freeze({ key: "beta",       label: "Beta",       sortable: true,  align: "right", formatter: "number" as const,  visible: true }),
  Object.freeze({ key: "score",      label: "Score",      sortable: true,  align: "right",                                  visible: true }),
  Object.freeze({ key: "range52w",   label: "52W Range",  sortable: false, align: "right",                                  visible: true }),
  Object.freeze({ key: "volume",     label: "Volume",     sortable: false, align: "right", formatter: "compact" as const, visible: true }),
  Object.freeze({ key: "sparkline",  label: "Trend (30d)", sortable: false, align: "right",                                 visible: true }),
]) as readonly ScreenerColumn[];

// ── Internal helpers ─────────────────────────────────────────────────────────

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

/**
 * cloneDefaults — deep clone the frozen defaults so mutation doesn't escape
 * back into the module-level constant. Returns a plain (mutable) array of
 * ScreenerColumn so the popover can splice/reorder without TypeScript
 * complaining about readonly arrays.
 */
function cloneDefaults(): ScreenerColumn[] {
  return DEFAULT_COLUMNS.map((c) => ({ ...c }));
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * loadColumnPrefs — read stored prefs, merge with defaults, return the result.
 *
 * MERGE STRATEGY:
 *   1. Start with the stored ordered keys.
 *   2. Drop any stored entries whose key no longer exists in DEFAULT_COLUMNS
 *      (column was removed in a code change → don't try to render it).
 *   3. Append any DEFAULT_COLUMNS keys NOT already present, in default order.
 *      → New columns added in code surface to existing users automatically.
 *   4. For each entry, take the user's `visible` choice but always pull
 *      `label`/`align`/`formatter`/`sortable` from DEFAULT_COLUMNS so a code
 *      change to those fields takes effect immediately.
 *
 * WHY this strategy: keeps user preferences (visible + order) authoritative
 * while letting code-side fixes (label typos, align changes) ship without a
 * forced reset.
 */
export function loadColumnPrefs(): ScreenerColumn[] {
  if (!isBrowser()) return cloneDefaults();
  try {
    const raw = window.localStorage.getItem(SCREENER_COLUMNS_KEY);
    if (!raw) return cloneDefaults();
    const stored: unknown = JSON.parse(raw);
    if (!Array.isArray(stored)) return cloneDefaults();

    // Build a quick lookup of defaults by key — this is the source of truth
    // for label/align/formatter/sortable.
    const defaultsByKey = new Map<string, ScreenerColumn>(
      DEFAULT_COLUMNS.map((c) => [c.key, { ...c }]),
    );

    const seen = new Set<string>();
    const merged: ScreenerColumn[] = [];

    // Step 1+2+4: walk stored entries, keep those whose key still exists.
    for (const entry of stored as Array<{ key?: unknown; visible?: unknown }>) {
      if (!entry || typeof entry !== "object" || typeof entry.key !== "string") continue;
      const def = defaultsByKey.get(entry.key);
      if (!def) continue; // dropped column
      if (seen.has(entry.key)) continue; // duplicates → keep first occurrence
      merged.push({
        ...def,
        // WHY `!== false`: missing visible field defaults to true, matches the
        // user's likely intent (they had it visible before the bug that wiped it).
        visible: entry.visible !== false,
      });
      seen.add(entry.key);
    }

    // Step 3: append any default columns not yet seen (newly added in code).
    for (const def of DEFAULT_COLUMNS) {
      if (!seen.has(def.key)) merged.push({ ...def });
    }

    return merged;
  } catch {
    // Same fallback as saved-screens.ts: corrupt JSON / Safari Private mode →
    // serve defaults instead of crashing.
    return cloneDefaults();
  }
}

/**
 * saveColumnPrefs — persist the user's column choices.
 *
 * WHY only persist key + visible (NOT label/align/etc.):
 *   - label/align/formatter come from DEFAULT_COLUMNS at load time. Persisting
 *     them too would freeze them to the version the user had on first save —
 *     so a label fix in code would never surface. Storing only key + visible
 *     keeps localStorage as a thin user-pref layer, with code authoritative for
 *     everything else.
 *   - Smaller payload = faster setItem (insignificant here, but good hygiene).
 */
export function saveColumnPrefs(cols: ScreenerColumn[]): void {
  if (!isBrowser()) return;
  try {
    const payload = cols.map((c) => ({ key: c.key, visible: c.visible }));
    window.localStorage.setItem(SCREENER_COLUMNS_KEY, JSON.stringify(payload));
  } catch {
    // Quota exceeded / private mode — silently no-op. The in-memory state still
    // works; the user just loses persistence across reloads.
  }
}

/**
 * resetColumnPrefs — convenience for the popover "Reset" button.
 *
 * WHY explicit (instead of asking the popover to localStorage.removeItem):
 *   - Encapsulates the storage key, so the UI never needs to know it.
 *   - Returns the fresh defaults so the caller can update React state in one go.
 */
export function resetColumnPrefs(): ScreenerColumn[] {
  if (isBrowser()) {
    try {
      window.localStorage.removeItem(SCREENER_COLUMNS_KEY);
    } catch {
      // ignore — same reasoning as saveColumnPrefs
    }
  }
  return cloneDefaults();
}
