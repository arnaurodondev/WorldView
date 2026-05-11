/**
 * lib/notification-prefs.ts — typed wrapper around localStorage notification prefs
 *
 * WHY THIS EXISTS (PLAN-0051 Wave D T-D-4-07):
 * Users need a place to control which alert channels are active (in-app,
 * email digest, browser push) and define quiet-hours so a CRITICAL signal
 * fired at 04:00 doesn't wake them up. Phase 1 of this is a localStorage MVP —
 * it lives entirely on the client until S10 grows a `/v1/preferences/alerts`
 * endpoint. Centralising the read/write in one module means both the
 * Settings dialog and the AlertStreamContext (FlashOverlay severity floor,
 * future quiet-hours suppression) read the exact same shape with no drift.
 *
 * WHY NOT useState IN THE DIALOG: any consumer that wants to gate behaviour
 * (e.g. "should I render this overlay right now?") needs synchronous access.
 * A pure function returning the current value is the cheapest API.
 *
 * STORAGE KEY: `worldview:notificationPrefs:v1` — the `:v1` suffix lets us
 * evolve the schema later (e.g. per-channel severity floor) without
 * silently corrupting old payloads. If we ever add `:v2`, callers should
 * migrate-on-read by checking both keys.
 *
 * SAFETY: every accessor is wrapped in try/catch because:
 *   1. SSR has no `localStorage`,
 *   2. Some browsers throw QuotaExceededError under storage pressure,
 *   3. JSON.parse on a corrupted blob would crash the page.
 */

import type { AlertSeverity } from "@/types/api";

// ── Types ──────────────────────────────────────────────────────────────────

/**
 * NotificationPrefs — shape of the persisted preferences blob.
 *
 * WHY HH:mm strings (not Date objects): JSON-friendly + matches the native
 * `<input type="time">` value contract. We never compare across timezones —
 * quiet-hours are interpreted in the user's local clock.
 */
export interface NotificationPrefs {
  /** Show alert overlays + sidebar badge inside the app. */
  inAppEnabled: boolean;
  /** Subscribe to the daily email digest. */
  emailDigestOptIn: boolean;
  /** Show OS-level browser notifications via `Notification` API. */
  browserPushEnabled: boolean;
  /** Local time "HH:mm" — start of the quiet window. Optional. */
  quietHoursStart?: string;
  /** Local time "HH:mm" — end of the quiet window. Optional. */
  quietHoursEnd?: string;
  /** Minimum severity that should breach quiet-hours / overlay rules. */
  severityFloor: AlertSeverity;
}

// ── Constants ──────────────────────────────────────────────────────────────

/** localStorage namespace — versioned so we can evolve the schema later. */
const STORAGE_KEY = "worldview:notificationPrefs:v1";

/**
 * DEFAULT_PREFS — sensible defaults for first-time users.
 *
 * WHY in-app on, email off, push off:
 *   - in-app is zero-friction — already on the user's screen,
 *   - email requires backend wiring (S1 EmailPreference, PRD-0017) and
 *     opt-in consent so we keep it OFF by default,
 *   - browser push needs an explicit `Notification.requestPermission()`
 *     gesture — defaulting it to false matches the actual browser state.
 */
export const DEFAULT_PREFS: NotificationPrefs = {
  inAppEnabled: true,
  emailDigestOptIn: false,
  browserPushEnabled: false,
  severityFloor: "LOW",
};

// ── Validation helpers ────────────────────────────────────────────────────

/**
 * isValidTimeString — true if the input matches HH:mm (24-hour).
 *
 * WHY validate: the dialog uses `<input type="time">` which is strict in
 * modern browsers, but we still defend against hand-edited localStorage
 * blobs that could feed garbage into the prefs and break downstream logic.
 */
export function isValidTimeString(value: unknown): value is string {
  if (typeof value !== "string") return false;
  // 00:00 through 23:59 — leading zeros required.
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

/** True if `severity` is one of the four AlertSeverity literals. */
function isValidSeverity(value: unknown): value is AlertSeverity {
  return value === "LOW" || value === "MEDIUM" || value === "HIGH" || value === "CRITICAL";
}

// ── Public API ────────────────────────────────────────────────────────────

/**
 * loadNotificationPrefs — read prefs from localStorage with a defaults fallback.
 *
 * Always returns a fully-populated NotificationPrefs object, even if the
 * blob is missing, malformed, or partially populated (forward-compat with
 * future schema evolution — e.g. a future field defaults to its DEFAULT_PREFS
 * value rather than `undefined`).
 */
export function loadNotificationPrefs(): NotificationPrefs {
  if (typeof window === "undefined") return { ...DEFAULT_PREFS };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_PREFS };
    const parsed = JSON.parse(raw) as Partial<NotificationPrefs> | null;
    if (!parsed || typeof parsed !== "object") return { ...DEFAULT_PREFS };
    // Merge into defaults so missing keys survive a schema bump.
    const merged: NotificationPrefs = {
      ...DEFAULT_PREFS,
      ...parsed,
      // Re-validate the fields that have non-trivial constraints:
      severityFloor: isValidSeverity(parsed.severityFloor)
        ? parsed.severityFloor
        : DEFAULT_PREFS.severityFloor,
      quietHoursStart: isValidTimeString(parsed.quietHoursStart) ? parsed.quietHoursStart : undefined,
      quietHoursEnd: isValidTimeString(parsed.quietHoursEnd) ? parsed.quietHoursEnd : undefined,
    };
    return merged;
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

/**
 * saveNotificationPrefs — persist prefs to localStorage.
 *
 * WHY swallow errors: QuotaExceededError or storage being unavailable
 * (private mode) shouldn't break the dialog UX. The dialog re-reads
 * via loadNotificationPrefs so the user will see whichever value
 * actually persisted.
 */
export function saveNotificationPrefs(prefs: NotificationPrefs): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // ignore — quota / private-mode / SSR
  }
}

/**
 * isInQuietHours — given a clock time, return true if the user is in the
 * configured quiet window.
 *
 * WHY exported: the AlertStreamContext (future wave) will call this to
 * decide whether to suppress flash overlays for sub-CRITICAL alerts.
 *
 * Handles wrap-around (e.g. 22:00 → 06:00 spans midnight) by detecting
 * `start >= end` and inverting the comparison.
 */
export function isInQuietHours(prefs: NotificationPrefs, now = new Date()): boolean {
  const { quietHoursStart, quietHoursEnd } = prefs;
  if (!quietHoursStart || !quietHoursEnd) return false;
  const minutes = now.getHours() * 60 + now.getMinutes();
  const [sh, sm] = quietHoursStart.split(":").map(Number);
  const [eh, em] = quietHoursEnd.split(":").map(Number);
  const startMin = sh * 60 + sm;
  const endMin = eh * 60 + em;
  if (startMin === endMin) return false; // zero-length window
  if (startMin < endMin) {
    // Same-day window (e.g. 13:00 → 17:00).
    return minutes >= startMin && minutes < endMin;
  }
  // Wrap window (e.g. 22:00 → 06:00).
  return minutes >= startMin || minutes < endMin;
}
