"""Unit tests for Block 13E: _emit_temporal_events + _infer_temporal_scope.

Validates the filter-and-publish logic that reuses Block 10 extraction output
to produce ``intelligence.temporal_event.v1`` Kafka messages via the outbox.
No LLM calls are involved; all assertions are purely on the outbox.add() calls.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    _emit_temporal_events,
    _infer_temporal_scope,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outbox_repo() -> AsyncMock:
    """Return an AsyncMock that behaves like OutboxRepository.add()."""
    repo = MagicMock()
    repo.add = AsyncMock(return_value=uuid.uuid4())
    return repo


def _make_settings(topic: str = "intelligence.temporal_event.v1") -> MagicMock:
    """Minimal settings stub — only topic_temporal_event is read."""
    s = MagicMock()
    s.topic_temporal_event = topic
    return s


def _make_raw_event(
    event_type: str = "MACRO",
    confidence: float = 0.7,
    event_text: str = "Federal Reserve raises rates by 25bp",
    participant_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a raw_events dict entry matching _build_raw_events output shape."""
    return {
        "subject_entity_id": str(uuid.uuid4()),
        "event_type": event_type,
        "event_text": event_text,
        "extraction_confidence": confidence,
        "participant_entity_ids": participant_ids or [],
        "entity_provisional": False,
        "provisional_queue_id": None,
    }


# Published_at fixture — a UTC-aware datetime used across tests.
_PUBLISHED_AT = datetime(2026, 5, 3, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# _infer_temporal_scope
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInferTemporalScope:
    """Scope inference covers all five temporal event types plus a fallback."""

    def test_geopolitical_maps_to_global(self) -> None:
        assert _infer_temporal_scope("GEOPOLITICAL") == "GLOBAL"

    def test_sanctions_maps_to_global(self) -> None:
        assert _infer_temporal_scope("SANCTIONS") == "GLOBAL"

    def test_macro_maps_to_national(self) -> None:
        assert _infer_temporal_scope("MACRO") == "NATIONAL"

    def test_regulatory_action_maps_to_national(self) -> None:
        assert _infer_temporal_scope("REGULATORY_ACTION") == "NATIONAL"

    def test_natural_disaster_maps_to_regional(self) -> None:
        assert _infer_temporal_scope("NATURAL_DISASTER") == "REGIONAL"

    def test_unknown_type_defaults_to_national(self) -> None:
        # Any unrecognised type (e.g. from future LLM output) must not raise
        # and must produce a valid scope the S7 consumer accepts.
        assert _infer_temporal_scope("EARNINGS_RELEASE") == "NATIONAL"
        assert _infer_temporal_scope("") == "NATIONAL"


# ---------------------------------------------------------------------------
# _emit_temporal_events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitTemporalEvents:
    """Full filter-and-publish behaviour of Block 13E."""

    # ── Serialization is patched so tests do not need a real schema file ──────
    # serialize_confluent_avro is imported at module level in article_consumer.py
    # and referenced via the closure captured in _emit_temporal_events.
    # We patch it at the site where it is called.
    _PATCH_SERIALIZER = "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.serialize_confluent_avro"

    @pytest.mark.asyncio
    async def test_publishes_qualifying_macro_event(self) -> None:
        """A MACRO event with confidence=0.7 and a resolved participant produces one outbox call."""
        resolved_id = str(uuid.uuid4())
        raw_events = [_make_raw_event("MACRO", confidence=0.7, participant_ids=[resolved_id])]
        outbox_repo = _make_outbox_repo()
        settings = _make_settings()
        sentinel_bytes = b"\x00fake_avro_bytes"

        with patch(self._PATCH_SERIALIZER, return_value=sentinel_bytes) as mock_ser:
            await _emit_temporal_events(
                raw_events=raw_events,
                entity_id_by_ref={},  # not used directly — participant_ids already resolved
                provisional_entity_ids=frozenset(),
                doc_id=uuid.uuid4(),
                published_at=_PUBLISHED_AT,
                outbox_repo=outbox_repo,
                settings=settings,
            )

        # One temporal event should be emitted.
        outbox_repo.add.assert_called_once()
        call_kwargs = outbox_repo.add.call_args.kwargs

        # Topic must match the settings value.
        assert call_kwargs["topic"] == "intelligence.temporal_event.v1"
        # Payload bytes must be what the serializer returned.
        assert call_kwargs["payload_avro"] == sentinel_bytes

        # Inspect the payload dict that was passed to the serializer.
        _schema_path_arg, payload_dict = mock_ser.call_args.args
        assert payload_dict["temporal_event_type"] == "macro"
        assert payload_dict["scope"] == "NATIONAL"
        assert payload_dict["confidence"] == 0.7
        assert len(payload_dict["exposed_entities"]) == 1
        assert payload_dict["exposed_entities"][0]["entity_id"] == resolved_id
        assert payload_dict["exposed_entities"][0]["exposure_type"] == "directly_affected"
        # active_from must equal the published_at ISO string.
        assert payload_dict["active_from"] == _PUBLISHED_AT.isoformat()

    @pytest.mark.asyncio
    async def test_skips_low_confidence_event(self) -> None:
        """An event with confidence < 0.5 must produce zero outbox calls."""
        raw_events = [_make_raw_event("MACRO", confidence=0.3)]
        outbox_repo = _make_outbox_repo()

        with patch(self._PATCH_SERIALIZER, return_value=b"bytes"):
            await _emit_temporal_events(
                raw_events=raw_events,
                entity_id_by_ref={},
                provisional_entity_ids=frozenset(),
                doc_id=uuid.uuid4(),
                published_at=_PUBLISHED_AT,
                outbox_repo=outbox_repo,
                settings=_make_settings(),
            )

        outbox_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_non_temporal_event_type(self) -> None:
        """An event with event_type=EARNINGS_RELEASE is not temporal and must be skipped."""
        raw_events = [_make_raw_event("EARNINGS_RELEASE", confidence=0.9)]
        outbox_repo = _make_outbox_repo()

        with patch(self._PATCH_SERIALIZER, return_value=b"bytes"):
            await _emit_temporal_events(
                raw_events=raw_events,
                entity_id_by_ref={},
                provisional_entity_ids=frozenset(),
                doc_id=uuid.uuid4(),
                published_at=_PUBLISHED_AT,
                outbox_repo=outbox_repo,
                settings=_make_settings(),
            )

        outbox_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_empty_events_list(self) -> None:
        """Empty raw_events must produce zero outbox calls."""
        outbox_repo = _make_outbox_repo()

        with patch(self._PATCH_SERIALIZER, return_value=b"bytes"):
            await _emit_temporal_events(
                raw_events=[],
                entity_id_by_ref={},
                provisional_entity_ids=frozenset(),
                doc_id=uuid.uuid4(),
                published_at=_PUBLISHED_AT,
                outbox_repo=outbox_repo,
                settings=_make_settings(),
            )

        outbox_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_scope_inference_per_event_type(self) -> None:
        """GEOPOLITICAL → GLOBAL, MACRO → NATIONAL, NATURAL_DISASTER → REGIONAL."""
        captured_scopes: list[str] = []
        outbox_repo = _make_outbox_repo()

        def _capture_scope(_schema_path: str, payload: dict[str, Any]) -> bytes:
            captured_scopes.append(payload["scope"])
            return b"bytes"

        raw_events = [
            _make_raw_event("GEOPOLITICAL", confidence=0.8),
            _make_raw_event("MACRO", confidence=0.8),
            _make_raw_event("NATURAL_DISASTER", confidence=0.8),
        ]

        with patch(self._PATCH_SERIALIZER, side_effect=_capture_scope):
            await _emit_temporal_events(
                raw_events=raw_events,
                entity_id_by_ref={},
                provisional_entity_ids=frozenset(),
                doc_id=uuid.uuid4(),
                published_at=_PUBLISHED_AT,
                outbox_repo=outbox_repo,
                settings=_make_settings(),
            )

        assert outbox_repo.add.call_count == 3
        assert captured_scopes == ["GLOBAL", "NATIONAL", "REGIONAL"]

    @pytest.mark.asyncio
    async def test_multiple_qualifying_events_two_outbox_calls(self) -> None:
        """3 events (2 temporal MACRO, 1 non-temporal EARNINGS_RELEASE) → 2 outbox calls."""
        raw_events = [
            _make_raw_event("MACRO", confidence=0.8),
            _make_raw_event("EARNINGS_RELEASE", confidence=0.9),
            _make_raw_event("MACRO", confidence=0.6),
        ]
        outbox_repo = _make_outbox_repo()

        with patch(self._PATCH_SERIALIZER, return_value=b"bytes"):
            await _emit_temporal_events(
                raw_events=raw_events,
                entity_id_by_ref={},
                provisional_entity_ids=frozenset(),
                doc_id=uuid.uuid4(),
                published_at=_PUBLISHED_AT,
                outbox_repo=outbox_repo,
                settings=_make_settings(),
            )

        # Only the two MACRO events should generate outbox entries.
        assert outbox_repo.add.call_count == 2

    @pytest.mark.asyncio
    async def test_provisional_entities_excluded_from_exposed_entities(self) -> None:
        """Participant IDs that belong to provisional queue entries are excluded."""
        canonical_id = str(uuid.uuid4())
        provisional_id = str(uuid.uuid4())

        raw_events = [
            _make_raw_event(
                "GEOPOLITICAL",
                confidence=0.75,
                participant_ids=[canonical_id, provisional_id],
            )
        ]
        captured_exposed: list[list[dict[str, Any]]] = []
        outbox_repo = _make_outbox_repo()

        def _capture(_schema_path: str, payload: dict[str, Any]) -> bytes:
            captured_exposed.append(payload["exposed_entities"])
            return b"bytes"

        with patch(self._PATCH_SERIALIZER, side_effect=_capture):
            await _emit_temporal_events(
                raw_events=raw_events,
                entity_id_by_ref={},
                # provisional_id is in this set → must be skipped
                provisional_entity_ids=frozenset({provisional_id}),
                doc_id=uuid.uuid4(),
                published_at=_PUBLISHED_AT,
                outbox_repo=outbox_repo,
                settings=_make_settings(),
            )

        assert outbox_repo.add.call_count == 1
        exposed = captured_exposed[0]
        assert len(exposed) == 1
        assert exposed[0]["entity_id"] == canonical_id

    @pytest.mark.asyncio
    async def test_title_truncated_to_500_chars(self) -> None:
        """event_text longer than 500 chars must be truncated in the title field."""
        long_text = "A" * 700
        raw_events = [_make_raw_event("MACRO", confidence=0.8, event_text=long_text)]
        outbox_repo = _make_outbox_repo()
        captured: list[dict[str, Any]] = []

        def _capture(_schema_path: str, payload: dict[str, Any]) -> bytes:
            captured.append(payload)
            return b"bytes"

        with patch(self._PATCH_SERIALIZER, side_effect=_capture):
            await _emit_temporal_events(
                raw_events=raw_events,
                entity_id_by_ref={},
                provisional_entity_ids=frozenset(),
                doc_id=uuid.uuid4(),
                published_at=_PUBLISHED_AT,
                outbox_repo=outbox_repo,
                settings=_make_settings(),
            )

        assert len(captured[0]["title"]) == 500

    @pytest.mark.asyncio
    async def test_active_from_falls_back_to_utcnow_when_no_published_at(self) -> None:
        """When published_at is None, active_from must be a non-empty ISO string."""
        raw_events = [_make_raw_event("MACRO", confidence=0.8)]
        outbox_repo = _make_outbox_repo()
        captured: list[dict[str, Any]] = []

        def _capture(_schema_path: str, payload: dict[str, Any]) -> bytes:
            captured.append(payload)
            return b"bytes"

        with patch(self._PATCH_SERIALIZER, side_effect=_capture):
            await _emit_temporal_events(
                raw_events=raw_events,
                entity_id_by_ref={},
                provisional_entity_ids=frozenset(),
                doc_id=uuid.uuid4(),
                published_at=None,  # no published_at
                outbox_repo=outbox_repo,
                settings=_make_settings(),
            )

        active_from = captured[0]["active_from"]
        # Must be a parseable ISO-8601 string.
        dt = datetime.fromisoformat(active_from)
        assert dt.tzinfo is not None
