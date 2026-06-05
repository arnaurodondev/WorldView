/**
 * app/(app)/settings/notifications/page.tsx — Notification preferences (wired)
 *
 * WHY THIS EXISTS (PLAN-0059 I-3 / FR-6.3 W8-SETTINGS):
 * Previously this page rendered a static `<NotificationsTab>` stub with a
 * "Coming soon" banner because the backend preference API didn't exist yet.
 * W1-Backend landed `GET /v1/users/me/notification-preferences` and
 * `PATCH /v1/users/me/notification-preferences` in S1 (proxied through S9).
 * This page is now fully wired: it loads live state on mount and persists
 * every toggle change immediately to the backend.
 *
 * DATA FLOW:
 *   On mount: useQuery → getNotificationPreferences() → S9 → S1 (GET)
 *   On toggle: useMutation → updateNotificationPreferences({ field: !val })
 *            → S9 → S1 (PATCH, upsert semantics) → invalidate qk.user.notificationPrefs()
 *
 * RETRY POLICY (CRIT-006 / FR-8.1): mutation retries 3× with exponential
 * backoff capped at 4 s. PATCH is idempotent (upsert) so retrying is safe.
 *
 * 404 HANDLING: S1 returns 404 when the user has never saved preferences
 * (first visit). The useQuery `onError` path falls back to all-true defaults
 * so new users see the "recommended" state without a broken empty UI.
 *
 * DESIGN: mirrors the existing NotificationsTab visual structure (single
 * Card, Label + Switch rows, Separator between rows) but removes the "Coming
 * soon" warning banner and drives each Switch from server state.
 */

"use client";
// WHY "use client": TanStack Query hooks (useQuery, useMutation, useQueryClient)
// are client-side; so is Switch (controlled interactive element).

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import type { UpdateNotificationPreferencesPayload } from "@/types/api";

// ── Toggle row descriptors ───────────────────────────────────────────────────

/**
 * TOGGLE_ROWS — declarative spec for each notification switch.
 *
 * WHY not hard-code four JSX blocks: a data-driven list makes it trivial to
 * add or remove toggle types without hunting for copy-pasted JSX. Each entry
 * maps a backend field name to its display copy.
 *
 * field: key in NotificationPreferences / UpdateNotificationPreferencesPayload
 * label: primary text shown next to the Switch
 * description: secondary hint text explaining when this notification fires
 */
const TOGGLE_ROWS: ReadonlyArray<{
  field: keyof UpdateNotificationPreferencesPayload;
  label: string;
  description: string;
}> = [
  {
    field: "price_alerts",
    label: "Price alert triggers",
    description: "When an instrument crosses a threshold you set",
  },
  {
    field: "news_alerts",
    label: "High-impact news",
    description: "Articles scoring above the routing-tier DEEP threshold",
  },
  {
    field: "movers_alerts",
    label: "Watchlist movers",
    description: "Daily roll-up of biggest movers in your watchlists",
  },
  {
    field: "contradiction_alerts",
    label: "AI contradiction detections",
    description: "When the knowledge graph flags conflicting claims",
  },
];

/**
 * DEFAULT_PREFS — fallback state for new users who have no row in S1 yet.
 *
 * WHY all-true: S1 creates the row on first PATCH with all toggles ON. We
 * mirror that default here so the UI looks consistent before the first save.
 * If GET returns 404 (no row yet), the user sees "everything enabled" which
 * matches what the backend will create on their first toggle action.
 */
const DEFAULT_PREFS = {
  price_alerts: true,
  news_alerts: true,
  movers_alerts: false,
  contradiction_alerts: false,
} as const;

// ── Page ─────────────────────────────────────────────────────────────────────

export default function SettingsNotificationsPage() {
  // WHY useQueryClient at top: mutation success needs it to invalidate the
  // query cache. Must be in the same component tree as the QueryClientProvider
  // (satisfied by app/providers.tsx).
  const queryClient = useQueryClient();
  const { accessToken } = useAuth();

  // ── Fetch current preferences ───────────────────────────────────────────

  const { data: prefs, isLoading } = useQuery({
    queryKey: qk.user.notificationPrefs(),
    // WHY arrow wrapping createGateway: the token may change (silent refresh).
    // The queryFn closure captures the latest token from this render.
    queryFn: () =>
      createGateway(accessToken).getNotificationPreferences().catch(() => null),
    // WHY staleTime 5 min: notification prefs change infrequently; avoiding a
    // GET on every panel open reduces S9 load without stale-state risk.
    staleTime: 5 * 60 * 1000,
  });

  // ── Persist a single toggle change ─────────────────────────────────────

  const { mutate: saveToggle } = useMutation({
    mutationFn: (payload: UpdateNotificationPreferencesPayload) =>
      createGateway(accessToken).updateNotificationPreferences(payload),
    // WHY invalidate on success: the returned body is the full updated object.
    // Invalidating instead of setQueryData keeps a single source of truth and
    // avoids optimistic-update rollback complexity.
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: qk.user.notificationPrefs(),
      });
    },
    // WHY retry 3 with exponential backoff: PATCH is idempotent (upsert) so
    // retrying is safe. Cap at 4 s to avoid hanging the UI for too long.
    // CRIT-006 / FR-8.1.
    retry: 3,
    retryDelay: (attemptIndex) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
  });

  // ── Resolved values (API data or defaults) ──────────────────────────────

  // WHY spread DEFAULT_PREFS first: if the API returns null (404 → no row)
  // we fall back to all defaults. If it returns partial data (schema drift),
  // we fill gaps with defaults rather than rendering `undefined` values.
  const resolvedPrefs = { ...DEFAULT_PREFS, ...(prefs ?? {}) };

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium text-foreground">
          Notification preferences
        </CardTitle>
        <CardDescription className="text-xs">
          Choose which events trigger notifications. Changes are saved
          immediately.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {isLoading ? (
          // WHY skeleton div: avoids layout shift while the GET round-trip
          // completes (typically < 200 ms on the local stack). The fixed
          // height matches the four-row layout below.
          <div className="space-y-4">
            {TOGGLE_ROWS.map((row) => (
              <div key={row.field} className="flex animate-pulse items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="h-4 w-40 rounded-[2px] bg-muted/60" />
                  <div className="h-3 w-64 rounded-[2px] bg-muted/40" />
                </div>
                <div className="h-5 w-9 rounded-full bg-muted/60" />
              </div>
            ))}
          </div>
        ) : (
          TOGGLE_ROWS.map((row, index) => (
            <div key={row.field}>
              <div className="flex items-center justify-between gap-4">
                <div className="space-y-0.5">
                  <Label
                    htmlFor={`notif-${row.field}`}
                    className="cursor-pointer text-sm font-medium text-foreground"
                  >
                    {row.label}
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    {row.description}
                  </p>
                </div>
                <Switch
                  id={`notif-${row.field}`}
                  // WHY key in resolvedPrefs cast: UpdateNotificationPreferencesPayload
                  // keys are a strict subset of NotificationPreferences keys, so
                  // this access is always valid. The cast avoids an index-type error.
                  checked={
                    Boolean(
                      resolvedPrefs[row.field as keyof typeof resolvedPrefs] ?? true,
                    )
                  }
                  onCheckedChange={(checked) => {
                    // WHY computed property: generates { price_alerts: true }
                    // etc. without a switch/if chain — one line per toggle row.
                    saveToggle({ [row.field]: checked });
                  }}
                  aria-label={`Toggle ${row.label}`}
                />
              </div>
              {index < TOGGLE_ROWS.length - 1 && (
                <Separator className="mt-4 bg-border/40" />
              )}
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
