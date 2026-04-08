"""Worker 13D-7: EODHD Macro Indicator Enrichment (PRD-0018 §6 Worker 13D-7).

APScheduler weekly job at 03:00 UTC on Sundays.

Fetches 6 World Bank macro indicators per country from the EODHD endpoint
``GET /macro-indicator/{ISO3_COUNTRY}?indicator={code}&fmt=json``, compares
the result against the stored JSON hash in the entity's metadata, and updates
``entity.metadata["macro_indicators"]`` only when data has changed.

Produces ``entity.dirtied.v1`` for each country entity whose indicators
changed, triggering re-embedding in the S6 DefinitionRefreshWorker.

Note: The Macro Indicator API uses **ISO 3166-1 alpha-3** codes (USA, GBR,
DEU, JPN, CHN) — different from the Economic Events API which uses alpha-2.
The constructor accepts a ``country_map`` of iso3 → iso2 pairs so that the
found country canonical entity can be located via its ``country_iso``
alpha-2 metadata field.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.metrics.prometheus import s7_macro_indicator_updates_total
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.eodhd.client import EodhDClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

# World Bank indicator codes fetched per country
MACRO_INDICATORS: tuple[str, ...] = (
    "gdp_current_usd",
    "gdp_growth_annual",
    "inflation_consumer_prices_annual",
    "real_interest_rate",
    "unemployment_total_pct",
    "current_account_balance_bop_usd",
)


class MacroIndicatorWorker:
    """Worker 13D-7: Enrich country entity metadata with World Bank macro indicators.

    Runs weekly on Sunday at 03:00 UTC. Indicators are annual data; a weekly
    refresh is sufficient to capture new World Bank data releases without
    unnecessary EODHD API calls.

    Idempotency: JSON hash comparison prevents unnecessary ``update_metadata``
    calls and ``entity.dirtied.v1`` events when indicators are unchanged.

    Args:
        session_factory:      async_sessionmaker for intelligence_db (read/write).
        eodhd_client:         Initialised :class:`EodhDClient` instance.
        country_map:          Mapping of ISO-3166 alpha-3 → alpha-2 codes
                              (e.g. ``{"USA": "US", "GBR": "GB", "DEU": "DE"}``).
        direct_producer:      Optional direct Kafka producer for entity.dirtied.v1.
        entity_dirtied_topic: Topic name for entity.dirtied.v1 events.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        eodhd_client: EodhDClient,
        country_map: dict[str, str],
        direct_producer: Any | None = None,
        entity_dirtied_topic: str = "entity.dirtied.v1",
    ) -> None:
        self._sf = session_factory
        self._eodhd = eodhd_client
        self._country_map = country_map
        self._producer = direct_producer
        self._dirtied_topic = entity_dirtied_topic

    async def run(self) -> None:
        """Execute one full weekly macro indicator refresh cycle."""
        total_updated = 0

        for iso3, iso2 in self._country_map.items():
            try:
                updated = await self._process_country(iso3, iso2)
            except Exception:
                logger.error(  # type: ignore[no-any-return]
                    "macro_indicator_worker_country_failed",
                    iso3=iso3,
                    iso2=iso2,
                    exc_info=True,
                )
                continue
            if updated:
                s7_macro_indicator_updates_total.labels(country=iso2).inc()
                total_updated += 1

        logger.info(  # type: ignore[no-any-return]
            "macro_indicator_worker_complete",
            countries=list(self._country_map.keys()),
            total_updated=total_updated,
        )

    # ── Per-country processing ────────────────────────────────────────────────

    async def _process_country(self, iso3: str, iso2: str) -> bool:
        """Fetch and update macro indicators for one country.

        Returns ``True`` if indicators were updated; ``False`` if unchanged or skipped.
        """
        macro_data: dict[str, Any] = {}

        for indicator_code in MACRO_INDICATORS:
            result = await self._eodhd.get_macro_indicator(iso3, indicator_code)
            if result:
                # Results are sorted by date descending — index 0 is most recent
                latest = result[0]
                macro_data[indicator_code] = {
                    "value": latest.get("Value"),
                    "year": latest.get("Period"),
                }

        if not macro_data:
            logger.debug(  # type: ignore[no-any-return]
                "macro_indicator_worker_no_data",
                iso3=iso3,
                iso2=iso2,
            )
            return False

        country_entity_id: UUID | None = None
        updated = False

        async with self._sf() as session:
            from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
                EntityRepository,
            )

            entity_repo = EntityRepository(session)

            country_entity_id = await entity_repo.find_country_entity(iso2)
            if country_entity_id is None:
                logger.debug(  # type: ignore[no-any-return]
                    "macro_indicator_worker_country_entity_missing",
                    iso3=iso3,
                    iso2=iso2,
                )
                return False

            new_hash = _sha256_hex(json.dumps(macro_data, sort_keys=True))
            old_hash = await entity_repo.get_metadata_hash(country_entity_id, "macro_indicators")

            if old_hash == new_hash:
                logger.debug(  # type: ignore[no-any-return]
                    "macro_indicator_worker_no_change",
                    iso3=iso3,
                    iso2=iso2,
                    entity_id=str(country_entity_id),
                )
                return False

            await entity_repo.update_metadata(country_entity_id, {"macro_indicators": macro_data})
            await session.commit()
            updated = True

        # Produce entity.dirtied.v1 outside DB session — best-effort, non-blocking
        if updated and self._producer is not None and country_entity_id is not None:
            self._producer.produce_bytes(
                topic=self._dirtied_topic,
                key=str(country_entity_id).encode(),
                value=json.dumps(
                    {
                        "event_id": str(new_uuid7()),
                        "event_type": "entity.dirtied",
                        "schema_version": 1,
                        "occurred_at": utc_now().isoformat(),
                        "entity_id": str(country_entity_id),
                        "dirty_reason": "macro_indicators_updated",
                        "source_doc_id": None,
                        "correlation_id": None,
                    }
                ).encode(),
            )
            logger.info(  # type: ignore[no-any-return]
                "macro_indicator_worker_updated",
                iso3=iso3,
                iso2=iso2,
                entity_id=str(country_entity_id),
                indicators=list(macro_data.keys()),
            )

        return updated


# ── Helpers ───────────────────────────────────────────────────────────────────


def _sha256_hex(s: str) -> str:
    """Return the SHA-256 hex digest of the UTF-8 encoded string *s*."""
    return hashlib.sha256(s.encode()).hexdigest()
