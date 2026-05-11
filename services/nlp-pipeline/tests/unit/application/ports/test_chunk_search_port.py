"""Stub-based tests for ChunkSearchPort ABC (PLAN-0084 T-D-1-04).

Demonstrates that:
1. A concrete stub class satisfying the ABC is accepted by mypy as a valid
   ``ChunkSearchPort`` — meaning use cases typed against the port can receive
   any conforming implementation.
2. The use case layer works correctly when wired with the stub, showing that
   no concrete-class methods are called beyond the port contract.

The stub replaces AsyncMock() in one representative test from
``test_enhanced_chunk_search.py`` to prove the pattern.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from nlp_pipeline.application.ports.chunk_search import ChunkSearchPort
from nlp_pipeline.application.use_cases.enhanced_chunk_search import (
    EnhancedChunkSearchUseCase,
)

pytestmark = pytest.mark.unit

# ── Shared test IDs ───────────────────────────────────────────────────────────

_CHUNK_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000010")
_DOC_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000011")
_SECTION_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000012")
_DUMMY_VEC = [0.1] * 1024


# ── Stub implementation ───────────────────────────────────────────────────────


class StubChunkSearchPort(ChunkSearchPort):
    """Minimal concrete implementation of ``ChunkSearchPort`` for testing.

    Returns a single hard-coded result from ``ann_search`` so that the use case
    can exercise its enrichment path without touching the DB.

    By being a proper ABC subclass (not a MagicMock), mypy verifies at
    *type-check time* that ``StubChunkSearchPort`` satisfies the port contract —
    i.e. that every abstract method is implemented with compatible signatures.
    """

    def __init__(
        self,
        *,
        ann_result: dict[str, Any] | None = None,
        entity_mentions: list[dict[str, Any]] | None = None,
    ) -> None:
        # Store configured return values so individual tests can customise them.
        self._ann_result = ann_result or {
            "chunk_id": _CHUNK_ID,
            "doc_id": _DOC_ID,
            "section_id": _SECTION_ID,
            "granularity": "chunk",
            "text": "Test heading",
            "score": 0.85,
            "section_type": "body",
            "heading_path": "Test heading",
            "chunk_text_key": None,
        }
        self._entity_mentions = entity_mentions or []
        # Call tracking for assertion in tests.
        self.ann_search_calls: int = 0
        self.lexical_search_calls: int = 0
        self.fetch_entity_mentions_calls: int = 0

    async def ann_search(
        self,
        embedding: list[float],
        granularity: str,
        top_k: int,
        min_score: float,
        date_from: Any | None,
        date_to: Any | None,
        source_types: list[str] | None,
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
        # PLAN-0086 Wave C-1: tenant scope filter.
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ann_search_calls += 1
        return [self._ann_result], 100

    async def lexical_search(
        self,
        query_text: str,
        *,
        mode: str,
        granularity: str,
        top_k: int,
        min_score: float,
        date_from: Any | None,
        date_to: Any | None,
        source_types: list[str] | None,
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
        # PLAN-0086 Wave C-1: tenant scope filter.
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        self.lexical_search_calls += 1
        return [], 0

    async def fetch_entity_mentions(
        self,
        chunk_ids: list[UUID],
        min_confidence: float,
    ) -> list[dict[str, Any]]:
        self.fetch_entity_mentions_calls += 1
        return self._entity_mentions


# ── ABC contract tests ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestChunkSearchPortContract:
    """Verify the ABC enforces all abstract methods."""

    def test_stub_is_valid_chunk_search_port(self) -> None:
        """StubChunkSearchPort must satisfy isinstance check against the ABC."""
        stub = StubChunkSearchPort()
        # isinstance checks that the concrete class correctly inherits and
        # implements all abstract methods declared in ChunkSearchPort.
        assert isinstance(stub, ChunkSearchPort)

    def test_cannot_instantiate_abstract_base_directly(self) -> None:
        """ChunkSearchPort itself must be abstract (cannot be instantiated)."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            ChunkSearchPort()  # type: ignore[abstract]

    def test_partial_stub_raises_type_error(self) -> None:
        """A class that only partially implements the ABC must fail instantiation."""

        class PartialStub(ChunkSearchPort):
            # Only implement ann_search; leave lexical_search + fetch_entity_mentions abstract.
            async def ann_search(  # type: ignore[override]
                self,
                embedding: list[float],
                granularity: str,
                top_k: int,
                min_score: float,
                date_from: Any | None,
                date_to: Any | None,
                source_types: list[str] | None,
                entity_ids: list[UUID] | None = None,
                entity_types: list[str] | None = None,
                tenant_id: str | None = None,
            ) -> tuple[list[dict[str, Any]], int]:
                return [], 0

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            PartialStub()  # type: ignore[abstract]


# ── Use-case integration with stub ───────────────────────────────────────────


@pytest.mark.unit
class TestEnhancedChunkSearchWithStub:
    """Demonstrate stub replacing AsyncMock in one use-case test.

    This test replaces the ``chunk_ann_repo=AsyncMock()`` pattern from
    ``test_enhanced_chunk_search.py`` with a proper ``StubChunkSearchPort``
    to show the canonical testing pattern going forward.
    """

    @pytest.mark.asyncio
    async def test_stub_delivers_ann_result_to_use_case(self) -> None:
        """Verify that the use case calls ann_search via the port and processes results."""
        from unittest.mock import AsyncMock

        stub = StubChunkSearchPort()

        # Minimal collaborator mocks (not the focus of this test).
        source_meta_repo = AsyncMock()
        source_meta_repo.batch_get = AsyncMock(return_value={})
        canon_repo = AsyncMock()
        canon_repo.batch_get = AsyncMock(return_value={})
        valkey = AsyncMock()
        valkey.get = AsyncMock(return_value=None)
        valkey.set = AsyncMock()

        uc = EnhancedChunkSearchUseCase(
            chunk_ann_repo=stub,
            source_metadata_repo=source_meta_repo,
            canonical_entity_repo=canon_repo,
            valkey=valkey,
        )

        results, total, model = await uc.execute(
            query_text=None,
            query_embedding=_DUMMY_VEC,
        )

        # Stub was called once; result was returned and enriched.
        assert stub.ann_search_calls == 1
        assert total == 100
        assert len(results) == 1
        assert results[0].chunk_id == _CHUNK_ID

    @pytest.mark.asyncio
    async def test_stub_lexical_search_not_called_for_ann_search_type(self) -> None:
        """When search_type='ann', the lexical_search path must not be invoked."""
        from unittest.mock import AsyncMock

        stub = StubChunkSearchPort()
        source_meta_repo = AsyncMock()
        source_meta_repo.batch_get = AsyncMock(return_value={})
        canon_repo = AsyncMock()
        canon_repo.batch_get = AsyncMock(return_value={})

        uc = EnhancedChunkSearchUseCase(
            chunk_ann_repo=stub,
            source_metadata_repo=source_meta_repo,
            canonical_entity_repo=canon_repo,
        )

        await uc.execute(
            query_text=None,
            query_embedding=_DUMMY_VEC,
            search_type="ann",
        )

        # ANN path must NOT invoke lexical_search.
        assert stub.lexical_search_calls == 0
        assert stub.ann_search_calls == 1
