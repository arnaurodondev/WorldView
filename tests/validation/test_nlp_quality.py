"""T-G-1-03: NLP data-quality SLO test (PLAN-0093 Wave G-1).

Audit refs: F-NPL-005, F-NPL-006, F-NPL-008, F-DB-004, F-DB-008, F-DB-010.

These tests assert on the integrity of NLP pipeline output after the Wave C
remediation:

* No sub-floor mentions persisted (``entity_mentions.score`` must respect the
  ``min_persist_floor`` settings cutoff — Wave C-2 fix).
* No NULL tenant_id (multi-tenant invariant).
* ``document_source_metadata.impact_score`` is being populated by the
  windower (Wave C-3 fix).
* ``article_impact_windows`` has rows (Wave C-3 backfill).
* LLM relevance score lag ≤ 5% of recent metadata rows (otherwise the
  ArticleRelevanceScoringWorker is backlogged).
* ``relation_evidence_raw.claim_id`` and ``.chunk_id`` are never NULL
  (Wave C-1 fix — they were being dropped on the wire pre-remediation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.validation.conftest import scalar

if TYPE_CHECKING:  # pragma: no cover
    import psycopg

# Minimum persistence floor — see ``nlp_pipeline.config.Settings.min_persist_floor``.
# The default in code is 0.6; the assertion checks that no mention below this
# floor was persisted. If the platform changes the floor, update this constant
# in lockstep with the config.
MIN_PERSIST_FLOOR = 0.6


def test_zero_sub_floor_entity_mentions(nlp_db_conn: psycopg.Connection) -> None:
    """No ``entity_mentions`` row may have ``score < min_persist_floor``.

    Audit ref: F-NPL-005. Wave C-2 added a defence-in-depth filter in
    ``persist.py`` that drops sub-floor mentions before the INSERT. This test
    is the regression guard: any sub-floor row in the DB means the filter is
    being bypassed (e.g. by a different ingestion path).
    """
    bad_count = int(
        scalar(
            nlp_db_conn,
            # F-LIVE-005 (Phase 5c, 2026-05-24): column is `confidence`, not `score`.
            # The audit referenced "GLiNER score" colloquially but the schema column
            # added by migration 0001 is `confidence DOUBLE PRECISION NOT NULL`.
            "SELECT count(*) FROM entity_mentions WHERE confidence < %(floor)s",
            {"floor": MIN_PERSIST_FLOOR},
        )
        or 0
    )
    assert bad_count == 0, (
        f"Found {bad_count} entity_mentions with score < {MIN_PERSIST_FLOOR}. "
        "Sub-floor mentions are being persisted — F-NPL-005 regression."
    )


def test_zero_null_tenant_id_in_mentions(nlp_db_conn: psycopg.Connection) -> None:
    """``entity_mentions.tenant_id`` must never be NULL.

    Audit ref: F-NPL-006. Multi-tenant invariant: any row without a tenant
    leaks across tenants in user-facing queries.
    """
    null_count = int(scalar(nlp_db_conn, "SELECT count(*) FROM entity_mentions WHERE tenant_id IS NULL") or 0)
    assert null_count == 0, (
        f"Found {null_count} entity_mentions with NULL tenant_id. "
        "Multi-tenant invariant broken — F-NPL-006 regression."
    )


def test_impact_score_populated(nlp_db_conn: psycopg.Connection) -> None:
    """≥ 30% of ``document_source_metadata`` rows older than 24h must have ``impact_score``.

    Audit ref: F-NPL-008. The ImpactScoreWriter (Wave C-3) populates
    ``impact_score`` once the day_t1 window closes (~24h after publication).
    A persistent low ratio means the writer is silently failing — historically
    this was the case because it was wired to the wrong topic.
    """
    total_old = int(
        scalar(
            nlp_db_conn,
            "SELECT count(*) FROM document_source_metadata " "WHERE created_at < now() - interval '24 hours'",
        )
        or 0
    )
    if total_old == 0:
        pytest.skip("no document_source_metadata rows older than 24h — nothing to assert")
    with_score = int(
        scalar(
            nlp_db_conn,
            "SELECT count(*) FROM document_source_metadata "
            "WHERE created_at < now() - interval '24 hours' "
            "AND impact_score IS NOT NULL",
        )
        or 0
    )
    ratio = with_score / total_old
    assert ratio >= 0.30, (
        f"impact_score coverage = {ratio:.2%} ({with_score}/{total_old}); "
        "expected ≥ 30% for rows older than 24h. ImpactScoreWriter is broken (F-NPL-008)."
    )


def test_article_impact_windows_populated(nlp_db_conn: psycopg.Connection) -> None:
    """``article_impact_windows`` must have ≥ 100 rows after 24h of ingestion.

    Audit ref: F-DB-008. Pre-remediation this table was empty (the
    windower wasn't being scheduled). Even a modest live workload should
    produce 100+ window rows per day.
    """
    count = int(scalar(nlp_db_conn, "SELECT count(*) FROM article_impact_windows") or 0)
    assert count >= 100, (
        f"article_impact_windows has only {count} rows; expected ≥ 100. "
        "Windower job is not running or not committing — F-DB-008 regression."
    )


def test_llm_relevance_score_lag(nlp_db_conn: psycopg.Connection) -> None:
    """≤ 5% of ``document_source_metadata`` (last 24h) may have NULL ``llm_relevance_score``.

    Audit ref: F-DB-010. The ArticleRelevanceScoringWorker scores every
    article within minutes of publish — a NULL ratio above 5% means the
    worker is backlogged or the LLM provider is failing silently.
    """
    total_recent = int(
        scalar(
            nlp_db_conn,
            "SELECT count(*) FROM document_source_metadata " "WHERE created_at >= now() - interval '24 hours'",
        )
        or 0
    )
    if total_recent == 0:
        pytest.skip("no document_source_metadata rows in the last 24h — nothing to assert")
    null_count = int(
        scalar(
            nlp_db_conn,
            "SELECT count(*) FROM document_source_metadata "
            "WHERE created_at >= now() - interval '24 hours' "
            "AND llm_relevance_score IS NULL",
        )
        or 0
    )
    ratio = null_count / total_recent
    assert ratio <= 0.05, (
        f"llm_relevance_score NULL ratio = {ratio:.2%} ({null_count}/{total_recent}); "
        "expected ≤ 5% over the last 24h. ArticleRelevanceScoringWorker is backlogged."
    )


def test_relation_evidence_raw_has_claim_id(intelligence_db_conn: psycopg.Connection) -> None:
    """``relation_evidence_raw.claim_id`` must never be NULL.

    Audit ref: F-DB-004. Pre-remediation the NLP→KG pipeline dropped the
    claim_id on the wire (the Avro schema had a default of NULL). Without it
    the KG can't link evidence back to the originating claim, which breaks
    contradiction detection.

    NOTE: this is in intelligence_db (the table lives on the KG side after
    PRD-0018), not nlp_db.
    """
    null_count = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM relation_evidence_raw WHERE claim_id IS NULL",
        )
        or 0
    )
    assert null_count == 0, (
        f"Found {null_count} relation_evidence_raw rows with NULL claim_id. "
        "NLP→KG payload is dropping claim_id — F-DB-004 regression."
    )


def test_relation_evidence_raw_has_chunk_id(intelligence_db_conn: psycopg.Connection) -> None:
    """``relation_evidence_raw.chunk_id`` must never be NULL.

    Audit ref: F-DB-004. Same wire-drop problem as claim_id. Without
    chunk_id the platform can't reconstruct the textual context of an
    evidence row for UI rendering.
    """
    null_count = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM relation_evidence_raw WHERE chunk_id IS NULL",
        )
        or 0
    )
    assert null_count == 0, (
        f"Found {null_count} relation_evidence_raw rows with NULL chunk_id. "
        "NLP→KG payload is dropping chunk_id — F-DB-004 regression."
    )
