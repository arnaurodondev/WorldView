"""Email digest scheduler for the Alert service (S10).

``EmailScheduler.run()`` is called once per UTC hour by the
``scheduler_main`` entrypoint.  It queries ``email_preferences`` for users
whose ``send_day_of_week`` + ``send_hour_utc`` match the current UTC
day/hour, then orchestrates the per-user digest flow:

  1. Resolve delivery address (preferences override → S1 fallback).
  2. Fetch OHLCV + fundamentals from S3 (best-effort).
  3. Request AI narrative from S8 (best-effort — send partial on failure).
  4. Render HTML/plain template stub (full template implemented in Wave D-2).
  5. Write a ``pending_send`` log entry BEFORE attempting the send (outbox-first
     so crash-recovery can detect and retry stalled sends).
  6. Send via email provider with exponential-backoff retry (3 attempts).
  7. UPDATE log row to ``sent`` | ``failed`` + write outbox event atomically.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import update

from alert.domain.email_provider import EmailProviderError
from alert.infrastructure.clients.s8_client import BriefingClientError
from alert.infrastructure.db.models import EmailLogModel, EmailPreferenceModel, OutboxEventModel
from alert.infrastructure.db.repositories.email_preference import EmailPreferenceRepository
from alert.infrastructure.email.template import render_digest_email
from alert.infrastructure.messaging.email_sent_event import EMAIL_SENT_TOPIC, serialize_email_sent
from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from alert.config import Settings
    from alert.domain.email_provider import EmailProvider
    from alert.domain.entities import EmailPreference
    from alert.infrastructure.clients.s1_client import S1Client
    from alert.infrastructure.clients.s3_client import S3MarketDataClient
    from alert.infrastructure.clients.s8_client import S8BriefingClient

logger = structlog.get_logger(__name__)

# Retry delays in seconds (exponential backoff: 1s → 2s → 4s between attempts)
_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)
_MAX_SEND_ATTEMPTS = len(_RETRY_DELAYS) + 1  # 4 total (1 initial + 3 retries)

_DIGEST_SUBJECT = "Your Weekly Portfolio Risk Digest"
_EMAIL_TYPE = "weekly_digest"


class EmailScheduler:
    """Orchestrates the weekly email digest per user.

    Args:
    ----
        session_factory: Write-side async session factory for alert_db.
        email_provider: Adapter implementing ``EmailProvider`` protocol.
        settings: Service settings (from_address, provider name, etc.).
        s1_client: S1 portfolio service client (for user email lookup).
        s3_client: S3 market data client (OHLCV + fundamentals).
        s8_client: S8 RAG/Chat client (AI narrative generation).

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        email_provider: EmailProvider,
        settings: Settings,
        s1_client: S1Client,
        s3_client: S3MarketDataClient,
        s8_client: S8BriefingClient,
    ) -> None:
        self._sf = session_factory
        self._email_provider = email_provider
        self._settings = settings
        self._s1 = s1_client
        self._s3 = s3_client
        self._s8 = s8_client

    async def run(self) -> None:
        """Run the digest scheduler for the current UTC day and hour.

        Queries ``email_preferences`` for users scheduled at
        ``(weekday, hour)`` and processes each sequentially.
        """
        now = utc_now()
        day_of_week: int = now.weekday()  # Monday=0, Sunday=6
        hour_utc: int = now.hour

        async with self._sf() as session:
            repo = EmailPreferenceRepository(session)
            prefs = await repo.list_scheduled_users(day_of_week, hour_utc)

        logger.info(  # type: ignore[no-any-return]
            "email_scheduler.run_started",
            day=day_of_week,
            hour=hour_utc,
            user_count=len(prefs),
        )

        for pref in prefs:
            try:
                await self._process_user(pref)
            except Exception:
                logger.exception(  # type: ignore[no-any-return]
                    "email_scheduler.user_processing_error",
                    user_id=str(pref.user_id),
                )

        logger.info(  # type: ignore[no-any-return]
            "email_scheduler.run_completed",
            day=day_of_week,
            hour=hour_utc,
            user_count=len(prefs),
        )

    async def _process_user(self, pref: EmailPreference) -> None:
        """Orchestrate one user's digest: resolve address → fetch data → send."""
        user_id = pref.user_id
        tenant_id = pref.tenant_id

        # ── 1. Resolve delivery address ──────────────────────────────────────
        email_address = pref.email_address
        if not email_address:
            email_address = await self._s1.get_user_email(str(user_id))
            if not email_address:
                logger.warning(  # type: ignore[no-any-return]
                    "email_scheduler.skip_no_email",
                    user_id=str(user_id),
                )
                await self._log_skipped(user_id, tenant_id)
                return

        # ── 2. Fetch market data (best-effort) ───────────────────────────────
        # entity_ids would normally come from the portfolio context; for the
        # stub pass empty list (Wave D-2 wires in real portfolio data)
        entity_ids: list[UUID] = []
        market_snapshots: list[dict[str, Any]] = []
        if entity_ids:
            ohlcv = await self._s3.get_ohlcv_bulk(entity_ids)
            fundamentals = await self._s3.get_fundamentals(entity_ids)
            # Merge into market_snapshots list (full merging done in Wave D-2)
            market_snapshots = ohlcv + fundamentals

        # ── 3. Request AI narrative (best-effort — degrade on S8 failure) ───
        portfolio_context: dict[str, Any] = {}
        narrative = ""
        briefing: dict[str, Any] | None = None
        try:
            raw = await self._s8.request_briefing(
                user_id=user_id,
                tenant_id=tenant_id,
                portfolio_context=portfolio_context,
                market_snapshots=market_snapshots,
            )
            # M-05: guard against non-dict responses (e.g. None or error string)
            if isinstance(raw, dict):
                briefing = raw
                narrative = str(briefing.get("narrative", ""))
        except BriefingClientError:
            logger.warning(  # type: ignore[no-any-return]
                "email_scheduler.s8_briefing_unavailable",
                user_id=str(user_id),
            )

        # ── 4. Render email (full template — Wave D-2) ──────────────────────
        risk_summary = briefing.get("risk_summary", {}) if briefing is not None else {}
        citations = briefing.get("citations", []) if briefing is not None else []
        html_body, text_body = render_digest_email(
            narrative=narrative,
            risk_summary=risk_summary if isinstance(risk_summary, dict) else {},
            citations=citations if isinstance(citations, list) else [],
            positions=[],  # Wave D-2+: populated from S1 portfolio context
            fundamentals=[],  # Wave D-2+: populated from S3 fundamentals data
        )

        # ── 5. Send with exponential-backoff retry + outbox event ───────────
        await self._send_with_retry(user_id, tenant_id, email_address, html_body, text_body)

    async def _log_skipped(self, user_id: UUID, tenant_id: UUID) -> None:
        """Insert a single 'skipped' email_log row (no outbox event needed)."""
        now = utc_now()
        row = EmailLogModel(
            log_id=new_uuid7(),
            user_id=user_id,
            tenant_id=tenant_id,
            email_type=_EMAIL_TYPE,
            sent_at=now,
            provider=self._settings.email_provider,
            status="skipped",
            error_detail="no_email_address",
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()

    async def _send_with_retry(
        self,
        user_id: UUID,
        tenant_id: UUID,
        email_address: str,
        html_body: str,
        text_body: str,
    ) -> None:
        """Outbox-first send with exponential-backoff retry.

        Pattern (B-01):
          1. Write ``pending_send`` log entry atomically BEFORE attempting send.
          2. Attempt send up to ``_MAX_SEND_ATTEMPTS`` times.
          3a. Success → UPDATE log to ``sent`` + INSERT outbox event + UPDATE
              ``email_preferences.last_digest_sent_at`` in one transaction.
          3b. Exhausted → UPDATE log to ``failed`` in one transaction.

        This means every attempted send is always visible, enabling crash
        detection and retry by an operator or a future recovery job.
        """
        log_id = new_uuid7()
        await self._create_pending_log(log_id, user_id, tenant_id)

        last_error: str = ""
        for attempt in range(_MAX_SEND_ATTEMPTS):
            try:
                msg_id = await self._email_provider.send(
                    to=email_address,
                    subject=_DIGEST_SUBJECT,
                    html_body=html_body,
                    text_body=text_body,
                    from_address=self._settings.email_from_address,
                )
                await self._finalize_sent(log_id, user_id, tenant_id, msg_id)
                logger.info(  # type: ignore[no-any-return]
                    "email_scheduler.digest_sent",
                    user_id=str(user_id),
                    attempt=attempt + 1,
                )
                return
            except EmailProviderError as exc:
                last_error = str(exc)
                logger.warning(  # type: ignore[no-any-return]
                    "email_scheduler.send_attempt_failed",
                    user_id=str(user_id),
                    attempt=attempt + 1,
                    error=last_error,
                )
                if attempt < len(_RETRY_DELAYS):
                    await asyncio.sleep(_RETRY_DELAYS[attempt])

        # All attempts exhausted
        await self._finalize_failed(log_id, user_id, tenant_id, last_error)
        logger.error(  # type: ignore[no-any-return]
            "email_scheduler.digest_failed",
            user_id=str(user_id),
            error=last_error,
        )

    # ── Outbox-first transaction helpers ────────────────────────────────────

    async def _create_pending_log(self, log_id: Any, user_id: UUID, tenant_id: UUID) -> None:
        """Step 1: INSERT pending_send row before attempting the send."""
        now = utc_now()
        row = EmailLogModel(
            log_id=log_id,
            user_id=user_id,
            tenant_id=tenant_id,
            email_type=_EMAIL_TYPE,
            sent_at=now,
            provider=self._settings.email_provider,
            status="pending_send",
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()

    async def _finalize_sent(
        self,
        log_id: Any,
        user_id: UUID,
        tenant_id: UUID,
        provider_message_id: str | None,
    ) -> None:
        """Step 3a: UPDATE log to 'sent' + INSERT outbox + UPDATE last_digest_sent_at atomically."""
        now = utc_now()
        now_iso = now.isoformat()
        event_id = str(new_uuid7())
        payload = serialize_email_sent(
            event_id=event_id,
            user_id=user_id,
            tenant_id=tenant_id,
            email_type=_EMAIL_TYPE,
            provider=self._settings.email_provider,
            sent_at=now_iso,
            subject=_DIGEST_SUBJECT,
            occurred_at=now_iso,
            provider_message_id=provider_message_id,
        )
        async with self._sf() as session:
            await session.execute(
                update(EmailLogModel)
                .where(EmailLogModel.log_id == log_id)
                .values(status="sent", updated_at=now, provider_message_id=provider_message_id)
            )
            session.add(
                OutboxEventModel(
                    event_id=new_uuid7(),
                    topic=EMAIL_SENT_TOPIC,
                    partition_key=str(user_id),
                    payload_avro=payload,
                )
            )
            await session.execute(
                update(EmailPreferenceModel)
                .where(EmailPreferenceModel.user_id == user_id)
                .values(last_digest_sent_at=now)
            )
            await session.commit()

    async def _finalize_failed(
        self,
        log_id: Any,
        user_id: UUID,
        tenant_id: UUID,
        error_detail: str,
    ) -> None:
        """Step 3b: UPDATE log to 'failed' so retry tooling can detect it."""
        now = utc_now()
        async with self._sf() as session:
            await session.execute(
                update(EmailLogModel)
                .where(EmailLogModel.log_id == log_id)
                .values(status="failed", updated_at=now, error_detail=error_detail)
            )
            await session.commit()
