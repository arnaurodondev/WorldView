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
