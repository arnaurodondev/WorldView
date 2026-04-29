"""Unit tests for feedback use cases (PLAN-0052 Wave D / T-D-4-05).

All tests use the in-memory ``FakeUnitOfWork`` from ``tests.unit.fakes``
(augmented with the feedback fakes). No DB, no HTTP — pure use-case
behaviour.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
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
    UpdateFeedbackSubmissionCommand,
    UpdateFeedbackSubmissionUseCase,
    UpsertBetaEnrollmentCommand,
    UpsertBetaEnrollmentUseCase,
    UpsertFeatureVoteCommand,
    UpsertFeatureVoteUseCase,
)
from portfolio.domain.errors import (
    FeatureRequestNotFoundError,
    FeedbackSubmissionNotFoundError,
    NPSRateLimitError,
)

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit]


# ── Helpers ──────────────────────────────────────────────────────────────────


_SENTINEL = object()


def _make_create_cmd(
    *,
    description: str = "I cannot find the dashboard logout button anywhere",
    user_id=_SENTINEL,
    email=None,
    console_logs=None,
) -> CreateFeedbackSubmissionCommand:
    # Sentinel pattern: default = generate a fresh user; passing user_id=None
    # explicitly keeps it None for the anonymous-feedback test.
    final_user_id = uuid4() if user_id is _SENTINEL else user_id
    return CreateFeedbackSubmissionCommand(
        tenant_id=uuid4(),
        user_id=final_user_id,
        email=email,
        kind="bug",
        severity="medium",
        description=description,
        console_logs=console_logs,
        screenshot_url=None,
        page_url="/dashboard",
        user_agent="Mozilla/5.0",
    )


# ── CreateFeedbackSubmissionUseCase ──────────────────────────────────────────


async def test_create_feedback_persists_with_redaction() -> None:
    uow = FakeUnitOfWork()
    cmd = _make_create_cmd(
        description="Auth failed: Bearer abcdef0123456789ABCDEFGH",
    )
    rec = await CreateFeedbackSubmissionUseCase().execute(cmd, uow)
    # Description must be redacted at the use-case layer.
    assert "abcdef0123456789ABCDEFGH" not in rec.description
    assert "[REDACTED:" in rec.description
    assert uow.committed
    assert uow.commit_count == 1


async def test_create_feedback_redacts_console_logs_recursively() -> None:
    uow = FakeUnitOfWork()
    cmd = _make_create_cmd(
        console_logs=[
            {"level": "error", "msg": "Bearer abcdef0123456789ABCDEFGH leaked"},
            {"level": "info", "msg": "ok", "ctx": {"email": "leaked@x.com"}},
        ],
    )
    rec = await CreateFeedbackSubmissionUseCase().execute(cmd, uow)
    flat = str(rec.console_logs)
    assert "abcdef0123456789ABCDEFGH" not in flat
    # Email regex catches it inside nested dict.
    assert "leaked@x.com" not in flat


async def test_create_feedback_anonymous_with_email_works() -> None:
    uow = FakeUnitOfWork()
    cmd = _make_create_cmd(user_id=None, email="anon@example.com")
    rec = await CreateFeedbackSubmissionUseCase().execute(cmd, uow)
    assert rec.user_id is None
    assert rec.email == "anon@example.com"


# ── ListFeedbackSubmissionsUseCase ───────────────────────────────────────────


async def test_list_feedback_filters_by_user() -> None:
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    for uid in (user_a, user_a, user_b):
        cmd = _make_create_cmd(user_id=uid)
        # Override tenant to the shared one so "list by tenant" gets all 3.
        cmd = CreateFeedbackSubmissionCommand(**{**cmd.__dict__, "tenant_id": tenant_id})
        await CreateFeedbackSubmissionUseCase().execute(cmd, uow)

    # All rows for the tenant.
    items, total = await ListFeedbackSubmissionsUseCase().execute(
        ListFeedbackSubmissionsQuery(tenant_id=tenant_id, user_id=None, status=None, kind=None, limit=10, offset=0),
        uow,
    )
    assert total == 3
    assert len(items) == 3

    # User A only.
    items_a, total_a = await ListFeedbackSubmissionsUseCase().execute(
        ListFeedbackSubmissionsQuery(tenant_id=tenant_id, user_id=user_a, status=None, kind=None, limit=10, offset=0),
        uow,
    )
    assert total_a == 2
    assert all(r.user_id == user_a for r in items_a)


async def test_list_feedback_tenant_isolation() -> None:
    uow = FakeUnitOfWork()
    tenant_a = uuid4()
    tenant_b = uuid4()
    # Two submissions in tenant_a, one in tenant_b — listing tenant_a must not leak tenant_b.
    for tid in (tenant_a, tenant_a, tenant_b):
        cmd = _make_create_cmd()
        cmd = CreateFeedbackSubmissionCommand(**{**cmd.__dict__, "tenant_id": tid})
        await CreateFeedbackSubmissionUseCase().execute(cmd, uow)

    items, total = await ListFeedbackSubmissionsUseCase().execute(
        ListFeedbackSubmissionsQuery(tenant_id=tenant_a, user_id=None, status=None, kind=None, limit=10, offset=0),
        uow,
    )
    assert total == 2
    assert all(r.tenant_id == tenant_a for r in items)


# ── Get / Update / Delete ────────────────────────────────────────────────────


async def test_get_feedback_not_found_raises() -> None:
    uow = FakeUnitOfWork()
    with pytest.raises(FeedbackSubmissionNotFoundError):
        await GetFeedbackSubmissionUseCase().execute(uuid4(), uuid4(), uow)


async def test_update_feedback_changes_status_and_tags() -> None:
    uow = FakeUnitOfWork()
    cmd = _make_create_cmd()
    rec = await CreateFeedbackSubmissionUseCase().execute(cmd, uow)

    updated = await UpdateFeedbackSubmissionUseCase().execute(
        UpdateFeedbackSubmissionCommand(
            submission_id=rec.id,
            tenant_id=rec.tenant_id,
            status="triaged",
            tags=["billing", "p2"],
            assigned_to=None,
        ),
        uow,
    )
    assert updated.status == "triaged"
    assert updated.tags == ["billing", "p2"]


async def test_update_feedback_not_found_raises() -> None:
    uow = FakeUnitOfWork()
    with pytest.raises(FeedbackSubmissionNotFoundError):
        await UpdateFeedbackSubmissionUseCase().execute(
            UpdateFeedbackSubmissionCommand(
                submission_id=uuid4(),
                tenant_id=uuid4(),
                status="triaged",
                tags=None,
                assigned_to=None,
            ),
            uow,
        )


async def test_delete_feedback_removes_row() -> None:
    uow = FakeUnitOfWork()
    cmd = _make_create_cmd()
    rec = await CreateFeedbackSubmissionUseCase().execute(cmd, uow)
    await DeleteFeedbackSubmissionUseCase().execute(rec.id, rec.tenant_id, uow)
    with pytest.raises(FeedbackSubmissionNotFoundError):
        await GetFeedbackSubmissionUseCase().execute(rec.id, rec.tenant_id, uow)


# ── NPS ──────────────────────────────────────────────────────────────────────


async def test_submit_nps_redacts_comment() -> None:
    uow = FakeUnitOfWork()
    cmd = SubmitNPSScoreCommand(
        tenant_id=uuid4(),
        user_id=uuid4(),
        score=9,
        comment="Loved it; api_key=abcdef1234567890ABCDEF leaked once",
        surface="dashboard",
    )
    rec = await SubmitNPSScoreUseCase().execute(cmd, uow)
    assert rec.score == 9
    assert "abcdef1234567890ABCDEF" not in (rec.comment or "")


async def test_submit_nps_twice_within_30_days_raises_rate_limit() -> None:
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user_id = uuid4()
    cmd = SubmitNPSScoreCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        score=8,
        comment=None,
        surface=None,
    )
    await SubmitNPSScoreUseCase().execute(cmd, uow)
    with pytest.raises(NPSRateLimitError):
        await SubmitNPSScoreUseCase().execute(cmd, uow)


async def test_nps_aggregate_computes_promoter_minus_detractor() -> None:
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    # 2 promoters (9, 10), 1 passive (7), 1 detractor (3) — NPS = (2-1)/4*100 = 25
    for score in (9, 10, 7, 3):
        await SubmitNPSScoreUseCase().execute(
            SubmitNPSScoreCommand(
                tenant_id=tenant_id,
                user_id=uuid4(),  # different users so no rate-limit
                score=score,
                comment=None,
                surface=None,
            ),
            uow,
        )
    agg = await GetNPSAggregateUseCase().execute(
        GetNPSAggregateQuery(tenant_id=tenant_id, days=30),
        uow,
    )
    assert agg.promoter_count == 2
    assert agg.passive_count == 1
    assert agg.detractor_count == 1
    assert agg.sample_size == 4
    assert agg.nps_score == pytest.approx(25.0)


async def test_nps_aggregate_zero_when_no_responses() -> None:
    uow = FakeUnitOfWork()
    agg = await GetNPSAggregateUseCase().execute(
        GetNPSAggregateQuery(tenant_id=uuid4(), days=30),
        uow,
    )
    assert agg.sample_size == 0
    assert agg.nps_score == 0.0


# ── Feature requests + votes ─────────────────────────────────────────────────


async def test_create_feature_request_and_list() -> None:
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    rec = await CreateFeatureRequestUseCase().execute(
        CreateFeatureRequestCommand(
            tenant_id=tenant_id,
            user_id=uuid4(),
            title="Dark mode for charts",
            description="Make the chart background match the rest of the app",
            category="dashboard",
        ),
        uow,
    )
    assert rec.vote_count == 0
    pairs, total = await ListFeatureRequestsUseCase().execute(
        ListFeatureRequestsQuery(tenant_id=tenant_id, status=None, category=None, limit=10, offset=0),
        uow,
    )
    assert total == 1
    assert pairs[0][0].id == rec.id
    assert pairs[0][1] is False  # has_voted == False (no viewer passed)


async def test_upsert_vote_idempotent() -> None:
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user_id = uuid4()
    rec = await CreateFeatureRequestUseCase().execute(
        CreateFeatureRequestCommand(
            tenant_id=tenant_id,
            user_id=user_id,
            title="Foo",
            description="Bar",
            category=None,
        ),
        uow,
    )
    cmd = UpsertFeatureVoteCommand(feature_request_id=rec.id, tenant_id=tenant_id, user_id=user_id)
    r1, _ = await UpsertFeatureVoteUseCase().execute(cmd, uow)
    r2, _ = await UpsertFeatureVoteUseCase().execute(cmd, uow)
    assert r1.vote_count == 1
    assert r2.vote_count == 1  # second call is a no-op


async def test_upsert_vote_unknown_feature_raises() -> None:
    uow = FakeUnitOfWork()
    with pytest.raises(FeatureRequestNotFoundError):
        await UpsertFeatureVoteUseCase().execute(
            UpsertFeatureVoteCommand(
                feature_request_id=uuid4(),
                tenant_id=uuid4(),
                user_id=uuid4(),
            ),
            uow,
        )


async def test_list_features_returns_has_voted_for_viewer() -> None:
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    voter = uuid4()
    other_user = uuid4()
    rec = await CreateFeatureRequestUseCase().execute(
        CreateFeatureRequestCommand(
            tenant_id=tenant_id,
            user_id=voter,
            title="Foo",
            description="Bar",
            category=None,
        ),
        uow,
    )
    await UpsertFeatureVoteUseCase().execute(
        UpsertFeatureVoteCommand(feature_request_id=rec.id, tenant_id=tenant_id, user_id=voter),
        uow,
    )

    # Voter sees has_voted=True
    pairs_voter, _ = await ListFeatureRequestsUseCase().execute(
        ListFeatureRequestsQuery(tenant_id=tenant_id, status=None, category=None, limit=10, offset=0),
        uow,
        viewer_user_id=voter,
    )
    assert pairs_voter[0][1] is True

    # Other user sees has_voted=False
    pairs_other, _ = await ListFeatureRequestsUseCase().execute(
        ListFeatureRequestsQuery(tenant_id=tenant_id, status=None, category=None, limit=10, offset=0),
        uow,
        viewer_user_id=other_user,
    )
    assert pairs_other[0][1] is False


# ── Micro-survey ─────────────────────────────────────────────────────────────


async def test_submit_micro_survey_persists_and_redacts() -> None:
    uow = FakeUnitOfWork()
    rec = await SubmitMicroSurveyUseCase().execute(
        SubmitMicroSurveyCommand(
            tenant_id=uuid4(),
            user_id=uuid4(),
            survey_key="docs:/instruments/overview",
            response="positive",
            comment="contact me at user@example.com",
        ),
        uow,
    )
    assert rec.response == "positive"
    assert "user@example.com" not in (rec.comment or "")


# ── Beta enrolment ───────────────────────────────────────────────────────────


async def test_get_beta_enrollment_returns_default_when_missing() -> None:
    uow = FakeUnitOfWork()
    rec = await GetBetaEnrollmentUseCase().execute(uuid4(), uuid4(), uow)
    assert rec.enrolled is False
    assert rec.programs == []


async def test_upsert_beta_enrollment_creates_then_updates() -> None:
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user_id = uuid4()
    rec1 = await UpsertBetaEnrollmentUseCase().execute(
        UpsertBetaEnrollmentCommand(
            tenant_id=tenant_id,
            user_id=user_id,
            enrolled=True,
            programs=["ai-brief"],
        ),
        uow,
    )
    assert rec1.enrolled is True
    rec2 = await UpsertBetaEnrollmentUseCase().execute(
        UpsertBetaEnrollmentCommand(
            tenant_id=tenant_id,
            user_id=user_id,
            enrolled=False,
            programs=[],
        ),
        uow,
    )
    assert rec2.enrolled is False
    assert rec2.programs == []
