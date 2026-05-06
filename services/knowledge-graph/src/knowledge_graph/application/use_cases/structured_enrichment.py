"""StructuredEnrichmentUseCase — Worker 13J enrichment orchestration (PRD-0073 §9.5).

Three-source cascade per entity:
  Step 1: S3 market-data existing DB data (GET /instruments/lookup?extra_info=true)
  Step 2: S3 on-demand EODHD profile (GET /instruments/on-demand-profile) — only for
          financial_instrument / company when Step 1 found no description
  Step 3: LLM description generation — only when description still absent after Steps 1-2,
          OR when entity_type is person / concept / location / event

R25 3-phase pattern:
  Phase 1: read entity (caller already has the CanonicalEntity; no session needed)
  Phase 2: external HTTP calls (Steps 1-3) — NO DB session held during I/O
  Phase 3: DB write (Steps 5-7) — open session, write, commit, close

entity.dirtied.v1 produced AFTER commit (PRD-0073 §10.1 Step 8).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.domain.enrichment_result import (
    EnrichmentResult,
    EnrichmentSource,
    compute_data_completeness,
)
from knowledge_graph.domain.errors import FatalEnrichmentError, RetryableEnrichmentError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.domain.models import CanonicalEntity
    from knowledge_graph.infrastructure.http.market_data_client import MarketDataClient
    from knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter import (
        EntityEnrichmentAdapter,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Entity types for which S3/EODHD enrichment is attempted (hot-path types)
_STRUCTURED_TYPES: frozenset[str] = frozenset({"financial_instrument", "company"})

# Entity types for which LLM is ALWAYS called (no S3/EODHD coverage)
_LLM_ONLY_TYPES: frozenset[str] = frozenset({"person", "concept", "location", "event"})

# Minimum description length to accept an LLM response (PRD-0073 §13.5)
_MIN_DESCRIPTION_LEN = 20

# LLM call timeout in seconds (NFR-02)
_LLM_TIMEOUT_S = 25.0


class DirectProducerProtocol(Protocol):
    """Port for emitting entity.dirtied.v1 after enrichment.

    The concrete implementation handles Avro serialisation in the infrastructure
    layer.  The use case only calls ``produce_entity_dirtied`` — it never builds
    bytes or imports from ``messaging.*``.
    """

    def produce_entity_dirtied(self, *, entity_id: UUID, reason: str) -> None: ...


class DescriptionLlmClientProtocol(Protocol):
    """Minimal protocol for description LLM calls.

    Concrete implementations: DeepInfraDescriptionAdapter, NullDescriptionAdapter.
    """

    async def generate_description(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        context_hints: dict[str, str],
    ) -> str | None: ...


class StructuredEnrichmentUseCase:
    """Orchestrate single-entity enrichment (Worker 13J — PRD-0073 §9.5).

    Args:
        enrichment_adapter: Port implementation for DB reads and writes.
        market_data_client: HTTP client for the two S3 endpoints.
        description_client: LLM description generator (Step 3).
        session_factory:    async_sessionmaker for Phase 3 DB writes.
        direct_producer:    Optional port for entity.dirtied.v1 emission after commit.
    """

    def __init__(
        self,
        enrichment_adapter: EntityEnrichmentAdapter,
        market_data_client: MarketDataClient,
        description_client: DescriptionLlmClientProtocol,
        session_factory: async_sessionmaker[AsyncSession],
        direct_producer: DirectProducerProtocol | None = None,
    ) -> None:
        self._adapter = enrichment_adapter
        self._mdc = market_data_client
        self._llm = description_client
        self._sf = session_factory
        self._producer = direct_producer

    async def enrich(self, entity: CanonicalEntity) -> EnrichmentResult:
        """Run the full enrichment cascade for a single entity.

        Returns an EnrichmentResult (source=NONE when no description could be
        obtained, but the result is still written to update enrichment_attempts).

        Raises:
            RetryableEnrichmentError: Transient failure (HTTP 429, LLM timeout).
                enrichment_attempts is NOT incremented.
            FatalEnrichmentError: Non-retryable failure (LLM < 20 chars, bad response).
                Caller must increment enrichment_attempts.
        """
        if entity.enrichment_attempts >= 3:
            logger.info(  # type: ignore[no-any-return]
                "enrichment_skipped_max_attempts",
                entity_id=str(entity.entity_id),
                enrichment_attempts=entity.enrichment_attempts,
            )
            return EnrichmentResult(
                entity_id=entity.entity_id,
                description=None,
                metadata={},
                data_completeness=0.0,
                enriched_at=utc_now(),
                source=EnrichmentSource.NONE,
                seeded_relations=[],
            )

        logger.debug(  # type: ignore[no-any-return]
            "enrichment_started",
            entity_id=str(entity.entity_id),
            entity_type=entity.entity_type,
        )

        description: str | None = None
        metadata: dict[str, object] = {}
        source = EnrichmentSource.NONE

        # ------------------------------------------------------------------
        # Phase 2 — external I/O (no DB session held)
        # ------------------------------------------------------------------

        # Step 1: S3 DB lookup (only for structured entity types)
        if entity.entity_type in _STRUCTURED_TYPES:
            try:
                payload = await self._mdc.lookup(
                    ticker=entity.ticker,
                    isin=entity.isin,
                    entity_id=entity.entity_id,
                )
                if payload:
                    description = payload.get("description") or None  # type: ignore[assignment]
                    metadata = _extract_metadata(payload)
                    if description:
                        source = EnrichmentSource.MARKET_DATA
                        logger.info(  # type: ignore[no-any-return]
                            "enrichment_market_data_hit",
                            entity_id=str(entity.entity_id),
                            description_length=len(description),
                        )
            except Exception as exc:
                # Transient connectivity issue — fall through to Step 2
                logger.warning(  # type: ignore[no-any-return]
                    "enrichment_market_data_miss",
                    entity_id=str(entity.entity_id),
                    reason=type(exc).__name__,
                )

            # Step 2: S3 on-demand profile (EODHD) — only when description still absent
            if not description:
                try:
                    od_payload = await self._mdc.on_demand_profile(
                        ticker=entity.ticker,
                        isin=entity.isin,
                    )
                    if od_payload:
                        description = od_payload.get("description") or None  # type: ignore[assignment]
                        _merge(metadata, _extract_metadata(od_payload))
                        if description:
                            source = EnrichmentSource.EODHD
                            logger.info(  # type: ignore[no-any-return]
                                "enrichment_eodhd_hit",
                                entity_id=str(entity.entity_id),
                                sector=metadata.get("sector"),
                                industry=metadata.get("industry"),
                            )
                except Exception as exc:
                    import httpx  # late import to avoid infra dep at module level

                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                        raise RetryableEnrichmentError("EODHD rate limit (429)") from exc
                    # Other errors (404 already handled as None return from client) — continue
                    logger.info(  # type: ignore[no-any-return]
                        "enrichment_eodhd_miss",
                        entity_id=str(entity.entity_id),
                        reason=type(exc).__name__,
                    )

        # Step 3: LLM description generation — conditional
        need_llm = (description is None) or (entity.entity_type in _LLM_ONLY_TYPES)
        if need_llm:
            context_hints: dict[str, str] = {}
            if metadata.get("sector"):
                context_hints["sector"] = str(metadata["sector"])
            if metadata.get("country"):
                context_hints["country"] = str(metadata["country"])

            try:
                llm_description = await asyncio.wait_for(
                    self._llm.generate_description(
                        entity_id=str(entity.entity_id),
                        canonical_name=entity.canonical_name,
                        entity_type=entity.entity_type,
                        context_hints=context_hints,
                    ),
                    timeout=_LLM_TIMEOUT_S,
                )

                if llm_description and len(llm_description) >= _MIN_DESCRIPTION_LEN:
                    description = llm_description
                    source = EnrichmentSource.LLM
                    logger.info(  # type: ignore[no-any-return]
                        "enrichment_llm_success",
                        entity_id=str(entity.entity_id),
                        description_length=len(description),
                    )
                elif llm_description is not None:
                    # Response too short — non-retryable (PRD-0073 §13.5)
                    raise FatalEnrichmentError(
                        f"LLM description too short ({len(llm_description)} chars) for " f"entity {entity.entity_id}"
                    )
            except TimeoutError as exc:
                raise RetryableEnrichmentError("LLM timed out") from exc
            except FatalEnrichmentError:
                raise
            except RetryableEnrichmentError:
                raise
            except Exception as exc:
                import httpx as _httpx

                if isinstance(exc, _httpx.HTTPStatusError) and exc.response.status_code == 429:
                    raise RetryableEnrichmentError("LLM rate limit (429)") from exc
                if isinstance(exc, _httpx.HTTPStatusError) and exc.response.status_code in (503, 502):
                    raise RetryableEnrichmentError(f"LLM unavailable ({exc.response.status_code})") from exc
                # Other LLM errors treated as non-retryable for this attempt
                logger.warning(  # type: ignore[no-any-return]
                    "enrichment_llm_failure",
                    entity_id=str(entity.entity_id),
                    error_type=type(exc).__name__,
                )
                raise FatalEnrichmentError(f"LLM failed: {exc}") from exc

        # ------------------------------------------------------------------
        # Phase 3 — DB write (open session, write, commit, close)
        # ------------------------------------------------------------------
        data_completeness = compute_data_completeness(entity.entity_type, description, metadata)

        async with self._sf() as session:
            seeded = await self._adapter.seed_relations(entity.entity_id, metadata, session)

            result = EnrichmentResult(
                entity_id=entity.entity_id,
                description=description,
                metadata=metadata,
                data_completeness=data_completeness,
                enriched_at=utc_now(),
                source=source,
                seeded_relations=seeded,
            )
            await self._adapter.write_enrichment_result(result, session)
            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "enrichment_complete",
            entity_id=str(entity.entity_id),
            data_completeness=data_completeness,
            source=source.value,
            seeded_relations_count=len(seeded),
        )

        # Step 8 — produce entity.dirtied.v1 post-commit (best-effort)
        if self._producer is not None:
            try:
                self._producer.produce_entity_dirtied(
                    entity_id=entity.entity_id,
                    reason="enrichment_updated",
                )
            except Exception:
                logger.error(  # type: ignore[no-any-return]
                    "enrichment_dirtied_produce_failed",
                    entity_id=str(entity.entity_id),
                    exc_info=True,
                )

        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_metadata(payload: dict[str, Any]) -> dict[str, object]:
    """Extract enrichment metadata fields from an S3 instrument response."""
    return {
        k: payload.get(k)
        for k in (
            "sector",
            "industry",
            "country",
            "exchange",
            "isin",
            "ticker",
            "currency_code",
            "employee_count",
            "founded_year",
            "headquarters_city",
            "headquarters_country",
        )
        if payload.get(k) is not None
    }


def _merge(base: dict[str, object], extra: dict[str, object]) -> None:
    """Merge extra into base; existing non-None values are not overwritten."""
    for k, v in extra.items():
        if k not in base or base[k] is None:
            base[k] = v
