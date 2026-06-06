"""Shared fixtures for PLAN-0093 Wave G-1 validation tests.

Provides synchronous ``psycopg`` connection factories for the two databases
these SLO tests touch:

* ``intelligence_db`` — used by AGE coverage, relations DQ, enrichment DQ,
  path-insight DQ tests.
* ``nlp_db`` — used by the NLP DQ tests.

Connections are session-scoped because the SLO tests are read-only — there's
no cross-test mutation to isolate. The connection is opened with
``autocommit=True`` because some queries (notably AGE Cypher invocations that
require ``LOAD 'age'`` + ``SET search_path``) prefer to run outside an
implicit transaction.

Skip strategy
-------------
We use *runtime* ``pytest.skip`` calls inside fixtures (NEVER
``@pytest.mark.skip``) so the tests are always *collected* but skipped cleanly
when their DB URL env var is unset. This satisfies R19 (never delete/skip/
weaken tests) — the tests still run in any environment that has the live DBs
wired up; we just degrade gracefully elsewhere.

Env var contract
----------------
``INTELLIGENCE_DB_URL_TEST`` (preferred) or ``INTELLIGENCE_DB_URL`` → connection
string for ``intelligence_db``. Same precedence for ``NLP_DB_URL_TEST`` /
``NLP_DB_URL``. The async driver suffix (``+asyncpg`` / ``+psycopg``) is
stripped automatically so psycopg sync accepts the URL.

Optional ``KNOWLEDGE_GRAPH_METRICS_URL`` → full URL to the ``/metrics`` Prometheus
endpoint of the knowledge-graph service; the path-insight test uses this to
verify ``path_insight_explanation_pending_total`` is exposed. When unset,
defaults to ``http://localhost:8007/metrics`` (the dev compose port).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

# psycopg import is deferred-but-not-optional: every test in this directory
# needs it. If it's missing we still want collection to succeed, so we import
# lazily inside fixtures and surface a clean skip.
if TYPE_CHECKING:  # pragma: no cover — typing only
    import psycopg

# ---------------------------------------------------------------------------
# Repo-root resolution. ``tests/validation/`` lives at repo root, so two
# parents back from this file is the repo root. Used by env loading helpers
# (currently unused but kept for parity with tests/architecture/conftest.py).
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# URL helpers — strip async-driver suffixes so sync psycopg accepts the URL.
# ---------------------------------------------------------------------------


def _normalize_sync_url(url: str) -> str:
    """Return *url* with any SQLAlchemy async-driver suffix stripped.

    The platform stores DB URLs in the form ``postgresql+asyncpg://…`` for the
    async session factories. Synchronous psycopg doesn't understand the
    ``+asyncpg`` / ``+psycopg`` suffix and would raise ``OperationalError``
    on connect, so we normalize before handing the URL off.
    """
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


def _intelligence_db_url() -> str | None:
    """Return a sync psycopg URL for intelligence_db, or ``None`` if unset."""
    url = os.environ.get("INTELLIGENCE_DB_URL_TEST") or os.environ.get("INTELLIGENCE_DB_URL")
    return _normalize_sync_url(url) if url else None


def _nlp_db_url() -> str | None:
    """Return a sync psycopg URL for nlp_db, or ``None`` if unset."""
    url = os.environ.get("NLP_DB_URL_TEST") or os.environ.get("NLP_DB_URL")
    return _normalize_sync_url(url) if url else None


# ---------------------------------------------------------------------------
# psycopg lazy-import helper. We do this in one place so each fixture can call
# it and get an identical skip-with-reason behaviour.
# ---------------------------------------------------------------------------


def _import_psycopg():  # type: ignore[no-untyped-def]
    """Import psycopg lazily; skip the test cleanly if it's not installed."""
    try:
        import psycopg  # — lazy by design
    except ImportError:  # pragma: no cover — psycopg is in venv per F-1
        pytest.skip("psycopg not installed — validation SLO tests require psycopg")
    return psycopg


# ---------------------------------------------------------------------------
# Connection fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def intelligence_db_conn() -> Iterator[psycopg.Connection]:
    """Yield a sync psycopg connection to ``intelligence_db``.

    Skips when:
    * psycopg is not installed (returns clean skip in fixture).
    * ``INTELLIGENCE_DB_URL_TEST`` / ``INTELLIGENCE_DB_URL`` is unset.
    * Connection fails (DB unreachable in this env).

    Uses ``autocommit=True`` because the AGE coverage test mixes
    ``LOAD 'age'`` + ``SET search_path`` + Cypher SELECTs in the same session
    and we don't want implicit transactions getting in the way.
    """
    psycopg = _import_psycopg()
    url = _intelligence_db_url()
    if not url:
        pytest.skip(
            "INTELLIGENCE_DB_URL_TEST not set — skipping intelligence_db SLO test "
            "(this is expected in CI without a live DB)"
        )
    try:
        conn = psycopg.connect(url, autocommit=True)
    except psycopg.OperationalError as exc:  # pragma: no cover — env-dependent
        pytest.skip(f"could not connect to intelligence_db at {url!r}: {exc}")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def age_session(intelligence_db_conn: psycopg.Connection) -> psycopg.Connection:
    """Return the intelligence_db connection with AGE loaded + search_path set.

    Apache AGE requires both ``LOAD 'age'`` and ``SET search_path = ag_catalog,
    "$user", public`` on every session before any Cypher invocation. We do
    that here once per session, then hand the same connection back to AGE
    tests so they can issue Cypher SELECTs directly.

    If AGE is not installed on the test DB, the ``LOAD 'age'`` call will fail
    with ``FileNotFoundError`` / ``UndefinedFile`` — we surface that as a
    clean skip so the test set still runs against non-AGE Postgres instances.
    """
    psycopg = _import_psycopg()
    try:
        with intelligence_db_conn.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute('SET search_path = ag_catalog, "$user", public')
    except psycopg.Error as exc:  # pragma: no cover — env-dependent
        pytest.skip(f"Apache AGE not available on intelligence_db: {exc}")
    return intelligence_db_conn


@pytest.fixture(scope="session")
def nlp_db_conn() -> Iterator[psycopg.Connection]:
    """Yield a sync psycopg connection to ``nlp_db``.

    Same skip strategy as ``intelligence_db_conn``.
    """
    psycopg = _import_psycopg()
    url = _nlp_db_url()
    if not url:
        pytest.skip("NLP_DB_URL_TEST not set — skipping nlp_db SLO test " "(this is expected in CI without a live DB)")
    try:
        conn = psycopg.connect(url, autocommit=True)
    except psycopg.OperationalError as exc:  # pragma: no cover — env-dependent
        pytest.skip(f"could not connect to nlp_db at {url!r}: {exc}")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tiny query helper. The SLO tests mostly issue ``SELECT count(*) …`` queries
# and immediately compare the result against a threshold; this helper makes
# those call sites a one-liner.
# ---------------------------------------------------------------------------


def scalar(conn: psycopg.Connection, sql: str, params: dict[str, object] | None = None) -> Any:
    """Execute *sql* and return the first column of the first row.

    Used for ``SELECT count(*)`` and similar single-value queries. Returns
    ``None`` if the result set is empty.

    The return type is ``Any`` deliberately so call sites can immediately
    ``int(...)`` / ``float(...)`` / ``str(...)`` the scalar without a
    ``cast(...)`` ceremony — these are tests, not domain code.
    """
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        row = cur.fetchone()
    if row is None:
        return None
    return row[0]
