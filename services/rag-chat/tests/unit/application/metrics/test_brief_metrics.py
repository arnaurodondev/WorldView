"""Smoke tests for the 6 PLAN-0094 W2 brief pre-generation metrics.

These are simple registration tests: import the metric, verify it has the right
type and labels.  Behavioural tests live in the worker / handler test modules
(``test_morning_brief_pregeneration_worker.py`` and ``test_public_briefings.py``).
"""

from __future__ import annotations

import pytest
from prometheus_client import Counter, Gauge, Histogram

pytestmark = pytest.mark.unit


def test_all_brief_metrics_registered() -> None:
    """All 6 W2 metrics are importable from the canonical metrics module."""
    from rag_chat.application.metrics.prometheus import (
        rag_brief_pregeneration_eligible_users,
        rag_brief_pregeneration_run_duration_seconds,
        rag_brief_pregeneration_runs_total,
        rag_brief_pregeneration_user_duration_seconds,
        rag_brief_pregeneration_users_total,
        rag_brief_served_stale_total,
    )

    # ── Types ─────────────────────────────────────────────────────────────────
    # WHY check the concrete prometheus-client class: catches accidental import
    # of a wrong metric (e.g. a developer pastes a Gauge where a Counter belongs).
    assert isinstance(rag_brief_pregeneration_runs_total, Counter)
    assert isinstance(rag_brief_pregeneration_users_total, Counter)
    assert isinstance(rag_brief_pregeneration_run_duration_seconds, Histogram)
    assert isinstance(rag_brief_pregeneration_user_duration_seconds, Histogram)
    assert isinstance(rag_brief_pregeneration_eligible_users, Gauge)
    assert isinstance(rag_brief_served_stale_total, Counter)

    # ── Labels ────────────────────────────────────────────────────────────────
    # ``_labelnames`` is the public-but-undocumented attribute prometheus-client
    # exposes for inspection.  We pin the exact label names so a future rename
    # breaks the test loudly.
    assert rag_brief_pregeneration_runs_total._labelnames == ("status",)
    assert rag_brief_pregeneration_users_total._labelnames == ("outcome",)
    assert rag_brief_pregeneration_run_duration_seconds._labelnames == ()
    assert rag_brief_pregeneration_user_duration_seconds._labelnames == ()
    assert rag_brief_pregeneration_eligible_users._labelnames == ()
    assert rag_brief_served_stale_total._labelnames == ()


def test_brief_metrics_accept_documented_labels() -> None:
    """Verify the 3 documented status / outcome labels can be applied without error."""
    from rag_chat.application.metrics.prometheus import (
        rag_brief_pregeneration_runs_total,
        rag_brief_pregeneration_users_total,
    )

    # status labels — exercised by the worker on run start/complete/fail.
    rag_brief_pregeneration_runs_total.labels(status="started")
    rag_brief_pregeneration_runs_total.labels(status="completed")
    rag_brief_pregeneration_runs_total.labels(status="failed")

    # outcome labels — exercised per user.
    rag_brief_pregeneration_users_total.labels(outcome="success")
    rag_brief_pregeneration_users_total.labels(outcome="generation_failed")
    rag_brief_pregeneration_users_total.labels(outcome="skipped_stale_kept")
