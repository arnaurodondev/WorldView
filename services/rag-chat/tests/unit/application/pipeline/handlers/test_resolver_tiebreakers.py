"""FIX-LIVE-O — entity-resolver tiebreaker tests.

The previous implementation of ``IntelligenceHandler._resolve_entity_by_name``
would return ``None`` (refuse to resolve) any time the top two alias-search
candidates were within 0.10 similarity of each other. That over-zealous gate
caused the live agent to bail on Q7 ("What contradictions exist around
Tesla's outlook?") even though the two top candidates were:

    Teslas    sim 0.625  → entity_id A
    Tesla Inc sim 0.600  → entity_id B (the actual Tesla canonical)

The fix layers three tiebreakers before the legacy ambiguous-bail path:
    (1) same-canonical collapse — top-K all share entity_id
    (2) exact canonical-name match — alias_text == query (suffix-tolerant)
    (3) length-penalty fallback — clear length-distance winner

Each tiebreaker emits a structured ``entity_resolution_tiebreaker_applied``
log event so the resolution path is auditable in production.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# Stable IDs for the tests — using uuid7-shaped values for realism.
_ID_A = UUID("01900000-0000-7000-8000-00000000000a")
_ID_B = UUID("01900000-0000-7000-8000-00000000000b")


def _make_handler(s7: AsyncMock) -> Any:
    """Construct an IntelligenceHandler with no scoped entity_context.

    The resolver only exercises the alias-search path when entity_context
    is None (otherwise the scoped entity is returned directly).
    """
    from rag_chat.application.pipeline.handlers.intelligence import IntelligenceHandler

    return IntelligenceHandler(s7=s7, entity_context=None, timeout=5.0)


def _s7_with_candidates(candidates: list[dict[str, Any]]) -> AsyncMock:
    """Build a mocked S7Port whose ``resolve_entity_by_name`` returns ``candidates``."""
    s7 = AsyncMock()
    s7.resolve_entity_by_name.return_value = candidates
    return s7


class TestResolverTiebreakers:
    """FIX-LIVE-O — three tiebreakers applied in order when |Δsim| < 0.10."""

    @pytest.mark.asyncio
    async def test_resolver_same_canonical_collapse(self, capsys: Any) -> None:
        """Rule 1: top-K candidates all share entity_id → resolve to that id.

        Same canonical entity surfaced under two different aliases — the
        "ambiguity" is illusory because both rows point at the same
        underlying record. The resolver should pick the highest-similarity
        row (candidates[0]) and emit the tiebreaker log.
        """
        candidates = [
            {"entity_id": str(_ID_A), "alias_text": "Acme Corp", "similarity": 0.72},
            {"entity_id": str(_ID_A), "alias_text": "ACME", "similarity": 0.66},
        ]
        s7 = _s7_with_candidates(candidates)
        handler = _make_handler(s7)

        resolved = await handler._resolve_entity_by_name("get_contradictions", "Acme")

        assert resolved == _ID_A
        out = capsys.readouterr()
        combined = out.out + out.err
        # The tiebreaker fired with the correct rule label.
        assert "entity_resolution_tiebreaker_applied" in combined
        assert "same_canonical_collapse" in combined
        # And the ambiguous-bail event did NOT fire.
        assert "tool_entity_ambiguous" not in combined

    @pytest.mark.asyncio
    async def test_resolver_exact_canonical_name_preferred(self, capsys: Any) -> None:
        """Rule 2: exact canonical-name match wins even with lower similarity.

        This is the Tesla case from the live log: a noisy plural alias
        ("Teslas") outranked the canonical alias ("Tesla Inc") on raw
        embedding similarity, so the previous resolver picked the wrong
        canonical id (or, with the 0.10 gate, bailed). The fix: when one
        candidate's alias_text (suffix-stripped) equals the query, that
        candidate wins regardless of similarity ordering.
        """
        candidates = [
            # alias_text "Teslas" with higher similarity but wrong canonical.
            {"entity_id": str(_ID_A), "alias_text": "Teslas", "similarity": 0.625},
            # alias_text "Tesla Inc" → suffix-stripped "tesla" == query.
            {"entity_id": str(_ID_B), "alias_text": "Tesla Inc", "similarity": 0.600},
        ]
        s7 = _s7_with_candidates(candidates)
        handler = _make_handler(s7)

        resolved = await handler._resolve_entity_by_name("get_contradictions", "Tesla")

        assert resolved == _ID_B  # the canonical Tesla wins, not "Teslas"
        out = capsys.readouterr()
        combined = out.out + out.err
        assert "entity_resolution_tiebreaker_applied" in combined
        assert "exact_canonical_name" in combined
        assert "tool_entity_ambiguous" not in combined

    @pytest.mark.asyncio
    async def test_resolver_still_ambiguous_when_genuinely_different(self, capsys: Any) -> None:
        """Genuinely ambiguous candidates → no rule fires → resolver returns None.

        Query "Apple" against two truly distinct canonicals where neither
        alias_text normalizes to "apple" (so rule 2 can't fire), the
        canonicals differ (so rule 1 can't fire), and length distances are
        close enough that the conservative length-penalty rule 3 also
        cannot meaningfully disambiguate. The resolver must fall through
        to the legacy ambiguity-bail path and emit the
        ``tool_entity_ambiguous`` log.
        """
        candidates = [
            # "Apple Computer" → normalized "apple computer" (no suffix match).
            # length 14 vs query length 5 → diff 9.
            {"entity_id": str(_ID_A), "alias_text": "Apple Computer", "similarity": 0.90},
            # "Apple Records" → normalized "apple records". length 13 → diff 8.
            # Delta(top vs best) = 9 - 8 = 1, below the 2-char gap → rule 3 skips.
            {"entity_id": str(_ID_B), "alias_text": "Apple Records", "similarity": 0.88},
        ]
        s7 = _s7_with_candidates(candidates)
        handler = _make_handler(s7)

        resolved = await handler._resolve_entity_by_name("get_contradictions", "Apple")

        assert resolved is None
        out = capsys.readouterr()
        combined = out.out + out.err
        # The legacy ambiguous warning fires.
        assert "tool_entity_ambiguous" in combined
        # And no tiebreaker should have fired.
        assert "entity_resolution_tiebreaker_applied" not in combined
