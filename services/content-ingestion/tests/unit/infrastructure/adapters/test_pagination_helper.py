"""Unit tests for the shared offset-pagination termination helper.

Exhaustive, single-location coverage for
``content_ingestion.infrastructure.adapters._pagination.next_offset_cursor`` so
individual client tests (Gamma markets/events, Polymarket trades) don't need
to re-duplicate these same three cases per file.

See ``docs/audits/2026-07-23-bottleneck-content-ingestion-pagination.md`` for
why this invariant needs to be centralized: the "short page == last page"
heuristic this helper replaces was independently disproven twice for the
Gamma clients before this module existed.
"""

from __future__ import annotations

import pytest
from content_ingestion.infrastructure.adapters._pagination import next_offset_cursor

pytestmark = pytest.mark.unit


class TestNextOffsetCursor:
    def test_empty_page_terminates(self) -> None:
        """A returned_count of 0 (empty page) is the ONLY termination signal."""
        assert next_offset_cursor(offset=0, returned_count=0) is None
        assert next_offset_cursor(offset=1000, returned_count=0) is None

    def test_short_nonempty_page_advances_not_terminates(self) -> None:
        """A page shorter than the requested limit must still advance.

        This is the exact invariant that was disproven twice for the Gamma
        clients: a server-side page-size cap makes a "short" page the norm,
        not a signal of end-of-data.
        """
        # e.g. requested limit=500, provider capped the page at 100 rows.
        assert next_offset_cursor(offset=0, returned_count=100) == "100"
        assert next_offset_cursor(offset=1000, returned_count=50) == "1050"

    def test_exactly_at_limit_page_advances(self) -> None:
        """A full page (returned_count == limit) also advances by the actual count."""
        assert next_offset_cursor(offset=0, returned_count=500) == "500"
        assert next_offset_cursor(offset=500, returned_count=500) == "1000"

    def test_over_limit_defensive(self) -> None:
        """Even a (should-never-happen) over-limit page advances by the actual
        count -- the helper never clamps to the requested limit, it always
        trusts the provider's actual returned count."""
        assert next_offset_cursor(offset=0, returned_count=600) == "600"

    def test_negative_returned_count_defensive(self) -> None:
        """A defensive negative returned_count (should never occur for a real
        provider response) is treated as empty, never propagating a negative
        offset."""
        assert next_offset_cursor(offset=100, returned_count=-1) is None
