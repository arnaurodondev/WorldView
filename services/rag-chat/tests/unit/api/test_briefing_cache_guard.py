"""Unit tests for the morning-brief cache-poisoning guard (2026-06-19).

Background: the empty-AI-brief investigation
(``docs/audits/2026-06-19-empty-ai-brief-investigation.md``) found that a
transient gateway/upstream auth blip produces a zero-context "refusal" brief —
every section reads "No specific items today" and ``confidence == 0.0``. The
GET cold-gen and POST /briefings/morning/generate paths used to write that
refusal to BOTH the fresh key AND the ``lastgood`` key, clobbering the previous
known-good brief and blanking the dashboard.

These tests pin the guard:
  * ``_is_low_context_brief`` correctly classifies refusal vs real briefs.
  * ``_write_brief_caches`` ALWAYS writes the fresh key but SKIPS the lastgood
    key for a refusal (preserving the prior good brief).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from rag_chat.api.routes.public_briefings import (
    _is_low_context_brief,
    _write_brief_caches,
)
from rag_chat.api.schemas import PublicBriefingResponse

pytestmark = pytest.mark.unit

_GENERATED_AT = "2026-06-19T12:00:00+00:00"


def _refusal_brief() -> PublicBriefingResponse:
    """A zero-context refusal: confidence 0, no citations, placeholder sections."""
    return PublicBriefingResponse(
        narrative="No specific items today.",
        risk_summary={},
        citations=[],
        generated_at=_GENERATED_AT,
        cached=False,
        entity_id=None,
        summary=None,
        sections=[
            {"title": "Portfolio", "body": "No specific items today."},
            {"title": "News", "body": "No specific items today."},
        ],
        confidence=0.0,
        lead=None,
        is_stale=False,
    )


def _real_brief() -> PublicBriefingResponse:
    """A genuine brief: positive confidence and a grounded section."""
    return PublicBriefingResponse(
        narrative="AAPL led your portfolio up +2.1% on strong iPhone demand.",
        risk_summary={"concentration_score": 0.4},
        citations=[],
        generated_at=_GENERATED_AT,
        cached=False,
        entity_id=None,
        summary=None,
        sections=[
            {"title": "Portfolio", "body": "AAPL +2.1%, MSFT +0.8%."},
        ],
        confidence=0.83,
        lead="Your portfolio rose today.",
        is_stale=False,
    )


# ── _is_low_context_brief classification ──────────────────────────────────────


def test_refusal_brief_is_low_context() -> None:
    assert _is_low_context_brief(_refusal_brief()) is True


def test_real_brief_is_not_low_context() -> None:
    assert _is_low_context_brief(_real_brief()) is False


def test_positive_confidence_alone_passes_guard() -> None:
    # confidence > 0 short-circuits to "not low-context" even with empty sections.
    brief = _refusal_brief()
    brief.confidence = 0.5
    assert _is_low_context_brief(brief) is False


def test_real_section_with_zero_confidence_passes_guard() -> None:
    # A grounded section means real content even if confidence happens to be 0.
    brief = _refusal_brief()
    brief.sections = [{"title": "News", "body": "Fed signalled a rate hold."}]
    assert _is_low_context_brief(brief) is False


# ── _write_brief_caches behaviour ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refusal_writes_fresh_but_not_lastgood() -> None:
    """A refusal must update the fresh key only — lastgood is preserved."""
    valkey = AsyncMock()
    await _write_brief_caches(
        valkey,
        cache_key="briefing:morning:v2:u1",
        lastgood_key="briefing:morning:lastgood:u1",
        response=_refusal_brief(),
    )
    written_keys = [call.args[0] for call in valkey.set.call_args_list]
    assert "briefing:morning:v2:u1" in written_keys
    assert "briefing:morning:lastgood:u1" not in written_keys


@pytest.mark.asyncio
async def test_real_brief_writes_both_keys() -> None:
    """A genuine brief updates both the fresh and lastgood keys."""
    valkey = AsyncMock()
    await _write_brief_caches(
        valkey,
        cache_key="briefing:morning:v2:u1",
        lastgood_key="briefing:morning:lastgood:u1",
        response=_real_brief(),
    )
    written_keys = [call.args[0] for call in valkey.set.call_args_list]
    assert "briefing:morning:v2:u1" in written_keys
    assert "briefing:morning:lastgood:u1" in written_keys


@pytest.mark.asyncio
async def test_none_valkey_is_noop() -> None:
    # Should not raise when Valkey is unavailable.
    await _write_brief_caches(
        None,
        cache_key="k",
        lastgood_key="lg",
        response=_real_brief(),
    )
