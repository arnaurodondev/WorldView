/**
 * features/dashboard/hooks/useBriefChatSeed.ts — "Discuss in Chat" action hook
 * (PLAN-0066 Wave F T-W10-F-02).
 *
 * WHY THIS EXISTS: The MorningBriefCard "Discuss in Chat" button needs to:
 *   1. POST to /api/v1/briefings/chat/discuss to create a new thread seeded
 *      with the morning brief's citations.
 *   2. Navigate to /chat?thread={thread_id} on success.
 *   3. Show a loading state during the POST.
 *   4. Show an error message if the POST fails (e.g. no brief available yet).
 *
 * Extracting this into a custom hook keeps the component declarative (just calls
 * `discuss()`) and keeps the async state (loading, error) co-located with the
 * logic rather than scattered across the component.
 *
 * WHY useRouter from next/navigation (not window.location): Next.js 15 App Router
 * requires router.push() for client-side navigation — it updates the React tree
 * correctly (layout persistence, scroll position, prefetching). window.location
 * would force a full page reload, destroying workspace state.
 *
 * WHO USES IT: MorningBriefCard.
 * DATA SOURCE: POST /api/v1/briefings/chat/discuss (S8 via S9 proxy)
 */

"use client";
// WHY "use client": uses useState + useCallback which are client-only React hooks.

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { postDiscussBrief } from "@/lib/api/briefing";
import { apiFetch } from "@/lib/api/_client";

// ── User-visible "Discuss" label ─────────────────────────────────────────────
//
// Density bundle 2026-05-09: when "Discuss" creates a new chat thread, S8
// seeds the thread with the FULL morning brief markdown as the first user
// message — useful as LLM context but visually overwhelming when the user
// lands on /chat and sees a wall of text labeled as their own message.
//
// We rename the thread title client-side immediately after creation so the
// thread sidebar and the chat header show the friendly label "Generate Daily
// Brief" rather than the auto-generated title (which is often the first
// 60 chars of the brief markdown — itself awkward).
//
// WHY only the title (not the seeded message): rewriting the seed message
// would strip the LLM context that makes the thread useful in the first
// place. The title is purely a display label so it's safe to override.
const DISCUSS_THREAD_TITLE = "Generate Daily Brief";

// ── Return type ───────────────────────────────────────────────────────────────

export interface UseBriefChatSeedResult {
  /**
   * discuss — trigger the chat-seed flow.
   * Calls the S8 endpoint, then navigates to /chat?thread={id}.
   * Sets loading=true for the duration; sets error on failure.
   */
  discuss: () => Promise<void>;
  /** loading — true while the POST is in-flight */
  loading: boolean;
  /** error — human-readable message if the POST failed; null otherwise */
  error: string | null;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useBriefChatSeed(token: string | undefined): UseBriefChatSeedResult {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // WHY useCallback: stable reference so MorningBriefCard can pass `discuss` to
  // a child button without triggering re-renders on every state update.
  const discuss = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { thread_id } = await postDiscussBrief(token);

      // Density bundle 2026-05-09 — relabel the new thread.
      //
      // S8 auto-titles new chat threads from the first user message (which is
      // the seeded brief markdown). That produces titles like "Morning Brief
      // — 2026-05-09: 1) Macro overnight..." which leaks internal prompt
      // structure into the user's sidebar.
      //
      // We PATCH the title to "Generate Daily Brief" right after creation.
      // The internal LLM context (seeded message body) is preserved — only
      // the display label changes.
      //
      // WHY best-effort (.catch swallows): if the rename fails for any reason
      // (network blip, 404 on a freshly-created thread that hasn't replicated
      // yet) the user still ends up on the chat page with a working thread —
      // the wrong title is far less bad than blocking navigation. We also
      // fire-and-forget so the navigation isn't delayed by the PATCH RTT.
      void apiFetch(`/v1/threads/${thread_id}`, {
        method: "PATCH",
        token,
        body: { title: DISCUSS_THREAD_TITLE },
      }).catch(() => {
        // Intentional swallow — see WHY best-effort above.
      });

      // WHY push (not replace): the user should be able to navigate back to the
      // dashboard from the chat page using the browser back button. push() adds
      // the chat URL to the history stack; replace() would destroy the dashboard.
      router.push(`/chat?thread=${thread_id}`);
    } catch {
      // WHY generic message: the raw error from postDiscussBrief includes HTTP
      // status and path details not useful to the trader. A single friendly message
      // is clearer than "GatewayError: 422 at /v1/briefings/chat/discuss".
      setError("Could not open chat — please try again");
    } finally {
      setLoading(false);
    }
  }, [router, token]);

  return { discuss, loading, error };
}
