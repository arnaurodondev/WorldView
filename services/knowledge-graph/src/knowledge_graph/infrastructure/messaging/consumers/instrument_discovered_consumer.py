"""Consumer 13D-4b: Lightweight canonical entity creation from market.instrument.discovered.v1.

PLAN-0057 Wave D-2.  Closes audit finding F-CRIT-12 (placeholder canonicals
like ``Instrument-019dbbdb...``).

Consumer group: ``kg-instrument-discovered-group``.
Consumes:       ``market.instrument.discovered.v1``.

What it does:
  1. UPSERT a *lightweight* canonical entity using ``instrument_id`` as
     ``entity_id`` (so the existing ``InstrumentEntityConsumer`` will later
     find it by primary key when fundamentals enrichment arrives).
       - ``canonical_name = symbol`` (placeholder; replaced when
         fundamentals arrives with the real EODHD ``Name``)
       - ``entity_type   = 'financial_instrument'``
       - ``ticker        = symbol``
       - ``exchange      = exchange``
       - ``isin          = NULL``
       - ``metadata      = {"source":"discovered","needs_fundamentals_enrichment":true,
                            "discovered_at":"<iso>"}``
       - ON CONFLICT (entity_id) DO NOTHING — idempotent on replay.
  2. Insert EXACT alias for ``symbol`` (idempotent via the partial UNIQUE
     index ``uidx_entity_aliases_entity_norm_type``).
  3. Insert TICKER alias for ``symbol`` (same).
  4. Ensure ``entity_embedding_state`` rows exist (3 rows for
     financial_instrument: definition, narrative, fundamentals_ohlcv;
     ``next_refresh_at = now()`` so workers pick them up immediately).
  5. NO LLM alias generation here — there is no description yet.
     The downstream ``InstrumentEntityConsumer`` runs the LLM step when
     fundamentals_consumer eventually emits ``market.instrument.created``
     for this same instrument_id (see Wave D-2 T-D-2-05 UPSERT-after-discover
     semantics).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sqlalchemy import text

from common.time import to_iso8601, utc_now  # type: ignore[import-untyped]
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


# ── Schema directory discovery — same pattern as instrument_consumer.py ────
def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    return Path(__file__).parents[7] / "infra" / "kafka" / "schemas"


_SCHEMA_DIR = _find_schema_dir()


# ---------------------------------------------------------------------------
# Minimal no-op UoW (consumer manages its own session via session_factory)
# ---------------------------------------------------------------------------
class _NoOpUoW:
    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------
class InstrumentDiscoveredConsumer(BaseKafkaConsumer[None]):
    """Materialises a lightweight canonical entity for every newly-discovered instrument.

    Args:
    ----
        config:           Consumer configuration (group_id, topics, bootstrap servers).
        session_factory:  async_sessionmaker for intelligence_db.
        dedup_client:     Optional Valkey dedup client (idempotency cache).

    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg:inst-discovered:{config.group_id}"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------
    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Create a lightweight canonical entity + 2 aliases + 3 embedding rows."""
        instrument_id = UUID(str(value["instrument_id"]))
        symbol_raw = value.get("symbol")
        if not symbol_raw or not str(symbol_raw).strip():
            # Without a symbol we have no placeholder canonical_name and no
            # alias text — refuse to create a "garbage" canonical.  This is
            # treated as malformed: caller's MalformedDataError handling will
            # dead-letter it.
            from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

            raise MalformedDataError(
                "market.instrument.discovered.v1: missing or empty 'symbol' — "
                "cannot create lightweight canonical without a placeholder name"
            )
        symbol = str(symbol_raw).strip()
        exchange = value.get("exchange")
        # Placeholder canonical_name = symbol; real EODHD Name overrides this when
        # fundamentals_consumer emits market.instrument.created → InstrumentEntityConsumer
        # runs the UPSERT-after-discover branch (T-D-2-05).
        canonical_name = symbol

        # Ticker uppercase normalisation matches existing instrument_consumer.py
        ticker_upper = symbol.upper()
        normalised_name = symbol.lower()

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        # Metadata for the lightweight canonical — stored as JSONB in canonical_entities.
        # ``needs_fundamentals_enrichment`` is the flag InstrumentEntityConsumer
        # will look up later to decide whether to UPSERT the real name.
        metadata: dict[str, object] = {
            "source": "discovered",
            "needs_fundamentals_enrichment": True,
            "discovered_at": to_iso8601(utc_now()),
        }

        async with self._sf() as session:
            # Step 1: UPSERT canonical entity with explicit entity_id = instrument_id.
            # We use raw SQL here (rather than CanonicalEntityRepository.create) because
            # the repo's create() does not accept a passed-in entity_id; it relies on
            # the table's gen_random_uuid() default.  Setting entity_id explicitly is
            # essential so the existing InstrumentEntityConsumer can find this row
            # later via entity_repo.get(instrument_id) (idempotency lookup keyed by
            # primary key).  ON CONFLICT (entity_id) DO NOTHING keeps replays cheap
            # and prevents overwriting an already-enriched canonical.
            await session.execute(
                text("""
INSERT INTO canonical_entities (entity_id, canonical_name, entity_type, ticker, exchange, isin, metadata)
VALUES (:entity_id, :canonical_name, 'financial_instrument', :ticker, :exchange, NULL, :metadata)
ON CONFLICT (entity_id) DO NOTHING
"""),
                {
                    "entity_id": str(instrument_id),
                    "canonical_name": canonical_name,
                    "ticker": ticker_upper,
                    "exchange": str(exchange) if exchange else None,
                    "metadata": json.dumps(metadata),
                },
            )

            # Step 2 + 3: Insert EXACT and TICKER aliases for the symbol.
            # ON CONFLICT against the partial UNIQUE index added by Wave A-2
            # (uidx_entity_aliases_entity_norm_type ON (entity_id, normalized_alias_text,
            # alias_type) WHERE is_active = true).  We must repeat the index's
            # WHERE clause for Postgres to use the partial index as the conflict
            # arbiter — same pattern as canonical_entity.create (Wave C-5).
            #
            # We wrap each insert in a SAVEPOINT so a constraint conflict on one
            # alias does not abort the outer transaction (matches the pattern in
            # instrument_consumer.py).
            async def _try_insert_alias(alias_text: str, normalized: str, alias_type: str) -> None:
                try:
                    async with session.begin_nested():
                        await session.execute(
                            text("""
INSERT INTO entity_aliases
    (entity_id, alias_text, normalized_alias_text, alias_type, is_active, source)
VALUES (:eid, :alias, :norm, :atype, true, 'instrument_discovered_consumer')
ON CONFLICT (entity_id, normalized_alias_text, alias_type)
WHERE is_active = true
DO NOTHING
"""),
                            {
                                "eid": str(instrument_id),
                                "alias": alias_text,
                                "norm": normalized,
                                "atype": alias_type,
                            },
                        )
                except Exception:  # noqa: S110
                    # SAVEPOINT rolled back; outer transaction remains usable.
                    pass

            await _try_insert_alias(canonical_name, normalised_name, "EXACT")
            await _try_insert_alias(ticker_upper, ticker_upper, "TICKER")

            # Step 4: Ensure embedding-state rows for financial_instrument.
            # The repo decides which view types to insert based on entity_type
            # (financial_instrument → 3 rows; others → 2 rows).
            emb_repo = EntityEmbeddingStateRepository(session)
            await emb_repo.ensure_rows_exist(instrument_id, "financial_instrument")

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "instrument_discovered_canonical_seeded",
            instrument_id=str(instrument_id),
            symbol=symbol,
            exchange=exchange,
        )

    # ------------------------------------------------------------------
    # Idempotency (Valkey-cached event_id; same pattern as instrument_consumer.py)
    # ------------------------------------------------------------------
    async def is_duplicate(self, event_id: str) -> bool:
        # PLAN-0057 QA DS-003 / F-DATA-08 fix: Valkey errors must NOT block
        # the consumer.  Canonical/alias inserts are protected by ON CONFLICT
        # DO NOTHING (defence-in-depth), so reprocessing a duplicate event is
        # safe.  Previously a Valkey hiccup raised → propagated to
        # _handle_failure → eventually dead-lettered the event, despite the
        # underlying writes being idempotent.  Fail OPEN here instead.
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            return bool(await self._dedup_client.exists(key))
        except Exception as exc:  # pragma: no cover — exercised by Valkey outage tests
            logger.warning(  # type: ignore[no-any-return]
                "instrument_discovered_consumer_dedup_check_unavailable",
                event_id=event_id,
                error=str(exc),
                note="failing open — canonical/alias writes are idempotent",
            )
            return False

    async def mark_processed(self, event_id: str) -> None:
        # Same fail-open semantics as is_duplicate: a missed mark just means
        # the next delivery will re-execute the idempotent INSERTs, not that
        # data is lost or corrupted.
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            await self._dedup_client.set(key, "1", ex=86400)
        except Exception as exc:  # pragma: no cover
            logger.warning(  # type: ignore[no-any-return]
                "instrument_discovered_consumer_mark_processed_unavailable",
                event_id=event_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------
    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "instrument_discovered_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "instrument_discovered_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "instrument_discovered_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "instrument_discovered_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Confluent Avro; fall back to JSON for tooling/tests."""
        if schema_path:
            try:
                return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
            except Exception:
                logger.debug(  # type: ignore[no-any-return]
                    "avro_deserialize_failed_falling_back_to_json",
                    schema_path=schema_path,
                )
        return cast("dict[str, Any]", json.loads(raw))

    def get_schema_path(self, topic: str) -> str | None:
        """Return the canonical Avro schema path for the topic, or None."""
        # Topic ``market.instrument.discovered.v1`` → schema file
        # ``market.instrument.discovered.v1.avsc``.
        path = _SCHEMA_DIR / f"{topic}.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
