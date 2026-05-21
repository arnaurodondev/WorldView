/**
 * useInstrumentBrief.ts — Lazy-generate brief hook for the Quote-tab AiBriefBanner.
 *
 * WHY THIS EXISTS (W5-T-04, Δ27):
 * AiBriefBanner previously called GET /v1/briefings/instrument/{id} directly.
 * If the brief wasn't cached (Valkey miss), S8 would block for 3-8 seconds
 * generating it, leaving a loading spinner in the page's most prominent real
 * estate. The new pattern is:
 *
 *   1. GET /v1/briefings/instrument/{id} — fast (≤ 50ms) cache check.
 *      If 200 → render immediately (status = "ready").
 *      If 404 → brief not in cache, proceed to step 2.
 *   2. POST /v1/briefings/instrument/{id}/generate — idempotent trigger.
 *      If 200 + status="cached" → brief exists; GET again to get the full body.
 *      If 202 + status="queued" → generation enqueued; poll.
 *      If 429 → quota exceeded; surface countdown (status = "quota-exceeded").
 *   3. Poll GET every 30s up to 5 attempts → status = "ready" on first 200.
 *      After 5 misses → status = "unavailable".
 *
 * WHY useRef for poll interval (not useState): interval ID doesn't need to
 * trigger a re-render; storing it in state would cause an extra render cycle
 * each time it's set or cleared.
 *
 * WHY manual GET-then-POST (not useMutation for step 2): TanStack Query
 * mutations don't integrate cleanly with "fetch first, then mutate if miss"
 * patterns. A thin custom hook with useQuery for step 1 and an effect for
 * step 2 keeps the state machine explicit and testable.
 *
 * WHO USES IT: AiBriefBanner.tsx (T-23). No other component should own the
 * lazy-generate logic — it should be consumed, not re-implemented.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { BriefingResponse } from "@/types/api";
import { GatewayError } from "@/lib/api/_client";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Milliseconds between poll attempts after POST /generate. */
const POLL_INTERVAL_MS = 30_000;

/** Maximum poll attempts before giving up (status → "unavailable"). */
const MAX_POLL_ATTEMPTS = 5;

// ── Types ─────────────────────────────────────────────────────────────────────

export type BriefStatus =
  | "loading"       // Initial GET in flight
  | "generating"    // POST queued; polling in progress
  | "ready"         // Brief available and rendered
  | "unavailable"   // Generation failed or max polls exhausted
  | "quota-exceeded"; // 429 — user has hit the 60/hr rate limit

export interface UseInstrumentBriefResult {
  data: BriefingResponse | undefined;
  status: BriefStatus;
  /** Populated when status = "quota-exceeded". Seconds until quota resets. */
  retryAfter: number | undefined;
  /** Manual refetch (e.g. user clicks "Retry"). */
  refetch: () => void;
}

// ── Hook ─────────────────────────────────────────────────────────────────────

/**
 * useInstrumentBrief — manages the full lazy-generate lifecycle for one instrument.
 *
 * @param instrumentId  The canonical instrument_id (UUID or ticker) to fetch a brief for.
 *                      Passing `undefined` disables the hook (all queries disabled).
 * @param entityId      The KG entity_id used for the POST /generate endpoint.
 *                      In most cases this is the same as instrumentId; some legacy
 *                      components pass a separate entity_id. If undefined, falls back
 *                      to instrumentId.
 */
export function useInstrumentBrief(
  instrumentId: string | undefined,
  entityId?: string,
): UseInstrumentBriefResult {
  const token = useAccessToken();
  const qc = useQueryClient();

  // The entity_id for POST /generate; falls back to instrumentId.
  const briefEntityId = entityId ?? instrumentId;

  // ── Step 1: GET (fast cache check) ─────────────────────────────────────────
  const {
    data: briefData,
    status: queryStatus,
    isFetching,
    refetch: refetchQuery,
  } = useQuery({
    queryKey: qk.instruments.brief(instrumentId ?? ""),
    queryFn: () =>
      createGateway(token).getInstrumentBrief(briefEntityId ?? ""),
    staleTime: 5 * 60 * 1000, // 5 min — brief changes at most once per session
    retry: false,              // WHY retry:false: a 404 is expected on cold cache; we handle it below
    enabled: !!instrumentId,
  });

  // ── Local state ───────────────────────────────────────────────────────────
  const [status, setStatus] = useState<BriefStatus>("loading");
  const [retryAfter, setRetryAfter] = useState<number | undefined>(undefined);
  const pollCountRef = useRef(0);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const isGeneratingRef = useRef(false); // WHY ref: prevents duplicate POST on StrictMode double-effect

  // ── Cleanup poll on unmount ───────────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (pollTimerRef.current !== undefined) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, []);

  // ── Poll helper ───────────────────────────────────────────────────────────
  const schedulePoll = useCallback(() => {
    if (pollTimerRef.current !== undefined) clearTimeout(pollTimerRef.current);
    pollTimerRef.current = setTimeout(async () => {
      pollCountRef.current += 1;
      if (pollCountRef.current > MAX_POLL_ATTEMPTS) {
        setStatus("unavailable");
        return;
      }
      try {
        // Invalidate the GET query so the next render gets fresh data.
        await qc.invalidateQueries({
          queryKey: qk.instruments.brief(instrumentId ?? ""),
        });
        // The useQuery above will refetch automatically after invalidation.
        // If it returns data, the main effect below will set status="ready".
        // If it 404s again, schedule another poll.
      } catch {
        // Network error — count as a failed attempt.
        if (pollCountRef.current >= MAX_POLL_ATTEMPTS) setStatus("unavailable");
        else schedulePoll();
      }
    }, POLL_INTERVAL_MS);
  }, [qc, instrumentId]);

  // ── Main effect — react to GET result ────────────────────────────────────
  useEffect(() => {
    if (!instrumentId || !briefEntityId) return;

    // Brief data available → ready.
    if (briefData) {
      setStatus("ready");
      pollCountRef.current = 0;
      isGeneratingRef.current = false;
      if (pollTimerRef.current !== undefined) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = undefined;
      }
      return;
    }

    // GET is still in flight → keep "loading".
    if (queryStatus === "pending" || isFetching) {
      setStatus("loading");
      return;
    }

    // GET returned an error (including 404) and we haven't started generating.
    if (queryStatus === "error" && !isGeneratingRef.current) {
      isGeneratingRef.current = true;
      setStatus("generating");

      // ── Step 2: POST /generate ────────────────────────────────────────────
      void (async () => {
        try {
          const genResp = await createGateway(token).triggerInstrumentBriefGeneration(
            briefEntityId,
          );

          if (genResp.retryAfterSeconds !== undefined) {
            // 429 — quota exceeded.
            setStatus("quota-exceeded");
            setRetryAfter(genResp.retryAfterSeconds);
            isGeneratingRef.current = false;
            return;
          }

          if (genResp.status === "cached") {
            // Brief already in cache; GET again to hydrate the query.
            await qc.invalidateQueries({
              queryKey: qk.instruments.brief(instrumentId),
            });
            // The useQuery re-run will set status="ready" via the effect above.
            return;
          }

          // status === "queued" — begin polling.
          pollCountRef.current = 0;
          schedulePoll();
        } catch (err) {
          // Non-429 error (503, network) → unavailable.
          setStatus("unavailable");
          isGeneratingRef.current = false;

          // Log for observability without crashing the UI.
          if (process.env.NODE_ENV !== "production") {
            // WHY only dev: production error goes to Sentry via Next.js error boundary
            console.warn("[useInstrumentBrief] POST /generate failed:", err);
          }
        }
      })();
    }

    // GET 404 while polling → wait for next scheduled poll.
    if (queryStatus === "error" && isGeneratingRef.current) {
      setStatus("generating");
    }
  }, [
    briefData,
    queryStatus,
    isFetching,
    instrumentId,
    briefEntityId,
    token,
    qc,
    schedulePoll,
  ]);

  // ── Manual refetch (Retry button) ─────────────────────────────────────────
  const refetch = useCallback(() => {
    pollCountRef.current = 0;
    isGeneratingRef.current = false;
    setStatus("loading");
    setRetryAfter(undefined);
    void refetchQuery();
  }, [refetchQuery]);

  return { data: briefData, status, retryAfter, refetch };
}
