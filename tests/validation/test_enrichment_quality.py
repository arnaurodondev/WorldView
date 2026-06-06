"""T-G-1-04: Enrichment + embedding SLO test (PLAN-0093 Wave G-1).

Audit refs: F-DB-005, F-REF-003, F-REF-004, F-REF-005, F-DB-ENRICHMENT-001.

These tests assert the post-remediation steady-state for entity enrichment
and the three-view embedding pipeline:

* The provisional-enrichment loop is actively advancing (24h attempt counter
  must be > 0; ``F-DB-ENRICHMENT-001`` was triggered by a frozen counter).
* Definition + narrative embedding coverage ≥ 95% (≤ 5% NULL).
* Fundamentals/OHLCV embedding coverage ≥ 80% on equity entities only
  (Wave C-4-03 reduced this scope to financial instruments — non-equities
  no longer get fundamentals rows at all per migration 0003).
* ``canonical_entities.description`` coverage ≥ 90% on company-shaped entities
  (organization, financial_instrument). Pre-remediation the
  DefinitionRefreshWorker was silently failing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.validation.conftest import scalar

if TYPE_CHECKING:  # pragma: no cover
    import psycopg


def test_enrichment_attempts_counter_advances(intelligence_db_conn: psycopg.Connection) -> None:
    """At least one canonical_entities row must have been enriched in the last 24h.

    Audit ref: F-DB-ENRICHMENT-001. The original audit observed 1,790 of 5,230
    canonical_entities (34%) with ``enriched_at IS NULL`` AND every row at
    ``enrichment_attempts=0`` — proof the StructuredEnrichmentWorker was
    silently dead. A live worker must move ``enriched_at`` forward continuously,
    so a 24h window with zero updates means the worker has stalled (claim loop
    empty, exponential-backoff bug, or queue-side deadlock).

    We query ``canonical_entities.enriched_at`` directly because that column is
    the authoritative SLO target (per F-DB-ENRICHMENT-001). The earlier draft
    of this test queried a queue-side table on a non-existent ``updated_at``
    column, which fails at SQL parse time and silently bypassed the SLO.
    """
    advanced = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM canonical_entities " "WHERE enriched_at >= now() - interval '24 hours'",
        )
        or 0
    )
    assert advanced > 0, (
        "No canonical_entities rows had enriched_at advanced in the last 24h. "
        "StructuredEnrichmentWorker appears dead — F-DB-ENRICHMENT-001 regression."
    )


def test_definition_embedding_coverage(intelligence_db_conn: psycopg.Connection) -> None:
    """≤ 5% of ``view_type='definition'`` rows may have NULL ``embedding``.

    Audit ref: F-REF-003. The EmbeddingRefreshWorker should keep this near
    zero in steady state; a high NULL ratio means the worker is throttled
    or the embedding provider is failing.
    """
    total = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM entity_embedding_state WHERE view_type = 'definition'",
        )
        or 0
    )
    if total == 0:
        pytest.skip("no entity_embedding_state rows with view_type=definition")
    null_count = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM entity_embedding_state " "WHERE view_type = 'definition' AND embedding IS NULL",
        )
        or 0
    )
    ratio = null_count / total
    assert ratio <= 0.05, (
        f"definition embedding NULL ratio = {ratio:.2%} ({null_count}/{total}); "
        "expected ≤ 5%. EmbeddingRefreshWorker is backlogged or upstream is failing."
    )


def test_narrative_embedding_coverage(intelligence_db_conn: psycopg.Connection) -> None:
    """≤ 5% of ``view_type='narrative'`` rows may have NULL ``embedding``.

    Audit ref: F-REF-004. Same rationale as definition; narrative is the
    weekly-refresh view.
    """
    total = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM entity_embedding_state WHERE view_type = 'narrative'",
        )
        or 0
    )
    if total == 0:
        pytest.skip("no entity_embedding_state rows with view_type=narrative")
    null_count = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM entity_embedding_state " "WHERE view_type = 'narrative' AND embedding IS NULL",
        )
        or 0
    )
    ratio = null_count / total
    assert ratio <= 0.05, (
        f"narrative embedding NULL ratio = {ratio:.2%} ({null_count}/{total}); "
        "expected ≤ 5%. NarrativeRefreshWorker is backlogged."
    )


def test_fundamentals_ohlcv_embedding_coverage(intelligence_db_conn: psycopg.Connection) -> None:
    """≥ 80% of equity entities must have a non-NULL fundamentals_ohlcv embedding.

    Audit ref: F-REF-005. Per migration 0003 (cleanup_non_company_fundamentals_ohlcv)
    only ``financial_instrument`` entities should have a fundamentals row at
    all. The SLO targets equities specifically because they're the only ones
    where fundamentals semantically apply.
    """
    total = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM entity_embedding_state ees "
            "JOIN canonical_entities ce ON ce.entity_id = ees.entity_id "
            "WHERE ees.view_type = 'fundamentals_ohlcv' "
            "AND ce.entity_type = 'financial_instrument'",
        )
        or 0
    )
    if total == 0:
        pytest.skip("no financial_instrument fundamentals_ohlcv rows — nothing to assert")
    with_embed = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM entity_embedding_state ees "
            "JOIN canonical_entities ce ON ce.entity_id = ees.entity_id "
            "WHERE ees.view_type = 'fundamentals_ohlcv' "
            "AND ce.entity_type = 'financial_instrument' "
            "AND ees.embedding IS NOT NULL",
        )
        or 0
    )
    ratio = with_embed / total
    assert ratio >= 0.80, (
        f"fundamentals_ohlcv embedding coverage = {ratio:.2%} ({with_embed}/{total}); "
        "expected ≥ 80% on financial_instrument entities. FundamentalsRefreshWorker "
        "is starved or upstream OHLCV ingestion is incomplete."
    )


def test_description_coverage_for_company_entities(
    intelligence_db_conn: psycopg.Connection,
) -> None:
    """≤ 10% of organization / financial_instrument entities may have NULL description.

    Audit ref: F-DB-005. Pre-remediation ~3,440 organisation rows had NULL
    descriptions and the dashboard rendered blank cards. Wave C-4-02
    backfilled these and the DefinitionRefreshWorker is responsible for
    keeping the share low going forward.
    """
    total = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM canonical_entities " "WHERE entity_type IN ('organization', 'financial_instrument')",
        )
        or 0
    )
    if total == 0:
        pytest.skip("no organization / financial_instrument entities — nothing to assert")
    null_count = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM canonical_entities "
            "WHERE entity_type IN ('organization', 'financial_instrument') "
            "AND description IS NULL",
        )
        or 0
    )
    ratio = null_count / total
    assert ratio <= 0.10, (
        f"description NULL ratio = {ratio:.2%} ({null_count}/{total}) on company entities; "
        "expected ≤ 10%. DefinitionRefreshWorker is starved or upstream description "
        "provider (Gemini Flash Lite) is failing."
    )
