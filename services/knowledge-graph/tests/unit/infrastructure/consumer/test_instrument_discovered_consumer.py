"""Unit tests for InstrumentDiscoveredConsumer (PLAN-0057 Wave D-2).

Covers:
  * Happy path: emits 1 canonical UPSERT + 2 alias inserts (EXACT, TICKER)
    + ensure_rows_exist call.
  * Re-delivery (idempotent): PLAN-0089 F2 step 4 changed the canonical
    conflict clause from DO NOTHING → DO UPDATE.  Re-running
    process_message must still succeed without raising; SQL stays identical
    across deliveries and the DB handles dedup via ON CONFLICT.
  * Missing/empty symbol → MalformedDataError (dead-lettered).
  * is_duplicate / mark_processed thread through the dedup client.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_INSTRUMENT_ID = uuid4()


def _make_consumer() -> tuple[Any, Any, Any]:
    """Build a consumer with a mocked session factory + emb_repo capture.

    Returns:
        (consumer, session_mock, sql_calls_list) — sql_calls_list captures
        every ``session.execute(text(...), params)`` for assertion.

    """
    from knowledge_graph.infrastructure.messaging.consumers.instrument_discovered_consumer import (
        InstrumentDiscoveredConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-instrument-discovered-test",
        topics=["market.instrument.discovered.v1"],
    )

    # Capture all SQL statements.  We deliberately do not parse the SQL — the
    # tests assert the EXACT number of execute() calls and inspect params,
    # which is the most useful behavioural guarantee at the consumer layer.
    sql_calls: list[tuple[str, dict]] = []

    async def _execute(stmt: Any, params: dict | None = None) -> Any:
        # ``stmt`` is a sqlalchemy.sql.elements.TextClause; str() gives the SQL.
        sql_calls.append((str(stmt), params or {}))
        return MagicMock()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()

    # session.begin_nested() returns an async context manager (SAVEPOINT).
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    sf = MagicMock(return_value=session_cm)

    consumer = InstrumentDiscoveredConsumer(config=config, session_factory=sf)

    return consumer, session, sql_calls


class TestInstrumentDiscoveredConsumerHappyPath:
    def test_new_instrument_inserts_canonical_aliases_and_embedding_rows(self) -> None:
        """One canonical UPSERT + two alias inserts + 3 embedding-state rows."""
        consumer, session, sql_calls = _make_consumer()

        msg = {
            "event_id": str(uuid4()),
            "event_type": "market.instrument.discovered",
            "schema_version": 1,
            "occurred_at": "2026-04-30T12:00:00Z",
            "instrument_id": str(_INSTRUMENT_ID),
            "symbol": "AAPL",
            "exchange": "NASDAQ",
        }

        from unittest import mock

        # Patch EntityEmbeddingStateRepository so we can assert it was called.
        emb_repo_mock = mock.AsyncMock()
        emb_repo_mock.ensure_rows_exist = mock.AsyncMock()

        with mock.patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=emb_repo_mock,
        ):
            asyncio.run(consumer.process_message(None, msg, {}))

        # 1 canonical UPSERT + 2 alias inserts = 3 raw SQL calls
        assert len(sql_calls) == 3, f"expected 3 SQL execute() calls; got {len(sql_calls)}: {sql_calls}"

        # First call: canonical entity UPSERT keyed on entity_id = instrument_id
        canonical_sql, canonical_params = sql_calls[0]
        assert "INSERT INTO canonical_entities" in canonical_sql
        # PLAN-0089 F2 step 4: conflict clause UPSERTs the lightweight columns
        # so a re-delivery with updated metadata propagates to the canonical
        # row (M-017 enforcement).
        assert "ON CONFLICT (entity_id) DO UPDATE" in canonical_sql
        assert "ticker = EXCLUDED.ticker" in canonical_sql
        assert "exchange = EXCLUDED.exchange" in canonical_sql
        assert "canonical_name = EXCLUDED.canonical_name" in canonical_sql
        assert "updated_at = now()" in canonical_sql
        assert canonical_params["entity_id"] == str(_INSTRUMENT_ID)
        assert canonical_params["canonical_name"] == "AAPL"  # placeholder = symbol
        assert canonical_params["ticker"] == "AAPL"
        assert canonical_params["exchange"] == "NASDAQ"
        # metadata is JSON-serialised in the consumer; verify the flag is in it.
        import json as _json

        meta = _json.loads(canonical_params["metadata"])
        assert meta["needs_fundamentals_enrichment"] is True
        assert meta["source"] == "discovered"
        assert "discovered_at" in meta

        # Second + third calls: alias inserts (EXACT then TICKER)
        exact_sql, exact_params = sql_calls[1]
        assert "INSERT INTO entity_aliases" in exact_sql
        assert exact_params["atype"] == "EXACT"
        assert exact_params["alias"] == "AAPL"
        assert exact_params["norm"] == "aapl"

        ticker_sql, ticker_params = sql_calls[2]
        assert "INSERT INTO entity_aliases" in ticker_sql
        assert ticker_params["atype"] == "TICKER"
        assert ticker_params["alias"] == "AAPL"
        assert ticker_params["norm"] == "AAPL"  # ticker normalisation is upper-case match

        # ensure_rows_exist was called with financial_instrument
        emb_repo_mock.ensure_rows_exist.assert_awaited_once()
        call_args = emb_repo_mock.ensure_rows_exist.call_args
        assert call_args.args[0] == _INSTRUMENT_ID
        assert call_args.args[1] == "financial_instrument"

        # session.commit was awaited
        session.commit.assert_awaited_once()

    def test_redelivery_is_idempotent(self) -> None:
        """A second delivery of the same event hits the same SQL path safely.

        All inserts use ON CONFLICT DO NOTHING; the consumer does not raise
        on replay.  We simulate the second delivery by simply running
        process_message twice in a row against the same mocks.
        """
        consumer, session, sql_calls = _make_consumer()

        msg = {
            "event_id": str(uuid4()),
            "event_type": "market.instrument.discovered",
            "schema_version": 1,
            "occurred_at": "2026-04-30T12:00:00Z",
            "instrument_id": str(_INSTRUMENT_ID),
            "symbol": "AAPL",
            "exchange": "NASDAQ",
        }

        from unittest import mock

        emb_repo_mock = mock.AsyncMock()
        emb_repo_mock.ensure_rows_exist = mock.AsyncMock()

        with mock.patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=emb_repo_mock,
        ):
            asyncio.run(consumer.process_message(None, msg, {}))
            asyncio.run(consumer.process_message(None, msg, {}))

        # 2 deliveries x (1 canonical + 2 aliases) = 6 SQL calls
        assert len(sql_calls) == 6
        # commit happened twice (once per delivery)
        assert session.commit.await_count == 2

    def test_missing_exchange_defaults_to_null(self) -> None:
        """When exchange is None / missing, the canonical INSERT still works."""
        consumer, _session, sql_calls = _make_consumer()

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(_INSTRUMENT_ID),
            "symbol": "BRK.A",
            "exchange": None,
        }

        from unittest import mock

        with mock.patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=mock.AsyncMock(ensure_rows_exist=mock.AsyncMock()),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))

        canonical_params = sql_calls[0][1]
        assert canonical_params["exchange"] is None
        assert canonical_params["canonical_name"] == "BRK.A"


class TestInstrumentDiscoveredConsumerMalformed:
    def test_missing_symbol_raises_malformed(self) -> None:
        """Missing symbol → MalformedDataError so the message is dead-lettered."""
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

        consumer, _session, _sql_calls = _make_consumer()

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(_INSTRUMENT_ID),
            # symbol intentionally absent
            "exchange": "NASDAQ",
        }

        with pytest.raises(MalformedDataError, match="symbol"):
            asyncio.run(consumer.process_message(None, msg, {}))

    def test_blank_symbol_raises_malformed(self) -> None:
        """Whitespace-only symbol → MalformedDataError (not a usable canonical_name)."""
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

        consumer, _session, _sql_calls = _make_consumer()

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(_INSTRUMENT_ID),
            "symbol": "   ",
            "exchange": "NASDAQ",
        }

        with pytest.raises(MalformedDataError, match="symbol"):
            asyncio.run(consumer.process_message(None, msg, {}))


class TestInstrumentDiscoveredConsumerDedup:
    def test_is_duplicate_without_dedup_client_returns_false(self) -> None:
        """When no dedup client is configured, is_duplicate is always False."""
        consumer, _, _ = _make_consumer()  # _make_consumer omits dedup_client
        assert asyncio.run(consumer.is_duplicate("evt-1")) is False

    def test_is_duplicate_with_dedup_client_threads_through(self) -> None:
        """With a dedup client, is_duplicate forwards to dedup_client.exists."""
        from knowledge_graph.infrastructure.messaging.consumers.instrument_discovered_consumer import (
            InstrumentDiscoveredConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="kg-instrument-discovered-test",
            topics=["market.instrument.discovered.v1"],
        )
        dedup = AsyncMock()
        dedup.exists = AsyncMock(return_value=True)

        consumer = InstrumentDiscoveredConsumer(
            config=config,
            session_factory=MagicMock(),
            dedup_client=dedup,
        )
        result = asyncio.run(consumer.is_duplicate("evt-42"))
        assert result is True
        dedup.exists.assert_awaited_once()

    def test_extract_event_id_returns_envelope_field(self) -> None:
        consumer, _, _ = _make_consumer()
        eid = str(uuid4())
        assert consumer.extract_event_id({"event_id": eid, "symbol": "AAPL"}) == eid


# ---------------------------------------------------------------------------
# Recurrence-1 structural fix (2026-07-23 bottleneck audit / BP-736)
# ---------------------------------------------------------------------------


class _FakeKafkaMessage:
    """Minimal confluent-Kafka message stand-in for ``_handle_message`` tests."""

    def __init__(self, raw_value: bytes, *, offset: int = 6161, partition: int = 0) -> None:
        self._value = raw_value
        self._offset = offset
        self._partition = partition

    def topic(self) -> str:
        return "market.instrument.discovered.v1"

    def value(self) -> bytes:
        return self._value

    def key(self) -> bytes | None:
        return None

    def headers(self) -> list[tuple[str, bytes]]:
        return []

    def offset(self) -> int:
        return self._offset

    def partition(self) -> int:
        return self._partition


class TestInstrumentDiscoveredConsumerResilientDeserialize:
    """An un-decodable/poison record must be SKIPPED, not crash-loop the group.

    ``InstrumentDiscoveredConsumer.deserialize_value`` (lines 354-364, now
    354-380 after the fix below) has the same "looks protected but isn't"
    shape as ``InstrumentEntityConsumer``: it catches ``Exception`` from the
    Avro path and falls back to ``json.loads(raw)``, but a genuinely
    truncated/misaligned Avro payload that is ALSO not valid JSON makes the
    JSON fallback itself raise, and THAT second exception used to propagate
    out of ``deserialize_value`` UNCAUGHT as a raw ``UnicodeDecodeError``/
    ``JSONDecodeError`` — a type OUTSIDE ``BaseKafkaConsumer``'s decode-poison
    skip tuple ``(EOFError, struct.error)`` — so it still dead-lettered
    inline UNPROTECTED (found during independent review: the first version
    of this fix mocked ``deserialize_value`` in its tests, masking this exact
    gap). The fix re-raises the JSON fallback's failure as ``EOFError``. This
    class tests BOTH the base mechanism in isolation (mocked) AND the real,
    end-to-end, non-mocked path — the latter is the one that would have
    caught the original gap.
    """

    def test_undecodable_old_schema_record_is_skipped_not_raised(self) -> None:
        """Base mechanism in isolation: a mocked raw decode-poison exception is skipped."""
        from structlog.testing import capture_logs

        consumer, _session, _sql_calls = _make_consumer()
        msg = _FakeKafkaMessage(b"\x00garbage-not-avro-not-json")
        with (
            patch.object(consumer, "deserialize_value", side_effect=EOFError("short read")),
            capture_logs() as logs,
        ):
            asyncio.run(consumer._handle_message(msg))  # must not raise
        assert any(e["event"] == "kafka_consumer_deserialize_skipped" for e in logs)
        skip = next(e for e in logs if e["event"] == "kafka_consumer_deserialize_skipped")
        assert skip["offset"] == 6161
        assert consumer._dead_letter_count == 0

    def test_real_undecodable_payload_is_skipped_end_to_end_not_mocked(self) -> None:
        """End-to-end regression: a REAL genuinely-undecodable payload (not
        Avro, not JSON) must be skipped by the REAL, un-mocked
        ``deserialize_value`` → ``_handle_message`` path, not merely by a
        mocked stand-in. This is the test that would have caught the gap a
        mocked-``deserialize_value`` test cannot.
        """
        from structlog.testing import capture_logs

        consumer, _session, _sql_calls = _make_consumer()
        # Confluent magic byte + truncated/misaligned Avro body that is ALSO
        # not valid JSON/UTF-8 — real bytes, real deserialize_value, no mocks.
        msg = _FakeKafkaMessage(b"\x00\x00\x00\x00\x01not-json-either", offset=6363)
        with capture_logs() as logs:
            asyncio.run(consumer._handle_message(msg))  # must not raise
        assert any(e["event"] == "kafka_consumer_deserialize_skipped" for e in logs)
        skip = next(e for e in logs if e["event"] == "kafka_consumer_deserialize_skipped")
        assert skip["offset"] == 6363
        assert skip["error_type"] == "EOFError"  # re-raised type, not the raw JSONDecodeError
        assert consumer._dead_letter_count == 0

    def test_json_fallback_re_raises_as_eoferror_on_genuinely_undecodable_payload(self) -> None:
        """Un-decodable Avro AND non-JSON bytes must not silently succeed via a lucky parse.

        Must raise ``EOFError`` specifically (not just "any exception") so
        the base's skip-and-advance path — scoped to
        ``(EOFError, struct.error)``, deliberately NOT ``MalformedDataError``
        — actually handles it.
        """
        consumer, _session, _sql_calls = _make_consumer()
        raw = b"\x00\x00\x00\x00\x01not-json-either"
        with pytest.raises(EOFError):
            consumer.deserialize_value(raw)
