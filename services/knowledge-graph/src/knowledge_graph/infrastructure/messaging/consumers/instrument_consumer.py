"""Consumer 13D-4: Instrument entity creation (PRD §6.7 Block 13D-4).

Consumer group: ``kg-instrument-group``.
Consumes: ``market.instrument.created``.

Processing:
  1. Create canonical_entity from instrument metadata.
  2. Insert mechanical aliases: ticker, exchange:ticker, canonical_name, ISIN.
  3. Call ExtractionClient (FallbackChainClient) for LLM-generated supplementary
     aliases.  Collision check: reject alias if it belongs to a different entity.
  4. Ensure 3 entity_embedding_state rows exist.
  5. Embed description as definition view (if description available).
  6. Log to llm_usage_log.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

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

    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import EntityAliasRepository
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
    from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

logger = get_logger(__name__)  # type: ignore[no-any-return]


# Walk up the directory tree to find infra/kafka/schemas/ — works both in development
# (repo root is a few levels up) and in Docker (schemas copied to /app/infra/kafka/schemas/).
def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    return Path(__file__).parents[7] / "infra" / "kafka" / "schemas"


_SCHEMA_DIR = _find_schema_dir()


# ---------------------------------------------------------------------------
# Minimal no-op UoW (same pattern as existing consumers)
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


class InstrumentEntityConsumer(BaseKafkaConsumer[None]):
    """Creates canonical entities from ``market.instrument.created`` events.

    Args:
    ----
        config:           Consumer configuration.
        session_factory:  async_sessionmaker for intelligence_db.
        llm_client:       FallbackChainClient for alias generation + embedding.
        definition_worker: DefinitionRefreshWorker to trigger definition embed.
        dedup_client:     Optional Valkey dedup client.

    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        definition_worker: DefinitionRefreshWorker | None = None,
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._llm = llm_client
        self._def_worker = definition_worker
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg:inst:{config.group_id}"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Create canonical entity + aliases + embeddings for a new instrument."""

        instrument_id = UUID(str(value["instrument_id"]))
        ticker = value.get("ticker")
        exchange = value.get("exchange")
        isin = value.get("isin")
        description = value.get("description") or ""

        # Guard against None/empty names that would produce the string "None" as an alias,
        # causing uidx_entity_aliases_normalized collisions across multiple null-name instruments.
        raw_name = value.get("name")
        if raw_name and str(raw_name).strip() and str(raw_name).strip().lower() not in ("none", "null"):
            canonical_name = str(raw_name).strip()
        elif ticker:
            canonical_name = str(ticker).upper()
        else:
            canonical_name = f"Instrument-{str(instrument_id)[:8]}"

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
            EntityAliasRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            VIEW_DEFINITION,
            EntityEmbeddingStateRepository,
        )

        async with self._sf() as session:
            entity_repo = CanonicalEntityRepository(session)
            alias_repo = EntityAliasRepository(session)
            emb_repo = EntityEmbeddingStateRepository(session)

            # Idempotency: check if entity already created for this instrument
            existing = await entity_repo.get(instrument_id)
            if existing:
                entity_id_existing: UUID = existing["entity_id"]  # type: ignore[assignment]
                # Re-trigger embedding if entity exists but definition embedding is absent.
                # This handles replay after a crash between entity creation (step 4) and
                # embedding (step 5) — fixes BP-124.
                if description and self._def_worker:
                    emb_row = await emb_repo.get(entity_id_existing, VIEW_DEFINITION)
                    if emb_row is None or emb_row.get("model_id") is None:
                        await session.commit()  # flush any reads
                        await self._def_worker.refresh_for_entity(entity_id_existing, description)
                logger.debug(  # type: ignore[no-any-return]
                    "instrument_consumer_already_exists",
                    instrument_id=str(instrument_id),
                )
                return

            # Step 1: Create canonical entity
            entity_id = await entity_repo.create(  # type: ignore[attr-defined]
                canonical_name=canonical_name,
                entity_type="financial_instrument",
                ticker=str(ticker) if ticker else None,
                isin=str(isin) if isin else None,
                exchange=str(exchange) if exchange else None,
            )

            # Step 2: Mechanical aliases — use SAVEPOINTs so that a collision on one
            # alias rolls back only that nested transaction and leaves the outer session
            # intact.  contextlib.suppress alone would leave the session in an aborted
            # state and break the next INSERT (InFailedSQLTransactionError).
            async def _try_insert_alias(alias_text: str, normalized: str, alias_type: str) -> None:
                try:
                    async with session.begin_nested():
                        await alias_repo.insert(entity_id, alias_text, normalized, alias_type, "instrument_consumer")
                except Exception:  # noqa: S110
                    pass  # SAVEPOINT rolled back; outer transaction remains usable

            normalized_name = canonical_name.lower().strip()
            await _try_insert_alias(canonical_name, normalized_name, "EXACT")

            if ticker:
                t = str(ticker).upper()
                await _try_insert_alias(t, t, "TICKER")
                if exchange:
                    exc_ticker = f"{exchange}:{ticker}".upper()
                    await _try_insert_alias(exc_ticker, exc_ticker, "TICKER")

            if isin:
                i = str(isin).upper()
                await _try_insert_alias(i, i, "ISIN")

            # Step 3: LLM-generated supplementary aliases
            await self._add_llm_aliases(entity_id, canonical_name, ticker, description, alias_repo, session)

            # Step 4: Ensure embedding_state rows (3 for financial_instrument)
            await emb_repo.ensure_rows_exist(entity_id, "financial_instrument")
            await session.commit()

        # Step 5: Embed description as definition view (outside main txn)
        if description and self._def_worker:
            await self._def_worker.refresh_for_entity(entity_id, description)

        logger.info(  # type: ignore[no-any-return]
            "instrument_entity_created",
            instrument_id=str(instrument_id),
            entity_id=str(entity_id),
            canonical_name=canonical_name,
        )

    async def _add_llm_aliases(
        self,
        entity_id: UUID,
        canonical_name: str,
        ticker: Any,
        description: str,
        alias_repo: EntityAliasRepository,
        session: Any,
    ) -> None:
        """Generate and validate LLM alias suggestions."""
        from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-untyped]
        from prompts.knowledge.alias import ALIAS_GENERATION  # type: ignore[import-untyped]

        inp = ExtractionInput(
            prompt=ALIAS_GENERATION.render(name=canonical_name, ticker=str(ticker)),
            context=description[:500],
            output_schema={"aliases": "list[string]"},
            model_id="kg-alias-gen-v1",
        )
        result = await self._llm.extract(inp, entity_id=entity_id)
        if result is None:
            return

        llm_aliases: list[str] = result.result.get("aliases") or []
        for alias in llm_aliases[:5]:
            normalized = alias.lower().strip()
            existing = await alias_repo.find_exact(normalized)
            if existing and existing["entity_id"] != entity_id:
                logger.warning(  # type: ignore[no-any-return]
                    "instrument_consumer_alias_collision",
                    alias=alias,
                    entity_id=str(entity_id),
                )
                continue
            try:
                async with session.begin_nested():
                    await alias_repo.insert(entity_id, alias, normalized, "LLM", "instrument_consumer")
            except Exception:  # noqa: S110
                pass  # SAVEPOINT rolled back; outer transaction remains usable

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def is_duplicate(self, event_id: str) -> bool:
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        return bool(await self._dedup_client.exists(key))

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        await self._dedup_client.set(key, "1", ex=86400)

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "instrument_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "instrument_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "instrument_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "instrument_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Confluent Avro bytes, falling back to JSON if no schema or deserialization fails."""
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
        """Return the canonical Avro schema path for the given topic, or None."""
        path = _SCHEMA_DIR / f"{topic}.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
