/**
 * lib/alerts/format.ts — shared alert title fallback ladder (PLAN-0049 T-D-4-04).
 *
 * Consumed by both `<RecentAlerts>` (dashboard) and `<AlarmsPanel>` (sidebar)
 * so they can never drift apart on the contract that we never display bare
 * "<SEVERITY> signal" / "<SEVERITY> alert" strings (regression: F-D-006 / F-X-201).
 *
 * Priority chain — first non-empty wins:
 *   1. Backend-composed `alert.title`  (best — composed by AlertFanoutUseCase)
 *   2. `subject + signal_label`         (e.g. "AAPL: Bullish guidance")
 *   3. Bare `signal_label`              (when no subject)
 *   4. Bare `subject` (ticker / name)
 *   5. payload.message                  (legacy alerts pre-PLAN-0048)
 *   6. Humanised `alert_type`           (e.g. "Graph Change Alert")
 *   7. Literal "Alert"                  (data bug — last-resort)
 *
 * NEVER returns a bare-severity string. The function is pure, so it's
 * trivial to unit-test and reuse from other surfaces (email digests etc.).
 */

/** Subset of the Alert API shape this formatter needs. */
export interface AlertTitleLikeAlert {
  alert_type?: string | null;
  title?: string | null;
  ticker?: string | null;
  entity_name?: string | null;
  signal_label?: string | null;
  payload?: Record<string, unknown> | null;
}

/** Humanise a snake/screaming-snake alert_type into Title Case prose. */
function humaniseAlertType(alertType: string | null | undefined): string {
  if (!alertType) return "";
  return alertType
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

/**
 * Compute the user-facing alert title, NEVER bare severity.
 *
 * Defensive: tolerates legacy rows where enrichment fields live in `payload`
 * (pre-PLAN-0049) instead of as top-level columns.
 */
export function formatAlertTitle(alert: AlertTitleLikeAlert): string {
  // Top-level fields take priority — those are the canonical PLAN-0049 columns.
  const topTitle = typeof alert.title === "string" ? alert.title : null;
  if (topTitle) return topTitle;

  const topSignalLabel = typeof alert.signal_label === "string" ? alert.signal_label : null;
  const topEntityName = typeof alert.entity_name === "string" ? alert.entity_name : null;
  const topTicker = typeof alert.ticker === "string" ? alert.ticker : null;

  // Fall back to payload-embedded fields for legacy rows (pre-migration backfill).
  const payload = (alert.payload ?? {}) as Record<string, unknown>;
  const pTicker = typeof payload.ticker === "string" ? payload.ticker : null;
  const pEntity = typeof payload.entity_name === "string" ? payload.entity_name : null;
  const pLabel = typeof payload.signal_label === "string" ? payload.signal_label : null;
  const pMessage = typeof payload.message === "string" ? payload.message : null;

  const ticker = topTicker ?? pTicker;
  const entityName = topEntityName ?? pEntity;
  const signalLabel = topSignalLabel ?? pLabel;
  const subject = ticker ?? entityName;

  if (subject && signalLabel) return `${subject}: ${signalLabel}`;
  if (signalLabel) return signalLabel;
  if (subject) return subject;
  if (pMessage) return pMessage;

  const human = humaniseAlertType(alert.alert_type);
  if (human) return `${human} alert`;
  return "Alert";
}

// ── ruleToNaturalLanguage (PLAN-0113 W4 T-4-03) ────────────────────────────────

import {
  type AlertRule,
  type FundamentalCrossCondition,
  type KgConnectionCondition,
  type NewsCountCondition,
  type NewsMomentumCondition,
  type PriceCrossCondition,
  type RuleType,
} from "@/lib/api/alertRules";

/**
 * RuleNlInput — the minimal slice of a rule the NL formatter needs.
 *
 * WHY a partial (not the full `AlertRule`): the AlertWizard renders a LIVE
 * summary while the user is still filling in fields — there is no persisted rule
 * yet, just a `rule_type` + an in-progress `condition` (possibly null). Accepting
 * a partial lets the same function drive both the live wizard summary AND the
 * saved-rule list label.
 *
 * WHY display-name maps: a condition only carries ids (instrument_id /
 * entity_id). The wizard knows the chosen entities' display names (from the
 * pickers) and passes them via `names` so the summary reads "Apple", not a UUID.
 */
export interface RuleNlInput {
  rule_type: RuleType;
  /** The in-progress or stored condition; null while the editor is incomplete. */
  condition: AlertRule["condition"] | null;
  /** Optional id→display-name map so the summary can show tickers / names. */
  names?: Record<string, string>;
}

/** Resolve an id to its display name, falling back to a short id stub. */
function nameFor(id: string | undefined, names?: Record<string, string>): string {
  if (!id) return "—";
  return names?.[id] ?? id;
}

/**
 * ruleToNaturalLanguage — render a human "Alert me when …" sentence for a rule.
 *
 * Returns a generic prompt when the condition is incomplete (null / missing
 * fields) so the wizard always has something to show. Pure + side-effect-free,
 * so it is trivial to unit-test per type.
 */
export function ruleToNaturalLanguage(input: RuleNlInput): string {
  const { rule_type, condition, names } = input;
  if (!condition) return "Complete the fields to preview this alert.";

  switch (rule_type) {
    case "PRICE_CROSS": {
      const c = condition as PriceCrossCondition;
      return `Alert me when ${nameFor(c.instrument_id, names)} price crosses ${c.operator} ${c.value}.`;
    }
    case "FUNDAMENTAL_CROSS": {
      const c = condition as FundamentalCrossCondition;
      return `Alert me when ${nameFor(c.instrument_id, names)} ${c.metric_key} crosses ${c.operator} ${c.value}.`;
    }
    case "NEWS_COUNT": {
      const c = condition as NewsCountCondition;
      const kw = c.keyword ? ` mentioning "${c.keyword}"` : "";
      return `Alert me when ≥ ${c.threshold} articles${kw} mention ${nameFor(c.entity_id, names)} in ${c.window}.`;
    }
    case "NEWS_MOMENTUM": {
      const c = condition as NewsMomentumCondition;
      return `Alert me when news momentum on ${nameFor(c.entity_id, names)} jumps ≥ ${c.delta_pct}% over ${c.window_hours}h (≥ ${c.min_count} articles).`;
    }
    case "KG_CONNECTION": {
      const c = condition as KgConnectionCondition;
      const rel = c.relation_type ? ` via a ${c.relation_type} link` : "";
      return `Alert me when ${nameFor(c.source_entity_id, names)} connects to ${nameFor(c.target_entity_id, names)} within ${c.max_hops} hop${c.max_hops !== 1 ? "s" : ""}${rel}.`;
    }
    default:
      // Exhaustiveness guard — a new RuleType without a case is a compile error.
      return "Alert rule.";
  }
}
