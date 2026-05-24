"""T-G-1-02: Relations data-quality SLO test (PLAN-0093 Wave G-1).

Audit refs: F-KG-PERSIST-002, F-DB-001, F-DB-012.

These tests assert the integrity guarantees the relations pipeline must
maintain after the Wave B remediation lands:

* No NULL confidences (every relation must have a 4-step bounded score).
* No orphan FKs (every subject/object_entity_id must resolve to a row in
  ``canonical_entities``).
* Self-loops only on system-sentinel entities (``is_system = true``) —
  user-facing entities must never relate to themselves.
* Confidence distribution is reasonable (≤ 5% in the noise floor).
* Summary coverage ≥ 30% (was 1.3% pre-remediation — SummaryWorker output).
* ``summary_stale`` flag drains (long queue indicates SummaryWorker
  starvation).
* The macro sentinel entity exists (required by Worker 13D-6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.validation.conftest import scalar

if TYPE_CHECKING:  # pragma: no cover
    import psycopg

# Macro-sentinel UUID — seeded by migration 0044 (KG system entities). Worker
# 13D-6 (Economic Events) anchors every macro_indicator event on this row, so
# its absence breaks the entire economic-events pipeline.
MACRO_SENTINEL_ENTITY_ID = "11111111-0004-7000-8000-000000000001"


def test_zero_null_confidence(intelligence_db_conn: psycopg.Connection) -> None:
    """Every relation must have a non-NULL confidence (4-step formula result).

    Audit ref: F-KG-PERSIST-002. A NULL confidence means a row was upserted
    *before* the ConfidenceWorker ran — those rows are filtered out of every
    user-facing query and should not exist in steady-state.
    """
    null_count = int(scalar(intelligence_db_conn, "SELECT count(*) FROM relations WHERE confidence IS NULL") or 0)
    assert null_count == 0, (
        f"Found {null_count} relations with NULL confidence. " "ConfidenceWorker is not draining the queue."
    )


def test_zero_orphan_subject_fk(intelligence_db_conn: psycopg.Connection) -> None:
    """No relation may have a ``subject_entity_id`` missing from ``canonical_entities``.

    Audit ref: F-DB-001. Pre-PLAN-0093 the relations table had no FK enforcement
    (added by migration 0045) and orphans accumulated when an upstream entity
    was hard-deleted. Now both should be impossible — this test is the
    regression guard.
    """
    orphan_count = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM relations r "
            "WHERE NOT EXISTS (SELECT 1 FROM canonical_entities ce "
            "WHERE ce.entity_id = r.subject_entity_id)",
        )
        or 0
    )
    assert orphan_count == 0, (
        f"Found {orphan_count} relations with orphan subject_entity_id. "
        "FK constraint from migration 0045 is missing or has been bypassed."
    )


def test_zero_orphan_object_fk(intelligence_db_conn: psycopg.Connection) -> None:
    """Same as subject — no relation may have an orphan ``object_entity_id``."""
    orphan_count = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM relations r "
            "WHERE NOT EXISTS (SELECT 1 FROM canonical_entities ce "
            "WHERE ce.entity_id = r.object_entity_id)",
        )
        or 0
    )
    assert orphan_count == 0, (
        f"Found {orphan_count} relations with orphan object_entity_id. "
        "FK constraint from migration 0045 is missing or has been bypassed."
    )


def test_zero_self_loops_on_non_system_entities(
    intelligence_db_conn: psycopg.Connection,
) -> None:
    """Self-loops are only allowed on ``is_system = true`` sentinels.

    Audit ref: F-DB-012, BP-384. Real-world entities should not relate to
    themselves; sentinels (macro, sector, etc.) carry self-loops as a graph-
    materialisation trick (every event ``EXPOSES`` the sentinel). Migration
    0045 added a CHECK constraint enforcing this — the test guards against
    bypasses (e.g. via direct SQL).
    """
    bad_loop_count = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM relations r "
            "JOIN canonical_entities ce ON ce.entity_id = r.subject_entity_id "
            "WHERE r.subject_entity_id = r.object_entity_id "
            "AND COALESCE(ce.is_system, false) = false",
        )
        or 0
    )
    assert bad_loop_count == 0, (
        f"Found {bad_loop_count} self-loops on non-system entities. "
        "BP-384 regression — check the relation-write path."
    )


def test_confidence_distribution_reasonable(intelligence_db_conn: psycopg.Connection) -> None:
    """≤ 5% of relations may have confidence < 0.1.

    High noise-floor share means the confidence formula is mis-tuned or the
    relation extraction is admitting too many low-quality candidates.
    """
    total = int(scalar(intelligence_db_conn, "SELECT count(*) FROM relations") or 0)
    if total == 0:
        pytest.skip("no relations rows — nothing to assert")
    low_conf = int(scalar(intelligence_db_conn, "SELECT count(*) FROM relations WHERE confidence < 0.1") or 0)
    ratio = low_conf / total
    assert ratio <= 0.05, (
        f"{ratio:.2%} of relations have confidence < 0.1 ({low_conf}/{total}); "
        "expected ≤ 5%. Confidence formula or extractor recall threshold is off."
    )


def test_summary_coverage(intelligence_db_conn: psycopg.Connection) -> None:
    """≥ 30% of relations must have a SummaryWorker-generated summary.

    Audit ref: F-KG-PERSIST-002. Pre-remediation summary coverage was 1.3%
    — most relations carried no human-readable narrative. After Wave B-2
    the SummaryWorker should drain the queue to at least 30%.
    """
    total = int(scalar(intelligence_db_conn, "SELECT count(*) FROM relations") or 0)
    if total == 0:
        pytest.skip("no relations rows — nothing to assert")
    with_summary = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM relations r "
            "WHERE EXISTS (SELECT 1 FROM relation_summaries rs "
            "WHERE rs.relation_id = r.relation_id "
            "AND rs.is_current = true)",
        )
        or 0
    )
    ratio = with_summary / total
    assert ratio >= 0.30, (
        f"Summary coverage = {ratio:.2%} ({with_summary}/{total}); "
        "expected ≥ 30%. SummaryWorker is starved or backlogged."
    )


def test_summary_stale_flag_drains(intelligence_db_conn: psycopg.Connection) -> None:
    """≤ 100 relations with ``summary_stale = true`` at any time.

    A persistent backlog means the SummaryWorker isn't keeping up with churn.
    The 3-phase architecture (Wave B-2) should keep stale count near zero.
    """
    stale_count = int(
        scalar(
            intelligence_db_conn,
            "SELECT count(*) FROM relations WHERE summary_stale = true",
        )
        or 0
    )
    assert stale_count <= 100, (
        f"Found {stale_count} relations with summary_stale=true; expected ≤ 100. " "SummaryWorker is falling behind."
    )


def test_macro_sentinel_entity_exists(intelligence_db_conn: psycopg.Connection) -> None:
    """The macro-indicator sentinel row must exist (seeded by migration 0044).

    Audit ref: F-DB-001. Worker 13D-6 anchors every macro event on this UUID;
    its absence cascades into silent dropout of all economic events.
    """
    exists = scalar(
        intelligence_db_conn,
        "SELECT 1 FROM canonical_entities WHERE entity_id = %(eid)s",
        {"eid": MACRO_SENTINEL_ENTITY_ID},
    )
    assert exists is not None, (
        f"Macro sentinel entity {MACRO_SENTINEL_ENTITY_ID!r} is missing from "
        "canonical_entities. Migration 0044 (seed_kg_system_entities) failed or "
        "was rolled back."
    )
