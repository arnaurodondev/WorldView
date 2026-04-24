"""Unit tests for InsiderTransactionsDatasetConsumer (Consumer 13D-8).

Replaces the former test_insider_transactions_worker.py.
Tests cover:
- is_executive_title() whitelist (all keyword variations).
- Filter: non-insider_transactions dataset_type silently skipped.
- Happy path: CEO transaction → has_executive relation upserted.
- Evidence text: 'bought' vs 'sold' direction from transactionAcquiredDisposed.
- Non-executive title: filtered out, relation skipped.
- No-name transactions: skipped.
- Deduplication: same officer in multiple transactions → one relation.
- Two different officers → two relations.
- Empty transactions list: no relations, no instrument lookup.
- Instrument not found: no crash, no relations.
- Session committed after processing.
- Prometheus counters.
- Storage failure: handled gracefully.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_COMPANY_ENTITY_ID = UUID("01910000-0000-7000-8000-000000000010")
_PERSON_ENTITY_ID = UUID("01910000-0000-7000-8000-000000000020")
_RELATION_ID = UUID("01910000-0000-7000-8000-000000000030")

_ENTITY_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository.EntityRepository"
_RELATION_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_instrument(
    entity_id: UUID = _COMPANY_ENTITY_ID,
    ticker: str = "AAPL",
    canonical_name: str = "Apple Inc.",
) -> Any:
    """Build a mock InstrumentRecord."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
        InstrumentRecord,
    )

    return InstrumentRecord(entity_id=entity_id, ticker=ticker, canonical_name=canonical_name)


def _make_consumer(
    instrument: Any | None = None,
    person_entity_id: UUID = _PERSON_ENTITY_ID,
    storage_bytes: bytes | None = None,
    storage_error: Exception | None = None,
) -> tuple[Any, Any, Any]:
    """Build InsiderTransactionsDatasetConsumer with mocked dependencies.

    Returns:
        (consumer, entity_repo_mock, relation_repo_mock)
    """
    from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
        InsiderTransactionsDatasetConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-insider-transactions-test",
        topics=["market.dataset.fetched"],
    )

    # Session factory mock
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session

    # Storage mock
    storage = AsyncMock()
    if storage_error is not None:
        storage.get_bytes = AsyncMock(side_effect=storage_error)
    elif storage_bytes is not None:
        storage.get_bytes = AsyncMock(return_value=storage_bytes)

    # Entity repo mock
    entity_repo = AsyncMock()
    if instrument is None:
        instrument = _make_instrument()
    entity_repo.find_instrument_by_ticker = AsyncMock(return_value=instrument)
    entity_repo.find_or_create_person = AsyncMock(return_value=person_entity_id)

    # Relation repo mock
    relation_repo = AsyncMock()
    relation_repo.upsert_relation = AsyncMock(return_value=_RELATION_ID)

    consumer = InsiderTransactionsDatasetConsumer(
        config=config,
        session_factory=sf,
        storage_client=storage,
    )

    return consumer, entity_repo, relation_repo


def _make_envelope(transactions: list[dict[str, Any]], symbol: str = "AAPL") -> bytes:
    """Build canonical NDJSON envelope bytes for insider transactions."""
    envelope = {
        "dataset_type": "insider_transactions",
        "symbol": symbol,
        "source": "eodhd",
        "payload": transactions,
        "fetched_at": "2026-04-07T02:00:00+00:00",
    }
    return (json.dumps(envelope) + "\n").encode("utf-8")


def _make_message(
    symbol: str = "AAPL",
    dataset_type: str = "insider_transactions",
    bucket: str = "canonical",
    key: str = "insider_transactions/aapl.ndjson",
) -> dict[str, Any]:
    """Build a decoded Avro dict for market.dataset.fetched."""
    return {
        "event_id": str(uuid4()),
        "dataset_type": dataset_type,
        "symbol": symbol,
        "canonical_ref_bucket": bucket,
        "canonical_ref_key": key,
    }


def _run(consumer: Any, entity_repo: Any, relation_repo: Any, msg: dict[str, Any]) -> None:
    """Run process_message with patched repositories."""
    with patch(_ENTITY_REPO, return_value=entity_repo), patch(_RELATION_REPO, return_value=relation_repo):
        asyncio.run(consumer.process_message(None, msg, {}))


# ── Test: is_executive_title ─────────────────────────────────────────────────


class TestIsExecutiveTitle:
    def test_ceo_included(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("CEO") is True

    def test_cfo_included(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("CFO") is True

    def test_coo_included(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("COO") is True

    def test_director_included(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("Director") is True

    def test_vp_included(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("VP") is True

    def test_vp_comma_qualifier_included(self) -> None:
        """'VP, Finance' is accepted (comma-qualified prefix)."""
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("VP, Finance") is True

    def test_vp_space_qualifier_excluded(self) -> None:
        """'VP Sales' is excluded (space qualifier = department head, not C-suite)."""
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("VP Sales") is False

    def test_general_counsel_included(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("General Counsel") is True

    def test_ten_percent_owner_included(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("10% Owner") is True

    def test_empty_title_excluded(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("") is False

    def test_random_title_excluded(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("Accountant") is False

    def test_case_insensitive(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
            is_executive_title,
        )

        assert is_executive_title("ceo") is True
        assert is_executive_title("Cfo") is True
        assert is_executive_title("DIRECTOR") is True


# ── Test: filter by dataset_type ─────────────────────────────────────────────


class TestInsiderTransactionsConsumerFilter:
    def test_economic_events_type_skipped(self) -> None:
        """dataset_type='economic_events' → process_message returns early."""
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=b"")
        msg = _make_message(dataset_type="economic_events")
        _run(consumer, entity_repo, relation_repo, msg)
        consumer._storage.get_bytes.assert_not_awaited()
        relation_repo.upsert_relation.assert_not_awaited()

    def test_macro_indicator_type_skipped(self) -> None:
        consumer, entity_repo, relation_repo = _make_consumer()
        msg = _make_message(dataset_type="macro_indicator")
        _run(consumer, entity_repo, relation_repo, msg)
        relation_repo.upsert_relation.assert_not_awaited()


# ── Test: happy path ──────────────────────────────────────────────────────────


class TestInsiderTransactionsConsumerHappyPath:
    def test_ceo_transaction_creates_has_executive_relation(self) -> None:
        """CEO transaction → has_executive relation upserted (company → person)."""
        transactions = [{"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        entity_repo.find_or_create_person.assert_awaited_once_with(
            name="Tim Cook",
            context_ticker="AAPL",
        )
        relation_repo.upsert_relation.assert_awaited_once()
        kwargs = relation_repo.upsert_relation.call_args.kwargs
        assert kwargs["subject_entity_id"] == _COMPANY_ENTITY_ID
        assert kwargs["object_entity_id"] == _PERSON_ENTITY_ID
        assert kwargs["canonical_type"] == "has_executive"
        assert kwargs["source_weight"] == 0.90
        assert kwargs["is_backfill"] is True

    def test_evidence_text_acquired_means_bought(self) -> None:
        """'A' (Acquired) → evidence text says 'bought'."""
        transactions = [{"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        evidence = relation_repo.upsert_relation.call_args.kwargs["evidence_text"]
        assert "bought" in evidence
        assert "Tim Cook" in evidence
        assert "CEO" in evidence

    def test_evidence_text_disposed_means_sold(self) -> None:
        """'D' (Disposed) → evidence text says 'sold'."""
        transactions = [{"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "D"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        evidence = relation_repo.upsert_relation.call_args.kwargs["evidence_text"]
        assert "sold" in evidence

    def test_session_committed_after_processing(self) -> None:
        """session.commit() called once after all relations upserted."""
        transactions = [{"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        consumer._sf.return_value.commit.assert_awaited()

    def test_ticker_extracted_from_symbol_with_exchange_suffix(self) -> None:
        """Symbol 'AAPL.US' → ticker 'AAPL' (exchange suffix stripped)."""
        transactions = [{"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions, symbol="AAPL.US"))

        _run(consumer, entity_repo, relation_repo, _make_message(symbol="AAPL.US"))

        entity_repo.find_instrument_by_ticker.assert_awaited_once_with("AAPL")


# ── Test: title filter ────────────────────────────────────────────────────────


class TestInsiderTransactionsConsumerTitleFilter:
    def test_non_executive_title_skipped(self) -> None:
        """VP Sales (non-executive) → no relation created."""
        transactions = [{"ownerName": "Jane Doe", "ownerTitle": "VP Sales", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        relation_repo.upsert_relation.assert_not_awaited()
        entity_repo.find_or_create_person.assert_not_awaited()

    def test_mixed_titles_only_executive_creates_relation(self) -> None:
        """VP Sales (skipped) + CEO (included) → exactly 1 relation created."""
        transactions = [
            {"ownerName": "Jane Doe", "ownerTitle": "VP Sales", "transactionAcquiredDisposed": "A"},
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"},
        ]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        assert relation_repo.upsert_relation.await_count == 1
        evidence = relation_repo.upsert_relation.call_args.kwargs["evidence_text"]
        assert "Tim Cook" in evidence
        assert "Jane Doe" not in evidence

    def test_no_name_transactions_skipped(self) -> None:
        """Empty ownerName → skipped, no relation."""
        transactions = [{"ownerName": "", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        relation_repo.upsert_relation.assert_not_awaited()


# ── Test: deduplication ────────────────────────────────────────────────────────


class TestInsiderTransactionsConsumerDeduplication:
    def test_same_officer_three_transactions_one_relation(self) -> None:
        """Same officer in 3 transactions → exactly 1 has_executive relation."""
        transactions = [
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"},
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "D"},
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"},
        ]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        entity_repo.find_or_create_person.assert_awaited_once_with(
            name="Tim Cook",
            context_ticker="AAPL",
        )
        relation_repo.upsert_relation.assert_awaited_once()

    def test_two_different_officers_two_relations(self) -> None:
        """Two different executives → 2 has_executive relations."""
        transactions = [
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"},
            {"ownerName": "Luca Maestri", "ownerTitle": "CFO", "transactionAcquiredDisposed": "D"},
        ]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        assert relation_repo.upsert_relation.await_count == 2


# ── Test: empty payload ────────────────────────────────────────────────────────


class TestInsiderTransactionsConsumerEmptyPayload:
    def test_empty_transactions_no_relations(self) -> None:
        """Empty transaction list → no relations, no instrument lookup."""
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([]))

        _run(consumer, entity_repo, relation_repo, _make_message())

        entity_repo.find_instrument_by_ticker.assert_not_awaited()
        relation_repo.upsert_relation.assert_not_awaited()


# ── Test: instrument not found ────────────────────────────────────────────────


class TestInsiderTransactionsConsumerInstrumentNotFound:
    def test_no_crash_when_instrument_not_found(self) -> None:
        """find_instrument_by_ticker returns None → no relations, no crash."""
        transactions = [{"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer(instrument=None)
        entity_repo.find_instrument_by_ticker = AsyncMock(return_value=None)
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        _run(consumer, entity_repo, relation_repo, _make_message())

        relation_repo.upsert_relation.assert_not_awaited()


# ── Test: storage failure ─────────────────────────────────────────────────────


class TestInsiderTransactionsConsumerStorageError:
    def test_storage_exception_does_not_crash(self) -> None:
        """Storage failure → returns cleanly, no relations."""
        consumer, entity_repo, relation_repo = _make_consumer(storage_error=RuntimeError("minio unavailable"))

        _run(consumer, entity_repo, relation_repo, _make_message())

        relation_repo.upsert_relation.assert_not_awaited()


# ── Test: Prometheus counters ──────────────────────────────────────────────────


class TestInsiderTransactionsConsumerPrometheus:
    def test_relations_counter_incremented(self) -> None:
        """s7_insider_transactions_relations_total{ticker=AAPL} incremented."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            s7_insider_transactions_relations_total,
        )

        transactions = [{"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        before = s7_insider_transactions_relations_total.labels(ticker="AAPL")._value.get()
        _run(consumer, entity_repo, relation_repo, _make_message())
        after = s7_insider_transactions_relations_total.labels(ticker="AAPL")._value.get()

        assert after - before == 1.0

    def test_skipped_non_executive_counter_incremented(self) -> None:
        """s7_insider_transactions_skipped_total{reason=non_executive_title} incremented."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            s7_insider_transactions_skipped_total,
        )

        transactions = [{"ownerName": "Jane Doe", "ownerTitle": "VP Sales", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        before = s7_insider_transactions_skipped_total.labels(reason="non_executive_title")._value.get()
        _run(consumer, entity_repo, relation_repo, _make_message())
        after = s7_insider_transactions_skipped_total.labels(reason="non_executive_title")._value.get()

        assert after - before == 1.0

    def test_skipped_no_name_counter_incremented(self) -> None:
        """s7_insider_transactions_skipped_total{reason=no_name} incremented."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            s7_insider_transactions_skipped_total,
        )

        transactions = [{"ownerName": "", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        consumer, entity_repo, relation_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope(transactions))

        before = s7_insider_transactions_skipped_total.labels(reason="no_name")._value.get()
        _run(consumer, entity_repo, relation_repo, _make_message())
        after = s7_insider_transactions_skipped_total.labels(reason="no_name")._value.get()

        assert after - before == 1.0
