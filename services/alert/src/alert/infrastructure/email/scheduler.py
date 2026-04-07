"""Email digest scheduler for the Alert service (S10).

``EmailScheduler.run()`` is called once per UTC hour by the
``scheduler_main`` entrypoint.  It queries ``email_preferences`` for users
whose ``send_day_of_week`` + ``send_hour_utc`` match the current UTC
day/hour, then orchestrates the per-user digest flow:

  1. Resolve delivery address (preferences override → S1 fallback).
  2. Fetch OHLCV + fundamentals from S3 (best-effort).
  3. Request AI narrative from S8 (best-effort — send partial on failure).
  4. Render HTML/plain template stub (full template implemented in Wave D-2).
  5. Send via email provider with exponential-backoff retry (3 attempts).
  6. Insert ``email_log`` row (status: sent | failed | skipped).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from alert.domain.email_provider import EmailProviderError
from alert.infrastructure.clients.s8_client import BriefingClientError
from alert.infrastructure.db.models import EmailLogModel, OutboxEventModel
from alert.infrastructure.db.repositories.email_preference import EmailPreferenceRepository
from alert.infrastructure.email.template import render_digest_email
from alert.infrastructure.messaging.schemas.email_sent import EMAIL_SENT_TOPIC, serialize_email_sent
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
            user_info = await self._resolve_user_email(user_id)
            if not user_info:
                logger.warning(  # type: ignore[no-any-return]
                    "email_scheduler.skip_no_email",
                    user_id=str(user_id),
                )
                await self._log_result(user_id, tenant_id, "skipped", error_detail="no_email_address")
                return
            email_address = user_info

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
            briefing = await self._s8.request_briefing(
                user_id=user_id,
                tenant_id=tenant_id,
                portfolio_context=portfolio_context,
                market_snapshots=market_snapshots,
            )
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

    async def _resolve_user_email(self, user_id: UUID) -> str | None:
        """Fetch user email from S1 via ``GET /internal/v1/users/{user_id}``
        (endpoint added in Wave E-1). Returns None when S1 is unavailable.
        """
        return await self._fetch_user_email_direct(user_id)

    async def _fetch_user_email_direct(self, user_id: UUID) -> str | None:
        """Call GET /internal/v1/users/{user_id} on S1 to get the email address."""
        import httpx

        url = f"{self._s1._base_url}/internal/v1/users/{user_id}"
        try:
            resp = await self._s1._client.get(
                url,
                headers={"X-Internal-Token": self._settings.s1_internal_token},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return str(data.get("email_address", "")) or None
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning(  # type: ignore[no-any-return]
                "email_scheduler.s1_user_lookup_failed",
                user_id=str(user_id),
                error=str(exc),
            )
            return None

    async def _send_with_retry(
        self,
        user_id: UUID,
        tenant_id: UUID,
        email_address: str,
        html_body: str,
        text_body: str,
    ) -> None:
        """Attempt email send up to ``_MAX_SEND_ATTEMPTS`` times.

        On success: inserts email_log with status='sent'.
        On all attempts exhausted: inserts email_log with status='failed'.
        """
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
                await self._log_result(user_id, tenant_id, "sent", provider_message_id=msg_id)
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

        # All attempts exhausted — log failure, no outbox event (send never succeeded)
        await self._log_result(user_id, tenant_id, "failed", error_detail=last_error)
        logger.error(  # type: ignore[no-any-return]
            "email_scheduler.digest_failed",
            user_id=str(user_id),
            error=last_error,
        )

    async def _log_result(
        self,
        user_id: UUID,
        tenant_id: UUID,
        status: str,
        *,
        provider_message_id: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        """Insert email_log + outbox event (on success) in a single transaction.

        For status='sent' an ``alert.email.sent.v1`` outbox row is written
        atomically alongside the log row — this is the transactional outbox
        pattern (no dual-write risk).
        """
        now = utc_now()
        row = EmailLogModel(
            log_id=new_uuid7(),
            user_id=user_id,
            tenant_id=tenant_id,
            email_type=_EMAIL_TYPE,
            sent_at=now,
            provider=self._settings.email_provider,
            provider_message_id=provider_message_id,
            status=status,
            error_detail=error_detail,
        )
        async with self._sf() as session:
            session.add(row)
            if status == "sent":
                event_id = str(new_uuid7())
                now_iso = now.isoformat()
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
                outbox_row = OutboxEventModel(
                    event_id=new_uuid7(),
                    topic=EMAIL_SENT_TOPIC,
                    partition_key=str(user_id),
                    payload_avro=payload,
                )
                session.add(outbox_row)
            await session.commit()
