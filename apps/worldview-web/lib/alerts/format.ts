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
