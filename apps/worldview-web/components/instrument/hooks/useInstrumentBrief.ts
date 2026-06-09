/**
 * components/instrument/hooks/useInstrumentBrief.ts — lazy-generate AI brief (T-05)
 *
 * WHY THIS EXISTS: PLAN-0089 W3 Δ19 specifies the AIBriefPanel uses a
 * GET→404→POST /generate→poll GET pattern. This encapsulates the stateful
 * multi-step flow so AIBriefPanel stays purely presentational. The complexity
 * of the lazy-generate lifecycle belongs in a hook, not a component.
 *
 * WHY NOT useQuery alone: TanStack Query re-fetches on 404 would be an
 * infinite loop. We need custom logic: 404 → fire a mutation → then poll.
 * The hook uses a combination of useQuery + useEffect for the generate trigger
 * + retry logic.
 *
 * THE FLOW (Δ19):
 *   1. GET /v1/briefings/instrument/{entityId}
 *   2a. 200 → return brief immediately.
 *   2b. 404 → POST /v1/briefings/instrument/{entityId}/generate (trigger)
 *   3. Poll GET every 30s up to 5 attempts.
 *   4. After 5 failed polls → error state "Brief generation timed out."
 *
 * WHY 30s interval / 5 max attempts: brief generation via DeepInfra typically
 * takes 10-25s for instrument briefs. 5 × 30s = 2.5 min maximum wait before
 * giving the user an error message. The backend is idempotent (rate-limited to
 * 1 generation per 60 min) so duplicate POSTs from stale renders are safe.
 *
 * WHO USES IT: AIBriefPanel.tsx (T-22).
 * DATA SOURCE: S9 GET + POST /v1/briefings/instrument/{entityId} → S8 rag-chat.
 */

"use client";
// WHY "use client": useState, useEffect, and useQuery all require the browser
// runtime. The hook manages polling timers and asynchronous generation triggers.

import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { GatewayError } from "@/lib/api/_client";
import type { BriefingResponse } from "@/types/api";

// How long to wait between poll attempts after triggering generation.
const POLL_INTERVAL_MS = 30_000;
// Maximum number of poll attempts before giving up.
const MAX_POLL_ATTEMPTS = 5;

export type BriefStatus =
  | "idle"
  | "loading"        // initial GET in-flight
  | "triggering"     // POSTing /generate
  | "polling"        // waiting for generation to complete
  | "ready"          // brief available
  | "error";         // generation failed or timed out

export interface UseInstrumentBriefResult {
  brief: BriefingResponse | null;
  status: BriefStatus;
  // Human-readable error for the UI error state.
  errorMessage: string | null;
  // Call to manually retry (e.g. after a "Retry" button click).
  retry: () => void;
}

export function useInstrumentBrief(entityId: string): UseInstrumentBriefResult {
  const token = useAccessToken();
  const queryClient = useQueryClient();

  // WHY local state for status (not derived from useQuery.status): the
  // generate-and-poll flow has states (triggering, polling, timedOut) that
  // TanStack Query's status enum doesn't model. Local state lets us drive the
  // UI through each phase explicitly.
  const [status, setStatus] = useState<BriefStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Track poll attempts with a ref (not state) to avoid re-triggering useEffect.
  const pollAttemptsRef = useRef(0);
  // Track the polling timer so we can clear it on unmount.
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Track whether generation has been triggered this session.
  const triggeredRef = useRef(false);

  // ── Step 1: Initial GET ───────────────────────────────────────────────────

  const {
    data: brief,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<BriefingResponse, Error>({
    queryKey: qk.instruments.brief(entityId),
    queryFn: async () => {
      const gw = createGateway(token);
      // WHY getInstrumentBrief (dashboard API): the brief endpoint lives in
      // createDashboardApi, not createInstrumentsApi. This is a historical
      // grouping decision (briefings belong to the AI/analysis domain).
      return gw.getInstrumentBrief(entityId);
    },
    // WHY retry: false — we handle 404 manually (trigger generate + poll).
    // TanStack's default 3-retry behaviour would waste 3× the time on 404s.
    retry: false,
    // WHY enabled: false — we control refetch timing manually via refetch().
    // Automatic background refetch would fire at mount, which is correct
    // for the initial load, so actually we want enabled=true for the initial
    // load. We disable after triggering generation to control the polling.
    enabled: !!entityId && status !== "polling",
    staleTime: 60 * 60 * 1000, // 1h — briefs are stable once generated
  });

  // ── Step 2: Handle initial load result ───────────────────────────────────

  useEffect(() => {
    if (!entityId) return;

    if (isLoading) {
      setStatus("loading");
      return;
    }

    if (brief) {
      // Brief exists — show it immediately.
      setStatus("ready");
      return;
    }

    if (isError && !triggeredRef.current) {
      // WHY check GatewayError.status 404: only trigger generation on 404
      // (no brief exists yet). Any other error (500, network) should surface
      // directly as an error state rather than triggering a generation.
      const is404 = error instanceof GatewayError && error.status === 404;
      if (is404) {
        // Trigger generation on first 404.
        void triggerGeneration();
      } else {
        setStatus("error");
        setErrorMessage("Failed to load instrument brief.");
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, brief, isError, error, entityId]);

  // ── Step 3: Trigger generation ────────────────────────────────────────────

  const triggerGeneration = useCallback(async () => {
    if (triggeredRef.current) return; // idempotent — don't double-trigger
    triggeredRef.current = true;
    pollAttemptsRef.current = 0;

    setStatus("triggering");
    try {
      const gw = createGateway(token);
      await gw.triggerInstrumentBriefingGeneration(entityId);
      // WHY immediately start polling (not wait for POLL_INTERVAL_MS): the
      // backend queues generation and may complete in < 30s. A fast first
      // poll catches this case. Subsequent polls are spaced at POLL_INTERVAL_MS.
      setStatus("polling");
      schedulePoll();
    } catch {
      setStatus("error");
      setErrorMessage("Failed to start brief generation.");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId, token]);

  // ── Step 4: Poll until brief appears ─────────────────────────────────────

  const schedulePoll = useCallback(() => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);

    pollTimerRef.current = setTimeout(async () => {
      pollAttemptsRef.current += 1;

      if (pollAttemptsRef.current > MAX_POLL_ATTEMPTS) {
        setStatus("error");
        setErrorMessage("Brief generation is taking longer than expected. Try again later.");
        return;
      }

      try {
        // WHY re-enable the query then refetch: setting enabled: true on the
        // existing query would require a state update + re-render cycle.
        // A direct refetch is more immediate and avoids the state-update lag.
        const result = await queryClient.fetchQuery<BriefingResponse>({
          queryKey: qk.instruments.brief(entityId),
          queryFn: () => createGateway(token).getInstrumentBrief(entityId),
          retry: false,
          staleTime: 0, // force fresh fetch during polling
        });

        if (result) {
          setStatus("ready");
          // WHY invalidate after polling success: the queryKey is now populated
          // with fresh data. Invalidating ensures any sibling components that
          // also read this key see the new brief immediately.
          await queryClient.invalidateQueries({
            queryKey: qk.instruments.brief(entityId),
          });
        }
      } catch (pollErr) {
        const is404 = pollErr instanceof GatewayError && pollErr.status === 404;
        if (is404 && pollAttemptsRef.current <= MAX_POLL_ATTEMPTS) {
          // Still not generated — schedule next poll.
          schedulePoll();
        } else {
          setStatus("error");
          setErrorMessage("Brief generation timed out. Please try again.");
        }
      }
    }, POLL_INTERVAL_MS);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId, token, queryClient]);

  // ── Cleanup ───────────────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      // WHY clear on unmount: if the user navigates away during polling, we
      // must cancel the timer to prevent a setState on an unmounted component
      // (a React warning and potential memory leak).
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, []);

  // ── Retry ─────────────────────────────────────────────────────────────────

  const retry = useCallback(() => {
    triggeredRef.current = false;
    pollAttemptsRef.current = 0;
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    setErrorMessage(null);
    setStatus("idle");
    // WHY invalidate then refetch: stale cached error responses need to be
    // cleared before re-fetching, otherwise TanStack serves the cached 404.
    void queryClient.invalidateQueries({ queryKey: qk.instruments.brief(entityId) });
    void refetch();
  }, [entityId, queryClient, refetch]);

  return {
    brief: brief ?? null,
    status,
    errorMessage,
    retry,
  };
}
