"""Unit tests for prompts.knowledge — summary, entity profile, alias prompts."""

from __future__ import annotations

import pytest
from prompts.knowledge.alias import ALIAS_GENERATION
from prompts.knowledge.entity_profile import ENTITY_PROFILE
from prompts.knowledge.summary import RELATION_SUMMARY


class TestRelationSummary:
    def test_render(self) -> None:
        evidence = "- Evidence A\n- Evidence B"
        result = RELATION_SUMMARY.render(evidence_statements=evidence)
        assert "Evidence A" in result
        assert "Evidence B" in result

    def test_contains_instructions(self) -> None:
        result = RELATION_SUMMARY.render(evidence_statements="test")
        assert "2-3 sentence summary" in result
        assert "key facts" in result

    def test_missing_param_raises(self) -> None:
        with pytest.raises(ValueError, match="evidence_statements"):
            RELATION_SUMMARY.render()


class TestEntityProfile:
    def test_render(self) -> None:
        result = ENTITY_PROFILE.render(name="Apple Inc", entity_class="company")
        assert "Apple Inc" in result
        assert "company" in result

    def test_contains_json_fields(self) -> None:
        result = ENTITY_PROFILE.render(name="Test", entity_class="person")
        assert "canonical_name" in result
        assert "ticker" in result
        assert "aliases" in result

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            ENTITY_PROFILE.render(entity_class="company")

    def test_missing_entity_class_raises(self) -> None:
        with pytest.raises(ValueError, match="entity_class"):
            ENTITY_PROFILE.render(name="Test")


class TestAliasGeneration:
    def test_render(self) -> None:
        result = ALIAS_GENERATION.render(name="Apple Inc", ticker="AAPL")
        assert "Apple Inc" in result
        assert "AAPL" in result

    def test_contains_json_instruction(self) -> None:
        result = ALIAS_GENERATION.render(name="Test", ticker="TST")
        assert '"aliases"' in result
        assert "5 common alternative names" in result

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            ALIAS_GENERATION.render(ticker="AAPL")

    def test_missing_ticker_raises(self) -> None:
        with pytest.raises(ValueError, match="ticker"):
            ALIAS_GENERATION.render(name="Apple Inc")


class TestVersions:
    def test_all_versions_are_semver(self) -> None:
        for pt in [RELATION_SUMMARY, ENTITY_PROFILE, ALIAS_GENERATION]:
            assert pt.version == "1.0", f"{pt.name} has unexpected version"
