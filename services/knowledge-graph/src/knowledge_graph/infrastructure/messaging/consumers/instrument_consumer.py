"""Consumer 13D-4: Instrument entity creation (PRD §6.7 Block 13D-4).

Consumer group: ``kg-instrument-group``.
Consumes: ``market.instrument.created``.

Processing:
  1. Create canonical_entity from instrument metadata.
     PLAN-0057 Wave D-2: if a placeholder canonical already exists (created
     by InstrumentDiscoveredConsumer with metadata.needs_fundamentals_enrichment
     = true), UPDATE it with the real EODHD ``Name``/``ISIN``/description and
     clear the flag — then proceed with rich alias enrichment as if the
     canonical were brand new.
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


def _utc_iso_now() -> str:
    """Return the current UTC time as an ISO-8601 string.  Used to stamp
    ``metadata.enriched_at`` on the canonical_entity when transitioning from
    a discovered placeholder to an enriched record (PLAN-0057 Wave D-2).
    """
    return to_iso8601(utc_now())


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
        # PLAN-0057 QA-iter1 F-DATA-01: the Avro schema (market.instrument.created.avsc)
        # only carries `symbol`; legacy code read `value.get("ticker")` which has always
        # been None, silently neutering the TICKER/exchange-TICKER mechanical alias paths
        # downstream. We accept either spelling for forward-compat with any future
        # producer that sets `ticker` explicitly, but fall back to `symbol` (the schema
        # field) which is what every real producer actually emits.
        ticker = value.get("ticker") or value.get("symbol")
        exchange = value.get("exchange")
        isin = value.get("isin")
        description = value.get("description") or ""
        # PLAN-0057 Wave C-3: extra EODHD identifiers from InstrumentCreated v3.
        # Each may be absent on producers that pre-date v3 (Avro defaults them
        # to ``None``) so we just .get() them safely.
        cusip = value.get("cusip")
        figi = value.get("figi")
        lei = value.get("lei")
        primary_ticker = value.get("primary_ticker")

        # Guard against None/empty names that would produce the string "None" as an alias,
        # causing uidx_entity_aliases_normalized collisions across multiple null-name instruments.
        raw_name = value.get("name")
        # PLAN-0057 Wave D-3 (F-CRIT-12.E.3): track whether the canonical name is
        # *synthesised* (i.e. we had no real EODHD ``name`` and had to fall back
        # to the ticker upper-case OR the ``Instrument-{8hex}`` placeholder).
        # When synthesised we still create the canonical row (downstream services
        # need an entity), but we MUST NOT publish the synthesised string as an
        # EXACT alias — otherwise lookups would resolve unrelated mentions to
        # the placeholder and pollute the entity-resolution index.
        _stripped_name = str(raw_name).strip() if raw_name else ""
        synthesised_name = not (_stripped_name and _stripped_name.lower() not in ("none", "null"))
        if not synthesised_name:
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

            # Idempotency / UPSERT-after-discover (PLAN-0057 Wave D-2):
            # If a placeholder canonical exists (created earlier by
            # InstrumentDiscoveredConsumer with
            # metadata.needs_fundamentals_enrichment = true), UPDATE it with
            # the real EODHD Name/ISIN/description and clear the flag.  Then
            # FALL THROUGH to the alias-enrichment block — every rich alias
            # (NAME / ISIN / CUSIP / FIGI / LEI / PRIMARY_TICKER / LLM) needs
            # to be inserted exactly once on the create-OR-discovery path.
            # If the canonical exists AND is NOT a placeholder, we treat it
            # as a true replay and re-trigger missing definition embeddings
            # only (the BP-124 path).
            existing = await entity_repo.get(instrument_id)
            entity_id: UUID
            if existing:
                metadata_existing = existing.get("metadata") or {}
                needs_enrichment = isinstance(metadata_existing, dict) and bool(
                    metadata_existing.get("needs_fundamentals_enrichment")
                )
                if needs_enrichment:
                    # Lightweight canonical → real one.  We use raw SQL (not the
                    # repo) because CanonicalEntityRepository is read-mostly and
                    # this very specific UPDATE shape is not part of its API.
                    # The metadata jsonb minus key '-' operator removes the
                    # ``needs_fundamentals_enrichment`` flag while preserving the
                    # ``source`` and ``discovered_at`` audit fields.
                    await session.execute(
                        text("""
UPDATE canonical_entities
SET
    canonical_name = :canonical_name,
    isin           = COALESCE(:isin, isin),
    metadata       = (COALESCE(metadata, '{}'::jsonb) - 'needs_fundamentals_enrichment')
                     || jsonb_build_object('enriched_at', :enriched_at)
WHERE entity_id = :entity_id
  AND metadata->>'needs_fundamentals_enrichment' = 'true'
"""),
                        {
                            "entity_id": str(instrument_id),
                            "canonical_name": canonical_name,
                            "isin": str(isin) if isin else None,
                            "enriched_at": _utc_iso_now(),
                        },
                    )
                    # Continue to step 2 (alias enrichment) using existing entity_id
                    entity_id = instrument_id
                else:
                    entity_id_existing: UUID = existing["entity_id"]  # type: ignore[assignment]
                    # Re-trigger embedding if entity exists but definition embedding
                    # is absent — handles replay after a crash between entity creation
                    # (step 4) and embedding (step 5).  Fixes BP-124.
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
            else:
                # Step 1: Create canonical entity (pristine path — no prior discovery).
                # PLAN-0057 QA-iter1 F-DS-03 / F-DATA-04: pin entity_id to instrument_id
                # so the M-017 stable cross-service identifier invariant holds even on
                # backfills that hit fundamentals_consumer before any discovery.
                entity_id = await self._create_new_canonical(
                    entity_repo,
                    instrument_id=instrument_id,
                    canonical_name=canonical_name,
                    ticker=ticker,
                    isin=isin,
                    exchange=exchange,
                )

            # Continue with steps 2..5 below for BOTH the brand-new path and the
            # UPSERT-after-discover path so that the rich alias suite is inserted
            # exactly once.  The remaining code is intentionally unchanged from the
            # original create-only flow — per-alias inserts are wrapped in SAVEPOINTs
            # already, so re-running them on a discovered entity is safe (the partial
            # UNIQUE index added by Wave A-2 dedupes EXACT/TICKER aliases the
            # discovered consumer already inserted).

            # Step 2: Mechanical aliases — use SAVEPOINTs so that a collision on one
            # alias rolls back only that nested transaction and leaves the outer session
            # intact.  contextlib.suppress alone would leave the session in an aborted
            # state and break the next INSERT (InFailedSQLTransactionError).
            #
            # ``source`` is now an explicit argument so we can attribute each alias
            # to the right provenance (mechanical vs eodhd_general_name vs
            # eodhd_<identifier>) — see PLAN-0057 Wave C-3.
            async def _try_insert_alias(
                alias_text: str,
                normalized: str,
                alias_type: str,
                source: str = "instrument_consumer",
            ) -> None:
                try:
                    async with session.begin_nested():
                        await alias_repo.insert(entity_id, alias_text, normalized, alias_type, source)
                except Exception:  # noqa: S110
                    pass  # SAVEPOINT rolled back; outer transaction remains usable

            normalized_name = canonical_name.lower().strip()
            # PLAN-0057 Wave D-3 (F-CRIT-12.E.3): only insert the canonical as an
            # EXACT alias when the name is *real* — never publish the
            # ``Instrument-{8hex}`` placeholder or the bare ticker as a
            # public-facing EXACT alias because that would steer the resolver to
            # this placeholder for any mention sharing the synthesised text.
            if not synthesised_name:
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

            # ── PLAN-0057 Wave C-3 — Fix-A: NAME alias from EODHD General.Name ──
            # When the EODHD-supplied name is real and differs from whatever the
            # canonical happens to be (after our synthesis-vs-real choice
            # above), surface it as a separate ``NAME`` alias so the resolver
            # can match either form.  Skipping the case where it equals the
            # canonical avoids publishing a redundant EXACT-equivalent alias.
            if not synthesised_name and raw_name:
                eodhd_name = str(raw_name).strip()
                eodhd_norm = eodhd_name.lower()
                if eodhd_name and eodhd_norm != normalized_name:
                    await _try_insert_alias(eodhd_name, eodhd_norm, "NAME", "eodhd_general_name")

            # ── PLAN-0057 Wave C-3 — Fix-D.3: CUSIP / FIGI / LEI / PRIMARY_TICKER ──
            # Each EODHD identifier surfaces as its own alias_type so the resolver
            # and the frontend can render them as distinct pills.  Decision
            # (Checkpoint A 2026-04-30): ``PRIMARY_TICKER`` is its own dedicated
            # alias_type rather than reusing ``TICKER`` so Stage-2 of the
            # resolution cascade can opt-in selectively (see entity_resolution.py).
            for raw_value, alias_type in (
                (cusip, "CUSIP"),
                (figi, "FIGI"),
                (lei, "LEI"),
                (primary_ticker, "PRIMARY_TICKER"),
            ):
                if not raw_value:
                    continue
                value_str = str(raw_value).strip()
                if not value_str:
                    continue
                # Identifiers are conventionally rendered upper-case (CUSIP/FIGI/LEI
                # are already case-insensitive in practice; primary_ticker mirrors
                # TICKER convention).
                upper = value_str.upper()
                source = f"eodhd_{alias_type.lower()}"
                await _try_insert_alias(upper, upper, alias_type, source)

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

    async def _create_new_canonical(
        self,
        entity_repo: Any,
        *,
        instrument_id: UUID,
        canonical_name: str,
        ticker: Any,
        isin: Any,
        exchange: Any,
    ) -> UUID:
        """Insert a brand-new canonical_entity (pristine create path).

        Extracted into a helper so process_message can share Steps 2..5 with the
        UPSERT-after-discover path (PLAN-0057 Wave D-2). The canonical's
        ``entity_id`` is pinned to ``instrument_id`` so the M-017 stable
        cross-service identifier invariant holds (portfolio's InstrumentRef.id
        and KG's canonical_entities.entity_id agree). When discovery already
        seeded the canonical, the ON CONFLICT (entity_id) DO NOTHING clause in
        the repo absorbs the duplicate-PK race deterministically.
        """
        return await entity_repo.create(  # type: ignore[no-any-return]
            canonical_name=canonical_name,
            entity_type="financial_instrument",
            entity_id=instrument_id,
            ticker=str(ticker) if ticker else None,
            isin=str(isin) if isin else None,
            exchange=str(exchange) if exchange else None,
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
        """Generate and validate LLM alias suggestions.

        PLAN-0057 Wave C-4 (F-MAJOR-09): the prompt is now ALIAS_GENERATION v2.0
        which expects ``name``, ``ticker``, ``description`` and ``aliases_so_far``
        all as template parameters.  The description is now passed *into* the
        prompt itself (not via ``ExtractionInput.context``) because the v2 model
        client treats ``context`` as a separate retrieval-augmentation slot
        whereas this prompt needs the description inline as part of the
        instruction.  ``aliases_so_far`` is sourced from the mechanical-alias
        block we just ran (NAME / TICKER / ISIN / CUSIP / FIGI / LEI / PRIMARY_TICKER)
        so the LLM doesn't propose duplicates.
        """
        from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-untyped]
        from prompts.knowledge.alias import ALIAS_GENERATION  # type: ignore[import-untyped]

        # Build aliases_so_far from the existing entity_aliases rows (everything
        # the mechanical-alias block has just inserted).  Pass them in as a
        # comma-joined list so the LLM can avoid suggesting duplicates.  When
        # the lookup itself fails for any reason we fall back to an empty
        # string — the prompt still works, the LLM may just suggest dupes
        # which the dedup-via-find_exact below will discard.
        try:
            existing_rows = await alias_repo.get_for_entity(entity_id)
            aliases_so_far = ", ".join(str(row.get("alias_text", "")) for row in existing_rows if row.get("alias_text"))
        except Exception:
            aliases_so_far = ""

        # Truncate description to 500 chars to keep the prompt small (the model
        # only needs enough context to disambiguate the entity, not the full
        # company write-up).
        description_excerpt = description[:500] if description else ""

        inp = ExtractionInput(
            prompt=ALIAS_GENERATION.render(
                name=canonical_name,
                ticker=str(ticker) if ticker else "",
                description=description_excerpt,
                aliases_so_far=aliases_so_far,
            ),
            context="",  # description is now inline in the prompt itself
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
