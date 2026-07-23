"""Unit tests for hybrid extraction-model routing (2026-07-17 DeepSeek regression).

Verifies the pure per-doc model selection: SEC filings and long docs route to the
high-recall Qwen model; short/medium docs keep the DeepSeek primary; the master
switch and empty high-recall slug both fall back to the primary.
"""

from __future__ import annotations

import pytest
from nlp_pipeline.application.blocks.extraction_routing import (
    parse_source_types,
    select_extraction_model,
)

pytestmark = pytest.mark.unit

PRIMARY = "deepseek-ai/DeepSeek-V4-Flash"
HIGH_RECALL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
SEC_TYPES = frozenset({"sec_edgar"})


def _route(
    source_type: str | None, word_count: int, *, enabled: bool = True, threshold: int = 6000, high: str = HIGH_RECALL
):
    return select_extraction_model(
        source_type=source_type,
        word_count=word_count,
        primary_model_id=PRIMARY,
        high_recall_model_id=high,
        high_recall_source_types=SEC_TYPES,
        word_count_threshold=threshold,
        enabled=enabled,
    )


def test_sec_edgar_routes_to_high_recall_regardless_of_size() -> None:
    # A short filing STILL routes to the recall model — filings are the reason for
    # KG-relation extraction (audit §6).
    route = _route("sec_edgar", word_count=50)
    assert route.high_recall is True
    assert route.model_id == HIGH_RECALL
    assert route.reason == "source_type"


def test_sec_edgar_case_insensitive() -> None:
    route = _route("SEC_EDGAR", word_count=10)
    assert route.model_id == HIGH_RECALL
    assert route.reason == "source_type"


def test_large_non_filing_doc_routes_to_high_recall_via_word_count() -> None:
    # DeepSeek also under-extracts long eodhd articles → word-count fallback catches them.
    route = _route("eodhd", word_count=6000)
    assert route.high_recall is True
    assert route.model_id == HIGH_RECALL
    assert route.reason == "word_count"


def test_short_doc_routes_to_deepseek_primary() -> None:
    route = _route("eodhd", word_count=500)
    assert route.high_recall is False
    assert route.model_id == PRIMARY
    assert route.reason == "default"


def test_word_count_threshold_is_inclusive_boundary() -> None:
    assert _route("newsapi", 5999).high_recall is False
    assert _route("newsapi", 6000).high_recall is True


def test_disabled_flag_forces_primary_even_for_filings() -> None:
    route = _route("sec_edgar", word_count=50000, enabled=False)
    assert route.high_recall is False
    assert route.model_id == PRIMARY
    assert route.reason == "disabled"


def test_empty_high_recall_model_forces_primary() -> None:
    route = _route("sec_edgar", word_count=50000, high="")
    assert route.high_recall is False
    assert route.model_id == PRIMARY
    assert route.reason == "disabled"


def test_zero_threshold_disables_word_count_arm() -> None:
    # source_type routing still applies, but a large non-filing doc stays on primary.
    assert _route("eodhd", 100000, threshold=0).high_recall is False
    assert _route("sec_edgar", 10, threshold=0).high_recall is True


def test_none_and_blank_source_type_route_by_word_count_only() -> None:
    assert _route(None, 500).high_recall is False
    assert _route(None, 6000).high_recall is True
    assert _route("   ", 6000).high_recall is True


def test_parse_source_types_normalises_and_drops_blanks() -> None:
    assert parse_source_types("sec_edgar, SEC_10K , ,tenant_upload") == frozenset(
        {"sec_edgar", "sec_10k", "tenant_upload"}
    )
    assert parse_source_types("") == frozenset()
