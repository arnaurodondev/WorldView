"""Unit tests for FetchAndWritePredictionMarketsUseCase."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.fetch_and_write_prediction_markets import (
    FetchAndWritePredictionMarketsUseCase,
    build_prediction_market_payload,
)
from content_ingestion.domain.entities import OutcomeSnapshot, PredictionMarketFetchResult, SourceType

import common.ids

pytestmark = pytest.mark.unit

_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)

_AVRO_FIELDS = {
    "event_id",
    "event_type",
    "schema_version",
    "occurred_at",
    "market_id",
    "source",
    "question",
    "description",
    "outcomes",
    "volume_24h",
    "liquidity",
    "close_time",
    "resolution_status",
    "resolved_answer",
    "minio_bronze_key",
    "correlation_id",
}


def _make_result(market_id: str = "cond_abc", source_id: object = None) -> PredictionMarketFetchResult:
    return PredictionMarketFetchResult(
        source_type=SourceType.POLYMARKET,
        market_id=market_id,
        question="Will X happen?",
        outcomes=[
            OutcomeSnapshot(name="Yes", token_id="tok_yes", price=0.6),
            OutcomeSnapshot(name="No", token_id="tok_no", price=0.4),
        ],
        raw_bytes=json.dumps({"conditionId": market_id}).encode(),
        fetched_at=_FETCHED_AT,
        minio_bronze_key=f"content-ingestion/polymarket/2026/04/09/{market_id}_2026-04-09T14:00:00+00:00.json",
    )


def _build_use_case(
    fetch_log: object = None,
    outbox: object = None,
    commit_fn: object = None,
    rollback_fn: object = None,
) -> FetchAndWritePredictionMarketsUseCase:
    return FetchAndWritePredictionMarketsUseCase(
        fetch_log_repo=fetch_log
        or AsyncMock(
            exists_by_market_snapshot=AsyncMock(return_value=False),
            create_market_fetch_log=AsyncMock(return_value=common.ids.new_uuid7()),
        ),
        outbox_repo=outbox or AsyncMock(append=AsyncMock()),
        commit_fn=commit_fn or AsyncMock(),
        rollback_fn=rollback_fn or AsyncMock(),
    )


class TestFetchAndWritePredictionMarketsUseCase:
    async def test_use_case_writes_fetch_log_and_outbox_atomically(self) -> None:
        """Both fetch_log and outbox rows are written for a new result."""
        result = _make_result()
        fetch_log = AsyncMock(
            exists_by_market_snapshot=AsyncMock(return_value=False),
            create_market_fetch_log=AsyncMock(return_value=common.ids.new_uuid7()),
        )
        outbox = AsyncMock(append=AsyncMock())
        commit = AsyncMock()
        use_case = _build_use_case(fetch_log=fetch_log, outbox=outbox, commit_fn=commit)

        summary = await use_case.execute([result])

        assert summary.fetched == 1
        assert summary.skipped == 0
        fetch_log.create_market_fetch_log.assert_awaited_once()
        outbox.append.assert_awaited_once()
        commit.assert_awaited_once()

    async def test_use_case_skips_duplicate(self) -> None:
        """exists_by_market_snapshot=True → no rows written, skipped count = 1."""
        result = _make_result()
        fetch_log = AsyncMock(
            exists_by_market_snapshot=AsyncMock(return_value=True),
            create_market_fetch_log=AsyncMock(),
        )
        outbox = AsyncMock(append=AsyncMock())
        commit = AsyncMock()
        use_case = _build_use_case(fetch_log=fetch_log, outbox=outbox, commit_fn=commit)

        summary = await use_case.execute([result])

        assert summary.fetched == 0
        assert summary.skipped == 1
        fetch_log.create_market_fetch_log.assert_not_awaited()
        outbox.append.assert_not_awaited()
        commit.assert_not_awaited()

    async def test_exception_triggers_rollback_not_commit(self) -> None:
        """On a write error the session is rolled back so subsequent results can proceed."""
        result = _make_result()
        fetch_log = AsyncMock(
            exists_by_market_snapshot=AsyncMock(return_value=False),
            create_market_fetch_log=AsyncMock(side_effect=RuntimeError("db down")),
        )
        commit = AsyncMock()
        rollback = AsyncMock()
        use_case = _build_use_case(fetch_log=fetch_log, commit_fn=commit, rollback_fn=rollback)

        summary = await use_case.execute([result])

        assert summary.failed == 1
        assert summary.fetched == 0
        rollback.assert_awaited_once()
        commit.assert_not_awaited()

    async def test_use_case_outbox_payload_matches_avro_schema(self) -> None:
        """All Avro schema fields are present in the outbox payload dict (BP-017)."""
        result = _make_result()
        payload = build_prediction_market_payload(result)

        missing = _AVRO_FIELDS - set(payload.keys())
        assert not missing, f"Missing Avro fields in payload: {missing}"

        # Verify field values
        assert payload["market_id"] == "cond_abc"
        assert payload["source"] == "polymarket"
        assert payload["event_type"] == "market.prediction.snapshot"
        assert payload["schema_version"] == 1
        assert len(payload["outcomes"]) == 2
        assert payload["outcomes"][0] == {"name": "Yes", "token_id": "tok_yes", "price": 0.6}
