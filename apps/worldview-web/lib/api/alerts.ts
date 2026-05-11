/**
 * lib/api/alerts.ts — Alerts (pending/history) + acknowledge + snooze.
 *
 * Backed by S10 alert service through S9. PLAN-0051 Wave D introduced the
 * ack/history/snooze contract; before that the surface was just /pending.
 */

import type {
  Alert,
  AlertHistoryParams,
  AlertsResponse,
  PaginationParams,
} from "@/types/api";
import { apiFetch } from "./_client";

export function createAlertsApi(t: string | undefined) {
  return {
    /**
     * getPendingAlerts — paginated list of unacknowledged alerts
     */
    getPendingAlerts(params: PaginationParams = {}): Promise<AlertsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v != null)
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<AlertsResponse>(`/v1/alerts/pending${qs ? `?${qs}` : ""}`, {
        token: t,
      });
    },

    /**
     * acknowledgeAlert — mark alert as acknowledged via PATCH endpoint.
     *
     * PLAN-0051 Wave D update: previously this used DELETE /ack (legacy
     * "remove from pending" semantics). The new contract is
     * `PATCH /v1/alerts/{id}/acknowledge` with an optional note body — the row
     * is preserved in the table so we can render the History tab. We pass the
     * optional `note` so an analyst can attach context for the audit trail.
     *
     * WHY return Alert (not void): the parent updates its UI (move to acked
     * group, add to history) using the canonical row from the backend
     * (acknowledged_at, acknowledged_by, etc.). Returning the row keeps the
     * client cache one round-trip away from drift.
     *
     * BACKEND CONTRACT: implemented by the parallel S10 agent. If the endpoint
     * is not yet deployed, callers fall back to localStorage-only ACK and tag
     * the alert with `_localOnly: true`.
     */
    acknowledgeAlert(alertId: string, note?: string | null): Promise<Alert> {
      return apiFetch<Alert>(
        `/v1/alerts/${encodeURIComponent(alertId)}/acknowledge`,
        { method: "PATCH", body: { note: note ?? null }, token: t },
      );
    },

    /**
     * snoozeAlert — temporarily mute an alert until a given timestamp.
     *
     * PLAN-0051 Wave D new endpoint. Sends ISO-8601 UTC datetime as the
     * `until` field — this is the canonical contract pinned by the S10
     * SnoozeAlertRequest Pydantic schema (`services/alert/.../schemas.py`).
     * QA iter1 C-1: an earlier draft sent `snooze_until` which the backend
     * rejected with 422 — the contract is `until`, not `snooze_until`.
     * Snoozed alerts re-appear in the Active list once the timestamp is in
     * the past. Returning the canonical row lets the UI paint the
     * de-emphasised state immediately.
     */
    snoozeAlert(alertId: string, until: Date): Promise<Alert> {
      return apiFetch<Alert>(`/v1/alerts/${encodeURIComponent(alertId)}/snooze`, {
        method: "PATCH",
        // WHY `until` (not `snooze_until`): pinned by SnoozeAlertRequest in
        // services/alert/src/alert/api/schemas.py. See QA-iter1 C-1.
        body: { until: until.toISOString() },
        token: t,
      });
    },

    /**
     * getAlertHistory — paginated alert history (active + acked + snoozed).
     *
     * PLAN-0051 Wave D new endpoint. Powers the "History" tab on /alerts.
     * Filters supported by the backend:
     *   - status: "active" | "acknowledged" | "snoozed" | "all"
     *   - severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
     *   - from / to: ISO-8601 UTC datetimes
     *   - entity_id: filter to a single entity
     *   - limit / offset: standard pagination
     *
     * WHY a builder over URLSearchParams: passing `undefined` filters as empty
     * strings would over-constrain the query. We strip nullish values so an
     * unset filter is truly "any".
     */
    getAlertHistory(params: AlertHistoryParams = {}): Promise<AlertsResponse> {
      const entries: [string, string][] = [];
      // WHY explicit list (not Object.entries spread): keeps the query-param
      // shape stable & easy to grep when debugging which filters arrived.
      if (params.status) entries.push(["status", params.status]);
      // WHY toLowerCase: the frontend AlertSeverity type uses uppercase tokens
      // ("HIGH", "LOW", …) for display, but the backend Pydantic enum is
      // lowercase ("high", "low", …). Sending uppercase produces a 422 from
      // S10 (QA-iter1 C-2). We normalise here so the UI layer never has to
      // think about the wire shape.
      if (params.severity) entries.push(["severity", params.severity.toLowerCase()]);
      if (params.from) entries.push(["from", params.from]);
      if (params.to) entries.push(["to", params.to]);
      if (params.entity_id) entries.push(["entity_id", params.entity_id]);
      if (params.limit !== undefined) entries.push(["limit", String(params.limit)]);
      if (params.offset !== undefined) entries.push(["offset", String(params.offset)]);
      const qs = new URLSearchParams(entries).toString();
      return apiFetch<AlertsResponse>(`/v1/alerts/history${qs ? `?${qs}` : ""}`, {
        token: t,
      });
    },
  };
}
