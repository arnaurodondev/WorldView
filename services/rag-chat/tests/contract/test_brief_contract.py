"""Contract tests for PLAN-0062-W4 structured brief schema (T-W4-C-04).

These tests verify the SHAPE and INVARIANTS of the brief response — not that
specific claims are true (that would require a live LLM). They use a 50-entry
fixture of real-world-style claims to stress the citation resolution pipeline.

WHY CONTRACT TESTS (not integration tests):
- Integration tests require a running LLM and S8 service.
- Contract tests verify the schema guarantees purely from the Pydantic models,
  the parser, and the citation pipeline — no external calls needed.
- The 50-claim fixture provides breadth coverage without flakiness.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from rag_chat.api.schemas import BriefBullet, BriefCitation, BriefSection, PublicBriefingResponse
from rag_chat.application.use_cases.generate_briefing import (
    _backfill_uncited_bullets,
    _compute_confidence,
    _materialize_brief_citations,
    _parse_sections_with_citations,
)

pytestmark = pytest.mark.unit

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "brief_50_claims.json"


# ── Fixture loading ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def claims_fixture() -> list[dict]:  # type: ignore[type-arg]
    """Load the 50-claim fixture from disk.

    WHY scope=module: the fixture JSON is read-only; loading once per module
    is safe and avoids redundant I/O for every test function.
    """
    with _FIXTURE_PATH.open() as f:
        return json.load(f)


def _build_mock_ctx(claim_entry: dict) -> object:  # type: ignore[type-arg]
    """Build a minimal mock context from a fixture entry.

    WHY dataclass-style mock: avoids importing unittest.mock in the fixture
    scope (reduces test startup overhead for 50 items).
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    articles = []
    for ca in claim_entry.get("context_articles", []):
        a = MagicMock()
        a.article_id = ca["id"]
        a.title = ca["title"]
        a.summary = ca.get("summary", "")
        a.url = ca.get("url")
        a.published_at = None
        a.display_relevance_score = None
        articles.append(a)

    ctx = SimpleNamespace(
        news_articles=articles,
        recent_events=[],
        active_alerts=[],
    )
    return ctx


def _make_brief_response(claim: str, context_citations: list[BriefCitation]) -> PublicBriefingResponse:
    """Simulate the full brief pipeline for a single claim.

    Uses a deterministic LLM-output template (no real LLM call) to produce a
    well-formed v3.0 brief that exercises the citation resolver.
    """
    if context_citations:
        # Build a synthetic LLM output referencing the first available citation
        cn = "[c1]"
        md = f"""## LEAD
{claim} {cn}

---

## DETAILS
### Market Context
- {claim[:100]} {cn}
- Related market movement observed {cn}

### Key Takeaways
- Evidence supports the narrative {cn}
- Monitoring required for ongoing developments {cn}
"""
    else:
        # No citations available — produce lead-less output
        md = f"""## LEAD
{claim} — awaiting source confirmation.

---

## DETAILS
### Market Context
- {claim[:100]}
- Related market movement observed
"""

    lead, lead_cits, sections = _parse_sections_with_citations(md, context_citations)
    sections = _backfill_uncited_bullets(sections, context_citations)
    confidence = _compute_confidence(sections, lead, lead_cits)

    return PublicBriefingResponse(
        narrative=md,
        risk_summary={},
        citations=[
            {
                "source_type": c.source_type,
                "source_id": c.document_id,
                "title": c.title,
                "url": c.url,
            }
            for c in context_citations
        ],
        generated_at="2026-05-03T10:00:00+00:00",
        sections=sections,
        lead=lead,
        confidence=confidence,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_response_validates_against_pydantic_schema(claims_fixture: list[dict]) -> None:  # type: ignore[type-arg]
    """Every claim's pipeline output must deserialise into PublicBriefingResponse.

    WHY this test: ensures no intermediate pipeline step produces a shape that
    violates the Pydantic schema contract (e.g. wrong type for bullets, out-of-range
    confidence, oversized lead text).
    """
    errors: list[str] = []
    for entry in claims_fixture:
        ctx = _build_mock_ctx(entry)
        ctx_cits = _materialize_brief_citations(ctx)
        try:
            resp = _make_brief_response(entry["claim"], ctx_cits)
            # Re-serialise and re-parse to catch any JSON round-trip issues
            PublicBriefingResponse.model_validate(resp.model_dump())
        except (ValidationError, Exception) as e:
            errors.append(f"claim={entry['claim'][:40]}: {e}")

    assert not errors, f"Schema validation failed for {len(errors)} claims:\n" + "\n".join(errors[:5])


def test_every_bullet_has_at_least_one_citation(claims_fixture: list[dict]) -> None:  # type: ignore[type-arg]
    """Every BriefBullet in every section must have ≥1 citation.

    WHY: this is the core PLAN-0062-W4 invariant — the 100% citation gate.
    No bullet may reach the response without a source document attached.
    """
    violations: list[str] = []
    for entry in claims_fixture:
        ctx = _build_mock_ctx(entry)
        ctx_cits = _materialize_brief_citations(ctx)
        resp = _make_brief_response(entry["claim"], ctx_cits)
        for sec in resp.sections:
            # WHY isinstance check: legacy fallback returns list[dict], not list[BriefBullet]
            for bullet in sec.bullets:
                if isinstance(bullet, BriefBullet):
                    if not bullet.citations:
                        violations.append(f"Uncited bullet: '{bullet.text[:40]}' in section '{sec.title}'")

    assert not violations, f"{len(violations)} uncited bullets found:\n" + "\n".join(violations[:5])


def test_every_citation_url_is_well_formed(claims_fixture: list[dict]) -> None:  # type: ignore[type-arg]
    """Every citation with a URL must have a well-formed https:// URL (no network calls).

    WHY: ensures the citation URL generation doesn't produce malformed hrefs
    (e.g. bare paths, double slashes, missing scheme) that would break frontend links.
    """
    url_pattern = re.compile(r"^https?://\S+$")
    bad_urls: list[str] = []
    for entry in claims_fixture:
        ctx = _build_mock_ctx(entry)
        ctx_cits = _materialize_brief_citations(ctx)
        for cit in ctx_cits:
            if cit.url is not None:
                if not url_pattern.match(cit.url):
                    bad_urls.append(f"doc_id={cit.document_id} url='{cit.url}'")

    assert not bad_urls, "Malformed URLs found:\n" + "\n".join(bad_urls)


def test_confidence_is_in_zero_to_one(claims_fixture: list[dict]) -> None:  # type: ignore[type-arg]
    """Confidence score must be in [0.0, 1.0] for every claim."""
    out_of_range: list[str] = []
    for entry in claims_fixture:
        ctx = _build_mock_ctx(entry)
        ctx_cits = _materialize_brief_citations(ctx)
        resp = _make_brief_response(entry["claim"], ctx_cits)
        if not (0.0 <= resp.confidence <= 1.0):
            out_of_range.append(f"confidence={resp.confidence} for claim: {entry['claim'][:40]}")

    assert not out_of_range, "Out-of-range confidence scores:\n" + "\n".join(out_of_range)


def test_stale_v1_shape_at_v2_cache_key_falls_through() -> None:
    """A v1 cached response (string bullets) at the v2 key causes Pydantic validation error.

    WHY: Verifies that the schema migration is a HARD BREAK — stale v1 responses
    (with bullets: list[str]) cannot be served as v2 responses (bullets: list[BriefBullet]).
    The route should get a cache miss (None) for the v2 key, not try to deserialise old data.

    This test simulates what happens when someone attempts to construct a BriefSection
    with legacy string bullets after PLAN-0062-W4.
    """
    # Simulating stale v1 section data (string bullets) being passed to new schema
    with pytest.raises(ValidationError):
        BriefSection(
            title="Legacy Section",
            bullets=["String bullet 1", "String bullet 2"],  # type: ignore[list-item]
        )
