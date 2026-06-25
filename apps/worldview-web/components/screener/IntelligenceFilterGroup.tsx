/**
 * components/screener/IntelligenceFilterGroup.tsx — 7-row Intelligence filter section
 * (PRD-0089 Wave I-A · Block B · T-IA-07 / IB-L5 unlock)
 *
 * WHY THIS EXISTS:
 *   Wave I-A scaffolded all 7 rows disabled. IB-L5 flips the 5 backend-ready
 *   flags (newsCount7d / aiBrief / activeAlert / contradictions / llmRelevance)
 *   to `true` and wires up real interactive controls for those rows. The
 *   remaining 2 (upcomingEarnings / upcomingDividend) stay disabled until a
 *   future wave delivers their S3 calendar fields.
 *
 * THE 7 FILTERS:
 *   1. NEWS COUNT 7D (IB-L5 ✓)  — integer range: articles in the past week.
 *   2. AI BRIEF      (IB-L5 ✓)  — boolean toggle: has_ai_brief = true.
 *   3. ACTIVE ALERT  (IB-L5 ✓)  — boolean toggle: has_active_alert = true.
 *   4. CONTRADICTIONS (IB-L5 ✓) — integer range: recent_contradiction_count.
 *   5. LLM RELEVANCE  (IB-L5 ✓) — float range (0–1): display_relevance_7d_weighted.
 *   6. UPCOMING EARNINGS (future) — pending S3 earnings calendar field.
 *   7. UPCOMING DIVIDEND (future) — pending S3 dividend calendar field.
 *
 *   WHY rendered even when disabled: discoverability. A disabled row teaches
 *   the user the feature exists — a missing row does not.
 *
 * WHO USES IT:
 *   - `components/screener/ScreenerFilterBar.tsx` (7th section).
 *
 * PLAN REF: docs/plans/0089-pages/I-screener-plan.md §5.1 T-IA-07
 */

"use client";
// WHY "use client": interactive inputs (number fields, checkboxes) require
// browser event handlers which are not compatible with React Server Components.

import { cn } from "@/lib/utils";
import { Section } from "@/features/screener/components/Section";
import { BackendPendingBadge } from "@/components/ui/backend-pending-badge";
import type { FilterState } from "@/features/screener/lib/filter-state";
import { rangeCount } from "@/features/screener/lib/active-counts";

// ── Props ────────────────────────────────────────────────────────────────────

/**
 * IntelligenceBackendReady — one flag per Intelligence filter row.
 *
 * IB-L5 baseline: newsCount7d / aiBrief / activeAlert / contradictions /
 * llmRelevance default to TRUE. upcomingEarnings / upcomingDividend remain
 * FALSE until a future wave delivers their S3 calendar backend fields.
 *
 * WHY typed object keys (not array): exhaustiveness — TypeScript will warn if
 * a new row is added without updating both this type and the JSX.
 */
export interface IntelligenceBackendReady {
  newsCount7d: boolean;
  aiBrief: boolean;
  activeAlert: boolean;
  contradictions: boolean;
  llmRelevance: boolean;
  upcomingEarnings: boolean;
  upcomingDividend: boolean;
}

/**
 * IB_L5_DEFAULTS — the post-IB-L5c baseline. ALL 7 rollup/calendar fields are
 * now live.
 *
 * WHY upcomingEarnings/upcomingDividend flipped to true (IB-L5c, 2026-06-18):
 * the L-5c backend shipped the calendar columns next_earnings_within_days /
 * next_dividend_within_days on instrument_fundamentals_snapshot, so the last 2
 * BackendPendingBadge rows are wired live (see ROW 6/7 below). No backend-pending
 * rows remain at the IB-L5c baseline.
 *
 * WHY a named constant (not inline): the test suite imports this to verify
 * the default state without re-declaring it. Keeps tests in sync automatically
 * if the defaults ever change.
 */
export const IB_L5_DEFAULTS: IntelligenceBackendReady = {
  newsCount7d: true,
  aiBrief: true,
  activeAlert: true,
  contradictions: true,
  llmRelevance: true,
  upcomingEarnings: true,
  upcomingDividend: true,
};

export interface IntelligenceFilterGroupProps {
  /** Current filter state — read from FilterState for IB-L5 fields. */
  value: FilterState;
  /** Patch handler — called with the full updated FilterState. */
  onChange: (next: FilterState) => void;
  /**
   * Per-row gating flags. When omitted, IB_L5_DEFAULTS applies (all 7 rows live
   * at the IB-L5c baseline). Pass `{ newsCount7d: false }` to re-disable a row
   * if needed for testing or staged rollouts.
   */
  backendReady?: Partial<IntelligenceBackendReady>;
  /**
   * IB-L5 stale-data indicator (T-IB5-04). ISO-8601 UTC timestamp of the last
   * S7→S3 intelligence rollup sync (`intelligence_rollup_synced_at`), read from
   * the screener response when present.
   *
   * WHY OPTIONAL + DEFENSIVE: a sibling agent is adding this field to the API;
   * it may be absent (older payloads, field not yet shipped). The stale pill
   * renders ONLY when the value parses to a real date AND its age exceeds the
   * 25h freshness threshold (the rollup runs nightly, so >25h means a missed
   * run). Absent/unparseable/fresh → nothing renders (no-op), so this never
   * shows a misleading "stale" warning on healthy or unknown data.
   */
  rollupSyncedAt?: string | null;
}

/**
 * STALE_ROLLUP_THRESHOLD_MS — age past which the intelligence rollup is "stale".
 *
 * WHY 25h: the L-5b/L-5c rollup is a nightly job. One full day plus a 1h grace
 * window means the pill only fires when a scheduled run was actually MISSED,
 * not merely because the clock crossed midnight. Exported so a test can pin the
 * threshold without re-deriving the arithmetic.
 */
export const STALE_ROLLUP_THRESHOLD_MS = 25 * 60 * 60 * 1000;

/**
 * computeRollupStaleHours — pure helper: given the sync timestamp and "now",
 * return the integer age in hours IF the data is stale, else null.
 *
 * WHY a pure exported function (not inline in the component): it encodes the
 * entire "should we warn?" decision (parse-guard + threshold) in one testable
 * unit, so the defensive behaviour (absent / unparseable / fresh → null) is
 * pinned by tests rather than buried in JSX.
 */
export function computeRollupStaleHours(
  rollupSyncedAt: string | null | undefined,
  now: number = Date.now(),
): number | null {
  if (!rollupSyncedAt) return null; // absent / null / "" → no-op
  const synced = Date.parse(rollupSyncedAt);
  if (Number.isNaN(synced)) return null; // unparseable → no-op (never crash)
  const ageMs = now - synced;
  if (ageMs <= STALE_ROLLUP_THRESHOLD_MS) return null; // fresh → no pill
  return Math.floor(ageMs / (60 * 60 * 1000));
}

// ── Internal shared style helpers ─────────────────────────────────────────────

// WHY centralised class strings: 5 numeric inputs share the same visual spec.
// Changing the design token once here updates all 5 simultaneously.
const inputCls =
  "h-6 w-20 px-1.5 text-[11px] font-mono tabular-nums bg-card border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary";

const inputDisabledCls =
  "h-6 w-20 px-1.5 text-[11px] font-mono tabular-nums bg-card border border-border rounded-[2px] text-muted-foreground placeholder:text-muted-foreground/50 cursor-not-allowed";

const labelCls =
  "text-[10px] font-mono uppercase tracking-[0.06em] w-32 shrink-0 text-muted-foreground";

// ── Component ────────────────────────────────────────────────────────────────

export function IntelligenceFilterGroup({
  value,
  onChange,
  backendReady,
  rollupSyncedAt,
}: IntelligenceFilterGroupProps) {
  // IB-L5 stale-data indicator (T-IB5-04). null when fresh/absent/unparseable
  // (the common case) → the pill is not rendered at all.
  const staleHours = computeRollupStaleHours(rollupSyncedAt);
  // WHY merge with IB_L5_DEFAULTS (not with all-false): the parent may pass
  // a partial override (e.g. `{ newsCount7d: false }` to re-gate one field
  // during an incident). Missing keys inherit the IB-L5 live baseline.
  const ready: IntelligenceBackendReady = {
    ...IB_L5_DEFAULTS,
    ...backendReady,
  };

  // Active count for the Section header badge. Counts each live filter that
  // has a value set — range filters count each set side independently.
  // WHY not imported from active-counts countActiveFiltersByGroup: that helper
  // returns a per-group map; reading it here would pull in the full FilterState
  // traversal just for the `intelligence` key. Inline is cheaper and explicit.
  const activeCount =
    rangeCount(value.newsCount7dMin, value.newsCount7dMax) +
    rangeCount(value.llmRelevance7dMin, value.llmRelevance7dMax) +
    rangeCount(value.displayRelevance7dMin, value.displayRelevance7dMax) +
    rangeCount(value.contradictionsMin, value.contradictionsMax) +
    (value.hasAiBrief === true ? 1 : 0) +
    (value.hasActiveAlert === true ? 1 : 0) +
    // IB-L5c calendar windows — each set "≤ N days" counts as one active filter.
    (value.upcomingEarningsWithinDays !== undefined ? 1 : 0) +
    (value.upcomingDividendWithinDays !== undefined ? 1 : 0);

  // ── Patch helper ──────────────────────────────────────────────────────────
  // WHY spread-merge (not Object.assign): keeps `value` immutable and produces
  // a new reference so React's referential-equality check detects the change.
  function patch(p: Partial<FilterState>) {
    onChange({ ...value, ...p });
  }

  // ── Number-field parse helper ─────────────────────────────────────────────
  // WHY parseFloat (not parseInt) for all numeric inputs: LLM relevance is a
  // 0–1 float. Using parseInt would silently truncate "0.7" to 0.
  function parseNum(raw: string): number | undefined {
    const n = parseFloat(raw);
    return Number.isFinite(n) ? n : undefined;
  }

  return (
    <Section
      title="Intelligence"
      activeCount={activeCount}
      headerExtra={
        // Stale-data pill — only mounts when the rollup is provably stale
        // (>25h). WHY warning tint + title tooltip: it is an advisory, not an
        // error — the filters still work, but the intelligence signals may be
        // up to N hours old. The native `title` gives a zero-dependency hover.
        staleHours != null ? (
          <span
            role="status"
            className="inline-flex items-center gap-1 rounded-[2px] bg-warning/10 px-1 py-px text-[9px] font-mono uppercase tracking-[0.06em] text-warning"
            title={`Intelligence rollup last synced ${staleHours}h ago — signals may be stale (nightly sync expected within 24h).`}
          >
            {staleHours}h stale
          </span>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-1.5">

        {/* ── ROW 1: NEWS COUNT 7D (IB-L5 ✓) ─────────────────────────────
          * Integer range filter → news_count_7d.
          * WHY only a min input (no max): the typical query is "at least N articles"
          * (coverage screen). A max would filter for instruments with very FEW articles
          * which is an unusual constraint. We expose both for completeness but the
          * label emphasises "≥". */}
        <div className="flex items-center gap-2 h-6" aria-disabled={!ready.newsCount7d}>
          <span className={labelCls}>News 7d ≥</span>
          <input
            type="number"
            min={0}
            step={1}
            aria-label={
              ready.newsCount7d
                ? "Minimum news articles in past 7 days"
                : "News 7d filter (backend pending)"
            }
            placeholder="min"
            disabled={!ready.newsCount7d}
            value={value.newsCount7dMin ?? ""}
            onChange={(e) => patch({ newsCount7dMin: parseNum(e.target.value) })}
            className={ready.newsCount7d ? inputCls : inputDisabledCls}
          />
          {!ready.newsCount7d && <BackendPendingBadge />}
        </div>

        {/* ── ROW 2: AI BRIEF (IB-L5 ✓) ──────────────────────────────────
          * Boolean toggle → has_ai_brief = true.
          * WHY a checkbox (not a text input): the field is a boolean — showing
          * a number input would mislead users into thinking it's a count. */}
        <div className="flex items-center gap-2 h-6" aria-disabled={!ready.aiBrief}>
          <span className={labelCls}>AI Brief</span>
          {ready.aiBrief ? (
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                aria-label="Only instruments with an AI brief"
                checked={value.hasAiBrief === true}
                onChange={(e) => patch({ hasAiBrief: e.target.checked ? true : undefined })}
                className="h-3.5 w-3.5 rounded-[2px] accent-primary"
              />
              <span className="text-[10px] font-mono text-muted-foreground">has brief</span>
            </label>
          ) : (
            <>
              <input
                type="text"
                aria-label="AI Brief filter (backend pending)"
                placeholder="has brief"
                disabled
                className={inputDisabledCls}
              />
              <BackendPendingBadge />
            </>
          )}
        </div>

        {/* ── ROW 3: ACTIVE ALERT (IB-L5 ✓) ──────────────────────────────
          * Boolean toggle → has_active_alert = true. Same boolean pattern
          * as AI Brief above. */}
        <div className="flex items-center gap-2 h-6" aria-disabled={!ready.activeAlert}>
          <span className={labelCls}>Active Alert</span>
          {ready.activeAlert ? (
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                aria-label="Only instruments with an active alert"
                checked={value.hasActiveAlert === true}
                onChange={(e) => patch({ hasActiveAlert: e.target.checked ? true : undefined })}
                className="h-3.5 w-3.5 rounded-[2px] accent-primary"
              />
              <span className="text-[10px] font-mono text-muted-foreground">has alert</span>
            </label>
          ) : (
            <>
              <input
                type="text"
                aria-label="Active Alert filter (backend pending)"
                placeholder="has alert"
                disabled
                className={inputDisabledCls}
              />
              <BackendPendingBadge />
            </>
          )}
        </div>

        {/* ── ROW 4: CONTRADICTIONS (IB-L5 ✓) ────────────────────────────
          * Integer range → recent_contradiction_count.
          * WHY a min input: screens for instruments with active KG contradictions
          * (often signals conflicting analyst narratives). */}
        <div className="flex items-center gap-2 h-6" aria-disabled={!ready.contradictions}>
          <span className={labelCls}>Contradictions ≥</span>
          <input
            type="number"
            min={0}
            step={1}
            aria-label={
              ready.contradictions
                ? "Minimum recent contradiction count"
                : "Contradictions filter (backend pending)"
            }
            placeholder="min"
            disabled={!ready.contradictions}
            value={value.contradictionsMin ?? ""}
            onChange={(e) => patch({ contradictionsMin: parseNum(e.target.value) })}
            className={ready.contradictions ? inputCls : inputDisabledCls}
          />
          {!ready.contradictions && <BackendPendingBadge />}
        </div>

        {/* ── ROW 5: LLM RELEVANCE (IB-L5 ✓) ─────────────────────────────
          * Float range (0–1) → display_relevance_7d_weighted.
          * WHY step=0.05: the score has 2 decimal precision; 0.05 steps let
          * users type "0.70" naturally in the number spinner. */}
        <div className="flex items-center gap-2 h-6" aria-disabled={!ready.llmRelevance}>
          <span className={labelCls}>LLM Relevance ≥</span>
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            aria-label={
              ready.llmRelevance
                ? "Minimum display relevance score (0–1)"
                : "LLM Relevance filter (backend pending)"
            }
            placeholder="0–1"
            disabled={!ready.llmRelevance}
            value={value.displayRelevance7dMin ?? ""}
            onChange={(e) => patch({ displayRelevance7dMin: parseNum(e.target.value) })}
            className={cn(ready.llmRelevance ? inputCls : inputDisabledCls)}
          />
          {!ready.llmRelevance && <BackendPendingBadge />}
        </div>

        {/* ── ROW 6: UPCOMING EARNINGS (IB-L5c ✓) ─────────────────────────
          * Integer "≤ N days" filter → next_earnings_within_days.
          * WHY only a max ("≤"): the canonical query is "names reporting in the
          * next N days" (an upper bound). build-filters maps it to the backend's
          * next_earnings_within_days_max named sibling. */}
        <div className="flex items-center gap-2 h-6" aria-disabled={!ready.upcomingEarnings}>
          <span className={labelCls}>Earnings ≤</span>
          <input
            type="number"
            min={0}
            step={1}
            aria-label={
              ready.upcomingEarnings
                ? "Maximum days until next earnings"
                : "Earnings filter (backend pending)"
            }
            placeholder="days"
            disabled={!ready.upcomingEarnings}
            value={value.upcomingEarningsWithinDays ?? ""}
            onChange={(e) => patch({ upcomingEarningsWithinDays: parseNum(e.target.value) })}
            className={ready.upcomingEarnings ? inputCls : inputDisabledCls}
          />
          {!ready.upcomingEarnings && <BackendPendingBadge />}
        </div>

        {/* ── ROW 7: UPCOMING DIVIDEND (IB-L5c ✓) ──────────────────────────
          * Integer "≤ N days" filter → next_dividend_within_days. Same
          * upper-bound pattern as the earnings row above. */}
        <div className="flex items-center gap-2 h-6" aria-disabled={!ready.upcomingDividend}>
          <span className={labelCls}>Dividend ≤</span>
          <input
            type="number"
            min={0}
            step={1}
            aria-label={
              ready.upcomingDividend
                ? "Maximum days until next dividend"
                : "Dividend filter (backend pending)"
            }
            placeholder="days"
            disabled={!ready.upcomingDividend}
            value={value.upcomingDividendWithinDays ?? ""}
            onChange={(e) => patch({ upcomingDividendWithinDays: parseNum(e.target.value) })}
            className={ready.upcomingDividend ? inputCls : inputDisabledCls}
          />
          {!ready.upcomingDividend && <BackendPendingBadge />}
        </div>

      </div>
    </Section>
  );
}
