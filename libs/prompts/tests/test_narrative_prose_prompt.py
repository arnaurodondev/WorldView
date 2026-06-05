"""Unit tests for prompts.knowledge.narrative_prose — Phase 2C migration."""

from __future__ import annotations

import pytest
from prompts.knowledge.narrative_prose import NARRATIVE_PROSE


class TestNarrativeProse:
    def test_render_returns_anchor_text(self) -> None:
        result = NARRATIVE_PROSE.render()
        # The anchor (journalistic voice + 2-4 sentence + no-JSON instruction)
        # is what keeps the 8B model from emitting JSON envelopes.
        assert "financial intelligence analyst" in result
        assert "2-4 sentence" in result
        assert "no JSON" in result

    def test_version_is_semver(self) -> None:
        assert NARRATIVE_PROSE.version == "1.0"

    def test_identifier_format(self) -> None:
        ident = NARRATIVE_PROSE.identifier()
        assert ident.startswith("narrative_prose@1.0#")
        assert len(ident.split("#")[-1]) == 12

    def test_no_parameters(self) -> None:
        # System-only message; caller supplies the structured profile via the
        # chat-completion user role, not via template substitution.
        assert NARRATIVE_PROSE.parameters == frozenset()

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            NARRATIVE_PROSE.version = "2.0"  # type: ignore[misc]
