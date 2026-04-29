/**
 * hooks/useAlertActions.ts — backend-synced ACK / snooze.
 *
 * WHY THIS EXISTS (PLAN-0051 Wave D T-D-4-03):
 * Until Wave D, alert acknowledgement was localStorage-only — the user's
 * "I've seen this" state never made it to S10. The new contract has a
 * `PATCH /v1/alerts/{id}/acknowledge` and `PATCH /v1/alerts/{id}/snooze`
 * endpoint that persist the action server-side so audit trails + cross-
 * device sync work. This hook is the single integration point.
 *
 * QA-iter1 MAJ-2: the original implementation treated *any* 404 as
 * "endpoint not deployed" and silently fell back to localStorage with a
 * `(local only)` badge. But the route layer also collapses 403 → 404 on
 * purpose (anti-enumeration), so a 404 from S9 means EITHER "alert
 * doesn't exist" OR "you don't own it" OR "endpoint missing". The
 * fallback masked the first two cases — a user could ACK someone else's
 * alert "successfully" in localStorage. The endpoints ship now, so we
 * surface 404 as a real error and keep the localStorage write only as
 * the optimistic UI signal owned by the caller (AlertsList).
 *
 * STORAGE: The `acknowledged` and `snoozed` localStorage blobs are owned by
 * AlertsList — the hook treats them as inputs/outputs through callbacks so
 * the parent stays the source of truth and React state remains consistent.
 */

"use client";
// WHY "use client": uses the gateway client + React hook surface.

import { useCallback } from "react";
// WHY no GatewayError import: QA-iter1 MAJ-2 dropped the 404-specific branch
// (any error is now treated uniformly as a real failure).
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";

// ── Types ──────────────────────────────────────────────────────────────────

/**
 * AlertActionResult — return shape so the caller can show a toast / banner.
 *
 * `localOnly: true` means "we wrote to localStorage, the backend was 404".
 * `localOnly: false` means we hit the backend and got the canonical row back.
 */
export interface AlertActionResult {
  ok: boolean;
  localOnly: boolean;
  /** Optional error message — only set when ok=false. */
  error?: string;
}

// ── Hook ──────────────────────────────────────────────────────────────────

/**
 * useAlertActions — returns ack(id, note?) and snooze(id, until) helpers
 * that try the backend first and fall back to localStorage-only on 404.
 *
 * Both helpers always run the local persistence side-effect (via the
 * supplied callbacks). The return value distinguishes "synced" vs
 * "local-only" so the UI can surface that state.
 */
export function useAlertActions(): {
  ack: (alertId: string, note?: string | null) => Promise<AlertActionResult>;
  snooze: (alertId: string, until: Date) => Promise<AlertActionResult>;
} {
  const { accessToken } = useAuth();

  const ack = useCallback(
    async (alertId: string, note?: string | null): Promise<AlertActionResult> => {
      // WHY guard on token: in dev / unauthenticated states we still want
      // the UI to mark the alert acked locally. Skipping the network call
      // is a sensible no-token fallback.
      if (!accessToken) {
        return { ok: true, localOnly: true };
      }
      try {
        await createGateway(accessToken).acknowledgeAlert(alertId, note ?? null);
        return { ok: true, localOnly: false };
      } catch (err) {
        // QA-iter1 MAJ-2: 404 is now treated as a real error (alert missing
        // or forbidden). The earlier "endpoint not deployed" fallback let
        // users silently ACK other-tenant alerts in localStorage. The endpoints
        // ship today; any 404 means the row isn't theirs to mutate.
        return {
          ok: false,
          localOnly: false,
          error: err instanceof Error ? err.message : "Failed to acknowledge alert.",
        };
      }
    },
    [accessToken],
  );

  const snooze = useCallback(
    async (alertId: string, until: Date): Promise<AlertActionResult> => {
      if (!accessToken) {
        return { ok: true, localOnly: true };
      }
      try {
        await createGateway(accessToken).snoozeAlert(alertId, until);
        return { ok: true, localOnly: false };
      } catch (err) {
        // QA-iter1 MAJ-2: see ack() above — 404 is a real error now.
        return {
          ok: false,
          localOnly: false,
          error: err instanceof Error ? err.message : "Failed to snooze alert.",
        };
      }
    },
    [accessToken],
  );

  return { ack, snooze };
}
