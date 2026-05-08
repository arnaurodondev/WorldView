/**
 * lib/api/briefing.ts — Brief-related API client functions (PLAN-0066 Wave F).
 *
 * WHY THIS EXISTS: Centralises all briefing API calls so they can be reused
 * across MorningBriefCard, BriefDiffBadge, BulletFeedback, and BriefRating
 * without duplicating fetch logic.
 *
 * WHO USES IT:
 * - features/dashboard/components/BriefDiffBadge.tsx (diff pill)
 * - features/dashboard/hooks/useBriefChatSeed.ts (discuss button)
 * - features/dashboard/components/BulletFeedback.tsx (thumbs feedback)
 * - features/dashboard/components/BriefRating.tsx (star rating)
 * - features/dashboard/components/BriefEntityPill.tsx (alert prefill)
 *
 * DATA SOURCE: S8 via S9 proxy at /api/v1/briefings/*
 * DESIGN REFERENCE: PLAN-0066 Wave F, PRD-0034 §3 FR-T1-1 extensions
 *
 * PATTERN: All functions use the apiFetch wrapper from _client.ts, which
 * injects the auth token, handles errors, and enforces the /api base prefix.
 * Token is passed as an argument so these are pure async functions (no
 * closure over auth state) — easier to test and reuse.
 */

import type {
  BriefDiffResponse,
  BriefAlertPrefillResponse,
} from "@/types/api";
import { apiFetch } from "./_client";

// ── Diff ──────────────────────────────────────────────────────────────────

/**
 * getBriefDiff — fetch the bullet diff between today's and yesterday's brief.
 *
 * WHY token param: apiFetch injects the Bearer token so S9/S8 can enforce auth.
 * The diff endpoint is protected by InternalJWTMiddleware (PRD-0025).
 *
 * WHY staleTime=5min in callers: diffs are cheap to recompute and change at most
 * once per day (when a new brief is generated). 5 minutes avoids hammering S8
 * while still reflecting a newly generated brief within a reasonable window.
 */
export function getBriefDiff(token: string | undefined): Promise<BriefDiffResponse> {
  return apiFetch<BriefDiffResponse>("/v1/briefings/morning/diff", { token });
}

// ── Chat seeding ──────────────────────────────────────────────────────────

/**
 * postDiscussBrief — create a new chat thread pre-seeded with the morning brief.
 *
 * WHY POST (not GET): creates a new thread row in the database (write operation).
 * Returns thread_id so the frontend can navigate to /chat?thread={id}.
 *
 * WHY brief_type="morning": the endpoint supports future brief types (entity briefs)
 * via this field. We always pass "morning" from the MorningBriefCard context.
 */
export function postDiscussBrief(
  token: string | undefined,
): Promise<{ thread_id: string; seeded_with_brief_id: string }> {
  return apiFetch<{ thread_id: string; seeded_with_brief_id: string }>(
    "/v1/briefings/chat/discuss",
    {
      method: "POST",
      token,
      body: { brief_type: "morning" },
    },
  );
}

// ── Bullet-level feedback ─────────────────────────────────────────────────

/**
 * postBulletFeedback — submit a thumbs-up/down reaction for a specific bullet.
 *
 * WHY section_idx + bullet_idx (not bullet ID): the backend identifies bullets by
 * their position in the sections array. BriefBullet objects don't have stable IDs
 * (they are regenerated each time the brief is generated).
 *
 * WHY optimistic update in the component (not here): the API call is best-effort —
 * the UI fills the icon immediately and silently eats failures. Optimistic state
 * belongs in the component, not the fetch layer.
 */
export function postBulletFeedback(
  token: string | undefined,
  briefId: string,
  sectionIdx: number,
  bulletIdx: number,
  reaction: "helpful" | "unhelpful",
): Promise<{ id: string; created_at: string }> {
  return apiFetch<{ id: string; created_at: string }>(
    "/v1/briefings/feedback/bullet",
    {
      method: "POST",
      token,
      body: {
        brief_id: briefId,
        section_idx: sectionIdx,
        bullet_idx: bulletIdx,
        reaction,
      },
    },
  );
}

// ── Brief-level rating ────────────────────────────────────────────────────

/**
 * postBriefRating — submit a 1-5 star rating for the whole brief.
 *
 * WHY reaction as string "1"-"5" (not number 1-5): the S8 Pydantic schema uses
 * Literal["1","2","3","4","5"] to accept string values — avoids integer/string
 * mismatch in JSON serialisation that previously caused 422 errors.
 */
export function postBriefRating(
  token: string | undefined,
  briefId: string,
  reaction: "1" | "2" | "3" | "4" | "5",
): Promise<{ id: string; created_at: string }> {
  return apiFetch<{ id: string; created_at: string }>(
    "/v1/briefings/feedback/brief",
    {
      method: "POST",
      token,
      body: { brief_id: briefId, reaction },
    },
  );
}

// ── Alert prefill ─────────────────────────────────────────────────────────

/**
 * postBriefAlertPrefill — fetch pre-filled alert context from a brief bullet.
 *
 * WHY a POST (not GET): the request body contains section_idx + bullet_idx
 * which identify the bullet — these are not natural URL path params.
 *
 * The response contains entity_id, entity_name, suggested_alert_type, and
 * context_snippet so the alert creation drawer can be pre-filled without the
 * user having to search for the entity separately.
 */
export function postBriefAlertPrefill(
  token: string | undefined,
  briefId: string,
  sectionIdx: number,
  bulletIdx: number,
  entityId: string | null,
): Promise<BriefAlertPrefillResponse> {
  return apiFetch<BriefAlertPrefillResponse>(
    `/v1/briefings/${briefId}/create-alert`,
    {
      method: "POST",
      token,
      body: {
        section_idx: sectionIdx,
        bullet_idx: bulletIdx,
        entity_id: entityId,
      },
    },
  );
}
