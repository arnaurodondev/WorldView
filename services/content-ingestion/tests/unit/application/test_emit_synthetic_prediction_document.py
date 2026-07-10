"""Unit tests for SyntheticDocumentEmitter (PLAN-0056 Wave B2)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.emit_synthetic_prediction_document import (
    SyntheticDocumentEmitter,
    build_synthetic_document_body,
    synthetic_first_sight_url_hash,
    synthetic_resolution_url_hash,
)
from content_ingestion.domain.entities import OutcomeSnapshot, PredictionMarketFetchResult, SourceType

pytestmark = pytest.mark.unit

_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)
_CLOSE_TIME = datetime(2026, 11, 3, 0, 0, 0, tzinfo=UTC)


def _make_result(
    market_id: str = "cond_abc",
    *,
    resolution_status: str = "open",
    resolved_answer: str | None = None,
    category: str | None = "politics",
) -> PredictionMarketFetchResult:
    return PredictionMarketFetchResult(
        source_type=SourceType.POLYMARKET,
        market_id=market_id,
        question="Will X win the 2026 election?",
        outcomes=[
            OutcomeSnapshot(name="Yes", token_id="tok_yes", price=0.62),
            OutcomeSnapshot(name="No", token_id="tok_no", price=0.38),
        ],
        raw_bytes=json.dumps({"conditionId": market_id}).encode(),
        fetched_at=_FETCHED_AT,
        close_time=_CLOSE_TIME,
        category=category,
        resolution_status=resolution_status,
        resolved_answer=resolved_answer,
        market_slug="will-x-win-2026",
        minio_bronze_key=f"content-ingestion/polymarket/2026/04/09/{market_id}.json",
    )


def _build_emitter(
    fetch_log: object = None,
    outbox: object = None,
    commit_fn: object = None,
    rollback_fn: object = None,
) -> SyntheticDocumentEmitter:
    return SyntheticDocumentEmitter(
        fetch_log_repo=fetch_log or AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock()),
        outbox_repo=outbox or AsyncMock(append=AsyncMock()),
        commit_fn=commit_fn or AsyncMock(),
        rollback_fn=rollback_fn or AsyncMock(),
    )


class TestUrlHashHelpers:
    def test_first_sight_hash_matches_spec(self) -> None:
        """First-sight url_hash = sha256('polymarket:<condition_id>')."""
        expected = hashlib.sha256(b"polymarket:cond_abc").hexdigest()
        assert synthetic_first_sight_url_hash("cond_abc") == expected

    def test_resolution_hash_matches_spec(self) -> None:
        """Resolution url_hash = sha256('polymarket:<condition_id>:resolved')."""
        expected = hashlib.sha256(b"polymarket:cond_abc:resolved").hexdigest()
        assert synthetic_resolution_url_hash("cond_abc") == expected

    def test_first_sight_and_resolution_hashes_differ(self) -> None:
        """The two lifecycle documents must not collide on dedup key."""
        assert synthetic_first_sight_url_hash("cond_abc") != synthetic_resolution_url_hash("cond_abc")


class TestBuildSyntheticDocumentBody:
    def test_body_contains_question_outcomes_and_metadata(self) -> None:
        """Body carries question, outcome percentages, close date, category (PRD §7)."""
        body = build_synthetic_document_body(_make_result())
        assert "Will X win the 2026 election?" in body
        assert "- Yes: 62.0%" in body
        assert "- No: 38.0%" in body
        assert "Market closes 2026-11-03" in body
        assert "Category: politics" in body

    def test_body_includes_event_name_when_given(self) -> None:
        """A parent-event name is included only when supplied."""
        body = build_synthetic_document_body(_make_result(), event_name="2026 US Election")
        assert "Belongs to event: 2026 US Election" in body

    def test_body_omits_event_line_when_absent(self) -> None:
        """No event line when event_name is None."""
        body = build_synthetic_document_body(_make_result())
        assert "Belongs to event" not in body

    def test_resolved_body_notes_resolved_outcome(self) -> None:
        """Resolution body appends the resolved outcome."""
        result = _make_result(resolution_status="resolved", resolved_answer="Yes")
        body = build_synthetic_document_body(result, resolved=True)
        assert "resolved" in body.lower()
        assert "Yes" in body


class TestSyntheticDocumentEmitter:
    async def test_first_sight_emits_one_document(self) -> None:
        """A new market emits exactly one first-sight content.article.raw.v1 event."""
        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock())
        outbox = AsyncMock(append=AsyncMock())
        commit = AsyncMock()
        emitter = _build_emitter(fetch_log=fetch_log, outbox=outbox, commit_fn=commit)

        summary = await emitter.emit(_make_result())

        assert summary.emitted == 1
        assert summary.skipped == 0
        fetch_log.create.assert_awaited_once()
        outbox.append.assert_awaited_once()
        commit.assert_awaited_once()

    async def test_outbox_event_shape_is_content_article_raw(self) -> None:
        """The outbox event targets the content.article.raw.v1 topic with polymarket source_type."""
        outbox = AsyncMock(append=AsyncMock())
        emitter = _build_emitter(outbox=outbox)

        await emitter.emit(_make_result())

        _, kwargs = outbox.append.call_args
        assert kwargs["topic"] == "content.article.raw.v1"
        assert kwargs["event_type"] == "content.article.raw.v1"
        payload = kwargs["payload"]
        assert payload["source_type"] == "polymarket"
        assert payload["title"] == "Will X win the 2026 election?"
        # published_at maps to the market close time.
        assert payload["published_at"].startswith("2026-11-03")
        # PLAN-0056 Wave C2b: the raw payload carries the market identity so the KG
        # can resolve this synthetic doc back to its real Polymarket market.
        assert payload["external_id"] == "polymarket:cond_abc"
        # source_url stays the human URL — external_id is NOT overloaded onto it.
        assert payload["external_id"] != payload["source_url"]

    async def test_normal_article_payload_has_null_external_id(self) -> None:
        """PLAN-0056 Wave C2b: the ordinary article path leaves external_id=None."""
        from content_ingestion.application.use_cases.fetch_and_write import build_raw_article_payload

        import common.ids

        payload = build_raw_article_payload(
            doc_id=common.ids.new_uuid7(),
            source_type="eodhd",
            source_url="https://example.com/news/1",
            minio_bronze_key="bronze/key",
            raw_bytes=b"body",
            fetch_id=common.ids.new_uuid7(),
            published_at=None,
            is_backfill=False,
            title="Some news",
        )
        assert payload["external_id"] is None

    async def test_fetch_log_written_with_first_sight_url_hash(self) -> None:
        """The fetch_log row uses the polymarket:<condition_id> dedup hash."""
        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock())
        emitter = _build_emitter(fetch_log=fetch_log)

        await emitter.emit(_make_result(market_id="cond_xyz"))

        _, kwargs = fetch_log.create.call_args
        assert kwargs["url_hash"] == synthetic_first_sight_url_hash("cond_xyz")

    async def test_content_hash_is_sha256_of_body(self) -> None:
        """The event content_hash is sha256 of the rendered body bytes."""
        outbox = AsyncMock(append=AsyncMock())
        emitter = _build_emitter(outbox=outbox)
        result = _make_result()

        await emitter.emit(result)

        expected = hashlib.sha256(build_synthetic_document_body(result).encode()).hexdigest()
        payload = outbox.append.call_args.kwargs["payload"]
        assert payload["content_hash"] == expected

    async def test_repoll_emits_zero_when_already_present(self) -> None:
        """A re-poll (url_hash already exists) emits no new documents."""
        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(return_value=True), create=AsyncMock())
        outbox = AsyncMock(append=AsyncMock())
        commit = AsyncMock()
        emitter = _build_emitter(fetch_log=fetch_log, outbox=outbox, commit_fn=commit)

        summary = await emitter.emit(_make_result())

        assert summary.emitted == 0
        assert summary.skipped == 1
        fetch_log.create.assert_not_awaited()
        outbox.append.assert_not_awaited()
        commit.assert_not_awaited()

    async def test_resolution_emits_additional_document(self) -> None:
        """A resolved, first-seen market emits both first-sight and resolution docs."""
        # exists=False for both hashes → both documents are new.
        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock())
        outbox = AsyncMock(append=AsyncMock())
        emitter = _build_emitter(fetch_log=fetch_log, outbox=outbox)

        result = _make_result(resolution_status="resolved", resolved_answer="No")
        summary = await emitter.emit(result)

        assert summary.emitted == 2
        assert outbox.append.await_count == 2
        # The second document uses the :resolved dedup hash and notes the outcome.
        second_payload = outbox.append.call_args_list[1].kwargs["payload"]
        assert second_payload["source_type"] == "polymarket"
        # PLAN-0056 Wave D2: first-sight external_id = polymarket:<cid>; the
        # resolution doc appends ':resolved' so S7 emits a 'resolution' (vs
        # 'new_market') signal. Both still carry the same condition_id.
        first_payload = outbox.append.call_args_list[0].kwargs["payload"]
        assert first_payload["external_id"] == "polymarket:cond_abc"
        assert second_payload["external_id"] == "polymarket:cond_abc:resolved"

    async def test_resolution_only_document_when_first_sight_exists(self) -> None:
        """When first-sight already emitted, a newly-resolved market emits only the resolution doc."""

        async def _exists(url_hash: str) -> bool:
            # First-sight already present; resolution not yet.
            return url_hash == synthetic_first_sight_url_hash("cond_abc")

        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(side_effect=_exists), create=AsyncMock())
        outbox = AsyncMock(append=AsyncMock())
        emitter = _build_emitter(fetch_log=fetch_log, outbox=outbox)

        summary = await emitter.emit(_make_result(resolution_status="resolved", resolved_answer="Yes"))

        assert summary.emitted == 1
        assert summary.skipped == 1
        assert outbox.append.await_count == 1
        assert fetch_log.create.call_args.kwargs["url_hash"] == synthetic_resolution_url_hash("cond_abc")

    async def test_empty_condition_id_emits_nothing(self) -> None:
        """A market without a condition id is refused (would collide dedup keys)."""
        # market_id="" would fail domain validation only via from_gamma_response; construct
        # directly and bypass by replacing after construction.
        result = replace(_make_result(), market_id="")
        outbox = AsyncMock(append=AsyncMock())
        emitter = _build_emitter(outbox=outbox)

        summary = await emitter.emit(result)

        assert summary.emitted == 0
        outbox.append.assert_not_awaited()

    async def test_write_failure_rolls_back_and_counts_failed(self) -> None:
        """A DB error rolls back the session and is reported as failed, not raised."""
        fetch_log = AsyncMock(
            exists_by_url_hash=AsyncMock(return_value=False),
            create=AsyncMock(side_effect=RuntimeError("db down")),
        )
        commit = AsyncMock()
        rollback = AsyncMock()
        emitter = _build_emitter(fetch_log=fetch_log, commit_fn=commit, rollback_fn=rollback)

        summary = await emitter.emit(_make_result())

        assert summary.failed == 1
        assert summary.emitted == 0
        rollback.assert_awaited_once()
        commit.assert_not_awaited()
