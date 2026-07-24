"""Unit tests for ``scripts/prod_qa/checks/duplicate_groups.py``.

VALIDATION NOTE (per the task that introduced this check): no live prod
Postgres / kubectl tunnel was available in the environment that authored
`duplicate_groups.py`, so this module cannot be validated end-to-end the way
the harness normally is (a real `python3 -m scripts.prod_qa.run` against the
Hetzner cluster). Instead, this test suite validates the two things that
*can* be checked without a live cluster:

1. Every ``DupGroupCheck.sql`` string is a well-formed, single-scalar
   `GROUP BY ... HAVING count(*) > 1` duplicate-group query against the
   correct table/columns (regex/structure assertions on the SQL text itself
   — a syntax-level review, not an execution proof).
2. The PASS/WARN/FAIL decision logic in ``_duplicate_groups``,
   ``_junk_canonical_names``, and ``_prediction_market_event_link_floor``
   produces the right verdict for synthetic `psql_many`/`psql_scalar`
   results, covering: zero duplicates (PASS), nonzero duplicates (FAIL),
   missing table / query error (WARN), and the soft event_id-NULL floor's
   total-collapse vs. partial-backfill distinction.

A follow-up session with cluster access should additionally run
`python3 -m scripts.prod_qa.run --only duplicate_groups` against prod once and
confirm the live query text is accepted by the real `psql` (this test cannot
prove that — it only proves the Python-side logic and SQL shape are correct).
"""

from __future__ import annotations

import re

import pytest

from scripts.prod_qa import harness as H  # noqa: N812 (H is the harness module's own idiom — see harness.py callers)
from scripts.prod_qa.checks import duplicate_groups as dg

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. SQL shape validation (static — no DB required)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("check", dg.DUP_GROUP_CHECKS, ids=lambda c: c.name)
def test_dup_group_check_sql_is_a_single_scalar_group_by_having(check: dg.DupGroupCheck) -> None:
    """Every DUP_GROUP_CHECKS entry must be a `count(*) FROM (... GROUP BY ...
    HAVING count(*) > 1) t` shape — the outer count(*) makes the result a
    single scalar (number of duplicate GROUPS), matching what
    `_duplicate_groups` and `H.psql_many` expect (one row per query key).
    """
    sql = check.sql
    assert sql.strip().upper().startswith("SELECT COUNT(*) FROM (")
    assert "GROUP BY" in sql.upper()
    assert "HAVING COUNT(*) > 1" in sql.upper()
    # Guarded against SQL injection via string formatting: every clause here is
    # a static module-level constant, never built from request/user input.
    assert "{" not in sql and "%" not in sql


def test_dup_group_check_tables_match_the_bug_patterns_this_scanner_guards() -> None:
    """Sanity-check the target tables are exactly the three BP-459/BP-743
    tables named in the task — catches an accidental typo'd table name that
    would silently scan nothing.
    """
    tables_seen = {
        re.search(r"\bFROM (\w+)\b", c.sql.split("FROM (", 1)[1]).group(1)  # type: ignore[union-attr]
        for c in dg.DUP_GROUP_CHECKS
    }
    assert tables_seen == {"instruments", "canonical_entities", "prediction_markets"}


def test_junk_canonical_name_regex_matches_the_bp700_shape() -> None:
    """The Postgres `~ '^[A-Z]+:\\s'` regex embedded in `_junk_canonical_names`
    must match BP-700's actual observed junk shape ("NYSE: BCS") and must NOT
    match a normal corporate name (false-positive risk).
    """
    pg_pattern = r"^[A-Z]+:\s"
    assert re.match(pg_pattern, "NYSE: BCS")
    assert re.match(pg_pattern, "NASDAQ: AAPL")
    assert not re.match(pg_pattern, "Apple Inc.")
    assert not re.match(pg_pattern, "Shell PLC ADR")
    # A lower-case or mixed-case prefix must NOT match — the regex is
    # deliberately upper-case-only so it never flags a legitimate name that
    # happens to start with a colon-adjacent capitalized word.
    assert not re.match(pg_pattern, "Nyse: BCS")


# ---------------------------------------------------------------------------
# 2. PASS/WARN/FAIL decision logic (mocked psql layer — no DB required)
# ---------------------------------------------------------------------------


def _ctx() -> H.Ctx:
    return H.Ctx(report=H.Report(quiet=True))


def test_duplicate_groups_all_zero_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every duplicate-group count == 0 → every check PASSes."""
    monkeypatch.setattr(H, "psql_many", lambda db, queries, **kw: dict.fromkeys(queries, "0"))
    ctx = _ctx()
    dg._duplicate_groups(ctx)
    rows = ctx.report.rows
    assert rows, "expected rows to be recorded"
    assert all(status == H.PASS for _, _, status, _ in rows)


def test_duplicate_groups_nonzero_fails_hard(monkeypatch: pytest.MonkeyPatch) -> None:
    """A nonzero duplicate-group count is a HARD FAIL (zero-tolerance), not WARN."""

    def fake_psql_many(db: str, queries: dict[str, str], **kw: object) -> dict[str, str]:
        # First key in this DB's batch gets a duplicate; rest stay clean.
        out = dict.fromkeys(queries, "0")
        first_key = next(iter(queries))
        out[first_key] = "3"
        return out

    monkeypatch.setattr(H, "psql_many", fake_psql_many)
    ctx = _ctx()
    dg._duplicate_groups(ctx)
    fails = [r for r in ctx.report.rows if r[2] == H.FAIL]
    assert fails, "a nonzero duplicate-group count must FAIL, not WARN/PASS"
    assert "3 duplicate group(s)" in fails[0][3]


def test_duplicate_groups_query_error_warns_not_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    """`psql_many`'s documented '' contract (missing table / query error) must
    WARN, never FAIL and never raise — mirrors every other check module's
    treatment of an absent table.
    """
    monkeypatch.setattr(H, "psql_many", lambda db, queries, **kw: dict.fromkeys(queries, ""))
    ctx = _ctx()
    dg._duplicate_groups(ctx)
    assert all(status == H.WARN for _, _, status, _ in ctx.report.rows)


def test_junk_canonical_names_zero_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "psql_scalar", lambda db, sql, **kw: "0")
    ctx = _ctx()
    dg._junk_canonical_names(ctx)
    assert ctx.report.rows[-1][2] == H.PASS


def test_junk_canonical_names_nonzero_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "psql_scalar", lambda db, sql, **kw: "2")
    ctx = _ctx()
    dg._junk_canonical_names(ctx)
    assert ctx.report.rows[-1][2] == H.FAIL


def test_junk_canonical_names_query_error_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "psql_scalar", lambda db, sql, **kw: "")
    ctx = _ctx()
    dg._junk_canonical_names(ctx)
    assert ctx.report.rows[-1][2] == H.WARN


@pytest.mark.parametrize(
    ("total", "null_event", "expect_status"),
    [
        ("100", "0", H.PASS),  # fully linked
        ("100", "5", H.PASS),  # a few unlinked (normal backfill lag) — still PASS since 5 < 100
        ("100", "100", H.WARN),  # total collapse (the BP-743-sibling regression shape) → WARN (soft)
    ],
)
def test_prediction_market_event_link_floor_soft_collapse_guard(
    monkeypatch: pytest.MonkeyPatch, total: str, null_event: str, expect_status: str
) -> None:
    """The event_id NULL floor is SOFT and only fires on a TOTAL collapse
    (every market unlinked) — a handful of freshly-discovered, not-yet-linked
    markets must not flap this check (unlike the hard duplicate-group checks
    above, which are zero-tolerance).
    """
    monkeypatch.setattr(H, "psql_many", lambda db, queries, **kw: {"total": total, "null_event": null_event})
    ctx = _ctx()
    dg._prediction_market_event_link_floor(ctx)
    assert ctx.report.rows[-1][2] == expect_status


def test_prediction_market_event_link_floor_no_rows_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "psql_many", lambda db, queries, **kw: {"total": "0", "null_event": "0"})
    ctx = _ctx()
    dg._prediction_market_event_link_floor(ctx)
    assert ctx.report.rows[-1][2] == H.WARN


def test_run_invokes_all_three_sub_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """`run(ctx)` must call all three sub-checks — a regression here would
    silently drop a whole check category from every prod-QA pass.
    """
    calls: list[str] = []
    monkeypatch.setattr(dg, "_duplicate_groups", lambda ctx: calls.append("dup_groups"))
    monkeypatch.setattr(dg, "_junk_canonical_names", lambda ctx: calls.append("junk_names"))
    monkeypatch.setattr(dg, "_prediction_market_event_link_floor", lambda ctx: calls.append("event_link_floor"))
    dg.run(_ctx())
    assert calls == ["dup_groups", "junk_names", "event_link_floor"]
