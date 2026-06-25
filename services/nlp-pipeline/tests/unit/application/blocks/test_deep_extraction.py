"""Unit tests for Block 10 — Deep LLM extraction (T-C-3-06).

Critical invariants:
  - Non-FULL_PIPELINE tiers return empty results (LIGHT/SUPPRESS guard).
  - Claims are surfaced via ``extraction_result["claims"]`` so the article
    consumer can wrap them as ``raw_claims`` in the enriched event payload.
    PLAN-0057 D-1 (F-CRIT-08): the legacy per-claim ``claim.extracted``
    outbox write loop was removed; the topic had zero subscribers.
  - evidence_date in downstream consumers = coalesce(published_at, extracted_at) —
    NEVER now(). Block 10 itself no longer computes evidence_date directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.blocks.deep_extraction import (
    SINGLE_WINDOW_TOKEN_LIMIT,
    WINDOW_OVERLAP_TOKENS,
    WINDOW_SIZE_TOKENS,
    _build_prompt,
    _build_windows,
    _merge_results_safe,
    run_deep_extraction_block,
)
from nlp_pipeline.application.blocks.suppression import ProcessingPath
from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome
from nlp_pipeline.domain.models import Chunk, EntityMention

pytestmark = pytest.mark.unit


def _make_chunk(text: str, doc_id: uuid.UUID | None = None, section_id: uuid.UUID | None = None) -> Chunk:
    d = doc_id or uuid.uuid4()
    s = section_id or uuid.uuid4()
    return Chunk(
        chunk_id=uuid.uuid4(),
        doc_id=d,
        section_id=s,
        chunk_index=0,
        char_start=0,
        char_end=len(text),
        token_count=len(text.split()),
        text=text,
    )


def _make_mention(
    text: str,
    resolved_entity_id: uuid.UUID | None = None,
    doc_id: uuid.UUID | None = None,
    mention_class: MentionClass = MentionClass.ORGANIZATION,
) -> EntityMention:
    m = EntityMention(
        mention_id=uuid.uuid4(),
        doc_id=doc_id or uuid.uuid4(),
        section_id=uuid.uuid4(),
        mention_text=text,
        mention_class=mention_class,
        confidence=0.90,
        char_start=0,
        char_end=len(text),
    )
    m.resolved_entity_id = resolved_entity_id
    m.resolution_outcome = ResolutionOutcome.AUTO_RESOLVED if resolved_entity_id else ResolutionOutcome.UNRESOLVED
    return m


def _make_extraction_client(result: dict) -> MagicMock:  # type: ignore[type-arg]
    from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-not-found]

    output = ExtractionOutput(result=result, raw_response="", model_id="qwen2.5:7b-instruct")
    client = MagicMock()
    client.extract = AsyncMock(return_value=output)
    return client


@pytest.mark.unit
class TestBuildWindows:
    def test_short_text_produces_single_window(self) -> None:
        chunks = [_make_chunk("Apple revenues grew. Tesla beat guidance.")]
        windows = _build_windows(chunks, max_tokens=WINDOW_SIZE_TOKENS, overlap_tokens=WINDOW_OVERLAP_TOKENS)
        assert len(windows) == 1

    def test_long_text_produces_multiple_windows(self) -> None:
        # Build a text longer than SINGLE_WINDOW_TOKEN_LIMIT
        long_text = " ".join(f"word{i}" for i in range(SINGLE_WINDOW_TOKEN_LIMIT + 100))
        chunks = [_make_chunk(long_text)]
        windows = _build_windows(chunks, max_tokens=WINDOW_SIZE_TOKENS, overlap_tokens=WINDOW_OVERLAP_TOKENS)
        assert len(windows) > 1

    def test_empty_chunks_returns_empty(self) -> None:
        assert _build_windows([], max_tokens=WINDOW_SIZE_TOKENS, overlap_tokens=WINDOW_OVERLAP_TOKENS) == []

    def test_windows_overlap(self) -> None:
        """Consecutive windows must share overlap words."""
        long_text = " ".join(f"word{i}" for i in range(SINGLE_WINDOW_TOKEN_LIMIT + 500))
        chunks = [_make_chunk(long_text)]
        windows = _build_windows(chunks, max_tokens=1000, overlap_tokens=100)
        if len(windows) >= 2:
            words0 = set(windows[0].split())
            words1 = set(windows[1].split())
            assert words0 & words1, "Consecutive windows must overlap"


@pytest.mark.unit
class TestMergeResultsSafe:
    def test_deduplicates_events_by_type_description(self) -> None:
        r1 = {
            "events": [{"event_type": "earnings", "description": "beat", "confidence": 0.9}],
            "claims": [],
            "relations": [],
        }
        r2 = {
            "events": [{"event_type": "earnings", "description": "beat", "confidence": 0.9}],
            "claims": [],
            "relations": [],
        }
        merged = _merge_results_safe([r1, r2])
        assert len(list(merged["events"])) == 1  # type: ignore[arg-type]

    def test_preserves_unique_events(self) -> None:
        r1 = {
            "events": [{"event_type": "earnings", "description": "beat", "confidence": 0.9}],
            "claims": [],
            "relations": [],
        }
        r2 = {
            "events": [{"event_type": "merger", "description": "announced", "confidence": 0.8}],
            "claims": [],
            "relations": [],
        }
        merged = _merge_results_safe([r1, r2])
        assert len(list(merged["events"])) == 2  # type: ignore[arg-type]


@pytest.mark.unit
class TestBuildPrompt:
    """ENHANCEMENT #1: type-annotated entity allow-list rendered into the prompt.

    Each distinct entity surface is tagged with its GLiNER ``mention_class``
    so the model can enforce relation precision + direction (2026-06-20
    stored-relation-quality audit: ~22% entity type/resolution errors).
    """

    def test_renders_class_annotations(self) -> None:
        mentions = [
            _make_mention("Apple Inc.", mention_class=MentionClass.ORGANIZATION),
            _make_mention("Tim Cook", mention_class=MentionClass.PERSON),
            _make_mention("S&P 500", mention_class=MentionClass.INDEX),
            _make_mention("US Dollar", mention_class=MentionClass.CURRENCY),
        ]
        prompt = _build_prompt("some article text", mentions)
        assert "Apple Inc. [organization]" in prompt
        assert "Tim Cook [person]" in prompt
        assert "S&P 500 [index]" in prompt
        assert "US Dollar [currency]" in prompt

    def test_order_preserving_dedup_first_class_wins(self) -> None:
        """Duplicate surfaces are collapsed; the FIRST-seen class wins and the
        original insertion order is preserved. Uses surfaces that do NOT appear
        in the prompt's static examples so the assertion targets only the
        dynamically-rendered entity allow-list."""
        mentions = [
            _make_mention("Acme Robotics", mention_class=MentionClass.ORGANIZATION),
            _make_mention("Jane Roe", mention_class=MentionClass.PERSON),
            # Duplicate surface with a DIFFERENT class — must be dropped, first wins.
            _make_mention("Acme Robotics", mention_class=MentionClass.FINANCIAL_INSTITUTION),
        ]
        prompt = _build_prompt("text", mentions)
        # Exactly one rendering of Acme, tagged organization (first-seen).
        assert prompt.count("Acme Robotics [organization]") == 1
        assert "Acme Robotics [financial_institution]" not in prompt
        # Order preserved: Acme appears before Jane Roe in the entity list.
        assert prompt.index("Acme Robotics [organization]") < prompt.index("Jane Roe [person]")

    def test_empty_mentions_uses_fallback(self) -> None:
        prompt = _build_prompt("text", [])
        assert "none identified" in prompt


@pytest.mark.unit
class TestRunDeepExtractionBlock:
    @pytest.mark.asyncio
    async def test_light_tier_returns_empty(self) -> None:
        """SECTION_EMBEDDINGS_ONLY (LIGHT) path must return empty results — critical guard."""
        client = _make_extraction_client({"events": [], "claims": [], "relations": []})

        result, signals = await run_deep_extraction_block(
            doc_id=uuid.uuid4(),
            chunks=[_make_chunk("Some article text about markets.")],
            mentions=[],
            processing_path=ProcessingPath.SECTION_EMBEDDINGS_ONLY,
            extraction_client=client,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        assert result == {"events": [], "claims": [], "relations": []}
        assert signals == []
        # Extraction client must NOT be called for non-FULL_PIPELINE
        client.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_halt_tier_returns_empty(self) -> None:
        """HALT (SUPPRESS) path must return empty results — critical guard."""
        client = _make_extraction_client({"events": [], "claims": [], "relations": []})

        result, signals = await run_deep_extraction_block(
            doc_id=uuid.uuid4(),
            chunks=[],
            mentions=[],
            processing_path=ProcessingPath.HALT,
            extraction_client=client,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        assert result == {"events": [], "claims": [], "relations": []}
        assert signals == []

    @pytest.mark.asyncio
    async def test_full_pipeline_calls_extraction_client(self) -> None:
        """FULL_PIPELINE path (MEDIUM/DEEP) invokes the extraction client."""
        entity_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        chunk = _make_chunk("Apple reported record quarterly revenue this period.", doc_id=doc_id)
        mention = _make_mention("apple", resolved_entity_id=entity_id, doc_id=doc_id)

        result_data = {
            "events": [{"event_type": "earnings", "description": "beat", "entity_refs": ["apple"], "confidence": 0.85}],
            "claims": [
                {
                    "entity_ref": "apple",
                    "claim_type": "revenue",
                    "polarity": "positive",
                    "confidence": 0.88,
                    "evidence_text": "record revenue",
                }
            ],
            "relations": [],
        }
        client = _make_extraction_client(result_data)

        _result, signals = await run_deep_extraction_block(
            doc_id=doc_id,
            chunks=[chunk],
            mentions=[mention],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        client.extract.assert_called_once()
        # High-confidence signal should be emitted
        assert len(signals) == 1
        assert signals[0].entity_id == entity_id

    @pytest.mark.asyncio
    async def test_claims_surfaced_in_extraction_result(self) -> None:
        """PLAN-0057 D-1: claims flow via ``extraction_result["claims"]``,
        which the article consumer wraps as ``raw_claims`` in the enriched
        event payload (consumed by KG enriched_consumer). The legacy
        per-claim ``claim.extracted`` outbox write loop was removed because
        the Kafka topic had zero subscribed consumer groups."""
        entity_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        chunk = _make_chunk("Apple raised its dividend.", doc_id=doc_id)
        mention = _make_mention("apple", resolved_entity_id=entity_id, doc_id=doc_id)

        result_data = {
            "events": [],
            "claims": [
                {
                    "entity_ref": "apple",
                    "claim_type": "dividend",
                    "polarity": "positive",
                    "confidence": 0.90,
                    "evidence_text": "raised dividend",
                }
            ],
            "relations": [],
        }
        client = _make_extraction_client(result_data)

        result, _signals = await run_deep_extraction_block(
            doc_id=doc_id,
            chunks=[chunk],
            mentions=[mention],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        # Claims must reach the caller via the result dict (not via any
        # outbox repo — the producer was removed in PLAN-0057 D-1).
        claims_list = list(result["claims"])  # type: ignore[arg-type, call-overload]
        assert len(claims_list) == 1
        claim = dict(claims_list[0])  # type: ignore[call-overload]
        assert claim["claim_type"] == "dividend"
        assert claim["entity_ref"] == "apple"

    @pytest.mark.asyncio
    async def test_block_does_not_import_claims_repository(self) -> None:
        """Regression: PLAN-0057 D-1 removed the ClaimsRepository import.
        Verify the deep-extraction module no longer references it (so a
        future re-introduction would have to be conscious, not accidental)."""
        import nlp_pipeline.application.blocks.deep_extraction as block_module

        # Module attribute lookup: ClaimsRepository must not be present.
        assert not hasattr(block_module, "ClaimsRepository"), (
            "ClaimsRepository must not be importable from deep_extraction; "
            "the orphan claim.extracted producer was deleted in PLAN-0057 D-1."
        )

    @pytest.mark.asyncio
    async def test_published_at_passed_through(self) -> None:
        """published_at + extracted_at remain function parameters but the
        block itself no longer computes evidence_date — downstream
        consumers compute it from the enriched event envelope. This test
        just verifies the block accepts these kwargs without error."""
        entity_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        chunk = _make_chunk("Apple raised dividend.", doc_id=doc_id)
        mention = _make_mention("apple", resolved_entity_id=entity_id, doc_id=doc_id)

        published_at = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        result_data = {
            "events": [],
            "claims": [
                {
                    "entity_ref": "apple",
                    "claim_type": "dividend",
                    "polarity": "positive",
                    "confidence": 0.90,
                    "evidence_text": "raised",
                }
            ],
            "relations": [],
        }
        client = _make_extraction_client(result_data)

        result, _signals = await run_deep_extraction_block(
            doc_id=doc_id,
            chunks=[chunk],
            mentions=[mention],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            model_id="qwen2.5:7b-instruct",
            published_at=published_at,
            extracted_at=datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        # Claim made it through the pipeline.
        assert len(list(result["claims"])) == 1  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_extraction_failure_does_not_raise(self) -> None:
        """A NON-transient (non-RetryableError) extraction error is caught and
        the window is recorded empty — method never raises to caller for the
        generic-exception case. (Transient timeouts are handled separately;
        see TestDeepExtractionTimeouts.)"""
        client = MagicMock()
        client.extract = AsyncMock(side_effect=Exception("Ollama parse blow-up"))

        result, signals = await run_deep_extraction_block(
            doc_id=uuid.uuid4(),
            chunks=[_make_chunk("Some article content here.")],
            mentions=[],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        assert result["events"] == []
        assert signals == []
        # A non-transient failure is NOT a timeout — the doc is not degraded.
        assert result["degraded"] is False
        assert result["timed_out_windows"] == 0


@pytest.mark.unit
class TestDeepExtractionTimeouts:
    """Task #22 (BP-677): unmask deep-extraction timeouts.

    A transient ``RetryableError`` (timeout/429/5xx/connection) from the
    extraction adapter must NOT be silently substituted with an empty result
    and logged as a clean zero. The doc must carry ``degraded=true`` +
    ``timed_out_windows>=1``; if EVERY window times out the block re-raises
    ``RetryableError`` so the consumer retries the whole doc.
    """

    @staticmethod
    def _long_multi_window_chunk(doc_id: uuid.UUID) -> Chunk:
        # Force >1 window so partial-timeout scenarios are reachable.
        long_text = " ".join(f"word{i}" for i in range(SINGLE_WINDOW_TOKEN_LIMIT + WINDOW_SIZE_TOKENS + 1000))
        return _make_chunk(long_text, doc_id=doc_id)

    @pytest.mark.asyncio
    async def test_partial_timeout_flags_degraded_and_keeps_good_windows(self) -> None:
        """SOME windows succeed, SOME time out -> persist the good windows but
        flag degraded=true + timed_out_windows>=1. The timeout is NOT swallowed
        as a clean zero."""
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-not-found]
        from ml_clients.errors import RetryableError  # type: ignore[import-not-found]

        doc_id = uuid.uuid4()
        chunk = self._long_multi_window_chunk(doc_id)

        good = ExtractionOutput(
            result={
                "events": [{"event_type": "earnings", "description": "beat", "confidence": 0.6}],
                "claims": [],
                "relations": [],
            },
            raw_response="",
            model_id="qwen2.5:7b-instruct",
        )
        # First window succeeds, every subsequent window times out.
        client = MagicMock()
        client.extract = AsyncMock(side_effect=[good, RetryableError("DeepSeek timeout"), RetryableError("timeout")])

        result, _signals = await run_deep_extraction_block(
            doc_id=doc_id,
            chunks=[chunk],
            mentions=[],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        # Good window's content is preserved (not lost).
        assert len(list(result["events"])) == 1  # type: ignore[arg-type]
        # Degradation is surfaced, NOT swallowed.
        assert result["degraded"] is True
        assert result["timed_out_windows"] >= 1

    @pytest.mark.asyncio
    async def test_all_windows_timeout_raises_retryable(self) -> None:
        """EVERY window times out -> RetryableError is raised so the consumer
        retries the whole doc instead of committing a fake empty extraction."""
        from ml_clients.errors import RetryableError  # type: ignore[import-not-found]

        client = MagicMock()
        client.extract = AsyncMock(side_effect=RetryableError("DeepSeek wall-clock timeout"))

        with pytest.raises(RetryableError):
            await run_deep_extraction_block(
                doc_id=uuid.uuid4(),
                chunks=[_make_chunk("Single window article body.")],
                mentions=[],
                processing_path=ProcessingPath.FULL_PIPELINE,
                extraction_client=client,
                model_id="qwen2.5:7b-instruct",
                published_at=None,
                extracted_at=datetime.now(tz=UTC),
                outbox_topic_signal="nlp.signal.detected.v1",
            )

    @pytest.mark.asyncio
    async def test_genuine_empty_is_not_degraded(self) -> None:
        """Model returns {events:[],claims:[],relations:[]} successfully (no
        exception) -> degraded=false, timed_out_windows=0. This MUST be
        distinguishable from the all-timeout case."""
        client = _make_extraction_client({"events": [], "claims": [], "relations": []})

        result, signals = await run_deep_extraction_block(
            doc_id=uuid.uuid4(),
            chunks=[_make_chunk("An article with genuinely no extractable events.")],
            mentions=[],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        assert list(result["events"]) == []  # type: ignore[arg-type]
        assert result["degraded"] is False
        assert result["timed_out_windows"] == 0
        assert signals == []

    @pytest.mark.asyncio
    async def test_fully_successful_doc_unchanged_behaviour(self) -> None:
        """A fully-successful multi-window doc behaves exactly as before:
        degraded=false, timed_out_windows=0, content merged normally."""
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-not-found]

        doc_id = uuid.uuid4()
        chunk = self._long_multi_window_chunk(doc_id)
        out = ExtractionOutput(
            result={
                "events": [{"event_type": "earnings", "description": "beat", "confidence": 0.6}],
                "claims": [],
                "relations": [],
            },
            raw_response="",
            model_id="qwen2.5:7b-instruct",
        )
        client = MagicMock()
        client.extract = AsyncMock(return_value=out)

        result, _signals = await run_deep_extraction_block(
            doc_id=doc_id,
            chunks=[chunk],
            mentions=[],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        assert result["degraded"] is False
        assert result["timed_out_windows"] == 0
        # Deduplicated to a single event across windows (overlap dedup).
        assert len(list(result["events"])) == 1  # type: ignore[arg-type]
