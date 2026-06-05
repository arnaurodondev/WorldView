"""Unit tests for prompts.extraction.entity_mention_classification — Phase 2C."""

from __future__ import annotations

import pytest
from prompts.extraction.entity_mention_classification import (
    ENTITY_MENTION_CLASSIFIER_SYSTEM,
    ENTITY_MENTION_CLASSIFIER_USER,
)


class TestEntityMentionClassifierSystem:
    def test_render_no_parameters(self) -> None:
        # System block has no template parameters; should render verbatim
        # (with {{ → { in the worked-example JSON snippets).
        result = ENTITY_MENTION_CLASSIFIER_SYSTEM.render()
        assert "candidate entity mention" in result
        assert '{"is_entity":' in result  # un-escaped after render()
        assert '"confidence":' in result

    def test_contains_positive_and_negative_classes(self) -> None:
        result = ENTITY_MENTION_CLASSIFIER_SYSTEM.render()
        # Positive class examples — must call out the historically-missed
        # categories (ETFs, regulators, subsidiaries).
        assert "ETF" in result
        assert "subsidiary" in result
        assert "central bank" in result
        # Negative class — generic roles + jargon (the production leakers).
        assert "analysts" in result
        assert "constant currency" in result

    def test_contains_five_worked_examples(self) -> None:
        # The five examples are the calibration anchors the LLM matches against.
        result = ENTITY_MENTION_CLASSIFIER_SYSTEM.render()
        for surface in ("iShares Core S&P 500 ETF", "MAS", "analysts", "constant currency", "Q3"):
            assert surface in result

    def test_version_is_semver(self) -> None:
        assert ENTITY_MENTION_CLASSIFIER_SYSTEM.version == "1.0"

    def test_identifier_format(self) -> None:
        ident = ENTITY_MENTION_CLASSIFIER_SYSTEM.identifier()
        assert ident.startswith("entity_mention_classifier_system@1.0#")
        assert len(ident.split("#")[-1]) == 12

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            ENTITY_MENTION_CLASSIFIER_SYSTEM.template = "x"  # type: ignore[misc]


class TestEntityMentionClassifierUser:
    def test_render_inlines_values(self) -> None:
        # Caller is responsible for json.dumps()-escaping; the template inlines
        # whatever it gets, without adding outer quotes.
        result = ENTITY_MENTION_CLASSIFIER_USER.render(
            surface='"Apple"',
            context='"context with quotes"',
        )
        assert result == 'SURFACE: "Apple"\nCONTEXT: "context with quotes"'

    def test_missing_surface_raises(self) -> None:
        with pytest.raises(ValueError, match="surface"):
            ENTITY_MENTION_CLASSIFIER_USER.render(context='""')

    def test_missing_context_raises(self) -> None:
        with pytest.raises(ValueError, match="context"):
            ENTITY_MENTION_CLASSIFIER_USER.render(surface='""')

    def test_parameters_set(self) -> None:
        assert ENTITY_MENTION_CLASSIFIER_USER.parameters == frozenset({"surface", "context"})
