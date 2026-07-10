"""Port interfaces for TemporalEvent and EntityEventExposure repositories (PRD-0018 §6.2-§6.4).

Use cases and workers depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from uuid import UUID


class TemporalEventRepositoryPort(ABC):
    """Port for temporal event upsert and query operations (S7 — PRD-0018 §6.4).

    Concrete implementations live in the infrastructure layer.
    """

    @abstractmethod
    async def upsert_by_natural_key(
        self,
        *,
        event_id: UUID,
        event_type: str,
        scope: str,
        region: str | None,
        title: str,
        active_from: datetime,
        confidence: float,
        description: str | None = None,
        source_article_ids: list[str] | None = None,
        source_url: str | None = None,
        active_until: datetime | None = None,
        residual_impact_days: int = 90,
    ) -> UUID:
        """Upsert a temporal event using the natural deduplication key.

        Natural key: ``(event_type, region, title, date_trunc('day', timezone('UTC', active_from)))``.
        On conflict: updates description, scope, active_until, residual_impact_days,
        confidence, and source_url; leaves event_id, event_type, region, title,
        active_from, and created_at unchanged.

        Region must be ``None`` (not empty string) for events without a region tag.
        The Avro consumer must convert ``""`` → ``None`` before calling this method.

        Args:
        ----
            event_id:             App-generated UUIDv7 identifier.
            event_type:           One of geopolitical/regulatory/macro/sanctions/
                                  natural_disaster/other.
            scope:                One of LOCAL/REGIONAL/NATIONAL/GLOBAL.
            region:               ISO-3166 alpha-2 or special tag (EU, APAC, etc.);
                                  None for LOCAL events.
            title:                Short event title (max 500 chars).
            active_from:          UTC-aware event start datetime.
            confidence:           0.0-1.0.
            description:          Narrative; for MACRO includes surprise magnitude.
            source_article_ids:   CanonicalDocument UUIDs (empty for EODHD events).
            source_url:           Primary source or EODHD API reference.
            active_until:         UTC-aware end datetime; None = still active.
            residual_impact_days: Days of residual impact after end (default 90).

        Returns:
        -------
            The event_id of the inserted or updated row.

        """

    @abstractmethod
    async def list_active(
        self,
        *,
        scope: str | None = None,
        entity_id: UUID | None = None,
        active_only: bool = True,
        event_type: str | None = None,
        region: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        """List temporal events with flexible filters (PRD-0018 §6.3).

        Args:
        ----
            scope:       Filter by EventScope string (LOCAL/REGIONAL/NATIONAL/GLOBAL).
            entity_id:   If set, only events where this entity is in entity_event_exposures.
            active_only: If True (default), exclude EXPIRED events.
            event_type:  Filter by event_type string.
            region:      Filter by region tag (ISO-3166 alpha-2 or special value).
            from_date:   Events with active_from >= this date.
            to_date:     Events with active_from <= this date.
            limit:       Page size (1-200).
            offset:      Pagination offset (≥ 0).

        Returns:
        -------
            Tuple of (rows, total_count) where:
            - rows: dicts with all temporal_events columns + ``exposed_entity_count``
            - total_count: total matching rows (ignoring limit/offset)

        """


class EntityEventExposureRepositoryPort(ABC):
    """Port for entity-event exposure link operations (PRD-0018 §6.4).

    Records which entities are exposed to which temporal events and how.
    """

    @abstractmethod
    async def upsert(
        self,
        *,
        exposure_id: UUID,
        event_id: UUID,
        entity_id: UUID,
        exposure_type: str,
        confidence: float,
        evidence_text: str | None = None,
        polarity: str | None = None,
        polarity_confidence: float | None = None,
    ) -> UUID:
        """Upsert an entity-event exposure link — ON CONFLICT DO NOTHING.

        Unique constraint: ``(event_id, entity_id, exposure_type)``.
        If a row already exists for the triple, the call is a no-op and
        the existing exposure_id is returned.

        Args:
        ----
            exposure_id:   App-generated UUIDv7 identifier.
            event_id:      FK → temporal_events.event_id.
            entity_id:     Logical FK → canonical_entities.entity_id.
            exposure_type: One of directly_affected/operationally_impacted/
                           supply_chain/revenue_geography/sector_exposure.
            confidence:    0.0-1.0.
            evidence_text: Optional extracted evidence snippet.
            polarity:      Directional signal for prediction-event exposures —
                           one of 'bullish'/'bearish'/'neutral', or None for
                           non-directional exposures (earnings/corporate). Added
                           by PLAN-0056 Wave C2 on top of migration 0066;
                           populated by the Wave C3 polarity classifier.
            polarity_confidence: Confidence [0,1] of the polarity, or None.

        Returns:
        -------
            The exposure_id of the existing or newly created row.

        """
