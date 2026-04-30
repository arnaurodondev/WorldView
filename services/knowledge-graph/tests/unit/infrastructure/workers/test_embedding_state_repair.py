"""Unit tests for the entity_embedding_state startup repair (PLAN-0057 Wave E-5)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_session_factory(rows_pages: list[list[tuple[str, str]]], counts: dict[str, int]):
    """Build a fake async sessionmaker.

    rows_pages: keyset-paginated batches; first call returns page 0, then page 1, …
    counts:     entity_id → current row count (drives whether ensure_rows_exist is invoked).
    """
    page_iter = iter(rows_pages)
    inserts: list[tuple[str, str]] = []

    @asynccontextmanager
    async def _ctx():
        session = AsyncMock()

        async def _execute(query, params=None):
            text_q = str(query)
            # Repository.count_for_entity uses SELECT COUNT(*).
            if "COUNT(*)" in text_q:
                eid = str(params["entity_id"])
                res = MagicMock()
                res.fetchone.return_value = (counts.get(eid, 0),)
                return res
            # Repository.ensure_rows_exist issues an INSERT per view type.
            if text_q.lstrip().upper().startswith("INSERT INTO ENTITY_EMBEDDING_STATE"):
                inserts.append((str(params["entity_id"]), params["view_type"]))
                return MagicMock()
            # The repair scan SELECT.
            res = MagicMock()
            res.fetchall.return_value = next(page_iter, [])
            return res

        session.execute = _execute
        session.commit = AsyncMock()
        yield session

    factory = MagicMock(side_effect=_ctx)
    factory.inserts = inserts
    return factory


class TestRepairMissingEmbeddingState:
    def test_inserts_missing_rows_for_non_company(self) -> None:
        """Non-company canonical with 0 rows should get definition+narrative inserted."""
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        # 1 currency canonical with 0 existing rows → expects 2 inserts.
        rows = [[("c0001-currency-usd", "currency")]]
        factory = _make_session_factory(rows, counts={"c0001-currency-usd": 0})

        stats = asyncio.run(repair_missing_embedding_state(factory))
        assert stats == {"checked": 1, "inserted": 2}

        view_types_inserted = {vt for _eid, vt in factory.inserts}
        assert view_types_inserted == {"definition", "narrative"}

    def test_inserts_three_rows_for_financial_instrument(self) -> None:
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        rows = [[("inst-aapl", "financial_instrument")]]
        factory = _make_session_factory(rows, counts={"inst-aapl": 0})

        stats = asyncio.run(repair_missing_embedding_state(factory))
        assert stats == {"checked": 1, "inserted": 3}
        view_types = {vt for _eid, vt in factory.inserts}
        assert view_types == {"definition", "narrative", "fundamentals_ohlcv"}

    def test_skips_when_rows_already_present(self) -> None:
        """A canonical with the expected number of rows should not re-insert."""
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        rows = [[("c0002-regulator-sec", "regulatory_body")]]
        factory = _make_session_factory(rows, counts={"c0002-regulator-sec": 2})

        stats = asyncio.run(repair_missing_embedding_state(factory))
        assert stats == {"checked": 1, "inserted": 0}
        assert factory.inserts == []

    def test_idempotent_across_runs(self) -> None:
        """Re-running with no missing rows reports 0 inserts (ON CONFLICT semantics)."""
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        rows = [[("inst-msft", "financial_instrument")]]
        # First pass: 0 → 3; second pass: 3 → no-op.
        factory1 = _make_session_factory(rows, counts={"inst-msft": 0})
        factory2 = _make_session_factory(rows, counts={"inst-msft": 3})

        first = asyncio.run(repair_missing_embedding_state(factory1))
        second = asyncio.run(repair_missing_embedding_state(factory2))
        assert first["inserted"] == 3
        assert second["inserted"] == 0

    def test_pagination_terminates(self) -> None:
        """Empty page after a partial page must end the loop without infinite scan."""
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        rows = [
            [("c001", "currency"), ("c002", "currency")],  # partial page
            [],
        ]
        factory = _make_session_factory(rows, counts={"c001": 0, "c002": 2})

        stats = asyncio.run(repair_missing_embedding_state(factory))
        assert stats["checked"] == 2
        assert stats["inserted"] == 2
