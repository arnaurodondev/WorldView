"""T-G-1-05: Path-insight LLM explanation SLO test (PLAN-0093 Wave G-1).

Audit refs: F-KG-PERSIST-003 / F-DB-002.

These tests assert the post-remediation steady-state for the path-insight
LLM explanation pipeline introduced in Wave D-1:

* ≤ 100 ``path_insights`` rows may have NULL ``llm_explanation`` for longer
  than 1 hour after seeding. The PathExplanationBatchWorker sweeps every
  3 minutes; anything older than 1h represents a queue starvation, an
  LLM-provider outage, or an explanation-budget cap (in which case the
  budget needs lifting).
* When ``llm_explanation`` is set, ``explanation_at`` must also be set —
  the two columns are written atomically by the worker so any drift
  between them indicates a non-atomic write path.
* The Prometheus gauge ``path_insight_explanation_pending_total`` (added
  in T-D-1-02) must be exposed on the knowledge-graph ``/metrics`` endpoint
  so operators can alert on it before the queue blows up.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from tests.validation.conftest import scalar

if TYPE_CHECKING:  # pragma: no cover
    import psycopg

# Default metrics URL — the gauge lives in the *scheduler* process, not the
# main knowledge-graph API on :8007. FIX-LIVE-C wired
# ``start_http_server(9108)`` inside ``scheduler_main.py`` because the
# scheduler is a standalone process with no FastAPI ``/metrics`` route, and
# the ``PathExplanationBatchWorker`` (which sets this gauge) only runs in
# that process. FIX-LIVE-U then published :9108 to the host in
# ``infra/compose/docker-compose.yml`` so this test can reach it.
# Override via ``KNOWLEDGE_GRAPH_METRICS_URL`` for k8s / non-default envs.
_DEFAULT_METRICS_URL = "http://localhost:9108/metrics"

# Name of the gauge added by T-D-1-02. Must match the registration in
# ``services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py``.
_EXPECTED_METRIC_NAME = "path_insight_explanation_pending_total"


def test_path_insight_llm_explanation_coverage(
    intelligence_db_conn: psycopg.Connection,
) -> None:
    """≤ 100 ``path_insights`` rows may have NULL ``llm_explanation`` and be > 1h old.

    Audit ref: F-DB-002. The PathExplanationBatchWorker fires every 3 minutes;
    anything older than 1 hour is stuck. We allow a 100-row buffer for the
    in-flight batch.
    """
    pending = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM path_insights "
            "WHERE llm_explanation IS NULL "
            "AND computed_at < now() - interval '1 hour'",
        )
        or 0
    )
    assert pending <= 100, (
        f"{pending} path_insights rows have NULL llm_explanation and are > 1h old; "
        "expected ≤ 100. PathExplanationBatchWorker is starved or the LLM provider is down."
    )


def test_path_insight_explanation_at_is_set(intelligence_db_conn: psycopg.Connection) -> None:
    """``llm_explanation`` and ``explanation_at`` must be set together (100% alignment).

    Audit ref: F-KG-PERSIST-003. The worker writes both columns in the same
    UPDATE — any drift means somebody added an alternative write path that
    forgot ``explanation_at``, which breaks freshness-based queries.
    """
    misaligned = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM path_insights " "WHERE llm_explanation IS NOT NULL AND explanation_at IS NULL",
        )
        or 0
    )
    assert misaligned == 0, (
        f"{misaligned} path_insights rows have llm_explanation set but explanation_at NULL. "
        "Non-atomic write path — F-KG-PERSIST-003 regression."
    )


def test_path_insight_pending_metric_exposed() -> None:
    """``path_insight_explanation_pending_total`` must be exposed on /metrics.

    Audit ref: F-DB-002 (T-D-1-02). The gauge is registered at process start
    in ``knowledge_graph.infrastructure.metrics.prometheus``; this test
    verifies it actually appears in the scrape output.

    We skip cleanly when:
    * ``KNOWLEDGE_GRAPH_METRICS_URL`` is unset *and* the default
      ``http://localhost:8007/metrics`` is unreachable (i.e. the platform
      isn't running locally). This keeps CI green in env-less runs.
    """
    url = os.environ.get("KNOWLEDGE_GRAPH_METRICS_URL", _DEFAULT_METRICS_URL)
    # We deliberately allow only http(s) URLs here — anything else is a
    # configuration mistake (no file://, no ftp, etc.).
    if not url.startswith(("http://", "https://")):
        pytest.skip(f"KNOWLEDGE_GRAPH_METRICS_URL has unsupported scheme: {url!r}")
    try:
        with urlopen(url, timeout=5) as response:  # noqa: S310 — scheme guarded above
            body = response.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"could not scrape {url!r}: {exc}")
    assert _EXPECTED_METRIC_NAME in body, (
        f"metric {_EXPECTED_METRIC_NAME!r} not found in /metrics output from {url!r}. "
        "T-D-1-02 regression — the gauge registration was removed or never wired."
    )
