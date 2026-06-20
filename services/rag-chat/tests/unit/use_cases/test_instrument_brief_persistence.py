"""Unit tests for entity-brief persistence in GenerateBriefingUseCase.execute_public_instrument.

AI-brief-flag fix (2026-06-19).

These tests verify the previously-missing producer of ``brief_type='entity'``
rows — the gap that made the screener ``has_ai_brief`` flag structurally always
false. Covered:

  * a fresh instrument brief persists a row with brief_type='entity' AND
    entity_id == the RESOLVED market-data instrument_id (not the KG entity_id);
  * when the ticker did NOT resolve, the persisted id falls back to entity_id;
  * skip_if_fresh returns the existing brief WITHOUT an LLM call (idempotency);
  * skip_if_fresh regenerates when the existing brief is stale;
  * persist=False suppresses the write (e.g. callers that opt out);
  * a persistence failure never fails the brief response.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from rag_chat.application.ports.brief_archive import UserBriefRecord
from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

pytestmark = pytest.mark.unit

# A KG entity id (route param) and a DIFFERENT market-data instrument id — the
# whole point of the fix is that we persist under the instrument id.
_ENTITY_ID = "11111111-1111-1111-1111-111111111111"
_INSTRUMENT_ID = "22222222-2222-2222-2222-222222222222"

_LLM_OUTPUT = "## LEAD\nApple is steady [c1].\n---\n## DETAILS\n### Drivers\n- iPhone demand firm [c1]."


def _make_llm_chain(output: str = _LLM_OUTPUT) -> MagicMock:
    async def _fake_stream(prompt: str, **kwargs: object):
        yield output

    chain = MagicMock()
    chain.stream = _fake_stream
    return chain


def _make_valkey() -> MagicMock:
    valkey = MagicMock()
    valkey.incr = AsyncMock(return_value=1)
    valkey.expire = AsyncMock()
    return valkey


def _make_ctx(*, resolved_instrument_id: str | None) -> SimpleNamespace:
    """Minimal duck-typed BriefingContext for the instrument path.

    The formatter + parser only touch the attributes set here; everything else
    degrades to empty strings / [] (R9). Using SimpleNamespace keeps the test
    decoupled from the full dataclass surface.
    """
    return SimpleNamespace(
        resolved_instrument_id=resolved_instrument_id,
        entity_id=_ENTITY_ID,
        entity_graph=None,
        fundamentals=None,
        news_articles=[],
        active_alerts=[],
        quotes={},
        recent_events=[],
        relevant_chunks=[],
        entity_narrative=None,
        entity_narrative_generated_at=None,
        market_overview=None,
        portfolio=None,
    )


def _make_gatherer(ctx: SimpleNamespace) -> MagicMock:
    gatherer = MagicMock()
    gatherer.gather_instrument_context = AsyncMock(return_value=ctx)
    return gatherer


@pytest.mark.asyncio
async def test_persists_entity_brief_keyed_to_instrument_id() -> None:
    """A fresh instrument brief writes brief_type='entity' keyed to the resolved instrument_id."""
    archive = MagicMock()
    archive.save = AsyncMock()
    archive.get_latest_entity_brief = AsyncMock(return_value=[])

    uc = GenerateBriefingUseCase(
        llm_chain=_make_llm_chain(),
        valkey=_make_valkey(),
        context_gatherer=_make_gatherer(_make_ctx(resolved_instrument_id=_INSTRUMENT_ID)),
        brief_archive=archive,
    )

    result = await uc.execute_public_instrument(_ENTITY_ID)
    await asyncio.sleep(0)  # drain the fire-and-forget persist task

    assert "content" in result
    archive.save.assert_called_once()
    record = archive.save.call_args[0][0]
    assert isinstance(record, UserBriefRecord)
    assert record.brief_type == "entity"
    # CRITICAL: keyed to the instrument_id (what the flag queries by), NOT the KG entity_id.
    assert record.entity_id == UUID(_INSTRUMENT_ID)
    assert record.entity_id != UUID(_ENTITY_ID)


@pytest.mark.asyncio
async def test_persist_falls_back_to_entity_id_when_unresolved() -> None:
    """When the ticker did not resolve an instrument_id, persist under the entity_id."""
    archive = MagicMock()
    archive.save = AsyncMock()
    archive.get_latest_entity_brief = AsyncMock(return_value=[])

    uc = GenerateBriefingUseCase(
        llm_chain=_make_llm_chain(),
        valkey=_make_valkey(),
        context_gatherer=_make_gatherer(_make_ctx(resolved_instrument_id=None)),
        brief_archive=archive,
    )

    await uc.execute_public_instrument(_ENTITY_ID)
    await asyncio.sleep(0)

    record = archive.save.call_args[0][0]
    assert record.entity_id == UUID(_ENTITY_ID)


@pytest.mark.asyncio
async def test_skip_if_fresh_returns_existing_without_llm() -> None:
    """skip_if_fresh short-circuits to the cached row and never calls the LLM (idempotency)."""
    fresh = UserBriefRecord(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        user_id=UUID("00000000-0000-0000-0000-000000000000"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000000"),
        brief_type="entity",
        entity_id=UUID(_INSTRUMENT_ID),
        generated_at=_dt.datetime.now(tz=_dt.UTC),  # brand new → fresh
        headline="Cached headline",
        lead="Cached lead",
        sections_json=[],
        citations_json=[],
        confidence=0.8,
        source_version="v2",
    )
    archive = MagicMock()
    archive.save = AsyncMock()
    archive.get_latest_entity_brief = AsyncMock(return_value=[fresh])

    # LLM that would EXPLODE if called — proves we short-circuit before it.
    def _boom_chain() -> MagicMock:
        async def _stream(prompt: str, **kwargs: object):
            raise AssertionError("LLM must not be called when a fresh brief exists")
            yield ""  # pragma: no cover

        chain = MagicMock()
        chain.stream = _stream
        return chain

    uc = GenerateBriefingUseCase(
        llm_chain=_boom_chain(),
        valkey=_make_valkey(),
        context_gatherer=_make_gatherer(_make_ctx(resolved_instrument_id=_INSTRUMENT_ID)),
        brief_archive=archive,
    )

    result = await uc.execute_public_instrument(_ENTITY_ID, skip_if_fresh=True)
    await asyncio.sleep(0)

    assert result.get("skipped_fresh") is True
    assert result["content"] == "Cached headline"
    archive.save.assert_not_called()


@pytest.mark.asyncio
async def test_skip_if_fresh_regenerates_when_stale() -> None:
    """skip_if_fresh regenerates (and re-persists) when the existing brief is stale."""
    stale = UserBriefRecord(
        id=UUID("44444444-4444-4444-4444-444444444444"),
        user_id=UUID("00000000-0000-0000-0000-000000000000"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000000"),
        brief_type="entity",
        entity_id=UUID(_INSTRUMENT_ID),
        generated_at=_dt.datetime.now(tz=_dt.UTC) - _dt.timedelta(days=3),  # stale
        headline="Old headline",
        lead="Old lead",
        sections_json=[],
        citations_json=[],
        confidence=0.5,
        source_version="v2",
    )
    archive = MagicMock()
    archive.save = AsyncMock()
    archive.get_latest_entity_brief = AsyncMock(return_value=[stale])

    uc = GenerateBriefingUseCase(
        llm_chain=_make_llm_chain(),
        valkey=_make_valkey(),
        context_gatherer=_make_gatherer(_make_ctx(resolved_instrument_id=_INSTRUMENT_ID)),
        brief_archive=archive,
    )

    result = await uc.execute_public_instrument(_ENTITY_ID, skip_if_fresh=True)
    await asyncio.sleep(0)

    assert not result.get("skipped_fresh")
    archive.save.assert_called_once()  # re-persisted a fresh brief


@pytest.mark.asyncio
async def test_persist_false_suppresses_write() -> None:
    """persist=False generates the brief but writes nothing."""
    archive = MagicMock()
    archive.save = AsyncMock()
    archive.get_latest_entity_brief = AsyncMock(return_value=[])

    uc = GenerateBriefingUseCase(
        llm_chain=_make_llm_chain(),
        valkey=_make_valkey(),
        context_gatherer=_make_gatherer(_make_ctx(resolved_instrument_id=_INSTRUMENT_ID)),
        brief_archive=archive,
    )

    await uc.execute_public_instrument(_ENTITY_ID, persist=False)
    await asyncio.sleep(0)

    archive.save.assert_not_called()


@pytest.mark.asyncio
async def test_persist_failure_does_not_fail_brief() -> None:
    """A DB failure in save() never propagates to the caller."""
    archive = MagicMock()
    archive.save = AsyncMock(side_effect=RuntimeError("DB down"))
    archive.get_latest_entity_brief = AsyncMock(return_value=[])

    uc = GenerateBriefingUseCase(
        llm_chain=_make_llm_chain(),
        valkey=_make_valkey(),
        context_gatherer=_make_gatherer(_make_ctx(resolved_instrument_id=_INSTRUMENT_ID)),
        brief_archive=archive,
    )

    result = await uc.execute_public_instrument(_ENTITY_ID)
    await asyncio.sleep(0)

    assert "content" in result
    assert "generated_at" in result


@pytest.mark.asyncio
async def test_persisted_row_satisfies_flag_query() -> None:
    """The persisted entity row is exactly what GetAiBriefFlagUseCase matches on.

    Cross-checks the producer against the consumer: the flag's predicate is
    ``brief_type='entity' AND entity_id=:id``. We assert the saved record carries
    both, with the instrument id the flag would be called with.
    """
    archive = MagicMock()
    archive.save = AsyncMock()
    archive.get_latest_entity_brief = AsyncMock(return_value=[])

    with (
        patch("common.ids.new_uuid7", return_value=UUID("55555555-5555-5555-5555-555555555555")),
    ):
        uc = GenerateBriefingUseCase(
            llm_chain=_make_llm_chain(),
            valkey=_make_valkey(),
            context_gatherer=_make_gatherer(_make_ctx(resolved_instrument_id=_INSTRUMENT_ID)),
            brief_archive=archive,
        )
        await uc.execute_public_instrument(_ENTITY_ID)
        await asyncio.sleep(0)

    record = archive.save.call_args[0][0]
    # The flag query: WHERE brief_type='entity' AND entity_id=:id
    assert record.brief_type == "entity"
    assert str(record.entity_id) == _INSTRUMENT_ID
