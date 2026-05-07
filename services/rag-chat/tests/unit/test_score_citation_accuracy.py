"""Unit tests for ScoreCitationAccuracyUseCase and iter_cited_claims — PLAN-0063 W5-5 T-W5-5-02."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from rag_chat.domain.entities.conversation import Citation, Message
from rag_chat.domain.enums import MessageRole

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────


def _msg(content: str, citations: tuple[Citation, ...] = ()) -> Message:
    return Message(
        message_id=uuid4(),
        thread_id=uuid4(),
        role=MessageRole.assistant,
        content=content,
        created_at=datetime.now(tz=UTC),
        citations=citations,
    )


def _cite(ref: int, title: str = "Article title") -> Citation:
    return Citation(ref=ref, item_type="chunk", id=str(uuid4()), title=title)


# ── iter_cited_claims ─────────────────────────────────────────────────────────


class TestIterCitedClaims:
    def test_iter_cited_claims_extracts_lead_sentence(self) -> None:
        """lead='Foo [c1] bar.' → yields exactly ('Foo [c1] bar.', 'c1')."""
        from rag_chat.application.use_cases.score_citation_accuracy import iter_cited_claims

        msg = _msg("Foo [c1] bar.", (_cite(1),))
        pairs = list(iter_cited_claims(msg))
        assert pairs == [("Foo [c1] bar.", "c1")]

    def test_iter_cited_claims_extracts_per_bullet(self) -> None:
        """Bullet text 'X happened [c1] [c2]' → yields two tuples with same sentence."""
        from rag_chat.application.use_cases.score_citation_accuracy import iter_cited_claims

        content = "X happened [c1] [c2]"
        msg = _msg(content, (_cite(1), _cite(2)))
        pairs = list(iter_cited_claims(msg))
        assert ("X happened [c1] [c2]", "c1") in pairs
        assert ("X happened [c1] [c2]", "c2") in pairs

    def test_iter_cited_claims_handles_multi_marker_lead_sentence(self) -> None:
        """'Foo [c1] and bar [c3].' → yields 2 tuples sharing the same sentence."""
        from rag_chat.application.use_cases.score_citation_accuracy import iter_cited_claims

        msg = _msg("Foo [c1] and bar [c3].", (_cite(1), _cite(3)))
        pairs = list(iter_cited_claims(msg))
        assert len(pairs) == 2
        sentences = {p[0] for p in pairs}
        assert sentences == {"Foo [c1] and bar [c3]."}
        assert ("Foo [c1] and bar [c3].", "c1") in pairs
        assert ("Foo [c1] and bar [c3].", "c3") in pairs

    def test_iter_cited_claims_falls_back_to_msg_text_for_non_brief(self) -> None:
        """Plain chat message without [cN] markers → full content paired per citation."""
        from rag_chat.application.use_cases.score_citation_accuracy import iter_cited_claims

        content = "The company reported record earnings this quarter."
        msg = _msg(content, (_cite(1), _cite(2)))
        pairs = list(iter_cited_claims(msg))
        assert len(pairs) == 2
        assert all(claim == content for claim, _ in pairs)
        assert {cid for _, cid in pairs} == {"c1", "c2"}


# ── ScoreCitationAccuracyUseCase ──────────────────────────────────────────────


class TestScoreCitationAccuracyUseCase:
    def _make_uc(self, messages: list[Message], judge_return: str = "2") -> object:
        from rag_chat.application.use_cases.score_citation_accuracy import ScoreCitationAccuracyUseCase

        repo = MagicMock()
        repo.sample_recent_with_citations = AsyncMock(return_value=messages)

        judge = MagicMock()
        judge.score_citation = AsyncMock(return_value=judge_return)

        return ScoreCitationAccuracyUseCase(message_repo=repo, llm_judge=judge)

    @pytest.mark.asyncio
    async def test_score_citation_accuracy_with_50_samples(self) -> None:
        """50 messages x 1 citation each, judge always returns 2 → mean ≈ 2/3."""
        msgs = [_msg("Claim text [c1].", (_cite(1),)) for _ in range(50)]
        uc = self._make_uc(msgs, judge_return="2")
        result = await uc.execute()
        assert abs(result - 2 / 3) < 1e-4

    @pytest.mark.asyncio
    async def test_score_citation_accuracy_insufficient_samples_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Only 5 samples (< 10 minimum) → returns 0.0 without crashing."""
        msgs = [_msg("Claim [c1].", (_cite(1),)) for _ in range(5)]
        uc = self._make_uc(msgs)
        result = await uc.execute()
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_score_citation_accuracy_no_samples_returns_zero(self) -> None:
        """0 samples → returns 0.0, no exception."""
        uc = self._make_uc([])
        result = await uc.execute()
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_score_citation_accuracy_emits_gauge(self) -> None:
        """After execution the rag_citation_accuracy gauge reflects the mean score."""
        from prometheus_client import REGISTRY

        msgs = [_msg("Revenue beat [c1].", (_cite(1, title="AAPL Q4 Earnings"),)) for _ in range(20)]
        uc = self._make_uc(msgs, judge_return="3")
        await uc.execute()

        gauge_value: float | None = None
        for m in REGISTRY.collect():
            if m.name == "rag_citation_accuracy":
                for s in m.samples:
                    gauge_value = s.value
        assert gauge_value is not None
        assert abs(gauge_value - 1.0) < 1e-4  # 3/3 = 1.0

    @pytest.mark.asyncio
    async def test_judge_returns_invalid_response_skipped(self) -> None:
        """LLM returns 'banana' → that pair is skipped, score is 0.0 (no valid scores)."""
        msgs = [_msg("Claim [c1].", (_cite(1),)) for _ in range(20)]
        uc = self._make_uc(msgs, judge_return="banana")
        result = await uc.execute()
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_judge_synthesis_claim_scored_at_least_2(self) -> None:
        """Synthesis claim with a supporting snippet → judge returns ≥2 (mock validates rubric)."""
        msgs = [
            _msg("Three signals point to hawkish pivot [c1].", (_cite(1, title="Fed hints at slower rate cuts"),))
            for _ in range(20)
        ]
        uc = self._make_uc(msgs, judge_return="2")
        result = await uc.execute()
        assert result >= 2 / 3 - 1e-4
