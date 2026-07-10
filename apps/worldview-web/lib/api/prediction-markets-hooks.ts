/**
 * lib/api/prediction-markets-hooks.ts — TanStack Query hooks for the
 * prediction-markets analytical surface (PLAN-0056 Wave E2).
 *
 * WHY A SEPARATE HOOKS MODULE (not inline useQuery in each component):
 * the ProbabilityChart, the MarketDetailSheet and the EntityPredictionsSection
 * all need the same fetch+cache policy (staleTime, token-gating, query keys). A
 * shared hook keeps those policies in ONE place — a stale-time change is a
 * single edit, and every component gets the same cache slot so re-opening the
 * detail Sheet for a market you already looked at is instant.
 *
 * WHY useAuth()+createGateway (mirrors the page + EarningsBarChart, NOT the
 * intelligence hooks' useAccessToken): the primary consumer is the
 * /prediction-markets page which already reads `useAuth().accessToken`. Using
 * the same source here means the hooks and the page share one auth surface, and
 * unit tests mock exactly two modules (`@/hooks/useAuth` + `@/lib/gateway`) —
 * the same pair the existing prediction-markets-page test already mocks.
 *
 * ALL CALLS route through /api/v1/... → S9 (R14: frontend never talks to a
 * backend service directly).
 */

"use client";
// WHY "use client": TanStack Query hooks read React context (QueryClient) and
// the auth token — browser-only. Server Components cannot call them.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type {
  PredictionMarketPriceHistory,
  PredictionMarketTrades,
  PredictionEventsResponse,
  EntityPredictionsResponse,
} from "@/types/api";

// ── Stale-time policy ─────────────────────────────────────────────────────────
//
// WHY 60s for price history + trades: S3 re-snapshots prediction markets on a
// ~minute cadence, so a 1-minute window shows fresh odds/flow without hammering
// S9 every time the analyst flips the interval toggle (which re-keys the query).
//
// WHY 5min for events: event GROUPS (name/category/market_count) mutate only
// when new markets are ingested into an event — that is a slow, batch cadence.
// WHY 2min for entity predictions: the KG entity-linking + polarity pipeline
// updates these at pipeline cadence, between the two above.
const HISTORY_STALE_MS = 60_000;
const TRADES_STALE_MS = 60_000;
const EVENTS_STALE_MS = 5 * 60_000;
const ENTITY_PREDICTIONS_STALE_MS = 2 * 60_000;

// ── usePredictionMarketPriceHistory ───────────────────────────────────────────

/**
 * usePredictionMarketPriceHistory — interval price bars for a market's outcomes.
 *
 * WHY `interval` in the query key: each toggle position (1h/1d/1w) is a distinct
 * server response. Keying on it means flipping the toggle back to a previously
 * loaded interval renders instantly from cache instead of re-fetching.
 *
 * WHY enabled gates on BOTH conditionId AND token: the detail Sheet mounts this
 * hook unconditionally (hooks cannot be conditional). Until a market is selected
 * conditionId is "" — the gate keeps the query idle so no `/history` call for an
 * empty id ever fires. Token gate = no request while signed out.
 */
export function usePredictionMarketPriceHistory(
  conditionId: string,
  interval: "1h" | "1d" | "1w",
) {
  const { accessToken } = useAuth();
  return useQuery<PredictionMarketPriceHistory>({
    queryKey: ["prediction-market-price-history", conditionId, interval],
    queryFn: () =>
      createGateway(accessToken).getPredictionMarketPriceHistory(conditionId, interval),
    staleTime: HISTORY_STALE_MS,
    enabled: !!conditionId && !!accessToken,
  });
}

// ── usePredictionMarketTrades ─────────────────────────────────────────────────

/**
 * usePredictionMarketTrades — recent fills for a market (recent-flow strip).
 */
export function usePredictionMarketTrades(conditionId: string, limit = 30) {
  const { accessToken } = useAuth();
  return useQuery<PredictionMarketTrades>({
    queryKey: ["prediction-market-trades", conditionId, limit],
    queryFn: () =>
      createGateway(accessToken).getPredictionMarketTrades(conditionId, limit),
    staleTime: TRADES_STALE_MS,
    enabled: !!conditionId && !!accessToken,
  });
}

// ── usePredictionEvents ───────────────────────────────────────────────────────

/**
 * usePredictionEvents — Polymarket event groups for the Events section.
 *
 * WHY no id in the key: this is a global list (paginated), not entity-scoped —
 * it just needs auth.
 */
export function usePredictionEvents(params: { limit?: number; offset?: number } = {}) {
  const { accessToken } = useAuth();
  return useQuery<PredictionEventsResponse>({
    queryKey: ["prediction-events", params],
    queryFn: () => createGateway(accessToken).getPredictionEvents(params),
    staleTime: EVENTS_STALE_MS,
    enabled: !!accessToken,
  });
}

// ── useEntityPredictions ──────────────────────────────────────────────────────

/**
 * useEntityPredictions — markets referencing an entity, with polarity.
 *
 * WHY enabled gates on entityId: the sidebar mounts this before the URL param
 * resolves; without the guard the first render would hit
 * `/entities/undefined/predictions` → 422.
 */
export function useEntityPredictions(
  entityId: string,
  params: { limit?: number; offset?: number } = {},
) {
  const { accessToken } = useAuth();
  return useQuery<EntityPredictionsResponse>({
    queryKey: ["entity-predictions", entityId, params],
    queryFn: () => createGateway(accessToken).getEntityPredictions(entityId, params),
    staleTime: ENTITY_PREDICTIONS_STALE_MS,
    enabled: !!entityId && !!accessToken,
  });
}
