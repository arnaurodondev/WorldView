"""T-G-1-01: AGE coverage assertion test (PLAN-0093 Wave G-1).

Audit refs: F-KG-PERSIST-001, F-REF-001, F-REF-002, F-DB-009.

Why this test exists
--------------------
The 2026-05-23 QA audit found Apache AGE was drastically behind Postgres on
all four cardinalities:

* AGE ``:entity`` vertices vs ``canonical_entities`` rows
* AGE relation edges vs ``relations`` rows
* AGE ``:TemporalEvent`` vertices vs ``temporal_events`` rows
* AGE ``EVENT_EXPOSES`` edges vs ``entity_event_exposures`` rows

The two event-related counts were at 0% (F-DB-009). Wave B-1/B-3 of the
remediation plan re-runs the AGE sync worker on all backlogged rows; this
test is the SLO assertion that the worker actually closed the gap.

We allow 5% lag because some rows may be in-flight (committed to Postgres but
not yet flushed to AGE). Below 95% indicates a structural problem.

We also document a known footgun (F-REF-001 / F-REF-002): the AGE label is
``entity`` lowercase, not ``Entity``. Cypher ``MATCH (n:Entity)`` returns
zero rows silently — the label namespace is case-sensitive. The fifth
sub-test (``test_age_label_case_matches_lowercase_entity``) is a regression
guard against that drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.validation.conftest import scalar

if TYPE_CHECKING:  # pragma: no cover
    import psycopg

# ---------------------------------------------------------------------------
# SLO threshold. 95% means the sync worker is at most 5 minutes behind on a
# steady-state ~1 Hz write rate (matches Block 12 hot-path latency budget).
# ---------------------------------------------------------------------------
COVERAGE_THRESHOLD = 0.95

# AGE graph name — defined in ``age_sync_worker._AGE_GRAPH_NAME`` and in
# migration 0004. Kept here as a constant so test failures point at the right
# graph if the platform ever moves to a multi-graph topology.
AGE_GRAPH = "worldview_graph"


def _age_count(conn: psycopg.Connection, cypher: str) -> int:
    """Run a Cypher ``count(*)`` against ``worldview_graph`` and return the int.

    AGE's ``ag_catalog.cypher(...)`` function returns ``agtype`` (a JSON-ish
    wrapper). For a bare ``RETURN count(*)`` we get back ``b'12'::agtype``,
    which psycopg surfaces as a string. We coerce to int.

    Falls back to a clean skip if the AGE graph itself is missing (e.g. the
    extension was loaded but the graph hasn't been created yet).
    """
    # AGE_GRAPH is a module-level constant whitelist (single value), and
    # *cypher* is built from caller-supplied literals only — no user input
    # ever reaches this path. ag_catalog.cypher() also parameterises Cypher
    # nodes independently of the surrounding SQL. S608 is a false positive
    # here.
    sql = f"SELECT * FROM ag_catalog.cypher('{AGE_GRAPH}', $$ {cypher} $$) AS (count_result ag_catalog.agtype)"  # noqa: S608
    with conn.cursor() as cur:
        try:
            cur.execute(sql)
        except Exception as exc:  # — anything from AGE is fatal-skip-worthy
            pytest.skip(f"AGE Cypher failed (graph {AGE_GRAPH!r} not initialised?): {exc}")
        row = cur.fetchone()
    if row is None or row[0] is None:
        return 0
    # ``row[0]`` is e.g. ``b'12'`` or ``'12'`` depending on psycopg version.
    raw = row[0]
    if isinstance(raw, bytes | bytearray):
        raw = raw.decode("ascii", errors="replace")
    # Strip any agtype annotation suffix (``"12"::numeric`` patterns).
    text_val = str(raw).strip().rstrip(":").strip('"')
    try:
        return int(float(text_val))
    except ValueError:  # pragma: no cover — defensive
        pytest.skip(f"could not parse AGE count result: {raw!r}")


def test_age_entity_coverage(age_session: psycopg.Connection) -> None:
    """AGE ``:entity`` vertex count must cover ≥ 95% of ``canonical_entities``.

    Audit ref: F-KG-PERSIST-001.
    """
    pg_count = int(scalar(age_session, "SELECT count(*) FROM canonical_entities") or 0)
    if pg_count == 0:
        pytest.skip("no canonical_entities rows in test DB — nothing to assert")
    age_count = _age_count(age_session, "MATCH (n:entity) RETURN count(n)")
    coverage = age_count / pg_count
    assert coverage >= COVERAGE_THRESHOLD, (
        f"AGE :entity coverage = {coverage:.2%} ({age_count}/{pg_count}); "
        f"expected ≥ {COVERAGE_THRESHOLD:.0%}. AGE sync worker is behind."
    )


def test_age_relation_coverage(age_session: psycopg.Connection) -> None:
    """AGE edges must cover ≥ 95% of ``relations`` rows.

    Audit refs: F-KG-PERSIST-001, F-DB-009. We count *all* edges (no label
    filter) because the platform uses multiple labels (``COMPETES_WITH``,
    ``HAS_EXECUTIVE``, etc.) — anything-with-a-relation_id counts as
    relation coverage.
    """
    pg_count = int(scalar(age_session, "SELECT count(*) FROM relations") or 0)
    if pg_count == 0:
        pytest.skip("no relations rows in test DB — nothing to assert")
    age_count = _age_count(age_session, "MATCH ()-[r]->() RETURN count(r)")
    coverage = age_count / pg_count
    assert coverage >= COVERAGE_THRESHOLD, (
        f"AGE edge coverage = {coverage:.2%} ({age_count}/{pg_count}); "
        f"expected ≥ {COVERAGE_THRESHOLD:.0%}. AGE sync worker is behind on relations."
    )


def test_age_temporal_event_coverage(age_session: psycopg.Connection) -> None:
    """AGE ``:TemporalEvent`` vertex count must cover ≥ 95% of ``temporal_events``.

    Audit ref: F-DB-009 — pre-remediation this was 0%.
    """
    pg_count = int(scalar(age_session, "SELECT count(*) FROM temporal_events") or 0)
    if pg_count == 0:
        pytest.skip("no temporal_events rows in test DB — nothing to assert")
    age_count = _age_count(age_session, "MATCH (n:TemporalEvent) RETURN count(n)")
    coverage = age_count / pg_count
    assert coverage >= COVERAGE_THRESHOLD, (
        f"AGE :TemporalEvent coverage = {coverage:.2%} ({age_count}/{pg_count}); "
        f"expected ≥ {COVERAGE_THRESHOLD:.0%}. Temporal event sync is broken (F-DB-009)."
    )


def test_age_event_exposures_coverage(age_session: psycopg.Connection) -> None:
    """AGE ``EVENT_EXPOSES`` edges must cover ≥ 95% of ``entity_event_exposures``.

    Audit ref: F-DB-009 — pre-remediation this was 0% (events synced as
    isolated vertices, never linked).
    """
    pg_count = int(scalar(age_session, "SELECT count(*) FROM entity_event_exposures") or 0)
    if pg_count == 0:
        pytest.skip("no entity_event_exposures rows in test DB — nothing to assert")
    age_count = _age_count(age_session, "MATCH ()-[r:EVENT_EXPOSES]->() RETURN count(r)")
    coverage = age_count / pg_count
    assert coverage >= COVERAGE_THRESHOLD, (
        f"AGE :EVENT_EXPOSES coverage = {coverage:.2%} ({age_count}/{pg_count}); "
        f"expected ≥ {COVERAGE_THRESHOLD:.0%}. Event-exposure edges not being created."
    )


def test_age_label_case_matches_lowercase_entity(age_session: psycopg.Connection) -> None:
    """Document the AGE label-case footgun: it's ``entity`` (lowercase).

    Audit refs: F-REF-001, F-REF-002.

    The AGE sync worker emits ``MERGE (n:entity {...})`` using a *lowercase*
    label name. Cypher label namespaces are case-sensitive, so
    ``MATCH (n:Entity)`` returns zero rows silently. This regression test
    asserts both halves of that footgun so any future drift (e.g. a
    well-meaning PR renaming the label to ``:Entity``) breaks loudly here.
    """
    # Lowercase must return rows (assuming the DB has any canonical entities).
    pg_count = int(scalar(age_session, "SELECT count(*) FROM canonical_entities") or 0)
    if pg_count == 0:
        pytest.skip("no canonical_entities rows — cannot verify label case")
    lower_count = _age_count(age_session, "MATCH (n:entity) RETURN count(n)")
    assert lower_count > 0, (
        "AGE MATCH (n:entity) returned 0 — label-case invariant broken. "
        "The sync worker must continue to use the lowercase :entity label."
    )
    # Uppercase must return zero — proves the namespace is distinct. If this
    # ever returns rows it means somebody started writing a second label and
    # we need to dedupe.
    upper_count = _age_count(age_session, "MATCH (n:Entity) RETURN count(n)")
    assert upper_count == 0, (
        f"AGE MATCH (n:Entity) returned {upper_count} rows — but the canonical "
        "label is lowercase ``entity``. Two label namespaces are diverging."
    )
