"""Regression tests for OHLCV bulk-upsert parameter chunking.

Guards against the combined-upsert wire-param overflow that crash-looped the
``market-data-ohlcv-consumer``: a 5_000-row x 12-col chunk = 60_000 bound
parameters, which exceeds asyncpg's hard ceiling of 32_767 and raises
``InterfaceError: the number of query arguments cannot exceed 32767``.
"""

from __future__ import annotations

import pytest
from market_data.infrastructure.db.repositories.ohlcv_repo import (
    _MAX_PARAMS,
    _UPSERT_CHUNK_ROWS,
    _chunk_rows,
)

# The widest VALUES row in this repo (the derived-bar upsert path).
_WIDEST_VALUES_COLUMNS = 13

# asyncpg encodes the bound-parameter count as a signed int16, so the real
# ceiling is 32_767 (NOT the wire protocol's uint16 65_535).
_ASYNCPG_PARAM_LIMIT = 32_767


@pytest.mark.unit
class TestUpsertChunking:
    def test_max_params_within_asyncpg_limit(self) -> None:
        assert _MAX_PARAMS <= _ASYNCPG_PARAM_LIMIT

    def test_chunk_size_keeps_widest_row_under_limit(self) -> None:
        # The defining invariant: a full chunk of the widest VALUES row must not
        # exceed the asyncpg parameter ceiling.
        assert _UPSERT_CHUNK_ROWS * _WIDEST_VALUES_COLUMNS <= _ASYNCPG_PARAM_LIMIT

    def test_regression_5000x12_would_have_overflowed(self) -> None:
        # The exact failing shape from the incident must now be impossible: the
        # chunk size is strictly smaller than the 5_000 that produced 60_000 params.
        assert _UPSERT_CHUNK_ROWS < 5_000
        assert 5_000 * 12 > _ASYNCPG_PARAM_LIMIT  # documents why 5_000 failed

    def test_chunk_rows_splits_large_input(self) -> None:
        rows = [{"i": i} for i in range(_UPSERT_CHUNK_ROWS * 2 + 7)]
        chunks = list(_chunk_rows(rows))
        # Every chunk stays within the row budget...
        assert all(len(c) <= _UPSERT_CHUNK_ROWS for c in chunks)
        # ...and chunking is lossless and order-preserving.
        assert sum(len(c) for c in chunks) == len(rows)
        assert [r for c in chunks for r in c] == rows

    def test_chunk_rows_empty_yields_nothing(self) -> None:
        assert list(_chunk_rows([])) == []
