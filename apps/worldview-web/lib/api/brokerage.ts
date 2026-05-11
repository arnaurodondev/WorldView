/**
 * lib/api/brokerage.ts — SnapTrade brokerage connection lifecycle.
 *
 * SCOPE: list / initiate / disconnect / sync / sync-errors / OAuth callback
 * activation. PRD-0022 §6.6 is the canonical reference.
 */

import type {
  BrokerageConnection,
  InitiateBrokerageConnectionResponse,
  SyncError,
} from "@/types/api";
import { apiFetch } from "./_client";

export function createBrokerageApi(t: string | undefined) {
  return {
    /**
     * getBrokerageConnections — list SnapTrade connections for the user
     *
     * WHY optional portfolioId: the UI can either show all connections (settings page)
     * or filter to a specific portfolio (portfolio brokerages tab). Both use cases
     * share this single method with an optional filter parameter.
     *
     * DATA SOURCE: S9 GET /api/v1/brokerage-connections?portfolio_id=...
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    async getBrokerageConnections(
      portfolioId?: string,
    ): Promise<BrokerageConnection[]> {
      // Build query string only when portfolioId is provided
      const qs = portfolioId
        ? `?portfolio_id=${encodeURIComponent(portfolioId)}`
        : "";

      const raw = await apiFetch<{ items: BrokerageConnection[] }>(
        `/v1/brokerage-connections${qs}`,
        { token: t },
      );

      // WHY ?? []: guard against S9 returning null items on empty result set
      return raw.items ?? [];
    },

    /**
     * initiateBrokerageConnection — create a pending connection and get redirect URI
     *
     * WHY snaptrade_tos_accepted: SnapTrade requires the end-user's explicit ToS
     * acceptance to be recorded with each connection initiation. The frontend
     * shows a checkbox in ConnectBrokerageModal that the user must tick before
     * this method is called — we forward their acceptance to S9/S1.
     *
     * On success: immediately redirect window.location.href to redirect_uri
     * (SnapTrade portal — user selects their broker and authorises access).
     *
     * DATA SOURCE: S9 POST /api/v1/brokerage-connections
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    initiateBrokerageConnection(
      portfolioId: string,
    ): Promise<InitiateBrokerageConnectionResponse> {
      return apiFetch<InitiateBrokerageConnectionResponse>(
        "/v1/brokerage-connections",
        {
          method: "POST",
          // WHY snaptrade_tos_accepted: true: the ConnectBrokerageModal checkbox
          // gate ensures the user has accepted ToS before triggering this mutation.
          body: { portfolio_id: portfolioId, snaptrade_tos_accepted: true },
          token: t,
        },
      );
    },

    /**
     * disconnectBrokerageConnection — revoke access and remove connection
     *
     * WHY void return: DELETE 204 has no response body. The component invalidates
     * the connection list query to reflect the removal in the UI.
     *
     * DATA SOURCE: S9 DELETE /api/v1/brokerage-connections/{id}
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    disconnectBrokerageConnection(connectionId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/brokerage-connections/${encodeURIComponent(connectionId)}`,
        { method: "DELETE", token: t },
      );
    },

    /**
     * triggerBrokerageSync — ask S1 to immediately re-sync this connection
     *
     * WHY 202 Accepted (not 200 OK): the sync is asynchronous — the worker picks
     * it up from a task queue. The response immediately confirms queuing, not
     * completion. The component should refetch connection list after a short delay
     * to see the updated last_synced_at and status.
     *
     * DATA SOURCE: S9 POST /api/v1/brokerage-connections/{id}/sync
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    triggerBrokerageSync(
      connectionId: string,
    ): Promise<{ status: string; connection_id: string }> {
      return apiFetch<{ status: string; connection_id: string }>(
        `/v1/brokerage-connections/${encodeURIComponent(connectionId)}/sync`,
        { method: "POST", token: t },
      );
    },

    /**
     * getSyncErrors — list transaction-level sync errors for a connection
     *
     * WHY these are non-fatal: sync errors are per-transaction (unknown instrument,
     * unsupported type, etc.). Other transactions in the same sync succeeded.
     * The UI shows them as warnings in SyncErrorsBanner, not as connection failures.
     *
     * DATA SOURCE: S9 GET /api/v1/brokerage-connections/{id}/sync-errors?limit=N
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    async getSyncErrors(connectionId: string, limit = 50): Promise<SyncError[]> {
      const raw = await apiFetch<{ items: SyncError[] }>(
        `/v1/brokerage-connections/${encodeURIComponent(connectionId)}/sync-errors?limit=${limit}`,
        { token: t },
      );

      // WHY ?? []: guard against null items field on empty error list
      return raw.items ?? [];
    },

    /**
     * activateBrokerageConnection — complete the OAuth callback flow
     *
     * WHY this is a GET (not POST): SnapTrade redirects the user's browser to
     * our callback page with params in the URL query string. We call S9's GET
     * endpoint with those params to activate the connection server-side.
     *
     * DATA SOURCE: S9 GET /api/v1/brokerage-connections/{id}/callback
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    activateBrokerageConnection(
      connectionId: string,
      params: { authorizationId: string; userId: string; sessionId: string },
    ): Promise<BrokerageConnection> {
      const qs = new URLSearchParams({
        authorizationId: params.authorizationId,
        userId: params.userId,
        sessionId: params.sessionId,
      }).toString();

      return apiFetch<BrokerageConnection>(
        `/v1/brokerage-connections/${encodeURIComponent(connectionId)}/callback?${qs}`,
        { token: t },
      );
    },
  };
}
