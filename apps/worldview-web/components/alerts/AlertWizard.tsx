/**
 * components/alerts/AlertWizard.tsx — type-first 2-step alert-rule wizard
 * (PLAN-0113 Wave 4, T-4-03).
 *
 * WHY THIS EXISTS:
 * The legacy AlertRuleBuilder / RuleManagerDialog Edit tab used a single free-text
 * "condition" box backed by localStorage — rules never reached the backend and the
 * condition was unvalidated. This wizard replaces both with a TYPE-FIRST flow:
 *
 *   Step 1 — pick one of the 5 rule types (a card grid, each "fires when …").
 *   Step 2 — fill the type's STRUCTURED editor + severity + notify toggles, see a
 *            LIVE natural-language summary, then Save → real `POST /v1/alert-rules`.
 *
 * Edit mode reuses the exact same wizard: pass `editRule` and we open straight to
 * Step 2 with the editor hydrated, and Save calls `PATCH` instead of `POST`.
 *
 * ARCHITECTURE (R14): all persistence goes through the gateway hooks in
 * `lib/api/useAlertRules.ts` (→ S9 `/v1/alert-rules`). No localStorage.
 *
 * WHY render the wizard INSIDE the existing shadcn Dialog: the alerts page already
 * uses Dialog for rule management; keeping the wizard in a Dialog matches the
 * surrounding chrome and avoids a second overlay primitive.
 */

"use client";
// WHY "use client": useState (step + form state) + the mutation hooks.

import { useMemo, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  RULE_TYPES,
  type AlertRule,
  type CreateAlertRuleInput,
  type RuleCondition,
  type RuleSeverity,
  type RuleType,
} from "@/lib/api/alertRules";
import { useCreateAlertRule, useUpdateAlertRule } from "@/lib/api/useAlertRules";
import { defaultRuleName } from "@/lib/alerts/rules";
import { ruleToNaturalLanguage } from "@/lib/alerts/format";
import { PriceCrossEditor } from "./condition-editors/PriceCrossEditor";
import { FundamentalCrossEditor } from "./condition-editors/FundamentalCrossEditor";
import { NewsVolumeEditor } from "./condition-editors/NewsVolumeEditor";
import { NewsMomentumEditor } from "./condition-editors/NewsMomentumEditor";
import { KgConnectionEditor } from "./condition-editors/KgConnectionEditor";

// ── Type-card metadata ─────────────────────────────────────────────────────────

/**
 * RULE_TYPE_META — display copy for each type card (Step 1).
 * `fires` is the "fires when …" subtitle shown under the title.
 */
const RULE_TYPE_META: Record<RuleType, { title: string; fires: string }> = {
  PRICE_CROSS: { title: "Price cross", fires: "a price crosses a level" },
  NEWS_COUNT: { title: "News volume", fires: "article count over a window spikes" },
  NEWS_MOMENTUM: { title: "News momentum", fires: "news momentum surges" },
  KG_CONNECTION: { title: "Connection", fires: "two entities become connected" },
  FUNDAMENTAL_CROSS: { title: "Fundamental", fires: "a metric crosses a threshold" },
};

/** Severity options (lowercase = backend wire shape). */
const SEVERITY_OPTIONS: RuleSeverity[] = ["low", "medium", "high", "critical"];

// ── Props ──────────────────────────────────────────────────────────────────────

export interface AlertWizardProps {
  /** Controlled open state. */
  open: boolean;
  /** Open/close callback (also fired after a successful save). */
  onOpenChange: (open: boolean) => void;
  /**
   * When set, the wizard opens in EDIT mode straight to Step 2 with this rule's
   * editor hydrated; Save calls PATCH. When undefined, it is a fresh create.
   */
  editRule?: AlertRule;
  /**
   * Optional pre-selected type for create mode (e.g. the instrument-page "+Alert"
   * button defaults to PRICE_CROSS). When set, the wizard skips Step 1.
   */
  initialRuleType?: RuleType;
  /**
   * Optional CREATE-mode condition seed (PLAN-0113 Wave 5, T-5-01).
   *
   * WHY a Partial: the entry-point buttons know the SUBJECT of the rule (the
   * instrument on the instrument page, the two entities on the Path panel) but
   * not the threshold/operator the user still has to choose. We therefore seed
   * only the known fields — e.g. `{ instrument_id }` from the instrument header,
   * or `{ source_entity_id, target_entity_id }` from the KG path panel — and let
   * the mounted editor hydrate those fields while leaving the rest blank. Because
   * the seed is partial, the editor keeps emitting `null` (Save disabled) until
   * the user completes the remaining required fields, so we never POST a
   * half-built condition.
   *
   * Ignored in EDIT mode (an existing rule's `condition` always wins).
   */
  prefillCondition?: Partial<RuleCondition>;
  /**
   * Optional id→display-name map for the seeded subjects (PLAN-0113 Wave 5).
   *
   * The pickers normally learn an entity/instrument's display name when the user
   * selects it from the dropdown. A prefilled subject skips that step, so the
   * chip would otherwise show a raw UUID. The entry points pass the names they
   * already know (e.g. the ticker on the instrument page) so the seeded chip and
   * the live NL summary read "AAPL", not a UUID.
   */
  prefillNames?: Record<string, string>;
}

// ── Component ────────────────────────────────────────────────────────────────────

/**
 * AlertWizard — the 2-step type-first rule creator/editor.
 */
export function AlertWizard({
  open,
  onOpenChange,
  editRule,
  initialRuleType,
  prefillCondition,
  prefillNames,
}: AlertWizardProps) {
  const isEdit = editRule !== undefined;

  // ── Step state ──────────────────────────────────────────────────────────
  // Edit mode (or a pre-selected type) starts on Step 2; a blank create starts
  // on Step 1 (the type-card grid).
  const [ruleType, setRuleType] = useState<RuleType | null>(
    editRule?.rule_type ?? initialRuleType ?? null,
  );
  const step: 1 | 2 = ruleType === null ? 1 : 2;

  // ── Step-2 form state ─────────────────────────────────────────────────────
  // `condition` is null until the mounted editor reports a complete payload.
  // (A partial prefill seeds the EDITOR fields but is intentionally NOT used as
  // the initial `condition` value — a partial seed is incomplete, so Save must
  // stay disabled until the editor reports a complete payload.)
  const [condition, setCondition] = useState<RuleCondition | null>(
    editRule?.condition ?? null,
  );
  const [severity, setSeverity] = useState<RuleSeverity>(editRule?.severity ?? "medium");
  const [name, setName] = useState<string>(editRule?.name ?? "");
  const [notifyInApp, setNotifyInApp] = useState<boolean>(editRule?.notify_in_app ?? true);
  const [notifyEmail, setNotifyEmail] = useState<boolean>(editRule?.notify_email ?? false);

  const createMut = useCreateAlertRule();
  const updateMut = useUpdateAlertRule();
  const saving = createMut.isPending || updateMut.isPending;

  // Live NL summary — recomputed as the editor reports condition changes.
  // `prefillNames` lets the summary read "AAPL" instead of a raw UUID for any
  // subject that was seeded by an entry point (PLAN-0113 Wave 5).
  const summary = useMemo(
    () =>
      ruleType
        ? ruleToNaturalLanguage({ rule_type: ruleType, condition, names: prefillNames })
        : "",
    [ruleType, condition, prefillNames],
  );

  // ── Handlers ──────────────────────────────────────────────────────────────

  /** Reset all state back to a fresh create. */
  function reset() {
    setRuleType(editRule?.rule_type ?? initialRuleType ?? null);
    setCondition(editRule?.condition ?? null);
    setSeverity(editRule?.severity ?? "medium");
    setName(editRule?.name ?? "");
    setNotifyInApp(editRule?.notify_in_app ?? true);
    setNotifyEmail(editRule?.notify_email ?? false);
  }

  /** Close the dialog and reset for next time. */
  function close() {
    onOpenChange(false);
    reset();
  }

  /** Save → create (POST) or update (PATCH) depending on mode. */
  async function handleSave() {
    if (!ruleType || !condition) return; // guarded by the disabled Save button too
    // Auto-fill name from the type + a subject hint when the user left it blank.
    const finalName = name.trim() || defaultRuleName(ruleType, "");

    if (isEdit && editRule) {
      await updateMut.mutateAsync({
        ruleId: editRule.rule_id,
        patch: {
          name: finalName,
          condition,
          severity,
          notify_in_app: notifyInApp,
          notify_email: notifyEmail,
        },
      });
    } else {
      const input: CreateAlertRuleInput = {
        rule_type: ruleType,
        name: finalName,
        condition,
        severity,
        notify_in_app: notifyInApp,
        notify_email: notifyEmail,
      };
      await createMut.mutateAsync(input);
    }
    close();
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent className="w-full max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            {isEdit ? "EDIT ALERT RULE" : "NEW ALERT RULE"}
          </DialogTitle>
          {/* Radix requires a description for aria-describedby; sr-only keeps it
              accessible without taking visual space. */}
          <DialogDescription className="sr-only">
            {step === 1
              ? "Choose an alert type, then configure its condition."
              : "Configure the alert condition, severity, and notifications."}
          </DialogDescription>
        </DialogHeader>

        {/* ── Step 1 — type cards ───────────────────────────────────────────── */}
        {step === 1 && (
          <div
            className="grid grid-cols-2 gap-2 pt-1"
            role="radiogroup"
            aria-label="Alert type"
          >
            {RULE_TYPES.map((t) => (
              <button
                key={t}
                type="button"
                role="radio"
                aria-checked={false}
                data-testid={`rule-type-card-${t}`}
                onClick={() => setRuleType(t)}
                className="flex flex-col items-start gap-1 rounded-[2px] border border-border/60 bg-muted/20 p-3 text-left hover:border-primary/50 hover:bg-muted/40"
              >
                <span className="text-[12px] font-medium text-foreground">
                  {RULE_TYPE_META[t].title}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  Fires when {RULE_TYPE_META[t].fires}.
                </span>
              </button>
            ))}
          </div>
        )}

        {/* ── Step 2 — editor + meta ────────────────────────────────────────── */}
        {step === 2 && ruleType && (
          <div className="flex flex-col gap-3 pt-1">
            {/* Type editor — mounted per the chosen rule_type.
                value precedence: an EDIT rule's stored condition wins; otherwise
                a CREATE-mode partial prefill (from an entry point) seeds the
                known fields. The editors treat a partial seed as incomplete and
                keep Save disabled until the user fills the rest. */}
            <ConditionEditorSwitch
              ruleType={ruleType}
              value={editRule?.condition ?? prefillCondition ?? null}
              names={prefillNames}
              onChange={setCondition}
            />

            {/* Name (optional). */}
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                Name (optional)
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={defaultRuleName(ruleType, "")}
                aria-label="Rule name"
                className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            {/* Severity. */}
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                Severity
              </label>
              <select
                value={severity}
                onChange={(e) => setSeverity(e.target.value as RuleSeverity)}
                aria-label="Severity"
                className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {SEVERITY_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            {/* Notify toggles. */}
            <div className="flex gap-4">
              <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-foreground">
                <input
                  type="checkbox"
                  checked={notifyInApp}
                  onChange={(e) => setNotifyInApp(e.target.checked)}
                  className="h-3.5 w-3.5 rounded-[2px] accent-primary"
                />
                In-app
              </label>
              <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-foreground">
                <input
                  type="checkbox"
                  checked={notifyEmail}
                  onChange={(e) => setNotifyEmail(e.target.checked)}
                  className="h-3.5 w-3.5 rounded-[2px] accent-primary"
                />
                Email
              </label>
            </div>

            {/* Live NL summary. */}
            <p
              data-testid="rule-nl-summary"
              className="rounded-[2px] border border-border/40 bg-muted/10 px-2 py-1.5 text-[11px] text-muted-foreground"
            >
              {summary}
            </p>

            {/* Footer actions. */}
            <div className="flex items-center justify-between pt-1">
              {/* Back is only meaningful in create mode (edit has no type step). */}
              {!isEdit ? (
                <button
                  type="button"
                  onClick={() => {
                    setRuleType(null);
                    setCondition(null);
                  }}
                  className="rounded-[2px] px-3 py-1 text-[11px] text-muted-foreground hover:text-foreground"
                >
                  ← Back
                </button>
              ) : (
                <span />
              )}

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={close}
                  className="rounded-[2px] px-3 py-1 text-[11px] text-muted-foreground hover:text-foreground"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void handleSave()}
                  disabled={condition === null || saving}
                  className={cn(
                    "rounded-[2px] bg-primary px-3 py-1 text-[11px] text-primary-foreground",
                    "hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40",
                  )}
                >
                  {saving ? "Saving…" : isEdit ? "Save changes" : "Create rule"}
                </button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ── ConditionEditorSwitch ────────────────────────────────────────────────────────

/**
 * ConditionEditorSwitch — mounts the editor for the chosen rule type.
 *
 * WHY a switch (not a registry map): the editors take slightly different generic
 * `value` shapes; a switch with `as never`-free narrowing keeps each branch typed
 * to its own condition. Exhaustiveness is enforced by the `default` throw.
 */
function ConditionEditorSwitch({
  ruleType,
  value,
  names,
  onChange,
}: {
  ruleType: RuleType;
  /** Stored condition (edit) or partial prefill (create); may be incomplete. */
  value: Partial<RuleCondition> | null;
  /** Optional id→display-name map so seeded chips show names, not UUIDs. */
  names?: Record<string, string>;
  onChange: (c: RuleCondition | null) => void;
}) {
  switch (ruleType) {
    case "PRICE_CROSS":
      return (
        <PriceCrossEditor
          value={value as never}
          names={names}
          onChange={onChange as never}
        />
      );
    case "FUNDAMENTAL_CROSS":
      return (
        <FundamentalCrossEditor
          value={value as never}
          names={names}
          onChange={onChange as never}
        />
      );
    case "NEWS_COUNT":
      return (
        <NewsVolumeEditor value={value as never} names={names} onChange={onChange as never} />
      );
    case "NEWS_MOMENTUM":
      return (
        <NewsMomentumEditor value={value as never} names={names} onChange={onChange as never} />
      );
    case "KG_CONNECTION":
      return (
        <KgConnectionEditor value={value as never} names={names} onChange={onChange as never} />
      );
    default: {
      // Exhaustiveness guard — adding a RuleType without a branch is a compile error.
      const _never: never = ruleType;
      return _never;
    }
  }
}
