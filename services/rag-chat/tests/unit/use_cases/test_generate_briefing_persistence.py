"""Unit tests for PLAN-0066 Wave B persistence hook in GenerateBriefingUseCase.

Tests verify:
  - archive.save() is scheduled (via ensure_future) after a fresh morning brief generation
  - a failure in archive.save() does NOT cause execute_public_morning() to raise
  - GenerateBriefingUseCase with no brief_archive arg defaults to NullBriefArchive (no error)

WHY asyncio.ensure_future: the use case schedules a fire-and-forget coroutine.
We drain the event loop via asyncio.gather(return_exceptions=True) in the
fixture so the mock assertion fires before the test exits.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from rag_chat.application.ports.brief_archive import NullBriefArchive, UserBriefRecord
from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

pytestmark = pytest.mark.unit

# ── Fixture helpers ───────────────────────────────────────────────────────────

_USER_ID = "00000000-0000-0000-0000-000000000099"
_TENANT_ID = "00000000-0000-0000-0000-000000000088"


def _make_llm_chain(
    output: str = "## LEAD\nMarkets stable [c1].\n---\n## DETAILS\n### Drivers\n- Tech leads [c1].",
) -> MagicMock:
    """Create a mock LLM chain that streams one chunk."""

    async def _fake_stream(prompt: str, **kwargs: object) -> None:
        for chunk in [output]:
            yield chunk

    chain = MagicMock()
    chain.stream = _fake_stream
    return chain


def _make_valkey(count: int = 1) -> MagicMock:
    """Create a mock Valkey client that stays under the rate limit."""
    valkey = MagicMock()
    valkey.incr = AsyncMock(return_value=count)
    valkey.expire = AsyncMock()
    return valkey


def _make_context_gatherer_empty() -> MagicMock:
    """Create a mock context gatherer returning None (triggers empty-context guard)."""
    gatherer = MagicMock()
    gatherer.gather_morning_context = AsyncMock(return_value=None)
    return gatherer


def _make_context_gatherer_with_news() -> MagicMock:
    """Create a mock context gatherer that returns minimal non-empty context.

    WHY non-empty: execute_public_morning() short-circuits to a placeholder response
    (without calling the LLM or running persistence) when ALL context sections are
    empty. We need at least one non-empty section (e.g. news text from a mock article)
    to reach the LLM call + persistence path.
    """
    gatherer = MagicMock()

    # Build a minimal BriefingContext with one news article so _format_news() != ""
    article = MagicMock()
    article.article_id = UUID("00000000-0000-0000-0000-000000000010")
    article.title = "AI stocks surge"
    article.url = "https://example.com/news/1"
    article.published_at = __import__("datetime").datetime(
        2026, 5, 8, 9, 0, 0, tzinfo=__import__("datetime").timezone.utc
    )
    article.display_relevance_score = 0.9
    article.summary = "Technology stocks rallied."

    ctx = MagicMock()
    ctx.news_articles = [article]
    ctx.recent_events = []
    ctx.active_alerts = []
    ctx.portfolio = None
    ctx.market_overview = None

    gatherer.gather_morning_context = AsyncMock(return_value=ctx)
    return gatherer


# ── T-W10-B-02: persistence called on fresh morning brief ────────────────────


@pytest.mark.asyncio
async def test_persistence_called_on_morning_brief() -> None:
    """archive.save() is scheduled once after a successful morning brief generation.

    WHY: the persistence hook must fire on every fresh generation (not cache hits).
    We drain the event loop after execute_public_morning() returns so that the
    ensure_future-scheduled coroutine has a chance to execute before we assert.
    """
    # Arrange: mock archive that records save() calls
    mock_archive = MagicMock()
    mock_archive.save = AsyncMock()

    # Patch common.ids + common.time at the source module level.
    # WHY patch common.ids/common.time (not the generate_briefing module):
    # the imports inside execute_public_morning() are lazy (inside the function
    # body). Python resolves them from sys.modules at call time, so patching
    # the source module (common.ids, common.time) is the correct intercept point.
    import datetime as _dt

    _fixed_ts = _dt.datetime(2026, 5, 8, 12, 0, 0, tzinfo=_dt.UTC)
    _fixed_id = UUID("00000000-0000-0000-0000-000000000001")

    with (
        patch("common.ids.new_uuid7", return_value=_fixed_id),
        patch("common.time.utc_now", return_value=_fixed_ts),
    ):
        uc = GenerateBriefingUseCase(
            llm_chain=_make_llm_chain(),
            valkey=_make_valkey(),
            context_gatherer=_make_context_gatherer_with_news(),
            brief_archive=mock_archive,
        )

        result = await uc.execute_public_morning(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
        )

    # WHY drain event loop: ensure_future schedules the _persist_brief coroutine
    # but it hasn't run yet when execute_public_morning() returns. We give the
    # loop a chance to run all pending tasks before asserting.
    await asyncio.sleep(0)

    # Assert: result is a valid dict with content key
    assert "content" in result or "narrative" in result or "sections" in result

    # Assert: save was called exactly once (the fire-and-forget scheduled it)
    mock_archive.save.assert_called_once()
    call_arg = mock_archive.save.call_args[0][0]
    assert isinstance(call_arg, UserBriefRecord)
    assert call_arg.brief_type == "morning"
    assert call_arg.entity_id is None
    assert call_arg.source_version == "v2"


# ── T-W10-B-02: persistence failure does not fail the brief ──────────────────


@pytest.mark.asyncio
async def test_persistence_failure_does_not_fail_brief() -> None:
    """If archive.save() raises, execute_public_morning() still returns the response.

    WHY: asyncio.shield + the try/except in _persist_brief absorb the exception.
    The user must always receive their briefing even if the DB write fails.
    """
    # Arrange: mock archive that always raises on save
    failing_archive = MagicMock()
    failing_archive.save = AsyncMock(side_effect=RuntimeError("DB connection refused"))

    import datetime as _dt

    _fixed_ts = _dt.datetime(2026, 5, 8, 12, 0, 0, tzinfo=_dt.UTC)
    _fixed_id = UUID("00000000-0000-0000-0000-000000000001")

    with (
        patch("common.ids.new_uuid7", return_value=_fixed_id),
        patch("common.time.utc_now", return_value=_fixed_ts),
    ):
        uc = GenerateBriefingUseCase(
            llm_chain=_make_llm_chain(),
            valkey=_make_valkey(),
            context_gatherer=_make_context_gatherer_with_news(),
            brief_archive=failing_archive,
        )

        # Act — must NOT raise even though save() raises
        result = await uc.execute_public_morning(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
        )

    # Drain event loop so the _persist_brief coroutine runs and the exception is logged
    await asyncio.sleep(0)

    # Assert: the HTTP response is still returned
    assert isinstance(result, dict)
    # The brief has content (either empty-context placeholder or generated content)
    assert "generated_at" in result


# ── T-W10-B-02: NullBriefArchive default — no errors ─────────────────────────


@pytest.mark.asyncio
async def test_null_archive_default_no_errors() -> None:
    """GenerateBriefingUseCase without brief_archive arg uses NullBriefArchive — no errors.

    WHY: existing callers (email path, unit tests without archive) must continue to
    work unchanged. The NullBriefArchive default is a silent no-op that doesn't
    require any DI setup.
    """
    # Arrange: no brief_archive arg → defaults to NullBriefArchive
    uc = GenerateBriefingUseCase(
        llm_chain=_make_llm_chain(),
        valkey=_make_valkey(),
        context_gatherer=_make_context_gatherer_empty(),
        # Intentionally omit brief_archive — should default to NullBriefArchive
    )

    # Verify the internal attribute is a NullBriefArchive
    assert isinstance(uc._brief_archive, NullBriefArchive)

    # Act — must not raise
    import datetime as _dt

    _fixed_ts = _dt.datetime(2026, 5, 8, 12, 0, 0, tzinfo=_dt.UTC)
    _fixed_id = UUID("00000000-0000-0000-0000-000000000001")

    with (
        patch("common.ids.new_uuid7", return_value=_fixed_id),
        patch("common.time.utc_now", return_value=_fixed_ts),
    ):
        result = await uc.execute_public_morning(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
        )

    await asyncio.sleep(0)

    # Assert: response returned normally
    assert isinstance(result, dict)
    assert "generated_at" in result


# ── PLAN-0103 W3 (BP-624): completeness check fires on missing sections ──────


@pytest.mark.asyncio
async def test_section_missing_metric_fires_for_partial_brief() -> None:
    """When the LLM emits only 4 of 6 v4.2 sections, brief_section_missing_total increments.

    Reproduces the FQA-01 pattern (Tape, Your Portfolio Today, Macro Today,
    News That Matters To You present; Risks + Opportunities and Bonus context
    missing) and asserts the Prom counter increments for the two missing
    section names.
    """
    fqa01_output = (
        "## Summary\nTech rally continues.\n\n"
        "## Details\n"
        "**Tape**\n- SPY +0.2% [N1]\n"
        "**Your Portfolio Today**\n- AAPL flat [N1]\n"
        "**Macro Today**\n- No prints today [N1]\n"
        "**News That Matters To You**\n- Dell up 40% [N1]\n"
    )

    from rag_chat.application.metrics import prometheus as _prom

    # Snapshot baseline counts so the test is order-independent.
    def _count(section: str) -> float:
        # _value.get() reads the live counter value for a label combination.
        return _prom.brief_section_missing_total.labels(section=section)._value.get()

    before_risks = _count("Risks + Opportunities")
    before_bonus = _count("Bonus context")
    before_tape = _count("Tape")

    import datetime as _dt

    _fixed_ts = _dt.datetime(2026, 5, 30, 12, 0, 0, tzinfo=_dt.UTC)
    _fixed_id = UUID("00000000-0000-0000-0000-000000000002")
    with (
        patch("common.ids.new_uuid7", return_value=_fixed_id),
        patch("common.time.utc_now", return_value=_fixed_ts),
    ):
        uc = GenerateBriefingUseCase(
            llm_chain=_make_llm_chain(output=fqa01_output),
            valkey=_make_valkey(),
            context_gatherer=_make_context_gatherer_with_news(),
        )
        await uc.execute_public_morning(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
        )

    after_risks = _count("Risks + Opportunities")
    after_bonus = _count("Bonus context")
    after_tape = _count("Tape")

    assert after_risks == before_risks + 1.0, "Risks + Opportunities should be flagged missing"
    assert after_bonus == before_bonus + 1.0, "Bonus context should be flagged missing"
    # Tape was present → no increment
    assert after_tape == before_tape, "Tape was present and should NOT increment"


@pytest.mark.asyncio
async def test_summary_paragraph_surfaced_on_response() -> None:
    """v4.2 ``## Summary`` block is parsed and surfaced as ``summary_paragraph`` on the result."""
    v42_output = (
        "## Summary\nDell rally and Palantir surge highlight AI momentum.\n\n"
        "## Details\n"
        "**Tape**\n- SPY +0.2% [N1]\n"
        "**Your Portfolio Today**\n- AAPL flat [N1]\n"
        "**Macro Today**\n- No prints [N1]\n"
        "**News That Matters To You**\n- Dell up 40% [N1]\n"
        "**Risks + Opportunities**\n- No risks\n"
        "**Bonus context**\n- None\n"
    )
    import datetime as _dt

    _fixed_ts = _dt.datetime(2026, 5, 30, 12, 0, 0, tzinfo=_dt.UTC)
    _fixed_id = UUID("00000000-0000-0000-0000-000000000003")
    with (
        patch("common.ids.new_uuid7", return_value=_fixed_id),
        patch("common.time.utc_now", return_value=_fixed_ts),
    ):
        uc = GenerateBriefingUseCase(
            llm_chain=_make_llm_chain(output=v42_output),
            valkey=_make_valkey(),
            context_gatherer=_make_context_gatherer_with_news(),
        )
        result = await uc.execute_public_morning(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
        )

    assert result.get("summary_paragraph") is not None
    assert "Dell rally" in result["summary_paragraph"]
