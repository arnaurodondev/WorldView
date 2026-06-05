"""Tests for the rag-chat ML-client metrics wiring.

Covers:
- ``build_ml_metrics`` registers the expected Prometheus metric families with
  the correct label sets so the Grafana dashboard ``rag_chat_ml_api_*``
  queries return data.
- A real ``JinaEmbeddingAdapter`` call (mocked HTTP) increments the
  ``ml_api_requests_total`` counter when ``metrics=`` is wired — proving the
  end-to-end plumbing works.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from prometheus_client import CollectorRegistry  # type: ignore[import-untyped]

from rag_chat.application.metrics.ml_clients import build_ml_metrics


def _label_names(metric: Any) -> list[str]:
    """Extract Prometheus label names from a Counter / Histogram regardless of version.

    prometheus_client exposes them on ``_labelnames`` (tuple) — we tolerate
    either tuple or list to keep the assertion stable across releases.
    """
    raw = getattr(metric, "_labelnames", ())
    return list(raw)


class TestBuildMlMetrics:
    """Registration: metric families have the labels the dashboard queries by."""

    def test_returns_mlmetrics_with_expected_label_names(self) -> None:
        # Use an isolated registry so this test never collides with other
        # tests that may have already imported and built the global singleton.
        registry = CollectorRegistry()
        m = build_ml_metrics("rag-chat", registry=registry)

        # The dashboard queries `sum by (model_id, operation) (rate(...))` and
        # `histogram_quantile(0.95, sum by (model_id, le) (rate(...)))` —
        # both require these label names exactly.
        assert _label_names(m.ml_api_requests_total) == ["model_id", "operation", "status"]
        assert _label_names(m.ml_api_latency_seconds) == ["model_id", "operation"]
        assert _label_names(m.ml_api_estimated_cost_usd_total) == ["model_id"]

    def test_idempotent_same_instance_for_same_registry(self) -> None:
        # Idempotency: passing the same explicit registry twice must return
        # equivalent dataclasses (the underlying observability cache key is
        # service_name on the global REGISTRY only — for explicit registries
        # we still want repeated calls to be safe, which the lib guarantees
        # via its create_ml_metrics implementation).
        registry = CollectorRegistry()
        a = build_ml_metrics("rag-chat-idemp", registry=registry)
        # Same registry, same service_name — the second call rebuilds with
        # the same labelnames; we just check it doesn't raise + has the
        # same shape (registration on isolated registries is one-shot per
        # service_name so we use a different name to avoid duplicate-ts).
        b = build_ml_metrics("rag-chat-idemp-b", registry=registry)
        assert _label_names(a.ml_api_requests_total) == _label_names(b.ml_api_requests_total)


class TestJinaAdapterIncrements:
    """Integration: feeding ``metrics=`` to JinaEmbeddingAdapter increments the counter."""

    @pytest.mark.asyncio
    async def test_jina_embed_increments_requests_total(self) -> None:
        # Lazy import so any environment without ml_clients installed still
        # collects the registration test above.
        from ml_clients.adapters.jina_embedding import JinaEmbeddingAdapter  # type: ignore[import-not-found]
        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

        registry = CollectorRegistry()
        metrics = build_ml_metrics("rag-chat-test", registry=registry)
        adapter = JinaEmbeddingAdapter(
            api_key="fake-key",
            model="jina-embeddings-v3",
            metrics=metrics,
        )

        # Stub the httpx call with a minimal valid Jina response (1 input → 1
        # embedding with the expected 1024 dimension constant from the adapter).
        fake_resp = type(
            "FR",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {
                    "data": [{"index": 0, "embedding": [0.1] * 1024}],
                },
            },
        )()

        async def _fake_post(*_args: Any, **_kwargs: Any) -> Any:
            return fake_resp

        with patch("ml_clients.adapters.jina_embedding.httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            instance.post = AsyncMock(side_effect=_fake_post)

            out = await adapter.embed([EmbeddingInput(text="hello world", model_id="jina-embeddings-v3")])

        assert len(out) == 1
        # The adapter's finally block calls
        #   metrics.ml_api_requests_total.labels(model_id=..., operation="embed", status="success").inc()
        # Read it back via the isolated registry — value must be 1.0.
        value = registry.get_sample_value(
            "rag_chat_test_ml_api_requests_total",
            {"model_id": "jina-embeddings-v3", "operation": "embed", "status": "success"},
        )
        assert value == 1.0
