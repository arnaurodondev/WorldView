"""PLAN-0103 W26 / BP-644 — entity-grounding guard text-token fallback.

Round 2 chat benchmark Q4 (TSLA gross margin) refused because the singular
``get_fundamentals_history`` handler did not set ``citation_meta.entity_name``
on its RetrievedItem. The BP-605 guard saw an empty entity-id set and
short-circuited to a refusal — the exact "data returned referenced different
entities" Round 2 fingerprint.

W26 ships two complementary fixes:
  * the singular handler now binds ``entity_name=<ticker>`` on the item
    (regression covered in test_fundamentals_snapshot.py);
  * the guard now ALSO scans each item's ``text`` for whole-word matches of
    any question entity token, so items rendered without a citation_meta
    (legacy handlers, future tools) still pass the grounding check when the
    ticker is visible in the rendered output.

These tests pin BOTH halves so a future revert of either path is caught.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from rag_chat.application.use_cases.chat_orchestrator import _check_entity_grounding

pytestmark = pytest.mark.unit


@dataclass
class _FakeItem:
    """Minimal stand-in for ``RetrievedItem`` — only the attrs the guard reads."""

    text: str = ""
    entity_id: str | None = None
    citation_meta: Any = None


def test_item_with_no_citation_meta_passes_when_text_has_question_token() -> None:
    """The TSLA gross-margin regression: text-only match must admit the item."""
    item = _FakeItem(
        text=(
            "TSLA quarterly fundamentals (Periodicity: QUARTERLY)\n"
            "| Period | Revenue | EPS |\n"
            "| Q1 FY2026 | $25.5B | 0.73 |"
        ),
        entity_id=None,
        citation_meta=None,
    )
    result = _check_entity_grounding([item], {"tsla"})
    assert result is None, "text-token fallback failed to admit a valid TSLA item"


def test_unrelated_item_still_refused() -> None:
    """Defence: an item with neither metadata nor text mention must refuse.

    Pre-W26 this returned a refusal too, so the test pins the failure-mode
    boundary remains unchanged.
    """
    item = _FakeItem(
        text="NVDA quarterly fundamentals\n| Q1 FY2026 | $44.0B |",
        entity_id="nvda-uuid",
        citation_meta=None,
    )
    result = _check_entity_grounding([item], {"tsla"})
    assert result is not None
    assert "different entities" in result


# ── BUG-1 (2026-07-01) — prediction markets are topic-matched, not entity-scoped ─


@dataclass
class _FakeCitationMeta:
    source_name: str | None = None
    entity_name: str | None = None


def test_polymarket_item_is_exempt_from_entity_grounding() -> None:
    """A topic-matched polymarket item grounds even when question entities don't overlap.

    Entity resolution routinely mis-scopes prediction queries (e.g. "odds for
    Nikki Haley" → "The US"), so no entity overlap could ever be found and the
    guard refused a valid markets answer (entity_grounding_failed
    item_entity_names:[null,null]). The guard now exempts polymarket items.
    """
    item = _FakeItem(
        text="## Will Nikki Haley win the 2028 nomination?\n- Implied odds: Yes 12%, No 88%",
        entity_id=None,
        citation_meta=_FakeCitationMeta(source_name="polymarket", entity_name="Politics"),
    )
    # Question resolved to an unrelated entity ("the us") — no overlap possible.
    result = _check_entity_grounding([item], {"the us"})
    assert result is None, "polymarket items must be exempt from the entity-grounding refusal"


def test_non_polymarket_item_still_refused_when_unrelated() -> None:
    """The exemption is scoped to polymarket only — other sources still refuse."""
    item = _FakeItem(
        text="Some unrelated news about the US economy.",
        entity_id=None,
        citation_meta=_FakeCitationMeta(source_name="news", entity_name="United States"),
    )
    result = _check_entity_grounding([item], {"nvda"})
    assert result is not None
    assert "different entities" in result


def test_substring_match_does_not_admit() -> None:
    """Whole-word check: "TS" should NOT match because of the 2-char floor.

    But "TSLA" inside "TSLA," or "TSLA:" SHOULD match. We pin both halves.
    """
    # 2-char tokens are allowed in principle, but "ts" inside "Costco" must
    # not satisfy the guard because of the whole-word boundary check.
    item_bad = _FakeItem(text="Costco fundamentals — COSTCO")
    assert _check_entity_grounding([item_bad], {"ts"}) is not None

    # Whole-word match with punctuation boundary is fine.
    item_good = _FakeItem(text="Snapshot: TSLA, AAPL, MSFT compared.")
    assert _check_entity_grounding([item_good], {"tsla"}) is None


def test_citation_meta_match_still_wins_first() -> None:
    """Forward-compat: citation_meta path remains the primary admission rule."""

    @dataclass
    class _CM:
        entity_name: str | None = None

    item = _FakeItem(
        text="some unrelated text",  # text would refuse on its own
        entity_id=None,
        citation_meta=_CM(entity_name="TSLA"),
    )
    assert _check_entity_grounding([item], {"tsla"}) is None


def test_item_id_carrying_symbol_admits_item_bp668() -> None:
    """BP-668 ext — the live BTC-USD refusal: symbol only present in item_id.

    ``get_price_history`` items used to carry no citation_meta and the
    rendered table may omit the symbol — the ONLY place "BTC-USD" appeared
    was the item id ``tool:price_history:BTC-USD:latest_1m``. The guard must
    scan the id (':' separators act as word delimiters) so a correct price
    answer is not replaced by the "different entities" refusal.
    """
    item = _FakeItem(
        text="| time | open | close |\n| 09:35 | 62,800.10 | 62,846.70 |",
        entity_id=None,
        citation_meta=None,
    )
    item.__dict__["item_id"] = "tool:price_history:BTC-USD:latest_1m"

    refusal = _check_entity_grounding([item], {"btc-usd", "019e0db3-6c19-77b6-86c4-43fa2dd47b49"})
    assert refusal is None


def test_head_word_variant_matches_possessive_title_bp670() -> None:
    """'apple inc.' question id must ground against a title saying "Apple's"."""
    item = _FakeItem(
        text="Apple's AI Push Deepens Alphabet Dependency\n  Source: news",
        entity_id=None,
        citation_meta=None,
    )
    refusal = _check_entity_grounding([item], {"apple inc.", "01900000-0000-7000-8000-000000001001"})
    assert refusal is None


def test_short_head_word_does_not_over_match_bp670() -> None:
    """'ON Semiconductor Corp.' must NOT contribute the token 'on'."""
    item = _FakeItem(
        text="Markets traded on heavy volume across the board today.",
        entity_id=None,
        citation_meta=None,
    )
    refusal = _check_entity_grounding([item], {"on semiconductor corp."})
    assert refusal is not None
