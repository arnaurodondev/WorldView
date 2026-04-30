/**
 * lib/api-client.tsx — Memoised gateway provider + hooks
 *
 * WHY THIS EXISTS: Before this module, every component that called the gateway
 * wrote the same five lines:
 *
 *   const { accessToken } = useAuth();
 *   const { data } = useQuery({
 *     queryKey: [...],
 *     queryFn: () => createGateway(accessToken).getThing(),
 *   });
 *
 * That meant `createGateway(accessToken)` ran on EVERY queryFn invocation —
 * once per fetch, once per refetch — across ~387 sites. The gateway object
 * is pure construction (no async work), but each call allocates ~80 closure
 * objects (one per method). At 387 sites with refetch-on-focus, this added
 * up to thousands of needless allocations on tab focus.
 *
 * `useApiClient()` returns a gateway instance memoised against the current
 * access token. Same token in → same gateway reference out. Components stop
 * re-creating gateways and stop having to pluck `accessToken` themselves.
 *
 * `useAuthedQuery()` is a thin wrapper around `useQuery` that:
 *  1. Auto-disables the query when the user is not authenticated (avoids the
 *     well-known "fired before token loaded → 401" race).
 *  2. Receives the gateway as the queryFn argument so call sites read as:
 *       useAuthedQuery({
 *         queryKey: qk.portfolios.list(),
 *         queryFn: (gw) => gw.getPortfolios(),
 *       });
 *
 * IDENTITY GUARANTEE: `useApiClient()` returns the SAME object reference for
 * the SAME token. The C-3 test asserts `===` between two consecutive renders.
 * This is what enables stable `useEffect` dependencies and avoids dependency
 * cascades that would otherwise re-fire on every render.
 *
 * USAGE (preferred — new code):
 *   import { useAuthedQuery } from "@/lib/api-client";
 *   import { qk } from "@/lib/query/keys";
 *   const { data } = useAuthedQuery({
 *     queryKey: qk.portfolios.list(),
 *     queryFn: (gw) => gw.getPortfolios(),
 *   });
 *
 * USAGE (escape hatch — when you need the gateway outside a query):
 *   const gw = useApiClient();
 *   const handleClick = () => gw.refreshToken();
 *
 * MIGRATION: Existing `createGateway(accessToken)` call sites continue to
 * work — the factory is unchanged. New code uses these hooks; old code is
 * converted incrementally.
 */

"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { createGateway, type Gateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";

// ── Context ──────────────────────────────────────────────────────────────────

/**
 * ApiClientContextValue — the value handed to consumers.
 *
 * `gateway` is the memoised gateway. `accessToken` is exposed for the rare
 * caller that needs to attach it to a non-gateway request (e.g. the EventSource
 * for SSE streaming, which receives the token in a query param).
 */
interface ApiClientContextValue {
  gateway: Gateway;
  accessToken: string | null;
}

// WHY null default (not a stub): we want `useApiClient()` to throw a clear
// error if it is used outside the provider, NOT to silently hand back a
// gateway with `accessToken=null` that would 401 every request. The throw
// catches the misuse at development time.
const ApiClientContext = createContext<ApiClientContextValue | null>(null);

// ── Provider ─────────────────────────────────────────────────────────────────

interface ApiClientProviderProps {
  children: ReactNode;
}

/**
 * ApiClientProvider — memoises createGateway(accessToken) into a stable
 * reference shared by every child component.
 *
 * MOUNT POINT: app/(app)/layout.tsx, INSIDE `AuthProvider` (so we can read
 * `accessToken`) and INSIDE `QueryClientProvider` (so `useAuthedQuery` works
 * for any consumer).
 *
 * WHY a provider (not a module-level memo): tokens differ per user, and
 * Next.js App Router renders multiple users on the same Node process for
 * SSR. A module-level cache would leak gateways across users. Provider state
 * is per-render-tree, so each request gets its own scope.
 */
export function ApiClientProvider({ children }: ApiClientProviderProps) {
  const { accessToken } = useAuth();

  // WHY useMemo with [accessToken]: same token → same gateway reference.
  // When the token rotates after silent refresh, accessToken changes, the
  // memo recomputes, and queries pinned to the old reference re-fire with
  // the fresh token (TanStack Query's queryFn closes over `gw` which now
  // points to the new gateway).
  const value = useMemo<ApiClientContextValue>(
    () => ({
      gateway: createGateway(accessToken),
      accessToken: accessToken ?? null,
    }),
    [accessToken],
  );

  return (
    <ApiClientContext.Provider value={value}>
      {children}
    </ApiClientContext.Provider>
  );
}

// ── Hooks ────────────────────────────────────────────────────────────────────

/**
 * useApiClient — returns the memoised gateway for the current access token.
 *
 * INVARIANT: Two consecutive renders with the same token return the SAME
 * gateway reference (by object identity). Verified by C-3 unit test.
 *
 * Throws if called outside `<ApiClientProvider>`.
 */
export function useApiClient(): Gateway {
  const ctx = useContext(ApiClientContext);
  if (!ctx) {
    throw new Error(
      "useApiClient must be used inside <ApiClientProvider>. Mount the " +
        "provider in app/(app)/layout.tsx, inside AuthProvider and " +
        "QueryClientProvider. PLAN-0059-C C-3.",
    );
  }
  return ctx.gateway;
}

/**
 * useAccessToken — returns the current access token (or null if signed out).
 *
 * EXPOSED because some surfaces (SSE, WebSocket subprotocols) cannot use the
 * gateway and need the raw token. Most code should NOT use this — prefer
 * `useApiClient()` so the gateway hides token plumbing.
 */
export function useAccessToken(): string | null {
  const ctx = useContext(ApiClientContext);
  if (!ctx) {
    throw new Error(
      "useAccessToken must be used inside <ApiClientProvider>. PLAN-0059-C C-3.",
    );
  }
  return ctx.accessToken;
}

/**
 * useAuthedQuery — useQuery wrapper that injects the gateway and gates on auth.
 *
 * BEHAVIOUR:
 *  - The `queryFn` receives the memoised gateway as its single argument.
 *  - The query is auto-disabled while accessToken is null (signed-out state).
 *    Callers can still pass `enabled: false` themselves; both gates AND.
 *  - All other useQuery options (staleTime, refetchInterval, ...) pass through.
 *
 * WHY auto-disable: nearly every previous call site wrote
 * `enabled: !!accessToken && isAuthenticated` by hand. Forgetting it caused
 * a stampede of 401s during the brief unauthenticated window on logout / token
 * expiry. Auto-gating eliminates that whole class of bug.
 *
 * TYPE PARAMETER MAPPING (mirrors useQuery):
 *   TQueryFnData — the raw shape the queryFn returns
 *   TError       — error type
 *   TData        — the shape exposed by `data` (after select())
 *   TQueryKey    — the literal queryKey tuple type
 */
export function useAuthedQuery<
  TQueryFnData = unknown,
  TError = Error,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey,
>(
  options: Omit<
    UseQueryOptions<TQueryFnData, TError, TData, TQueryKey>,
    "queryFn"
  > & {
    queryFn: (gw: Gateway) => Promise<TQueryFnData>;
  },
): UseQueryResult<TData, TError> {
  const ctx = useContext(ApiClientContext);
  if (!ctx) {
    throw new Error(
      "useAuthedQuery must be used inside <ApiClientProvider>. PLAN-0059-C C-3.",
    );
  }
  const { gateway, accessToken } = ctx;
  const { queryFn, enabled, ...rest } = options;

  // WHY `enabled !== false &&`: respects an explicit `enabled: false` from the
  // caller (e.g. "wait for the user to type 3+ chars"). When the caller passes
  // `enabled: true` or omits it, we additionally require an access token.
  const finalEnabled = enabled !== false && Boolean(accessToken);

  return useQuery<TQueryFnData, TError, TData, TQueryKey>({
    ...rest,
    enabled: finalEnabled,
    queryFn: () => queryFn(gateway),
  });
}
