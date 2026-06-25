"""Unit tests for reconcile_age_graph (FR-13 AGE↔relations reconcile).

The Cypher DELETEs / detection SQL run against the live DB via ``--apply`` /
``--dry-run`` (an integration concern); these tests pin the pure orchestration
logic — orphan detection wiring, dry-run-vs-apply behaviour, and idempotency —
with a mocked psycopg connection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import reconcile_age_graph as r

pytestmark = pytest.mark.unit


def _make_conn(detect_results: list[list[tuple[Any, ...]]]) -> Any:
    """Mock psycopg connection.

    ``execute`` returns a cursor whose ``fetchall`` yields the next queued
    result list.  Non-SELECT statements (LOAD/SET/DELETE) also consume a slot but
    their result is irrelevant — we queue ``[]`` for those.
    """
    conn = MagicMock()
    results = list(detect_results)

    def _execute(_sql: str, _params: Any = None) -> Any:
        cur = MagicMock()
        cur.fetchall.return_value = results.pop(0) if results else []
        return cur

    conn.execute.side_effect = _execute
    return conn


class TestOrphanDetection:
    def test_finds_phantom_edge_relation_ids(self) -> None:
        """Detection returns the relation_id strings from the SELECT result."""
        # 2 LOAD/SET (setup) consume slots, then the detection SELECT result.
        conn = _make_conn([[], [], [("rid-1",), ("rid-2",)]])
        ids = r.find_phantom_edge_relation_ids(conn)
        assert ids == ["rid-1", "rid-2"]

    def test_finds_phantom_vertex_entity_ids(self) -> None:
        conn = _make_conn([[], [], [("eid-1",)]])
        ids = r.find_phantom_vertex_entity_ids(conn)
        assert ids == ["eid-1"]

    def test_filters_none_rows(self) -> None:
        """NULL relation_id rows are dropped (defensive)."""
        conn = _make_conn([[], [], [("rid-1",), (None,)]])
        ids = r.find_phantom_edge_relation_ids(conn)
        assert ids == ["rid-1"]


class TestDeleteHelpers:
    def test_delete_phantom_edges_one_cypher_per_id(self) -> None:
        conn = _make_conn([[], []])  # LOAD/SET only; deletes return nothing useful
        n = r.delete_phantom_edges(conn, ["rid-1", "rid-2"], batch_size=500)
        assert n == 2
        # 2 setup + 2 deletes = 4 execute calls.
        delete_calls = [c for c in conn.execute.call_args_list if "DELETE r" in str(c.args[0])]
        assert len(delete_calls) == 2
        sent_ids = {json.loads(c.args[1]["params"])["relation_id"] for c in delete_calls}
        assert sent_ids == {"rid-1", "rid-2"}

    def test_delete_phantom_vertices_detach_delete(self) -> None:
        conn = _make_conn([[], []])
        n = r.delete_phantom_vertices(conn, ["eid-1"], batch_size=500)
        assert n == 1
        detach_calls = [c for c in conn.execute.call_args_list if "DETACH DELETE" in str(c.args[0])]
        assert len(detach_calls) == 1
        assert json.loads(detach_calls[0].args[1]["params"])["entity_id"] == "eid-1"

    def test_delete_empty_list_no_cypher(self) -> None:
        conn = _make_conn([[], []])
        assert r.delete_phantom_edges(conn, [], batch_size=500) == 0
        assert not [c for c in conn.execute.call_args_list if "DELETE r" in str(c.args[0])]


class TestReconcileDryRunVsApply:
    def test_dry_run_detects_but_does_not_delete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dry-run reports counts and issues NO Cypher DELETE + NO degree refresh."""
        # Detection: edges first (setup, setup, result), then vertices (setup, setup, result).
        conn = _make_conn([[], [], [("rid-1",), ("rid-2",)], [], [], [("eid-1",)]])

        refresh_called = {"n": 0}
        monkeypatch.setattr(r, "refresh_node_degrees", lambda: refresh_called.__setitem__("n", 1))

        report = r.reconcile(conn, apply=False, batch_size=500)

        assert report.applied is False
        assert report.phantom_edges == 2
        assert report.phantom_vertices == 1
        # No DELETE issued, no degree refresh, no commit.
        assert not [c for c in conn.execute.call_args_list if "DELETE" in str(c.args[0])]
        conn.commit.assert_not_called()
        assert refresh_called["n"] == 0

    def test_apply_deletes_and_refreshes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Apply mode deletes phantoms, commits, and refreshes degree."""
        conn = _make_conn(
            [
                [],
                [],
                [("rid-1",)],  # edge detection
                [],
                [],
                [("eid-1",)],  # vertex detection
                [],
                [],  # delete-edges setup
                [],
                [],  # delete-vertices setup
            ]
        )
        refresh_called = {"n": 0}
        monkeypatch.setattr(r, "refresh_node_degrees", lambda: refresh_called.__setitem__("n", 1))

        report = r.reconcile(conn, apply=True, batch_size=500)

        assert report.applied is True
        assert report.phantom_edges == 1
        assert report.phantom_vertices == 1
        # Cypher DELETE + DETACH DELETE both issued.
        assert [c for c in conn.execute.call_args_list if "DELETE r" in str(c.args[0])]
        assert [c for c in conn.execute.call_args_list if "DETACH DELETE" in str(c.args[0])]
        conn.commit.assert_called_once()
        assert refresh_called["n"] == 1

    def test_idempotent_no_phantoms_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A clean graph (no orphans) deletes nothing even in --apply mode."""
        conn = _make_conn([[], [], [], [], [], []])  # both detections empty
        refresh_called = {"n": 0}
        monkeypatch.setattr(r, "refresh_node_degrees", lambda: refresh_called.__setitem__("n", 1))

        report = r.reconcile(conn, apply=True, batch_size=500)

        assert report.phantom_edges == 0
        assert report.phantom_vertices == 0
        assert not [c for c in conn.execute.call_args_list if "DELETE r" in str(c.args[0])]
        assert not [c for c in conn.execute.call_args_list if "DETACH DELETE" in str(c.args[0])]
        # Apply path still commits (harmless) + refreshes degree over clean graph.
        assert refresh_called["n"] == 1


class TestAsyncDsnDerivation:
    def test_sync_dsn_converted_to_asyncpg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INTELLIGENCE_DB_ASYNC_DSN", raising=False)
        monkeypatch.setattr(r, "_INTEL_DSN", "postgresql://u:p@h:5432/intelligence_db")
        assert r._async_dsn() == "postgresql+asyncpg://u:p@h:5432/intelligence_db"

    def test_explicit_async_dsn_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INTELLIGENCE_DB_ASYNC_DSN", "postgresql+asyncpg://x/db")
        assert r._async_dsn() == "postgresql+asyncpg://x/db"
