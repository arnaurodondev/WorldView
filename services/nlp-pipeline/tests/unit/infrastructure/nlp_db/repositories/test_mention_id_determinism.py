"""Tests for mention_id determinism — PLAN-0084 B-3 / F-010.

mention_id is computed as uuid5_from_parts(str(doc_id), str(loop_index), normalized_surface).
This module verifies:
- Identical inputs → identical IDs (safe Kafka replay)
- Different positions → different IDs (no collision)
- Different surfaces → different IDs
- Different doc_ids → different IDs (cross-document isolation)
"""

from __future__ import annotations

import uuid

import pytest

from common.ids import uuid5_from_parts  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_DOC_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
_DOC_B = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _mention_id(doc_id: uuid.UUID, idx: int, surface: str) -> uuid.UUID:
    """Mirror the exact formula in article_consumer.py:376."""
    return uuid.UUID(uuid5_from_parts(str(doc_id), str(idx), surface.lower().strip()))


def test_mention_id_is_deterministic_on_replay() -> None:
    """Same (doc_id, idx, surface) → same mention_id across two calls (F-010)."""
    id1 = _mention_id(_DOC_A, 0, "Apple Inc")
    id2 = _mention_id(_DOC_A, 0, "Apple Inc")
    assert id1 == id2, "mention_id must be deterministic — uuid5_from_parts guarantees this"


def test_mention_id_differs_by_position() -> None:
    """Two mentions with same surface but different loop-index must have different IDs."""
    id_pos0 = _mention_id(_DOC_A, 0, "Apple Inc")
    id_pos1 = _mention_id(_DOC_A, 1, "Apple Inc")
    assert id_pos0 != id_pos1, "Different positions must yield different IDs"


def test_mention_id_differs_by_surface() -> None:
    """Different normalized surfaces at the same position must differ."""
    id_apple = _mention_id(_DOC_A, 0, "Apple Inc")
    id_google = _mention_id(_DOC_A, 0, "Alphabet Inc")
    assert id_apple != id_google


def test_mention_id_differs_by_doc() -> None:
    """Same surface + same index across two docs must yield different IDs."""
    id_a = _mention_id(_DOC_A, 0, "Apple Inc")
    id_b = _mention_id(_DOC_B, 0, "Apple Inc")
    assert id_a != id_b, "Cross-document mention IDs must not collide"


def test_mention_id_normalises_surface_case() -> None:
    """The formula applies .lower().strip() so case/whitespace variants are identical."""
    id_lower = _mention_id(_DOC_A, 0, "apple inc")
    id_upper = _mention_id(_DOC_A, 0, "Apple Inc")
    id_spaced = _mention_id(_DOC_A, 0, "  Apple Inc  ")
    assert id_lower == id_upper == id_spaced, "Surface normalisation must produce identical IDs"
