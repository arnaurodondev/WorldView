"""Unit tests for FundamentalsRefreshWorker (T-D-3-07) — Worker 13D-3."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000042")
_EMB_REPO = (
    "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository"
)


def _make_session_factory(due_rows: list) -> tuple:
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session

    emb_repo = AsyncMock()
    emb_repo.get_due_for_refresh = AsyncMock(return_value=due_rows)
    emb_repo.upsert = AsyncMock()

    return sf, emb_repo


class TestFundamentalsRefreshWorkerS3Failure:
    def test_s3_down_does_not_update_refresh_at(self) -> None:
        """HTTP failure -> upsert() never called (next_refresh_at not updated)."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": "AAPL",
                "canonical_name": "Apple Inc.",
                "entity_type": "financial_instrument",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        http_client = AsyncMock()
        http_client.get = AsyncMock(side_effect=RuntimeError("connection refused"))
        http_client.aclose = AsyncMock()

        llm = AsyncMock()
        llm.embed = AsyncMock(return_value=None)

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.run(worker.run())

        emb_repo.upsert.assert_not_awaited()

    def test_http_non_200_does_not_update_refresh_at(self) -> None:
        """HTTP 503 -> upsert() never called."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": "MSFT",
                "canonical_name": "Microsoft",
                "entity_type": "financial_instrument",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        mock_response = MagicMock()
        mock_response.status_code = 503

        http_client = AsyncMock()
        http_client.get = AsyncMock(return_value=mock_response)
        http_client.aclose = AsyncMock()

        llm = AsyncMock()

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.run(worker.run())

        emb_repo.upsert.assert_not_awaited()

    def test_non_ticker_entity_skipped(self) -> None:
        """Entity without ticker field -> skipped, no HTTP call, upsert not called."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": None,
                "canonical_name": "Some Person",
                "entity_type": "person",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        http_client = AsyncMock()
        http_client.get = AsyncMock()

        llm = AsyncMock()

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.run(worker.run())

        http_client.get.assert_not_awaited()
        emb_repo.upsert.assert_not_awaited()

    def test_successful_fetch_calls_upsert(self) -> None:
        """Successful HTTP 200 -> embed called, upsert called."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker
        from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-untyped]

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": "AAPL",
                "canonical_name": "Apple Inc.",
                "entity_type": "financial_instrument",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        fundamentals_data = {
            "revenue_usd_millions": 390000.0,
            "gross_margin_pct": 44.5,
            "net_margin_pct": 25.3,
            "pe_ratio": 28.0,
            "price": 189.0,
            "week_52_high": 200.0,
            "week_52_low": 130.0,
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=fundamentals_data)

        http_client = AsyncMock()
        http_client.get = AsyncMock(return_value=mock_response)
        http_client.aclose = AsyncMock()

        llm = AsyncMock()
        llm.embed = AsyncMock(
            return_value=[EmbeddingOutput(embedding=[0.1] * 10, model_id="nomic-embed-text", dimension=10)]
        )

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.run(worker.run())

        llm.embed.assert_awaited_once()
        emb_repo.upsert.assert_awaited_once()


# ── T-C-4-01: Earnings event insertion ───────────────────────────────────────

_EARNINGS_RECORD = {
    "id": "00000000-0000-0000-0000-000000000001",
    "section": "earnings_history",
    "period_end": "2024-09-30T00:00:00",
    "period_type": "quarterly",
    "data": {"epsActual": 1.64, "epsEstimate": 1.60, "revenueActual": 94900.0},
    "source": "eodhd",
    "ingested_at": "2024-10-01T00:00:00",
}


def _make_earnings_http(status: int = 200, records: list | None = None) -> AsyncMock:
    """Return an AsyncMock http_client whose .get() yields the given earnings response."""
    resp = MagicMock()
    resp.status_code = status
    if records is None:
        records = [_EARNINGS_RECORD]
    resp.json = MagicMock(return_value={"security_id": str(_ENTITY_ID), "records": records})
    http = AsyncMock()
    http.get = AsyncMock(return_value=resp)
    return http


def _make_session_for_earnings(dedup_found: bool = False) -> AsyncMock:
    """Return an AsyncMock session.

    First execute call (dedup SELECT) returns a row or None based on *dedup_found*.
    Second execute call (INSERT) returns a plain MagicMock.
    """
    dedup_result = MagicMock()
    dedup_result.fetchone.return_value = (1,) if dedup_found else None
    insert_result = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[dedup_result, insert_result])
    return session


def _make_worker_bare() -> object:
    from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

    sf = MagicMock()
    llm = AsyncMock()
    return FundamentalsRefreshWorker(sf, llm, "http://market-data:8003")


class TestEarningsEventInsertion:
    """Tests for FundamentalsRefreshWorker._insert_earnings_events (T-C-4-01)."""

    def test_earnings_event_inserted(self) -> None:
        """New earnings record (dedup SELECT returns nothing) → INSERT executed."""
        http = _make_earnings_http()
        session = _make_session_for_earnings(dedup_found=False)
        worker = _make_worker_bare()

        count = asyncio.run(worker._insert_earnings_events(http, session, _ENTITY_ID, _ENTITY_ID, "AAPL", "Apple Inc."))

        assert count == 1
        # First call = dedup SELECT, second call = INSERT
        assert session.execute.call_count == 2

    def test_earnings_event_idempotent(self) -> None:
        """Existing earnings record (dedup SELECT returns row) → INSERT skipped, count=0."""
        http = _make_earnings_http()
        session = _make_session_for_earnings(dedup_found=True)
        worker = _make_worker_bare()

        count = asyncio.run(worker._insert_earnings_events(http, session, _ENTITY_ID, _ENTITY_ID, "AAPL", "Apple Inc."))

        assert count == 0
        # Only the dedup SELECT; no INSERT
        assert session.execute.call_count == 1

    def test_earnings_s3_404_skipped(self) -> None:
        """S3 returns 404 → no DB execute, count=0, no error raised."""
        http = _make_earnings_http(status=404)
        session = AsyncMock()
        worker = _make_worker_bare()

        count = asyncio.run(worker._insert_earnings_events(http, session, _ENTITY_ID, _ENTITY_ID, "AAPL", "Apple Inc."))

        assert count == 0
        session.execute.assert_not_awaited()


# ── T-C-4-02: Sector/industry relation upsert ────────────────────────────────

_SECTOR_ENTITY_ID = UUID("0195daad-a008-7008-8008-000000000008")  # Information Technology seed ID
_INDUSTRY_ENTITY_ID = UUID("0195daad-b013-7013-8013-000000000013")  # Software & Services seed ID


def _make_profile_http(status: int = 200, gic_sector: str = "Information Technology") -> AsyncMock:
    """Return an AsyncMock http_client whose .get() yields the given company-profile response."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(
        return_value={
            "security_id": str(_ENTITY_ID),
            "records": [
                {
                    "id": "00000000-0000-0000-0000-000000000002",
                    "section": "company_profile",
                    "period_end": "2024-10-01T00:00:00",
                    "period_type": "snapshot",
                    "data": {"GicSector": gic_sector, "GicGroup": "Software & Services"},
                    "source": "eodhd",
                    "ingested_at": "2024-10-01T00:00:00",
                }
            ],
        }
    )
    http = AsyncMock()
    http.get = AsyncMock(return_value=resp)
    return http


def _make_sector_repos(sector_found: bool = True, industry_found: bool = True) -> tuple:
    """Return (relation_repo, evidence_repo, entity_repo) mocks."""
    relation_repo = AsyncMock()
    relation_repo.upsert = AsyncMock(return_value=UUID("00000000-0000-0000-0000-000000000010"))
    evidence_repo = AsyncMock()
    evidence_repo.insert_raw = AsyncMock()
    entity_repo = AsyncMock()
    entity_repo.find_by_name_and_type = AsyncMock(
        side_effect=lambda name, typ: (
            _SECTOR_ENTITY_ID
            if typ == "sector" and sector_found
            else (_INDUSTRY_ENTITY_ID if typ == "industry_group" and industry_found else None)
        )
    )
    return relation_repo, evidence_repo, entity_repo


class TestSectorRelationUpsert:
    """Tests for FundamentalsRefreshWorker._upsert_sector_relations (T-C-4-02)."""

    def test_sector_relation_upserted(self) -> None:
        """Valid sector + industry → relation_repo.upsert and evidence_repo.insert_raw called."""
        http = _make_profile_http()
        relation_repo, evidence_repo, entity_repo = _make_sector_repos()
        worker = _make_worker_bare()

        count = asyncio.run(
            worker._upsert_sector_relations(http, _ENTITY_ID, _ENTITY_ID, relation_repo, evidence_repo, entity_repo)
        )

        assert count == 2  # is_in_sector + is_in_industry
        assert relation_repo.upsert.await_count == 2
        assert evidence_repo.insert_raw.await_count == 2
        # Verify canonical_type args: sector first, industry second
        sector_call_kwargs = relation_repo.upsert.call_args_list[0].kwargs
        assert sector_call_kwargs["canonical_type"] == "is_in_sector"
        industry_call_kwargs = relation_repo.upsert.call_args_list[1].kwargs
        assert industry_call_kwargs["canonical_type"] == "is_in_industry"

    def test_sector_entity_not_found_skipped(self) -> None:
        """Sector/industry not in canonical_entities → no relation upsert, count=0, no error."""
        http = _make_profile_http(gic_sector="Unknown Sector XYZ")
        relation_repo, evidence_repo, entity_repo = _make_sector_repos(sector_found=False, industry_found=False)
        worker = _make_worker_bare()

        count = asyncio.run(
            worker._upsert_sector_relations(http, _ENTITY_ID, _ENTITY_ID, relation_repo, evidence_repo, entity_repo)
        )

        assert count == 0
        relation_repo.upsert.assert_not_awaited()
        evidence_repo.insert_raw.assert_not_awaited()

    def test_sector_relation_idempotent(self) -> None:
        """Second run with same sector → relation_repo.upsert called again (advisory lock upsert)."""
        http = _make_profile_http()
        relation_repo, evidence_repo, entity_repo = _make_sector_repos()
        worker = _make_worker_bare()

        asyncio.run(
            worker._upsert_sector_relations(http, _ENTITY_ID, _ENTITY_ID, relation_repo, evidence_repo, entity_repo)
        )
        asyncio.run(
            worker._upsert_sector_relations(http, _ENTITY_ID, _ENTITY_ID, relation_repo, evidence_repo, entity_repo)
        )

        # Advisory-lock upsert is called on every run (idempotency handled at DB level)
        assert relation_repo.upsert.await_count == 4  # 2 relations x 2 runs
