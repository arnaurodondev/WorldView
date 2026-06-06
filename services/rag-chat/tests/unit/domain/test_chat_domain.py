"""Unit tests for S8 domain entities (Wave D-1).

Tests: T-D-1-01 (chat.py) and T-D-1-02 (conversation.py).
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000003")


# ── compute_recency_score ─────────────────────────────────────────────────────


class TestComputeRecencyScore:
    def test_recency_score_none_published_at(self) -> None:
        """None published_at → neutral score of 0.5."""
        from rag_chat.domain.entities.chat import compute_recency_score

        assert compute_recency_score(None) == 0.5

    def test_recency_score_365_days(self) -> None:
        """365-day-old item with default source → exp(-0.005 * 365) ≈ 0.1613."""
        from rag_chat.domain.entities.chat import compute_recency_score

        published = datetime.now(tz=UTC) - timedelta(days=365)
        score = compute_recency_score(published, source_type=None)  # explicit: default rate=0.005
        expected = math.exp(-0.005 * 365)
        assert abs(score - expected) < 1e-6

    def test_recency_score_today(self) -> None:
        """Item published today with default source → score close to 1.0."""
        from rag_chat.domain.entities.chat import compute_recency_score

        published = datetime.now(tz=UTC)
        score = compute_recency_score(published, source_type=None)  # explicit: default rate=0.005
        assert score > 0.99


# ── RetrievedItem fusion_score invariant ──────────────────────────────────────


class TestRetrievedItemFusionScore:
    def test_fusion_score_invariant_via_factory(self) -> None:
        """create() computes fusion_score = score * recency * trust automatically."""
        from rag_chat.domain.entities.chat import RetrievedItem
        from rag_chat.domain.enums import ItemType

        item = RetrievedItem.create(
            item_id="chunk-1",
            item_type=ItemType.chunk,
            text="Apple reported strong earnings.",
            score=0.85,
            trust_weight=0.70,
            published_at=None,
        )
        expected = 0.85 * 0.5 * 0.70  # recency_score=0.5 (no published_at)
        assert abs(item.fusion_score - expected) < 1e-9

    def test_fusion_score_invariant_enforced_on_construction(self) -> None:
        """Constructing RetrievedItem with inconsistent fusion_score raises ValueError."""
        from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
        from rag_chat.domain.enums import ItemType

        with pytest.raises(ValueError, match="fusion_score invariant"):
            RetrievedItem(
                item_id="bad",
                item_type=ItemType.chunk,
                text="x",
                score=0.9,
                recency_score=0.8,
                trust_weight=0.7,
                fusion_score=0.99,  # wrong: should be 0.9*0.8*0.7=0.504
                citation_meta=CitationMeta(None, None, None, None, None),
            )


# ── ChatContext validation ────────────────────────────────────────────────────


class TestChatContext:
    def test_max_5_entity_ids(self) -> None:
        """More than 5 entity_ids → ValueError."""
        from rag_chat.domain.entities.chat import ChatContext

        ids = tuple(uuid4() for _ in range(6))
        with pytest.raises(ValueError, match="exceeds maximum of 5"):
            ChatContext(entity_ids=ids)

    def test_exactly_5_entity_ids_allowed(self) -> None:
        """Exactly 5 entity_ids is valid."""
        from rag_chat.domain.entities.chat import ChatContext

        ids = tuple(uuid4() for _ in range(5))
        ctx = ChatContext(entity_ids=ids)
        assert len(ctx.entity_ids) == 5


# ── DateRange validation ───────────────────────────────────────────────────────


class TestDateRange:
    def test_start_after_end_raises(self) -> None:
        """start > end → ValueError."""
        from rag_chat.domain.value_objects import DateRange

        with pytest.raises(ValueError, match="must be <="):
            DateRange(start=date(2024, 12, 31), end=date(2024, 1, 1))

    def test_valid_range_allowed(self) -> None:
        """start <= end is valid."""
        from rag_chat.domain.value_objects import DateRange

        dr = DateRange(start=date(2024, 1, 1), end=date(2024, 12, 31))
        assert dr.start < dr.end  # type: ignore[operator]


# ── QueryIntent completeness ───────────────────────────────────────────────────


class TestQueryIntent:
    def test_all_8_values_accessible(self) -> None:
        """All 10 QueryIntent values are present (7 original + GENERAL +
        MACRO + CONTRADICTION).

        MACRO was added in PLAN-0093 Wave E-1 so the macro/calendar tool
        family has its own per-intent prompt and rerank weight bucket.
        CONTRADICTION was added in PLAN-0093 ITER-9 (F-LIVE-O) so
        "what contradicts X" questions route to a dedicated prompt.
        """
        from rag_chat.domain.enums import QueryIntent

        expected = {
            "FACTUAL_LOOKUP",
            "RELATIONSHIP",
            "SIGNAL_INTEL",
            "FINANCIAL_DATA",
            "COMPARISON",
            "REASONING",
            "PORTFOLIO",
            "GENERAL",  # added PRD-0016 Wave A-1
            "MACRO",  # added PLAN-0093 Wave E-1
            "CONTRADICTION",  # added PLAN-0093 ITER-9 (F-LIVE-O)
        }
        actual = {v.value for v in QueryIntent}
        assert actual == expected


# ── ConversationThread properties ─────────────────────────────────────────────


class TestConversationThread:
    def _make_thread(self, n_messages: int = 0, archived: bool = False) -> object:
        from rag_chat.domain.entities.conversation import ConversationThread, Message
        from rag_chat.domain.enums import MessageRole

        now = datetime.now(tz=UTC)
        msgs = tuple(
            Message(
                message_id=uuid4(),
                thread_id=uuid4(),
                role=MessageRole.user,
                content=f"msg {i}",
                created_at=now,
            )
            for i in range(n_messages)
        )
        return ConversationThread(
            thread_id=uuid4(),
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            created_at=now,
            updated_at=now,
            messages=msgs,
            archived_at=now if archived else None,
        )

    def test_is_active_when_not_archived(self) -> None:
        """archived_at=None → is_active=True."""
        thread = self._make_thread()
        assert thread.is_active is True  # type: ignore[union-attr]

    def test_is_not_active_when_archived(self) -> None:
        """archived_at set → is_active=False."""
        thread = self._make_thread(archived=True)
        assert thread.is_active is False  # type: ignore[union-attr]

    def test_recent_history_returns_last_n(self) -> None:
        """7 messages, n=5 → last 5 returned in order."""
        thread = self._make_thread(n_messages=7)
        history = thread.recent_history(5)  # type: ignore[union-attr]
        assert len(history) == 5
        assert history == thread.messages[-5:]  # type: ignore[union-attr]

    def test_recent_history_n_larger_than_messages(self) -> None:
        """n > len(messages) → all messages returned."""
        thread = self._make_thread(n_messages=3)
        history = thread.recent_history(10)  # type: ignore[union-attr]
        assert len(history) == 3

    def test_recent_history_zero_returns_empty(self) -> None:
        """n=0 → empty tuple."""
        thread = self._make_thread(n_messages=3)
        assert thread.recent_history(0) == ()  # type: ignore[union-attr]
