"""Worker 13D-6: EODHD Economic Events Ingestion (PRD-0018 §6 Worker 13D-6).

APScheduler daily job at 06:00 UTC.

Polls ``GET /economic-events`` for each configured country, skips unreleased
events (``actual=null``), computes surprise magnitude, and upserts structured
macro events into ``temporal_events`` as ``event_type=MACRO, scope=NATIONAL``.

Each event is linked to the country's canonical entity via
``entity_event_exposures`` (exposure_type='directly_affected').

Natural-key deduplication prevents duplicate rows across daily runs:
    ``(event_type='macro', region=country, title, active_from::date)``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.domain.enums import EventScope, EventType, ExposureType
from knowledge_graph.infrastructure.metrics.prometheus import s7_economic_events_ingested_total
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.eodhd.client import EodhDClient
    from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
        EntityEventExposureRepository,
        TemporalEventRepository,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Macro events have a 30-day residual impact window
_RESIDUAL_IMPACT_DAYS = 30

# Structured EODHD data carries full confidence (no NLP uncertainty)
_EODHD_CONFIDENCE = 1.0


class EconomicEventsWorker:
    """Worker 13D-6: Poll EODHD Economic Events API and upsert into temporal_events.

    Runs daily at 06:00 UTC (markets closed overnight; prior-day events available).
    Each country in *countries* is processed independently — one EODHD request per country.

    Args:
        session_factory: async_sessionmaker for intelligence_db (read/write).
        eodhd_client:    Initialised :class:`EodhDClient` instance.
        countries:       List of ISO-3166 alpha-2 codes to poll (e.g. ``["US", "DE"]``).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        eodhd_client: EodhDClient,
        countries: list[str],
    ) -> None:
        self._sf = session_factory
        self._eodhd = eodhd_client
        self._countries = countries

    async def run(self) -> None:
        """Execute one full daily poll cycle across all configured countries."""
        from datetime import timedelta

        today = utc_now().date()  # type: ignore[no-any-return]
        yesterday = today - timedelta(days=1)

        total_ingested = 0

        for country in self._countries:
            try:
                ingested = await self._process_country(country, yesterday, today)
            except Exception:
                logger.error(  # type: ignore[no-any-return]
                    "economic_events_worker_country_failed",
                    country=country,
                    exc_info=True,
                )
                continue
            s7_economic_events_ingested_total.labels(country=country).inc(ingested)
            total_ingested += ingested

        logger.info(  # type: ignore[no-any-return]
            "economic_events_worker_complete",
            countries=self._countries,
            total_ingested=total_ingested,
        )

    # ── Per-country processing ────────────────────────────────────────────────

    async def _process_country(
        self,
        country: str,
        from_date: date,
        to_date: date,
    ) -> int:
        """Fetch and upsert economic events for one country.

        Returns the number of events successfully upserted.
        """

        events = await self._eodhd.get_economic_events(
            country=country,
            from_date=from_date,
            to_date=to_date,
        )

        if not events:
            logger.debug(  # type: ignore[no-any-return]
                "economic_events_worker_no_events",
                country=country,
                from_date=str(from_date),
            )
            return 0

        ingested = 0

        async with self._sf() as session:
            from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
                EntityRepository,
            )
            from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
                EntityEventExposureRepository,
                TemporalEventRepository,
            )

            event_repo = TemporalEventRepository(session)
            exposure_repo = EntityEventExposureRepository(session)
            entity_repo = EntityRepository(session)

            country_entity_id = await entity_repo.find_country_entity(country)
            if country_entity_id is None:
                logger.debug(  # type: ignore[no-any-return]
                    "economic_events_worker_country_entity_missing",
                    country=country,
                )

            for ev in events:
                upserted = await self._upsert_event(
                    ev=ev,
                    country=country,
                    event_repo=event_repo,
                    exposure_repo=exposure_repo,
                    country_entity_id=country_entity_id,
                )
                if upserted:
                    ingested += 1

            await session.commit()

        return ingested

    async def _upsert_event(
        self,
        ev: dict[str, Any],
        country: str,
        event_repo: TemporalEventRepository,
        exposure_repo: EntityEventExposureRepository,
        country_entity_id: UUID | None,
    ) -> bool:
        """Process a single EODHD economic event dict.

        Returns ``True`` if the event was upserted; ``False`` if skipped.

        Skips events where ``actual`` is ``None`` (unreleased scheduled events).
        """
        from datetime import timedelta

        actual = ev.get("actual")
        if actual is None:
            return False  # Unreleased event — skip

        # Build event title (unique natural key component)
        ev_type = str(ev.get("type", "Economic Event"))
        period = str(ev.get("period", ""))
        title = f"{ev_type} ({country}) — {period}"
        if len(title) > 500:
            title = title[:497] + "..."

        # Build description with surprise magnitude
        previous = ev.get("previous")
        description_parts = [f"Actual: {actual}, Previous: {previous}"]

        estimate = ev.get("estimate")
        if estimate is not None:
            try:
                surprise = float(actual) - float(estimate)
                direction = "beat" if surprise > 0 else "missed"
                change_pct = ev.get("change_percentage")
                if change_pct is not None:
                    description_parts.append(f"Estimate {direction} by {abs(surprise):.2f} ({float(change_pct):.1f}%)")
                else:
                    description_parts.append(f"Estimate {direction} by {abs(surprise):.2f}")
            except (TypeError, ValueError):
                pass

        description = "; ".join(description_parts)

        # Parse event date — skip if unparseable
        active_from = _parse_event_date(str(ev.get("date", "")))
        if active_from is None:
            logger.warning(  # type: ignore[no-any-return]
                "economic_events_worker_invalid_date",
                country=country,
                raw_date=ev.get("date"),
            )
            return False

        active_until = active_from + timedelta(hours=24)

        event_id = new_uuid7()
        # Capture the returned db_event_id — on conflict this is the EXISTING row's
        # UUID, not the freshly-generated one. The exposure FK must reference the
        # canonical DB event_id to avoid a ForeignKeyViolationError on re-runs.
        db_event_id = await event_repo.upsert_by_natural_key(
            event_id=event_id,
            event_type=EventType.MACRO,
            scope=EventScope.NATIONAL,
            region=country,
            title=title,
            description=description,
            active_from=active_from,
            active_until=active_until,
            residual_impact_days=_RESIDUAL_IMPACT_DAYS,
            confidence=_EODHD_CONFIDENCE,
        )

        # Link to the country's canonical entity (if found)
        if country_entity_id is not None:
            exposure_id = new_uuid7()
            await exposure_repo.upsert(
                exposure_id=exposure_id,
                event_id=db_event_id,
                entity_id=country_entity_id,
                exposure_type=ExposureType.DIRECTLY_AFFECTED,
                confidence=_EODHD_CONFIDENCE,
            )

        logger.debug(  # type: ignore[no-any-return]
            "economic_events_worker_event_upserted",
            country=country,
            title=title,
        )
        return True


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_event_date(date_str: str) -> Any | None:
    """Parse an EODHD date string to a UTC-aware datetime.

    Accepts ISO-8601 with or without time component.
    Returns ``None`` if the string cannot be parsed.
    """
    from datetime import UTC, datetime

    if not date_str:
        return None
    # Try full ISO-8601 datetime first, then date-only
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str[:19], fmt)  # noqa: DTZ007
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
