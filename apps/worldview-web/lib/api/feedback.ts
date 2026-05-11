/**
 * lib/api/feedback.ts — Feedback subsystem (PLAN-0053 Wave G).
 *
 * SCOPE: bug/feature/UX/general feedback submissions, NPS, public feature
 * requests + voting, micro-survey reactions, beta-program enrollment.
 *
 * WHY a single section: all 9 feedback endpoints live under `/v1/feedback/*`
 * on S9 and route through the same Pydantic schemas. Grouping keeps the
 * contract obvious and reduces the chance of drift between frontend type
 * names and backend schema names.
 *
 * SECURITY: Anonymous submissions are allowed (S9 issues a system JWT for
 * unauthenticated public routes). For authenticated callers we still pass
 * the bearer token. Admin endpoints (NPS aggregate, GET list w/o mine=true,
 * PATCH submission) require role=admin which the backend checks server-side;
 * the frontend only hides the entry points.
 */

import type {
  FeedbackSubmission,
  FeedbackSubmissionPayload,
  FeedbackSubmissionUpdate,
  FeedbackSubmissionFilters,
  FeedbackListResponse,
  NPSScore,
  NPSPayload,
  NPSAggregate,
  FeatureRequest,
  FeatureRequestPayload,
  FeatureRequestFilters,
  FeatureVoteResponse,
  MicroSurveyPayload,
  BetaEnrollment,
  BetaEnrollmentPatch,
} from "@/types/api";
import { apiFetch } from "./_client";

export function createFeedbackApi(t: string | undefined) {
  return {
    /**
     * postFeedbackSubmission — submit a bug / feature / UX / general feedback.
     *
     * WHY token optional: anonymous submissions are allowed (PRD-0053 Wave G
     * approved decision). When the caller has no JWT, the backend requires
     * `payload.email` so support staff can follow up. The form-level
     * validator enforces this — gateway just passes through.
     *
     * BACKEND: POST /v1/feedback/submissions → 201 Created.
     */
    postFeedbackSubmission(
      payload: FeedbackSubmissionPayload,
    ): Promise<FeedbackSubmission> {
      return apiFetch<FeedbackSubmission>("/v1/feedback/submissions", {
        method: "POST",
        body: payload,
        token: t,
      });
    },

    /**
     * getFeedbackSubmissions — list feedback rows (admin OR user-own).
     *
     * WHY query string assembled here: TanStack Query queryKey arrays take
     * the filters object verbatim (good for cache uniqueness), but the
     * backend wants ?mine=true&status=open&kind=bug. URLSearchParams handles
     * the encoding and skips undefined values cleanly.
     *
     * WHY mine=true is the user-facing default: without it the route
     * requires admin role (returns 403). Components for end-users always
     * pass mine=true; the admin dashboard explicitly sets mine=false to
     * see the full tenant list.
     *
     * BACKEND: GET /v1/feedback/submissions → FeedbackListResponse.
     */
    async getFeedbackSubmissions(
      filters: FeedbackSubmissionFilters = {},
    ): Promise<FeedbackListResponse> {
      const params = new URLSearchParams();
      if (filters.mine) params.set("mine", "true");
      if (filters.status) params.set("status", filters.status);
      if (filters.kind) params.set("kind", filters.kind);
      if (filters.limit !== undefined) params.set("limit", String(filters.limit));
      if (filters.offset !== undefined) params.set("offset", String(filters.offset));
      const qs = params.toString();
      const path = qs ? `/v1/feedback/submissions?${qs}` : "/v1/feedback/submissions";
      return apiFetch<FeedbackListResponse>(path, { token: t });
    },

    /**
     * patchFeedbackSubmission — admin-only triage updates (status / tags / assignee).
     *
     * WHY PATCH (not PUT): the backend accepts partial bodies — undefined
     * fields are ignored. PUT semantics would require sending every field.
     *
     * BACKEND: PATCH /v1/feedback/submissions/{id} → updated row.
     */
    patchFeedbackSubmission(
      id: string,
      fields: FeedbackSubmissionUpdate,
    ): Promise<FeedbackSubmission> {
      return apiFetch<FeedbackSubmission>(
        `/v1/feedback/submissions/${encodeURIComponent(id)}`,
        { method: "PATCH", body: fields, token: t },
      );
    },

    /**
     * postNPS — submit a Net Promoter Score (0-10) with optional free-text.
     *
     * WHY surface field: the analytics team needs to compare NPS submitted
     * after a portfolio sync vs after a first-alert trigger. The backend
     * stores it on `nps_score.surface` for downstream slicing.
     *
     * BACKEND: POST /v1/feedback/nps → NPSScore (201).
     */
    postNPS(payload: NPSPayload): Promise<NPSScore> {
      return apiFetch<NPSScore>("/v1/feedback/nps", {
        method: "POST",
        body: payload,
        token: t,
      });
    },

    /**
     * getNPSAggregate — admin-only roll-up of NPS over a recent window.
     *
     * WHY admin-only: NPS is a leadership / product metric. Per-row scores
     * stay private to the user; the aggregate exposes only counts.
     *
     * @param days — backend-supported 1..365 window. Defaults to 30 server-side.
     * BACKEND: GET /v1/feedback/nps/aggregate?days=N → NPSAggregate.
     */
    getNPSAggregate(days?: number): Promise<NPSAggregate> {
      const path =
        days !== undefined
          ? `/v1/feedback/nps/aggregate?days=${days}`
          : "/v1/feedback/nps/aggregate";
      return apiFetch<NPSAggregate>(path, { token: t });
    },

    /**
     * getFeatureRequests — list public roadmap items.
     *
     * WHY this is "public" but still requires a JWT: the backend resolves
     * `tenant_id` from the JWT to scope feature requests per tenant. The
     * api-gateway issues a system JWT for unauthenticated routes, so anon
     * users still get a working response (with `has_voted: false`).
     *
     * BACKEND: GET /v1/feedback/features.
     */
    async getFeatureRequests(
      filters: FeatureRequestFilters = {},
    ): Promise<{ items: FeatureRequest[]; total: number }> {
      const params = new URLSearchParams();
      if (filters.status) params.set("status", filters.status);
      if (filters.category) params.set("category", filters.category);
      if (filters.limit !== undefined) params.set("limit", String(filters.limit));
      if (filters.offset !== undefined) params.set("offset", String(filters.offset));
      const qs = params.toString();
      const path = qs ? `/v1/feedback/features?${qs}` : "/v1/feedback/features";
      return apiFetch<{ items: FeatureRequest[]; total: number }>(path, { token: t });
    },

    /**
     * postFeatureRequest — propose a new feature.
     *
     * BACKEND: POST /v1/feedback/features → 201 Created with default
     * status="proposed", is_public starts true (admin can hide later).
     */
    postFeatureRequest(payload: FeatureRequestPayload): Promise<FeatureRequest> {
      return apiFetch<FeatureRequest>("/v1/feedback/features", {
        method: "POST",
        body: payload,
        token: t,
      });
    },

    /**
     * voteFeature — idempotent upvote (second click is a no-op server-side).
     *
     * WHY return the vote response (not void): the caller wants the new
     * vote_count to update the badge immediately without a refetch. The
     * backend already returns it; surfacing it here saves a round-trip.
     *
     * BACKEND: POST /v1/feedback/features/{id}/vote → FeatureVoteResponse.
     */
    voteFeature(id: string): Promise<FeatureVoteResponse> {
      return apiFetch<FeatureVoteResponse>(
        `/v1/feedback/features/${encodeURIComponent(id)}/vote`,
        { method: "POST", token: t },
      );
    },

    /**
     * postMicroSurvey — single-tap reaction (👍 👎 🤷) with optional comment.
     *
     * BACKEND: POST /v1/feedback/micro-survey → 201 Created. Anonymous
     * callers are accepted (the docs widget can fire from the public site).
     */
    postMicroSurvey(payload: MicroSurveyPayload): Promise<void> {
      // WHY <void>: callers don't need the response body — the success
      // toast just confirms receipt. apiFetch parses JSON anyway; we
      // discard it so consumers don't have to model an unused shape.
      return apiFetch<void>("/v1/feedback/micro-survey", {
        method: "POST",
        body: payload,
        token: t,
      });
    },

    /**
     * getBetaEnrollment — read the current user's beta-program row.
     *
     * BACKEND: GET /v1/feedback/beta-program/enrollment → 200 with
     * BetaEnrollmentResponse. The route is auth-only; calling without a
     * token returns 401. The server returns a row with `enrolled: false`
     * (not 404) when the user has never opted in, so the UI can render an
     * unchecked toggle without special-casing missing-row.
     *
     * PLAN-0052 Wave E T-E-5-07.
     */
    getBetaEnrollment(): Promise<BetaEnrollment> {
      return apiFetch<BetaEnrollment>("/v1/feedback/beta-program/enrollment", {
        method: "GET",
        token: t,
      });
    },

    /**
     * patchBetaEnrollment — partial update on the user's beta row. Used by
     * the toggle in /settings/beta-program. Server upserts on first PATCH.
     *
     * BACKEND: PATCH /v1/feedback/beta-program/enrollment → 200 with the
     * updated row. Auth-only.
     */
    patchBetaEnrollment(payload: BetaEnrollmentPatch): Promise<BetaEnrollment> {
      return apiFetch<BetaEnrollment>("/v1/feedback/beta-program/enrollment", {
        method: "PATCH",
        body: payload,
        token: t,
      });
    },
  };
}
