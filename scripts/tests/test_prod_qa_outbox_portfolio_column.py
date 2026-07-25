"""Regression test for the portfolio_db outbox-column bug (2026-07-25 infra investigation).

``_outbox_dispatchers`` (scripts/prod_qa/checks/coarse.py) ran a hardcoded
``dispatched_at``-based query against every DB in ``OUTBOX_DBS`` — but
portfolio_db's ``outbox_events`` tracks completion via ``published_at``
(services/portfolio/src/portfolio/infrastructure/db/models/outbox.py), an
older column name that predates the ``dispatched_at`` rename every other
service uses. The wrong column name made every portfolio_db query error;
``psql_many`` swallows psql errors and maps the key to ``""``, which the
"no outbox_events table in this DB" skip then silently treated as "nothing to
check" — portfolio's outbox drain was never actually evaluated, so a wedged
portfolio dispatcher would have reported "all outboxes drained" instead of
paging.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.prod_qa import harness as H  # noqa: N812 (H is the harness module's own idiom)
from scripts.prod_qa.checks import coarse

pytestmark = pytest.mark.unit


def test_portfolio_db_query_uses_published_at_not_dispatched_at() -> None:
    """The queries built for portfolio_db must reference published_at."""
    captured: dict[str, dict[str, str]] = {}

    def fake_psql_many(db: str, queries: dict[str, str], timeout: int = 90) -> dict[str, str]:
        captured[db] = queries
        if db == "portfolio_db":
            return {"aged": "0", "undispatched": "0", "oldest_min": "0"}
        return {"aged": "", "undispatched": "", "oldest_min": ""}

    report = H.Report()
    with patch.object(H, "psql_many", side_effect=fake_psql_many):
        coarse._outbox_dispatchers(report)

    assert "portfolio_db" in captured
    portfolio_queries = captured["portfolio_db"]
    for key, sql in portfolio_queries.items():
        assert "published_at" in sql, f"portfolio_db query {key!r} must use published_at, got: {sql}"
        assert "dispatched_at" not in sql, f"portfolio_db query {key!r} must NOT use dispatched_at, got: {sql}"


def test_other_dbs_still_use_dispatched_at() -> None:
    """Every non-portfolio DB in OUTBOX_DBS must still query dispatched_at (no regression)."""
    from scripts.prod_qa import thresholds as T  # noqa: N812 (T is the thresholds module's own idiom)

    captured: dict[str, dict[str, str]] = {}

    def fake_psql_many(db: str, queries: dict[str, str], timeout: int = 90) -> dict[str, str]:
        captured[db] = queries
        return {"aged": "0", "undispatched": "0", "oldest_min": "0"}

    report = H.Report()
    with patch.object(H, "psql_many", side_effect=fake_psql_many):
        coarse._outbox_dispatchers(report)

    non_portfolio = [db for db in T.OUTBOX_DBS if db != "portfolio_db"]
    assert non_portfolio, "expected at least one non-portfolio DB in OUTBOX_DBS to validate against"
    for db in non_portfolio:
        for key, sql in captured[db].items():
            assert "dispatched_at" in sql, f"{db} query {key!r} must use dispatched_at, got: {sql}"


def test_portfolio_db_wedged_outbox_is_no_longer_silently_skipped() -> None:
    """A genuinely wedged portfolio_db outbox must surface as FAIL, not be skipped.

    Before the fix, the wrong column name meant psql_many's error response
    (mapped to "") made this check treat portfolio_db as "no outbox_events
    table" and skip it entirely — a wedged dispatcher would report healthy.
    """
    from scripts.prod_qa import thresholds as T  # noqa: N812 (T is the thresholds module's own idiom)

    def fake_psql_many(db: str, queries: dict[str, str], timeout: int = 90) -> dict[str, str]:
        if db == "portfolio_db":
            # Simulate a badly wedged dispatcher: backlog past the FAIL threshold.
            return {
                "aged": str(T.OUTBOX_TABLE_BACKLOG_FAIL + 1),
                "undispatched": str(T.OUTBOX_TABLE_BACKLOG_FAIL + 1),
                "oldest_min": str(T.OUTBOX_AGE_FAIL_MIN + 5),
            }
        return {"aged": "0", "undispatched": "0", "oldest_min": "0"}

    report = H.Report()
    with patch.object(H, "psql_many", side_effect=fake_psql_many):
        coarse._outbox_dispatchers(report)

    portfolio_rows = [row for row in report.rows if "portfolio_db" in row[3]]
    assert portfolio_rows, "portfolio_db's wedged backlog must appear in the report, not be silently skipped"
