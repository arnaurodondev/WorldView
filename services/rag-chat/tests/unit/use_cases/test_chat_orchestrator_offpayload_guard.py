"""Cat-B FIX 3 — deterministic off-payload ticker guard.

Unit coverage for the pure module-level guard added to ``chat_orchestrator.py``
(docs/audits/2026-06-28-cat-b-screener-missingness.md, B1):

``find_off_payload_tickers`` / ``strip_off_payload_ticker_lines`` — for
screener/listing questions, flag/strip structured ranking rows whose lead ticker
was NOT in any tool result (the model padding a distrusted screen with its own
world knowledge — the AI-chip allowlist for ``ru_ai_semi_screener``, KEYS/HPE for
``iter3_top5_tech_marketcap``).

The guard only calls ``getattr(item, "text" | "ticker" | "citation_meta", …)``,
so a lightweight dataclass double keeps the wiring minimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from rag_chat.application.use_cases.chat_orchestrator import (
    find_off_payload_tickers,
    strip_off_payload_ticker_lines,
)

pytestmark = pytest.mark.unit


@dataclass
class _FakeItem:
    text: str | None = None
    ticker: str | None = None
    canonical_name: str | None = None
    entity_name: str | None = None
    citation_meta: Any = None


def _screener_items() -> list[_FakeItem]:
    """A screener payload whose rendered rows carry QRVO/SWKS/ALGM (the real
    ``ru_ai_semi_screener`` cohort) — the only tickers the answer may name."""
    return [
        _FakeItem(
            text=(
                "Technology / Semiconductors screen (3 rows):\n"
                "  QRVO — Qorvo Inc | MCap: $8.7B\n"
                "  SWKS — Skyworks Solutions | MCap: $11.1B\n"
                "  ALGM — Allegro MicroSystems | MCap: $11.5B\n"
            )
        )
    ]


def test_off_payload_flags_ai_chip_allowlist() -> None:
    """The model pads a screen answer with its own AI-chip allowlist
    (NVDA/AMD/AVGO/…) that the tool never returned → all flagged."""
    answer = (
        "Top AI-semiconductor names:\n"
        "| Ticker | MCap |\n"
        "|--------|------|\n"
        "| NVDA | $3.0T |\n"
        "| AMD | $240B |\n"
        "| AVGO | $700B |\n"
    )
    off = find_off_payload_tickers(
        question="Screen for AI semiconductor companies with market cap above $50B.",
        answer=answer,
        tool_items=_screener_items(),
        called_tool_names=["screen_universe"],
    )
    assert off == {"NVDA", "AMD", "AVGO"}


def test_off_payload_passes_payload_tickers() -> None:
    """An answer that lists ONLY the returned QRVO/SWKS/ALGM is clean."""
    answer = (
        "| Ticker | MCap |\n" "|--------|------|\n" "| QRVO | $8.7B |\n" "| SWKS | $11.1B |\n" "| ALGM | $11.5B |\n"
    )
    off = find_off_payload_tickers(
        question="List the semiconductors the screener returned.",
        answer=answer,
        tool_items=_screener_items(),
        called_tool_names=["screen_universe"],
    )
    assert off == set()


def test_off_payload_ignores_acronyms_and_period_labels() -> None:
    """US / YoY / ETF / Q4 / FY2024 are ticker-shaped but not tickers — never
    flagged, even in a structured row."""
    answer = (
        "| Scope | Metric | Period |\n"
        "|-------|--------|--------|\n"
        "| US | YoY | Q4 FY2024 |\n"
        "| QRVO | EPS | Q1 2025 |\n"
    )
    off = find_off_payload_tickers(
        question="List US tech stocks ranked by market cap.",
        answer=answer,
        tool_items=_screener_items(),
        called_tool_names=["screen_universe"],
    )
    assert off == set()


def test_off_payload_does_not_fire_on_non_listing_question() -> None:
    """A single-entity intelligence question is never gated — a peer mentioned in
    prose must not be stripped."""
    off = find_off_payload_tickers(
        question="What is the latest news on Apple?",
        answer="Apple competes with NVDA and AMD in AI silicon.",
        tool_items=_screener_items(),
        called_tool_names=["get_entity_intelligence"],
    )
    assert off == set()


def test_off_payload_does_not_fire_without_universe_tool() -> None:
    """No universe/aggregate tool ran → guard is a no-op even for a listing
    question (nothing to anchor the payload set against)."""
    off = find_off_payload_tickers(
        question="List the top 5 tech companies by market cap.",
        answer="| KEYS | $63.8B |\n| HPE | $55.6B |\n",
        tool_items=[_FakeItem(text="some narrative text")],
        called_tool_names=["search_documents"],
    )
    assert off == set()


def test_off_payload_does_not_fire_on_empty_payload() -> None:
    """An empty/failed screen (no payload tickers) is handled by the refusal
    guards — the off-payload guard must NOT strip every answer token."""
    off = find_off_payload_tickers(
        question="List the top 5 tech companies by market cap.",
        answer="| KEYS | $63.8B |\n",
        tool_items=[_FakeItem(text="screen returned 0 rows")],
        called_tool_names=["screen_universe"],
    )
    assert off == set()


def test_off_payload_ignores_prose_tickers() -> None:
    """Tickers in free prose (not a table/list row) are never collected."""
    off = find_off_payload_tickers(
        question="Screen for the largest semiconductor companies.",
        answer="The screener returned QRVO, SWKS and ALGM. NVDA was not in scope.",
        tool_items=_screener_items(),
        called_tool_names=["screen_universe"],
    )
    assert off == set()


def test_strip_off_payload_removes_only_offending_rows() -> None:
    """The strip drops the fabricated KEYS/HPE rows but keeps the real FLEX
    row and the header."""
    answer = (
        "| Ticker | MCap |\n" "|--------|------|\n" "| KEYS | $63.8B |\n" "| HPE | $55.6B |\n" "| FLEX | $55.63B |\n"
    )
    stripped = strip_off_payload_ticker_lines(answer, {"KEYS", "HPE"})
    assert "KEYS" not in stripped
    assert "HPE" not in stripped
    assert "FLEX" in stripped
    assert "| Ticker | MCap |" in stripped


def test_strip_off_payload_keeps_answer_if_it_would_empty() -> None:
    """If every line is off-payload, the strip leaves the answer unchanged so the
    caller appends a flag instead of shipping an empty answer."""
    answer = "| KEYS | $63.8B |\n| HPE | $55.6B |\n"
    stripped = strip_off_payload_ticker_lines(answer, {"KEYS", "HPE"})
    assert stripped == answer
