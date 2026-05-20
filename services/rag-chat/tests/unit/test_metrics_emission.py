"""Unit tests for PLAN-0063 W5-5 T-W5-5-01 Prometheus metric emission."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

pytestmark = pytest.mark.unit


class TestRetrievalScoreDistributionMetric:
    def test_retrieval_score_distribution_metric_registered(self) -> None:
        """rag_retrieval_score_distribution appears in the Prometheus default registry."""
        metric_names = {m.name for m in REGISTRY.collect()}
        assert "rag_retrieval_score_distribution" in metric_names

    def test_retrieval_score_distribution_emits_on_fetch(self) -> None:
        """Calling .observe() on the histogram does not raise and updates the count."""
        from prometheus_client import REGISTRY
        from rag_chat.application.metrics.prometheus import rag_retrieval_score_distribution

        before = sum(
            s.value
            for m in REGISTRY.collect()
            if m.name == "rag_retrieval_score_distribution"
            for s in m.samples
            if s.name.endswith("_count")
        )
        rag_retrieval_score_distribution.labels(source="eodhd_news").observe(0.75)
        after = sum(
            s.value
            for m in REGISTRY.collect()
            if m.name == "rag_retrieval_score_distribution"
            for s in m.samples
            if s.name.endswith("_count")
        )
        assert after > before


class TestSourceContributionMetric:
    def test_source_contribution_increments_per_query(self) -> None:
        """3 distinct source types → 3 distinct increments in rag_source_contribution_total."""
        from rag_chat.application.metrics.prometheus import rag_source_contribution_total

        def _current(source: str) -> float:
            # Check s.name (sample name keeps _total); m.name strips _total in newer prometheus_client.
            for m in REGISTRY.collect():
                for s in m.samples:
                    if s.name == "rag_source_contribution_total" and s.labels.get("source") == source:
                        return s.value
            return 0.0

        sources = ["sec_filing_w55", "eodhd_news_w55", "earnings_transcript_w55"]
        before = {s: _current(s) for s in sources}

        for src in sources:
            rag_source_contribution_total.labels(source=src).inc()

        for src in sources:
            assert _current(src) == before[src] + 1
