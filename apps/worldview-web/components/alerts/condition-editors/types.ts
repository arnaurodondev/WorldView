/**
 * components/alerts/condition-editors/types.ts — shared contract for the per-type
 * condition editors (PLAN-0113 Wave 4, T-4-04 / T-4-05).
 *
 * Each editor is a controlled component: it renders the structured fields for one
 * rule type and reports the current condition up via `onChange`. When the form is
 * incomplete (a required picker not chosen, a blank number), the editor emits
 * `null` — the wizard uses that to keep Save disabled. When complete, it emits the
 * exact `RuleCondition` shape the backend expects (so the wizard can POST it
 * verbatim without re-shaping).
 */

import type { RuleCondition } from "@/lib/api/alertRules";

/**
 * ConditionEditorProps — generic prop contract for every condition editor.
 *
 * @typeParam C - the specific condition shape this editor produces.
 */
export interface ConditionEditorProps<C extends RuleCondition = RuleCondition> {
  /**
   * The current condition (when editing an existing rule), or `null` for a fresh
   * create. Editors hydrate their internal field state from this on mount.
   *
   * PLAN-0113 Wave 5 (T-5-01): this may be a PARTIAL condition when an entry
   * point seeds only the known subject fields (e.g. just `instrument_id` from
   * the instrument header, or `{source_entity_id, target_entity_id}` from the KG
   * path panel). Editors read fields defensively (optional access) and treat any
   * missing required field as "incomplete" → they emit `null` so Save stays
   * disabled until the user fills the rest.
   */
  value: Partial<C> | null;
  /**
   * Optional id→display-name map (PLAN-0113 Wave 5). When a subject is prefilled,
   * the picker chip would otherwise show a raw UUID (the user never picked it
   * from the dropdown, so the editor never learned its name). Entry points pass
   * the names they already know (e.g. the ticker) so the chip reads "AAPL".
   */
  names?: Record<string, string>;
  /**
   * Emits the structured condition when complete, or `null` when the form is not
   * yet valid (so the wizard can disable Save).
   */
  onChange: (condition: C | null) => void;
}
