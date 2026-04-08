"""Unit tests for InsiderTransactionsWorker (Worker 13D-8) — PRD-0018 §6 Worker 13D-8."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_COMPANY_ENTITY_ID = UUID("01910000-0000-7000-8000-000000000010")
_PERSON_ENTITY_ID = UUID("01910000-0000-7000-8000-000000000020")
_RELATION_ID = UUID("01910000-0000-7000-8000-000000000030")

_AAPL_INSTRUMENT = None  # initialised per-test via _make_instrument()

# Patch paths for lazy repository imports inside the worker
_ENTITY_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories" ".entity_repository.EntityRepository"
_RELATION_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories" ".relation.RelationRepository"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_instrument(
    ticker: str = "AAPL",
    canonical_name: str = "Apple Inc.",
    entity_id: UUID = _COMPANY_ENTITY_ID,
) -> Any:
    """Build a mock InstrumentRecord-like object."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
        InstrumentRecord,
    )

    return InstrumentRecord(entity_id=entity_id, ticker=ticker, canonical_name=canonical_name)


def _make_entity_repo(
    person_entity_id: UUID = _PERSON_ENTITY_ID,
    instruments: list[Any] | None = None,
) -> Any:
    """Build a mock EntityRepository."""
    repo = AsyncMock()
    repo.list_us_instruments = AsyncMock(return_value=[_make_instrument()] if instruments is None else instruments)
    repo.find_or_create_person = AsyncMock(return_value=person_entity_id)
    return repo


def _make_relation_repo(relation_id: UUID = _RELATION_ID) -> Any:
    """Build a mock RelationRepository."""
    repo = AsyncMock()
    repo.upsert_relation = AsyncMock(return_value=relation_id)
    return repo


def _make_session_factory() -> Any:
    """Build a mock async session factory."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session
    return sf


def _make_eodhd_client(transactions: list[dict[str, Any]] | None = None) -> Any:
    """Build a mock EodhDClient."""
    client = AsyncMock()
    client.get_insider_transactions = AsyncMock(return_value=transactions or [])
    return client


def _run_worker(
    transactions: list[dict[str, Any]] | None = None,
    instruments: list[Any] | None = None,
    person_entity_id: UUID = _PERSON_ENTITY_ID,
) -> tuple[Any, Any, Any]:
    """Build worker, patch repos, run worker.

    Returns:
        Tuple of (entity_repo_mock, relation_repo_mock, eodhd_client_mock).
    """
    from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
        InsiderTransactionsWorker,
    )

    entity_repo = _make_entity_repo(person_entity_id=person_entity_id, instruments=instruments)
    relation_repo = _make_relation_repo()
    eodhd_client = _make_eodhd_client(transactions=transactions)
    sf = _make_session_factory()

    worker = InsiderTransactionsWorker(session_factory=sf, eodhd_client=eodhd_client)

    with patch(_ENTITY_REPO, return_value=entity_repo), patch(_RELATION_REPO, return_value=relation_repo):
        asyncio.run(worker.run())

    return entity_repo, relation_repo, eodhd_client


# ── Tests: Title filter ───────────────────────────────────────────────────────


class TestIsExecutiveTitle:
    def test_ceo_included(self) -> None:
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("CEO") is True

    def test_cfo_included(self) -> None:
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("CFO") is True

    def test_director_included(self) -> None:
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("Director") is True

    def test_vp_included(self) -> None:
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("VP") is True

    def test_general_counsel_included(self) -> None:
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("General Counsel") is True

    def test_ten_percent_owner_included(self) -> None:
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("10% Owner") is True

    def test_vp_comma_qualifier_included(self) -> None:
        """'VP, Finance' is an accepted comma-qualified prefix."""
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("VP, Finance") is True

    def test_vp_sales_excluded(self) -> None:
        """'VP Sales' has a space qualifier → non-executive title, filtered out."""
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("VP Sales") is False

    def test_empty_title_excluded(self) -> None:
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("") is False

    def test_random_title_excluded(self) -> None:
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("Accountant") is False

    def test_case_insensitive(self) -> None:
        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            is_executive_title,
        )

        assert is_executive_title("ceo") is True
        assert is_executive_title("Cfo") is True


# ── Tests: CEO creates relation ───────────────────────────────────────────────


class TestInsiderTransactionsWorkerCreatesRelation:
    def test_ceo_transaction_creates_has_executive_relation(self) -> None:
        """CEO transaction for AAPL → has_executive relation upserted (company → person)."""
        transactions = [
            {
                "ownerName": "Tim Cook",
                "ownerTitle": "CEO",
                "transactionAcquiredDisposed": "A",
            }
        ]
        entity_repo, relation_repo, _ = _run_worker(transactions=transactions)

        # Person entity created with correct name
        entity_repo.find_or_create_person.assert_awaited_once_with(
            name="Tim Cook",
            context_ticker="AAPL",
        )

        # Relation upserted as has_executive
        relation_repo.upsert_relation.assert_awaited_once()
        kwargs = relation_repo.upsert_relation.call_args.kwargs
        assert kwargs["subject_entity_id"] == _COMPANY_ENTITY_ID
        assert kwargs["object_entity_id"] == _PERSON_ENTITY_ID
        assert kwargs["canonical_type"] == "has_executive"
        assert kwargs["source_weight"] == 0.90
        assert kwargs["is_backfill"] is True

    def test_evidence_text_includes_direction_bought(self) -> None:
        """Transaction with 'A' (Acquired) → evidence text says 'bought'."""
        transactions = [
            {
                "ownerName": "Tim Cook",
                "ownerTitle": "CEO",
                "transactionAcquiredDisposed": "A",
            }
        ]
        _, relation_repo, _ = _run_worker(transactions=transactions)

        evidence = relation_repo.upsert_relation.call_args.kwargs["evidence_text"]
        assert "bought" in evidence
        assert "Tim Cook" in evidence
        assert "CEO" in evidence

    def test_evidence_text_includes_direction_sold(self) -> None:
        """Transaction with 'D' (Disposed) → evidence text says 'sold'."""
        transactions = [
            {
                "ownerName": "Tim Cook",
                "ownerTitle": "CEO",
                "transactionAcquiredDisposed": "D",
            }
        ]
        _, relation_repo, _ = _run_worker(transactions=transactions)

        evidence = relation_repo.upsert_relation.call_args.kwargs["evidence_text"]
        assert "sold" in evidence

    def test_session_committed_after_processing(self) -> None:
        """session.commit() is called once per instrument."""
        transactions = [{"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        sf = _make_session_factory()
        entity_repo = _make_entity_repo()
        relation_repo = _make_relation_repo()
        eodhd_client = _make_eodhd_client(transactions=transactions)

        from knowledge_graph.infrastructure.workers.insider_transactions_worker import (
            InsiderTransactionsWorker,
        )

        worker = InsiderTransactionsWorker(session_factory=sf, eodhd_client=eodhd_client)
        with patch(_ENTITY_REPO, return_value=entity_repo), patch(_RELATION_REPO, return_value=relation_repo):
            asyncio.run(worker.run())

        sf.return_value.commit.assert_awaited()


# ── Tests: Title filter integration ──────────────────────────────────────────


class TestInsiderTransactionsWorkerTitleFilter:
    def test_vp_sales_filtered_ceo_included(self) -> None:
        """VP Sales (non-executive) → skipped; CEO → included. Only 1 relation created."""
        transactions = [
            {
                "ownerName": "Jane Doe",
                "ownerTitle": "VP Sales",
                "transactionAcquiredDisposed": "A",
            },
            {
                "ownerName": "Tim Cook",
                "ownerTitle": "CEO",
                "transactionAcquiredDisposed": "A",
            },
        ]
        entity_repo, relation_repo, _ = _run_worker(transactions=transactions)

        # Only CEO creates a relation; VP Sales is skipped
        assert relation_repo.upsert_relation.await_count == 1
        kwargs = relation_repo.upsert_relation.call_args.kwargs
        evidence = kwargs["evidence_text"]
        assert "Tim Cook" in evidence
        assert "Jane Doe" not in evidence

    def test_no_name_skipped(self) -> None:
        """Transactions with empty ownerName are silently skipped."""
        transactions = [
            {"ownerName": "", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"},
        ]
        _, relation_repo, _ = _run_worker(transactions=transactions)
        relation_repo.upsert_relation.assert_not_awaited()

    def test_empty_transactions_no_relation(self) -> None:
        """Empty transaction list → no relations, no person lookup."""
        entity_repo, relation_repo, _ = _run_worker(transactions=[])
        relation_repo.upsert_relation.assert_not_awaited()
        entity_repo.find_or_create_person.assert_not_awaited()

    def test_no_us_instruments_no_eodhd_call(self) -> None:
        """No US instruments → EODHD not called."""
        _, _, eodhd_client = _run_worker(instruments=[])
        eodhd_client.get_insider_transactions.assert_not_awaited()


# ── Tests: Deduplication ──────────────────────────────────────────────────────


class TestInsiderTransactionsWorkerDeduplication:
    def test_same_officer_three_transactions_one_relation(self) -> None:
        """Same officer appearing in 3 transactions → exactly 1 has_executive relation."""
        transactions = [
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"},
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "D"},
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"},
        ]
        entity_repo, relation_repo, _ = _run_worker(transactions=transactions)

        # find_or_create_person called once (deduplication via seen_officers dict)
        entity_repo.find_or_create_person.assert_awaited_once_with(
            name="Tim Cook",
            context_ticker="AAPL",
        )
        # upsert_relation called once
        relation_repo.upsert_relation.assert_awaited_once()

    def test_two_different_officers_two_relations(self) -> None:
        """Two different executives → 2 has_executive relations created."""
        transactions = [
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"},
            {"ownerName": "Luca Maestri", "ownerTitle": "CFO", "transactionAcquiredDisposed": "D"},
        ]
        _, relation_repo, _ = _run_worker(transactions=transactions)
        assert relation_repo.upsert_relation.await_count == 2

    def test_first_occurrence_of_officer_title_used(self) -> None:
        """When same officer appears multiple times, first title is recorded in seen_officers."""
        transactions = [
            {"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"},
            # Second occurrence should be deduplicated by seen_officers
            {"ownerName": "Tim Cook", "ownerTitle": "President", "transactionAcquiredDisposed": "D"},
        ]
        _, relation_repo, _ = _run_worker(transactions=transactions)

        relation_repo.upsert_relation.assert_awaited_once()
        evidence = relation_repo.upsert_relation.call_args.kwargs["evidence_text"]
        # First title (CEO) is stored, not the second (President)
        assert "CEO" in evidence


# ── Tests: Prometheus counters ────────────────────────────────────────────────


class TestInsiderTransactionsWorkerPrometheus:
    def test_relations_counter_incremented(self) -> None:
        """s7_insider_transactions_relations_total incremented for each relation."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            s7_insider_transactions_relations_total,
        )

        transactions = [{"ownerName": "Tim Cook", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        before = s7_insider_transactions_relations_total.labels(ticker="AAPL")._value.get()
        _run_worker(transactions=transactions)
        after = s7_insider_transactions_relations_total.labels(ticker="AAPL")._value.get()
        assert after - before == 1.0

    def test_skipped_counter_incremented_for_non_executive(self) -> None:
        """s7_insider_transactions_skipped_total{reason=non_executive_title} incremented."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            s7_insider_transactions_skipped_total,
        )

        transactions = [{"ownerName": "Jane Doe", "ownerTitle": "VP Sales", "transactionAcquiredDisposed": "A"}]
        before = s7_insider_transactions_skipped_total.labels(reason="non_executive_title")._value.get()
        _run_worker(transactions=transactions)
        after = s7_insider_transactions_skipped_total.labels(reason="non_executive_title")._value.get()
        assert after - before == 1.0

    def test_skipped_counter_incremented_for_no_name(self) -> None:
        """s7_insider_transactions_skipped_total{reason=no_name} incremented."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            s7_insider_transactions_skipped_total,
        )

        transactions = [{"ownerName": "", "ownerTitle": "CEO", "transactionAcquiredDisposed": "A"}]
        before = s7_insider_transactions_skipped_total.labels(reason="no_name")._value.get()
        _run_worker(transactions=transactions)
        after = s7_insider_transactions_skipped_total.labels(reason="no_name")._value.get()
        assert after - before == 1.0


# ── Tests: Multiple instruments ───────────────────────────────────────────────


class TestInsiderTransactionsWorkerMultipleInstruments:
    def test_each_instrument_triggers_eodhd_call(self) -> None:
        """Worker calls get_insider_transactions once per instrument."""
        instruments = [
            _make_instrument(ticker="AAPL", entity_id=UUID("01910000-0000-7000-8000-000000000011")),
            _make_instrument(
                ticker="MSFT",
                canonical_name="Microsoft Corp.",
                entity_id=UUID("01910000-0000-7000-8000-000000000012"),
            ),
        ]
        _, _, eodhd_client = _run_worker(transactions=[], instruments=instruments)

        assert eodhd_client.get_insider_transactions.await_count == 2
        codes_called = {c.kwargs["code"] for c in eodhd_client.get_insider_transactions.call_args_list}
        assert codes_called == {"AAPL.US", "MSFT.US"}
