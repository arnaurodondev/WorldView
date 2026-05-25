"""PRD-0089 F2 §4.3 — provisional enrichment deferral (location note).

The F2 plan filed this test under ``services/nlp-pipeline/tests/``, but the
ProvisionalEnrichmentWorker that owns the provisional → canonical promotion
actually lives in S7 (knowledge-graph): see
``services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py``
and its hot-path Kafka twin ``provisional_queued_consumer.py``.

The deferral logic, the S2 lookup port, the adapter, and the full test
matrix therefore live in S7:

  services/knowledge-graph/src/knowledge_graph/
    application/ports/market_data_lookup_port.py
    infrastructure/http/market_data_lookup_adapter.py
    infrastructure/workers/provisional_enrichment_core.py            (edited)
    infrastructure/workers/provisional_enrichment.py                 (edited)
    infrastructure/messaging/consumers/provisional_queued_consumer.py (edited)

  services/knowledge-graph/tests/unit/infrastructure/workers/
    test_provisional_enrichment_deferral.py                          (added)

This S6 stub exists purely as a navigational signpost — pytest collects no
tests from it (no test_* functions). It does NOT introduce a cross-service
import (R7-safe) and is skipped automatically.
"""

from __future__ import annotations
