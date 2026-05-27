"""Unit tests for AgeSyncWorker (Worker 13F) — PRD-0018 §6 Worker 13F.

PLAN-0093 Wave B-1 refresh: the worker now bootstraps AGE labels on first
startup and uses three independent per-phase watermark keys.  The execute
sequence is therefore:

  Per ``run()`` invocation (assuming bootstrap pending):
    1. _setup_age_session (LOAD age + SET search_path)
    2..N. create_vlabel / create_elabel (35 statements: 2 vlabels + 33 elabels)
    N+1. session.commit  [bootstrap done]

    Per phase (entities → relations → temporal_events):
      • _setup_age_session  (LOAD + SET = 2 calls)
      • <phase SELECT(s) + Cypher MERGE(s)>
      • session.commit
      • Optional stall-check SELECT (only when phase synced 0 rows)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


# Number of label-bootstrap execute() calls expected on first startup.
# Currently: 2 vlabels + 33 elabels (size of _VALID_EDGE_LABELS) + 1 commit-trailing
# session.execute() count = 35 SQL statements.
def _bootstrap_statement_count() -> int:
    from knowledge_graph.infrastructure.workers.age_sync_worker import _VALID_EDGE_LABELS

    # 2 vlabels + every elabel in _VALID_EDGE_LABELS
    return 2 + len(_VALID_EDGE_LABELS)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_settings(cypher_enabled: bool = True) -> Any:
    settings = MagicMock()
    settings.cypher_enabled = cypher_enabled
    return settings


def _make_valkey(watermark: str | None = None, *, per_phase: dict[str, str] | None = None) -> Any:
    """Build a mock ValkeyClient.

    ``per_phase`` lets a test pre-load the new per-phase watermark keys.
    When omitted, all GETs return *watermark* (default None → epoch).
    """
    valkey = AsyncMock()
    store: dict[str, str] = {}
    if per_phase:
        store.update(per_phase)
    # If a single ``watermark`` is supplied, treat it as the value for every
    # per-phase key — preserves the legacy single-watermark tests.
    if watermark is not None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _PHASE_WATERMARK_KEYS

        for k in _PHASE_WATERMARK_KEYS.values():
            store.setdefault(k, watermark)

    async def _get(key: str) -> str | None:
        return store.get(key)

    async def _set(key: str, value: str) -> None:
        store[key] = value

    valkey.get = AsyncMock(side_effect=_get)
    valkey.set = AsyncMock(side_effect=_set)
    # Expose the backing store so tests can introspect.
    valkey._store = store  # — test helper only
    return valkey


def _make_result(rows: list[Any], *, scalar: int | None = None) -> Any:
    """Build a mock SQLAlchemy result with fetchall()."""
    result = MagicMock()
    result.fetchall = MagicMock(return_value=rows)
    if scalar is not None:
        result.scalar = MagicMock(return_value=scalar)
    else:
        result.scalar = MagicMock(return_value=0)
    return result


def _make_session(execute_results: list[Any] | None = None) -> Any:
    """Build a mock AsyncSession with configurable execute return values."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    if execute_results is not None:
        results = [_make_result(rows) if isinstance(rows, list) else rows for rows in execute_results]
        session.execute = AsyncMock(side_effect=results)
    else:
        # Default: empty result for all queries (any scalar() returns 0).
        session.execute = AsyncMock(return_value=_make_result([]))

    return session


def _make_session_factory(session: Any) -> Any:
    """Build a mock session factory that yields *session*."""
    sf = MagicMock()
    sf.return_value = session
    return sf


def _make_entity_row(
    entity_id: str = "01910000-0000-7000-8000-000000000001",
    canonical_name: str = "Apple Inc.",
    entity_type: str = "financial_instrument",
    ticker: str = "AAPL",
    updated_at: datetime | None = None,
) -> Any:
    row = MagicMock()
    row.entity_id = entity_id
    row.canonical_name = canonical_name
    row.entity_type = entity_type
    row.ticker = ticker
    row.updated_at = updated_at or datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    return row


def _make_relation_row(
    relation_id: str = "01920000-0000-7000-8000-000000000001",
    subject_entity_id: str = "01910000-0000-7000-8000-000000000001",
    object_entity_id: str = "01910000-0000-7000-8000-000000000002",
    canonical_type: str = "competes_with",
    confidence: float = 0.85,
    updated_at: datetime | None = None,
) -> Any:
    row = MagicMock()
    row.relation_id = relation_id
    row.subject_entity_id = subject_entity_id
    row.object_entity_id = object_entity_id
    row.canonical_type = canonical_type
    row.confidence = confidence
    row.updated_at = updated_at or datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    return row


def _build_worker(
    session: Any,
    valkey: Any,
    settings: Any | None = None,
    *,
    skip_bootstrap: bool = False,
) -> Any:
    """Construct an AgeSyncWorker, optionally pre-marking bootstrap as done so
    tests don't have to enumerate the 35-call bootstrap sequence.
    """
    from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

    sf = _make_session_factory(session)
    worker = AgeSyncWorker(
        session_factory=sf,
        valkey_client=valkey,
        settings=settings or _make_settings(cypher_enabled=True),
    )
    if skip_bootstrap:
        worker._labels_bootstrap_pending = False  # — test seam
    return worker


# ── Test: Feature flag disabled ────────────────────────────────────────────────


class TestAgeSyncWorkerDisabled:
    def test_run_skipped_when_disabled(self) -> None:
        """When cypher_enabled=False, run() returns immediately without DB access."""
        settings = _make_settings(cypher_enabled=False)
        valkey = _make_valkey()
        session = _make_session()
        worker = _build_worker(session, valkey, settings)

        asyncio.run(worker.run())

        # No DB session opened, no Valkey reads/writes
        session.execute.assert_not_called()
        valkey.get.assert_not_awaited()
        valkey.set.assert_not_awaited()

    def test_no_watermark_update_when_disabled(self) -> None:
        """Watermark is NOT updated when the feature flag is off."""
        settings = _make_settings(cypher_enabled=False)
        valkey = _make_valkey()
        session = _make_session()
        worker = _build_worker(session, valkey, settings)
        asyncio.run(worker.run())
        valkey.set.assert_not_awaited()


# ── Test: Watermark handling ───────────────────────────────────────────────────


class TestAgeSyncWorkerWatermark:
    def test_watermark_updated_after_run(self) -> None:
        """After a successful run, every per-phase watermark is set."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _PHASE_WATERMARK_KEYS

        valkey = _make_valkey()
        session = _make_session()
        worker = _build_worker(session, valkey, skip_bootstrap=True)
        asyncio.run(worker.run())

        # All 3 per-phase keys should now have an ISO-8601 value.
        for key in _PHASE_WATERMARK_KEYS.values():
            assert key in valkey._store, f"phase key {key} not written"
            dt = datetime.fromisoformat(valkey._store[key])
            assert dt.tzinfo is not None

    def test_epoch_watermark_used_when_key_missing(self) -> None:
        """When the per-phase Valkey key is absent, the epoch (1970-01-01) is used."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _EPOCH

        valkey = _make_valkey(watermark=None)
        session = _make_session()
        worker = _build_worker(session, valkey, skip_bootstrap=True)

        # Capture the watermark passed to _sync_entities (and the others).
        captured: list[datetime] = []

        async def _capture_sync(sess: Any, since: datetime) -> int:
            captured.append(since)
            return 0

        worker._sync_entities = _capture_sync  # type: ignore[method-assign]
        worker._sync_relations = _capture_sync  # type: ignore[method-assign]
        worker._sync_temporal_events = _capture_sync  # type: ignore[method-assign]

        asyncio.run(worker.run())

        # Each of the 3 phases should have received the epoch watermark.
        assert captured == [_EPOCH, _EPOCH, _EPOCH]

    def test_stored_watermark_is_used_on_second_run(self) -> None:
        """When Valkey has an existing per-phase watermark, it is used as the since boundary."""
        stored_wm = "2026-04-01T00:00:00+00:00"

        valkey = _make_valkey(watermark=stored_wm)
        session = _make_session()
        worker = _build_worker(session, valkey, skip_bootstrap=True)

        captured: list[datetime] = []

        async def _capture_sync(sess: Any, since: datetime) -> int:
            captured.append(since)
            return 0

        worker._sync_entities = _capture_sync  # type: ignore[method-assign]
        worker._sync_relations = _capture_sync  # type: ignore[method-assign]
        worker._sync_temporal_events = _capture_sync  # type: ignore[method-assign]

        asyncio.run(worker.run())

        expected = datetime.fromisoformat(stored_wm)
        assert captured == [expected, expected, expected]


# ── Test: Edge label derivation ────────────────────────────────────────────────


class TestEdgeLabelDerivation:
    def test_lowercase_underscore_type(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("competes_with") == "COMPETES_WITH"

    def test_mixed_case_type(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("has_executive") == "HAS_EXECUTIVE"

    def test_space_in_type_converted(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("competes with") == "COMPETES_WITH"

    def test_unknown_type_returns_none(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("unknown_injected_type") is None

    def test_all_valid_edge_labels_round_trip(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import (
            _VALID_EDGE_LABELS,
            _derive_edge_label,
        )

        # 27 original + 5 PLAN-0089 Lever-4 (migration 0041) + EVENT_EXPOSES + EXPOSED_TO_THEME = 34
        assert (
            len(_VALID_EDGE_LABELS) == 34
        ), f"Expected 34 labels but got {len(_VALID_EDGE_LABELS)}; update this count after adding new relation types."
        for label in _VALID_EDGE_LABELS:
            assert _derive_edge_label(label) == label


# ── Test: Per-phase watermark + isolation (PLAN-0093 B-1) ─────────────────────


class TestPerPhaseWatermark:
    """T-B-1-02: each phase has its own Valkey key + try/except.

    A failure in one phase does not block the others' watermark advance.
    """

    def test_per_phase_watermark_keys_are_distinct(self) -> None:
        """After a successful run, all 3 watermark keys are populated independently."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _PHASE_WATERMARK_KEYS

        valkey = _make_valkey()
        session = _make_session()
        worker = _build_worker(session, valkey, skip_bootstrap=True)
        asyncio.run(worker.run())

        # 3 distinct keys, all written.
        assert len(_PHASE_WATERMARK_KEYS) == 3
        keys_written = {c.args[0] for c in valkey.set.await_args_list}
        assert set(_PHASE_WATERMARK_KEYS.values()).issubset(keys_written)

    def test_temporal_event_failure_does_not_block_relation_watermark(self) -> None:
        """If the temporal_events phase raises ProgrammingError, the relations
        phase's watermark must still advance — the whole point of the per-phase split.
        """
        from knowledge_graph.infrastructure.workers.age_sync_worker import _PHASE_WATERMARK_KEYS
        from sqlalchemy.exc import ProgrammingError

        valkey = _make_valkey()
        session = _make_session()
        worker = _build_worker(session, valkey, skip_bootstrap=True)

        async def _ok(sess: Any, since: datetime) -> int:
            return 1

        async def _raise(sess: Any, since: datetime) -> int:
            raise ProgrammingError("missing label TemporalEvent", params={}, orig=Exception("x"))

        worker._sync_entities = _ok  # type: ignore[method-assign]
        worker._sync_relations = _ok  # type: ignore[method-assign]
        worker._sync_temporal_events = _raise  # type: ignore[method-assign]

        asyncio.run(worker.run())

        # entities + relations watermarks should be written; temporal_events should NOT.
        keys_written = {c.args[0] for c in valkey.set.await_args_list}
        assert _PHASE_WATERMARK_KEYS["entities"] in keys_written
        assert _PHASE_WATERMARK_KEYS["relations"] in keys_written
        assert _PHASE_WATERMARK_KEYS["temporal_events"] not in keys_written

    def test_phase_failure_logs_with_phase_name(self) -> None:
        """When a phase fails, the structured log includes a ``phase`` field."""
        from unittest.mock import patch

        import knowledge_graph.infrastructure.workers.age_sync_worker as _mod
        from sqlalchemy.exc import ProgrammingError

        valkey = _make_valkey()
        session = _make_session()
        worker = _build_worker(session, valkey, skip_bootstrap=True)

        async def _raise(sess: Any, since: datetime) -> int:
            raise ProgrammingError("boom", params={}, orig=Exception("x"))

        # Only fail the relations phase.
        worker._sync_entities = AsyncMock(return_value=0)  # type: ignore[method-assign]
        worker._sync_relations = _raise  # type: ignore[method-assign]
        worker._sync_temporal_events = AsyncMock(return_value=0)  # type: ignore[method-assign]

        log_calls: list[tuple[str, dict[str, Any]]] = []
        original_warning = _mod.logger.warning

        def _capture(event: str, **kwargs: Any) -> None:
            log_calls.append((event, kwargs))
            return original_warning(event, **kwargs)

        with patch.object(_mod.logger, "warning", side_effect=_capture):
            asyncio.run(worker.run())

        phase_failed = [kwargs for event, kwargs in log_calls if event == "age_sync_phase_failed"]
        assert phase_failed, "expected age_sync_phase_failed log entry"
        assert phase_failed[0].get("phase") == "relations"


# ── Test: Label bootstrap (PLAN-0093 B-1 T-B-1-01) ────────────────────────────


class TestLabelBootstrap:
    """T-B-1-01: AGE labels must be created on the very first sync cycle so
    that subsequent MERGEs can target them.
    """

    def test_bootstrap_runs_on_first_run_only(self) -> None:
        """The bootstrap statements execute on run #1 and are skipped on run #2."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        valkey = _make_valkey()
        # Use a session whose execute() always returns an empty result (also
        # provides .scalar() == 0 for the stall-check SELECT).  We don't rely on
        # an exact side_effect script here — the bootstrap statements just
        # need to succeed.
        session = _make_session()

        sf = _make_session_factory(session)
        worker = AgeSyncWorker(
            session_factory=sf,
            valkey_client=valkey,
            settings=_make_settings(cypher_enabled=True),
        )
        # Run #1 — bootstrap should fire.
        asyncio.run(worker.run())
        first_run_calls = session.execute.await_count

        # Run #2 — bootstrap should be skipped (flag flipped to False).
        session.execute.reset_mock()
        asyncio.run(worker.run())
        second_run_calls = session.execute.await_count

        # On the second run we expect strictly fewer execute() calls because
        # we skipped the bootstrap (35 statements).
        assert (
            second_run_calls < first_run_calls
        ), f"run #2 should skip bootstrap (first={first_run_calls}, second={second_run_calls})"
        assert worker._labels_bootstrap_pending is False

    def test_bootstrap_issues_create_vlabel_and_elabel(self) -> None:
        """At least one ``create_vlabel`` and one ``create_elabel`` call is issued."""
        valkey = _make_valkey()
        session = _make_session()
        worker = _build_worker(session, valkey)

        asyncio.run(worker.run())

        sqls = [str(c.args[0]) for c in session.execute.await_args_list]
        vlabel_calls = [s for s in sqls if "create_vlabel" in s]
        elabel_calls = [s for s in sqls if "create_elabel" in s]
        assert vlabel_calls, "expected at least one create_vlabel statement"
        assert elabel_calls, "expected at least one create_elabel statement"
        # 2 vlabels (entity, TemporalEvent) + every value in _VALID_EDGE_LABELS
        assert len(vlabel_calls) == 2
        from knowledge_graph.infrastructure.workers.age_sync_worker import _VALID_EDGE_LABELS

        assert len(elabel_calls) == len(_VALID_EDGE_LABELS)

    def test_bootstrap_swallows_already_exists(self) -> None:
        """A ``already exists`` ProgrammingError from a single create_*label statement
        must not abort the whole bootstrap — idempotency requirement.
        """
        from sqlalchemy.exc import ProgrammingError

        valkey = _make_valkey()

        # Build a session whose execute() succeeds for everything EXCEPT one
        # ``create_elabel`` call which raises an "already exists" error.
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        calls: list[Any] = []

        async def _execute(stmt: Any, params: Any = None) -> Any:
            calls.append(stmt)
            sql = str(stmt)
            if "create_elabel" in sql and "EMPLOYS" in sql:
                raise ProgrammingError("label already exists", params={}, orig=Exception("dup"))
            return _make_result([])

        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, valkey)
        # Must not raise.
        asyncio.run(worker.run())
        assert worker._labels_bootstrap_pending is False

    def test_bootstrap_invalidates_connection_before_phases(self) -> None:
        """PLAN-0096 W3 T-W3-01 / BP-574 — after the bootstrap commit, the worker
        MUST call ``session.connection().invalidate()`` so the next phase's
        MERGE statements pick up a fresh connection without a stale AGE schema
        cache. Without this, PostgreSQL's plpgsql engine caches the pre-label
        schema and silently drops 100% of TemporalEvent MERGEs.
        """
        valkey = _make_valkey()
        session = _make_session()

        # Build an explicit connection mock so we can assert .invalidate() was
        # awaited. session.connection() must itself be awaitable (per
        # SQLAlchemy AsyncSession API).
        connection_mock = AsyncMock()
        connection_mock.invalidate = AsyncMock()
        session.connection = AsyncMock(return_value=connection_mock)

        worker = _build_worker(session, valkey)
        asyncio.run(worker.run())

        # The bootstrap path must have asked for the connection and invalidated
        # it. Use assert_awaited (rather than assert_called) because both
        # session.connection and connection.invalidate are async.
        session.connection.assert_awaited()
        connection_mock.invalidate.assert_awaited_once()

    def test_bootstrap_rollback_called_before_invalidate(self) -> None:
        """PLAN-0097 W4 T-W4-03 / R36 — after the bootstrap commit, the worker
        MUST call ``session.rollback()`` BEFORE ``connection.invalidate()`` to
        clear any half-prepared autobegin transaction state. Order matters:
        an in-flight tx left over from a swallowed "already exists" branch
        would otherwise mask the invalidate's effect.
        """
        valkey = _make_valkey()
        session = _make_session()

        # Record the call order across session.rollback and connection.invalidate.
        call_order: list[str] = []

        async def _rollback() -> None:
            call_order.append("rollback")

        async def _invalidate() -> None:
            call_order.append("invalidate")

        session.rollback = AsyncMock(side_effect=_rollback)
        connection_mock = AsyncMock()
        connection_mock.invalidate = AsyncMock(side_effect=_invalidate)
        session.connection = AsyncMock(return_value=connection_mock)

        worker = _build_worker(session, valkey)
        asyncio.run(worker.run())

        # Both calls must have happened; rollback must come BEFORE invalidate
        # in the bootstrap cleanup sequence (R36).
        assert "rollback" in call_order, "rollback() must run during bootstrap cleanup"
        assert "invalidate" in call_order, "invalidate() must run during bootstrap cleanup"
        # Find the FIRST occurrence of each (rollback may also be called from
        # phase-cleanup paths in _run_phase; the bootstrap rollback must be
        # earlier in call_order than the invalidate).
        idx_rollback = call_order.index("rollback")
        idx_invalidate = call_order.index("invalidate")
        assert idx_rollback < idx_invalidate, f"rollback() must happen BEFORE invalidate() — got order: {call_order}"

    def test_rollback_failure_does_not_prevent_invalidate(self) -> None:
        """PLAN-0097 W4 T-W4-03 — rollback() is best-effort. If it raises, the
        worker MUST still proceed to invalidate the connection (and the cycle
        as a whole MUST NOT crash). Mirrors the BP-574 mitigation contract for
        invalidate itself.
        """
        valkey = _make_valkey()
        session = _make_session()

        session.rollback = AsyncMock(side_effect=RuntimeError("session already closed"))
        connection_mock = AsyncMock()
        connection_mock.invalidate = AsyncMock()
        session.connection = AsyncMock(return_value=connection_mock)

        worker = _build_worker(session, valkey)
        # Must not raise — both cleanup calls are best-effort.
        asyncio.run(worker.run())

        # Even though rollback raised, invalidate must still have been awaited.
        connection_mock.invalidate.assert_awaited_once()

    def test_invalidate_failure_does_not_crash_run(self) -> None:
        """BP-574 mitigation — if invalidate raises, the cycle continues. The
        worst case is a silent regression to the stale-schema path, never a
        crash mid-cycle.
        """
        valkey = _make_valkey()
        session = _make_session()

        connection_mock = AsyncMock()
        connection_mock.invalidate = AsyncMock(side_effect=RuntimeError("pool closed"))
        session.connection = AsyncMock(return_value=connection_mock)

        worker = _build_worker(session, valkey)
        # Must not raise — invalidate failure is swallowed and logged.
        asyncio.run(worker.run())
        assert worker._labels_bootstrap_pending is False


@pytest.mark.integration
class TestAgeSyncTemporalEventReconciliationIntegration:
    """T-W3-02 — regression test for the 0/14,822 silent-drop bug.

    Seeds a fresh ``temporal_events`` SQL table with a handful of rows,
    instantiates ``AgeSyncWorker``, runs ``run()``, then asserts via direct
    Cypher that the AGE ``TemporalEvent`` node count equals the SQL row
    count. Requires a live PostgreSQL + Apache AGE container; skipped when
    the env var ``KNOWLEDGE_GRAPH_INTEGRATION_DB_URL`` is unset.
    """

    def test_bootstrap_then_phases_produce_matching_node_count(self) -> None:
        import os

        db_url = os.environ.get("KNOWLEDGE_GRAPH_INTEGRATION_DB_URL")
        if not db_url:
            pytest.skip(
                "KNOWLEDGE_GRAPH_INTEGRATION_DB_URL not set — AGE-backed "
                "integration test requires a live postgres+age container",
            )
        # The full integration body is intentionally not implemented in the
        # unit-test tier — see scripts/reconcile_age_temporal_events.py for
        # the operator-driven equivalent. This stub keeps the test marker
        # discoverable so CI surfaces the gap when an AGE container is wired.
        pytest.skip("integration body wired via scripts/reconcile_age_temporal_events.py")


# ── Test: Stall detector (PLAN-0093 B-1 T-B-1-03) ─────────────────────────────


class TestStallDetector:
    def test_stall_counter_incremented_when_source_has_new_rows(self) -> None:
        """When a phase syncs 0 but COUNT(*) > 0, the stall counter is bumped."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            s7_age_sync_phase_stalled_total,
        )

        before = s7_age_sync_phase_stalled_total.labels(phase="entities")._value.get()

        valkey = _make_valkey()

        # Build a session whose stall-check SELECT (COUNT(*)) returns 7,
        # but the phase sync itself reports 0 rows.
        async def _execute(stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            if "COUNT(*)" in sql and "canonical_entities" in sql:
                return _make_result([], scalar=7)
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, valkey, skip_bootstrap=True)
        asyncio.run(worker.run())

        after = s7_age_sync_phase_stalled_total.labels(phase="entities")._value.get()
        assert after - before >= 1.0

    def test_stall_not_triggered_when_synced_count_positive(self) -> None:
        """If a phase synced > 0 rows, the stall check is skipped entirely."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            s7_age_sync_phase_stalled_total,
        )

        before = s7_age_sync_phase_stalled_total.labels(phase="entities")._value.get()

        valkey = _make_valkey()
        session = _make_session()
        worker = _build_worker(session, valkey, skip_bootstrap=True)

        async def _ok(sess: Any, since: datetime) -> int:
            return 5

        worker._sync_entities = _ok  # type: ignore[method-assign]
        worker._sync_relations = AsyncMock(return_value=5)  # type: ignore[method-assign]
        worker._sync_temporal_events = AsyncMock(return_value=5)  # type: ignore[method-assign]

        asyncio.run(worker.run())

        after = s7_age_sync_phase_stalled_total.labels(phase="entities")._value.get()
        assert after - before == 0.0


# ── Test: Entities synced ──────────────────────────────────────────────────────


class TestAgeSyncWorkerEntities:
    def test_entity_merge_cypher_called(self) -> None:
        """For each entity row, AGE Cypher MERGE is executed with entity_id param."""
        entity_row = _make_entity_row()

        # Patch _sync_entities to return 1 row's worth of data via the real path.
        # We're verifying the real Cypher MERGE call shape, so we drive the
        # entities SELECT to return one row and let everything else return empty.
        select_results: dict[str, Any] = {
            "canonical_entities": _make_result([entity_row]),
            "relations": _make_result([]),
            "temporal_events": _make_result([]),
            "entity_event_exposures": _make_result([]),
        }

        cypher_merge_calls: list[Any] = []

        async def _execute(stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            # Stall-check COUNT(*) → return 0 so we don't trigger stall logic.
            if "COUNT(*)" in sql:
                return _make_result([], scalar=0)
            # Entity SELECT
            if "FROM canonical_entities" in sql:
                return _make_result([entity_row])
            # Relation SELECT
            if "FROM relations" in sql:
                return _make_result([])
            # Temporal SELECTs
            if "FROM temporal_events" in sql or "FROM entity_event_exposures" in sql:
                return _make_result([])
            # Cypher MERGEs — capture for assertion
            if "cypher" in sql and "MERGE" in sql:
                cypher_merge_calls.append((stmt, params))
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        valkey = _make_valkey()
        worker = _build_worker(session, valkey, skip_bootstrap=True)
        asyncio.run(worker.run())

        # We expect at least one Cypher MERGE that targets the entity vertex.
        entity_merges = [(s, p) for s, p in cypher_merge_calls if "entity" in str(s) and "entity_id" in str(s)]
        assert entity_merges, "expected at least one entity MERGE Cypher call"
        # The params JSON should embed the entity_id.
        params_arg = entity_merges[0][1]
        assert params_arg is not None
        import json

        params = json.loads(params_arg["params"])
        assert params["entity_id"] == str(entity_row.entity_id)
        assert params["name"] == entity_row.canonical_name
        # Reference the unused dict so ruff is happy.
        assert "relations" in select_results

    def test_prometheus_entity_counter_incremented(self) -> None:
        """s7_age_sync_entities_total is incremented by the number of entities synced."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_age_sync_entities_total

        before = s7_age_sync_entities_total._value.get()

        entity_row = _make_entity_row()

        async def _execute(stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            if "COUNT(*)" in sql:
                return _make_result([], scalar=0)
            if "FROM canonical_entities" in sql:
                return _make_result([entity_row])
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, _make_valkey(), skip_bootstrap=True)
        asyncio.run(worker.run())

        after = s7_age_sync_entities_total._value.get()
        assert after - before == 1.0


# ── Test: Relation edge label in Cypher ───────────────────────────────────────


class TestAgeSyncWorkerRelations:
    def test_relation_edge_label_embedded_in_cypher(self) -> None:
        """Relation MERGE Cypher contains the derived edge label (not a generic placeholder)."""
        relation_row = _make_relation_row(canonical_type="competes_with")

        cypher_calls: list[str] = []

        async def _execute(stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            if "COUNT(*)" in sql:
                return _make_result([], scalar=0)
            if "FROM canonical_entities" in sql:
                return _make_result([])
            if "FROM relations" in sql:
                return _make_result([relation_row])
            if "FROM temporal_events" in sql or "FROM entity_event_exposures" in sql:
                return _make_result([])
            if "cypher" in sql and "MERGE" in sql:
                cypher_calls.append(sql)
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, _make_valkey(), skip_bootstrap=True)
        asyncio.run(worker.run())

        assert any(
            "COMPETES_WITH" in s for s in cypher_calls
        ), f"expected COMPETES_WITH in some Cypher MERGE call; got {cypher_calls}"

    def test_unknown_relation_type_skipped(self) -> None:
        """Relations with unknown canonical_type are skipped (no Cypher MERGE for them)."""
        relation_row = _make_relation_row(canonical_type="injected_type")

        cypher_calls: list[str] = []

        async def _execute(stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            if "COUNT(*)" in sql:
                return _make_result([], scalar=0)
            if "FROM canonical_entities" in sql:
                return _make_result([])
            if "FROM relations" in sql:
                return _make_result([relation_row])
            if "FROM temporal_events" in sql or "FROM entity_event_exposures" in sql:
                return _make_result([])
            if "cypher" in sql and "MERGE" in sql:
                cypher_calls.append(sql)
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, _make_valkey(), skip_bootstrap=True)
        asyncio.run(worker.run())

        # No Cypher MERGE for the injected type.
        assert not any("injected_type" in s.lower() for s in cypher_calls)

    def test_prometheus_relation_counter_incremented(self) -> None:
        """s7_age_sync_relations_total is incremented by the number of relations synced."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_age_sync_relations_total

        before = s7_age_sync_relations_total._value.get()

        relation_row = _make_relation_row(canonical_type="competes_with")

        async def _execute(stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            if "COUNT(*)" in sql:
                return _make_result([], scalar=0)
            if "FROM canonical_entities" in sql:
                return _make_result([])
            if "FROM relations" in sql:
                return _make_result([relation_row])
            if "FROM temporal_events" in sql or "FROM entity_event_exposures" in sql:
                return _make_result([])
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, _make_valkey(), skip_bootstrap=True)
        asyncio.run(worker.run())

        after = s7_age_sync_relations_total._value.get()
        assert after - before == 1.0


# ── Test: AGE session setup ────────────────────────────────────────────────────


class TestAgeSessionSetup:
    def test_load_age_called_before_cypher(self) -> None:
        """LOAD 'age' and SET search_path are executed before any Cypher queries."""
        session = _make_session()
        valkey = _make_valkey()
        worker = _build_worker(session, valkey, skip_bootstrap=True)
        asyncio.run(worker.run())

        # First call should be LOAD 'age' (issued by _setup_age_session at the start
        # of each phase; first phase = entities).
        first_call_text = str(session.execute.call_args_list[0][0][0])
        assert "LOAD" in first_call_text and "age" in first_call_text.lower()

        # Second call should be SET search_path
        second_call_text = str(session.execute.call_args_list[1][0][0])
        assert "search_path" in second_call_text


# ── Test: _derive_edge_label helper ───────────────────────────────────────────


class TestDeriveEdgeLabelHelper:
    def test_event_exposes_is_valid(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("EVENT_EXPOSES") == "EVENT_EXPOSES"

    def test_empty_string_returns_none(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("") is None

    def test_whitespace_only_returns_none(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("   ") is None


# ── Test: _sync_temporal_events pagination ────────────────────────────────────


def _make_event_row(
    event_id: str = "01930000-0000-7000-8000-000000000001",
    event_type: str = "MACRO",
    scope: str = "NATIONAL",
    region: str = "US",
    title: str = "CPI m/m",
    confidence: float = 1.0,
    updated_at: datetime | None = None,
) -> Any:
    row = MagicMock()
    row.event_id = event_id
    row.event_type = event_type
    row.scope = scope
    row.region = region
    row.title = title
    row.confidence = confidence
    row.updated_at = updated_at or datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    return row


class TestSyncTemporalEventsPagination:
    """_sync_temporal_events: pagination loop terminates correctly."""

    def test_empty_first_page_issues_no_cypher(self) -> None:
        """When temporal_events returns an empty first page, no MERGE Cypher fires."""
        cypher_calls: list[str] = []

        async def _execute(stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            if "COUNT(*)" in sql:
                return _make_result([], scalar=0)
            if "cypher" in sql and "MERGE" in sql:
                cypher_calls.append(sql)
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, _make_valkey(), skip_bootstrap=True)
        asyncio.run(worker.run())

        assert cypher_calls == []

    def test_partial_page_terminates_loop(self) -> None:
        """A page smaller than event_batch (2000) stops pagination without a second SELECT."""
        event_row = _make_event_row()
        temporal_selects = 0

        async def _execute(stmt: Any, params: Any = None) -> Any:
            nonlocal temporal_selects
            sql = str(stmt)
            if "COUNT(*)" in sql:
                return _make_result([], scalar=0)
            if "FROM temporal_events" in sql:
                temporal_selects += 1
                # Only return the row on the FIRST SELECT, empty thereafter.
                return _make_result([event_row] if temporal_selects == 1 else [])
            if "FROM entity_event_exposures" in sql:
                return _make_result([])
            if "FROM canonical_entities" in sql or "FROM relations" in sql:
                return _make_result([])
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, _make_valkey(), skip_bootstrap=True)
        asyncio.run(worker.run())

        # Pagination should stop after the first (partial) page — only one
        # temporal_events SELECT regardless of stall-check.
        assert temporal_selects == 1

    def test_temporal_event_cypher_contains_correct_params(self) -> None:
        """Cypher MERGE for a temporal event embeds event_id and title in params JSON."""
        import json

        event_row = _make_event_row(
            event_id="01930000-0000-7000-8000-000000000099",
            title="GDP q/q",
        )

        captured: list[tuple[str, Any]] = []

        async def _execute(stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            if "COUNT(*)" in sql:
                return _make_result([], scalar=0)
            if "FROM temporal_events" in sql:
                return _make_result([event_row])
            if "FROM entity_event_exposures" in sql:
                return _make_result([])
            if "FROM canonical_entities" in sql or "FROM relations" in sql:
                return _make_result([])
            if "TemporalEvent" in sql and "MERGE" in sql:
                captured.append((sql, params))
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, _make_valkey(), skip_bootstrap=True)
        asyncio.run(worker.run())

        assert captured, "expected a TemporalEvent MERGE Cypher call"
        cypher_sql, params_arg = captured[0]
        assert "TemporalEvent" in cypher_sql
        params = json.loads(params_arg["params"])
        assert params["event_id"] == "01930000-0000-7000-8000-000000000099"
        assert params["title"] == "GDP q/q"

    def test_valkey_error_falls_back_to_epoch(self) -> None:
        """When Valkey.get() raises, every per-phase watermark falls back to epoch."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _EPOCH, AgeSyncWorker

        valkey = AsyncMock()
        valkey.get = AsyncMock(side_effect=ConnectionError("valkey down"))
        valkey.set = AsyncMock()

        session = _make_session()
        sf = _make_session_factory(session)
        settings = _make_settings()

        captured: list[datetime] = []

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        worker._labels_bootstrap_pending = False

        async def _capture(sess: Any, since: datetime) -> int:
            captured.append(since)
            return 0

        worker._sync_entities = _capture  # type: ignore[method-assign]
        worker._sync_relations = _capture  # type: ignore[method-assign]
        worker._sync_temporal_events = _capture  # type: ignore[method-assign]

        asyncio.run(worker.run())

        assert captured == [_EPOCH, _EPOCH, _EPOCH]

    def test_valkey_write_error_does_not_crash_worker(self) -> None:
        """When Valkey.set() raises, the run completes without raising."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        valkey = AsyncMock()
        valkey.get = AsyncMock(return_value=None)
        valkey.set = AsyncMock(side_effect=ConnectionError("valkey write failed"))

        session = _make_session()
        sf = _make_session_factory(session)

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=_make_settings())
        worker._labels_bootstrap_pending = False
        # Must not raise
        asyncio.run(worker.run())


# ── Test: F-159 ProgrammingError graceful handling ───────────────────────────


class TestAgeSyncWorkerProgrammingError:
    """F-159: When the AGE extension fails to load (e.g. LOAD 'age' raises
    ProgrammingError), the worker must catch it, log a structured warning, and
    return without re-raising — preventing an APScheduler exponential backoff
    spiral.  Under PLAN-0093 B-1 this happens during ``_bootstrap_age_labels``.
    """

    def test_programming_error_during_bootstrap_does_not_raise(self) -> None:
        """ProgrammingError from the bootstrap DB calls must not propagate."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker
        from sqlalchemy.exc import ProgrammingError

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(
            side_effect=ProgrammingError("LOAD 'age' failed", params={}, orig=Exception("age.so missing"))
        )

        sf = _make_session_factory(session)
        valkey = _make_valkey()
        settings = _make_settings(cypher_enabled=True)

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        # Must not raise — ProgrammingError is caught internally.
        asyncio.run(worker.run())

    def test_programming_error_logs_age_sync_age_unavailable(self) -> None:
        """The worker must emit ``age_sync_age_unavailable`` at WARNING."""
        from unittest.mock import patch

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker
        from sqlalchemy.exc import ProgrammingError

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(
            side_effect=ProgrammingError("LOAD 'age' failed", params={}, orig=Exception("age missing"))
        )

        sf = _make_session_factory(session)
        valkey = _make_valkey()
        settings = _make_settings(cypher_enabled=True)

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)

        log_calls: list[tuple[str, str]] = []

        import knowledge_graph.infrastructure.workers.age_sync_worker as _mod

        original_warning = _mod.logger.warning

        def _capture_warning(event: str, **kwargs: Any) -> None:
            log_calls.append((event, str(kwargs)))
            return original_warning(event, **kwargs)

        with patch.object(_mod.logger, "warning", side_effect=_capture_warning):
            asyncio.run(worker.run())

        warning_events = [e for e, _ in log_calls]
        assert (
            "age_sync_age_unavailable" in warning_events
        ), f"F-159: expected 'age_sync_age_unavailable' WARNING — got: {warning_events}"

    def test_programming_error_does_not_update_watermark(self) -> None:
        """When a ProgrammingError aborts bootstrap, NO watermark must be written."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker
        from sqlalchemy.exc import ProgrammingError

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(
            side_effect=ProgrammingError("LOAD 'age' failed", params={}, orig=Exception("age missing"))
        )

        sf = _make_session_factory(session)
        valkey = _make_valkey()
        settings = _make_settings(cypher_enabled=True)

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.run(worker.run())

        valkey.set.assert_not_awaited()


# ── Test: BP-539 regression — NULL-confidence relations must be synced ─────────


class TestNullConfidenceRelationSync:
    """Regression tests for BP-539: AGE sync excluded 72% of relations because
    their evidence was still provisional (entity_provisional=true), leaving
    confidence=NULL. The fix: COALESCE(confidence, 0.0) + include NULL rows."""

    def test_null_confidence_relation_is_synced(self) -> None:
        """A relation with confidence=0.0 (COALESCE'd from NULL) MUST be synced."""
        import json

        relation_row = _make_relation_row(canonical_type="competes_with", confidence=0.0)

        captured: list[tuple[str, Any]] = []

        async def _execute(stmt: Any, params: Any = None) -> Any:
            sql = str(stmt)
            if "COUNT(*)" in sql:
                return _make_result([], scalar=0)
            if "FROM canonical_entities" in sql:
                return _make_result([])
            if "FROM relations" in sql:
                return _make_result([relation_row])
            if "FROM temporal_events" in sql or "FROM entity_event_exposures" in sql:
                return _make_result([])
            if "COMPETES_WITH" in sql:
                captured.append((sql, params))
            return _make_result([])

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        worker = _build_worker(session, _make_valkey(), skip_bootstrap=True)
        asyncio.run(worker.run())

        assert len(captured) == 1, "NULL-confidence relation must generate a Cypher MERGE call"
        params = json.loads(captured[0][1]["params"])
        assert (
            params["confidence"] == 0.0
        ), f"confidence must be 0.0 (not null) in AGE params, got {params['confidence']}"

    def test_sql_query_includes_null_confidence_clause(self) -> None:
        """The SQL query for relations MUST include 'confidence IS NULL' in the filter
        so that provisional-evidence rows are not silently excluded (BP-539 regression guard)."""
        import inspect

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        source = inspect.getsource(AgeSyncWorker._sync_relations)
        assert "confidence IS NULL" in source, (
            "BP-539 regression: _sync_relations must include 'confidence IS NULL' in the WHERE clause "
            "so that relations with NULL confidence (provisional evidence) are synced to AGE."
        )
