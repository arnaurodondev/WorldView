/**
 * components/alerts/AlertRuleBuilder.tsx — Alert rule creation dialog
 *
 * WHY THIS EXISTS: Traders need to create custom alert rules without navigating
 * away from the Alerts page. This dialog provides a quick-entry form for the
 * most common rule types (Price Threshold, Volume Spike, News Signal, Portfolio Risk)
 * without requiring a dedicated settings page.
 *
 * WHY DIALOG (not Sheet): The shadcn/ui Sheet component is not installed in
 * this project. Dialog provides equivalent overlay behavior using the already-
 * installed @radix-ui/react-dialog dependency.
 *
 * WHY localStorage PERSISTENCE: Alert rules are a user preference stored
 * locally for the MVP. A future wave will sync them to S10 via the alerts API.
 * localStorage avoids a round-trip to the backend for MVP validation.
 *
 * WHO USES IT: app/(app)/alerts/page.tsx (+ Create Rule button)
 * DATA SOURCE: localStorage['worldview-alert-rules']
 * DESIGN REFERENCE: PRD-0031 §11 Alerts Wave 7
 */

"use client";
// WHY "use client": uses useState (form state, dialog open), localStorage.

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * AlertRule — a user-defined alert trigger stored in localStorage.
 * WHY id: rules need stable keys for deletion/editing in future waves.
 */
interface AlertRule {
  id: string;
  type: "price_threshold" | "volume_spike" | "news_signal" | "portfolio_risk";
  entitySearch: string;
  condition: string;
  notifyInApp: boolean;
  notifyEmail: boolean;
  createdAt: string; // ISO string
}

/** localStorage key for persisted rules */
const LS_RULES_KEY = "worldview-alert-rules";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Condition label changes based on rule type — contextualises the input */
const CONDITION_LABEL: Record<AlertRule["type"], string> = {
  price_threshold: "Condition (e.g. price > 150)",
  volume_spike: "Condition (e.g. volume > 2x 30d avg)",
  news_signal: "Condition (e.g. keyword: earnings)",
  portfolio_risk: "Condition (e.g. drawdown > 5%)",
};

/** Load saved rules from localStorage */
function loadRules(): AlertRule[] {
  try {
    const stored = localStorage.getItem(LS_RULES_KEY);
    return stored ? (JSON.parse(stored) as AlertRule[]) : [];
  } catch {
    return [];
  }
}

/** Save rules to localStorage */
function saveRules(rules: AlertRule[]): void {
  try {
    localStorage.setItem(LS_RULES_KEY, JSON.stringify(rules));
  } catch { /* ignore quota errors */ }
}

// ── Component ─────────────────────────────────────────────────────────────────

interface AlertRuleBuilderProps {
  /** Callback fired after a rule is saved — parent refreshes rule count */
  onRuleSaved?: () => void;
}

/**
 * AlertRuleBuilder — dialog form for creating alert rules.
 *
 * Exposes a trigger button (slot children) that opens the dialog.
 * After saving, rules are persisted to localStorage and onRuleSaved is called.
 */
export function AlertRuleBuilder({ onRuleSaved }: AlertRuleBuilderProps) {
  const [open, setOpen] = useState(false);

  // ── Form state ─────────────────────────────────────────────────────────────
  const [ruleType, setRuleType] = useState<AlertRule["type"]>("price_threshold");
  const [entitySearch, setEntitySearch] = useState("");
  const [condition, setCondition] = useState("");
  const [notifyInApp, setNotifyInApp] = useState(true);
  const [notifyEmail, setNotifyEmail] = useState(false);

  // ── Save handler ───────────────────────────────────────────────────────────
  const handleSave = () => {
    if (!condition.trim()) return; // WHY validate condition: empty rules have no effect

    const newRule: AlertRule = {
      id: typeof crypto !== "undefined" ? crypto.randomUUID() : `rule-${Date.now()}`,
      type: ruleType,
      entitySearch: entitySearch.trim(),
      condition: condition.trim(),
      notifyInApp,
      notifyEmail,
      createdAt: new Date().toISOString(),
    };

    const existing = loadRules();
    saveRules([...existing, newRule]);

    // Reset form
    setEntitySearch("");
    setCondition("");
    setNotifyInApp(true);
    setNotifyEmail(false);
    setRuleType("price_threshold");

    setOpen(false);
    onRuleSaved?.();
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>

      {/* Trigger — the "+ Create Rule" button */}
      <DialogTrigger asChild>
        <button
          type="button"
          // WHY rounded-[2px]: design system 2px radius everywhere
          className="rounded-[2px] border border-border/60 bg-muted/30 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted/60 hover:text-foreground"
        >
          + Create Rule
        </button>
      </DialogTrigger>

      <DialogContent className="w-full max-w-md">

        {/* ── Dialog header §0.9 pattern ──────────────────────────────────── */}
        <DialogHeader>
          <DialogTitle className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            CREATE ALERT RULE
          </DialogTitle>
        </DialogHeader>

        {/* ── Form body ─────────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-3 pt-1">

          {/* Rule type dropdown */}
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              Rule Type
            </label>
            <select
              value={ruleType}
              onChange={(e) => setRuleType(e.target.value as AlertRule["type"])}
              // WHY h-7 rounded-[2px]: all form inputs use this pattern per terminal design rules
              className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="price_threshold">Price Threshold</option>
              <option value="volume_spike">Volume Spike</option>
              <option value="news_signal">News Signal</option>
              <option value="portfolio_risk">Portfolio Risk</option>
            </select>
          </div>

          {/* Entity search input */}
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              Entity / Ticker (optional)
            </label>
            <input
              type="text"
              value={entitySearch}
              onChange={(e) => setEntitySearch(e.target.value)}
              placeholder="e.g. AAPL, NVDA"
              className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Condition input — label changes by rule type */}
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              {CONDITION_LABEL[ruleType]}
            </label>
            <input
              type="text"
              value={condition}
              onChange={(e) => setCondition(e.target.value)}
              placeholder={CONDITION_LABEL[ruleType]}
              className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Notification checkboxes */}
          <div className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              Notify Via
            </span>
            <div className="flex gap-4">
              {/* In-app notification */}
              <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-foreground">
                <input
                  type="checkbox"
                  checked={notifyInApp}
                  onChange={(e) => setNotifyInApp(e.target.checked)}
                  className="h-3.5 w-3.5 rounded-[2px] accent-primary"
                />
                In-app
              </label>

              {/* Email notification */}
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
          </div>

          {/* Save / Cancel actions */}
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-[2px] px-3 py-1 text-[11px] text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!condition.trim()}
              className={cn(
                "rounded-[2px] bg-primary px-3 py-1 text-[11px] text-primary-foreground",
                "hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40",
              )}
            >
              Save Rule
            </button>
          </div>

        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Rule count helper (exported for use in page toolbar) ─────────────────────

/**
 * getAlertRuleCount — returns the number of saved alert rules from localStorage.
 * WHY exported: the alerts page toolbar shows a rule count badge next to the
 * Manage Rules button without needing to mount AlertRuleBuilder.
 */
export function getAlertRuleCount(): number {
  return loadRules().length;
}
