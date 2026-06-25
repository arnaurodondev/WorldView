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
  // ── sparkline (TREND 30d): demoted to opt-in (DESIGN-QA S-1, 2026-06-18) ────
  // WHY visible: false (was true): the TREND (30d) sparkline column shipped ON
  // by default but rendered EMPTY on every row in the deployed build — the
  // design audit's single biggest "this looks broken" finding on the flagship
  // page. A trend/sparkline column must render real data or not exist by
  // default; it must never sit as a dead placeholder at rest (cross-cutting
  // global rule #1 in DESIGN-QA.md).
  //
  // WHY OPT-IN (not deleted): the data path IS real — useScreenerSparklines
  // batches POST /v1/quotes/bars/batch and MiniChart renders a proper coloured
  // line whenever bars arrive. The column simply has no reliable per-row bar
  // coverage in this deployment yet. Same treatment as `score`/`forwardPe`:
  // keep it first-class and selectable in ColumnSettingsPopover so a user can
  // opt in (and a "Momentum" saved screen can include it) the moment coverage
  // lands — no code change needed. When OFF, MiniChart never mounts, so no
  // empty cells are shown by default.
  //
  // DENSITY: removing one default-visible column here is offset by promoting
  // `briefScore` (a real IB-L5 data column) below, keeping the §6.3 cap at
  // exactly 14 AND swapping a dead column for a populated one (helps S-2:
  // fills the right-side whitespace with information instead of a void).
  Object.freeze({ key: "sparkline",     label: "Trend (30d)", sortable: false, align: "right",                                visible: false }),

  // ════════════════════════════════════════════════════════════════════════════
  // CATALOGUE-RECONCILIATION (2026-06-18, screener-frontend audit §2.5)
  // ════════════════════════════════════════════════════════════════════════════
  // WHY THIS WHOLE BLOCK CHANGED:
  //   The audit (docs/audits/2026-06-16-prd0089-screener-frontend.md §2.5) found
  //   the screener had TWO column lists that must agree but had silently drifted:
  //     1. The AG-Grid ColDefs (components/screener/ag-screener-columns.tsx) —
  //        these define which columns actually RENDER + their cell renderers.
  //     2. This DEFAULT_COLUMNS catalogue — the ONLY list ColumnSettingsPopover
  //        shows the user, and the ONLY set of colIds page.tsx feeds to
  //        gridApi.applyColumnState() to toggle visibility.
  //   The drift meant:
  //     - 16 real ColDefs (all IB-L3 returns, all IB-L4 ownership, the two IB-L5
  //       intelligence columns, plus `revenue` and `volume`) had NO catalogue
  //       entry → the user could never reveal them via the ⚙ popover, even though
  //       the data + renderers existed. Permanently-hidden dead columns.
  //     - 8 catalogue keys (evEbitda, avgVol, epsTtm, fcf, fcfMargin,
  //       interestCoverage, netDebtToEbitda, creditRating) had NO matching
  //       ColDef → toggling them in the popover was a silent no-op (nothing to
  //       show/hide). Those 8 dead keys are REMOVED below.
  //
  // RECONCILIATION RULE (now guarded by a test — see
  //   lib/__tests__/screener-columns.test.ts "ColDef/catalogue parity"):
  //     The set of catalogue keys MUST exactly equal the set of leaf ColDef
  //     colIds. Every ColDef is now selectable in the popover; every popover key
  //     maps to a real ColDef. This invariant cannot silently regress again.
  //
  // VISIBILITY POLICY (the 14-column default-visible cap, §6.3):
  //   The catalogue's `visible` flags are AUTHORITATIVE at runtime — page.tsx's
  //   applyColumnState() overrides each ColDef's own `hide` default. So even
  //   though `revenue`/`volume`/`briefScore` ColDefs have no `hide:true`, they
  //   render HIDDEN until the user opts in, because their catalogue entries are
  //   visible:false. Only `news7d` is promoted to default-visible (the single
  //   highest-signal IB-L5 column — see the IB-L5 group comment in
  //   ag-screener-columns.tsx), keeping the default-visible count at exactly 14.
  //
  // WHY `formatter` is omitted on the bar/visual columns (range52w handled above,
  //   news7d/briefScore/range): those use custom AG-Grid cell renderers, not the
  //   legacy TanStack formatter path — same convention as `score` above.

  // ── opMargin: opt-in (was already in the catalogue; kept) ───────────────────
  Object.freeze({ key: "opMargin",      label: "OP MGN%",     sortable: true,  align: "right", formatter: "percent" as const, visible: false }),

  // ── revenue: had a ColDef but NO catalogue entry → could not be hidden. Now
  //    selectable (opt-in: REV YoY% covers the common case; raw revenue is a
  //    power-user column). ────────────────────────────────────────────────────
  Object.freeze({ key: "revenue",       label: "Revenue",     sortable: true,  align: "right", formatter: "compact" as const, visible: false }),

  // ── IB-L3 — Performance / Returns + 52W distance (opt-in) ───────────────────
  // All 8 had ColDefs + renderers + live server-side filters but were
  // unreachable from the popover before this fix.
  Object.freeze({ key: "dist52wHigh",   label: "52W% ↑",      sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "dist52wLow",    label: "52W% ↓",      sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "return1m",      label: "1M RTN",      sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "return3m",      label: "3M RTN",      sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "return6m",      label: "6M RTN",      sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "returnYtd",     label: "YTD RTN",     sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "return1y",      label: "1Y RTN",      sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "return3y",      label: "3Y RTN",      sortable: true,  align: "right", formatter: "percent" as const, visible: false }),

  // ── IB-L4 — Analyst / Insider / Ownership (opt-in) ──────────────────────────
  // 5 backend fields + 1 client-derived (analystUpside). All had ColDefs but no
  // catalogue entry.
  Object.freeze({ key: "analystTarget",    label: "Analyst Tgt",    sortable: true,  align: "right", formatter: "price" as const,   visible: false }),
  Object.freeze({ key: "analystUpside",    label: "Analyst Upside", sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "analystConsensus", label: "Consensus",      sortable: true,  align: "right", formatter: "number" as const,  visible: false }),
  Object.freeze({ key: "insiderNet90d",    label: "Insider 90d",    sortable: true,  align: "right", formatter: "compact" as const, visible: false }),
  Object.freeze({ key: "instOwn",          label: "Inst Own%",      sortable: true,  align: "right", formatter: "percent" as const, visible: false }),
  Object.freeze({ key: "shortPct",         label: "Short %",        sortable: true,  align: "right", formatter: "percent" as const, visible: false }),

  // ── IB-L5 — Intelligence rollup ─────────────────────────────────────────────
  // news7d is DEFAULT-VISIBLE (the headline intelligence-moat column EQS cannot
  // express); briefScore is opt-in to stay within the 14-column cap.
  Object.freeze({ key: "news7d",        label: "News 7d",     sortable: true,  align: "right", formatter: "number" as const,  visible: true }),
  // ── briefScore: promoted to default-visible (DESIGN-QA S-1/S-2, 2026-06-18) ──
  // WHY visible: true (was false): it takes the default-visible slot freed by
  // demoting the dead `sparkline` column above. briefScore renders REAL data
  // (display_relevance_7d_weighted from the L-5b rollup) so it fills the
  // right-side whitespace with an intelligence signal EQS-style screeners
  // cannot express — exactly the "richer default columns" S-2 asks for —
  // instead of a perpetually-empty trend cell. Net default-visible count stays
  // at the §6.3 cap of 14 (sparkline −1, briefScore +1).
  Object.freeze({ key: "briefScore",    label: "Brief Score", sortable: true,  align: "right", formatter: "number" as const,  visible: true }),

  // ── volume: had a ColDef but no catalogue entry → could not be hidden. Now
  //    selectable (opt-in). ────────────────────────────────────────────────────
  Object.freeze({ key: "volume",        label: "Volume",      sortable: true,  align: "right", formatter: "compact" as const, visible: false }),
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
