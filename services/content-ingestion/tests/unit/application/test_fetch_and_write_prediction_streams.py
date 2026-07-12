"""Unit tests for the deeper-stream fetch-and-write use case (PLAN-0056 Wave B3).

Covers the 4 payload builders (Avro-shape parity per ``.avsc``) and the generic
``FetchAndWritePredictionStreamUseCase`` (write / skip / rollback + correct
event_type + topic per stream).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.fetch_and_write_prediction_streams import (
    PREDICTION_EVENT_SPEC,
    PREDICTION_HISTORY_SPEC,
    PREDICTION_OI_SPEC,
    PREDICTION_TRADE_SPEC,
    FetchAndWritePredictionStreamUseCase,
    build_prediction_event_payloads,
    build_prediction_history_payloads,
    build_prediction_oi_payloads,
    build_prediction_trade_payloads,
)
from content_ingestion.domain.entities import (
    PredictionEventFetchResult,
    PredictionHistoryFetchResult,
    PredictionOIFetchResult,
    PredictionTradeFetchResult,
    PricePoint,
    SourceType,
)

import common.ids
from messaging.topics import (  # type: ignore[import-untyped]
    MARKET_PREDICTION_EVENT,
    MARKET_PREDICTION_HISTORY,
    MARKET_PREDICTION_OI,
    MARKET_PREDICTION_TRADE,
)

pytestmark = pytest.mark.unit

_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)


# ── Avro field sets (must match the .avsc schemas exactly) ─────────────────────

_EVENT_FIELDS = {
    "event_id",
    "event_type",
    "schema_version",
    "occurred_at",
    "group_id",
    "name",
    "category",
    "start_date",
    "end_date",
    "market_count",
    "correlation_id",
}
_HISTORY_FIELDS = {
    "event_id",
    "event_type",
    "schema_version",
    "occurred_at",
    "market_id",
    "token_id",
    "outcome_name",
    "interval",
    "window_start_ts",
    "price",
    "source",
    "is_backfill",
    "correlation_id",
}
_TRADE_FIELDS = {
    "event_id",
    "event_type",
    "schema_version",
    "occurred_at",
    "market_id",
    "trade_id",
    "token_id",
    "price",
    "size_usd",
    "side",
    "ts",
    "correlation_id",
}
_OI_FIELDS = {
    "event_id",
    "event_type",
    "schema_version",
    "occurred_at",
    "market_id",
    "snapshot_date",
    "total_oi_usd",
    "total_volume_24h_usd",
    "correlation_id",
}


# ── Entity factories ───────────────────────────────────────────────────────────


def _event() -> PredictionEventFetchResult:
    return PredictionEventFetchResult(
        source_type=SourceType.POLYMARKET_GAMMA_EVENTS,
        event_id="grp_123",
        title="2028 US Presidential Election",
        raw_bytes=json.dumps({"id": "grp_123"}).encode(),
        fetched_at=_FETCHED_AT,
        category="politics",
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        end_date=datetime(2028, 11, 7, tzinfo=UTC),
        market_count=42,
    )


def _history(market_id: str | None = "cond_parent") -> PredictionHistoryFetchResult:
    # PLAN-0056 Wave B4: results now carry the parent market_id (conditionId).
    return PredictionHistoryFetchResult(
        source_type=SourceType.POLYMARKET_CLOB,
        token_id="tok_yes",
        interval="1h",
        points=[
            PricePoint(timestamp=datetime(2026, 4, 9, 12, 0, tzinfo=UTC), price=0.61),
            PricePoint(timestamp=datetime(2026, 4, 9, 13, 0, tzinfo=UTC), price=0.63),
        ],
        raw_bytes=b"{}",
        fetched_at=_FETCHED_AT,
        market_id=market_id,
    )


def _trade(market_id: str | None = "cond_parent") -> PredictionTradeFetchResult:
    # PLAN-0056 Wave B4: results now carry the parent market_id (conditionId).
    return PredictionTradeFetchResult(
        source_type=SourceType.POLYMARKET_DATA_TRADES,
        trade_id="0xabc",
        token_id="tok_yes",
        price=0.62,
        size_usd=125.5,
        side="buy",
        traded_at=_FETCHED_AT,
        raw_bytes=b"{}",
        fetched_at=_FETCHED_AT,
        market_id=market_id,
    )


def _oi() -> PredictionOIFetchResult:
    return PredictionOIFetchResult(
        source_type=SourceType.POLYMARKET_DATA_OI,
        market_id="cond_abc",
        open_interest_usd=100000.0,
        snapshot_date=_FETCHED_AT,
        raw_bytes=b"{}",
        fetched_at=_FETCHED_AT,
        volume_24h_usd=5000.0,
    )


# ── Payload-builder tests ──────────────────────────────────────────────────────


class TestPayloadBuilders:
    def test_event_payload_matches_schema_fields(self) -> None:
        payload = build_prediction_event_payloads(_event())[0]
        assert set(payload.keys()) == _EVENT_FIELDS
        assert payload["event_type"] == "market.prediction.event"
        assert payload["group_id"] == "grp_123"
        assert payload["name"] == "2028 US Presidential Election"
        assert payload["category"] == "politics"
        assert payload["market_count"] == 42
        assert payload["schema_version"] == 1

    def test_history_emits_one_payload_per_datapoint(self) -> None:
        payloads = build_prediction_history_payloads(_history(), is_backfill=True)
        assert len(payloads) == 2
        for p in payloads:
            assert set(p.keys()) == _HISTORY_FIELDS
            assert p["event_type"] == "market.prediction.history"
            # PLAN-0056 Wave B4: market_id is now the PARENT conditionId (was the
            # token_id surrogate in B3 — that assertion encoded the join bug).
            assert p["market_id"] == "cond_parent"
            assert p["token_id"] == "tok_yes"  # noqa: S105
            assert p["interval"] == "1h"
            assert p["is_backfill"] is True
        assert payloads[0]["price"] == 0.61
        assert payloads[0]["window_start_ts"].startswith("2026-04-09T12:00")

    def test_history_is_backfill_defaults_false(self) -> None:
        payloads = build_prediction_history_payloads(_history())
        assert all(p["is_backfill"] is False for p in payloads)

    def test_history_market_id_falls_back_to_token_when_no_parent(self) -> None:
        # PLAN-0056 Wave B4: legacy fetch-result with no parent conditionId keeps
        # the non-null schema field satisfied via the token_id surrogate.
        payloads = build_prediction_history_payloads(_history(market_id=None))
        for p in payloads:
            assert p["market_id"] == "tok_yes"
            assert p["token_id"] == "tok_yes"  # noqa: S105

    def test_trade_payload_matches_schema_fields(self) -> None:
        payload = build_prediction_trade_payloads(_trade())[0]
        assert set(payload.keys()) == _TRADE_FIELDS
        assert payload["event_type"] == "market.prediction.trade"
        assert payload["trade_id"] == "0xabc"
        assert payload["token_id"] == "tok_yes"  # noqa: S105
        # PLAN-0056 Wave B4: market_id is now the PARENT conditionId (was token_id
        # surrogate in B3 — that assertion encoded the join bug).
        assert payload["market_id"] == "cond_parent"
        assert payload["side"] == "buy"
        assert payload["size_usd"] == 125.5

    def test_trade_market_id_falls_back_to_token_when_no_parent(self) -> None:
        # PLAN-0056 Wave B4: legacy trade with no parent conditionId keeps the
        # non-null schema field satisfied via the token_id surrogate.
        payload = build_prediction_trade_payloads(_trade(market_id=None))[0]
        assert payload["market_id"] == "tok_yes"
        assert payload["token_id"] == "tok_yes"  # noqa: S105

    def test_oi_payload_matches_schema_fields(self) -> None:
        payload = build_prediction_oi_payloads(_oi())[0]
        assert set(payload.keys()) == _OI_FIELDS
        assert payload["event_type"] == "market.prediction.oi"
        assert payload["market_id"] == "cond_abc"
        # snapshot_date is a YYYY-MM-DD calendar date string.
        assert payload["snapshot_date"] == "2026-04-09"
        assert payload["total_oi_usd"] == 100000.0
        assert payload["total_volume_24h_usd"] == 5000.0

    def test_oi_volume_defaults_to_zero_when_absent(self) -> None:
        from dataclasses import replace

        payload = build_prediction_oi_payloads(replace(_oi(), volume_24h_usd=None))[0]
        # Schema field is a non-null double — must fall back to 0.0, never None.
        assert payload["total_volume_24h_usd"] == 0.0


# ── Generic use-case tests ─────────────────────────────────────────────────────


def _mock_fetch_log(exists: bool = False) -> AsyncMock:
    return AsyncMock(
        exists_by_market_snapshot=AsyncMock(return_value=exists),
        create_market_fetch_log=AsyncMock(return_value=common.ids.new_uuid7()),
    )


class TestFetchAndWritePredictionStreamUseCase:
    async def test_event_writes_fetch_log_and_outbox(self) -> None:
        fetch_log = _mock_fetch_log()
        outbox = AsyncMock(append=AsyncMock())
        commit = AsyncMock()
        uc = FetchAndWritePredictionStreamUseCase(
            fetch_log_repo=fetch_log,
            outbox_repo=outbox,
            spec=PREDICTION_EVENT_SPEC,
            commit_fn=commit,
            rollback_fn=AsyncMock(),
        )

        summary = await uc.execute([_event()])

        assert summary.fetched == 1
        assert summary.emitted == 1
        fetch_log.create_market_fetch_log.assert_awaited_once()
        # Correct event_type + topic routed to the outbox.
        _, kwargs = outbox.append.call_args
        assert kwargs["event_type"] == "market.prediction.event"
        assert kwargs["topic"] == MARKET_PREDICTION_EVENT
        assert kwargs["aggregate_type"] == "prediction_event"
        commit.assert_awaited_once()

    async def test_incremental_commit_persists_partial_progress_on_midstream_failure(self) -> None:
        """PLAN-0056 QA: the use case commits PER trade, so a mid-list failure keeps
        already-committed trades (no all-or-nothing deadlock).

        Simulates the 3rd commit failing: the first 2 trades stay committed, the
        3rd rolls back, and the summary reports 2 fetched / 1 failed.
        """
        import dataclasses

        trades = [dataclasses.replace(_trade(), trade_id=f"0x{i}") for i in range(3)]
        fetch_log = _mock_fetch_log()
        outbox = AsyncMock(append=AsyncMock())
        rollback = AsyncMock()
        # 3rd commit raises → the first two are already durably committed.
        commit = AsyncMock(side_effect=[None, None, RuntimeError("timeout mid-write")])
        uc = FetchAndWritePredictionStreamUseCase(
            fetch_log_repo=fetch_log,
            outbox_repo=outbox,
            spec=PREDICTION_TRADE_SPEC,
            commit_fn=commit,
            rollback_fn=rollback,
        )

        summary = await uc.execute(trades, source_id=common.ids.new_uuid7())

        assert summary.fetched == 2  # first two committed and survive
        assert summary.failed == 1  # the third failed
        assert commit.await_count == 3  # attempted on every trade
        rollback.assert_awaited_once()  # only the failed trade rolls back

    async def test_history_emits_multiple_outbox_events_single_fetch_log(self) -> None:
        fetch_log = _mock_fetch_log()
        outbox = AsyncMock(append=AsyncMock())
        uc = FetchAndWritePredictionStreamUseCase(
            fetch_log_repo=fetch_log,
            outbox_repo=outbox,
            spec=PREDICTION_HISTORY_SPEC,
            commit_fn=AsyncMock(),
            rollback_fn=AsyncMock(),
        )

        summary = await uc.execute([_history()])

        assert summary.fetched == 1
        assert summary.emitted == 2  # one outbox event per datapoint
        # One fetch_log row (dedup key = token_id), two outbox rows.
        fetch_log.create_market_fetch_log.assert_awaited_once()
        assert outbox.append.await_count == 2
        for call in outbox.append.call_args_list:
            assert call.kwargs["topic"] == MARKET_PREDICTION_HISTORY

    async def test_trade_routes_to_trade_topic(self) -> None:
        outbox = AsyncMock(append=AsyncMock())
        uc = FetchAndWritePredictionStreamUseCase(
            fetch_log_repo=_mock_fetch_log(),
            outbox_repo=outbox,
            spec=PREDICTION_TRADE_SPEC,
            commit_fn=AsyncMock(),
            rollback_fn=AsyncMock(),
        )
        await uc.execute([_trade()])
        assert outbox.append.call_args.kwargs["topic"] == MARKET_PREDICTION_TRADE
        assert outbox.append.call_args.kwargs["event_type"] == "market.prediction.trade"

    async def test_oi_routes_to_oi_topic(self) -> None:
        outbox = AsyncMock(append=AsyncMock())
        uc = FetchAndWritePredictionStreamUseCase(
            fetch_log_repo=_mock_fetch_log(),
            outbox_repo=outbox,
            spec=PREDICTION_OI_SPEC,
            commit_fn=AsyncMock(),
            rollback_fn=AsyncMock(),
        )
        await uc.execute([_oi()])
        assert outbox.append.call_args.kwargs["topic"] == MARKET_PREDICTION_OI
        assert outbox.append.call_args.kwargs["event_type"] == "market.prediction.oi"

    async def test_dedup_hit_skips_write(self) -> None:
        fetch_log = _mock_fetch_log(exists=True)
        outbox = AsyncMock(append=AsyncMock())
        commit = AsyncMock()
        uc = FetchAndWritePredictionStreamUseCase(
            fetch_log_repo=fetch_log,
            outbox_repo=outbox,
            spec=PREDICTION_OI_SPEC,
            commit_fn=commit,
            rollback_fn=AsyncMock(),
        )

        summary = await uc.execute([_oi()])

        assert summary.skipped == 1
        assert summary.fetched == 0
        fetch_log.create_market_fetch_log.assert_not_awaited()
        outbox.append.assert_not_awaited()
        commit.assert_not_awaited()

    async def test_exception_triggers_rollback_not_commit(self) -> None:
        fetch_log = AsyncMock(
            exists_by_market_snapshot=AsyncMock(return_value=False),
            create_market_fetch_log=AsyncMock(side_effect=RuntimeError("db down")),
        )
        commit = AsyncMock()
        rollback = AsyncMock()
        uc = FetchAndWritePredictionStreamUseCase(
            fetch_log_repo=fetch_log,
            outbox_repo=AsyncMock(append=AsyncMock()),
            spec=PREDICTION_EVENT_SPEC,
            commit_fn=commit,
            rollback_fn=rollback,
        )

        summary = await uc.execute([_event()])

        assert summary.failed == 1
        assert summary.fetched == 0
        rollback.assert_awaited_once()
        commit.assert_not_awaited()

    async def test_history_is_backfill_threaded_into_payload(self) -> None:
        outbox = AsyncMock(append=AsyncMock())
        uc = FetchAndWritePredictionStreamUseCase(
            fetch_log_repo=_mock_fetch_log(),
            outbox_repo=outbox,
            spec=PREDICTION_HISTORY_SPEC,
            commit_fn=AsyncMock(),
            rollback_fn=AsyncMock(),
        )
        await uc.execute([_history()], is_backfill=True)
        assert all(c.kwargs["payload"]["is_backfill"] is True for c in outbox.append.call_args_list)
