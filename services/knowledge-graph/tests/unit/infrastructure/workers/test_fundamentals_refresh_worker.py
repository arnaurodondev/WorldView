"""Unit tests for FundamentalsRefreshWorker (T-D-3-07) — Worker 13D-3."""

from __future__ import annotations

import asyncio
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000042")
_EMB_REPO = (
    "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository"
)


def _make_fundamentals_response(
    *,
    security_id: str = "00000000-0000-0000-0000-000000000999",
    revenue_ttm: float | None = 390_000_000_000.0,  # USD raw, → 390_000.0 millions
    gross_profit: float | None = 173_000_000_000.0,
    net_income: float | None = 98_700_000_000.0,
    total_revenue: float | None = 390_000_000_000.0,
    pe_ratio: float | None = 28.0,
    price: float | None = 189.0,
    week_52_high: float | None = 200.0,
    week_52_low: float | None = 130.0,
    description: str | None = None,
) -> dict[str, object]:
    """Build a response matching the REAL ``GET /api/v1/fundamentals/{id}`` schema.

    F-DB-005 (2026-05-28): the previous fixtures (lines 144-152, 514) stubbed
    a flat ``{revenue_usd_millions, pe_ratio, price, ...}`` shape that the
    production endpoint NEVER returned. That mismatch hid the bug for months.
    This helper now mirrors the canonical schema at
    ``services/market-data/src/market_data/api/schemas/fundamentals.py:24-28``
    so any future drift between the worker and market-data is caught by the
    unit tests, not by ops dashboards.

    Section names match the ``FundamentalsSection`` enum
    (``services/market-data/src/market_data/domain/enums.py:63-69``). The
    inner ``data`` dict uses EODHD's CamelCase keys (``PERatio``,
    ``RevenueTTM``, ``totalRevenue``, ...) because market-ingestion stores
    them verbatim — see ``docs/audits/2026-05-28-fundamentals-shape-audit.md``
    Stage 3 for the canonical shape.
    """
    records: list[dict[str, object]] = []
    highlights_data: dict[str, object] = {}
    if revenue_ttm is not None:
        highlights_data["RevenueTTM"] = revenue_ttm
    if pe_ratio is not None:
        highlights_data["PERatio"] = pe_ratio
    if highlights_data:
        records.append(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "security_id": security_id,
                "section": "highlights",
                "period_end": "2026-03-31T00:00:00Z",
                "period_type": "QUARTERLY",
                "data": highlights_data,
                "source": "eodhd",
                "ingested_at": "2026-05-01T00:00:00Z",
            }
        )

    income_data: dict[str, object] = {}
    if total_revenue is not None:
        income_data["totalRevenue"] = total_revenue
    if gross_profit is not None:
        income_data["grossProfit"] = gross_profit
    if net_income is not None:
        income_data["netIncome"] = net_income
    if income_data:
        records.append(
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "security_id": security_id,
                "section": "income_statement",
                "period_end": "2026-03-31T00:00:00Z",
                "period_type": "QUARTERLY",
                "data": income_data,
                "source": "eodhd",
                "ingested_at": "2026-05-01T00:00:00Z",
            }
        )

    technicals_data: dict[str, object] = {}
    if price is not None:
        technicals_data["Price"] = price
    if week_52_high is not None:
        technicals_data["52WeekHigh"] = week_52_high
    if week_52_low is not None:
        technicals_data["52WeekLow"] = week_52_low
    if technicals_data:
        records.append(
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "security_id": security_id,
                "section": "technicals_snapshot",
                "period_end": "2026-05-01T00:00:00Z",
                "period_type": "QUARTERLY",
                "data": technicals_data,
                "source": "eodhd",
                "ingested_at": "2026-05-01T00:00:00Z",
            }
        )

    if description is not None:
        records.append(
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "security_id": security_id,
                "section": "company_profile",
                "period_end": "2026-01-01T00:00:00Z",
                "period_type": "ANNUAL",
                "data": {"Description": description},
                "source": "eodhd",
                "ingested_at": "2026-05-01T00:00:00Z",
            }
        )

    return {"security_id": security_id, "records": records}


def _make_session_factory(due_rows: list) -> tuple:
    """Return (session_factory, emb_repo).

    The factory returns a fresh context-manager each call (ARCH-004: run()
    opens separate sessions for Phase 1 read and Phase 3 write).  All context
    managers share the same underlying session mock so assertions work.
    """
    session = AsyncMock()
    session.commit = AsyncMock()

    def _make_cm():
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    sf = MagicMock(side_effect=lambda: _make_cm())

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

        _INSTRUMENT_ID = UUID("01900000-0000-7000-8000-000000001001")
        # F-DB-005 (2026-05-28): real ``records[]`` shape, not the flat shape
        # the previous fixture stubbed (which never matched production).
        fundamentals_data = _make_fundamentals_response(
            security_id=str(_INSTRUMENT_ID),
            revenue_ttm=390_000_000_000.0,  # → 390_000 millions
            gross_profit=173_000_000_000.0,  # → ~44.4% gross margin
            net_income=98_700_000_000.0,  # → ~25.3% net margin
            total_revenue=390_000_000_000.0,
            pe_ratio=28.0,
            price=189.0,
            week_52_high=200.0,
            week_52_low=130.0,
        )

        instrument_resp = MagicMock()
        instrument_resp.status_code = 200
        instrument_resp.json = MagicMock(return_value={"id": str(_INSTRUMENT_ID), "symbol": "AAPL"})

        fundamentals_resp = MagicMock()
        fundamentals_resp.status_code = 200
        fundamentals_resp.json = MagicMock(return_value=fundamentals_data)

        def _route_get(url: str, **_kwargs: object) -> object:
            if "/instruments/lookup" in url:
                return instrument_resp
            return fundamentals_resp

        http_client = AsyncMock()
        http_client.get = AsyncMock(side_effect=_route_get)
        http_client.aclose = AsyncMock()

        llm = AsyncMock()
        llm.embed = AsyncMock(
            return_value=[EmbeddingOutput(embedding=[0.1] * 10, model_id="nomic-embed-text", dimension=10)],
        )

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.run(worker.run())

        llm.embed.assert_awaited_once()
        emb_repo.upsert.assert_awaited_once()

    def test_embedding_failure_uses_short_retry_interval(self) -> None:
        """BP-351: when LLM embedding returns None, next_refresh_at must be ≤6h not 30d."""
        from datetime import timedelta

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

        _INSTRUMENT_ID = UUID("01900000-0000-7000-8000-000000001001")
        instrument_resp = MagicMock()
        instrument_resp.status_code = 200
        instrument_resp.json = MagicMock(return_value={"id": str(_INSTRUMENT_ID), "symbol": "AAPL"})

        fundamentals_resp = MagicMock()
        fundamentals_resp.status_code = 200
        # F-DB-005 (2026-05-28): real ``records[]`` shape (was a lying flat
        # ``{revenue_usd_millions, price}`` stub).
        fundamentals_resp.json = MagicMock(
            return_value=_make_fundamentals_response(
                security_id=str(_INSTRUMENT_ID),
                revenue_ttm=390_000_000_000.0,
                price=189.0,
                gross_profit=None,
                net_income=None,
                total_revenue=None,
                pe_ratio=None,
                week_52_high=None,
                week_52_low=None,
            )
        )

        def _route_get(url: str, **_kwargs: object) -> object:
            if "/instruments/lookup" in url:
                return instrument_resp
            return fundamentals_resp

        http_client = AsyncMock()
        http_client.get = AsyncMock(side_effect=_route_get)
        http_client.aclose = AsyncMock()

        # Simulate DeepInfra/LLM transient failure — embed returns empty list
        llm = AsyncMock()
        llm.embed = AsyncMock(return_value=[])

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.run(worker.run())

        emb_repo.upsert.assert_awaited_once()
        call_kwargs = emb_repo.upsert.call_args
        assert call_kwargs is not None

        # Embedding should be None (failed)
        embedding_arg = call_kwargs.args[2] if len(call_kwargs.args) > 2 else call_kwargs.kwargs.get("embedding")
        assert embedding_arg is None, "embedding should be None when LLM fails"

        # next_refresh_at must be ≤ 12h from now (BP-351: 6h, not 30 days)
        import inspect
        from datetime import datetime

        next_at = call_kwargs.kwargs.get("next_refresh_at")
        if next_at is None:
            # Could be positional — check the upsert signature
            for i, param in enumerate(inspect.signature(emb_repo.upsert).parameters):
                if param == "next_refresh_at" and i < len(call_kwargs.args):
                    next_at = call_kwargs.args[i]
                    break

        assert next_at is not None, "next_refresh_at must be set even on embedding failure"
        now_utc = datetime.now(tz=UTC)
        delta = next_at - now_utc
        assert delta < timedelta(hours=12), f"BP-351: embedding failure should retry in <12h, got {delta}"


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
    """Tests for FundamentalsRefreshWorker earnings pipeline (T-C-4-01).

    ARCH-004 refactor: the old _insert_earnings_events was split into:
    - _fetch_earnings_data (HTTP only, Phase 2)
    - _write_earnings_events (DB only, Phase 3)
    Tests call both methods in sequence to verify the same invariants.
    """

    def test_earnings_event_inserted(self) -> None:
        """New earnings record (dedup SELECT returns nothing) → INSERT executed."""
        http = _make_earnings_http()
        session = _make_session_for_earnings(dedup_found=False)
        worker = _make_worker_bare()

        # Phase 2: fetch data (HTTP)
        records = asyncio.run(worker._fetch_earnings_data(http, _ENTITY_ID, "AAPL"))
        assert records is not None

        # Phase 3: write events (DB)
        count = asyncio.run(worker._write_earnings_events(session, _ENTITY_ID, _ENTITY_ID, "Apple Inc.", records))

        assert count == 1
        # First call = dedup SELECT, second call = INSERT
        assert session.execute.call_count == 2

    def test_earnings_event_idempotent(self) -> None:
        """Existing earnings record (dedup SELECT returns row) → INSERT skipped, count=0."""
        http = _make_earnings_http()
        session = _make_session_for_earnings(dedup_found=True)
        worker = _make_worker_bare()

        # Phase 2: fetch data (HTTP)
        records = asyncio.run(worker._fetch_earnings_data(http, _ENTITY_ID, "AAPL"))
        assert records is not None

        # Phase 3: write events (DB)
        count = asyncio.run(worker._write_earnings_events(session, _ENTITY_ID, _ENTITY_ID, "Apple Inc.", records))

        assert count == 0
        # Only the dedup SELECT; no INSERT
        assert session.execute.call_count == 1

    def test_earnings_s3_404_skipped(self) -> None:
        """S3 returns 404 → _fetch_earnings_data returns None, no DB interaction."""
        http = _make_earnings_http(status=404)
        worker = _make_worker_bare()

        records = asyncio.run(worker._fetch_earnings_data(http, _ENTITY_ID, "AAPL"))

        assert records is None


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
                },
            ],
        },
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
        ),
    )
    return relation_repo, evidence_repo, entity_repo


class TestSectorRelationUpsert:
    """Tests for FundamentalsRefreshWorker sector/industry pipeline (T-C-4-02).

    ARCH-004 refactor: the old _upsert_sector_relations was split into:
    - _fetch_company_profile_data (HTTP only, Phase 2)
    - _write_sector_relations (DB only, Phase 3)
    Tests call both methods in sequence to verify the same invariants.
    """

    def test_sector_relation_upserted(self) -> None:
        """Valid sector + industry → relation_repo.upsert and evidence_repo.insert_raw called."""
        http = _make_profile_http()
        relation_repo, evidence_repo, entity_repo = _make_sector_repos()
        worker = _make_worker_bare()

        # Phase 2: fetch profile (HTTP)
        profile_data = asyncio.run(worker._fetch_company_profile_data(http, _ENTITY_ID))
        assert profile_data is not None

        # Phase 3: write relations (DB)
        count = asyncio.run(
            worker._write_sector_relations(
                _ENTITY_ID,
                _ENTITY_ID,
                profile_data,
                relation_repo,
                evidence_repo,
                entity_repo,
            ),
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

        # Phase 2: fetch profile (HTTP) — returns profile even with unknown sector
        profile_data = asyncio.run(worker._fetch_company_profile_data(http, _ENTITY_ID))
        assert profile_data is not None

        # Phase 3: write relations (DB) — entity lookup returns None for both
        count = asyncio.run(
            worker._write_sector_relations(
                _ENTITY_ID,
                _ENTITY_ID,
                profile_data,
                relation_repo,
                evidence_repo,
                entity_repo,
            ),
        )

        assert count == 0
        relation_repo.upsert.assert_not_awaited()
        evidence_repo.insert_raw.assert_not_awaited()

    def test_sector_relation_idempotent(self) -> None:
        """Second run with same sector → relation_repo.upsert called again (advisory lock upsert)."""
        http = _make_profile_http()
        relation_repo, evidence_repo, entity_repo = _make_sector_repos()
        worker = _make_worker_bare()

        # Run Phase 2 + Phase 3 twice
        profile_data = asyncio.run(worker._fetch_company_profile_data(http, _ENTITY_ID))
        asyncio.run(
            worker._write_sector_relations(
                _ENTITY_ID,
                _ENTITY_ID,
                profile_data,
                relation_repo,
                evidence_repo,
                entity_repo,
            ),
        )
        profile_data = asyncio.run(worker._fetch_company_profile_data(http, _ENTITY_ID))
        asyncio.run(
            worker._write_sector_relations(
                _ENTITY_ID,
                _ENTITY_ID,
                profile_data,
                relation_repo,
                evidence_repo,
                entity_repo,
            ),
        )

        # Advisory-lock upsert is called on every run (idempotency handled at DB level)
        assert relation_repo.upsert.await_count == 4  # 2 relations x 2 runs


# ── Batch embed tests (perf-fix) ─────────────────────────────────────────────

_ENTITY_ID_A = UUID("00000000-0000-0000-0000-000000000010")
_ENTITY_ID_B = UUID("00000000-0000-0000-0000-000000000011")
_ENTITY_ID_C = UUID("00000000-0000-0000-0000-000000000012")


def _make_multi_entity_http(instrument_id: UUID) -> AsyncMock:
    """HTTP client that successfully routes instrument-symbol lookups and fundamentals."""
    instrument_resp = MagicMock()
    instrument_resp.status_code = 200
    instrument_resp.json = MagicMock(return_value={"id": str(instrument_id), "symbol": "TEST"})

    fundamentals_resp = MagicMock()
    fundamentals_resp.status_code = 200
    # F-DB-005 (2026-05-28): real ``records[]`` shape (was a lying flat stub).
    fundamentals_resp.json = MagicMock(
        return_value=_make_fundamentals_response(
            security_id=str(instrument_id),
            revenue_ttm=100_000_000.0,  # → 100 millions (small-cap)
            price=50.0,
            gross_profit=None,
            net_income=None,
            total_revenue=None,
            pe_ratio=None,
            week_52_high=None,
            week_52_low=None,
        )
    )

    # 404 for earnings and profile so those paths complete quickly
    not_found_resp = MagicMock()
    not_found_resp.status_code = 404

    def _route(url: str, **_kwargs: object) -> object:
        if "/instruments/lookup" in url:
            return instrument_resp
        if "/earnings" in url or "/company-profile" in url:
            return not_found_resp
        return fundamentals_resp

    http = AsyncMock()
    http.get = AsyncMock(side_effect=_route)
    http.aclose = AsyncMock()
    return http


def _make_session_factory_multi(due_rows: list) -> tuple:
    """Session factory for multi-entity tests."""
    session = AsyncMock()
    session.commit = AsyncMock()

    def _make_cm() -> AsyncMock:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    sf = MagicMock(side_effect=lambda: _make_cm())

    emb_repo = AsyncMock()
    emb_repo.get_due_for_refresh = AsyncMock(return_value=due_rows)
    emb_repo.upsert = AsyncMock()

    return sf, emb_repo


class TestBatchEmbedding:
    """Verify that the batch-embed refactor sends all inputs in a single embed() call."""

    def test_multiple_entities_embed_called_once_with_all_inputs(self) -> None:
        """3 entities → embed() called exactly once with 3 inputs (not 3 separate calls)."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker
        from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-untyped]

        _INSTRUMENT_ID = UUID("01900000-0000-7000-8000-000000002001")
        due_rows = [
            {
                "entity_id": eid,
                "ticker": f"TKR{i}",
                "canonical_name": f"Company {i}",
                "entity_type": "financial_instrument",
            }
            for i, eid in enumerate([_ENTITY_ID_A, _ENTITY_ID_B, _ENTITY_ID_C])
        ]

        sf, emb_repo = _make_session_factory_multi(due_rows)
        http = _make_multi_entity_http(_INSTRUMENT_ID)

        llm = AsyncMock()
        # Return 3 outputs for the 3 narratives.
        llm.embed = AsyncMock(
            return_value=[
                EmbeddingOutput(embedding=[0.1] * 10, model_id="nomic-embed-text", dimension=10) for _ in range(3)
            ],
        )

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http)
            asyncio.run(worker.run())

        # embed() must be called once with all 3 narratives.
        llm.embed.assert_awaited_once()
        inputs = llm.embed.call_args.args[0]
        assert len(inputs) == 3, f"Expected 3 embed inputs, got {len(inputs)}"

        # upsert called once per entity that has a narrative.
        assert emb_repo.upsert.await_count == 3

    def test_entities_processed_concurrently(self) -> None:
        """3 entities: asyncio.gather path ensures embed receives 3 inputs in one call."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker
        from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-untyped]

        _INSTRUMENT_ID = UUID("01900000-0000-7000-8000-000000002002")
        due_rows = [
            {
                "entity_id": eid,
                "ticker": f"SYM{i}",
                "canonical_name": f"Corp {i}",
                "entity_type": "financial_instrument",
            }
            for i, eid in enumerate([_ENTITY_ID_A, _ENTITY_ID_B, _ENTITY_ID_C])
        ]

        sf, emb_repo = _make_session_factory_multi(due_rows)
        http = _make_multi_entity_http(_INSTRUMENT_ID)

        embed_call_count = 0

        async def _tracking_embed(inputs: list, **_kwargs: object) -> list:
            nonlocal embed_call_count
            embed_call_count += 1
            return [EmbeddingOutput(embedding=[0.2] * 10, model_id="nomic-embed-text", dimension=10) for _ in inputs]

        llm = AsyncMock()
        llm.embed = _tracking_embed

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(
                sf,
                llm,
                "http://market-data:8003",
                http_client=http,
                concurrency=3,  # allow all 3 entities to run concurrently
            )
            asyncio.run(worker.run())

        # Batch embed means exactly 1 embed call for all 3 entities.
        assert embed_call_count == 1, f"Expected 1 embed call, got {embed_call_count}"
        # All 3 entities have narratives → 3 upserts.
        assert emb_repo.upsert.await_count == 3


# ── PLAN-0093 D-2 (T-D-2-01) — per-ticker exponential backoff tests ──────────


class TestFundamentalsRefreshBackoff:
    """Unit tests for the per-ticker Valkey backoff schedule (T-D-2-01).

    These exercise the pure ``_next_backoff_seconds`` helper plus the
    instance methods that read/write the Valkey key.  No DB session is
    actually opened (the helpers are isolated from the run() pipeline).
    """

    def test_first_404_backs_off_1h(self) -> None:
        """No prior backoff → escalate to 3600 s (1h)."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import (
            _BACKOFF_STAGE_1H_S,
            FundamentalsRefreshWorker,
        )

        valkey = AsyncMock()
        valkey.get = AsyncMock(return_value=None)  # no prior key
        valkey.set = AsyncMock()
        valkey.delete = AsyncMock()

        sf, _emb_repo = _make_session_factory([])
        llm = AsyncMock()
        worker = FundamentalsRefreshWorker(
            sf,
            llm,
            "http://market-data:8003",
            valkey_client=valkey,
        )

        new_s = asyncio.run(worker._escalate_backoff("AAPL"))
        assert new_s == _BACKOFF_STAGE_1H_S
        # SET key with TTL == 3600 s.
        valkey.set.assert_awaited_once()
        call_args = valkey.set.await_args
        assert call_args.args[0] == "s7:fundamentals:backoff:aapl"
        assert call_args.args[1] == str(_BACKOFF_STAGE_1H_S)
        assert call_args.kwargs.get("ex") == _BACKOFF_STAGE_1H_S

    def test_consecutive_errors_escalate_to_7d(self) -> None:
        """3rd consecutive error → 7d backoff (604800 s)."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import (
            _BACKOFF_STAGE_1D_S,
            _BACKOFF_STAGE_1H_S,
            _BACKOFF_STAGE_7D_S,
            FundamentalsRefreshWorker,
            _next_backoff_seconds,
        )

        # Verify the pure escalation table.
        assert _next_backoff_seconds(None) == _BACKOFF_STAGE_1H_S
        assert _next_backoff_seconds(_BACKOFF_STAGE_1H_S) == _BACKOFF_STAGE_1D_S
        assert _next_backoff_seconds(_BACKOFF_STAGE_1D_S) == _BACKOFF_STAGE_7D_S
        # Terminal stage stays at 7d (we never escalate past 7d).
        assert _next_backoff_seconds(_BACKOFF_STAGE_7D_S) == _BACKOFF_STAGE_7D_S

        # End-to-end: starting from "currently at 1d" → escalate sets 7d.
        valkey = AsyncMock()
        valkey.get = AsyncMock(return_value=str(_BACKOFF_STAGE_1D_S))
        valkey.set = AsyncMock()

        sf, _emb_repo = _make_session_factory([])
        llm = AsyncMock()
        worker = FundamentalsRefreshWorker(
            sf,
            llm,
            "http://market-data:8003",
            valkey_client=valkey,
        )

        new_s = asyncio.run(worker._escalate_backoff("BADTICK"))
        assert new_s == _BACKOFF_STAGE_7D_S
        valkey.set.assert_awaited_once()
        assert valkey.set.await_args.kwargs.get("ex") == _BACKOFF_STAGE_7D_S

    def test_success_resets_backoff(self) -> None:
        """A successful HTTP fetch → DELETE the backoff key."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        valkey = AsyncMock()
        valkey.delete = AsyncMock()

        sf, _emb_repo = _make_session_factory([])
        llm = AsyncMock()
        worker = FundamentalsRefreshWorker(
            sf,
            llm,
            "http://market-data:8003",
            valkey_client=valkey,
        )
        asyncio.run(worker._reset_backoff("AAPL"))
        valkey.delete.assert_awaited_once_with("s7:fundamentals:backoff:aapl")


# ── PLAN-0093 D-2 (T-D-2-02) — HTTP status-code logging tests ───────────────


class TestFundamentalsRefreshStatusLogging:
    """Verify _fetch_json logs status code + ticker + latency on every call."""

    def test_5xx_logs_at_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """503 response → ERROR log with structured fields.

        structlog routes output to stdout in the dev formatter, so we
        capture via ``capsys`` instead of ``caplog`` (which only sees
        stdlib-logger records).
        """
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.content = b""
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_response)

        result = asyncio.run(
            FundamentalsRefreshWorker._fetch_json(
                http,
                "http://market-data:8003/api/v1/fundamentals/abc",
                ticker="AAPL",
            ),
        )
        assert result is None
        captured = capsys.readouterr()
        # All four assertions must hold to prove the log record is well-formed.
        combined = captured.out + captured.err
        assert "market_data_call_server_error" in combined
        assert "status_code=503" in combined
        assert "ticker=AAPL" in combined
        assert "latency_ms=" in combined


class TestFundamentalsRefreshFailureObservability:
    """FIX-LIVE-G (2026-05-24) regression tests.

    INV-LIVE-E mis-diagnosed a 100% ``fundamentals_refresh_market_data_unavailable``
    failure rate as a JWT/auth issue. The real cause was 99% missing
    instruments in market-data (data-availability gap). The generic warning
    hid the actual failure category — making the next investigator chase the
    wrong hypothesis. These tests pin the observability contract: when a
    market-data call fails, the structured event must carry a precise
    ``failure_reason`` that distinguishes ``instrument_lookup_failed`` (data
    gap) from ``fundamentals_http_404`` (instrument exists but no fundamentals
    ingested) from ``fundamentals_http_401`` (auth — the hypothesis INV-LIVE-E
    chased) from ``fundamentals_transport_error`` (network).
    """

    def test_instrument_lookup_404_emits_failure_reason(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Lookup 404 → unavailable warning carries ``failure_reason='instrument_lookup_failed'``."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": "OBSCURE",
                "canonical_name": "Obscure Ltd",
                "entity_type": "financial_instrument",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        lookup_404 = MagicMock()
        lookup_404.status_code = 404
        lookup_404.content = b'{"detail": "not found"}'
        lookup_404.json = MagicMock(return_value={"detail": "not found"})

        http_client = AsyncMock()
        http_client.get = AsyncMock(return_value=lookup_404)
        http_client.aclose = AsyncMock()

        llm = AsyncMock()

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.run(worker.run())

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        # Both the precise reason and the aggregate breakdown must surface.
        assert "fundamentals_refresh_market_data_unavailable" in combined
        assert "failure_reason=instrument_lookup_failed" in combined
        # worker_complete summary must include the aggregate counter.
        assert "fundamentals_refresh_worker_complete" in combined
        assert "instrument_lookup_failed" in combined.split("worker_complete", 1)[1]

    def test_fundamentals_http_404_emits_failure_reason_with_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Fundamentals 404 → ``failure_reason='fundamentals_http_404'`` (distinct from lookup miss)."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": "NEWLIST",
                "canonical_name": "Newly Listed Co",
                "entity_type": "financial_instrument",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        _INSTRUMENT_ID = UUID("01900000-0000-7000-8000-000000099999")

        # Lookup succeeds — the instrument IS in market-data.
        lookup_ok = MagicMock()
        lookup_ok.status_code = 200
        lookup_ok.content = b'{"id": "..."}'
        lookup_ok.json = MagicMock(return_value={"id": str(_INSTRUMENT_ID), "symbol": "NEWLIST"})

        # All fundamentals/earnings/profile calls return 404 — newly-listed
        # instrument with no derived data ingested yet.
        not_found = MagicMock()
        not_found.status_code = 404
        not_found.content = b'{"detail": "no data"}'
        not_found.json = MagicMock(return_value={"detail": "no data"})

        def _route(url: str, **_kwargs: object) -> object:
            if "/instruments/lookup" in url:
                return lookup_ok
            return not_found

        http_client = AsyncMock()
        http_client.get = AsyncMock(side_effect=_route)
        http_client.aclose = AsyncMock()

        llm = AsyncMock()

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.run(worker.run())

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "fundamentals_refresh_market_data_unavailable" in combined
        assert "failure_reason=fundamentals_http_404" in combined

    def test_fundamentals_http_401_emits_failure_reason_with_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Auth failure (401) → distinct ``failure_reason='fundamentals_http_401'``.

        This is exactly the failure mode INV-LIVE-E *hypothesised*. The test
        pins that if auth ever really does break, the log will say so
        explicitly rather than the generic message that started this whole
        investigation. Future investigators will not have to guess.
        """
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

        _INSTRUMENT_ID = UUID("01900000-0000-7000-8000-000000001001")
        lookup_ok = MagicMock()
        lookup_ok.status_code = 200
        lookup_ok.content = b'{"id": "..."}'
        lookup_ok.json = MagicMock(return_value={"id": str(_INSTRUMENT_ID), "symbol": "AAPL"})

        unauthorized = MagicMock()
        unauthorized.status_code = 401
        unauthorized.content = b'{"detail": "invalid JWT"}'
        unauthorized.json = MagicMock(return_value={"detail": "invalid JWT"})

        def _route(url: str, **_kwargs: object) -> object:
            if "/instruments/lookup" in url:
                return lookup_ok
            return unauthorized

        http_client = AsyncMock()
        http_client.get = AsyncMock(side_effect=_route)
        http_client.aclose = AsyncMock()

        llm = AsyncMock()

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.run(worker.run())

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "fundamentals_refresh_market_data_unavailable" in combined
        assert "failure_reason=fundamentals_http_401" in combined
        # The dedicated per-call HTTP log must also surface the 401 status,
        # so an investigator can immediately see "the request was rejected"
        # without inferring it from the worker's summary.
        assert "market_data_call_client_error" in combined
        assert "status_code=401" in combined
