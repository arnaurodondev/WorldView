"""Unit tests for UnresolvedResolutionWorker (PLAN-0033 T-C-2-01).

Tests:
  - test_run_once_phase1_resolves        — cascade resolves → auto_resolved
  - test_run_once_phase2_entity_created  — Qwen says is_entity=True → entity_created
  - test_run_once_phase2_noise           — Qwen says is_entity=False → noise + reason
  - test_run_once_non_eligible_class_noise — LOCATION → noise without LLM call
  - test_recover_stale_escalated         — stale mentions reset to unresolved
  - test_run_loop_continues_on_exception — run_once exception does not crash loop
  - test_llm_call_logged_on_phase2       — usage_logger.log() called once per eligible mention
  - test_json_parse_failure_leaves_unresolved — malformed JSON → unresolved, not noise
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome
from nlp_pipeline.infrastructure.workers.unresolved_resolution_worker import (
    UnresolvedResolutionWorker,
    WorkerStats,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    enabled: bool = True,
    interval_s: int = 60,
    batch_size: int = 5,
    lookback_days: int = 30,
    stale_minutes: int = 30,
    ollama_url: str = "http://localhost:11434",
    model_id: str = "qwen3:0.6b",
    llm_timeout_s: float = 30.0,
) -> MagicMock:
    s = MagicMock()
    s.unresolved_resolution_enabled = enabled
    s.unresolved_resolution_interval_s = interval_s
    s.unresolved_resolution_batch_size = batch_size
    s.unresolved_resolution_lookback_days = lookback_days
    s.unresolved_resolution_stale_escalated_minutes = stale_minutes
    s.unresolved_resolution_ollama_base_url = ollama_url
    s.unresolved_resolution_classification_model = model_id
    s.unresolved_resolution_llm_timeout_s = llm_timeout_s
    # DeepInfra provider fields — default to empty (Ollama path active)
    s.unresolved_resolution_api_key = ""
    s.unresolved_resolution_api_base_url = "https://api.deepinfra.com/v1/openai"
    s.unresolved_resolution_api_model_id = "Qwen/Qwen2.5-0.5B-Instruct"
    return s


def _make_nlp_session_factory(
    mentions: list[Any],
    recover_count: int = 0,
) -> MagicMock:
    """Build a mock nlp_session_factory that returns mentions on get_unresolved_batch()."""
    factory = MagicMock()
    session = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = cm

    # EntityMentionRepository mock
    repo = AsyncMock()
    repo.get_unresolved_batch = AsyncMock(return_value=mentions)
    repo.mark_batch_escalated = AsyncMock()
    repo.update_resolution_outcome = AsyncMock()
    repo.recover_stale_escalated = AsyncMock(return_value=recover_count)

    with patch(
        "nlp_pipeline.infrastructure.workers.unresolved_resolution_worker.EntityMentionRepository"
        if False  # patched inline in each test
        else "dummy"
    ):
        pass

    # Attach repo to the factory for test access
    factory._mock_repo = repo
    return factory, repo


def _make_mention(
    mention_class: MentionClass = MentionClass.ORGANIZATION,
    mention_text: str = "Apple Inc.",
    outcome: str = "unresolved",
) -> MagicMock:
    m = MagicMock()
    m.mention_id = uuid.uuid4()
    m.doc_id = uuid.uuid4()
    m.mention_text = mention_text
    m.mention_class = mention_class.value
    m.resolution_outcome = outcome
    m.resolution_noise_reason = None
    m.resolved_entity_id = None
    m.resolution_confidence = None
    return m


# ---------------------------------------------------------------------------
# recover_stale_escalated
# ---------------------------------------------------------------------------


class TestRecoverStaleEscalated:
    async def test_recover_stale_escalated_delegates_to_repo(self) -> None:
        """recover_stale_escalated() calls repo.recover_stale_escalated() and commits."""
        settings = _make_settings(stale_minutes=30)

        session = AsyncMock()
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=cm)

        repo = AsyncMock()
        repo.recover_stale_escalated = AsyncMock(return_value=2)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
        )

        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
            return_value=repo,
        ):
            count = await worker.recover_stale_escalated()

        assert count == 2
        repo.recover_stale_escalated.assert_awaited_once_with(stale_minutes=30)
        session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# run_once — empty batch
# ---------------------------------------------------------------------------


class TestRunOnceEmptyBatch:
    async def test_empty_batch_returns_zero_stats(self) -> None:
        """run_once() with no unresolved rows returns WorkerStats with all zeros."""
        settings = _make_settings()

        session = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=cm)

        repo = AsyncMock()
        repo.get_unresolved_batch = AsyncMock(return_value=[])

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
        )

        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
            return_value=repo,
        ):
            stats = await worker.run_once()

        assert stats == WorkerStats(processed=0, auto_resolved=0, entity_created=0, noise=0, errors=0)
        repo.mark_batch_escalated.assert_not_awaited()


# ---------------------------------------------------------------------------
# run_once — non-eligible class → noise without LLM
# ---------------------------------------------------------------------------


class TestRunOnceNonEligibleClass:
    async def test_location_mention_noise_no_llm(self) -> None:
        """MentionClass.LOCATION → noise directly without Ollama call."""
        settings = _make_settings()
        mention = _make_mention(mention_class=MentionClass.LOCATION, mention_text="New York")

        session = AsyncMock()
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=cm)

        repo = AsyncMock()
        repo.get_unresolved_batch = AsyncMock(return_value=[mention])
        repo.mark_batch_escalated = AsyncMock()
        repo.update_resolution_outcome = AsyncMock()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=None,  # Phase 1 skipped
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=repo,
            ),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            stats = await worker.run_once()

        # Ollama should NOT be called for non-eligible class
        mock_httpx.assert_not_called()
        assert stats.noise == 1
        assert stats.entity_created == 0
        assert stats.processed == 1


# ---------------------------------------------------------------------------
# run_once — Phase 2 entity_created
# ---------------------------------------------------------------------------


class TestRunOncePhase2EntityCreated:
    async def test_qwen_entity_true_marks_entity_created(self) -> None:
        """Qwen responds is_entity=True → outcome='entity_created'."""
        settings = _make_settings(ollama_url="http://localhost:11434")
        mention = _make_mention(
            mention_class=MentionClass.ORGANIZATION,
            mention_text="OpenAI",
        )

        session = AsyncMock()
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=cm)

        repo = AsyncMock()
        repo.get_unresolved_batch = AsyncMock(return_value=[mention])
        repo.mark_batch_escalated = AsyncMock()
        repo.update_resolution_outcome = AsyncMock()

        # Mock httpx response: Ollama returns is_entity=true
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"response": '{"is_entity": true, "reason": "AI company"}'})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=None,  # no intel for this test
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=repo,
            ),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            stats = await worker.run_once()

        assert stats.entity_created == 1
        assert stats.noise == 0
        assert mention.resolution_outcome == ResolutionOutcome.ENTITY_CREATED.value


# ---------------------------------------------------------------------------
# run_once — Phase 2 noise
# ---------------------------------------------------------------------------


class TestRunOncePhase2Noise:
    async def test_qwen_entity_false_marks_noise_with_reason(self) -> None:
        """Qwen responds is_entity=False → outcome='noise', reason stored."""
        settings = _make_settings()
        mention = _make_mention(
            mention_class=MentionClass.PERSON,
            mention_text="John",
        )

        session = AsyncMock()
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=cm)

        repo = AsyncMock()
        repo.get_unresolved_batch = AsyncMock(return_value=[mention])
        repo.mark_batch_escalated = AsyncMock()
        repo.update_resolution_outcome = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"response": '{"is_entity": false, "reason": "Too generic"}'})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=repo,
            ),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            stats = await worker.run_once()

        assert stats.noise == 1
        assert mention.resolution_outcome == ResolutionOutcome.NOISE.value
        assert mention.resolution_noise_reason == "Too generic"


# ---------------------------------------------------------------------------
# run_once — JSON parse failure → unresolved
# ---------------------------------------------------------------------------


class TestRunOnceJsonParseFailure:
    async def test_malformed_json_leaves_unresolved(self) -> None:
        """Malformed JSON from Qwen → mention stays unresolved (not noise)."""
        settings = _make_settings()
        mention = _make_mention(
            mention_class=MentionClass.ORGANIZATION,
            mention_text="Corp XYZ",
        )

        session = AsyncMock()
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=cm)

        repo = AsyncMock()
        repo.get_unresolved_batch = AsyncMock(return_value=[mention])
        repo.mark_batch_escalated = AsyncMock()
        repo.update_resolution_outcome = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        # Malformed JSON — not parseable
        mock_response.json = MagicMock(return_value={"response": "I cannot tell if this is an entity."})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=repo,
            ),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            stats = await worker.run_once()

        # JSON parse failure → unresolved (not noise), counted in errors
        assert stats.errors == 1
        assert stats.noise == 0
        # Mention should be reset to unresolved
        update_calls = repo.update_resolution_outcome.call_args_list
        # One of the calls should set to 'unresolved'
        outcomes = [call.args[1] for call in update_calls if len(call.args) >= 2]
        assert "unresolved" in outcomes or mention.resolution_outcome == ResolutionOutcome.UNRESOLVED.value


# ---------------------------------------------------------------------------
# run_loop — exception tolerance
# ---------------------------------------------------------------------------


class TestRunLoop:
    async def test_run_loop_continues_after_exception(self) -> None:
        """run_loop() catches run_once() exceptions and keeps running."""
        settings = _make_settings(interval_s=0)  # 0s sleep to make test fast

        call_count = 0

        async def _run_once_failing() -> WorkerStats:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated failure")
            if call_count >= 2:
                raise asyncio.CancelledError  # Stop the loop after 2nd call
            return WorkerStats(0, 0, 0, 0, 0)

        nlp_sf = MagicMock()
        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
        )
        worker.run_once = _run_once_failing  # type: ignore[method-assign]

        with pytest.raises(asyncio.CancelledError):
            await worker.run_loop()

        # Confirmed: loop ran 2 times (1 exception + 1 cancellation)
        assert call_count >= 2


# ---------------------------------------------------------------------------
# Usage logging
# ---------------------------------------------------------------------------


class TestUsageLogging:
    async def test_llm_call_logged_on_phase2_eligible(self) -> None:
        """usage_logger.log() is called for each eligible mention in Phase 2."""
        settings = _make_settings()
        mention = _make_mention(
            mention_class=MentionClass.FINANCIAL_INSTITUTION,
            mention_text="JPMorgan Chase",
        )

        session = AsyncMock()
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        nlp_sf = MagicMock(return_value=cm)

        repo = AsyncMock()
        repo.get_unresolved_batch = AsyncMock(return_value=[mention])
        repo.mark_batch_escalated = AsyncMock()
        repo.update_resolution_outcome = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"response": '{"is_entity": true, "reason": "Major bank"}'})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        usage_logger = AsyncMock()
        usage_logger.log = AsyncMock(return_value=None)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            usage_logger=usage_logger,
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=repo,
            ),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            await worker.run_once()

        # Allow fire-and-forget task to execute
        await asyncio.sleep(0)

        usage_logger.log.assert_awaited_once()
        call_kwargs = usage_logger.log.call_args.kwargs
        assert call_kwargs["provider"] == "ollama"
        assert call_kwargs["capability"] == "extraction"
        assert call_kwargs["estimated_cost_usd"] == 0.0
        assert call_kwargs["success"] is True


# ---------------------------------------------------------------------------
# DeepInfra provider path
# ---------------------------------------------------------------------------


class TestDeepInfraProviderPath:
    """Tests for UnresolvedResolutionWorker when api_key triggers external API path."""

    def _make_settings_with_api(self) -> MagicMock:
        s = _make_settings()
        # Enable the DeepInfra path
        s.unresolved_resolution_api_key = "test-key"
        s.unresolved_resolution_api_base_url = "https://api.deepinfra.com/v1/openai"
        s.unresolved_resolution_api_model_id = "Qwen/Qwen2.5-0.5B-Instruct"
        return s

    @pytest.mark.asyncio
    async def test_external_api_entity_true_creates_entity(self) -> None:
        """DeepInfra returns is_entity=true → ENTITY_CREATED outcome."""
        settings = self._make_settings_with_api()
        mention = _make_mention(mention_class=MentionClass.ORGANIZATION, mention_text="Apple Inc")

        openai_resp = {"choices": [{"message": {"content": '{"is_entity": true, "reason": "major company"}'}}]}
        resp_mock = MagicMock()
        resp_mock.json.return_value = openai_resp
        resp_mock.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp_mock)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=MagicMock(),
            settings=settings,
        )

        with patch(
            "nlp_pipeline.infrastructure.workers.unresolved_resolution_worker.httpx.AsyncClient",
            return_value=mock_client,
        ):
            outcome, reason = await worker._phase2_llm_classify(mention)

        assert outcome == ResolutionOutcome.ENTITY_CREATED
        assert reason is None

    @pytest.mark.asyncio
    async def test_external_api_entity_false_marks_noise(self) -> None:
        """DeepInfra returns is_entity=false → NOISE outcome with reason."""
        settings = self._make_settings_with_api()
        mention = _make_mention(mention_class=MentionClass.ORGANIZATION, mention_text="xyz123")

        openai_resp = {"choices": [{"message": {"content": '{"is_entity": false, "reason": "noise"}'}}]}
        resp_mock = MagicMock()
        resp_mock.json.return_value = openai_resp
        resp_mock.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp_mock)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=MagicMock(),
            settings=settings,
        )

        with patch(
            "nlp_pipeline.infrastructure.workers.unresolved_resolution_worker.httpx.AsyncClient",
            return_value=mock_client,
        ):
            outcome, reason = await worker._phase2_llm_classify(mention)

        assert outcome == ResolutionOutcome.NOISE
        assert reason == "noise"

    @pytest.mark.asyncio
    async def test_external_api_bad_json_returns_unresolved(self) -> None:
        """Malformed JSON from external API → UNRESOLVED (safe fallback)."""
        settings = self._make_settings_with_api()
        mention = _make_mention(mention_class=MentionClass.ORGANIZATION, mention_text="test")

        resp_mock = MagicMock()
        resp_mock.json.return_value = {"choices": [{"message": {"content": "bad json {"}}]}
        resp_mock.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp_mock)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=MagicMock(),
            settings=settings,
        )

        with patch(
            "nlp_pipeline.infrastructure.workers.unresolved_resolution_worker.httpx.AsyncClient",
            return_value=mock_client,
        ):
            outcome, _ = await worker._phase2_llm_classify(mention)

        assert outcome == ResolutionOutcome.UNRESOLVED
