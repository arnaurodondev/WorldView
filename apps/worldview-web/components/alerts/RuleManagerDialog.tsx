/**
 * components/alerts/RuleManagerDialog.tsx — server-backed alert-rule manager
 * (PLAN-0113 Wave 4, T-4-06).
 *
 * WHY THIS EXISTS:
 * The single management surface for STANDING alert rules: list the caller's
 * rules, pause/unpause (enabled toggle), edit, and delete. PLAN-0113 retired the
 * old localStorage layer — every operation now hits the real backend through the
 * gateway hooks (`useAlertRules` / `useUpdateAlertRule` / `useDeleteAlertRule`).
 *
 * WHAT CHANGED FROM THE LEGACY DIALOG:
 *   - Rules come from `GET /v1/alert-rules` (was: localStorage).
 *   - The inline "Edit" tab + 4-option free-text type select are GONE — create /
 *     edit now open the type-first `AlertWizard` (absorbs AlertRuleBuilder too).
 *   - The "(local only)" badge is removed (rules are real backend rows now).
 *
 * WHY a single List view (no tabs): with editing delegated to the wizard, the
 * dialog only needs the list; the old List|Edit tab split is unnecessary.
 *
 * DESIGN: Midnight Pro dark palette, shadcn/ui Dialog only.
 */

"use client";
// WHY "use client": uses state (open) + the query/mutation hooks.

import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { AlertWizard } from "@/components/alerts/AlertWizard";
import {
  useAlertRules,
  useDeleteAlertRule,
  useUpdateAlertRule,
} from "@/lib/api/useAlertRules";
import { ruleToNaturalLanguage } from "@/lib/alerts/format";
import type { AlertRule, RuleType } from "@/lib/api/alertRules";

// Short human label per rule type for the list's left column.
const RULE_TYPE_LABEL: Record<RuleType, string> = {
  PRICE_CROSS: "Price",
  NEWS_COUNT: "News",
  NEWS_MOMENTUM: "Momentum",
  KG_CONNECTION: "Connection",
  FUNDAMENTAL_CROSS: "Fundamental",
};

interface RuleManagerDialogProps {
  /** Optional trigger override — when omitted we render the default button. */
  trigger?: React.ReactNode;
  /** Fired after any CRUD op so a parent can refresh badges. */
  onRulesChanged?: () => void;
  /**
   * DEPRECATED (PLAN-0113 W4): the legacy localStorage dialog pre-filled a
   * free-text entity box from an alert's ticker. The new type-first wizard uses
   * structured entity/instrument PICKERS (no free-text), so a ticker string can
   * no longer pre-seed a rule reliably. The prop is accepted for call-site
   * back-compat (e.g. AlertDetailSheet) but is currently a no-op. A future wave
   * can resolve the ticker → instrument_id and pass it into the wizard.
   */
  prefillEntity?: string;
}

export function RuleManagerDialog({
  trigger,
  onRulesChanged,
}: RuleManagerDialogProps) {
  const [open, setOpen] = useState(false);

  // Wizard state: open + which rule is being edited (undefined = create).
  const [wizardOpen, setWizardOpen] = useState(false);
  const [editRule, setEditRule] = useState<AlertRule | undefined>(undefined);

  // Server data + mutations. The list only loads while the dialog is open.
  const { data, isLoading, isError } = useAlertRules();
  const rules = data?.items ?? [];
  const updateMut = useUpdateAlertRule();
  const deleteMut = useDeleteAlertRule();

  /** Open the wizard for a fresh create. */
  function beginCreate() {
    setEditRule(undefined);
    setWizardOpen(true);
  }

  /** Open the wizard hydrated for an existing rule. */
  function beginEdit(rule: AlertRule) {
    setEditRule(rule);
    setWizardOpen(true);
  }

  /** Toggle a rule's enabled flag inline (pause / unpause). */
  async function handleToggleEnabled(rule: AlertRule, next: boolean) {
    await updateMut.mutateAsync({ ruleId: rule.rule_id, patch: { enabled: next } });
    onRulesChanged?.();
  }

  /** Delete a rule. */
  async function handleDelete(ruleId: string) {
    await deleteMut.mutateAsync(ruleId);
    onRulesChanged?.();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <button
            type="button"
            className="rounded-[2px] border border-border/40 bg-muted/20 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground"
            aria-label="Manage alert rules"
          >
            ⚙ Rules
          </button>
        )}
      </DialogTrigger>

      <DialogContent className="w-full max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            ALERT RULES
          </DialogTitle>
          <DialogDescription className="sr-only">
            Manage alert rules — create, edit, pause, and remove alert rules.
          </DialogDescription>
        </DialogHeader>

        {/* Toolbar: new rule. */}
        <div className="mb-2 flex items-center justify-end">
          <button
            type="button"
            onClick={beginCreate}
            className="flex items-center gap-1 rounded-[2px] border border-border/40 bg-muted/20 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground"
            aria-label="Create new alert rule"
          >
            <Plus className="h-3 w-3" aria-hidden="true" />
            New rule
          </button>
        </div>

        {/* List states: loading / error / empty / rows. */}
        {isLoading && (
          <p className="py-6 text-center text-[11px] text-muted-foreground">
            Loading rules…
          </p>
        )}
        {isError && (
          <p className="py-6 text-center text-[11px] text-destructive">
            Failed to load alert rules.
          </p>
        )}
        {!isLoading && !isError && rules.length === 0 && (
          <p className="py-6 text-center text-[11px] text-muted-foreground">
            No alert rules defined yet.
          </p>
        )}

        {!isLoading && !isError && rules.length > 0 && (
          <ul role="list" className="divide-y divide-border/30">
            {rules.map((rule) => (
              <li
                key={rule.rule_id}
                className={cn(
                  "flex items-center gap-2 px-2 py-1.5",
                  !rule.enabled && "opacity-60",
                )}
              >
                {/* Type label. */}
                <span className="w-[90px] shrink-0 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                  {RULE_TYPE_LABEL[rule.rule_type]}
                </span>

                {/* Name + NL summary. */}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[11px] text-foreground" title={rule.name}>
                    {rule.name}
                  </div>
                  <div className="truncate text-[10px] text-muted-foreground">
                    {ruleToNaturalLanguage({
                      rule_type: rule.rule_type,
                      condition: rule.condition,
                    })}
                  </div>
                </div>

                {/* Enabled toggle (pause / unpause). */}
                <label className="flex cursor-pointer items-center gap-1 text-[10px] text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={rule.enabled}
                    onChange={(e) => void handleToggleEnabled(rule, e.target.checked)}
                    className="h-3 w-3 accent-primary"
                    aria-label={`Toggle rule ${rule.name}`}
                  />
                  {rule.enabled ? "on" : "off"}
                </label>

                {/* Edit. */}
                <button
                  type="button"
                  onClick={() => beginEdit(rule)}
                  className="rounded-[2px] p-1 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
                  aria-label={`Edit rule ${rule.name}`}
                >
                  <Pencil className="h-3 w-3" aria-hidden="true" />
                </button>

                {/* Delete. */}
                <button
                  type="button"
                  onClick={() => void handleDelete(rule.rule_id)}
                  className="rounded-[2px] p-1 text-muted-foreground hover:bg-destructive/20 hover:text-destructive"
                  aria-label={`Delete rule ${rule.name}`}
                >
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>

      {/* The wizard lives outside DialogContent so it overlays the manager. It is
          controlled; closing it after a save invalidates the rules cache (via the
          mutation hooks) so the list above refreshes automatically. */}
      <AlertWizard
        open={wizardOpen}
        onOpenChange={(o) => {
          setWizardOpen(o);
          if (!o) {
            setEditRule(undefined);
            onRulesChanged?.();
          }
        }}
        editRule={editRule}
      />
    </Dialog>
  );
}
