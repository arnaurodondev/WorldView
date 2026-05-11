/**
 * lib/gateway.ts — Typed S9 API Gateway client (composition shim).
 *
 * WHY THIS FILE EXISTS: Single entry point for all S9 API calls from the
 * frontend. Components NEVER call fetch() directly — they call
 * `createGateway(token).<method>()` and never know which sub-module owns
 * the method. This is a backwards-compatible shim that merges the
 * per-domain modules under `lib/api/*.ts` into one object identical to the
 * pre-split monolith. ~91 import sites depend on the surface staying stable.
 *
 * Benefits of the per-domain split (PLAN-0059-E):
 * 1. Each `lib/api/*.ts` is <450 LOC — fits in a single read
 * 2. Domain isolation: `lib/api/auth.ts` change doesn't touch `lib/api/portfolios.ts`
 * 3. CI gate: `lib/api/*.ts` files >350 LOC fail build (forces further splits)
 * 4. Mocking gets simpler: tests can stub a single domain factory
 *
 * Method resolution: every domain factory returns an object whose methods are
 * defined with object-method syntax (dynamic `this`). When merged here via
 * spread, `this` inside any method resolves to the merged result, so calls
 * like `this.getCompanyOverview(...)` (from search) and
 * `this.getWatchlistMembers(...)` (from watchlists) reach the right method.
 *
 * WHO USES IT: TanStack Query queryFn callbacks in all feature components.
 * Usage: const { data } = useQuery({ queryFn: () => gw.getPortfolios() })
 *        where gw = createGateway(accessToken)
 *
 * DATA SOURCE: All calls go to /api/* which next.config.ts rewrites to
 * API_GATEWAY_URL (S9 FastAPI at localhost:8000 in dev).
 *
 * DESIGN REFERENCE: docs/specs/0028-worldview-web-frontend.md §6.2
 * SECURITY: Access token NEVER stored in localStorage — passed as parameter.
 *           Token is in React state (AuthContext) only.
 */

import { createAuthApi } from "./api/auth";
import { createInstrumentsApi } from "./api/instruments";
import { createKnowledgeGraphApi } from "./api/knowledge-graph";
import { createNewsApi } from "./api/news";
import { createScreenerApi } from "./api/screener";
import { createPortfoliosApi } from "./api/portfolios";
import { createWatchlistsApi } from "./api/watchlists";
import { createAlertsApi } from "./api/alerts";
import { createChatApi } from "./api/chat";
import { createPredictionMarketsApi } from "./api/prediction-markets";
import { createDashboardApi } from "./api/dashboard";
import { createBrokerageApi } from "./api/brokerage";
import { createSearchApi } from "./api/search";
import { createFeedbackApi } from "./api/feedback";

// Re-export so consumers keep importing from "@/lib/gateway" — no churn at
// the ~91 call sites. GatewayError is `instanceof`-checked in components.
export { GatewayError } from "./api/_client";

/**
 * createGateway — creates a typed gateway instance bound to an access token
 *
 * WHY factory (not singleton): The access token changes on refresh.
 * Components call this inside TanStack Query's queryFn closure where they
 * have access to the latest token from useAuth():
 *
 *   const { accessToken } = useAuth()
 *   const { data } = useQuery({
 *     queryKey: ["portfolios"],
 *     queryFn: () => createGateway(accessToken).getPortfolios()
 *   })
 *
 * The queryFn re-runs on refetch, always using the latest token.
 *
 * IMPLEMENTATION: each domain factory closes over the same `t` value and
 * returns a plain object. We spread them in dependency order — instruments
 * before search (because search.searchFundamentals calls
 * this.getCompanyOverview), watchlists order doesn't matter (its self-calls
 * resolve through the merged `this`).
 */
export function createGateway(token?: string | null) {
  const t = token ?? undefined;

  return {
    // Order: deepest cross-domain dependencies first. searchFundamentals
    // depends on getCompanyOverview, so instruments must be spread before
    // search. All other factories are independent of each other.
    ...createAuthApi(t),
    ...createInstrumentsApi(t),
    ...createKnowledgeGraphApi(t),
    ...createNewsApi(t),
    ...createScreenerApi(t),
    ...createPortfoliosApi(t),
    ...createWatchlistsApi(t),
    ...createAlertsApi(t),
    ...createChatApi(t),
    ...createPredictionMarketsApi(t),
    ...createDashboardApi(t),
    ...createBrokerageApi(t),
    ...createSearchApi(t),
    ...createFeedbackApi(t),
  };
}

/**
 * Type of the gateway object (for mocking in tests)
 * Usage: const mockGateway: Gateway = { ... }
 */
export type Gateway = ReturnType<typeof createGateway>;
