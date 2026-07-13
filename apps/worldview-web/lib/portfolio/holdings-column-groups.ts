/**
 * lib/portfolio/holdings-column-groups.ts — Core/Portfolio/Advanced column-group
 * membership, persistence, and visibility computation for the holdings table
 * (PLAN-0122 W-E, PRD-0122 §6.7).
 *
 * WHY THIS EXISTS: the holdings table has 15 data columns + a locked ACTIONS
 * kebab. Casual users are overwhelmed by all of them; power users want them all.
 * §6.7 partitions the columns into three GROUPS the user toggles as a unit:
 *   • Core     — always on (the Simple-mode set): ticker, qty, avg_cost, current,
 *                value, pnl, actions.
 *   • Portfolio— name, dayChange, dayChangePct, pnlPct, weight.
 *   • Advanced — spark, sector, asset, divYld.
 * This module is the SINGLE SOURCE OF TRUTH for that membership + the persisted
 * enabled-groups state. The AG-Grid ColDef array (`ag-holdings-columns.tsx`)
 * also carries a `group` field per colId for locality, but the authoritative
 * map + the visibility maths live HERE so the table, the ⚙ toggle, and the tests
 * all read from one place.
 *
 * WHY TWO ORTHOGONAL localStorage KEYS (R-25): AG-Grid already persists per-column
 * WIDTH + ORDER (+ its own visibility) under `worldview-holdings-cols` via
 * `applyColumnState`. This module persists the higher-level GROUP visibility under
 * `worldview:holdingsColGroups:v1`. They are deliberately orthogonal:
 *   - `worldview-holdings-cols`      = widths / order (AG-Grid's own state restore)
 *   - `worldview:holdingsColGroups:v1` = which GROUPS are shown (this layer)
 * The group layer is applied AFTER the AG-Grid restore (see SemanticHoldingsTable
 * `handleGridReady`) so it is the higher-level control and always wins on
 * visibility, while widths/order still come from the AG-Grid key.
 *
 * WHY `divYld` IS SPECIAL: it belongs to the Advanced group but keeps its OWN
 * `hide: true` default in the ColDef (§6.7 / OQ-5). The group layer therefore
 * NEVER force-SHOWS divYld — even when the Advanced group is enabled. It only
 * force-HIDES divYld when the Advanced group is OFF. When Advanced is on, divYld
 * is left to its own hide flag / AG-Grid's per-column menu, so a user can show it
 * individually without flipping any group. This is what makes "Advanced default =
 * every column except divYld" (today's layout, US-B1) true.
 */

// ── Group identity ────────────────────────────────────────────────────────────
export type HoldingsColGroup = "core" | "portfolio" | "advanced";

/**
 * HoldingsColGroups — the persisted enabled-state, one boolean per group.
 * `core` is always `true` (locked); it is stored explicitly so a corrupted/older
 * blob still round-trips to a well-formed object.
 */
export interface HoldingsColGroups {
  core: boolean;
  portfolio: boolean;
  advanced: boolean;
}

// ── colId → group membership (R-24, PRD §6.7) ────────────────────────────────
// EVERY holdings colId (15 data + `actions`) MUST appear here exactly once — the
// membership test (`test_column_groups_membership_and_lock`) asserts no colId is
// orphaned and the ColDef array + this map agree.
export const COLUMN_GROUPS: Record<string, HoldingsColGroup> = {
  // Core (always on; Simple-mode set) — 6 data + actions.
  ticker: "core",
  qty: "core",
  avg_cost: "core",
  current: "core",
  value: "core",
  pnl: "core",
  actions: "core",
  // Portfolio — 5.
  name: "portfolio",
  dayChange: "portfolio",
  dayChangePct: "portfolio",
  pnlPct: "portfolio",
  weight: "portfolio",
  // Advanced — 4.
  spark: "advanced",
  sector: "advanced",
  asset: "advanced",
  divYld: "advanced",
};

/**
 * LOCKED_COL_IDS — columns that anchor the row and are NEVER hideable by the
 * group toggle (§6.7): `ticker` (pinned-left) and `actions` (pinned-right). They
 * live in the Core group but are additionally force-visible so that even a
 * corrupt saved state can never hide them.
 */
export const LOCKED_COL_IDS = ["ticker", "actions"] as const;

/**
 * SELF_HIDDEN_COL_IDS — columns that carry their OWN `hide: true` ColDef default
 * and must NOT be force-shown by the group layer even when their group is enabled
 * (today only `divYld`). The group layer may only force-HIDE these (when their
 * group is disabled); when the group is on it leaves them to their own hide flag /
 * AG-Grid's per-column menu. See the file header for the full rationale.
 */
export const SELF_HIDDEN_COL_IDS = ["divYld"] as const;

// ── Persistence config (R-25) ─────────────────────────────────────────────────
export const HOLDINGS_COL_GROUPS_KEY = "worldview:holdingsColGroups:v1";

/**
 * ADVANCED_GROUP_DEFAULT — the default when nothing is saved / state is corrupt.
 * All three groups on → every column visible EXCEPT `divYld` (which keeps its own
 * `hide:true`). This reproduces today's Advanced layout (US-B1 / anti-fork).
 */
export const ADVANCED_GROUP_DEFAULT: HoldingsColGroups = {
  core: true,
  portfolio: true,
  advanced: true,
};

/**
 * SIMPLE_GROUPS — the forced Core-only set for Simple mode (§6.1 / §6.7). Simple
 * always shows exactly the Core group regardless of the user's saved Advanced
 * choice; leaving Simple restores the saved choice (the saved blob is untouched).
 */
export const SIMPLE_GROUPS: HoldingsColGroups = {
  core: true,
  portfolio: false,
  advanced: false,
};

// ── Membership helpers ────────────────────────────────────────────────────────

/**
 * colIdsForGroups — the union of colIds belonging to any ENABLED group. Includes
 * locked cols and `divYld` (raw membership); the visibility partition below
 * applies the locked / self-hidden carve-outs. `core` is coerced on so a
 * hand-built `{core:false}` can never orphan the anchors.
 */
export function colIdsForGroups(groups: HoldingsColGroups): string[] {
  const enabled: HoldingsColGroups = { ...groups, core: true };
  return Object.keys(COLUMN_GROUPS).filter((colId) => enabled[COLUMN_GROUPS[colId]]);
}

/**
 * computeGroupVisibility — turn an enabled-groups state into the exact
 * `setColumnsVisible` argument lists the table applies AFTER the AG-Grid restore.
 *
 * Returns `{ show, hide }` where:
 *   - `show` = toggleable colIds whose group is enabled (NEVER includes locked or
 *     self-hidden `divYld` — those are handled separately).
 *   - `hide` = toggleable colIds whose group is disabled, PLUS `divYld` when its
 *     Advanced group is off (so Advanced-off cleanly hides the intraday extras).
 *   - locked cols (`ticker`, `actions`) are omitted from both — the table
 *     force-shows them unconditionally.
 */
export function computeGroupVisibility(groups: HoldingsColGroups): {
  show: string[];
  hide: string[];
} {
  const enabled = new Set(colIdsForGroups(groups));
  const locked = new Set<string>(LOCKED_COL_IDS);
  const selfHidden = new Set<string>(SELF_HIDDEN_COL_IDS);
  const show: string[] = [];
  const hide: string[] = [];

  for (const colId of Object.keys(COLUMN_GROUPS)) {
    if (locked.has(colId)) continue; // always visible — handled by the table
    if (selfHidden.has(colId)) {
      // divYld: never force-shown by the group layer. Only force-hidden when its
      // group is disabled; when enabled we leave its own hide flag / column menu.
      if (!enabled.has(colId)) hide.push(colId);
      continue;
    }
    if (enabled.has(colId)) show.push(colId);
    else hide.push(colId);
  }
  return { show, hide };
}

/**
 * groupStateForMode — the effective group state for a render mode. Simple always
 * forces the Core-only set; Advanced uses the saved (or provided) state. This is
 * the single decision point the table uses so the Simple/Advanced interaction
 * (R-26) lives in one testable place.
 */
export function groupStateForMode(
  mode: "simple" | "advanced",
  saved?: HoldingsColGroups,
): HoldingsColGroups {
  return mode === "simple" ? SIMPLE_GROUPS : (saved ?? loadGroupState());
}

// ── localStorage round-trip (R-25) ────────────────────────────────────────────

/**
 * loadGroupState — read the saved enabled-groups blob. Absent, corrupt, or
 * malformed → `ADVANCED_GROUP_DEFAULT` (today's layout). `core` is always coerced
 * to `true` and unknown keys are dropped so a forward/older blob still yields a
 * well-formed object. SSR-safe (no `window` → default).
 */
export function loadGroupState(): HoldingsColGroups {
  if (typeof window === "undefined") return { ...ADVANCED_GROUP_DEFAULT };
  try {
    const raw = window.localStorage.getItem(HOLDINGS_COL_GROUPS_KEY);
    if (!raw) return { ...ADVANCED_GROUP_DEFAULT };
    const parsed = JSON.parse(raw) as Partial<HoldingsColGroups> | null;
    if (!parsed || typeof parsed !== "object") return { ...ADVANCED_GROUP_DEFAULT };
    return {
      // core is locked-on regardless of what was persisted.
      core: true,
      portfolio: typeof parsed.portfolio === "boolean" ? parsed.portfolio : true,
      advanced: typeof parsed.advanced === "boolean" ? parsed.advanced : true,
    };
  } catch {
    // Corrupt JSON / storage access error → safe default (today's layout).
    return { ...ADVANCED_GROUP_DEFAULT };
  }
}

/**
 * saveGroupState — persist the enabled-groups blob. `core` is normalised to
 * `true` before writing so the stored value can never claim Core is off. Storage
 * failures (quota, private mode) are swallowed — the choice still applies
 * in-session, it just won't survive a reload (same tolerance as the AG-Grid
 * column-state persistence).
 */
export function saveGroupState(groups: HoldingsColGroups): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      HOLDINGS_COL_GROUPS_KEY,
      JSON.stringify({ ...groups, core: true }),
    );
  } catch {
    /* storage full / unavailable — view-only for this session */
  }
}
