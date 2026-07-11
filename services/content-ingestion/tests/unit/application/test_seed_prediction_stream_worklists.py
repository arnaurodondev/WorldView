"""Unit tests for SeedPredictionStreamWorklistsUseCase (PLAN-0056 live-QA BUG 2).

Covers:
- ``build_market_worklist`` derives the correct ``{condition_id, token_ids}`` list.
- Only OPEN markets are included (resolved / cancelled skipped).
- The cap (``max_markets``) is enforced.
- Duplicate condition_ids are collapsed.
- ``execute`` writes the work-list to the CLOB + trades ``config["markets"]`` and
  the OI ``config["condition_ids"]``.
- Idempotent: a second run with the same universe performs NO writes / no commit.
- Empty/all-resolved batch leaves configs untouched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from content_ingestion.application.use_cases.seed_prediction_stream_worklists import (
    SeedPredictionStreamWorklistsUseCase,
    build_market_worklist,
)
from content_ingestion.domain.entities import OutcomeSnapshot, PredictionMarketFetchResult, SourceType

pytestmark = pytest.mark.unit

_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)


def _make_result(
    market_id: str,
    *,
    resolution_status: str = "open",
    token_ids: tuple[str, str] = ("tok_yes", "tok_no"),
) -> PredictionMarketFetchResult:
    return PredictionMarketFetchResult(
        source_type=SourceType.POLYMARKET,
        market_id=market_id,
        question="Will X happen?",
        outcomes=[
            OutcomeSnapshot(name="Yes", token_id=token_ids[0], price=0.6),
            OutcomeSnapshot(name="No", token_id=token_ids[1], price=0.4),
        ],
        raw_bytes=json.dumps({"conditionId": market_id}).encode(),
        fetched_at=_FETCHED_AT,
        resolution_status=resolution_status,
    )


class _FakeSourceRow:
    """Minimal stand-in for SourceModel (has id, source_type, config)."""

    _seq = 0

    def __init__(self, source_type: str, config: dict[str, Any]) -> None:
        # Distinct id per row so the fake repo's update() targets exactly one row.
        _FakeSourceRow._seq += 1
        self.id = UUID(int=_FakeSourceRow._seq)
        self.source_type = source_type
        self.config = config


class _FakeSourceRepo:
    """Records update() calls; get_all() returns the seeded rows."""

    def __init__(self, rows: list[_FakeSourceRow]) -> None:
        self._rows = rows
        self.updates: list[tuple[UUID, dict[str, Any]]] = []

    async def get_all(self) -> list[_FakeSourceRow]:
        return self._rows

    async def update(self, source_id: UUID, **kwargs: Any) -> _FakeSourceRow:
        self.updates.append((source_id, kwargs))
        # Reflect the write onto the in-memory row so an idempotent re-run sees it.
        for row in self._rows:
            if row.id == source_id:
                row.config = kwargs["config"]
        return self._rows[0]


def _seeded_rows() -> list[_FakeSourceRow]:
    return [
        _FakeSourceRow("polymarket_clob", {"markets": []}),
        _FakeSourceRow("polymarket_data_trades", {"markets": []}),
        _FakeSourceRow("polymarket_data_oi", {"condition_ids": []}),
    ]


class TestBuildMarketWorklist:
    def test_maps_condition_id_and_token_ids(self) -> None:
        results = [_make_result("0xcond1", token_ids=("t1", "t2"))]
        worklist = build_market_worklist(results)
        assert worklist == [{"condition_id": "0xcond1", "token_ids": ["t1", "t2"]}]

    def test_only_open_markets(self) -> None:
        results = [
            _make_result("0xopen", resolution_status="open"),
            _make_result("0xresolved", resolution_status="resolved"),
            _make_result("0xcancelled", resolution_status="cancelled"),
        ]
        worklist = build_market_worklist(results)
        assert [m["condition_id"] for m in worklist] == ["0xopen"]

    def test_cap_enforced(self) -> None:
        results = [_make_result(f"0xc{i}") for i in range(10)]
        worklist = build_market_worklist(results, max_markets=3)
        assert len(worklist) == 3
        assert [m["condition_id"] for m in worklist] == ["0xc0", "0xc1", "0xc2"]

    def test_duplicate_condition_ids_collapsed(self) -> None:
        results = [_make_result("0xdup"), _make_result("0xdup"), _make_result("0xother")]
        worklist = build_market_worklist(results)
        assert [m["condition_id"] for m in worklist] == ["0xdup", "0xother"]

    def test_blank_condition_id_skipped(self) -> None:
        # market_id="" would fail entity invariants elsewhere, but guard here anyway.
        results = [_make_result("   "), _make_result("0xreal")]
        worklist = build_market_worklist(results)
        assert [m["condition_id"] for m in worklist] == ["0xreal"]


class TestSeedExecute:
    def test_writes_all_three_configs(self) -> None:
        import asyncio

        rows = _seeded_rows()
        repo = _FakeSourceRepo(rows)
        commit = AsyncMock()
        use_case = SeedPredictionStreamWorklistsUseCase(repo, commit, max_markets=500)

        results = [_make_result("0xc1", token_ids=("t1", "t2")), _make_result("0xc2", token_ids=("t3", "t4"))]
        summary = asyncio.run(use_case.execute(results))

        assert summary.markets == 2
        assert summary.clob_updated and summary.trades_updated and summary.oi_updated
        commit.assert_awaited_once()

        # CLOB + trades carry the full {condition_id, token_ids} work-list.
        expected_markets = [
            {"condition_id": "0xc1", "token_ids": ["t1", "t2"]},
            {"condition_id": "0xc2", "token_ids": ["t3", "t4"]},
        ]
        assert rows[0].config["markets"] == expected_markets
        assert rows[1].config["markets"] == expected_markets
        # OI carries only the flat condition_id list.
        assert rows[2].config["condition_ids"] == ["0xc1", "0xc2"]

    def test_idempotent_second_run_no_writes(self) -> None:
        import asyncio

        rows = _seeded_rows()
        repo = _FakeSourceRepo(rows)
        commit = AsyncMock()
        use_case = SeedPredictionStreamWorklistsUseCase(repo, commit)

        results = [_make_result("0xc1")]
        asyncio.run(use_case.execute(results))
        first_update_count = len(repo.updates)
        assert first_update_count == 3
        assert commit.await_count == 1

        # Second run with the identical universe: configs already match → no writes.
        summary2 = asyncio.run(use_case.execute(results))
        assert not (summary2.clob_updated or summary2.trades_updated or summary2.oi_updated)
        assert len(repo.updates) == first_update_count  # no new update() calls
        assert commit.await_count == 1  # no second commit

    def test_empty_batch_no_writes(self) -> None:
        import asyncio

        rows = _seeded_rows()
        repo = _FakeSourceRepo(rows)
        commit = AsyncMock()
        use_case = SeedPredictionStreamWorklistsUseCase(repo, commit)

        summary = asyncio.run(use_case.execute([_make_result("0xr", resolution_status="resolved")]))
        assert summary.markets == 0
        assert repo.updates == []
        commit.assert_not_awaited()

    def test_preserves_other_config_keys(self) -> None:
        import asyncio

        rows = [
            _FakeSourceRow("polymarket_clob", {"markets": [], "note": "keep-me"}),
            _FakeSourceRow("polymarket_data_trades", {"markets": []}),
            _FakeSourceRow("polymarket_data_oi", {"condition_ids": [], "extra": 1}),
        ]
        repo = _FakeSourceRepo(rows)
        use_case = SeedPredictionStreamWorklistsUseCase(repo, AsyncMock())
        asyncio.run(use_case.execute([_make_result("0xc1")]))

        assert rows[0].config["note"] == "keep-me"
        assert rows[2].config["extra"] == 1
