"""Unit tests for the entity_embedding_state startup repair (PLAN-0057 Wave E-5).

Refactored 2026-05-01 (QA M-2): repair now uses a single GROUP BY gap-detection
query instead of N per-row counts, so the test fakes return rows directly from
the gap query without simulating ``count_for_entity``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_session_factory(rows_pages: list[list[tuple[str, str]]]):
    """Build a fake async sessionmaker driven by a sequence of gap-query result pages."""
    page_iter = iter(rows_pages)
    inserts: list[tuple[str, str]] = []

    @asynccontextmanager
    async def _ctx():
        session = AsyncMock()

        async def _execute(query, params=None):
            text_q = str(query)
            if text_q.lstrip().upper().startswith("INSERT INTO ENTITY_EMBEDDING_STATE"):
                inserts.append((str(params["entity_id"]), params["view_type"]))
                return MagicMock()
            # The repair gap-detection SELECT.
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
        """Non-company canonical surfaces from the gap query → ensure_rows_exist runs."""
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        # The gap query returns 1 currency row; ensure_rows_exist is invoked.
        rows = [[("c0001-currency-usd", "currency")], []]
        factory = _make_session_factory(rows)

        stats = asyncio.run(repair_missing_embedding_state(factory))
        assert stats == {"checked": 1, "inserted": 2}

        view_types_inserted = {vt for _eid, vt in factory.inserts}
        assert view_types_inserted == {"definition", "narrative"}

    def test_inserts_three_rows_for_financial_instrument(self) -> None:
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        rows = [[("inst-aapl", "financial_instrument")], []]
        factory = _make_session_factory(rows)

        stats = asyncio.run(repair_missing_embedding_state(factory))
        assert stats == {"checked": 1, "inserted": 3}
        view_types = {vt for _eid, vt in factory.inserts}
        assert view_types == {"definition", "narrative", "fundamentals_ohlcv"}

    def test_skips_when_no_gaps(self) -> None:
        """Empty gap-query result → no inserts, no checks counted."""
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        # First page is empty → repair exits cleanly without a second page query.
        factory = _make_session_factory([[]])

        stats = asyncio.run(repair_missing_embedding_state(factory))
        assert stats == {"checked": 0, "inserted": 0}
        assert factory.inserts == []

    def test_idempotent_across_runs(self) -> None:
        """Re-running with no gaps returns 0/0 (every canonical already has its rows)."""
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        factory_first = _make_session_factory([[("inst-msft", "financial_instrument")], []])
        factory_second = _make_session_factory([[]])

        first = asyncio.run(repair_missing_embedding_state(factory_first))
        second = asyncio.run(repair_missing_embedding_state(factory_second))
        assert first["inserted"] == 3
        assert second["inserted"] == 0

    def test_pagination_terminates(self) -> None:
        """A partial page must end the loop — no infinite scan even if the gap query
        keeps returning rows.  When fewer than _PAGE_SIZE rows come back, exit."""
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        rows = [
            [("c001", "currency"), ("c002", "currency")],  # partial page → exits after
        ]
        factory = _make_session_factory(rows)

        stats = asyncio.run(repair_missing_embedding_state(factory))
        assert stats["checked"] == 2
        assert stats["inserted"] == 4

    def test_advances_through_multiple_full_pages(self) -> None:
        """PLAN-0057 QA DS-002 regression: the previous OFFSET-based pagination
        skipped ~50% of canonicals when the gap-set exceeded a single page,
        because INSERTs from page 1 shifted the gap-set under page 2's OFFSET
        cursor.  This test simulates a 1001-canonical gap-set delivered in
        three pages (500 + 500 + 1) and asserts every row is processed.
        """
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            _PAGE_SIZE,
            repair_missing_embedding_state,
        )

        page1 = [(f"c{i:04d}", "currency") for i in range(_PAGE_SIZE)]
        page2 = [(f"c{i:04d}", "currency") for i in range(_PAGE_SIZE, _PAGE_SIZE * 2)]
        page3 = [(f"c{_PAGE_SIZE * 2:04d}", "currency")]
        # Empty page after page3 short-circuits the iteration cap.
        rows = [page1, page2, page3, []]
        factory = _make_session_factory(rows)

        stats = asyncio.run(repair_missing_embedding_state(factory))
        assert stats["checked"] == _PAGE_SIZE * 2 + 1, (
            f"expected {_PAGE_SIZE * 2 + 1} canonicals processed, got {stats['checked']}"
        )
        assert stats["inserted"] == (_PAGE_SIZE * 2 + 1) * 2  # 2 view types per non-instrument

    def test_iteration_cap_protects_against_runaway_loop(self) -> None:
        """If ensure_rows_exist were silently failing (e.g. constraint violation
        rolled back) the gap-set would never shrink and the loop would spin.
        The iteration cap (100) bounds the worst case.  Simulated by always
        returning a full page.
        """
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            _PAGE_SIZE,
            repair_missing_embedding_state,
        )

        infinite_page = [(f"c{i:04d}", "currency") for i in range(_PAGE_SIZE)]
        # Iterator yields the same full page forever — repair must terminate
        # within the iteration cap rather than hang the test.
        from itertools import repeat as _repeat

        page_iter = _repeat(infinite_page)
        inserts: list[tuple[str, str]] = []

        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, MagicMock

        @asynccontextmanager
        async def _ctx():
            session = AsyncMock()

            async def _execute(query, params=None):
                text_q = str(query)
                if text_q.lstrip().upper().startswith("INSERT INTO ENTITY_EMBEDDING_STATE"):
                    inserts.append((str(params["entity_id"]), params["view_type"]))
                    return MagicMock()
                res = MagicMock()
                res.fetchall.return_value = next(page_iter)
                return res

            session.execute = _execute
            session.commit = AsyncMock()
            yield session

        factory = MagicMock(side_effect=_ctx)

        stats = asyncio.run(repair_missing_embedding_state(factory))
        # The cap is 100 iterations x _PAGE_SIZE rows per iteration.
        assert stats["checked"] == 100 * _PAGE_SIZE
