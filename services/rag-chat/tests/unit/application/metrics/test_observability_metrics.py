"""Unit tests for the PLAN-0093 QA-7 observability metrics added to prometheus.py.

These tests assert the two NEW metric singletons created for the observability
remediation:

- ``rag_no_tool_calls_first_turn_total`` — regression smoke signal (C1)
- ``rag_tool_result_items``               — empty-result quality signal (C2)

Both are module-level singletons registered with the default Prometheus
registry on import. Tests query each via its own ``.collect()`` method (not the
global ``REGISTRY``) so they keep working with the ``isolated_registry`` fixture
that monkeypatches ``prometheus_client.REGISTRY`` away.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestNoToolCallsFirstTurnMetric:
    """C1 — rag_no_tool_calls_first_turn_total."""

    def test_metric_is_registered_with_expected_name(self) -> None:
        """Importing the metric exposes the canonical Prometheus name."""
        from rag_chat.application.metrics.prometheus import rag_no_tool_calls_first_turn

        # ``collect()`` returns one MetricFamily — its name is the registered base
        # name (Prometheus client strips ``_total`` from Counter base names in
        # newer releases; we accept either canonical form).
        names = {m.name for m in rag_no_tool_calls_first_turn.collect()}
        assert names == {"rag_no_tool_calls_first_turn"} or names == {
            "rag_no_tool_calls_first_turn_total"
        }, f"unexpected metric name(s): {names!r}"

    def test_metric_has_provider_label(self) -> None:
        """Provider is the ONLY label (bounded ≤4 by the provider chain)."""
        from rag_chat.application.metrics.prometheus import rag_no_tool_calls_first_turn

        # _labelnames is the prometheus_client internal store of the label tuple.
        # Asserting on it locks the cardinality contract — additional labels
        # (user_id, tenant_id, etc.) would break this test loudly.
        assert tuple(rag_no_tool_calls_first_turn._labelnames) == ("provider",)

    def test_increment_appears_on_collect(self) -> None:
        """A single ``.inc()`` shows up in the metric's own ``.collect()`` samples."""
        from rag_chat.application.metrics.prometheus import rag_no_tool_calls_first_turn

        def _value(provider: str) -> float:
            # Walk the singleton's own samples — independent of REGISTRY identity.
            for m in rag_no_tool_calls_first_turn.collect():
                for s in m.samples:
                    if s.name.endswith("_total") and s.labels.get("provider") == provider:
                        return s.value
            return 0.0

        before = _value("test_provider_for_observability")
        rag_no_tool_calls_first_turn.labels(provider="test_provider_for_observability").inc()
        assert _value("test_provider_for_observability") == before + 1.0


class TestToolResultItemsHistogram:
    """C2 — rag_tool_result_items."""

    def test_metric_is_registered_with_expected_name(self) -> None:
        from rag_chat.application.metrics.prometheus import rag_tool_result_items

        names = {m.name for m in rag_tool_result_items.collect()}
        assert "rag_tool_result_items" in names

    def test_metric_has_tool_name_label_only(self) -> None:
        """Only ``tool_name`` is a label (bounded ≤22 by the tool registry)."""
        from rag_chat.application.metrics.prometheus import rag_tool_result_items

        assert tuple(rag_tool_result_items._labelnames) == ("tool_name",)

    def test_observation_records_count(self) -> None:
        """``.observe(N)`` for a given tool_name appears in the histogram count."""
        from rag_chat.application.metrics.prometheus import rag_tool_result_items

        def _count(tool_name: str) -> float:
            # Histograms expose <name>_count samples per label combination.
            total = 0.0
            for m in rag_tool_result_items.collect():
                for s in m.samples:
                    if s.name.endswith("_count") and s.labels.get("tool_name") == tool_name:
                        total += s.value
            return total

        before = _count("test_tool_for_observability")
        rag_tool_result_items.labels(tool_name="test_tool_for_observability").observe(0)
        rag_tool_result_items.labels(tool_name="test_tool_for_observability").observe(20)
        assert _count("test_tool_for_observability") == before + 2.0
