/**
 * lib/api/notification-preferences.ts — User notification-preference API client.
 *
 * WHY THIS FILE EXISTS (MED-022 / FR-6.3):
 * S1 gained `GET /v1/users/me/notification-preferences` and
 * `PATCH /v1/users/me/notification-preferences` endpoints (W1-Backend audit
 * confirms both live and proxied through S9). The settings page needs a way
 * to read and write the user's four alert-toggle flags without reaching into
 * the backend directly.
 *
 * SCOPE: two methods only — getNotificationPreferences and
 * updateNotificationPreferences. No TanStack hooks here: hooks that consume
 * these live in `hooks/useNotificationPreferences.ts` (or can be written
 * inline by any settings component). Keeping the API layer free of hooks
 * maintains the same separation used throughout `lib/api/*.ts`.
 *
 * IDEMPOTENCY (MED-022 FR-8.1): PATCH has upsert semantics — safe to retry.
 * The hook layer should add `retry: 3` + exponential backoff per CRIT-006.
 *
 * QUERY KEY: `qk.user.notificationPrefs()` already exists in lib/query/keys.ts.
 * Use it for both useQuery and useMutation invalidation.
 *
 * DATA FLOW:
 *   Frontend → /api/v1/users/me/notification-preferences
 *            → (Next.js rewrite) S9 proxy → S1 GET/PATCH endpoint
 *            ← S1 returns NotificationPreferencesResponse (upserted on PATCH)
 *
 * SECURITY: token is injected per-call via apiFetch options.token (Bearer).
 * The route is auth-only on S9/S1 — 401 when token is absent or expired.
 */

import type {
  NotificationPreferences,
  UpdateNotificationPreferencesPayload,
} from "@/types/api";
import { apiFetch } from "./_client";

// ── API path constant ─────────────────────────────────────────────────────────

/**
 * Canonical path for both GET and PATCH. Defined once so a future route
 * change only touches this file.
 */
const PREFS_PATH = "/v1/users/me/notification-preferences" as const;

// ── Factory ───────────────────────────────────────────────────────────────────

/**
 * createNotificationPreferencesApi — returns the two preference methods.
 *
 * Follows the exact same factory pattern as createPortfoliosApi, createWatchlistsApi,
 * etc. — takes the access token at construction time and closes over it so the
 * gateway shim can spread the result into the merged gateway object.
 *
 * @param t  Access token from useAuth / createGateway. Undefined = unauthenticated
 *           (the apiFetch wrapper omits the Authorization header when falsy).
 */
export function createNotificationPreferencesApi(t: string | undefined) {
  return {
    /**
     * getNotificationPreferences — fetch the user's four alert-toggle states.
     *
     * WHY this can return a "defaulted" object: S1 creates the preferences row
     * on first PATCH. Before that, the backend returns `null` or 404. The
     * frontend settings page should treat a missing row as "all toggles ON"
     * (the confirmed S1 default). This method surfaces a 404 as a GatewayError
     * so the caller can decide — use a try/catch or `onError` to return a
     * default in the hook layer.
     *
     * BACKEND: GET /v1/users/me/notification-preferences → 200 with
     *   NotificationPreferencesResponse OR 404 when no row exists yet.
     */
    getNotificationPreferences(): Promise<NotificationPreferences> {
      // WHY GET with no body: RESTful read, no side effects. The apiFetch
      // wrapper defaults method to GET when none is specified.
      return apiFetch<NotificationPreferences>(PREFS_PATH, { token: t });
    },

    /**
     * updateNotificationPreferences — partial-update (upsert) the user's prefs.
     *
     * WHY PATCH (not PUT): the backend accepts partial bodies — only the supplied
     * fields are updated; omitted fields keep their current values. PUT would
     * require the full object, which forces the client to read-before-write.
     *
     * WHY upsert semantics: S1 creates the row on first PATCH, so there's no
     * need for the frontend to call GET first to check whether the row exists.
     * This is idempotent and safe to retry (CRIT-006 / FR-8.1).
     *
     * BACKEND: PATCH /v1/users/me/notification-preferences → 200 with the
     *   full updated NotificationPreferencesResponse (not just the patched fields).
     *
     * @param payload  Partial preference flags. Only supplied fields are applied.
     */
    updateNotificationPreferences(
      payload: UpdateNotificationPreferencesPayload,
    ): Promise<NotificationPreferences> {
      // WHY body: PATCH semantics require a JSON body with the fields to update.
      // The apiFetch wrapper serialises it with JSON.stringify automatically.
      return apiFetch<NotificationPreferences>(PREFS_PATH, {
        method: "PATCH",
        body: payload,
        token: t,
      });
    },
  };
}
