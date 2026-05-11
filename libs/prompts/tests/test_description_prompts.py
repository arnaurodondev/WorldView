"""Unit tests for prompts.description — entity description prompt template."""

from __future__ import annotations

import pytest
from prompts.description.entity import ENTITY_DESCRIPTION


class TestEntityDescription:
    def test_render(self) -> None:
        result = ENTITY_DESCRIPTION.render(
            name="Federal Reserve",
            type="government_body",
            hints="sector: Finance; country: US",
        )
        assert "Federal Reserve" in result
        assert "government_body" in result
        assert "sector: Finance; country: US" in result

    def test_xml_wrapping(self) -> None:
        """Verify that name and type are wrapped in XML tags for injection safety."""
        result = ENTITY_DESCRIPTION.render(name="TestEntity", type="person", hints="none")
        assert "<entity_name>TestEntity</entity_name>" in result
        assert "<entity_type>person</entity_type>" in result

    def test_contains_instructions(self) -> None:
        result = ENTITY_DESCRIPTION.render(name="X", type="y", hints="none")
        assert "2-3 sentence" in result
        assert "Do not include opinions" in result
        assert "no JSON, no markdown" in result

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            ENTITY_DESCRIPTION.render(type="company", hints="none")

    def test_missing_type_raises(self) -> None:
        with pytest.raises(ValueError, match="type"):
            ENTITY_DESCRIPTION.render(name="Test", hints="none")

    def test_missing_hints_raises(self) -> None:
        with pytest.raises(ValueError, match="hints"):
            ENTITY_DESCRIPTION.render(name="Test", type="company")

    def test_version_is_semver(self) -> None:
        assert ENTITY_DESCRIPTION.version == "1.0"

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            ENTITY_DESCRIPTION.name = "changed"  # type: ignore[misc]
