/**
 * lib/alerts/rules.ts — DEPRECATED localStorage rule layer → thin server shim
 * (PLAN-0113 Wave 4, T-4-01).
 *
 * HISTORY: This module used to persist user alert rules in `localStorage`
 * (`worldview-alert-rules`) because no backend rule resource existed. Rules a
 * user created never actually fired. PLAN-0113 Wave 1 shipped the REAL backend
 * resource (`/v1/alert-rules`), so the localStorage layer is retired.
 *
 * WHY KEEP THE FILE AT ALL (one release): a couple of legacy call sites import
 * the `AlertRule` *type* / `defaultRuleName` from here. Rather than churn them
 * all in a single commit, this shim re-points the type at the new server model
 * and keeps `defaultRuleName` (a pure label helper, no storage). ALL localStorage
 * read/write helpers are GONE — there is no rule persistence in the browser
 * anymore. New code must use `lib/api/useAlertRules.ts` (server CRUD).
 *
 * Slated for deletion once the last legacy import is migrated.
 */

import type { RuleType } from "@/lib/api/alertRules";

// Re-export the canonical server rule type so legacy `AlertRule` imports keep
// compiling against the real backend shape (not the old localStorage struct).
export type { AlertRule, RuleType } from "@/lib/api/alertRules";

/**
 * defaultRuleName — produce a human label from a rule type + subject.
 *
 * WHY retained: the wizard auto-fills the `name` field with a readable default
 * when the user leaves it blank. Pure function, no storage. The legacy 4-type
 * label map is replaced by the 5 real `RuleType` values.
 */
const RULE_TYPE_LABEL: Record<RuleType, string> = {
  PRICE_CROSS: "Price",
  NEWS_COUNT: "News volume",
  NEWS_MOMENTUM: "News momentum",
  KG_CONNECTION: "Connection",
  FUNDAMENTAL_CROSS: "Fundamental",
};

export function defaultRuleName(ruleType: RuleType, subject: string): string {
  const who = subject.trim() || "any entity";
  return `${RULE_TYPE_LABEL[ruleType]} • ${who}`;
}
