"""Schema validator tests for ChunkSearchRequest (PLAN-0063 W5-3 T-01).

These exercise the `search_type` literal + the new
`_search_type_requires_query_text` model_validator. They run *inside* the API
boundary — the use case never sees an invalid request because pydantic
rejects it at deserialisation.
"""

from __future__ import annotations

import pytest
from nlp_pipeline.api.schemas import ChunkSearchRequest
from pydantic import ValidationError

# A 1024-dim dummy vector — the schema requires exactly 1024 floats.
_DUMMY_VEC = [0.1] * 1024


def test_default_search_type_is_ann() -> None:
    """Backwards compatibility: callers that don't set search_type stay on ANN."""
    req = ChunkSearchRequest(query_embedding=_DUMMY_VEC)
    assert req.search_type == "ann"


def test_search_type_hybrid_accepted() -> None:
    """Hybrid + query_text is the typical S8 path."""
    req = ChunkSearchRequest(query_text="apple revenue", search_type="hybrid")
    assert req.search_type == "hybrid"


def test_search_type_lexical_accepted() -> None:
    """Lexical-only mode is exposed for debugging / boost-sweep evaluation."""
    req = ChunkSearchRequest(query_text="PRD-0034 design", search_type="lexical")
    assert req.search_type == "lexical"


def test_search_type_unknown_value_rejected() -> None:
    """The Literal type rejects anything outside {ann, lexical, hybrid}."""
    with pytest.raises(ValidationError):
        ChunkSearchRequest(query_text="x", search_type="fts5")  # type: ignore[arg-type]


def test_lexical_requires_query_text() -> None:
    """Lexical FTS has no interpretation of a raw embedding."""
    with pytest.raises(ValidationError) as exc:
        ChunkSearchRequest(query_embedding=_DUMMY_VEC, search_type="lexical")
    # Sanity: error message mentions search_type.
    assert "search_type" in str(exc.value)


def test_hybrid_requires_query_text() -> None:
    """Hybrid needs text for the FTS leg even if an embedding is supplied."""
    with pytest.raises(ValidationError) as exc:
        ChunkSearchRequest(query_embedding=_DUMMY_VEC, search_type="hybrid")
    assert "search_type" in str(exc.value)


def test_hybrid_with_both_text_and_embedding_ok() -> None:
    """Hybrid loosens the exactly-one-query rule — both inputs are useful."""
    req = ChunkSearchRequest(
        query_text="apple revenue",
        query_embedding=_DUMMY_VEC,
        search_type="hybrid",
    )
    assert req.query_text == "apple revenue"
    assert req.query_embedding is not None
    assert len(req.query_embedding) == 1024
