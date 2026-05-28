"""BP-604 / BP-605 (PLAN-0100 W1) — entity-drift guards.

Unit coverage for the two helpers added to ``chat_orchestrator.py``:

* ``_validate_fallback_tool_call`` (BP-604) — rejects an iter ≥ 1 tool call
  whose entity-typed input names an entity that was NOT in the original
  question and was NOT surfaced by any prior tool call.
* ``_check_entity_grounding`` (BP-605) — refuses to synthesise when ZERO
  retrieved items reference an entity from the original question.

The Q2 MSTR canary in docs/audits/2026-05-27-plan-0100-q2-mstr-entity-drift-
deepdive.md is the regression fixture: question entities = {MSTR}, prior
calls used entity_tickers=["MSTR"], next call uses
entity_name="ON Semiconductor Corporation" — must reject.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from rag_chat.application.use_cases.chat_orchestrator import (
    _check_entity_grounding,
    _collect_prior_tool_entity_identifiers,
    _collect_question_entity_identifiers,
    _normalise_entity_identifier,
    _validate_fallback_tool_call,
)

pytestmark = pytest.mark.unit


# ── Lightweight test doubles ──────────────────────────────────────────────────
# The orchestrator helpers only call ``getattr`` on ``input``/``entity_id``/
# ``citation_meta``/``entity_name`` — so a simple dataclass keeps the test
# wiring minimal without importing the real domain types (which carry
# fusion_score invariants that would distract from the entity logic).


@dataclass
class _FakeToolCall:
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeEntity:
    entity_id: Any
    canonical_name: str | None = None
    ticker: str | None = None
    matched_text: str | None = None


@dataclass
class _FakeCitationMeta:
    entity_name: str | None = None


@dataclass
class _FakeRetrievedItem:
    citation_meta: _FakeCitationMeta | None = None
    entity_id: Any = None


# ── _normalise_entity_identifier ─────────────────────────────────────────────


class TestNormaliseEntityIdentifier:
    def test_none_returns_empty_set(self) -> None:
        assert _normalise_entity_identifier(None) == set()

    def test_str_lowercases_and_strips(self) -> None:
        assert _normalise_entity_identifier("  MSTR  ") == {"mstr"}

    def test_uuid_collapses_to_str(self) -> None:
        u = uuid4()
        assert _normalise_entity_identifier(u) == {str(u).lower()}

    def test_list_recurses(self) -> None:
        assert _normalise_entity_identifier(["MSTR", "AAPL"]) == {"mstr", "aapl"}

    def test_empty_string_is_dropped(self) -> None:
        assert _normalise_entity_identifier("") == set()
        assert _normalise_entity_identifier("   ") == set()


# ── _collect_question_entity_identifiers ─────────────────────────────────────


class TestCollectQuestionEntityIdentifiers:
    def test_combines_all_fields(self) -> None:
        u = uuid4()
        ent = _FakeEntity(entity_id=u, canonical_name="MicroStrategy Inc.", ticker="MSTR", matched_text="mstr")
        ids = _collect_question_entity_identifiers([ent], None)
        assert str(u).lower() in ids
        assert "microstrategy inc." in ids
        assert "mstr" in ids

    def test_empty_entities_returns_empty_set(self) -> None:
        assert _collect_question_entity_identifiers([], None) == set()


# ── BP-604: _validate_fallback_tool_call ─────────────────────────────────────


class TestValidateFallbackToolCall:
    """Q2 MSTR canary regression: drift to a different entity must reject."""

    def test_q2_mstr_canary_rejects_on_semiconductor(self) -> None:
        """The exact Q2 trace: prior call had entity_tickers=["MSTR"], next
        call hallucinates entity_name="ON Semiconductor Corporation".  This
        is the single most important assertion in this file — if this test
        regresses, the HARMFUL fault class returns.
        """
        mstr_uuid = uuid4()
        question_ids = _collect_question_entity_identifiers(
            [_FakeEntity(entity_id=mstr_uuid, ticker="MSTR", canonical_name="MicroStrategy Inc.")],
            None,
        )
        prior = [_FakeToolCall(name="search_documents", input={"entity_tickers": ["MSTR"]})]
        drift = _FakeToolCall(
            name="search_claims",
            input={"entity_name": "ON Semiconductor Corporation"},
        )
        reason = _validate_fallback_tool_call(prior, drift, question_ids)
        assert reason is not None
        assert "ON Semiconductor Corporation" in reason
        assert "entity_name" in reason

    def test_admits_call_with_question_entity_by_ticker(self) -> None:
        question_ids = _collect_question_entity_identifiers(
            [_FakeEntity(entity_id=uuid4(), ticker="AAPL", canonical_name="Apple Inc.")], None
        )
        call = _FakeToolCall(name="search_documents", input={"entity_tickers": ["AAPL"]})
        assert _validate_fallback_tool_call([], call, question_ids) is None

    def test_admits_call_with_question_entity_by_name(self) -> None:
        question_ids = _collect_question_entity_identifiers(
            [_FakeEntity(entity_id=uuid4(), ticker="AAPL", canonical_name="Apple Inc.")], None
        )
        call = _FakeToolCall(name="search_claims", input={"entity_name": "Apple Inc."})
        assert _validate_fallback_tool_call([], call, question_ids) is None

    def test_admits_entity_surfaced_by_prior_tool_call(self) -> None:
        """A peer entity introduced by a prior call must be admitted — the
        LLM legitimately drills into it on the next iteration.
        """
        question_ids = _collect_question_entity_identifiers(
            [_FakeEntity(entity_id=uuid4(), ticker="MSTR", canonical_name="MicroStrategy")], None
        )
        prior = [_FakeToolCall(name="search_documents", input={"entity_tickers": ["MSTR", "BTC"]})]
        # The follow-up names BTC — surfaced by the prior call, so admitted.
        next_call = _FakeToolCall(name="search_claims", input={"entity_name": "BTC"})
        assert _validate_fallback_tool_call(prior, next_call, question_ids) is None

    def test_non_entity_fields_are_not_validated(self) -> None:
        """Free-text query / date / source fields may vary freely."""
        question_ids = {"mstr"}
        call = _FakeToolCall(
            name="search_documents",
            input={"query": "some random text", "date_from": "2026-01-01"},
        )
        assert _validate_fallback_tool_call([], call, question_ids) is None

    def test_empty_input_admits(self) -> None:
        call = _FakeToolCall(name="get_market_movers", input={})
        assert _validate_fallback_tool_call([], call, {"mstr"}) is None


# ── BP-605: _check_entity_grounding ──────────────────────────────────────────


class TestCheckEntityGrounding:
    def test_q2_mstr_canary_refuses_on_semi_synthesis(self) -> None:
        """Question = MSTR; every retrieved item cites ON Semiconductor →
        refusal. Without this guard, the synthesis produces a confident,
        well-cited answer about the wrong company (the Q2 HARMFUL fault).
        """
        question_ids = {"mstr", "microstrategy inc."}
        items = [
            _FakeRetrievedItem(citation_meta=_FakeCitationMeta(entity_name="ON Semiconductor")),
            _FakeRetrievedItem(citation_meta=_FakeCitationMeta(entity_name="ON Semiconductor Corp")),
        ]
        refusal = _check_entity_grounding(items, question_ids)
        assert refusal is not None
        assert "cannot find information" in refusal.lower()

    def test_at_least_one_overlap_admits(self) -> None:
        question_ids = {"mstr"}
        items = [
            _FakeRetrievedItem(citation_meta=_FakeCitationMeta(entity_name="Peer Co")),
            _FakeRetrievedItem(citation_meta=_FakeCitationMeta(entity_name="MSTR")),  # match
        ]
        assert _check_entity_grounding(items, question_ids) is None

    def test_overlap_via_entity_id_field(self) -> None:
        u = uuid4()
        question_ids = _normalise_entity_identifier(u)
        items = [_FakeRetrievedItem(entity_id=u)]
        assert _check_entity_grounding(items, question_ids) is None

    def test_empty_question_entities_skips_check(self) -> None:
        items = [_FakeRetrievedItem(citation_meta=_FakeCitationMeta(entity_name="Anything"))]
        assert _check_entity_grounding(items, set()) is None

    def test_empty_retrieved_items_skips_check(self) -> None:
        # When no items were retrieved a different guard handles that path
        # (the all-tools-failed / consecutive-errors logic).
        assert _check_entity_grounding([], {"mstr"}) is None


# ── _collect_prior_tool_entity_identifiers ───────────────────────────────────


class TestCollectPriorToolEntityIdentifiers:
    def test_collects_across_multiple_calls_and_fields(self) -> None:
        prior = [
            _FakeToolCall(name="search_documents", input={"entity_tickers": ["MSTR", "AAPL"]}),
            _FakeToolCall(name="search_claims", input={"entity_name": "Tesla"}),
            _FakeToolCall(name="get_price_history", input={"query": "ignored"}),
        ]
        ids = _collect_prior_tool_entity_identifiers(prior)
        assert ids == {"mstr", "aapl", "tesla"}
