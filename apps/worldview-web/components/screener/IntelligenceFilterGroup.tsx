/**
 * components/screener/IntelligenceFilterGroup.tsx — 7-row Intelligence filter section
 * (PRD-0089 Wave I-A · Block B · T-IA-07)
 *
 * WHY THIS EXISTS:
 *   Wave I-A surfaces the FRONT end of seven intelligence-layer screener
 *   filters whose BACK end will land in Wave L-5 (S7→S3 nightly rollup).
 *   Rendering all 7 rows today — disabled with a "Backend pending" badge —
 *   shows users the roadmap and lets us flip individual rows on by switching
 *   the matching `backendReady.X` flag to true (one-line change per Wave L
 *   track completion). The alternative (waiting until L-5 lands before
 *   showing anything) hides the product direction.
 *
 *   This section mounts as the SEVENTH collapsible group in
 *   `ScreenerFilterBar` (after Valuation / Profitability / Growth / Cap /
 *   Risk / Categorical), per plan §5.1 T-IA-07. We compose <Section>
 *   directly so the chrome (badge, chevron, grid-rows animation) stays
 *   identical to the existing six sections.
 *
 * THE 7 FILTERS (all gated on Wave L-5):
 *   1. NEWS COUNT 7D            — min news article count over the past week.
 *   2. AI BRIEF                 — boolean: only instruments with a fresh AI brief.
 *   3. ACTIVE ALERT             — boolean: only instruments with a live alert.
 *   4. CONTRADICTIONS           — min count of recent KG contradiction events.
 *   5. LLM RELEVANCE            — min display_relevance_7d_weighted score (0-1).
 *   6. UPCOMING EARNINGS        — discrete window: 7d / 14d / 30d.
 *   7. UPCOMING DIVIDEND        — discrete window: 7d / 14d / 30d.
 *
 *   WHY rendered (not skipped) when disabled: discoverability. A disabled
 *   row teaches the user the feature exists — a missing row does not.
 *
 * WHO USES IT:
 *   - `components/screener/ScreenerFilterBar.tsx` (mounted as the 7th section).
 *
 * PLAN REF: docs/plans/0089-pages/I-screener-plan.md §5.1 T-IA-07
 */

"use client";
// WHY "use client": the rows are interactive (when enabled) and use local
// component composition; we don't want SSR boundary churn here.

import { Section } from "@/features/screener/components/Section";
import { BackendPendingBadge } from "@/components/ui/backend-pending-badge";
import type { FilterState } from "@/features/screener/lib/filter-state";

// ── Props ────────────────────────────────────────────────────────────────────

/**
 * BackendReady — one flag per Intelligence filter row. Wave I-A ships them
 * ALL as `false`. As each Wave L-5 sub-task lands, the parent flips the
 * matching flag to `true` (a one-line edit at the mount site).
 *
 * WHY all flags up-front (not an enum array): typed object keys give us
 * exhaustiveness in the renderer — TypeScript yells if we add a new row
 * and forget to update both the type and the JSX, preventing silent drift.
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

export interface IntelligenceFilterGroupProps {
  /** Current filter state — read-only for now (all rows disabled in I-A). */
  value: FilterState;
  /** Patch handler — wired today for future use, no-op while all rows disabled. */
  onChange: (next: FilterState) => void;
  /**
   * Per-row gating flags. Defaults to ALL false (Wave I-A baseline). Each
   * Wave L-5 sub-task that lands flips one flag to true; nothing else
   * changes in this component.
   */
  backendReady?: Partial<IntelligenceBackendReady>;
}

// ── Constants ────────────────────────────────────────────────────────────────

// WHY a row config array (not 7 inline JSX blocks): keeps the JSX skim-able
// and makes "add an 8th row" a single config entry instead of a copy-paste
// of an entire <Row /> block.
type IntelligenceRow = {
  key: keyof IntelligenceBackendReady;
  label: string;
  hint: string;
};

const INTELLIGENCE_ROWS: readonly IntelligenceRow[] = [
  { key: "newsCount7d",       label: "News 7d ≥",      hint: "count" },
  { key: "aiBrief",           label: "AI Brief",        hint: "has brief" },
  { key: "activeAlert",       label: "Active Alert",    hint: "has alert" },
  { key: "contradictions",    label: "Contradictions ≥", hint: "count" },
  { key: "llmRelevance",      label: "LLM Relevance ≥", hint: "0–1" },
  { key: "upcomingEarnings",  label: "Earnings ≤",      hint: "days" },
  { key: "upcomingDividend",  label: "Dividend ≤",      hint: "days" },
];

// ── Component ────────────────────────────────────────────────────────────────

export function IntelligenceFilterGroup({
  value,
  onChange,
  backendReady,
}: IntelligenceFilterGroupProps) {
  // WHY referenced but unused while all rows are disabled: keeping `value`
  // and `onChange` in the prop surface today means flipping a `backendReady`
  // flag in Wave I-B is a one-line change. Suppress the "unused" rule for
  // the two arguments without removing them.
  void value;
  void onChange;

  // WHY a flag-merge layer: the parent may pass `backendReady` partially
  // (only `newsCount7d: true`) — fill missing keys with `false` so the
  // renderer never sees `undefined`.
  const ready: IntelligenceBackendReady = {
    newsCount7d: backendReady?.newsCount7d ?? false,
    aiBrief: backendReady?.aiBrief ?? false,
    activeAlert: backendReady?.activeAlert ?? false,
    contradictions: backendReady?.contradictions ?? false,
    llmRelevance: backendReady?.llmRelevance ?? false,
    upcomingEarnings: backendReady?.upcomingEarnings ?? false,
    upcomingDividend: backendReady?.upcomingDividend ?? false,
  };

  // Active count for the Section header badge: any row whose backend is
  // ready AND has a filter value in `value`. While all rows are disabled
  // (Wave I-A baseline), this stays at 0 — keeps the badge invisible.
  const activeCount = 0;

  return (
    <Section title="Intelligence" activeCount={activeCount}>
      <div className="flex flex-col gap-1.5">
        {INTELLIGENCE_ROWS.map((row) => {
          const isReady = ready[row.key];
          return (
            // WHY `h-6` row + flex gap-2: matches the height + spacing of
            // the News & Signals section so the visual rhythm is identical.
            <div
              key={row.key}
              className="flex items-center gap-2 h-6"
              aria-disabled={!isReady}
            >
              <span
                className="text-[10px] font-mono uppercase tracking-[0.06em] w-32 shrink-0 text-muted-foreground"
              >
                {row.label}
              </span>
              {/* WHY a placeholder input (disabled) instead of a real
               *  control: the visual real estate stays reserved for the
               *  future interactive widget. When `isReady` flips to true
               *  in I-B, this scaffolding is replaced by the real control
               *  in a focused diff. */}
              <input
                type="text"
                aria-label={`${row.label} filter (backend pending)`}
                placeholder={row.hint}
                disabled
                className="h-6 w-20 px-1.5 text-[11px] font-mono tabular-nums bg-card border border-border rounded-[2px] text-muted-foreground placeholder:text-muted-foreground/50 cursor-not-allowed"
              />
              {!isReady && <BackendPendingBadge />}
            </div>
          );
        })}
      </div>
    </Section>
  );
}
