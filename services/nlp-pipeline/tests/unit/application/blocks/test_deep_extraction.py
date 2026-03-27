"""Unit tests for Block 10 — Deep LLM extraction (T-C-3-06).

Critical invariants:
  - Non-FULL_PIPELINE tiers return empty results (LIGHT/SUPPRESS guard).
  - Claims are written via outbox, never directly to intelligence_db.
  - evidence_date = coalesce(published_at, extracted_at) — NEVER now().
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
    _build_windows,
    _merge_results_safe,
    run_deep_extraction_block,
)
from nlp_pipeline.application.blocks.suppression import ProcessingPath
from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome
from nlp_pipeline.domain.models import Chunk, EntityMention


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
) -> EntityMention:
    m = EntityMention(
        mention_id=uuid.uuid4(),
        doc_id=doc_id or uuid.uuid4(),
        section_id=uuid.uuid4(),
        mention_text=text,
        mention_class=MentionClass.ORGANIZATION,
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
class TestRunDeepExtractionBlock:
    @pytest.mark.asyncio
    async def test_light_tier_returns_empty(self) -> None:
        """SECTION_EMBEDDINGS_ONLY (LIGHT) path must return empty results — critical guard."""
        client = _make_extraction_client({"events": [], "claims": [], "relations": []})
        claims_repo = MagicMock()

        result, signals = await run_deep_extraction_block(
            doc_id=uuid.uuid4(),
            chunks=[_make_chunk("Some article text about markets.")],
            mentions=[],
            processing_path=ProcessingPath.SECTION_EMBEDDINGS_ONLY,
            extraction_client=client,
            claims_repo=claims_repo,
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
        claims_repo = MagicMock()

        result, signals = await run_deep_extraction_block(
            doc_id=uuid.uuid4(),
            chunks=[],
            mentions=[],
            processing_path=ProcessingPath.HALT,
            extraction_client=client,
            claims_repo=claims_repo,
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
        claims_repo = MagicMock()
        claims_repo.write_via_outbox = AsyncMock()

        _result, signals = await run_deep_extraction_block(
            doc_id=doc_id,
            chunks=[chunk],
            mentions=[mention],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            claims_repo=claims_repo,
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
    async def test_claims_written_via_outbox_not_directly(self) -> None:
        """Claims MUST go through outbox repo — never direct intelligence_db write."""
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
        claims_repo = MagicMock()
        claims_repo.write_via_outbox = AsyncMock()

        await run_deep_extraction_block(
            doc_id=doc_id,
            chunks=[chunk],
            mentions=[mention],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            claims_repo=claims_repo,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        claims_repo.write_via_outbox.assert_called_once()

    @pytest.mark.asyncio
    async def test_evidence_date_uses_published_at_not_now(self) -> None:
        """evidence_date = published_at when available — NEVER now()."""
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
        claims_repo = MagicMock()
        claims_repo.write_via_outbox = AsyncMock()

        await run_deep_extraction_block(
            doc_id=doc_id,
            chunks=[chunk],
            mentions=[mention],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            claims_repo=claims_repo,
            model_id="qwen2.5:7b-instruct",
            published_at=published_at,
            extracted_at=datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        call_kwargs = claims_repo.write_via_outbox.call_args
        # evidence_date must be published_at, not extracted_at
        assert call_kwargs.kwargs["evidence_date"] == published_at

    @pytest.mark.asyncio
    async def test_extraction_failure_does_not_raise(self) -> None:
        """Extraction errors must be caught — method never raises to caller."""
        client = MagicMock()
        client.extract = AsyncMock(side_effect=Exception("Ollama timeout"))
        claims_repo = MagicMock()

        result, signals = await run_deep_extraction_block(
            doc_id=uuid.uuid4(),
            chunks=[_make_chunk("Some article content here.")],
            mentions=[],
            processing_path=ProcessingPath.FULL_PIPELINE,
            extraction_client=client,
            claims_repo=claims_repo,
            model_id="qwen2.5:7b-instruct",
            published_at=None,
            extracted_at=datetime.now(tz=UTC),
            outbox_topic_signal="nlp.signal.detected.v1",
        )

        assert result["events"] == []
        assert signals == []
