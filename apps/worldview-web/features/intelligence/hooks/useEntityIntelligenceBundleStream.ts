/**
 * features/intelligence/hooks/useEntityIntelligenceBundleStream.ts
 *   — PLAN-0099 W4 follow-up R2 (SSE streaming variant)
 *
 * WHY THIS HOOK EXISTS:
 * The non-streaming Intelligence-tab bundle hook
 * (`useEntityIntelligenceBundle`) fans out 5 legs server-side via
 * `asyncio.gather` and blocks on the slowest one before the frontend can
 * paint ANY widget. Above-the-fold panels (entity detail, AI brief,
 * intelligence summary) resolve in well under 200 ms but pay the
 * worst-case latency of the slowest leg — typically `graph_d2`'s AGE
 * depth-2 traversal, which can take seconds on a cold KG container.
 *
 * The streaming variant calls the SSE endpoint
 * `GET /v1/entities/{id}/intelligence-bundle/stream`, which fans out the
 * same 5 legs via `asyncio.wait(FIRST_COMPLETED)` and YIELDS one SSE
 * `event: leg` per leg as it completes. This hook reads each event and
 * hydrates the corresponding per-widget TanStack cache via `setQueryData`
 * — mirroring the EXACT keys the widgets read, same as the non-streaming
 * hook. The page feels "fully painted" the moment the fastest legs land
 * (sub-second), while the slow leg continues to stream in.
 *
 * WHY fetch + ReadableStream (NOT EventSource):
 * Matches the existing chat-stream consumer pattern at
 * `features/chat/hooks/useChatStream.ts`. The reasons listed there apply:
 *   - EventSource is GET-only, but we need to inject an Authorization
 *     header (Bearer token), which EventSource cannot do. fetch() can.
 *   - The wire format is already shared via `lib/sse-parser.ts`, so we
 *     reuse the canonical line-level parser instead of forking it.
 *
 * USAGE (NOT YET WIRED — rollout is gated on a feature flag / prop by
 * IntelligenceTab; see task spec R2 § CONSTRAINTS):
 *
 *   const { legsLoaded, allDone, error } =
 *     useEntityIntelligenceBundleStream(entityId);
 *   // The hook hydrates the per-widget caches as legs arrive; the
 *   // child queries see the data as already-fetched and skip their
 *   // own initial fetches. Callers can use `legsLoaded` to render
 *   // per-leg skeletons or `allDone` to gate post-load effects.
 *
 * MIRRORS the non-streaming hook's setQueryData targets so a future
 * caller can choose either variant via feature flag without touching the
 * downstream widgets.
 */

"use client";
// WHY "use client": useState + useEffect + useQueryClient + fetch streaming
// all require browser runtime. Only Client Components may import this hook.

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/hooks/useAuth";
import { parseSSELine } from "@/lib/sse-parser";
import { qk } from "@/lib/query/keys";

// ── Wire-format types ─────────────────────────────────────────────────────────

/**
 * The 5 legs emitted by the backend. Keeping this as a string-literal union
 * means a typo in the hook ("graph2" instead of "graph_d2") is a compile-time
 * error rather than a silent runtime miss.
 */
export type StreamLegName =
  | "detail"
  | "brief"
  | "graph_d2"
  | "paths"
  | "intelligence_summary";

/**
 * Shape of each `event: leg` payload (see backend `_format_sse`).
 *
 * WHY `value: unknown`: every leg has a different payload shape (entity
 * detail vs paths list vs graph nodes/edges). Typing each variant here
 * would require importing 5 unrelated types from `lib/api/*`. We treat
 * the value as opaque JSON and let the consuming widget cast as needed —
 * same approach the non-streaming bundle response uses.
 */
interface LegEvent {
  leg: StreamLegName;
  value: unknown | null;
  error?: string;
}

// ── Hook contract ─────────────────────────────────────────────────────────────

export interface UseEntityIntelligenceBundleStreamResult {
  /** Names of legs we have received so far. Mutated incrementally. */
  legsLoaded: Set<StreamLegName>;
  /** True once the backend emits `event: done` (or the stream errors out). */
  allDone: boolean;
  /** Non-null when the stream itself failed (network / non-2xx). Per-leg
   *  failures arrive as `{value: null, error: ...}` events and do NOT
   *  populate this field — they hydrate the cache with null instead. */
  error: Error | null;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useEntityIntelligenceBundleStream — SSE consumer for the streaming
 * variant of the Intelligence-tab bundle.
 *
 * @param entityId The KG entity_id for the instrument page's primary entity.
 *                 The hook stays idle until both this and an access token are
 *                 present. Passing an empty string is treated as "not ready"
 *                 (same gate as useEntityIntelligenceBundle).
 */
export function useEntityIntelligenceBundleStream(
  entityId: string,
): UseEntityIntelligenceBundleStreamResult {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  // WHY useState + Set: we expose `legsLoaded` as a reactive value so a
  // caller can render `<Skeleton/>` until a specific leg has arrived. A
  // plain ref would mutate silently and never re-render the caller. We
  // create a NEW Set on each update so React's referential equality check
  // notices the change.
  const [legsLoaded, setLegsLoaded] = useState<Set<StreamLegName>>(() => new Set());
  const [allDone, setAllDone] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // WHY useRef for the abort controller: an in-flight stream must be
  // cancelled on unmount OR when the inputs change (different entityId).
  // The controller lives across renders so the cleanup function can
  // access the SAME instance that the effect kicked off.
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // ── Idle guards ────────────────────────────────────────────────────
    // Same enabled-gate semantics as the non-streaming hook: skip when
    // either input is missing so we never fire a malformed request.
    if (!accessToken || !entityId) return;

    // Reset state for a new (entityId, token) pair so a re-entrant
    // navigation does not show stale legs from a previous instrument.
    setLegsLoaded(new Set());
    setAllDone(false);
    setError(null);

    const controller = new AbortController();
    abortRef.current = controller;

    /**
     * runStream — drive the SSE read loop until `done` or abort.
     *
     * The loop mirrors `useChatStream` so the SSE wire-format contract
     * lives in exactly two places (chat + this hook), both using
     * `parseSSELine` from `lib/sse-parser.ts`.
     */
    const runStream = async () => {
      try {
        // WHY /api prefix: matches `lib/api/_client.ts:BASE = "/api"`.
        // next.config.ts rewrites /api/* → S9 in dev and prod.
        const response = await fetch(
          `/api/v1/entities/${encodeURIComponent(entityId)}/intelligence-bundle/stream`,
          {
            method: "GET",
            headers: {
              Accept: "text/event-stream",
              Authorization: `Bearer ${accessToken}`,
            },
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          throw new Error(
            `Bundle stream request failed: ${response.status} ${response.statusText}`,
          );
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error(
            "Response body is null — server did not return a stream",
          );
        }

        const decoder = new TextDecoder();
        let buffer = "";
        // SSE events carry an optional `event:` field before their `data:`
        // line. We track the pending event name so each data payload is
        // routed to the right handler (same as useChatStream).
        let pendingEventName = "";

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            // Keep the trailing partial line for the next pump — the
            // backend writes complete blocks but TCP may split mid-line.
            buffer = lines.pop() ?? "";

            for (const line of lines) {
              const parsed = parseSSELine(line);
              if (!parsed) continue;

              // `event:` line — remember the name for the next data line.
              if (parsed.type !== "message") {
                pendingEventName = parsed.type;
                continue;
              }

              // `data:` line — consume the pending event name.
              const eventName = pendingEventName;
              pendingEventName = "";
              const payload = parsed.data;

              if (eventName === "done") {
                // Backend signals clean end-of-stream. The `partial`
                // boolean inside the data field is informational only;
                // we expose `allDone` regardless because per-leg
                // hydration has already happened by this point.
                setAllDone(true);
                return;
              }

              if (eventName !== "leg") continue;

              let leg: LegEvent;
              try {
                leg = JSON.parse(payload) as LegEvent;
              } catch {
                // Malformed payload — skip the event rather than tearing
                // down the whole stream. The other legs may still arrive.
                continue;
              }

              hydrateLeg(leg);

              // Track that this leg has arrived (even if value is null).
              // Callers may want to render "leg failed" skeletons that
              // depend on knowing the leg has been ATTEMPTED — they can
              // distinguish that case by checking the cache value
              // (null vs the absence of the leg name in `legsLoaded`).
              setLegsLoaded((prev) => {
                if (prev.has(leg.leg)) return prev;
                const next = new Set(prev);
                next.add(leg.leg);
                return next;
              });
            }
          }
        } finally {
          // Release the reader lock on all exit paths — same pattern as
          // useChatStream. Without this, an abort mid-stream leaves the
          // underlying body locked and future reads throw.
          try {
            await reader.cancel();
          } catch {
            // ignore — already closed.
          }
        }

        // EOF without an explicit `done` event — still mark as done so
        // consumers can release any "loading" UI.
        setAllDone(true);
      } catch (err) {
        // WHY swallow AbortError: unmounting / changing entityId
        // intentionally aborts the in-flight stream. That is not a user-
        // visible error condition.
        if ((err as Error).name === "AbortError") return;
        setError(err as Error);
        // Mark allDone so the caller's loading gate releases even on
        // failure — they can branch on `error` to render a fallback.
        setAllDone(true);
      }
    };

    /**
     * hydrateLeg — write the leg's value into the per-widget TanStack
     * cache slot under the EXACT key the widget reads.
     *
     * CRITICAL: if the key drifts even by one element the widget will
     * treat the cache as empty and fire its own initial fetch, defeating
     * the entire purpose of the bundle. The keys here MUST mirror
     * `useEntityIntelligenceBundle.ts`. When that file changes, this
     * one MUST follow.
     */
    const hydrateLeg = (leg: LegEvent) => {
      // WHY skip when value is null: TanStack treats null/undefined as a
      // valid resolved value. Writing null would mark the cache "loaded"
      // and prevent the widget from issuing its own fetch as a fallback.
      if (leg.value === null) return;

      switch (leg.leg) {
        case "detail":
          // ContextPanel's entityDetailQuery uses ["entity-detail", id].
          queryClient.setQueryData(["entity-detail", entityId], leg.value);
          break;
        case "brief":
          // GraphColumn's brief uses qk.instruments.brief(entityId).
          queryClient.setQueryData(
            qk.instruments.brief(entityId),
            leg.value,
          );
          break;
        case "graph_d2":
          // GraphColumn's graph query uses
          // qk.instruments.entityGraph(entityId, 2). Hydrating under
          // that exact key prevents the depth=2 fetch on mount.
          queryClient.setQueryData(
            qk.instruments.entityGraph(entityId, 2),
            leg.value,
          );
          break;
        case "paths":
          // PathInsightsBlock uses ["entity-paths", entityId, {}] with
          // empty default filters; we seed that exact slot.
          queryClient.setQueryData(
            ["entity-paths", entityId, {}],
            leg.value,
          );
          break;
        case "intelligence_summary":
          // useEntityIntelligence keys on ["entity-intelligence", id].
          queryClient.setQueryData(
            ["entity-intelligence", entityId],
            leg.value,
          );
          break;
        default:
          // Unknown leg name — backend may have added one we don't know
          // about. Ignore silently so the rest of the stream still
          // hydrates the widgets we DO know.
          break;
      }
    };

    // Fire-and-forget the async loop. The hook surface stays sync —
    // consumers read the reactive state we update from within runStream.
    void runStream();

    // ── Cleanup: abort on unmount / inputs-change ─────────────────────
    return () => {
      controller.abort();
      abortRef.current = null;
    };
    // WHY queryClient in deps: in tests / SSR boundaries the client
    // reference can change across renders. Including it satisfies the
    // exhaustive-deps lint and matches the pattern in
    // useEntityIntelligenceBundle.
  }, [accessToken, entityId, queryClient]);

  return { legsLoaded, allDone, error };
}
