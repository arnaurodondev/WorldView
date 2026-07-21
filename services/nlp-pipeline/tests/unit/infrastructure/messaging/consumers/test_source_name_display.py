"""Regression tests for ISSUE-B / R7: source_name derivation from source_type.

The ``content.article.stored.v1`` event carries no ``source_name`` field, so the
S6 consumer used to write ``document_source_metadata.source_name = NULL`` for
100% of rows (docs/audits/2026-07-16-kg-data-quality-eval.md R7: 15,325/15,325
empty after the news backfill). ``_display_source_name`` derives a human-readable
label from the canonical ``source_type`` so the column is always populated for a
known source.
"""

from __future__ import annotations

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    _display_source_name,
)

pytestmark = pytest.mark.unit


@pytest.mark.unit
class TestDisplaySourceName:
    @pytest.mark.parametrize(
        ("source_type", "expected"),
        [
            ("eodhd", "EODHD"),
            ("eodhd_ticker_news", "EODHD"),
            ("finnhub", "Finnhub"),
            ("newsapi", "NewsAPI"),
            ("sec_edgar", "SEC EDGAR"),
            ("polymarket", "Polymarket"),
            ("manual", "Manual Upload"),
            ("tenant_upload", "Tenant Upload"),
        ],
    )
    def test_known_source_types_map_to_display_labels(self, source_type: str, expected: str) -> None:
        assert _display_source_name(source_type) == expected

    def test_unknown_source_type_falls_back_to_title_case(self) -> None:
        # Forward-compat: a future adapter still gets a readable, non-NULL label.
        assert _display_source_name("some_new_feed") == "Some New Feed"

    @pytest.mark.parametrize("blank", [None, ""])
    def test_blank_source_type_returns_none(self, blank: str | None) -> None:
        # Nothing to label → None (the column stays NULL only when source_type is).
        assert _display_source_name(blank) is None
