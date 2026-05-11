/**
 * components/alerts/RuleManagerDialog.tsx — full CRUD for alert rules.
 *
 * WHY THIS EXISTS (PLAN-0051 Wave D T-D-4-06):
 * AlertRuleBuilder (legacy) only supports create. Power users need to list
 * existing rules, edit them, pause / unpause without deleting, and remove
 * obsolete rules. This dialog is the single management surface for those
 * operations. It uses the helpers in `lib/alerts/rules.ts` so storage is
 * centralised and the eventual upgrade to a backend endpoint is a one-file
 * swap (no consumer changes).
 *
 * WHY TWO TABS (List | Edit) IN ONE DIALOG: keeping the Edit form colocated
 * with the list avoids a second dialog stacking on top — Radix supports
 * nested dialogs but the visual stack is confusing for users.
 *
 * BACKEND GAP: there is no `/v1/alerts/rules` CRUD endpoint shipped yet. We
 * tag every rule with `_localOnly: true` so the UI can render a small
 * "(local only)" badge until the parallel backend agent or a future S10
 * wave catches up. See `docs/audits/2026-04-29-alert-rule-crud-gap.md`.
 */

"use client";
// WHY "use client": uses useState (open + tab + form), useEffect (load on
// open), and localStorage via the rules helper.

import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  listAlertRules,
  createAlertRule,
  updateAlertRule,
  deleteAlertRule,
  defaultRuleName,
  type AlertRule,
} from "@/lib/alerts/rules";

// ── Constants ──────────────────────────────────────────────────────────────

/** Condition-input placeholder text varies per rule type. */
const CONDITION_PLACEHOLDER: Record<AlertRule["type"], string> = {
  price_threshold: "e.g. price > 150",
  volume_spike: "e.g. volume > 2x 30d avg",
  news_signal: "e.g. keyword: earnings",
  portfolio_risk: "e.g. drawdown > 5%",
};

/** All rule-type enumeration values, in display order. */
const RULE_TYPES: AlertRule["type"][] = [
  "price_threshold",
  "volume_spike",
  "news_signal",
  "portfolio_risk",
];

const RULE_TYPE_LABEL: Record<AlertRule["type"], string> = {
  price_threshold: "Price",
  volume_spike: "Volume",
  news_signal: "News",
  portfolio_risk: "Portfolio risk",
};

// ── Component ──────────────────────────────────────────────────────────────

interface RuleManagerDialogProps {
  /** Optional trigger override — when omitted we render the default button. */
  trigger?: React.ReactNode;
  /** Optional pre-fill for the Edit tab — e.g. "Set Alert Rule" button on
   *  AlertDetailSheet passes the alert's entity_id so the rule starts
   *  scoped to that ticker. */
  prefillEntity?: string;
  /** Fired after any CRUD op so the parent can refresh badges. */
  onRulesChanged?: () => void;
}

export function RuleManagerDialog({
  trigger,
  prefillEntity,
  onRulesChanged,
}: RuleManagerDialogProps) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"list" | "edit">("list");
  const [rules, setRules] = useState<AlertRule[]>([]);

  // ── Edit-tab form state ────────────────────────────────────────────────
  // null = creating a brand-new rule; non-null = editing the row's id.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [type, setType] = useState<AlertRule["type"]>("price_threshold");
  const [name, setName] = useState("");
  const [entitySearch, setEntitySearch] = useState("");
  const [condition, setCondition] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [notifyInApp, setNotifyInApp] = useState(true);
  const [notifyEmail, setNotifyEmail] = useState(false);

  /** refresh — re-fetch the rule list from storage. */
  async function refresh() {
    const next = await listAlertRules();
    setRules(next);
  }

  // Re-load whenever the dialog opens (so external edits are visible).
  useEffect(() => {
    if (!open) return;
    void refresh();
    if (prefillEntity && tab === "edit") {
      // WHY only pre-fill when the consumer opens directly to Edit tab:
      // in normal "manage rules" flow the user starts on the List tab and
      // would be confused by an entity baked into a phantom new rule.
      setEntitySearch((prev) => (prev ? prev : prefillEntity));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // ── Form helpers ───────────────────────────────────────────────────────

  function resetForm() {
    setEditingId(null);
    setType("price_threshold");
    setName("");
    setEntitySearch(prefillEntity ?? "");
    setCondition("");
    setEnabled(true);
    setNotifyInApp(true);
    setNotifyEmail(false);
  }

  /** beginEdit — load a row into the Edit tab. */
  function beginEdit(rule: AlertRule) {
    setEditingId(rule.id);
    setType(rule.type);
    setName(rule.name);
    setEntitySearch(rule.entitySearch);
    setCondition(rule.condition);
    setEnabled(rule.enabled);
    setNotifyInApp(rule.notifyInApp);
    setNotifyEmail(rule.notifyEmail);
    setTab("edit");
  }

  /** beginCreate — switch to Edit tab with a blank form. */
  function beginCreate() {
    resetForm();
    setTab("edit");
  }

  /** handleSave — create or update depending on editingId. */
  async function handleSave() {
    if (!condition.trim()) return; // empty condition is a no-op rule
    const payload = {
      name: name.trim() || defaultRuleName(type, entitySearch, condition),
      type,
      entitySearch: entitySearch.trim(),
      condition: condition.trim(),
      enabled,
      notifyInApp,
      notifyEmail,
    };
    if (editingId) {
      await updateAlertRule(editingId, payload);
    } else {
      await createAlertRule(payload);
      // PLAN-0053 Wave G T-G-7-08 — post-first-alert NPS trigger.
      // Only fire on creation (not edits). The NPSPromptHost decides
      // whether to actually show the prompt — eligibility checks include
      // session count, last-submitted, and per-quarter cap. We don't need
      // a "is this the *first* alert?" check here because eligibility
      // already throttles to once per quarter, which is the spirit of
      // the requirement (users don't get hassled on every alert create).
      void import("@/components/feedback/NPSPromptHost").then(
        ({ requestNPS }) => requestNPS("post_first_alert"),
      );
    }
    await refresh();
    onRulesChanged?.();
    resetForm();
    setTab("list");
  }

  /** handleDelete — remove a row + refresh. */
  async function handleDelete(id: string) {
    await deleteAlertRule(id);
    await refresh();
    onRulesChanged?.();
  }

  /** handleToggleEnabled — flip the enabled flag inline (no edit-tab trip). */
  async function handleToggleEnabled(id: string, next: boolean) {
    await updateAlertRule(id, { enabled: next });
    await refresh();
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
          {/* QA-iter1 NIT-1: ``DialogDescription`` is required by Radix for
              the ``aria-describedby`` linkage on DialogContent. Visually
              hidden via ``sr-only`` so the design stays compact while screen
              readers announce the dialog purpose. */}
          <DialogDescription className="sr-only">
            Manage alert rules — create, edit, pause, and remove alert rules.
          </DialogDescription>
        </DialogHeader>

        <Tabs value={tab} onValueChange={(v) => setTab(v as "list" | "edit")}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="list" className="text-[11px]">
              List ({rules.length})
            </TabsTrigger>
            <TabsTrigger value="edit" className="text-[11px]">
              {editingId ? "Edit" : "New rule"}
            </TabsTrigger>
          </TabsList>

          {/* ── List tab ──────────────────────────────────────────────── */}
          <TabsContent value="list" className="pt-2">
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

            {rules.length === 0 ? (
              <p className="py-6 text-center text-[11px] text-muted-foreground">
                No alert rules defined yet.
              </p>
            ) : (
              <ul role="list" className="divide-y divide-border/30">
                {rules.map((rule) => (
                  <li
                    key={rule.id}
                    className={cn(
                      "flex items-center gap-2 px-2 py-1.5",
                      !rule.enabled && "opacity-60",
                    )}
                  >
                    {/* Type label */}
                    <span className="w-[80px] shrink-0 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                      {RULE_TYPE_LABEL[rule.type]}
                    </span>

                    {/* Name + condition summary */}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[11px] text-foreground" title={rule.name}>
                        {rule.name}
                        {rule._localOnly && (
                          <span
                            className="ml-1.5 rounded-[2px] border border-border/40 px-1 text-[9px] uppercase tracking-[0.08em] text-muted-foreground/70"
                            title="Stored in browser only — backend endpoint not yet shipped"
                          >
                            local only
                          </span>
                        )}
                      </div>
                      <div className="truncate font-mono text-[10px] tabular-nums text-muted-foreground">
                        {rule.condition || "(no condition)"}
                      </div>
                    </div>

                    {/* Enabled toggle */}
                    <label className="flex cursor-pointer items-center gap-1 text-[10px] text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={rule.enabled}
                        onChange={(e) => void handleToggleEnabled(rule.id, e.target.checked)}
                        className="h-3 w-3 accent-primary"
                        aria-label={`Toggle rule ${rule.name}`}
                      />
                      {rule.enabled ? "on" : "off"}
                    </label>

                    {/* Edit */}
                    <button
                      type="button"
                      onClick={() => beginEdit(rule)}
                      className="rounded-[2px] p-1 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
                      aria-label={`Edit rule ${rule.name}`}
                    >
                      <Pencil className="h-3 w-3" aria-hidden="true" />
                    </button>

                    {/* Delete */}
                    <button
                      type="button"
                      onClick={() => void handleDelete(rule.id)}
                      className="rounded-[2px] p-1 text-muted-foreground hover:bg-destructive/20 hover:text-destructive"
                      aria-label={`Delete rule ${rule.name}`}
                    >
                      <Trash2 className="h-3 w-3" aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>

          {/* ── Edit tab ──────────────────────────────────────────────── */}
          <TabsContent value="edit" className="pt-2">
            <div className="flex flex-col gap-3">
              {/* Name */}
              <FieldLabel label="Name (optional)">
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={defaultRuleName(type, entitySearch, condition)}
                  className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </FieldLabel>

              {/* Type */}
              <FieldLabel label="Rule type">
                <select
                  value={type}
                  onChange={(e) => setType(e.target.value as AlertRule["type"])}
                  className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {RULE_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {RULE_TYPE_LABEL[t]}
                    </option>
                  ))}
                </select>
              </FieldLabel>

              {/* Entity */}
              <FieldLabel label="Entity / ticker (optional)">
                <input
                  type="text"
                  value={entitySearch}
                  onChange={(e) => setEntitySearch(e.target.value)}
                  placeholder="e.g. AAPL"
                  className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </FieldLabel>

              {/* Condition */}
              <FieldLabel label="Condition">
                <input
                  type="text"
                  value={condition}
                  onChange={(e) => setCondition(e.target.value)}
                  placeholder={CONDITION_PLACEHOLDER[type]}
                  className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  aria-label="Rule condition"
                />
              </FieldLabel>

              {/* Notification toggles */}
              <div className="flex gap-4">
                <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-foreground">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                    className="h-3.5 w-3.5 rounded-[2px] accent-primary"
                  />
                  Enabled
                </label>
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

              {/* Footer actions */}
              <div className="flex items-center justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => {
                    resetForm();
                    setTab("list");
                  }}
                  className="rounded-[2px] px-3 py-1 text-[11px] text-muted-foreground hover:text-foreground"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void handleSave()}
                  disabled={!condition.trim()}
                  className={cn(
                    "rounded-[2px] bg-primary px-3 py-1 text-[11px] text-primary-foreground",
                    "hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40",
                  )}
                >
                  {editingId ? "Save changes" : "Create rule"}
                </button>
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

// ── FieldLabel ─────────────────────────────────────────────────────────────

/**
 * FieldLabel — label + child input wrapper. Keeps spacing consistent.
 */
function FieldLabel({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}
