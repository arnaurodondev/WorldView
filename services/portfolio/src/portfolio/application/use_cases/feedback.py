"""Use cases for the feedback subsystem (PLAN-0052 Wave D / T-D-4-03).

Each use case is a small, single-purpose object exposed to the API
layer. Mutating use cases call ``uow.commit()``; read-only ones do
not commit (R27).

PII redaction is applied **inside** the use case (not the route)
because:
    1. It is part of the domain rule "no secrets at rest", not a
       transport concern.
    2. Tests at the use-case level can verify redaction without
       spinning up FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.ports.feedback import (
    BetaEnrollmentRecord,
    FeatureRequestRecord,
    FeatureVoteRecord,
    FeedbackSubmissionRecord,
    MicroSurveyRecord,
    NPSScoreRecord,
)
from portfolio.domain.errors import (
    FeatureRequestNotFoundError,
    FeedbackSubmissionNotFoundError,
    NPSRateLimitError,
)
from portfolio.security.pii_redaction import redact, redact_json

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


# ── Commands / queries ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CreateFeedbackSubmissionCommand:
    tenant_id: UUID
    user_id: UUID | None  # None for anonymous (with email)
    email: str | None
    kind: str
    severity: str | None
    description: str
    console_logs: Any | None
    screenshot_url: str | None
    page_url: str | None
    user_agent: str | None
    # REQ-002d (TASK-W0-05): caller-supplied ``Idempotency-Key`` header. On
    # replay we return the original record with 200 instead of inserting a
    # duplicate. NULL when the header is absent (back-compat for older clients).
    idempotency_key: str | None = None


@dataclass(frozen=True)
class CreateFeedbackSubmissionResult:
    """Use-case result so the route can pick 201 (new) vs 200 (replay)."""

    record: FeedbackSubmissionRecord
    created: bool


@dataclass(frozen=True)
class ListFeedbackSubmissionsQuery:
    tenant_id: UUID
    user_id: UUID | None  # When set, filter to this user only ("mine")
    status: str | None
    kind: str | None
    limit: int
    offset: int


@dataclass(frozen=True)
class UpdateFeedbackSubmissionCommand:
    submission_id: UUID
    tenant_id: UUID
    status: str | None
    tags: list[str] | None
    assigned_to: UUID | None


@dataclass(frozen=True)
class SubmitNPSScoreCommand:
    tenant_id: UUID
    user_id: UUID
    score: int
    comment: str | None
    surface: str | None


@dataclass(frozen=True)
class GetNPSAggregateQuery:
    tenant_id: UUID
    days: int


@dataclass(frozen=True)
class CreateFeatureRequestCommand:
    tenant_id: UUID
    user_id: UUID | None
    title: str
    description: str
    category: str | None


@dataclass(frozen=True)
class ListFeatureRequestsQuery:
    tenant_id: UUID
    status: str | None
    category: str | None
    limit: int
    offset: int


@dataclass(frozen=True)
class UpdateFeatureRequestCommand:
    feature_request_id: UUID
    tenant_id: UUID
    status: str | None
    category: str | None
    is_public: bool | None


@dataclass(frozen=True)
class UpsertFeatureVoteCommand:
    feature_request_id: UUID
    tenant_id: UUID
    user_id: UUID


@dataclass(frozen=True)
class SubmitMicroSurveyCommand:
    tenant_id: UUID
    user_id: UUID | None
    survey_key: str
    response: str
    comment: str | None


@dataclass(frozen=True)
class UpsertBetaEnrollmentCommand:
    tenant_id: UUID
    user_id: UUID
    enrolled: bool
    programs: list[str]


# ── Use cases ─────────────────────────────────────────────────────────────────


class CreateFeedbackSubmissionUseCase:
    async def execute(
        self,
        cmd: CreateFeedbackSubmissionCommand,
        uow: UnitOfWork,
    ) -> CreateFeedbackSubmissionResult:
        # ── REQ-002d: idempotency-key validation + replay lookup ──────────────
        idem_uuid: UUID | None = None
        if cmd.idempotency_key is not None:
            try:
                idem_uuid = UUID(cmd.idempotency_key)
            except (ValueError, AttributeError) as exc:
                from portfolio.domain.errors import IdempotencyKeyInvalidError

                raise IdempotencyKeyInvalidError(
                    f"idempotency_key must be a valid UUID: {exc}",
                ) from exc
            existing = await uow.feedback_submissions.find_by_idempotency_key(
                cmd.tenant_id,
                idem_uuid,
            )
            if existing is not None:
                # Same key + materially different body → 409. Compare the
                # user-visible fields the route already validated against.
                # We do NOT compare console_logs / screenshot_url since those
                # are noisy and the request body is the primary contract.
                if (
                    existing.kind != cmd.kind
                    or existing.severity != cmd.severity
                    or existing.user_id != cmd.user_id
                    or existing.email != cmd.email
                ):
                    from portfolio.domain.errors import IdempotencyConflictError

                    raise IdempotencyConflictError(
                        f"Idempotency key {cmd.idempotency_key!r} already used with a different request body",
                    )
                # Idempotent replay — return the original record verbatim.
                return CreateFeedbackSubmissionResult(record=existing, created=False)

        # Redact PII / secrets before they hit the DB. We redact:
        #   * description — free text from the user
        #   * console_logs — captured browser logs (often contain Bearer tokens)
        # We do NOT redact the explicit email field — it's a structured field
        # the user knowingly typed in for follow-up contact.
        # description is required (min_length=10 in the schema), so redact()
        # never returns None — narrow the type via assert for mypy.
        redacted_description = redact(cmd.description)
        assert redacted_description is not None
        redacted_console_logs = redact_json(cmd.console_logs) if cmd.console_logs is not None else None

        now = utc_now()
        record = FeedbackSubmissionRecord(
            id=new_uuid7(),
            tenant_id=cmd.tenant_id,
            user_id=cmd.user_id,
            email=cmd.email,
            kind=cmd.kind,
            severity=cmd.severity,
            description=redacted_description,
            console_logs=redacted_console_logs,
            screenshot_url=cmd.screenshot_url,
            page_url=cmd.page_url,
            user_agent=cmd.user_agent,
            status="open",
            tags=[],
            assigned_to=None,
            created_at=now,
            updated_at=now,
            # REQ-002d: stamp the key so concurrent replays can resolve back.
            idempotency_key=idem_uuid,
        )
        await uow.feedback_submissions.add(record)

        # REQ-002d: catch the TOCTOU race where two concurrent same-key
        # requests both pass ``find_by_idempotency_key`` and collide on the
        # partial unique index at commit. The second resolves back to the
        # original row and returns ``created=False``.
        from sqlalchemy.exc import IntegrityError

        try:
            await uow.commit()
        except IntegrityError as exc:
            await uow.rollback()
            if idem_uuid is not None:
                existing = await uow.feedback_submissions.find_by_idempotency_key(
                    cmd.tenant_id,
                    idem_uuid,
                )
                if existing is not None:
                    return CreateFeedbackSubmissionResult(record=existing, created=False)
            from portfolio.domain.errors import IdempotencyConflictError

            raise IdempotencyConflictError(
                f"Concurrent idempotency conflict on key {cmd.idempotency_key!r}; retry the request.",
            ) from exc

        logger.info(  # type: ignore[no-any-return]
            "feedback_submission_created",
            submission_id=str(record.id),
            kind=record.kind,
            anonymous=record.user_id is None,
        )
        return CreateFeedbackSubmissionResult(record=record, created=True)


class ListFeedbackSubmissionsUseCase:
    async def execute(
        self,
        query: ListFeedbackSubmissionsQuery,
        uow: ReadOnlyUnitOfWork,
    ) -> tuple[list[FeedbackSubmissionRecord], int]:
        return await uow.feedback_submissions.list(
            query.tenant_id,
            user_id=query.user_id,
            status=query.status,
            kind=query.kind,
            limit=query.limit,
            offset=query.offset,
        )


class GetFeedbackSubmissionUseCase:
    async def execute(
        self,
        submission_id: UUID,
        tenant_id: UUID,
        uow: ReadOnlyUnitOfWork,
    ) -> FeedbackSubmissionRecord:
        rec = await uow.feedback_submissions.get(submission_id, tenant_id)
        if rec is None:
            raise FeedbackSubmissionNotFoundError(f"Feedback {submission_id} not found")
        return rec


class UpdateFeedbackSubmissionUseCase:
    async def execute(
        self,
        cmd: UpdateFeedbackSubmissionCommand,
        uow: UnitOfWork,
    ) -> FeedbackSubmissionRecord:
        updated = await uow.feedback_submissions.update(
            cmd.submission_id,
            cmd.tenant_id,
            status=cmd.status,
            tags=cmd.tags,
            assigned_to=cmd.assigned_to,
        )
        if updated is None:
            raise FeedbackSubmissionNotFoundError(f"Feedback {cmd.submission_id} not found")
        await uow.commit()
        return updated


class DeleteFeedbackSubmissionUseCase:
    async def execute(self, submission_id: UUID, tenant_id: UUID, uow: UnitOfWork) -> None:
        deleted = await uow.feedback_submissions.delete(submission_id, tenant_id)
        if not deleted:
            raise FeedbackSubmissionNotFoundError(f"Feedback {submission_id} not found")
        await uow.commit()


class SubmitNPSScoreUseCase:
    async def execute(self, cmd: SubmitNPSScoreCommand, uow: UnitOfWork) -> NPSScoreRecord:
        # F-Q1-01: enforce the 30-day-per-(tenant,user) rate limit at the
        # application layer. The original migration used a partial-unique
        # index with ``WHERE created_at > now() - INTERVAL '30 days'`` but
        # Postgres rejects non-IMMUTABLE functions in index predicates.
        # SELECT-then-INSERT has a tiny race window — the repo's add() also
        # maps IntegrityError → NPSRateLimitError as belt-and-suspenders.
        cutoff = utc_now() - timedelta(days=30)
        existing = await uow.nps_scores.find_recent_by_user(cmd.tenant_id, cmd.user_id, cutoff)
        if existing is not None:
            raise NPSRateLimitError(
                f"User {cmd.user_id} already submitted an NPS score in the last 30 days",
            )
        # Redact comment before persist — users sometimes paste auth headers
        # into "what could we improve" boxes.
        redacted_comment = redact(cmd.comment)
        record = NPSScoreRecord(
            id=new_uuid7(),
            tenant_id=cmd.tenant_id,
            user_id=cmd.user_id,
            score=cmd.score,
            comment=redacted_comment,
            surface=cmd.surface,
            created_at=utc_now(),
        )
        await uow.nps_scores.add(record)
        await uow.commit()
        return record


@dataclass(frozen=True)
class NPSAggregate:
    promoter_count: int
    passive_count: int
    detractor_count: int
    nps_score: float
    sample_size: int
    period_days: int


class GetNPSAggregateUseCase:
    async def execute(self, query: GetNPSAggregateQuery, uow: ReadOnlyUnitOfWork) -> NPSAggregate:
        promoter, passive, detractor = await uow.nps_scores.aggregate(
            query.tenant_id,
            days=query.days,
        )
        sample = promoter + passive + detractor
        # NPS = %promoters - %detractors (range -100 to +100). When there are
        # no responses the result is conventionally 0.
        nps = ((promoter - detractor) / sample * 100.0) if sample > 0 else 0.0
        return NPSAggregate(
            promoter_count=promoter,
            passive_count=passive,
            detractor_count=detractor,
            nps_score=nps,
            sample_size=sample,
            period_days=query.days,
        )


class ListFeatureRequestsUseCase:
    async def execute(
        self,
        query: ListFeatureRequestsQuery,
        uow: ReadOnlyUnitOfWork,
        *,
        viewer_user_id: UUID | None = None,
    ) -> tuple[list[tuple[FeatureRequestRecord, bool]], int]:
        # Returns list of (record, has_voted) tuples so the API layer can
        # render the upvote button state without an extra round-trip.
        records, total = await uow.feature_requests.list(
            query.tenant_id,
            status=query.status,
            category=query.category,
            is_public=True,  # Public roadmap — never expose admin-only items.
            limit=query.limit,
            offset=query.offset,
        )
        if viewer_user_id is None:
            return [(r, False) for r in records], total
        # has_voted check is one query per item — small N (≤50) keeps this
        # acceptable; if it becomes a hot path, batch into a single
        # ``WHERE feature_request_id = ANY(...)``.
        # F-Q1-09: pass tenant_id so a user belonging to multiple tenants
        # cannot probe vote state in the *other* tenant via crafted ids.
        result: list[tuple[FeatureRequestRecord, bool]] = []
        for r in records:
            voted = await uow.feature_votes.has_voted(r.id, viewer_user_id, query.tenant_id)
            result.append((r, voted))
        return result, total


class CreateFeatureRequestUseCase:
    async def execute(
        self,
        cmd: CreateFeatureRequestCommand,
        uow: UnitOfWork,
    ) -> FeatureRequestRecord:
        now = utc_now()
        # Title and description are user-supplied free text; redact in case
        # anyone pastes a token into the feature description. description is
        # required (min_length=1 in the schema) so redact() never returns None.
        redacted_description = redact(cmd.description)
        assert redacted_description is not None
        record = FeatureRequestRecord(
            id=new_uuid7(),
            tenant_id=cmd.tenant_id,
            created_by_user_id=cmd.user_id,
            title=cmd.title,
            description=redacted_description,
            status="proposed",
            category=cmd.category,
            vote_count=0,
            is_public=True,
            created_at=now,
            updated_at=now,
        )
        await uow.feature_requests.add(record)
        await uow.commit()
        return record


class UpsertFeatureVoteUseCase:
    async def execute(
        self,
        cmd: UpsertFeatureVoteCommand,
        uow: UnitOfWork,
    ) -> tuple[FeatureRequestRecord, bool]:
        # Verify the feature request exists and belongs to this tenant before
        # we let a vote be recorded — protects against tenant-leak via crafted IDs.
        feature = await uow.feature_requests.get(cmd.feature_request_id, cmd.tenant_id)
        if feature is None:
            raise FeatureRequestNotFoundError(
                f"Feature request {cmd.feature_request_id} not found",
            )
        await uow.feature_votes.upsert(
            FeatureVoteRecord(
                feature_request_id=cmd.feature_request_id,
                user_id=cmd.user_id,
                tenant_id=cmd.tenant_id,
                created_at=utc_now(),
            ),
        )
        # F-Q1-06: refresh_vote_count is now a single atomic UPDATE that
        # both reads count(feature_votes) and writes the denorm column in
        # one statement, eliminating the lost-update race window. Refresh
        # always — even on duplicate inserts — so any prior drift heals.
        new_count = await uow.feature_requests.refresh_vote_count(cmd.feature_request_id)
        await uow.commit()
        # Re-fetch so the response carries the updated count. The atomic
        # UPDATE just ran, so the re-fetch is guaranteed to see the new
        # value — no drift-compensation branch needed.
        refreshed = await uow.feature_requests.get(cmd.feature_request_id, cmd.tenant_id)
        assert refreshed is not None  # we just verified the row exists above
        assert refreshed.vote_count == new_count
        return refreshed, True


class UpdateFeatureRequestUseCase:
    async def execute(
        self,
        cmd: UpdateFeatureRequestCommand,
        uow: UnitOfWork,
    ) -> FeatureRequestRecord:
        updated = await uow.feature_requests.update(
            cmd.feature_request_id,
            cmd.tenant_id,
            status=cmd.status,
            category=cmd.category,
            is_public=cmd.is_public,
        )
        if updated is None:
            raise FeatureRequestNotFoundError(f"Feature request {cmd.feature_request_id} not found")
        await uow.commit()
        return updated


class SubmitMicroSurveyUseCase:
    async def execute(
        self,
        cmd: SubmitMicroSurveyCommand,
        uow: UnitOfWork,
    ) -> MicroSurveyRecord:
        record = MicroSurveyRecord(
            id=new_uuid7(),
            tenant_id=cmd.tenant_id,
            user_id=cmd.user_id,
            survey_key=cmd.survey_key,
            response=cmd.response,
            comment=redact(cmd.comment),
            created_at=utc_now(),
        )
        await uow.micro_surveys.add(record)
        await uow.commit()
        return record


class GetBetaEnrollmentUseCase:
    async def execute(
        self,
        tenant_id: UUID,
        user_id: UUID,
        uow: ReadOnlyUnitOfWork,
    ) -> BetaEnrollmentRecord:
        rec = await uow.beta_enrollments.get(tenant_id, user_id)
        if rec is None:
            # Default state: not enrolled, no programs. Returning a synthetic
            # row keeps the API contract simple (always 200 with a body).
            return BetaEnrollmentRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                enrolled=False,
                programs=[],
                enrolled_at=None,
                updated_at=None,
            )
        return rec


class UpsertBetaEnrollmentUseCase:
    async def execute(
        self,
        cmd: UpsertBetaEnrollmentCommand,
        uow: UnitOfWork,
    ) -> BetaEnrollmentRecord:
        record = BetaEnrollmentRecord(
            tenant_id=cmd.tenant_id,
            user_id=cmd.user_id,
            enrolled=cmd.enrolled,
            programs=cmd.programs,
        )
        result = await uow.beta_enrollments.upsert(record)
        await uow.commit()
        return result
