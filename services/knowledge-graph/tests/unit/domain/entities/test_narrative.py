"""Unit tests for the EntityNarrativeVersion domain entity (T-C-01)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000001")
_VERSION_ID = UUID("00000000-0000-0000-0000-000000000002")
_NARRATIVE = "A" * 100  # 100-char string, well within [50, 10000]
_GENERATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_version(**kwargs: object) -> EntityNarrativeVersion:
    from knowledge_graph.domain.narrative import EntityNarrativeVersion, NarrativeGenerationReason

    defaults = {
        "version_id": _VERSION_ID,
        "entity_id": _ENTITY_ID,
        "narrative_text": _NARRATIVE,
        "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
        "generation_reason": NarrativeGenerationReason.INITIAL,
        "generated_at": _GENERATED_AT,
    }
    defaults.update(kwargs)  # type: ignore[arg-type]
    return EntityNarrativeVersion(**defaults)  # type: ignore[arg-type]


class TestEntityNarrativeVersionValidation:
    def test_narrative_too_short_rejected(self) -> None:
        """Texts shorter than 50 characters must raise ValueError."""
        with pytest.raises(ValueError, match="length"):
            _make_version(narrative_text="X" * 49)

    def test_narrative_too_long_rejected(self) -> None:
        """Texts longer than 10000 characters must raise ValueError."""
        with pytest.raises(ValueError, match="length"):
            _make_version(narrative_text="X" * 10001)

    def test_narrative_boundary_accepted_50_chars(self) -> None:
        """Exactly 50 characters is the minimum accepted length."""
        v = _make_version(narrative_text="X" * 50)
        assert len(v.narrative_text) == 50

    def test_narrative_boundary_accepted_10000_chars(self) -> None:
        """Exactly 10000 characters is the maximum accepted length."""
        v = _make_version(narrative_text="X" * 10000)
        assert len(v.narrative_text) == 10000

    def test_word_count_must_match_narrative(self) -> None:
        """Supplying word_count that does not match raises ValueError."""
        text = "hello world foo bar"  # 4 words
        with pytest.raises(ValueError, match="word_count"):
            _make_version(narrative_text=text + " " * 46, word_count=999)

    def test_word_count_valid_matches_accepted(self) -> None:
        """When word_count equals actual word count, no error is raised."""
        text = "word " * 12  # 12 words, 60 chars
        v = _make_version(narrative_text=text.strip(), word_count=12)
        assert v.word_count == 12

    def test_generated_at_must_be_utc_aware(self) -> None:
        """Naive datetime must raise ValueError."""
        naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo  # noqa: DTZ001
        with pytest.raises(ValueError, match="timezone-aware"):
            _make_version(generated_at=naive)

    def test_generated_at_aware_accepted(self) -> None:
        """A timezone-aware datetime is accepted without error."""
        v = _make_version(generated_at=_GENERATED_AT)
        assert v.generated_at.tzinfo is not None


class TestNarrativeGenerationReasonEnum:
    def test_narrative_generation_reason_enum_values(self) -> None:
        """All 5 enum members must round-trip through their string values."""
        from knowledge_graph.domain.narrative import NarrativeGenerationReason

        expected = {
            NarrativeGenerationReason.INITIAL: "INITIAL",
            NarrativeGenerationReason.PERIODIC_REFRESH: "PERIODIC_REFRESH",
            NarrativeGenerationReason.DATA_UPDATE: "DATA_UPDATE",
            NarrativeGenerationReason.EVIDENCE_SURGE: "EVIDENCE_SURGE",
            NarrativeGenerationReason.MANUAL_TRIGGER: "MANUAL_TRIGGER",
        }
        for member, value in expected.items():
            assert member.value == value
            assert NarrativeGenerationReason(value) is member


class TestEntityNarrativeVersionImmutability:
    def test_narrative_frozen_immutable(self) -> None:
        """Attempting to reassign any field on a frozen dataclass raises FrozenInstanceError."""
        from dataclasses import FrozenInstanceError

        v = _make_version()
        with pytest.raises(FrozenInstanceError):
            v.narrative_text = "changed"  # type: ignore[misc]

    def test_defaults_applied_correctly(self) -> None:
        """is_current defaults to False, word_count and quality_score default to None."""
        v = _make_version()
        assert v.is_current is False
        assert v.word_count is None
        assert v.quality_score is None
        assert v.input_snapshot is None
