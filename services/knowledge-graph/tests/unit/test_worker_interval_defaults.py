"""Regression guard for FIX-LIVE-GG worker-scheduler defaults (INV-LIVE-GG).

Background:
    iter-5 SLO failures (``test_summary_coverage`` 7%, ``test_definition_
    embedding_coverage`` 10%, ``test_fundamentals_ohlcv_embedding_coverage``
    0/2405) traced back to over-long worker cadences (3600 s / 7200 s /
    10 800 s) in ``knowledge_graph.config.Settings``.  FIX-LIVE-GG lowered
    them to 600 s / 300 s / 300 s and raised the embedding batch limit
    default from 0 to 200.  This test pins those defaults so a future
    refactor cannot silently regress them.

R38 (boot-time defaults must match docker.env) — see
``docs/audits/2026-05-25-iter-5-results-and-closeout.md`` section
INV-LIVE-GG for the audit trail.
"""

from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.unit


def _make_settings() -> object:
    """Construct ``Settings()`` with the bare minimum of required env vars.

    The Settings class fails fast on missing ``KNOWLEDGE_GRAPH_DATABASE_URL``
    (DEF-001) and ``KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY`` / ``..._SECRET_KEY``.
    We don't care about the values — only the integer defaults — so we
    inject placeholders just to satisfy the validator.
    """
    from knowledge_graph.config import Settings

    # Inject required env vars only for the duration of this constructor
    # call.  Done via monkeypatched os.environ rather than ``BaseSettings``
    # kwargs to mirror real production behaviour.
    saved: dict[str, str | None] = {}
    for key, value in (
        ("KNOWLEDGE_GRAPH_DATABASE_URL", "postgresql+asyncpg://x:x@x/x"),
        ("KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY", "x"),
        ("KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY", "x"),
    ):
        saved[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        # type: ignore[call-arg] — pydantic-settings populates from env.
        return Settings()  # type: ignore[call-arg]
    finally:
        for key, original in saved.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


class TestWorkerIntervalDefaults:
    """Pin the FIX-LIVE-GG cadences so they cannot silently regress."""

    def test_summary_interval_default_is_600s(self) -> None:
        """SummaryWorker cadence — was 3600s, lowered to 600s by FIX-LIVE-GG."""
        s = _make_settings()
        assert s.worker_summary_interval_s == 600, (  # type: ignore[attr-defined]
            "SummaryWorker default cadence regressed from 600s — "
            "see FIX-LIVE-GG / INV-LIVE-GG cluster 2 audit trail."
        )

    def test_embedding_refresh_interval_default_is_300s(self) -> None:
        """EmbeddingRefreshWorker cadence — was 10800s, lowered to 300s."""
        s = _make_settings()
        assert s.worker_embedding_refresh_interval_s == 300, (  # type: ignore[attr-defined]
            "EmbeddingRefreshWorker default cadence regressed from 300s — "
            "see FIX-LIVE-GG / INV-LIVE-GG cluster 2 audit trail."
        )

    def test_fundamentals_refresh_interval_default_is_300s(self) -> None:
        """FundamentalsRefreshWorker cadence — was 7200s, lowered to 300s."""
        s = _make_settings()
        assert s.worker_fundamentals_refresh_interval_s == 300, (  # type: ignore[attr-defined]
            "FundamentalsRefreshWorker default cadence regressed from 300s — "
            "see FIX-LIVE-GG / INV-LIVE-GG cluster 2 audit trail."
        )

    def test_embedding_batch_limit_default_is_200(self) -> None:
        """EmbeddingRefresh batch ceiling — was 0 (unlimited), set to 200.

        Matches the DeepInfra single-call ceiling so a cycle issues at most
        one batched embed call.  Keeps the asyncio loop responsive for the
        other 4 LLM-bound workers in the same scheduler.
        """
        s = _make_settings()
        assert s.worker_embedding_batch_limit == 200, (  # type: ignore[attr-defined]
            "Embedding batch ceiling regressed from 200 — see FIX-LIVE-GG."
        )


class TestPriceImpactRetryBackoff:
    """Pin the MarketDataClient JWT-mint retry schedule (cluster 1)."""

    def test_mint_retry_delays_match_audit(self) -> None:
        """5s/15s/45s exponential backoff (4 attempts incl. immediate first)."""
        # Cross-service import: nlp-pipeline may not be installed in this venv.
        import pytest as _pt

        _pt.importorskip("nlp_pipeline.infrastructure.http.market_data_client")
        from nlp_pipeline.infrastructure.http.market_data_client import (
            _TOKEN_MINT_RETRY_DELAYS,
        )

        # First attempt fires immediately (0.0); remaining three back off
        # exponentially.  Total grace window ≈ 65s (matches api-gateway
        # ``start_period: 45s`` + a generous margin).
        assert _TOKEN_MINT_RETRY_DELAYS == (0.0, 5.0, 15.0, 45.0), (
            "MarketDataClient JWT-mint retry schedule regressed from "
            "(0, 5, 15, 45)s — see FIX-LIVE-GG / INV-LIVE-GG cluster 1."
        )


# ---------------------------------------------------------------------------
# SecretStr import is referenced from the docstring above; keep the import
# explicit so type checkers don't strip it.  (Pydantic raises at module load
# if SecretStr is removed from public API.)
# ---------------------------------------------------------------------------
_ = SecretStr
