"""Unit tests for contracts.canonical.entity."""

from __future__ import annotations

import dataclasses

import pytest

from contracts.canonical.entity import CanonicalEntity
from contracts.versions import ENTITY_SCHEMA_VERSION


class TestCanonicalEntity:
    def _make_entity(self) -> CanonicalEntity:
        return CanonicalEntity(
            entity_id="01JPENT123",
            entity_type="Company",
            name="Apple Inc.",
            canonical_name="Apple",
            source_article_id="01JPXYZ123ABC",
            confidence=0.95,
        )

    def test_schema_version(self) -> None:
        assert self._make_entity().schema_version == ENTITY_SCHEMA_VERSION

    def test_schema_version_is_1(self) -> None:
        assert ENTITY_SCHEMA_VERSION == 1

    def test_roundtrip(self) -> None:
        entity = self._make_entity()
        restored = CanonicalEntity.from_dict(entity.to_dict())
        assert restored.entity_id == entity.entity_id
        assert restored.entity_type == entity.entity_type
        assert restored.name == entity.name
        assert restored.canonical_name == entity.canonical_name
        assert restored.source_article_id == entity.source_article_id
        assert restored.confidence == entity.confidence

    def test_frozen(self) -> None:
        entity = self._make_entity()
        with pytest.raises(dataclasses.FrozenInstanceError):
            entity.name = "Google"  # type: ignore[misc]

    def test_metadata_default_empty(self) -> None:
        entity = self._make_entity()
        assert entity.metadata == {}

    def test_metadata_roundtrip(self) -> None:
        entity = CanonicalEntity(
            entity_id="01JPENT456",
            entity_type="Person",
            name="Tim Cook",
            canonical_name="Tim Cook",
            source_article_id="01JPXYZ999",
            confidence=0.88,
            metadata={"role": "CEO", "ticker": "AAPL"},
        )
        d = entity.to_dict()
        restored = CanonicalEntity.from_dict(d)
        assert restored.metadata == {"role": "CEO", "ticker": "AAPL"}

    def test_entity_types(self) -> None:
        for etype in ("Person", "Company", "Location", "Event"):
            entity = CanonicalEntity(
                entity_id="x",
                entity_type=etype,
                name="test",
                canonical_name="test",
                source_article_id="y",
                confidence=0.5,
            )
            assert entity.entity_type == etype

    def test_confidence_float(self) -> None:
        entity = self._make_entity()
        assert isinstance(entity.confidence, float)
        assert 0.0 <= entity.confidence <= 1.0
