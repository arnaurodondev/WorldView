"""Unit tests for S7IntelligenceClient response parsing (PLAN-0100 W3 T-W3-03).

Regression for BP-602: the client previously read ``raw["narrative"]`` and
``raw["source_distribution"]`` at the top level, but S7's
``EntityIntelligencePublic`` nests them under ``current_narrative.narrative_text``
and ``confidence_breakdown.source_distribution``. Result: the narrative text
(the highest-value signal — names competitors, themes, exposures) was silently
dropped, and ``get_entity_intelligence(AAPL)`` produced a one-line
"Health Score: 0.73" bundle. Live evidence in
``docs/audits/2026-05-28-plan-0100-aapl-kg-investigation.md``.

The tests below use a real S7 payload shape (captured from the live
``/v1/entities/{AAPL}/intelligence`` endpoint) and assert that the parsed
result is **non-empty** — i.e. has narrative OR health_score populated.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from rag_chat.infrastructure.clients.s7_intelligence_client import S7IntelligenceClient

if TYPE_CHECKING:
    import pytest_httpx

pytestmark = pytest.mark.unit


_AAPL_ID = UUID("01900000-0000-7000-8000-000000001001")
_BASE = "http://testkg"


# ── Live S7 payload shape — copied from a real response ──────────────────────


def _live_intelligence_payload() -> dict:
    """Match the EntityIntelligencePublic schema returned by S7 (real fields)."""
    return {
        "entity_id": str(_AAPL_ID),
        "canonical_name": "Apple Inc.",
        "entity_type": "financial_instrument",
        "health_score": 0.7291120333665124,
        "current_narrative": {
            "version_id": "019e4849-2525-7308-9c4b-bcc88abda1f5",
            "narrative_text": (
                "Apple Inc. is a leading technology company that competes with "
                "Microsoft Corporation in the global market for personal computers "
                "and software."
            ),
            "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
            "generation_reason": "PERIODIC_REFRESH",
            "generated_at": "2026-05-21T02:06:53.733573Z",
            "word_count": 96,
            "quality_score": None,
        },
        "confidence_breakdown": {
            "mean_support": 0.95,
            "mean_corroboration": None,
            "mean_contradiction": None,
            "latest_evidence_at": "2026-05-28T03:19:31.186807Z",
            "relation_count": 1,
            "source_distribution": [
                {"source_type": "eodhd", "source_name": "eodhd", "count": 4, "pct": 1.0},
            ],
            "confidence_trend": [
                {"date": "2026-05-28", "avg_confidence": 0.9},
            ],
        },
        "key_metrics": {},
        "data_completeness": 0.5,
    }


def _live_narratives_payload() -> dict:
    """Match the NarrativeVersionListResponse schema returned by S7."""
    return {
        "entity_id": str(_AAPL_ID),
        "versions": [
            {
                "version_id": "019e4849-2525-7308-9c4b-bcc88abda1f5",
                "narrative_text": "Apple Inc. competes with Microsoft and Samsung in consumer tech.",
                "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
                "generation_reason": "PERIODIC_REFRESH",
                "generated_at": "2026-05-21T02:06:53.733573Z",
                "word_count": 12,
                "quality_score": None,
            }
        ],
        "next_cursor": None,
    }


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_entity_intelligence_aapl_bundle_is_non_empty(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """BP-602 regression: AAPL intelligence bundle must surface the narrative.

    Before the fix, the client read ``raw["narrative"]`` (top-level), which
    does not exist in the S7 schema, so the narrative was silently dropped
    and the agent could not answer "Who are Apple's competitors?".
    """
    httpx_mock.add_response(
        url=re.compile(rf"{_BASE}/api/v1/entities/{_AAPL_ID}/intelligence"),
        json=_live_intelligence_payload(),
    )
    client = S7IntelligenceClient(base_url=_BASE)

    result = await client.get_entity_intelligence(_AAPL_ID)

    # The whole point of the wave: result must be non-empty for a top-50 entity.
    assert result is not None
    # At least one of (narrative, health_score) must be populated — both should be.
    assert result.narrative is not None and len(result.narrative) > 0, (
        "BP-602: narrative was silently dropped because the client read the wrong key. "
        "S7 nests it under current_narrative.narrative_text."
    )
    assert (
        "Microsoft" in result.narrative
    ), "Narrative must surface the competitor name verbatim so the agent can cite it."
    assert result.health_score == pytest.approx(0.7291120333665124)
    # source_distribution is normalised from list-of-dicts to a name→pct map.
    assert result.source_distribution == {"eodhd": 1.0}


@pytest.mark.asyncio
async def test_get_narrative_parses_versions_list(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """BP-602: get_narrative must read versions[0].narrative_text, not legacy ``content``."""
    httpx_mock.add_response(
        url=re.compile(rf"{_BASE}/api/v1/entities/{_AAPL_ID}/narratives"),
        json=_live_narratives_payload(),
    )
    client = S7IntelligenceClient(base_url=_BASE)

    result = await client.get_narrative(_AAPL_ID)

    assert result is not None
    assert result.content.startswith("Apple Inc. competes with Microsoft")
    assert result.generated_at == "2026-05-21T02:06:53.733573Z"


@pytest.mark.asyncio
async def test_get_narrative_returns_none_when_versions_empty(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Empty versions list → return None so the handler emits no item."""
    httpx_mock.add_response(
        url=re.compile(rf"{_BASE}/api/v1/entities/{_AAPL_ID}/narratives"),
        json={"entity_id": str(_AAPL_ID), "versions": [], "next_cursor": None},
    )
    client = S7IntelligenceClient(base_url=_BASE)

    result = await client.get_narrative(_AAPL_ID)
    assert result is None


@pytest.mark.asyncio
async def test_get_entity_intelligence_handles_missing_narrative_block(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """If current_narrative is None, narrative=None but bundle still parses."""
    payload = _live_intelligence_payload()
    payload["current_narrative"] = None
    httpx_mock.add_response(
        url=re.compile(rf"{_BASE}/api/v1/entities/{_AAPL_ID}/intelligence"),
        json=payload,
    )
    client = S7IntelligenceClient(base_url=_BASE)

    result = await client.get_entity_intelligence(_AAPL_ID)

    assert result is not None
    assert result.narrative is None
    assert result.health_score == pytest.approx(0.7291120333665124)
