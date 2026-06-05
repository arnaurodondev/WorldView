"""ML-client Prometheus metrics for rag-chat.

This module wires the ``observability.metrics.MLMetrics`` family into rag-chat
so the Grafana dashboard ``rag-chat.json`` panels ("ML latency p95", "ML API
request rate", "ML API estimated cost 24h") render real series.

WHY a dedicated module
----------------------
The ml-clients library adapters (e.g. ``JinaEmbeddingAdapter`` in
``libs/ml-clients/src/ml_clients/adapters/jina_embedding.py``) accept an
optional ``metrics: MLMetrics | None`` constructor kwarg.  When ``None``
(the default), every counter / histogram update is silently skipped — which is
exactly what was happening for rag-chat before this module existed.

The metric attribute names the adapters look up
(``ml_api_requests_total``, ``ml_api_latency_seconds``,
``ml_api_tokens_in_total``, ``ml_api_tokens_out_total``,
``ml_api_estimated_cost_usd_total``) are produced by
``observability.metrics.create_ml_metrics(service_name)`` with the right
namespace prefix.  Passing ``service_name="rag-chat"`` yields metric names
``rag_chat_ml_api_*`` — matching the Grafana dashboard queries.

Labels exposed
--------------
- ``ml_api_requests_total``: ``model_id, operation, status``
- ``ml_api_latency_seconds``: ``model_id, operation``
- ``ml_api_tokens_in_total`` / ``ml_api_tokens_out_total``: ``model_id``
- ``ml_api_estimated_cost_usd_total``: ``model_id``

NOTE on the dashboard's "model" label
-------------------------------------
The dashboard JSON uses ``{{ model_id }}`` in legend formats and
``sum by (model_id, ...)`` in queries — which matches the observability
library's label name exactly.  No translation is needed.

Singleton semantics
-------------------
``observability.metrics.create_ml_metrics`` is itself idempotent for the
global registry (keyed by ``service_name``), so multiple invocations return
the same ``MLMetrics`` instance.  We still cache it here at module level so
all adapter wiring in ``app.py`` shares one reference and tests can substitute
an isolated-registry fixture easily.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Import the shared ML metrics factory + dataclass from the observability lib.
# These metrics are registered on the default prometheus_client global REGISTRY
# (or an explicit one in tests) so `/metrics` exposition picks them up.
from observability.metrics import MLMetrics, create_ml_metrics  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry


# Cache the per-process singleton so repeated calls from app.py / tests return
# the same MLMetrics instance.  Keyed on service_name so test fixtures using
# alternative names are also safe (matches observability lib semantics).
_singleton: MLMetrics | None = None


def build_ml_metrics(
    service_name: str = "rag-chat",
    registry: CollectorRegistry | None = None,
) -> MLMetrics:
    """Build (or return the cached) ``MLMetrics`` instance for rag-chat.

    Args:
        service_name: Namespace prefix; default ``"rag-chat"`` produces metrics
            named ``rag_chat_ml_api_*`` (hyphens become underscores in the
            Prometheus namespace, per the observability lib convention).
        registry: Optional Prometheus registry; defaults to the global one.
            Tests pass an isolated ``CollectorRegistry()`` to avoid duplicate
            registration errors between modules.

    Returns:
        The shared ``MLMetrics`` dataclass.  Adapters that accept a
        ``metrics=`` kwarg will look up ``ml_api_requests_total``,
        ``ml_api_latency_seconds``, etc. on this object.
    """
    # When a custom registry is provided (typically in tests), we deliberately
    # bypass the singleton cache: tests want isolated registries per case to
    # avoid label-cardinality leakage and "duplicate timeseries" errors.
    if registry is not None:
        return create_ml_metrics(service_name, registry=registry)

    global _singleton
    if _singleton is None:
        _singleton = create_ml_metrics(service_name)
    return _singleton


__all__ = ["MLMetrics", "build_ml_metrics"]
