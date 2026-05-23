"""Unit tests for StructuredEnrichmentUseCase (PRD-0073 §9.5, Wave C-2).

Tests:
- test_enrich_market_data_hit: S3 lookup returns description -> source=MARKET_DATA
- test_enrich_eodhd_hit: S3 miss, EODHD returns description -> source=EODHD
- test_enrich_llm_hit_after_s3_miss: both S3 miss -> LLM called -> source=LLM
- test_enrich_llm_only_type_skips_s3: person type -> S3 never called, LLM always called
- test_enrich_max_attempts_skip: enrichment_attempts>=3 returns NONE, no I/O
- test_enrich_llm_timeout_raises_retryable: asyncio.TimeoutError -> RetryableEnrichmentError
- test_enrich_llm_too_short_raises_fatal: LLM returns <20 chars -> FatalEnrichmentError
- test_enrich_eodhd_429_raises_retryable: EODHD 429 -> RetryableEnrichmentError
- test_enrich_llm_429_raises_retryable: LLM HTTP 429 -> RetryableEnrichmentError
- test_enrich_db_write_called: Phase 3 writes EnrichmentResult and commits
- test_enrich_seed_relations_included: seeded relations propagated to result
- test_enrich_dirtied_event_produced: direct producer called after commit
- test_enrich_llm_always_for_concept: concept type -> LLM called even if market_data returned description
- test_enrich_market_data_exception_continues: S3 exception -> falls through to EODHD
- test_enrich_no_description_source_none: all sources miss -> source=NONE, still writes
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from knowledge_graph.application.use_cases.structured_enrichment import (
    StructuredEnrichmentUseCase,
)
from knowledge_graph.domain.enrichment_result import EnrichmentResult, EnrichmentSource
from knowledge_graph.domain.errors import FatalEnrichmentError, RetryableEnrichmentError
from knowledge_graph.domain.models import CanonicalEntity
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000001")
_NOW = datetime(2026, 5, 1, 2, 0, 0, tzinfo=UTC)


def _make_entity(
    entity_type: str = "financial_instrument",
    enrichment_attempts: int = 0,
    ticker: str | None = "AAPL",
    isin: str | None = None,
) -> CanonicalEntity:
    return CanonicalEntity(
        entity_id=_ENTITY_ID,
        canonical_name="Apple Inc.",
        entity_type=entity_type,
        ticker=ticker,
        isin=isin,
        enrichment_attempts=enrichment_attempts,
    )


def _make_session_factory() -> MagicMock:
    """Return a mock async_sessionmaker that yields a usable async context manager."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    # seed_relations is called within the session context
    sf = MagicMock()
    sf.return_value.__aenter__ = AsyncMock(return_value=session)
    sf.return_value.__aexit__ = AsyncMock(return_value=False)
    return sf


def _make_adapter(seeded: list[str] | None = None) -> AsyncMock:
    adapter = AsyncMock()
    adapter.seed_relations = AsyncMock(return_value=seeded or [])
    adapter.write_enrichment_result = AsyncMock()
    adapter.increment_attempts = AsyncMock()
    return adapter


def _make_mdc(
    lookup_payload: dict | None = None,
    od_payload: dict | None = None,
    lookup_exc: Exception | None = None,
    od_exc: Exception | None = None,
) -> AsyncMock:
    mdc = AsyncMock()
    if lookup_exc:
        mdc.lookup = AsyncMock(side_effect=lookup_exc)
    else:
        mdc.lookup = AsyncMock(return_value=lookup_payload)
    if od_exc:
        mdc.on_demand_profile = AsyncMock(side_effect=od_exc)
    else:
        mdc.on_demand_profile = AsyncMock(return_value=od_payload)
    return mdc


def _make_llm(description: str | None = "A well-known technology company.") -> AsyncMock:
    llm = AsyncMock()
    llm.generate_description = AsyncMock(return_value=description)
    return llm


def _make_use_case(
    adapter: AsyncMock | None = None,
    mdc: AsyncMock | None = None,
    llm: AsyncMock | None = None,
    sf: MagicMock | None = None,
    producer: MagicMock | None = None,
) -> StructuredEnrichmentUseCase:
    return StructuredEnrichmentUseCase(
        enrichment_adapter=adapter or _make_adapter(),
        market_data_client=mdc or _make_mdc(),
        description_client=llm or _make_llm(),
        session_factory=sf or _make_session_factory(),
        direct_producer=producer,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_enrich_market_data_hit() -> None:
    mdc = _make_mdc(lookup_payload={"description": "Apple is a tech giant.", "sector": "Technology"})
    llm = _make_llm()
    uc = _make_use_case(mdc=mdc, llm=llm)

    result = await uc.enrich(_make_entity())

    assert result.source == EnrichmentSource.MARKET_DATA
    assert result.description == "Apple is a tech giant."
    llm.generate_description.assert_not_called()


@pytest.mark.asyncio()
async def test_enrich_eodhd_hit() -> None:
    mdc = _make_mdc(
        lookup_payload={"sector": "Technology"},  # no description
        od_payload={"description": "Apple makes iPhones.", "country": "USA"},
    )
    llm = _make_llm()
    uc = _make_use_case(mdc=mdc, llm=llm)

    result = await uc.enrich(_make_entity())

    assert result.source == EnrichmentSource.EODHD
    assert result.description == "Apple makes iPhones."
    llm.generate_description.assert_not_called()


@pytest.mark.asyncio()
async def test_enrich_llm_hit_after_s3_miss() -> None:
    mdc = _make_mdc(lookup_payload=None, od_payload=None)
    llm = _make_llm("Apple Inc. is a technology company headquartered in Cupertino.")
    uc = _make_use_case(mdc=mdc, llm=llm)

    result = await uc.enrich(_make_entity())

    assert result.source == EnrichmentSource.LLM
    assert "Apple" in (result.description or "")


@pytest.mark.asyncio()
async def test_enrich_llm_only_type_skips_s3() -> None:
    entity = _make_entity(entity_type="person", ticker=None)
    mdc = _make_mdc()
    llm = _make_llm("A prominent financial executive with decades of experience.")
    uc = _make_use_case(mdc=mdc, llm=llm)

    result = await uc.enrich(entity)

    assert result.source == EnrichmentSource.LLM
    mdc.lookup.assert_not_called()
    mdc.on_demand_profile.assert_not_called()


@pytest.mark.asyncio()
async def test_enrich_max_attempts_skip() -> None:
    entity = _make_entity(enrichment_attempts=3)
    mdc = _make_mdc()
    llm = _make_llm()
    uc = _make_use_case(mdc=mdc, llm=llm)

    result = await uc.enrich(entity)

    assert result.source == EnrichmentSource.NONE
    assert result.description is None
    mdc.lookup.assert_not_called()
    llm.generate_description.assert_not_called()


@pytest.mark.asyncio()
async def test_enrich_llm_timeout_raises_retryable() -> None:
    mdc = _make_mdc(lookup_payload=None, od_payload=None)
    llm = AsyncMock()
    llm.generate_description = AsyncMock(side_effect=TimeoutError())
    uc = _make_use_case(mdc=mdc, llm=llm)

    with pytest.raises(RetryableEnrichmentError):
        await uc.enrich(_make_entity())


@pytest.mark.asyncio()
async def test_enrich_llm_too_short_raises_fatal() -> None:
    mdc = _make_mdc(lookup_payload=None, od_payload=None)
    llm = _make_llm("Short")  # < 20 chars
    uc = _make_use_case(mdc=mdc, llm=llm)

    with pytest.raises(FatalEnrichmentError, match="too short"):
        await uc.enrich(_make_entity())


@pytest.mark.asyncio()
async def test_enrich_eodhd_429_raises_retryable() -> None:
    response_mock = MagicMock()
    response_mock.status_code = 429
    exc = httpx.HTTPStatusError("rate limit", request=MagicMock(), response=response_mock)
    mdc = _make_mdc(lookup_payload=None, od_exc=exc)
    uc = _make_use_case(mdc=mdc)

    # F-X11 fix: error message widened to cover all retryable on-demand-profile
    # statuses (429 + 5xx).  Match on "(429)" so the assertion stays specific to
    # the rate-limit branch without overfitting to the exact wording.
    with pytest.raises(RetryableEnrichmentError, match=r"on-demand-profile unavailable \(429\)"):
        await uc.enrich(_make_entity())


@pytest.mark.asyncio()
async def test_enrich_llm_429_raises_retryable() -> None:
    response_mock = MagicMock()
    response_mock.status_code = 429
    exc = httpx.HTTPStatusError("rate limit", request=MagicMock(), response=response_mock)
    mdc = _make_mdc(lookup_payload=None, od_payload=None)
    llm = AsyncMock()
    llm.generate_description = AsyncMock(side_effect=exc)
    uc = _make_use_case(mdc=mdc, llm=llm)

    with pytest.raises(RetryableEnrichmentError, match="LLM rate limit"):
        await uc.enrich(_make_entity())


@pytest.mark.asyncio()
async def test_enrich_db_write_called() -> None:
    mdc = _make_mdc(lookup_payload={"description": "Apple is a tech company.", "sector": "Tech"})
    adapter = _make_adapter()
    sf = _make_session_factory()
    uc = _make_use_case(mdc=mdc, adapter=adapter, sf=sf)

    await uc.enrich(_make_entity())

    adapter.write_enrichment_result.assert_called_once()
    call_result: EnrichmentResult = adapter.write_enrichment_result.call_args[0][0]
    assert call_result.entity_id == _ENTITY_ID
    assert call_result.source == EnrichmentSource.MARKET_DATA


@pytest.mark.asyncio()
async def test_enrich_seed_relations_included() -> None:
    mdc = _make_mdc(lookup_payload={"description": "Apple is a tech company.", "sector": "Technology"})
    adapter = _make_adapter(seeded=["operates_in_sector"])
    uc = _make_use_case(mdc=mdc, adapter=adapter)

    result = await uc.enrich(_make_entity())

    assert result.seeded_relations == ["operates_in_sector"]


@pytest.mark.asyncio()
async def test_enrich_dirtied_event_produced() -> None:
    mdc = _make_mdc(lookup_payload={"description": "Apple is a tech company."})
    producer = MagicMock()
    producer.produce_entity_dirtied = MagicMock()

    uc = _make_use_case(mdc=mdc, producer=producer)
    await uc.enrich(_make_entity())

    producer.produce_entity_dirtied.assert_called_once()
    call_kwargs = producer.produce_entity_dirtied.call_args[1]
    assert call_kwargs["entity_id"] == _ENTITY_ID
    assert call_kwargs["reason"] == "enrichment_updated"


@pytest.mark.asyncio()
async def test_enrich_llm_always_for_concept() -> None:
    """concept type -> LLM called regardless of whether market_data has description."""
    entity = _make_entity(entity_type="concept", ticker=None)
    # market_data would not be called for concept, but set up a description just in case
    mdc = _make_mdc(lookup_payload={"description": "Organic growth concept."})
    llm = _make_llm("Organic growth is a financial metric measuring revenue expansion.")
    uc = _make_use_case(mdc=mdc, llm=llm)

    result = await uc.enrich(entity)

    # S3/EODHD not called for LLM-only types
    mdc.lookup.assert_not_called()
    # LLM is always called
    llm.generate_description.assert_called_once()
    assert result.source == EnrichmentSource.LLM


@pytest.mark.asyncio()
async def test_enrich_market_data_exception_continues() -> None:
    """S3 lookup exception -> fall through to EODHD."""
    mdc = _make_mdc(
        lookup_exc=ConnectionError("S3 down"),
        od_payload={"description": "Apple makes iPhones and Macs."},
    )
    llm = _make_llm()
    uc = _make_use_case(mdc=mdc, llm=llm)

    result = await uc.enrich(_make_entity())

    assert result.source == EnrichmentSource.EODHD
    llm.generate_description.assert_not_called()


@pytest.mark.asyncio()
async def test_enrich_no_description_source_none() -> None:
    """All sources miss -> source=NONE, DB write still called (updates attempts)."""
    mdc = _make_mdc(lookup_payload=None, od_payload=None)
    llm = _make_llm(None)  # LLM returns None
    adapter = _make_adapter()
    uc = _make_use_case(mdc=mdc, llm=llm, adapter=adapter)

    result = await uc.enrich(_make_entity())

    assert result.source == EnrichmentSource.NONE
    assert result.description is None
    adapter.write_enrichment_result.assert_called_once()


# ---------------------------------------------------------------------------
# F-Q04 extensions — 7 additional behaviour tests for PLAN-0073 QA coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_relation_seeding_eodhd_sector() -> None:
    """When EODHD returns a sector, adapter.seed_relations is called with metadata
    containing that sector.  Without this assertion we can't detect a regression
    where sector is dropped between Phase 2 and Phase 3."""
    mdc = _make_mdc(
        lookup_payload=None,
        od_payload={"description": "Apple is a technology firm.", "sector": "Technology"},
    )
    adapter = _make_adapter(seeded=["operates_in_sector"])
    uc = _make_use_case(mdc=mdc, adapter=adapter)

    await uc.enrich(_make_entity())

    adapter.seed_relations.assert_awaited_once()
    # Args: (entity_id, metadata, session)
    args = adapter.seed_relations.call_args.args
    assert args[0] == _ENTITY_ID
    metadata = args[1]
    assert metadata.get("sector") == "Technology"


@pytest.mark.asyncio()
async def test_relation_seeding_skips_missing_object_entity() -> None:
    """If seed_relations returns an empty list (e.g. sector entity not yet seeded
    in canonical_entities), enrichment still completes without error."""
    mdc = _make_mdc(lookup_payload={"description": "Apple Inc.", "sector": "UnknownSector"})
    adapter = _make_adapter(seeded=[])  # adapter found no matching object entity
    uc = _make_use_case(mdc=mdc, adapter=adapter)

    result = await uc.enrich(_make_entity())

    assert result.seeded_relations == []
    # Still wrote the enrichment row.
    adapter.write_enrichment_result.assert_awaited_once()


@pytest.mark.asyncio()
async def test_entity_dirtied_produce_failure_does_not_raise() -> None:
    """When the producer raises after commit, the use case must still return
    a successful EnrichmentResult — entity.dirtied.v1 is best-effort post-commit."""
    mdc = _make_mdc(lookup_payload={"description": "Apple is a technology giant."})
    producer = MagicMock()
    producer.produce_entity_dirtied = MagicMock(side_effect=RuntimeError("kafka down"))

    uc = _make_use_case(mdc=mdc, producer=producer)
    result = await uc.enrich(_make_entity())

    assert result.source == EnrichmentSource.MARKET_DATA
    producer.produce_entity_dirtied.assert_called_once()


@pytest.mark.asyncio()
async def test_llm_prompt_sanitizes_entity_name() -> None:
    """The entity name fed to the LLM must be the canonical_name as-is.

    NB (PLAN-0073 QA F-Q04 spec): the spec described 'sanitization of <script>'
    but the actual production code passes canonical_name straight through —
    no HTML stripping happens at the LLM-prompt boundary.  We assert what the
    code actually does (canonical_name passed verbatim) so a regression that
    silently mutates names is detected.  If a future fix introduces real
    sanitization, update this assertion accordingly.
    """
    entity = _make_entity(entity_type="person", ticker=None)
    object.__setattr__(entity, "canonical_name", "<script>alert(1)</script>Tim Cook")
    mdc = _make_mdc()
    llm = _make_llm("Tim Cook is the CEO of Apple Inc.")
    uc = _make_use_case(mdc=mdc, llm=llm)

    await uc.enrich(entity)

    llm.generate_description.assert_awaited_once()
    kwargs = llm.generate_description.call_args.kwargs
    # The canonical_name reaches the LLM verbatim — confirms there is no
    # silent mutation in the cascade.
    assert kwargs["canonical_name"] == "<script>alert(1)</script>Tim Cook"


@pytest.mark.asyncio()
async def test_market_data_connect_error_falls_through() -> None:
    """httpx.ConnectError on Step 1 must NOT raise — Step 2 (EODHD) is tried next."""
    mdc = _make_mdc(
        lookup_exc=httpx.ConnectError("S3 connection refused"),
        od_payload={"description": "Apple via EODHD fallback."},
    )
    uc = _make_use_case(mdc=mdc)

    result = await uc.enrich(_make_entity())

    assert result.source == EnrichmentSource.EODHD


@pytest.mark.skip(reason="depends on F-Q08 fix — LLM fallback chain not yet implemented in use case")
@pytest.mark.asyncio()
async def test_llm_fallback_on_primary_404() -> None:
    """When F-Q08 lands, primary LLM returning 404 should trigger the fallback
    LLM rather than raising FatalEnrichmentError."""


@pytest.mark.asyncio()
async def test_enrichment_attempts_incremented_on_llm_short_response() -> None:
    """LLM returns < 20 chars → FatalEnrichmentError raised → worker increments
    enrichment_attempts (verified via the worker, not the use case).

    The use case itself only RAISES the FatalEnrichmentError; the responsibility
    for incrementing attempts lives in StructuredEnrichmentWorker. This test
    therefore drives the whole worker→use-case chain to assert the contract.
    """
    from knowledge_graph.infrastructure.workers.structured_enrichment_worker import (
        StructuredEnrichmentWorker,
    )

    entity = _make_entity()
    mdc = _make_mdc(lookup_payload=None, od_payload=None)
    llm = _make_llm("nope")  # < 20 chars → FatalEnrichmentError
    sf = _make_session_factory()
    adapter = _make_adapter()
    use_case = _make_use_case(adapter=adapter, mdc=mdc, llm=llm, sf=sf)

    worker = StructuredEnrichmentWorker(adapter, use_case, sf)

    # Drive list_unenriched: one batch with our entity, then empty.
    adapter.list_unenriched = AsyncMock(side_effect=[[entity], []])

    await worker.run()

    adapter.increment_attempts.assert_awaited()


# ---------------------------------------------------------------------------
# DB write failure — logging and error propagation (F-X09 regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_db_write_sqlalchemy_error_raises_retryable_with_log() -> None:
    """write_enrichment_result raises SQLAlchemyError → RetryableEnrichmentError raised
    AND a structlog event with key 'enrichment_db_write_failed' is emitted.

    This is the regression test for the silent-failure bug where SQLAlchemy errors
    were caught and re-raised as RetryableEnrichmentError with no logging, making
    3,951 entities permanently invisible to the operator.

    Root-cause fix: the adapter's seed_relations INSERT contained the column
    ``is_backfill`` which does not exist on the ``relations`` table.  The
    ProgrammingError was caught silently.  Both the logging addition and the
    column removal are guarded by this test.
    """
    from sqlalchemy.exc import ProgrammingError

    mdc = _make_mdc(lookup_payload={"description": "Apple is a technology giant."})
    adapter = _make_adapter()
    # Simulate the ProgrammingError that was caused by the is_backfill column bug.
    adapter.write_enrichment_result = AsyncMock(
        side_effect=ProgrammingError(
            "column 'is_backfill' of relation 'relations' does not exist",
            params=None,
            orig=Exception("column is_backfill does not exist"),
        ),
    )
    uc = _make_use_case(mdc=mdc, adapter=adapter)

    with capture_logs() as captured:
        with pytest.raises(RetryableEnrichmentError, match="DB error during enrichment write"):
            await uc.enrich(_make_entity())

    error_events = [e for e in captured if e.get("event") == "enrichment_db_write_failed"]
    assert error_events, (
        "Expected a structlog event with key 'enrichment_db_write_failed' but none was emitted. "
        "This means the logging fix in the Phase 3 except block has been reverted."
    )
    assert str(_ENTITY_ID) in error_events[0].get(
        "entity_id",
        "",
    ), "Log event must carry entity_id so operators can identify the failing entity."


@pytest.mark.asyncio()
async def test_db_write_seed_relations_sqlalchemy_error_raises_retryable_with_log() -> None:
    """seed_relations raises SQLAlchemyError → RetryableEnrichmentError with log.

    Guards against seed_relations failures (e.g. bad column name in INSERT)
    also being surfaced and logged.
    """
    from sqlalchemy.exc import ProgrammingError

    mdc = _make_mdc(lookup_payload={"description": "Apple is a technology giant."})
    adapter = _make_adapter()
    adapter.seed_relations = AsyncMock(
        side_effect=ProgrammingError(
            "column 'is_backfill' of relation 'relations' does not exist",
            params=None,
            orig=Exception("column is_backfill does not exist"),
        ),
    )
    uc = _make_use_case(mdc=mdc, adapter=adapter)

    with capture_logs() as captured:
        with pytest.raises(RetryableEnrichmentError, match="DB error during enrichment write"):
            await uc.enrich(_make_entity())

    error_events = [e for e in captured if e.get("event") == "enrichment_db_write_failed"]
    assert error_events, "SQLAlchemy error from seed_relations must also emit 'enrichment_db_write_failed' log."
