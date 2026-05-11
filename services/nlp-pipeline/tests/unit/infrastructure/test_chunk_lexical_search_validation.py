"""Unit-level argument validation for ``ChunkANNRepository.lexical_search``.

These tests do NOT touch the database — they only assert that the method
rejects invalid arguments BEFORE any IO is attempted. The matching DB-backed
integration tests live in
``tests/integration/test_chunk_lexical_search.py``.

PLAN-0063 W5-2.
"""

from __future__ import annotations

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_search import ChunkANNRepository

pytestmark = pytest.mark.unit


async def test_lexical_search_section_granularity_raises_value_error() -> None:
    """``granularity='section'`` is unsupported in W5 — raises ValueError."""
    repo = ChunkANNRepository(session=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="granularity='chunk' only"):
        await repo.lexical_search("anything", granularity="section")


async def test_lexical_search_invalid_mode_raises_value_error() -> None:
    """Unknown mode (e.g. ``fts5``) raises ValueError before any IO."""
    repo = ChunkANNRepository(session=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mode must be one of"):
        await repo.lexical_search("anything", mode="fts5")
