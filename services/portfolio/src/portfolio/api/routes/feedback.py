"""Feedback subsystem API routes (PLAN-0052 Wave D / T-D-4-03).

12 endpoints under ``/api/v1/feedback`` — exposed by the portfolio
service. The api-gateway proxies ``/v1/feedback/*`` to these routes.

Auth pattern: tenant_id / user_id come from ``request.state`` set by
``InternalJWTMiddleware`` — never from raw headers (PRD-0025).

Anonymous submissions: ``POST /submissions`` accepts requests where
``user_id`` is missing from the JWT (e.g. a docs-page form) AS LONG AS
the body carries an ``email`` field. This is the only feedback path
that allows an unauthenticated user.

Admin-only routes use the same role check as
``services/api-gateway/src/api_gateway/routes/admin_costs.py:_require_admin``:
``request.state.role == "admin"``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.api.feedback_schemas import (
    BetaEnrollmentResponse,
    BetaEnrollmentUpdate,
    FeatureRequestCreate,
    FeatureRequestListResponse,
    FeatureRequestResponse,
    FeatureRequestUpdate,
    FeatureVoteResponse,
    FeedbackListResponse,
    FeedbackSubmissionCreate,
    FeedbackSubmissionResponse,
    FeedbackSubmissionUpdate,
    MicroSurveyCreate,
    MicroSurveyResponseSchema,
    NPSAggregateResponse,
    NPSSubmissionCreate,
    NPSSubmissionResponse,
)
from portfolio.application.ports.feedback import FeedbackSubmissionRecord
from portfolio.application.use_cases.feedback import (
    CreateFeatureRequestCommand,
    CreateFeatureRequestUseCase,
    CreateFeedbackSubmissionCommand,
    CreateFeedbackSubmissionUseCase,
    DeleteFeedbackSubmissionUseCase,
    GetBetaEnrollmentUseCase,
    GetFeedbackSubmissionUseCase,
    GetNPSAggregateQuery,
    GetNPSAggregateUseCase,
    ListFeatureRequestsQuery,
    ListFeatureRequestsUseCase,
    ListFeedbackSubmissionsQuery,
    ListFeedbackSubmissionsUseCase,
    SubmitMicroSurveyCommand,
    SubmitMicroSurveyUseCase,
    SubmitNPSScoreCommand,
    SubmitNPSScoreUseCase,
    UpdateFeatureRequestCommand,
    UpdateFeatureRequestUseCase,
    UpdateFeedbackSubmissionCommand,
    UpdateFeedbackSubmissionUseCase,
    UpsertBetaEnrollmentCommand,
    UpsertBetaEnrollmentUseCase,
    UpsertFeatureVoteCommand,
    UpsertFeatureVoteUseCase,
)

router = APIRouter(tags=["feedback"])


# ── Auth helpers ─────────────────────────────────────────────────────────────


def _extract_tenant_id(request: Request) -> UUID:
    """Read tenant_id from request.state set by InternalJWTMiddleware.

    F-Q1-03: defensive parsing — system / dev JWTs may carry a non-UUID
    sentinel for tenant_id. Anything that does not parse as a UUID is
    treated as missing.
    """
    raw = getattr(request.state, "tenant_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
    try:
        return UUID(str(raw))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Malformed tenant_id in JWT") from exc


def _extract_user_id_optional(request: Request) -> UUID | None:
    """Return the authenticated user_id, or ``None`` for anonymous calls.

    Used by routes that allow anon submissions (POST /submissions,
    POST /micro-survey). All other routes use ``_extract_user_id``
    which raises 401 when absent.

    F-Q1-03: the gateway issues a system JWT for unauthenticated public
    routes with ``sub: "system:api-gateway"``. That string is truthy but
    not a UUID — without the explicit guard ``UUID("system:api-gateway")``
    raised ValueError → 500 on every anon submission. We treat any
    non-UUID sub as anonymous.
    """
    raw = getattr(request.state, "user_id", None)
    if not raw or raw == "system:api-gateway":
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _extract_user_id(request: Request) -> UUID:
    raw = getattr(request.state, "user_id", None)
    if not raw or raw == "system:api-gateway":
        raise HTTPException(status_code=401, detail="Missing user_id in JWT")
    try:
        return UUID(str(raw))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Malformed user_id in JWT") from exc


def _is_admin(request: Request) -> bool:
    """True if the JWT carries ``role=admin``.

    Mirrors the gateway helper in ``admin_costs._require_admin``.
    """
    return getattr(request.state, "role", None) == "admin"


def _require_admin(request: Request) -> None:
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin role required")


def _to_response(record: FeedbackSubmissionRecord) -> FeedbackSubmissionResponse:
    return FeedbackSubmissionResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        email=record.email,
        kind=record.kind,  # type: ignore[arg-type]
        severity=record.severity,  # type: ignore[arg-type]
        description=record.description,
        console_logs=record.console_logs,
        screenshot_url=record.screenshot_url,
        page_url=record.page_url,
        user_agent=record.user_agent,
        status=record.status,  # type: ignore[arg-type]
        tags=record.tags,
        assigned_to=record.assigned_to,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ── Feedback submissions ─────────────────────────────────────────────────────


@router.post(
    "/submissions",
    response_model=FeedbackSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_submission(
    body: FeedbackSubmissionCreate,
    uow: UoWDep,
    request: Request,
) -> FeedbackSubmissionResponse:
    """Create a feedback submission.

    Anonymous path: when no JWT user is present, ``body.email`` is
    required so support staff can follow up. We still need a tenant_id —
    the gateway issues a system JWT for unauthenticated public routes,
    which carries the public tenant id.
    """
    tenant_id = _extract_tenant_id(request)
    user_id = _extract_user_id_optional(request)
    if user_id is None and not body.email:
        raise HTTPException(
            status_code=422,
            detail="Either authentication or email is required for anonymous feedback",
        )
    cmd = CreateFeedbackSubmissionCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        email=body.email,
        kind=body.kind,
        severity=body.severity,
        description=body.description,
        console_logs=body.console_logs,
        screenshot_url=body.screenshot_url,
        page_url=body.page_url,
        user_agent=body.user_agent,
    )
    record = await CreateFeedbackSubmissionUseCase().execute(cmd, uow)
    return _to_response(record)


@router.get("/submissions", response_model=FeedbackListResponse)
async def list_submissions(
    uow: ReadUoWDep,
    request: Request,
    mine: bool = Query(default=False),
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> FeedbackListResponse:
    """List feedback submissions.

    Default behaviour: admin-only (full list across the tenant).
    With ``mine=true`` any authenticated user can list their own
    submissions.
    """
    tenant_id = _extract_tenant_id(request)
    if mine:
        user_id = _extract_user_id(request)
        query = ListFeedbackSubmissionsQuery(
            tenant_id=tenant_id,
            user_id=user_id,
            status=status,
            kind=kind,
            limit=limit,
            offset=offset,
        )
    else:
        _require_admin(request)
        query = ListFeedbackSubmissionsQuery(
            tenant_id=tenant_id,
            user_id=None,
            status=status,
            kind=kind,
            limit=limit,
            offset=offset,
        )
    items, total = await ListFeedbackSubmissionsUseCase().execute(query, uow)
    return FeedbackListResponse(
        items=[_to_response(r) for r in items],
        total=total,
    )


@router.get("/submissions/anonymous", response_model=FeedbackListResponse)
async def list_anonymous_submissions(
    uow: ReadUoWDep,
    request: Request,
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> FeedbackListResponse:
    """List submissions made anonymously (admin-only).

    F-Q1-04: anonymous submissions land under the configured "platform
    support" tenant id (``feedback_anonymous_tenant_id`` — default nil
    UUID, matches the gateway's issue_public_jwt). Real-tenant admins
    can never see these via ``GET /submissions`` because that endpoint
    filters by their own tenant. This endpoint exists so admins can
    review the anon backlog.

    Defined BEFORE ``GET /submissions/{submission_id}`` so FastAPI's
    path-matching resolves "anonymous" as the literal segment, not as
    a UUID id.
    """
    _require_admin(request)
    settings = request.app.state.settings
    anon_tenant_id = UUID(settings.feedback_anonymous_tenant_id)
    query = ListFeedbackSubmissionsQuery(
        tenant_id=anon_tenant_id,
        user_id=None,
        status=status,
        kind=kind,
        limit=limit,
        offset=offset,
    )
    items, total = await ListFeedbackSubmissionsUseCase().execute(query, uow)
    return FeedbackListResponse(
        items=[_to_response(r) for r in items],
        total=total,
    )


@router.get("/submissions/{submission_id}", response_model=FeedbackSubmissionResponse)
async def get_submission(
    submission_id: UUID,
    uow: ReadUoWDep,
    request: Request,
) -> FeedbackSubmissionResponse:
    tenant_id = _extract_tenant_id(request)
    rec = await GetFeedbackSubmissionUseCase().execute(submission_id, tenant_id, uow)
    # Owner OR admin can read; everyone else 403.
    if not _is_admin(request):
        viewer = _extract_user_id_optional(request)
        if rec.user_id is None or viewer != rec.user_id:
            raise HTTPException(status_code=403, detail="Not authorised")
    return _to_response(rec)


@router.patch("/submissions/{submission_id}", response_model=FeedbackSubmissionResponse)
async def update_submission(
    submission_id: UUID,
    body: FeedbackSubmissionUpdate,
    uow: UoWDep,
    request: Request,
) -> FeedbackSubmissionResponse:
    _require_admin(request)
    tenant_id = _extract_tenant_id(request)
    cmd = UpdateFeedbackSubmissionCommand(
        submission_id=submission_id,
        tenant_id=tenant_id,
        status=body.status,
        tags=body.tags,
        assigned_to=body.assigned_to,
    )
    rec = await UpdateFeedbackSubmissionUseCase().execute(cmd, uow)
    return _to_response(rec)


@router.delete(
    "/submissions/{submission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_submission(
    submission_id: UUID,
    uow: UoWDep,
    request: Request,
) -> None:
    _require_admin(request)
    tenant_id = _extract_tenant_id(request)
    await DeleteFeedbackSubmissionUseCase().execute(submission_id, tenant_id, uow)


# ── NPS ──────────────────────────────────────────────────────────────────────


@router.post(
    "/nps",
    response_model=NPSSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_nps(
    body: NPSSubmissionCreate,
    uow: UoWDep,
    request: Request,
) -> NPSSubmissionResponse:
    tenant_id = _extract_tenant_id(request)
    user_id = _extract_user_id(request)
    cmd = SubmitNPSScoreCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        score=body.score,
        comment=body.comment,
        surface=body.surface,
    )
    record = await SubmitNPSScoreUseCase().execute(cmd, uow)
    return NPSSubmissionResponse(id=record.id, score=record.score, created_at=record.created_at)


@router.get("/nps/aggregate", response_model=NPSAggregateResponse)
async def nps_aggregate(
    uow: ReadUoWDep,
    request: Request,
    days: int = Query(30, ge=1, le=365),
) -> NPSAggregateResponse:
    _require_admin(request)
    tenant_id = _extract_tenant_id(request)
    agg = await GetNPSAggregateUseCase().execute(GetNPSAggregateQuery(tenant_id=tenant_id, days=days), uow)
    return NPSAggregateResponse(
        promoter_count=agg.promoter_count,
        passive_count=agg.passive_count,
        detractor_count=agg.detractor_count,
        nps_score=agg.nps_score,
        sample_size=agg.sample_size,
        period_days=agg.period_days,
    )


# ── Feature requests / public roadmap ────────────────────────────────────────


@router.get("/features", response_model=FeatureRequestListResponse)
async def list_features(
    uow: ReadUoWDep,
    request: Request,
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> FeatureRequestListResponse:
    tenant_id = _extract_tenant_id(request)
    viewer = _extract_user_id_optional(request)
    query = ListFeatureRequestsQuery(
        tenant_id=tenant_id,
        status=status,
        category=category,
        limit=limit,
        offset=offset,
    )
    pairs, total = await ListFeatureRequestsUseCase().execute(query, uow, viewer_user_id=viewer)
    return FeatureRequestListResponse(
        items=[
            FeatureRequestResponse(
                id=rec.id,
                title=rec.title,
                description=rec.description,
                status=rec.status,  # type: ignore[arg-type]
                category=rec.category,
                vote_count=rec.vote_count,
                is_public=rec.is_public,
                created_at=rec.created_at,
                updated_at=rec.updated_at,
                has_voted=voted,
            )
            for rec, voted in pairs
        ],
        total=total,
    )


@router.post(
    "/features",
    response_model=FeatureRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_feature(
    body: FeatureRequestCreate,
    uow: UoWDep,
    request: Request,
) -> FeatureRequestResponse:
    tenant_id = _extract_tenant_id(request)
    user_id = _extract_user_id(request)
    cmd = CreateFeatureRequestCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        title=body.title,
        description=body.description,
        category=body.category,
    )
    rec = await CreateFeatureRequestUseCase().execute(cmd, uow)
    return FeatureRequestResponse(
        id=rec.id,
        title=rec.title,
        description=rec.description,
        status=rec.status,  # type: ignore[arg-type]
        category=rec.category,
        vote_count=rec.vote_count,
        is_public=rec.is_public,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        has_voted=False,
    )


@router.patch("/features/{feature_request_id}", response_model=FeatureRequestResponse)
async def update_feature(
    feature_request_id: UUID,
    body: FeatureRequestUpdate,
    uow: UoWDep,
    request: Request,
) -> FeatureRequestResponse:
    _require_admin(request)
    tenant_id = _extract_tenant_id(request)
    cmd = UpdateFeatureRequestCommand(
        feature_request_id=feature_request_id,
        tenant_id=tenant_id,
        status=body.status,
        category=body.category,
        is_public=body.is_public,
    )
    rec = await UpdateFeatureRequestUseCase().execute(cmd, uow)
    return FeatureRequestResponse(
        id=rec.id,
        title=rec.title,
        description=rec.description,
        status=rec.status,  # type: ignore[arg-type]
        category=rec.category,
        vote_count=rec.vote_count,
        is_public=rec.is_public,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        has_voted=False,
    )


@router.post("/features/{feature_request_id}/vote", response_model=FeatureVoteResponse)
async def vote_feature(
    feature_request_id: UUID,
    uow: UoWDep,
    request: Request,
) -> FeatureVoteResponse:
    """Idempotent upvote — second POST returns the same row."""
    tenant_id = _extract_tenant_id(request)
    user_id = _extract_user_id(request)
    cmd = UpsertFeatureVoteCommand(
        feature_request_id=feature_request_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    rec, _new = await UpsertFeatureVoteUseCase().execute(cmd, uow)
    return FeatureVoteResponse(
        feature_request_id=rec.id,
        vote_count=rec.vote_count,
        has_voted=True,
    )


# ── Micro-survey ─────────────────────────────────────────────────────────────


@router.post(
    "/micro-survey",
    response_model=MicroSurveyResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def submit_micro_survey(
    body: MicroSurveyCreate,
    uow: UoWDep,
    request: Request,
) -> MicroSurveyResponseSchema:
    tenant_id = _extract_tenant_id(request)
    user_id = _extract_user_id_optional(request)  # docs widget can be anon
    cmd = SubmitMicroSurveyCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        survey_key=body.survey_key,
        response=body.response,
        comment=body.comment,
    )
    rec = await SubmitMicroSurveyUseCase().execute(cmd, uow)
    return MicroSurveyResponseSchema(
        id=rec.id,
        survey_key=rec.survey_key,
        response=rec.response,  # type: ignore[arg-type]
        created_at=rec.created_at,
    )


# ── Beta program enrolment ───────────────────────────────────────────────────


@router.get("/beta-program/enrollment", response_model=BetaEnrollmentResponse)
async def get_beta_enrollment(
    uow: ReadUoWDep,
    request: Request,
) -> BetaEnrollmentResponse:
    tenant_id = _extract_tenant_id(request)
    user_id = _extract_user_id(request)
    rec = await GetBetaEnrollmentUseCase().execute(tenant_id, user_id, uow)
    return BetaEnrollmentResponse(
        enrolled=rec.enrolled,
        programs=rec.programs,
        enrolled_at=rec.enrolled_at,
        updated_at=rec.updated_at,
    )


@router.patch("/beta-program/enrollment", response_model=BetaEnrollmentResponse)
async def update_beta_enrollment(
    body: BetaEnrollmentUpdate,
    uow: UoWDep,
    request: Request,
) -> BetaEnrollmentResponse:
    tenant_id = _extract_tenant_id(request)
    user_id = _extract_user_id(request)
    cmd = UpsertBetaEnrollmentCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        enrolled=body.enrolled,
        programs=body.programs,
    )
    rec = await UpsertBetaEnrollmentUseCase().execute(cmd, uow)
    return BetaEnrollmentResponse(
        enrolled=rec.enrolled,
        programs=rec.programs,
        enrolled_at=rec.enrolled_at,
        updated_at=rec.updated_at,
    )
