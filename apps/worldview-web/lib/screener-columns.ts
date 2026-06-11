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

/**
 * SCORE_HIDDEN_MIGRATION_KEY — one-time migration marker (Wave-2, 2026-06-10).
 *
 * WHY THIS EXISTS: the SCORE column default flipped visible:true → false
 * because market_impact_score has no backend data source (permanently "—").
 * loadColumnPrefs deliberately keeps the USER's stored `visible` choice
 * authoritative — which means anyone whose prefs were written while score
 * defaulted to visible:true would keep seeing the dead column forever. This
 * marker lets the read path coerce score → hidden EXACTLY ONCE:
 *   - marker absent  → force score.visible = false, persist, set marker.
 *   - marker present → the user's choice wins again (so deliberately
 *     re-enabling score from the popover sticks across reloads — important
 *     for when the backend eventually ships the score and users opt back in).
 *
 * WHY not a v1→v2 storage-key bump: a key bump would wipe ALL column prefs
 * (order + every visibility choice) to change one flag — needlessly hostile.
 */
export const SCORE_HIDDEN_MIGRATION_KEY =
  "worldview:screenerColumns:scoreHiddenMigration:v1";

/**
 * ESSENTIAL_COLUMN_KEYS — columns that can NEVER be hidden (Round 2).
 *
 * WHY: ticker is the row's identity (and the row-click navigation key); name
 * is the only human-readable disambiguator (three tickers can look alike).
 * A table where the user hid both is unusable — every cell becomes context-
 * free numbers — and "why is my screener empty-looking" is a support ticket
 * we can avoid structurally. The popover renders these rows with a disabled
 * checkbox, and loadColumnPrefs() coerces them visible on read so stale
 * localStorage written BEFORE this rule existed can't resurrect a hidden
 * ticker column.
 */
export const ESSENTIAL_COLUMN_KEYS: readonly string[] = Object.freeze(["ticker", "name"]);

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
  // ── Default-visible columns ─────────────────────────────────────────────────
  Object.freeze({ key: "ticker",        label: "Ticker",      sortable: true,  align: "left",  formatter: "text" as const,    visible: true }),
  Object.freeze({ key: "name",          label: "Name",        sortable: true,  align: "left",  formatter: "text" as const,    visible: true }),
  Object.freeze({ key: "sector",        label: "Sector",      sortable: true,  align: "left",  formatter: "text" as const,    visible: true }),
  Object.freeze({ key: "price",         label: "Price",       sortable: true,  align: "right", formatter: "price" as const,   visible: true }),
  Object.freeze({ key: "change",        label: "Chg%",        sortable: true,  align: "right", formatter: "percent" as const, visible: true }),
  Object.freeze({ key: "marketCap",     label: "Mkt Cap",     sortable: true,  align: "right", formatter: "compact" as const, visible: true }),
  Object.freeze({ key: "pe",            label: "P/E",         sortable: true,  align: "right", formatter: "number" as const,  visible: true }),
  // PLAN-0092 Wave C: replaced revenue with revenue growth; added fwdPe, divYield, roe
  Object.freeze({ key: "revenueGrowth", label: "Rev YoY%",    sortable: true,  align: "right", formatter: "percent" as const, visible: true }),
  // ── forwardPe demoted to opt-in (PRD-0089 §6.3 14-column cap, QA finding #1) ─
  // WHY visible: false (was true in PLAN-0092 Wave C):
  //   - PRD-0089 plan §6.3 caps default-visible columns at ≤14 above the fold at
  //     1440×900 to hit the 240–280 visible body-cell density target (20 rows ×
  //     12–14 cols). Wave I-B QA flagged we were shipping 15 — one over budget.
  //   - Of the candidates, Fwd P/E is the most natural drop: it is HIGHLY
  //     correlated with the already-visible trailing P/E (rank correlation
  //     ~0.85 across the S&P 500 ex-loss-makers), so the marginal information
  //     gained from showing both side-by-side is small for a general-purpose
  //     default. P/E is the more universal "first glance" multiple.
  //   - Forward P/E remains FIRST-CLASS: surfaced as an opt-in toggle in
  //     ColumnSettingsPopover (Valuation group) and is the natural inclusion in
  //     a "Compounder" or "Growth-at-a-reasonable-price" saved screen where the
  //     user explicitly opts into forward-looking valuation.
  //   - Regression guard: see lib/__tests__/screener-columns.test.ts —
  //     `DEFAULT_COLUMNS.filter(c => c.visible).length === 14` is asserted to
  //     prevent the count from drifting back up next time we add a column.
  Object.freeze({ key: "forwardPe",     label: "Fwd P/E",     sortable: true,  align: "right", formatter: "number" as const,  visible: false }),
  Object.freeze({ key: "divYield",      label: "Div Y%",      sortable: true,  align: "right", formatter: "percent" as const, visible: true }),
  Object.freeze({ key: "roe",           label: "ROE%",        sortable: true,  align: "right", formatter: "percent" as const, visible: true }),
  Object.freeze({ key: "beta",          label: "Beta",        sortable: true,  align: "right", formatter: "number" as const,  visible: true }),
  // ── score demoted to opt-in (Wave-2, 2026-06-10) ────────────────────────────
  // WHY visible: false (was true): market_impact_score has NO backend data
  // source — the Wave-2 live audit confirmed the field is absent from every
  // screener row (default and filtered views alike; the PRD-0020 scoring
  // pipeline never shipped a screener projection). A column that renders "—"
  // on 100% of rows forever erodes trust in every other dash in the table.
  // The entry STAYS in the catalogue (not deleted) so:
  //   - ColumnSettingsPopover still lists it — users can opt in the moment
  //     the backend ships data (the ColDef + HeatCell renderer still work).
  //   - Saved column orders that include "score" keep merging cleanly.
  // Stale localStorage written when this defaulted to visible:true is healed
  // by the one-time migration in loadColumnPrefs (SCORE_HIDDEN_MIGRATION_KEY).
  Object.freeze({ key: "score",         label: "Score",       sortable: true,  align: "right",                                visible: false }),
  Object.freeze({ key: "range52w",      label: "52W Range",   sortable: false, align: "right",                                visible: true }),
  Object.freeze({ key: "sparkline",     label: "Trend (30d)", sortable: false, align: "right",                                visible: true }),
  // ── Opt-in columns (hidden by default — user reveals via ⚙ popover) ─────────
  // WHY hidden by default: these metrics are valuable for specific strategies but
  // add column width that crowds the 12-column default layout at 1440px.
  Object.freeze({ key: "opMargin",      label: "OP MGN%",     sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "evEbitda",      label: "EV/EBITDA",   sortable: true,  align: "right", formatter: "number" as const,  visible: false }),
  // ── PRD-0089 Wave I-B Block IB-L2 (T-IB-05): fundamentals snapshot opt-ins ──
  // WHY listed here AS WELL as in `ag-screener-columns.tsx`:
  //   - The popover (gear ⚙ icon) reads from THIS file to show toggle rows.
  //   - The AG-Grid columns file reads from ITSELF for the ColDef factory.
  //   - The page maps user prefs → AG-Grid visibility via colId === key.
  // So a column must be declared in BOTH places to (a) appear in the popover
  // and (b) actually have a ColDef. The key field must match the colId.
  //
  // FORMATTER MAPPING:
  //   - "compact"  → 50M / $1.2B style (no decimals on avg-vol, 1dp on FCF).
  //   - "number"   → fixed 2dp (eps_ttm: 6.32) / fixed 1dp (multiples).
  //   - "percent"  → 28.4% (FCF margin).
  //   - "text"     → raw string (credit rating, badge-rendered by colDef).
  // The popover doesn't use these directly today — they're recorded for the
  // future legacy TanStack table renderer if it gets resurrected. The AG-Grid
  // path picks its renderer per-column from ag-screener-columns.tsx.
  Object.freeze({ key: "avgVol",           label: "Avg Vol",     sortable: true,  align: "right", formatter: "compact" as const, visible: false }),
  Object.freeze({ key: "epsTtm",           label: "EPS (TTM)",   sortable: true,  align: "right", formatter: "number" as const,  visible: false }),
  Object.freeze({ key: "fcf",              label: "FCF",         sortable: true,  align: "right", formatter: "compact" as const, visible: false }),
  Object.freeze({ key: "fcfMargin",        label: "FCF Mgn%",    sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "interestCoverage", label: "Int Cov",     sortable: true,  align: "right", formatter: "number" as const,  visible: false }),
  Object.freeze({ key: "netDebtToEbitda",  label: "ND/EBITDA",   sortable: true,  align: "right", formatter: "number" as const,  visible: false }),
  // creditRating uses a custom badge renderer (no formatter). sortable=false —
  // see ag-screener-columns.tsx CreditRatingCellRenderer for the rationale
  // (lexical sort would mis-order tiers).
  Object.freeze({ key: "creditRating",     label: "Credit Rating", sortable: false, align: "right",                                visible: false }),
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

/**
 * markScoreMigrationDone — flag the Wave-2 score-hidden migration as applied.
 * Best-effort: quota/private-mode failures are swallowed (same policy as
 * saveColumnPrefs) — worst case the coercion re-runs on the next load, which
 * is idempotent (it only flips score visible→hidden, never the reverse).
 */
function markScoreMigrationDone(): void {
  try {
    window.localStorage.setItem(SCORE_HIDDEN_MIGRATION_KEY, "1");
  } catch {
    // ignore — see docstring
  }
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
    if (!raw) {
      // No stored prefs — the new defaults (score hidden) apply directly.
      // Set the migration marker NOW so that if the user later opts back
      // INTO score via the popover, the coercion below can never revert
      // their deliberate choice on a subsequent load.
      markScoreMigrationDone();
      return cloneDefaults();
    }
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
        // WHY the ESSENTIAL override: ticker/name are non-hideable (Round 2);
        // prefs saved before that rule existed may carry visible:false for
        // them — coercing on READ heals stale storage without a migration.
        visible: ESSENTIAL_COLUMN_KEYS.includes(entry.key) || entry.visible !== false,
      });
      seen.add(entry.key);
    }

    // Step 3: append any default columns not yet seen (newly added in code).
    for (const def of DEFAULT_COLUMNS) {
      if (!seen.has(def.key)) merged.push({ ...def });
    }

    // ── Wave-2 one-time SCORE migration (see SCORE_HIDDEN_MIGRATION_KEY) ────
    // Stored prefs written while score defaulted to visible:true would keep
    // the dead column on screen forever (user `visible` choices win in the
    // merge above, by design). Coerce it hidden exactly once, persist the
    // result, and never touch it again — so a user who deliberately
    // re-enables score from the popover AFTER this migration keeps it.
    if (window.localStorage.getItem(SCORE_HIDDEN_MIGRATION_KEY) === null) {
      const score = merged.find((c) => c.key === "score");
      if (score && score.visible) {
        score.visible = false;
        // Persist the migrated state so saveColumnPrefs-free sessions (user
        // never opens the popover) still read score-hidden on the next load.
        saveColumnPrefs(merged);
      }
      markScoreMigrationDone();
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
