"""EntityRepository — write-oriented canonical entity operations for EODHD enrichment.

Complements :class:`CanonicalEntityRepository` (read-only) with mutation
operations used by EODHD enrichment workers (Wave B-1/B-3/B-4).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class InstrumentRecord(NamedTuple):
    """Minimal canonical_entities projection for US-listed instruments (Worker 13D-8)."""

    entity_id: UUID
    ticker: str
    canonical_name: str


class EntityRepository:
    """Write-oriented repository for ``canonical_entities`` in intelligence_db.

    Provides partial metadata patch and entity upsert operations used by
    EODHD enrichment workers (FundamentalsConsumer, MacroIndicatorWorker,
    InsiderTransactionsWorker).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def update_metadata(
        self,
        entity_id: UUID,
        updates: dict[str, object],
    ) -> None:
        """Partially patch ``canonical_entities.metadata`` — merges, does not replace.

        Uses PostgreSQL JSONB ``||`` operator: existing keys not present in *updates*
        are preserved; new keys are added; existing keys in *updates* are overwritten.
        No-op if the entity does not exist.

        Args:
            entity_id: Target canonical entity UUID.
            updates:   Key/value pairs to merge into the existing metadata JSONB.
        """
        await self._session.execute(
            text("""
UPDATE canonical_entities
SET metadata = COALESCE(metadata, '{}'::jsonb) || cast(:updates AS jsonb)
WHERE entity_id = :entity_id
"""),
            {
                "entity_id": str(entity_id),
                "updates": json.dumps(updates),
            },
        )

    async def get_metadata_hash(self, entity_id: UUID, key: str) -> str | None:
        """Return the SHA-256 hex digest of ``metadata[key]`` for *entity_id*.

        Fetches the JSONB value at ``metadata->>'key'`` (text form), re-serialises
        it with ``sort_keys=True`` for a deterministic hash, and returns the
        SHA-256 hex digest.

        Returns ``None`` when the entity does not exist or the key is absent.
        This allows callers to treat a missing key the same as a first-time write
        (hash mismatch → update triggered).

        Args:
            entity_id: Target canonical entity UUID.
            key:       Top-level key inside the ``metadata`` JSONB column.
        """
        result = await self._session.execute(
            text("""
SELECT metadata->>:key FROM canonical_entities
WHERE entity_id = :entity_id
"""),
            {"entity_id": str(entity_id), "key": key},
        )
        row = result.fetchone()
        if not row or row[0] is None:
            return None
        try:
            # Re-parse and re-serialise with sort_keys to get a deterministic hash
            # regardless of how Postgres serialised the JSONB internally.
            data = json.loads(row[0])
            canonical = json.dumps(data, sort_keys=True)
            return hashlib.sha256(canonical.encode()).hexdigest()
        except (json.JSONDecodeError, TypeError):
            return None

    async def find_country_entity(self, iso2: str) -> UUID | None:
        """Find the canonical entity_id for a country by ISO-3166 alpha-2 code.

        Looks up ``canonical_entities`` where ``entity_type = 'country'`` and
        ``metadata->>'country_iso' = :iso2``.

        Returns ``None`` if no country entity is found (e.g. the entity has not
        been seeded or the ISO-2 code is not tracked).

        Args:
            iso2: ISO-3166 alpha-2 country code (e.g. ``"US"``, ``"DE"``).
        """
        result = await self._session.execute(
            text("""
SELECT entity_id FROM canonical_entities
WHERE entity_type = 'country'
  AND metadata->>'country_iso' = :iso2
LIMIT 1
"""),
            {"iso2": iso2},
        )
        row = result.fetchone()
        return UUID(str(row[0])) if row else None

    async def list_us_instruments(self) -> list[InstrumentRecord]:
        """List all US-listed financial instruments tracked in canonical_entities.

        Filters on ``entity_type = 'financial_instrument'``, ``exchange = 'US'``,
        and ``ticker IS NOT NULL``.  Used by :class:`InsiderTransactionsWorker`
        to build the list of tickers to poll for SEC Form 4 filings.

        Returns:
            List of :class:`InstrumentRecord` sorted by canonical_name.
        """
        result = await self._session.execute(
            text("""
SELECT entity_id, ticker, canonical_name
FROM canonical_entities
WHERE entity_type = 'financial_instrument'
  AND exchange = 'US'
  AND ticker IS NOT NULL
ORDER BY canonical_name
"""),
        )
        rows = result.fetchall()
        return [
            InstrumentRecord(
                entity_id=UUID(str(row[0])),
                ticker=str(row[1]),
                canonical_name=str(row[2]),
            )
            for row in rows
        ]

    async def find_or_create_person(self, name: str, context_ticker: str) -> UUID:
        """Find or create a person canonical entity by name.

        Looks up ``canonical_entities`` where ``entity_type = 'person'`` and
        ``canonical_name = :name``.  If not found, inserts a new person entity
        with the given name and stores *context_ticker* in metadata.

        **Idempotency**: Two calls with the same *name* return the same
        entity_id (SELECT finds the existing row on the second call).

        Args:
            name:           Full name of the person (e.g. ``"Tim Cook"``).
            context_ticker: Ticker of the company where the person was discovered
                            (e.g. ``"AAPL"``); stored as ``metadata["context_ticker"]``.

        Returns:
            The ``entity_id`` of the found or created person entity.
        """
        from common.ids import new_uuid7  # type: ignore[import-untyped]

        # Try to find existing person by canonical_name
        result = await self._session.execute(
            text("""
SELECT entity_id FROM canonical_entities
WHERE entity_type = 'person'
  AND canonical_name = :name
LIMIT 1
"""),
            {"name": name},
        )
        row = result.fetchone()
        if row:
            return UUID(str(row[0]))

        # Create new person entity
        entity_id: UUID = new_uuid7()
        await self._session.execute(
            text("""
INSERT INTO canonical_entities (entity_id, entity_type, canonical_name, metadata)
VALUES (:entity_id, 'person', :name, cast(:metadata AS jsonb))
"""),
            {
                "entity_id": str(entity_id),
                "name": name,
                "metadata": json.dumps({"context_ticker": context_ticker}),
            },
        )
        return entity_id
