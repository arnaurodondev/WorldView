/**
 * components/alerts/NotificationPreferencesDialog.tsx — alert notification settings
 *
 * WHY THIS EXISTS (PLAN-0051 Wave D T-D-4-07):
 * Traders need a single place to control which alert channels are active
 * (in-app, email digest, browser push), set quiet-hours so a CRITICAL signal
 * fired at 04:00 doesn't wake them up, and define a severity floor below
 * which alerts are suppressed entirely. This dialog is the MVP UI for those
 * preferences — values persist via lib/notification-prefs.ts (localStorage).
 *
 * WHY DIALOG (not Sheet): the prefs surface is a discrete settings sub-page
 * that doesn't need to coexist with the alerts list — a centred modal is
 * the convention used by the Settings page for similar surfaces.
 *
 * WHY BROWSER PUSH IS A "TRY-AND-SEE" TOGGLE: the `Notification` API requires
 * a synchronous user gesture to open the permission prompt. We call
 * `Notification.requestPermission()` only when the user actively flips the
 * toggle on. If they deny we revert the toggle silently — there is no
 * server-side state to keep in sync.
 */

"use client";
// WHY "use client": uses useState (form state), localStorage, and the
// browser-only Notification API.

import { useEffect, useState } from "react";
import { Bell } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  loadNotificationPrefs,
  saveNotificationPrefs,
  isValidTimeString,
  DEFAULT_PREFS,
  type NotificationPrefs,
} from "@/lib/notification-prefs";
import type { AlertSeverity } from "@/types/api";

// ── Constants ──────────────────────────────────────────────────────────────

/**
 * SEVERITY_OPTIONS — render order of the severity-floor picker.
 *
 * WHY ascending (LOW → CRITICAL): the picker reads "show me alerts at this
 * level OR ABOVE". Ascending order makes the implicit floor obvious.
 */
const SEVERITY_OPTIONS: AlertSeverity[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

// ── Component ──────────────────────────────────────────────────────────────

interface NotificationPreferencesDialogProps {
  /**
   * Optional callback fired after Save — lets the parent re-read prefs without
   * a full re-render of the alerts page (e.g. update a "Quiet hours active"
   * indicator in the toolbar).
   */
  onSaved?: (prefs: NotificationPrefs) => void;
}

export function NotificationPreferencesDialog({ onSaved }: NotificationPreferencesDialogProps = {}) {
  const [open, setOpen] = useState(false);

  // ── Form state ─────────────────────────────────────────────────────────
  // WHY mirror the persisted blob in local state: gives us inline cancel
  // (close without save), and prevents intermediate keystrokes from being
  // committed to localStorage on every change.
  const [prefs, setPrefs] = useState<NotificationPrefs>(DEFAULT_PREFS);

  // Re-load every time the dialog opens — covers the case where the user
  // edited prefs in another tab and re-opened this one.
  useEffect(() => {
    if (open) setPrefs(loadNotificationPrefs());
  }, [open]);

  // ── Field updaters ─────────────────────────────────────────────────────

  /**
   * setField — generic patcher to keep the JSX terse.
   * WHY a callback (not direct setState): we need to merge with current state
   * without forcing each handler to spread the prior object inline.
   */
  function setField<K extends keyof NotificationPrefs>(key: K, value: NotificationPrefs[K]) {
    setPrefs((prev) => ({ ...prev, [key]: value }));
  }

  /**
   * handleBrowserPushToggle — request permission on opt-in.
   *
   * WHY the order: we flip the local state FIRST (so the UI is responsive),
   * then call requestPermission(). If the user denies, we revert.
   */
  async function handleBrowserPushToggle(next: boolean) {
    if (!next) {
      setField("browserPushEnabled", false);
      return;
    }
    if (typeof window === "undefined" || !("Notification" in window)) {
      // Browser doesn't support the API at all — no-op + leave toggle off.
      return;
    }
    setField("browserPushEnabled", true);
    try {
      const result = await Notification.requestPermission();
      if (result !== "granted") {
        setField("browserPushEnabled", false);
      }
    } catch {
      // Some browsers throw on insecure origins — revert silently.
      setField("browserPushEnabled", false);
    }
  }

  // ── Save handler ───────────────────────────────────────────────────────

  /**
   * handleSave — validate quiet-hours, persist, close.
   *
   * WHY validate at save (not on each keystroke): native `<input type="time">`
   * already constrains to HH:mm — but localStorage may have malformed entries.
   * This guard is a belt-and-suspenders.
   */
  function handleSave() {
    const cleaned: NotificationPrefs = {
      ...prefs,
      quietHoursStart: isValidTimeString(prefs.quietHoursStart) ? prefs.quietHoursStart : undefined,
      quietHoursEnd: isValidTimeString(prefs.quietHoursEnd) ? prefs.quietHoursEnd : undefined,
    };
    saveNotificationPrefs(cleaned);
    onSaved?.(cleaned);
    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {/* Trigger — a small "Preferences" button matching the rule manager style */}
      <DialogTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-1 rounded-[2px] border border-border/40 bg-muted/20 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          aria-label="Notification preferences"
        >
          <Bell className="h-3 w-3" aria-hidden="true" />
          Preferences
        </button>
      </DialogTrigger>

      <DialogContent className="w-full max-w-md">
        <DialogHeader>
          <DialogTitle className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            NOTIFICATION PREFERENCES
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3 pt-1">
          {/* In-app — always available */}
          <ToggleRow
            label="In-app notifications"
            help="Show alert overlays + sidebar badge while the app is open."
            checked={prefs.inAppEnabled}
            onChange={(v) => setField("inAppEnabled", v)}
          />

          {/* Email digest */}
          <ToggleRow
            label="Daily email digest"
            help="Summary of new alerts emailed once per day."
            checked={prefs.emailDigestOptIn}
            onChange={(v) => setField("emailDigestOptIn", v)}
          />

          {/* Browser push */}
          <ToggleRow
            label="Browser notifications"
            help="OS-level alerts even when the tab is in the background."
            checked={prefs.browserPushEnabled}
            onChange={(v) => void handleBrowserPushToggle(v)}
          />

          {/* Severity floor */}
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              Severity floor
            </label>
            <select
              value={prefs.severityFloor}
              onChange={(e) => setField("severityFloor", e.target.value as AlertSeverity)}
              className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              aria-label="Minimum alert severity"
            >
              {SEVERITY_OPTIONS.map((sev) => (
                <option key={sev} value={sev}>
                  {sev}
                </option>
              ))}
            </select>
            <span className="text-[10px] text-muted-foreground/70">
              Suppress alerts below this severity entirely.
            </span>
          </div>

          {/* Quiet hours */}
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              Quiet hours (local time)
            </label>
            <div className="flex items-center gap-2">
              <input
                type="time"
                value={prefs.quietHoursStart ?? ""}
                onChange={(e) => setField("quietHoursStart", e.target.value || undefined)}
                className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                aria-label="Quiet hours start"
              />
              <span className="text-[10px] text-muted-foreground">→</span>
              <input
                type="time"
                value={prefs.quietHoursEnd ?? ""}
                onChange={(e) => setField("quietHoursEnd", e.target.value || undefined)}
                className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                aria-label="Quiet hours end"
              />
            </div>
            <span className="text-[10px] text-muted-foreground/70">
              Leave blank to disable. Wrap-around windows (22:00 → 06:00) supported.
            </span>
          </div>

          {/* Footer actions */}
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
              className={cn(
                "rounded-[2px] bg-primary px-3 py-1 text-[11px] text-primary-foreground",
                "hover:bg-primary/90",
              )}
            >
              Save
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── ToggleRow ──────────────────────────────────────────────────────────────

/**
 * ToggleRow — label + help text + checkbox laid out consistently.
 *
 * WHY a sub-component: three toggles in this dialog share the same shape;
 * extracting eliminates copy-paste and keeps the styling centralised.
 */
function ToggleRow({
  label,
  help,
  checked,
  onChange,
}: {
  label: string;
  help: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 rounded-[2px] border border-border/30 bg-muted/10 p-2 hover:bg-muted/20">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-3.5 w-3.5 rounded-[2px] accent-primary"
      />
      <div className="flex-1">
        <div className="text-[11px] text-foreground">{label}</div>
        <div className="text-[10px] text-muted-foreground/80">{help}</div>
      </div>
    </label>
  );
}
