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
from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import (
    UnresolvedMentionWithContext,
)
from nlp_pipeline.infrastructure.workers.unresolved_resolution_worker import (
    _CLASSIFICATION_PROMPT_TEMPLATE,
    UnresolvedResolutionWorker,
    WorkerStats,
)


def _wrap(mentions: list[Any], context: str | None = None) -> list[UnresolvedMentionWithContext]:
    """Wrap mention mocks into the dataclass returned by the new repo method.

    The worker switched to ``get_unresolved_batch_with_context`` (PLAN-0057
    T-B-3-01); tests need to return ``UnresolvedMentionWithContext`` bundles
    so the worker's iteration produces the correct ``(mention, context)``
    pair when calling ``_process_mention``.
    """
    return [UnresolvedMentionWithContext(mention=m, context_sentence=context) for m in mentions]


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
        repo.get_unresolved_batch_with_context = AsyncMock(return_value=[])

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
        repo.get_unresolved_batch_with_context = AsyncMock(return_value=_wrap([mention]))
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
        repo.get_unresolved_batch_with_context = AsyncMock(return_value=_wrap([mention]))
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
        repo.get_unresolved_batch_with_context = AsyncMock(return_value=_wrap([mention]))
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
        repo.get_unresolved_batch_with_context = AsyncMock(return_value=_wrap([mention]))
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
        repo.get_unresolved_batch_with_context = AsyncMock(return_value=_wrap([mention]))
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


# ---------------------------------------------------------------------------
# F-CRIT-05: financial-domain prompt — 4 worked examples + snapshot
# ---------------------------------------------------------------------------


# PLAN-0057 T-B-3-02: each tuple is (surface, context, llm_payload, expected_outcome).
# The four worked examples are exactly the cases burned into the prompt body —
# we feed each one back to the classifier with a mocked LLM that returns the
# canonical answer, asserting end-to-end that the worker plumbs context_sentence
# through and translates the JSON correctly.
_FCRIT05_CASES: list[tuple[str, str, str, ResolutionOutcome]] = [
    (
        "iShares Core S&P 500 ETF",
        "The iShares Core S&P 500 ETF (IVV) saw inflows of $1.2B.",
        '{"is_entity": true, "reason": "named investable fund"}',
        ResolutionOutcome.ENTITY_CREATED,
    ),
    (
        "MAS",
        "Singapore's MAS raised the benchmark rate by 25bps.",
        '{"is_entity": true, "reason": "Monetary Authority of Singapore — regulator"}',
        ResolutionOutcome.ENTITY_CREATED,
    ),
    (
        "the company",
        "Analysts said the company would miss guidance.",
        '{"is_entity": false, "reason": "generic anaphora, not a named entity"}',
        ResolutionOutcome.NOISE,
    ),
    (
        "Q3",
        "Q3 revenue rose 8% year-over-year.",
        '{"is_entity": false, "reason": "calendar fragment, not a named entity"}',
        ResolutionOutcome.NOISE,
    ),
]


@pytest.mark.parametrize(("surface", "context", "llm_payload", "expected"), _FCRIT05_CASES)
@pytest.mark.asyncio
async def test_phase2_llm_classify_handles_financial_domain_examples(
    surface: str,
    context: str,
    llm_payload: str,
    expected: ResolutionOutcome,
) -> None:
    """F-CRIT-05: each worked example classifies correctly via the new prompt.

    The mocked LLM returns the canonical JSON answer the new prompt elicits;
    we assert ``_phase2_llm_classify`` translates it to the expected
    ResolutionOutcome.  This is the anti-regression test for the
    over-suppression bug (subsidiaries/ETFs/regulators were rejected by the
    old "Wikipedia article" prompt).
    """
    settings = _make_settings()
    mention = _make_mention(mention_class=MentionClass.ORGANIZATION, mention_text=surface)

    # The Ollama path wraps the JSON inside {"response": "..."} — match that.
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"response": llm_payload})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
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
        outcome, _reason = await worker._phase2_llm_classify(mention, context_sentence=context)

    assert outcome == expected, f"surface={surface!r} expected {expected} got {outcome}"
    # Confirm the prompt that hit the LLM included BOTH the surface and the
    # context — this is the load-bearing change vs the old prompt.
    sent_prompt = mock_client.post.await_args.kwargs["json"]["prompt"]
    assert surface in sent_prompt
    assert context in sent_prompt


@pytest.mark.asyncio
async def test_phase2_llm_classify_passes_context_to_external_provider() -> None:
    """DeepInfra path also receives both surface AND context in the prompt body.

    Both call sites (Ollama + DeepInfra) must use the new template; this
    asserts the prompt that the OpenAI-compatible chat/completions request
    carries contains the per-mention ``context_sentence``.
    """
    s = _make_settings()
    s.unresolved_resolution_api_key = "test-key"
    s.unresolved_resolution_api_base_url = "https://api.deepinfra.com/v1/openai"
    s.unresolved_resolution_api_model_id = "Qwen/Qwen2.5-0.5B-Instruct"
    mention = _make_mention(mention_class=MentionClass.ORGANIZATION, mention_text="MAS")

    openai_resp = {"choices": [{"message": {"content": '{"is_entity": true, "reason": "regulator"}'}}]}
    resp_mock = MagicMock()
    resp_mock.json.return_value = openai_resp
    resp_mock.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=resp_mock)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    worker = UnresolvedResolutionWorker(
        nlp_session_factory=MagicMock(),
        settings=s,
    )

    ctx = "Singapore central bank press release | Rate decision"
    with patch(
        "nlp_pipeline.infrastructure.workers.unresolved_resolution_worker.httpx.AsyncClient",
        return_value=mock_client,
    ):
        outcome, _reason = await worker._phase2_llm_classify(mention, context_sentence=ctx)

    assert outcome == ResolutionOutcome.ENTITY_CREATED
    chat_messages = mock_client.post.await_args.kwargs["json"]["messages"]
    sent_prompt = chat_messages[0]["content"]
    # Both surface and context must reach the external provider.
    assert "MAS" in sent_prompt
    assert "Singapore central bank" in sent_prompt


def test_classification_prompt_template_includes_all_four_worked_examples() -> None:
    """Snapshot: anti-regression on the four examples burned into the prompt.

    If any of these four signature substrings disappears from the prompt,
    we have silently regressed F-CRIT-05's recall fix.  The exact strings
    are pulled verbatim from the audit fix-design report.
    """
    rendered = _CLASSIFICATION_PROMPT_TEMPLATE.format(
        surface="placeholder-surface",
        context="placeholder-context",
    )
    # Positive examples
    assert "iShares Core S&P 500 ETF" in rendered
    assert "Singapore's MAS raised the benchmark rate" in rendered
    # Negative examples
    assert "the company would miss guidance" in rendered
    assert "Q3 revenue rose 8% year-over-year" in rendered
    # Domain coverage signals
    assert "subsidiary" in rendered
    assert "ETF" in rendered
    assert "regulator" in rendered
    # The old "Wikipedia article" criterion must NOT come back.
    assert "Wikipedia" not in rendered
    # Final response instruction must be present and unambiguous.
    # The actual prompt phrasing is "Respond with a single JSON object ONLY"
    # — match on the substantive token "JSON object ONLY" so it survives
    # minor prompt rewording without breaking the anti-regression intent.
    assert "JSON object ONLY" in rendered or "JSON ONLY" in rendered


def test_classification_prompt_handles_missing_context_gracefully() -> None:
    """Empty context is replaced with a stable placeholder so the prompt still renders.

    Some legacy mentions have no associated document_source_metadata row
    (or no section); the worker must not crash on ``None``.
    """
    rendered = _CLASSIFICATION_PROMPT_TEMPLATE.format(
        surface="OpenAI",
        context="(no surrounding context available)",
    )
    assert "OpenAI" in rendered
    assert "(no surrounding context available)" in rendered


# ---------------------------------------------------------------------------
# PLAN-0061 Wave B — _phase1_cascade() real implementation tests
# ---------------------------------------------------------------------------


def _make_intel_sf() -> tuple[MagicMock, AsyncMock]:
    """Return (intel_session_factory, session) mocks."""
    session = AsyncMock()
    session.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm), session


def _make_nlp_sf() -> tuple[MagicMock, AsyncMock]:
    """Return (nlp_session_factory, session) mocks."""
    session = AsyncMock()
    session.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm), session


class TestPhase1CascadeStage1:
    """Stage 1: exact alias match resolves the mention."""

    async def test_exact_match_resolves_and_returns_true(self) -> None:
        settings = _make_settings()
        mention = _make_mention(mention_text="Apple Inc.")
        entity_id = uuid.uuid4()

        intel_sf, _ = _make_intel_sf()
        nlp_sf, nlp_session = _make_nlp_sf()

        alias_repo = AsyncMock()
        alias_repo.exact_match = AsyncMock(return_value=entity_id)
        alias_repo.ticker_isin_match = AsyncMock(return_value=None)
        alias_repo.fuzzy_trigram = AsyncMock(return_value=[])

        em_repo = AsyncMock()
        em_repo.resolve = AsyncMock()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=intel_sf,
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias.EntityAliasRepository",
                return_value=alias_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=em_repo,
            ),
        ):
            resolved = await worker._phase1_cascade(mention)

        assert resolved is True
        alias_repo.exact_match.assert_awaited_once_with("Apple Inc.")
        # Stage 2+3 must NOT have been called once Stage 1 hit
        alias_repo.ticker_isin_match.assert_not_awaited()
        alias_repo.fuzzy_trigram.assert_not_awaited()
        em_repo.resolve.assert_awaited_once_with(mention.mention_id, entity_id, 1.0, 1)
        nlp_session.commit.assert_awaited_once()


class TestPhase1CascadeStage2:
    """Stage 2: ticker/ISIN match resolves the mention when Stage 1 misses."""

    async def test_ticker_match_resolves_and_returns_true(self) -> None:
        settings = _make_settings()
        mention = _make_mention(mention_text="AAPL")
        entity_id = uuid.uuid4()

        intel_sf, _ = _make_intel_sf()
        nlp_sf, nlp_session = _make_nlp_sf()

        alias_repo = AsyncMock()
        alias_repo.exact_match = AsyncMock(return_value=None)
        alias_repo.ticker_isin_match = AsyncMock(return_value=entity_id)
        alias_repo.fuzzy_trigram = AsyncMock(return_value=[])

        em_repo = AsyncMock()
        em_repo.resolve = AsyncMock()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=intel_sf,
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias.EntityAliasRepository",
                return_value=alias_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=em_repo,
            ),
        ):
            resolved = await worker._phase1_cascade(mention)

        assert resolved is True
        alias_repo.ticker_isin_match.assert_awaited_once_with(ticker="AAPL", isin=None)
        alias_repo.fuzzy_trigram.assert_not_awaited()
        em_repo.resolve.assert_awaited_once_with(mention.mention_id, entity_id, 0.95, 2)
        nlp_session.commit.assert_awaited_once()


class TestPhase1CascadeStage3:
    """Stage 3: fuzzy trigram resolves the mention when Stages 1+2 miss."""

    async def test_fuzzy_match_resolves_and_returns_true(self) -> None:
        settings = _make_settings()
        mention = _make_mention(mention_text="Berkshire Hathaway")
        entity_id = uuid.uuid4()
        sim = 0.88

        intel_sf, _ = _make_intel_sf()
        nlp_sf, nlp_session = _make_nlp_sf()

        alias_repo = AsyncMock()
        alias_repo.exact_match = AsyncMock(return_value=None)
        alias_repo.ticker_isin_match = AsyncMock(return_value=None)
        alias_repo.fuzzy_trigram = AsyncMock(return_value=[(entity_id, sim)])

        em_repo = AsyncMock()
        em_repo.resolve = AsyncMock()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=intel_sf,
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias.EntityAliasRepository",
                return_value=alias_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=em_repo,
            ),
        ):
            resolved = await worker._phase1_cascade(mention)

        assert resolved is True
        expected_confidence = round(sim * 0.90, 4)
        actual_call = em_repo.resolve.call_args
        assert actual_call.args[0] == mention.mention_id
        assert actual_call.args[1] == entity_id
        assert round(actual_call.args[2], 4) == expected_confidence
        assert actual_call.args[3] == 3
        nlp_session.commit.assert_awaited_once()


class TestPhase1CascadeNoHit:
    """All stages miss -> returns False, no resolve() called."""

    async def test_no_hit_returns_false(self) -> None:
        settings = _make_settings()
        mention = _make_mention(mention_text="xyzzy-unknown-entity")

        intel_sf, _ = _make_intel_sf()
        nlp_sf, nlp_session = _make_nlp_sf()

        alias_repo = AsyncMock()
        alias_repo.exact_match = AsyncMock(return_value=None)
        alias_repo.ticker_isin_match = AsyncMock(return_value=None)
        alias_repo.fuzzy_trigram = AsyncMock(return_value=[])

        em_repo = AsyncMock()
        em_repo.resolve = AsyncMock()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=intel_sf,
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias.EntityAliasRepository",
                return_value=alias_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=em_repo,
            ),
        ):
            resolved = await worker._phase1_cascade(mention)

        assert resolved is False
        em_repo.resolve.assert_not_awaited()
        nlp_session.commit.assert_not_awaited()

    async def test_no_intel_sf_returns_false(self) -> None:
        """If intel_session_factory is None, cascade is skipped and returns False."""
        settings = _make_settings()
        mention = _make_mention(mention_text="Apple")
        nlp_sf, _ = _make_nlp_sf()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=None,
        )

        resolved = await worker._phase1_cascade(mention)
        assert resolved is False


# ---------------------------------------------------------------------------
# PLAN-0061 Wave B — _enqueue_for_enrichment() tests
# ---------------------------------------------------------------------------


class TestEnqueueForEnrichment:
    """_enqueue_for_enrichment() inserts into provisional_entity_queue."""

    async def test_returns_none_when_no_intel_sf(self) -> None:
        settings = _make_settings()
        mention = _make_mention()
        nlp_sf, _ = _make_nlp_sf()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=None,
        )

        result = await worker._enqueue_for_enrichment(mention)
        assert result is None

    async def test_executes_sql_and_returns_queue_id(self) -> None:
        # SQL changed from DO UPDATE to DO NOTHING RETURNING — worker now calls
        # scalar_one_or_none() (returns None on conflict, UUID str on new insert).
        settings = _make_settings()
        mention = _make_mention(mention_text="OpenAI")
        queue_id = uuid.uuid4()

        intel_sf, intel_session = _make_intel_sf()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none = MagicMock(return_value=str(queue_id))
        intel_session.execute = AsyncMock(return_value=execute_result)

        nlp_sf, _ = _make_nlp_sf()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=intel_sf,
        )

        with patch("common.ids.new_uuid7", return_value=queue_id):
            result = await worker._enqueue_for_enrichment(mention)

        assert result == queue_id
        intel_session.execute.assert_awaited_once()
        intel_session.commit.assert_awaited_once()
        # Confirm the SQL params included surface and doc_id
        call_params = intel_session.execute.call_args.args[1]
        assert call_params["surface"] == "OpenAI"
        assert call_params["doc_id"] == str(mention.doc_id)


# ---------------------------------------------------------------------------
# PLAN-0061 Wave B — ENTITY_CREATED branch enqueues for KG enrichment
# ---------------------------------------------------------------------------


class TestEntityCreatedEnqueues:
    """ENTITY_CREATED outcome triggers _enqueue_for_enrichment()."""

    async def test_entity_created_calls_enqueue(self) -> None:
        """When LLM returns is_entity=True, _enqueue_for_enrichment is called once."""
        settings = _make_settings(ollama_url="http://localhost:11434")
        mention = _make_mention(mention_class=MentionClass.ORGANIZATION, mention_text="Stripe Inc")

        nlp_sf, _nlp_session = _make_nlp_sf()

        em_repo = AsyncMock()
        em_repo.get_unresolved_batch = AsyncMock(return_value=[mention])
        em_repo.get_unresolved_batch_with_context = AsyncMock(return_value=_wrap([mention]))
        em_repo.mark_batch_escalated = AsyncMock()
        em_repo.update_resolution_outcome = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"response": '{"is_entity": true, "reason": "fintech company"}'})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=None,  # enqueue returns None without intel_sf
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=em_repo,
            ),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch.object(worker, "_enqueue_for_enrichment", new=AsyncMock(return_value=None)) as mock_enqueue,
        ):
            stats = await worker.run_once()

        assert stats.entity_created == 1
        mock_enqueue.assert_awaited_once_with(mention)

    async def test_noise_does_not_call_enqueue(self) -> None:
        """NOISE outcome must NOT call _enqueue_for_enrichment."""
        settings = _make_settings()
        mention = _make_mention(mention_class=MentionClass.ORGANIZATION, mention_text="the company")

        nlp_sf, _ = _make_nlp_sf()

        em_repo = AsyncMock()
        em_repo.get_unresolved_batch_with_context = AsyncMock(return_value=_wrap([mention]))
        em_repo.mark_batch_escalated = AsyncMock()
        em_repo.update_resolution_outcome = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"response": '{"is_entity": false, "reason": "generic phrase"}'})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=None,
        )

        with (
            patch(
                "nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention.EntityMentionRepository",
                return_value=em_repo,
            ),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch.object(worker, "_enqueue_for_enrichment", new=AsyncMock(return_value=None)) as mock_enqueue,
        ):
            stats = await worker.run_once()

        assert stats.noise == 1
        mock_enqueue.assert_not_awaited()


# ---------------------------------------------------------------------------
# PLAN-0061 Wave E — entity.provisional.queued.v1 Kafka emit
# ---------------------------------------------------------------------------


class TestEnqueueKafkaEmit:
    """_enqueue_for_enrichment emits entity.provisional.queued.v1 on new insert."""

    async def test_emits_event_when_new_row_inserted(self) -> None:
        """When scalar_one_or_none returns a UUID, producer.produce_bytes is called."""
        settings = _make_settings()
        mention = _make_mention(mention_text="Stripe Inc")
        queue_id = uuid.uuid4()

        intel_sf, intel_session = _make_intel_sf()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none = MagicMock(return_value=str(queue_id))
        intel_session.execute = AsyncMock(return_value=execute_result)

        producer = MagicMock()
        nlp_sf, _ = _make_nlp_sf()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=intel_sf,
            direct_producer=producer,
        )

        with patch("common.ids.new_uuid7", return_value=queue_id):
            result = await worker._enqueue_for_enrichment(mention)

        assert result == queue_id
        producer.produce_bytes.assert_called_once()
        call_kwargs = producer.produce_bytes.call_args.kwargs
        assert call_kwargs["topic"] == settings.kafka_topic_provisional_queued

        # PLAN-0062: payload is now Confluent-wire-format Avro (5-byte header +
        # raw Avro body), not JSON.  Decode via the same helper the consumer
        # uses so the test enforces producer/consumer alignment end-to-end.
        from nlp_pipeline.infrastructure.workers.unresolved_resolution_worker import (
            _PROVISIONAL_QUEUED_SCHEMA_PATH,
        )

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        payload = deserialize_confluent_avro(_PROVISIONAL_QUEUED_SCHEMA_PATH, call_kwargs["value"])
        assert payload["queue_id"] == str(queue_id)
        # mention_class is already a string (mention.mention_class is set to enum.value in _make_mention)
        assert payload["mention_class"] == mention.mention_class

    async def test_no_emit_when_conflict(self) -> None:
        """When scalar_one_or_none returns None (conflict), no event is emitted."""
        settings = _make_settings()
        mention = _make_mention(mention_text="Duplicate Corp")

        intel_sf, intel_session = _make_intel_sf()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none = MagicMock(return_value=None)
        intel_session.execute = AsyncMock(return_value=execute_result)

        producer = MagicMock()
        nlp_sf, _ = _make_nlp_sf()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=intel_sf,
            direct_producer=producer,
        )

        result = await worker._enqueue_for_enrichment(mention)

        assert result is None
        producer.produce_bytes.assert_not_called()

    async def test_no_emit_when_producer_not_configured(self) -> None:
        """When direct_producer is None, no exception is raised on new insert."""
        settings = _make_settings()
        mention = _make_mention(mention_text="TestCo")
        queue_id = uuid.uuid4()

        intel_sf, intel_session = _make_intel_sf()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none = MagicMock(return_value=str(queue_id))
        intel_session.execute = AsyncMock(return_value=execute_result)

        nlp_sf, _ = _make_nlp_sf()

        worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=intel_sf,
            direct_producer=None,
        )

        with patch("common.ids.new_uuid7", return_value=queue_id):
            result = await worker._enqueue_for_enrichment(mention)

        assert result == queue_id  # still returns the queue_id
