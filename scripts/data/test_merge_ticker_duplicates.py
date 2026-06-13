"""Unit tests for the survivor-selection rule in merge_ticker_duplicates (BP-459).

The re-pointing SQL itself is exercised against the live DB via the script's
``--dry-run`` mode (transactional rollback); these tests pin the pure,
deterministic survivor-selection logic that decides which canonical wins a
same-ticker merge.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_ticker_duplicates import Cluster, _choose_survivor

pytestmark = pytest.mark.unit

_INSTRUMENT = UUID("a770802d-66df-48f6-aecc-90b0dd025edf")
_NEWS = UUID("5d294bd2-f602-4449-8642-4f6707e24c96")
_OTHER = UUID("0195daad-d001-7000-8000-000000000001")


def _member(eid: UUID, exch: str | None, day: int) -> dict[str, object]:
    return {
        "entity_id": eid,
        "canonical_name": str(eid)[:6],
        "exchange": exch,
        "created_at": datetime(2026, 5, day, tzinfo=UTC),
    }


def test_prefers_instrument_anchored_row() -> None:
    """Rule 1: the row that exists in market_data.instruments wins (the SHEL case)."""
    cluster = Cluster(
        ticker="SHEL",
        members=[
            _member(_NEWS, None, 10),  # news-minted, NULL exchange, older
            _member(_INSTRUMENT, "US", 11),  # the tradable instrument
        ],
    )
    survivor = _choose_survivor(cluster, anchored={str(_INSTRUMENT)})
    assert survivor["entity_id"] == _INSTRUMENT


def test_prefers_exchange_when_no_anchor() -> None:
    """Rule 2: with no instrument-anchored row, the one WITH an exchange wins."""
    cluster = Cluster(
        ticker="PG",
        members=[
            _member(_NEWS, None, 10),
            _member(_OTHER, "US", 12),
        ],
    )
    survivor = _choose_survivor(cluster, anchored=set())
    assert survivor["entity_id"] == _OTHER


def test_tiebreak_oldest_created_at() -> None:
    """Rule 3: when neither anchored nor exchange disambiguates, oldest wins."""
    cluster = Cluster(
        ticker="SNDK",
        members=[
            _member(_OTHER, None, 15),
            _member(_NEWS, None, 9),  # oldest
        ],
    )
    survivor = _choose_survivor(cluster, anchored=set())
    assert survivor["entity_id"] == _NEWS


def test_multiple_anchored_falls_back_to_exchange_then_age() -> None:
    """Two instrument-anchored rows (dual-listing) → fall back to exchange/age."""
    cluster = Cluster(
        ticker="XYZ",
        members=[
            _member(_NEWS, "US", 11),
            _member(_OTHER, "US", 9),  # both anchored + exchange → oldest wins
        ],
    )
    survivor = _choose_survivor(cluster, anchored={str(_NEWS), str(_OTHER)})
    assert survivor["entity_id"] == _OTHER


# ── FR-13: graph-aware merge helper (_age_graph_cleanup) ────────────────────────


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self.rowcount = len(rows)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _FakeConn:
    """Minimal psycopg-Connection stand-in recording every execute call."""

    def __init__(self, returns: dict[str, list[tuple[object, ...]]] | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self._returns = returns or {}

    def execute(self, sql: str, params: object = None) -> _FakeCursor:
        self.calls.append((sql, params))
        for needle, rows in self._returns.items():
            if needle in sql:
                return _FakeCursor(rows)
        return _FakeCursor([])

    def rollback(self) -> None:
        self.calls.append(("ROLLBACK", None))

    def commit(self) -> None:
        self.calls.append(("COMMIT", None))


def test_age_cleanup_deletes_edges_and_vertices() -> None:
    """Each affected relation_id → one Cypher edge DELETE; each loser → DETACH DELETE."""
    import json

    from merge_ticker_duplicates import _age_graph_cleanup

    conn = _FakeConn()
    edges, vertices = _age_graph_cleanup(
        conn,
        relation_ids=["rid-a", "rid-b"],
        loser_entity_ids=["loser-1"],
    )
    assert edges == 2
    assert vertices == 1
    edge_calls = [c for c in conn.calls if "DELETE r" in c[0]]
    detach_calls = [c for c in conn.calls if "DETACH DELETE" in c[0]]
    assert len(edge_calls) == 2
    assert len(detach_calls) == 1
    assert {json.loads(c[1]["params"])["relation_id"] for c in edge_calls} == {"rid-a", "rid-b"}
    assert json.loads(detach_calls[0][1]["params"])["entity_id"] == "loser-1"
    # AGE session must be set up (LOAD 'age') before any Cypher.
    assert any("LOAD 'age'" in c[0] for c in conn.calls)


def test_age_cleanup_noop_when_nothing_affected() -> None:
    """No relation_ids + no losers → no Cypher, no LOAD (cheap early return)."""
    from merge_ticker_duplicates import _age_graph_cleanup

    conn = _FakeConn()
    edges, vertices = _age_graph_cleanup(conn, relation_ids=[], loser_entity_ids=[])
    assert (edges, vertices) == (0, 0)
    assert conn.calls == []


def test_merge_cluster_repoints_relation_evidence_and_cleans_age() -> None:
    """A full cluster merge re-points relation_evidence + issues AGE cleanup.

    Drives _merge_cluster with a fake connection that returns a self-loop and a
    collision deletion so the evidence-repoint + AGE-delete branches execute.
    """
    import json

    from merge_ticker_duplicates import Cluster, _merge_cluster

    survivor = "01910000-0000-7000-8000-0000000000aa"
    loser = "01910000-0000-7000-8000-0000000000bb"
    selfloop_rid = "01920000-0000-7000-8000-000000000001"
    collision_loser_rid = "01920000-0000-7000-8000-000000000002"
    collision_kept_rid = "01920000-0000-7000-8000-000000000003"
    repoint_rid = "01920000-0000-7000-8000-000000000004"

    intel = _FakeConn(
        returns={
            # self-loop DELETE ... RETURNING relation_id
            "AND (CASE WHEN r.subject_entity_id": [(selfloop_rid,)],
            # collision DELETE ... RETURNING relation_id, kept_rid
            "USING ranked": [(collision_loser_rid, collision_kept_rid)],
            # endpoint UPDATE ... RETURNING relation_id (re-pointed survivors)
            "UPDATE relations SET subject_entity_id": [(repoint_rid,)],
        }
    )
    nlp = _FakeConn()

    cluster = Cluster(ticker="ZZZ", members=[])
    counts = _merge_cluster(intel, nlp, cluster, survivor, [loser], dry_run=True)

    # relation_evidence re-pointed for the collision loser → kept survivor.
    repoint_calls = [c for c in intel.calls if "UPDATE relation_evidence SET relation_id" in c[0]]
    assert repoint_calls, "collision-loser evidence must be re-pointed, not orphaned"
    assert repoint_calls[0][1] == {"kept": collision_kept_rid, "loser": collision_loser_rid}

    # self-loop evidence deleted.
    assert any("DELETE FROM relation_evidence WHERE relation_id = ANY" in c[0] for c in intel.calls)

    # AGE cleanup: every affected relation_id (self-loop + collision + re-pointed)
    # gets a Cypher edge DELETE; the loser entity gets a DETACH DELETE.
    edge_deletes = {json.loads(c[1]["params"])["relation_id"] for c in intel.calls if "DELETE r" in c[0]}
    assert edge_deletes == {selfloop_rid, collision_loser_rid, repoint_rid}
    detach = [c for c in intel.calls if "DETACH DELETE" in c[0]]
    assert json.loads(detach[0][1]["params"])["entity_id"] == loser

    # re-pointed survivor UPDATE bumps updated_at so the additive sync rebuilds it.
    assert any("updated_at = now()" in c[0] for c in intel.calls)
    assert counts["age.loser_vertices_deleted"] == 1
