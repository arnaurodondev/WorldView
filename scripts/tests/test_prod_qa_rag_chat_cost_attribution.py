"""Tests for the BP-740-generalization cost-attribution NULL-ratio guard.

BP-740 (`docs/BUG_PATTERNS.md`): `rag_db.llm_usage_log.chat_thread_id` was
NULL on 100% of rows for a 7-day prod window before anyone noticed — found
only by a one-off manual audit query. The fix itself
(`services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`)
already has solid unit + integration regression coverage. What was missing is
an automated prod-QA check that would catch the NEXT similarly-shaped
attribution bug — this test module covers the new check added to
`scripts/prod_qa/checks/rag_chat.py::_cost_attribution_null_guard`.

No live/testcontainers Postgres is exercised here: the check's SQL is plain,
already-conventional `psql_many`-shaped aggregate queries (identical pattern to
every other check in this file, none of which carry a DB-level test either —
see e.g. `rag_db persistence schema present` a few lines above the new
check). What IS meaningfully testable in isolation, and what this module
covers exhaustively, is the check's pure decision logic
(`_classify_null_ratio`): given row/NULL counts and per-column thresholds,
does it return the right PASS/WARN/FAIL verdict? That logic is where a
threshold miscalibration or an off-by-one in the ratio math would actually
hide a regression, independent of whatever the live SQL happens to return.
"""

from __future__ import annotations

import pytest

from scripts.prod_qa import harness as h
from scripts.prod_qa.checks import rag_chat as c_rag

pytestmark = pytest.mark.unit


# ── _classify_null_ratio: too-little-signal guard ────────────────────────────


def test_below_min_rows_is_warn_not_a_verdict() -> None:
    """Fewer rows than MIN_ROWS in the window → WARN ('skipped'), never FAIL —
    a quiet night should not masquerade as a broken invariant."""
    status, detail = c_rag._classify_null_ratio(total=5, nulls=5, warn_pct=30.0, fail_pct=95.0, min_rows=20)
    assert status == h.WARN
    assert "skipped" in detail


def test_negative_total_from_failed_query_is_warn() -> None:
    """`H.as_int` defaults to -1 on a failed/absent psql result; that must not
    be misread as '-1 NULL rows out of -1 total' producing a bogus ratio."""
    status, _ = c_rag._classify_null_ratio(total=-1, nulls=-1, warn_pct=30.0, fail_pct=95.0, min_rows=20)
    assert status == h.WARN


# ── _classify_null_ratio: FAIL-capable column (chat_thread_id-shaped) ────────


def test_bp740_signature_100pct_null_fails() -> None:
    """The literal BP-740 finding: 100% of rows NULL over the window → FAIL."""
    status, detail = c_rag._classify_null_ratio(total=1000, nulls=1000, warn_pct=30.0, fail_pct=95.0, min_rows=20)
    assert status == h.FAIL
    assert "1000/1000" in detail
    assert "100.0%" in detail


def test_near_total_null_above_fail_floor_fails() -> None:
    """Not literally 100% — a genuine near-total regression must still FAIL,
    not hide behind requiring an exact 100% match."""
    status, _ = c_rag._classify_null_ratio(total=1000, nulls=970, warn_pct=30.0, fail_pct=95.0, min_rows=20)
    assert status == h.FAIL


def test_partial_null_ratio_between_warn_and_fail_warns() -> None:
    """A ratio in the WARN band (above warn_pct, below fail_pct) WARNs — the
    partial-NULL case the task explicitly calls out (e.g. some legitimate
    non-chat-turn gateway-relayed rows)."""
    status, detail = c_rag._classify_null_ratio(total=1000, nulls=500, warn_pct=30.0, fail_pct=95.0, min_rows=20)
    assert status == h.WARN
    assert "500/1000" in detail


def test_low_null_ratio_passes() -> None:
    """Low NULL ratio (below warn_pct) → PASS — the healthy steady state after
    the BP-740 fix, where only a small gateway-relayed minority is NULL."""
    status, _ = c_rag._classify_null_ratio(total=1000, nulls=50, warn_pct=30.0, fail_pct=95.0, min_rows=20)
    assert status == h.PASS


def test_exact_threshold_boundaries_are_inclusive() -> None:
    """Ratio exactly AT warn_pct/fail_pct must trip that tier (>=), not require
    strictly-above — a boundary value should not silently slip through."""
    warn_boundary, _ = c_rag._classify_null_ratio(total=100, nulls=30, warn_pct=30.0, fail_pct=95.0, min_rows=20)
    assert warn_boundary == h.WARN
    fail_boundary, _ = c_rag._classify_null_ratio(total=100, nulls=95, warn_pct=30.0, fail_pct=95.0, min_rows=20)
    assert fail_boundary == h.FAIL


# ── _classify_null_ratio: WARN-only column (user_id-shaped) ─────────────────


def test_warn_only_column_never_fails_even_at_100pct_null() -> None:
    """`fail_pct=None` models a column that is legitimately nullable BY DESIGN
    (user_id for system/background calls, per migration 0010's docstring) —
    it must WARN, never FAIL, no matter how high the ratio climbs. This is the
    "calibrate rather than assume zero-tolerance" requirement: a column with a
    real legitimate-NULL population must not alarm at the same severity as a
    column (chat_thread_id) whose NULLs are a genuine defect."""
    status, detail = c_rag._classify_null_ratio(total=1000, nulls=1000, warn_pct=80.0, fail_pct=None, min_rows=20)
    assert status == h.WARN
    assert "1000/1000" in detail


def test_warn_only_column_passes_below_its_warn_floor() -> None:
    status, _ = c_rag._classify_null_ratio(total=1000, nulls=100, warn_pct=80.0, fail_pct=None, min_rows=20)
    assert status == h.PASS


# ── Generic-over-a-future-column property: the check has no column-name logic ─


def test_classify_is_column_agnostic() -> None:
    """The decision function takes no column name — the SAME logic judges any
    future cost-attribution column added to `RAG_COST_ATTR_NULL_COLUMNS`
    without a code change, which is the actual point of the exercise (the
    check generalizes beyond chat_thread_id/user_id, not just re-checks them)."""
    hypothetical_future_column_result = c_rag._classify_null_ratio(
        total=500, nulls=480, warn_pct=30.0, fail_pct=95.0, min_rows=20
    )
    chat_thread_id_shaped_result = c_rag._classify_null_ratio(
        total=500, nulls=480, warn_pct=30.0, fail_pct=95.0, min_rows=20
    )
    assert hypothetical_future_column_result == chat_thread_id_shaped_result == (h.FAIL, "480/500 NULL (96.0%)")


# ── Threshold table sanity (catches a malformed entry before it ships) ───────


def test_threshold_table_entries_are_well_formed() -> None:
    """Every configured column has a name, a warn_pct in (0, 100], and either
    no fail_pct or a fail_pct strictly above its own warn_pct (otherwise the
    WARN tier would be unreachable — FAIL would always fire first)."""
    from scripts.prod_qa import thresholds as t

    assert len(t.RAG_COST_ATTR_NULL_COLUMNS) >= 2  # at minimum chat_thread_id + user_id (BP-740's two fields)
    seen_columns = set()
    for col, warn_pct, fail_pct in t.RAG_COST_ATTR_NULL_COLUMNS:
        assert col not in seen_columns, f"duplicate column entry: {col}"
        seen_columns.add(col)
        assert 0.0 < warn_pct <= 100.0
        if fail_pct is not None:
            assert fail_pct > warn_pct
            assert fail_pct <= 100.0
    assert "chat_thread_id" in seen_columns
    assert "user_id" in seen_columns


def test_chat_thread_id_can_fail_but_user_id_cannot() -> None:
    """Pin the calibration decision directly: chat_thread_id (the BP-740
    field) is FAIL-capable; user_id (legitimately nullable by design) is not."""
    from scripts.prod_qa import thresholds as t

    by_col = {col: fail_pct for col, _warn_pct, fail_pct in t.RAG_COST_ATTR_NULL_COLUMNS}
    assert by_col["chat_thread_id"] is not None
    assert by_col["user_id"] is None
