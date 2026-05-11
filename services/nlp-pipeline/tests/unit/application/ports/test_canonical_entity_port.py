"""Stub-based tests for CanonicalEntityPort ABC (PLAN-0084 T-D-2-04).

Demonstrates that:
1. A concrete stub class satisfying the ABC is accepted as a valid
   ``CanonicalEntityPort`` — use cases typed against the port can receive
   any conforming implementation.
2. ``CanonicalEntityRepository`` (concrete infra class) satisfies
   ``isinstance(..., CanonicalEntityPort)``.
3. Partial stubs fail instantiation — the ABC enforces all three methods.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from nlp_pipeline.application.ports.canonical_entity import CanonicalEntityPort

pytestmark = pytest.mark.unit

# ── Shared test IDs ───────────────────────────────────────────────────────────

_ENTITY_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000020")


# ── Stub implementation ───────────────────────────────────────────────────────


class StubCanonicalEntityPort(CanonicalEntityPort):
    """Minimal concrete implementation of ``CanonicalEntityPort`` for testing.

    Stores entities in an in-memory dict so tests can add/query rows without
    hitting the database.

    By subclassing the ABC (not MagicMock), mypy verifies at type-check time
    that all abstract methods are implemented with compatible signatures.
    """

    def __init__(self) -> None:
        self._store: dict[UUID, dict[str, object]] = {}

    def seed(self, entity_id: UUID, *, canonical_name: str, entity_type: str) -> None:
        """Helper for tests: pre-populate an entity row."""
        self._store[entity_id] = {
            "entity_id": entity_id,
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "isin": None,
            "ticker": None,
            "exchange": None,
        }

    async def get(self, entity_id: UUID) -> dict[str, object] | None:
        return self._store.get(entity_id)

    async def batch_get(self, entity_ids: list[UUID]) -> dict[UUID, dict[str, object]]:
        return {eid: row for eid, row in self._store.items() if eid in entity_ids}

    async def create(
        self,
        canonical_name: str,
        entity_type: str,
        *,
        isin: str | None = None,
        ticker: str | None = None,
        exchange: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> UUID:
        new_id = uuid.uuid4()
        self._store[new_id] = {
            "entity_id": new_id,
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "isin": isin,
            "ticker": ticker,
            "exchange": exchange,
        }
        return new_id


# ── ABC contract tests ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCanonicalEntityPortContract:
    """Verify the ABC enforces all abstract methods."""

    def test_stub_is_valid_canonical_entity_port(self) -> None:
        """StubCanonicalEntityPort must satisfy isinstance check against the ABC."""
        stub = StubCanonicalEntityPort()
        assert isinstance(stub, CanonicalEntityPort)

    def test_cannot_instantiate_abstract_base_directly(self) -> None:
        """CanonicalEntityPort itself must be abstract (cannot be instantiated)."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            CanonicalEntityPort()  # type: ignore[abstract]

    def test_partial_stub_missing_create_raises(self) -> None:
        """A stub that omits ``create`` must fail instantiation."""

        class NoCreateStub(CanonicalEntityPort):
            async def get(self, entity_id: UUID) -> dict[str, object] | None:
                return None

            async def batch_get(self, entity_ids: list[UUID]) -> dict[UUID, dict[str, object]]:
                return {}

            # ``create`` intentionally omitted.

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            NoCreateStub()  # type: ignore[abstract]

    def test_partial_stub_missing_get_raises(self) -> None:
        """A stub that omits ``get`` must fail instantiation."""

        class NoBatchGetStub(CanonicalEntityPort):
            async def batch_get(self, entity_ids: list[UUID]) -> dict[UUID, dict[str, object]]:
                return {}

            async def create(
                self,
                canonical_name: str,
                entity_type: str,
                *,
                isin: str | None = None,
                ticker: str | None = None,
                exchange: str | None = None,
                metadata: dict[str, object] | None = None,
            ) -> UUID:
                return uuid.uuid4()

            # ``get`` intentionally omitted.

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            NoBatchGetStub()  # type: ignore[abstract]


# ── Stub functional tests ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestStubCanonicalEntityPortFunctionality:
    """Verify the stub behaves correctly as a drop-in for use case tests."""

    @pytest.mark.asyncio
    async def test_get_returns_seeded_entity(self) -> None:
        stub = StubCanonicalEntityPort()
        stub.seed(_ENTITY_ID, canonical_name="Apple Inc.", entity_type="organization")

        result = await stub.get(_ENTITY_ID)

        assert result is not None
        assert result["canonical_name"] == "Apple Inc."
        assert result["entity_type"] == "organization"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown_id(self) -> None:
        stub = StubCanonicalEntityPort()
        result = await stub.get(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_batch_get_returns_only_requested_ids(self) -> None:
        other_id = uuid.UUID("018f1e2a-0000-7000-8000-000000000021")

        stub = StubCanonicalEntityPort()
        stub.seed(_ENTITY_ID, canonical_name="Apple Inc.", entity_type="organization")
        stub.seed(other_id, canonical_name="Microsoft Corp.", entity_type="organization")

        result = await stub.batch_get([_ENTITY_ID])

        assert len(result) == 1
        assert _ENTITY_ID in result
        assert other_id not in result

    @pytest.mark.asyncio
    async def test_batch_get_empty_list_returns_empty_dict(self) -> None:
        stub = StubCanonicalEntityPort()
        stub.seed(_ENTITY_ID, canonical_name="Apple Inc.", entity_type="organization")

        result = await stub.batch_get([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_create_adds_entity_and_returns_new_id(self) -> None:
        stub = StubCanonicalEntityPort()

        new_id = await stub.create("Tesla Inc.", "organization", ticker="TSLA")

        assert isinstance(new_id, UUID)
        row = await stub.get(new_id)
        assert row is not None
        assert row["canonical_name"] == "Tesla Inc."
        assert row["ticker"] == "TSLA"

    @pytest.mark.asyncio
    async def test_create_returns_unique_ids_for_different_calls(self) -> None:
        stub = StubCanonicalEntityPort()
        id1 = await stub.create("Entity A", "organization")
        id2 = await stub.create("Entity B", "organization")
        assert id1 != id2


# ── Concrete repository satisfies port ───────────────────────────────────────


@pytest.mark.unit
class TestCanonicalEntityRepositorySatisfiesPort:
    """Verify the concrete infra class is a valid CanonicalEntityPort subtype."""

    def test_concrete_class_is_subclass_of_port(self) -> None:
        """``CanonicalEntityRepository`` must be a structural subclass of the ABC.

        This test imports the concrete class and verifies it satisfies
        ``issubclass``. If the D-2 refactor breaks the inheritance declaration,
        this test fails immediately.
        """
        from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        assert issubclass(CanonicalEntityRepository, CanonicalEntityPort)
