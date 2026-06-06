"""PLAN-0093 F-1: PREPARE every repository SELECT against the live schema.

Why this exists
---------------
F-LOG-MIGRATION-001 (2026-05-23 audit) found ~10/min Postgres errors of the form
``column "X" does not exist`` triggered by repository SQL that drifted from the
schema between migrations 0026-0029 and beyond. These errors only surface at
runtime — lint, mypy, and unit tests all pass because Python never parses the
SQL string. The fix is to ask Postgres itself to parse + plan every SQL string
the repos own, *without executing it*, via ``PREPARE``. Any reference to a
non-existent column / table / function trips ``UndefinedColumn`` /
``UndefinedTable`` and we record the file:line.

How it works
------------
1. F-1-01: ``repository_sql_extractor`` walks every repository file and pulls
   literal SQL.
2. F-1-02 (this file): for each extracted statement, run
   ``PREPARE _qatest AS <sql>; DEALLOCATE _qatest`` against the test DB.
3. F-1-03: a session-scoped fixture runs ``alembic upgrade head`` on
   *intelligence_db* and *nlp_db* test databases first, so PREPARE sees the
   true head schema.

Notes on routing
----------------
Worldview has three logical DBs touched by repositories:

* ``intelligence_db`` — owned by ``intelligence-migrations`` (S6/S7 read/write).
* ``nlp_db`` — owned by ``nlp-pipeline`` Alembic.
* Per-service DBs (portfolio, content-store, market-data, …) — each service
  owns its own DDL.

For F-1 we focus the PREPARE pass on the **intelligence/nlp** repositories,
because those are where F-LOG-MIGRATION-001 was observed (~10/min). The same
pattern can be extended to the per-service DBs in a later wave by registering
additional alembic ↔ repository-root mappings in ``_DB_ROUTES``.

Skip rules
----------
- If the test DBs are not reachable (``INTELLIGENCE_DB_URL`` / ``NLP_DB_URL``
  not set, no local Postgres) the integration tests are skipped with a clear
  message — they still run in CI where the DBs exist.
- SQL containing AGE / Cypher (``cypher(...)``) is skipped: AGE's parser is not
  plain SQL and ``PREPARE`` will reject it for reasons unrelated to schema.
- Temp tables created in the same SQL block are honoured by ``PREPARE`` (it
  parses against the catalogs at PREPARE time, after the implicit txn starts).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.architecture.repository_sql_extractor import (
    ExtractedSQL,
    extract_sql_from_file,
    extract_sql_from_repositories,
    repository_files,
)

# ---------------------------------------------------------------------------
# Repo-root resolution. ``tests/architecture/`` lives at repo root.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Routing: which repository roots target which DB.
# ---------------------------------------------------------------------------

_DB_ROUTES: dict[str, tuple[str, ...]] = {
    # Anything under these two repository roots executes against intelligence_db.
    "intelligence_db": (
        "services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories",
        "services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories",
    ),
    "nlp_db": ("services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories",),
}


def _route_for(path: Path) -> str | None:
    """Return the DB key for ``path``, or ``None`` if the file isn't routed."""
    rel = path.relative_to(REPO_ROOT).as_posix()
    for db, roots in _DB_ROUTES.items():
        for root in roots:
            if rel.startswith(root):
                return db
    return None


# ---------------------------------------------------------------------------
# SQL filters — skip statements PREPARE cannot validate.
# ---------------------------------------------------------------------------

# Apache AGE Cypher queries pass through cypher(...) — PREPARE rejects the
# nested Cypher dialect; we trust AGE's own unit tests instead.
_AGE_PATTERN = re.compile(r"\bcypher\s*\(", re.IGNORECASE)

# Statements that are not really one statement (multiple ``;``) — PREPARE only
# accepts a single command, so we skip multi-statement strings.
_MULTI_STMT = re.compile(r";\s*\S")


def _should_skip(sql: str) -> str | None:
    """Return a human-readable reason if PREPARE cannot validate this SQL."""
    if _AGE_PATTERN.search(sql):
        return "AGE/Cypher (not plain SQL)"
    # Allow the trailing ; that authors sometimes include.
    stripped = sql.strip().rstrip(";")
    if _MULTI_STMT.search(stripped):
        return "multi-statement SQL"
    # VALUES-only literals (used in seed data) are not PREPARE-validatable on
    # their own — they're typically embedded in INSERT, but a raw ``VALUES``
    # block exists in a few places. Skip with a note.
    if stripped.upper().startswith("VALUES"):
        return "bare VALUES clause"
    return None


# ---------------------------------------------------------------------------
# Placeholder translation — :name → $N (FIX-LIVE-F / INV-LIVE-B Part 1).
# ---------------------------------------------------------------------------
#
# Why this exists
# ---------------
# SQLAlchemy ``text()`` uses ``:name`` placeholders. Postgres ``PREPARE``
# itself only accepts ``$N`` positional placeholders — feeding a raw
# ``:name`` SQL into PREPARE produces a syntax error at the colon, e.g.::
#
#     ERROR: syntax error at or near ":"
#
# That noise was the root cause of 60+ false positives in the Phase 5c
# PREPARE pass. The fix is a *small* purpose-built translator: walk the SQL
# left-to-right, replace ``:name`` with ``$N`` (re-using ``$N`` for repeated
# names), but **skip** characters that live inside single-quoted strings,
# inside ``$$...$$`` dollar-quoted blocks, or right after ``::`` Postgres
# type casts.
#
# We intentionally avoid a full SQL parser — the rules below cover every
# pattern observed in worldview repository SQL.

# Match a bare ``:name`` not preceded by another ``:`` (which would make it
# a ``::TYPE`` cast) and not preceded by an identifier char (defence in depth).
_NAMED_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")


def _translate_named_to_positional(sql: str) -> str:
    """Translate SQLAlchemy ``:name`` placeholders into Postgres ``$N``.

    Rules (in order):

    * Inside ``'...'`` single-quoted string literals: never translate.
      String literals may legitimately contain colons (e.g. ``':status'``
      in a WHERE clause comparing against a literal value).
    * Inside ``$$...$$`` dollar-quoted blocks (used for plpgsql function
      bodies and AGE Cypher payloads): never translate.
    * After ``::`` (Postgres type-cast prefix): never translate. The
      regex ``_NAMED_PARAM`` already guards against this, but we double-
      check in the per-segment walk for robustness.
    * Repeated names re-use the same ``$N`` slot (matches asyncpg
      semantics and SQLAlchemy's compile-to-positional behaviour).

    Returns the translated SQL. If there are no ``:name`` placeholders,
    the original string is returned unchanged.
    """
    # Fast path — no colons at all, nothing to do.
    if ":" not in sql:
        return sql

    # We segment the SQL into translatable and non-translatable regions:
    #   * ``'…'`` single-quoted strings        → opaque
    #   * ``$$…$$`` dollar-quoted blocks       → opaque
    #   * Everything else                       → run _NAMED_PARAM substitution
    #
    # Postgres also supports ``E'…'`` escape strings and ``$tag$…$tag$``
    # tagged dollar quoting; both are rare in worldview SQL and the simple
    # rules above cover every existing case. If a future repository needs
    # one of those forms, extend this routine — don't reach for a full
    # SQL parser unless complexity demands it.
    out: list[str] = []
    # Name → $N mapping; preserves first-seen ordering.
    name_to_idx: dict[str, int] = {}

    def _sub_named(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in name_to_idx:
            # Slots are 1-indexed per Postgres convention.
            name_to_idx[name] = len(name_to_idx) + 1
        return f"${name_to_idx[name]}"

    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        # ── $$ dollar-quoted block ──────────────────────────────────────
        # Look for an opening "$$"; if found, copy through (and including)
        # the next "$$" verbatim.
        if ch == "$" and i + 1 < n and sql[i + 1] == "$":
            end = sql.find("$$", i + 2)
            if end == -1:
                # Unterminated — copy the rest verbatim and stop.
                out.append(sql[i:])
                break
            # Copy the entire $$…$$ block (including delimiters) verbatim.
            out.append(sql[i : end + 2])
            i = end + 2
            continue
        # ── single-quoted string literal ────────────────────────────────
        if ch == "'":
            j = i + 1
            while j < n:
                # SQL escapes '' inside a literal — skip the pair as a unit.
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    j += 1
                    break
                j += 1
            out.append(sql[i:j])
            i = j
            continue
        # ── translatable region: find the next opaque boundary ──────────
        # Scan until the next "'" or "$$" (or EOF), then translate that slice.
        j = i
        while j < n and sql[j] != "'" and not (sql[j] == "$" and j + 1 < n and sql[j + 1] == "$"):
            j += 1
        segment = sql[i:j]
        out.append(_NAMED_PARAM.sub(_sub_named, segment))
        i = j
    return "".join(out)


# ---------------------------------------------------------------------------
# Unit tests for the extractor (T-F-1-01 acceptance criteria).
# ---------------------------------------------------------------------------


def test_extractor_finds_sa_text_sql() -> None:
    """The extractor must find at least one known SELECT in a known file."""
    target = (
        REPO_ROOT
        / "services/knowledge-graph/src/knowledge_graph/infrastructure"
        / "intelligence_db/repositories/entity_alias.py"
    )
    extracted, _ = extract_sql_from_file(target)
    assert any(
        "FROM entity_aliases" in item.sql_text.replace("\n", " ") for item in extracted
    ), "entity_alias.py is known to SELECT FROM entity_aliases; extractor missed it"


def test_extractor_handles_multiline_strings(tmp_path: Path) -> None:
    """Extractor must capture multi-line literal SQL inside a text(...) call."""
    fixture = tmp_path / "fake_repo.py"
    fixture.write_text(
        '''
from sqlalchemy import text

QUERY = text("""
SELECT a, b, c
FROM   widgets
WHERE  status = :status
""")
''',
        encoding="utf-8",
    )
    extracted, _ = extract_sql_from_file(fixture)
    assert len(extracted) == 1
    sql_one_line = extracted[0].sql_text.replace("\n", " ")
    assert "SELECT a, b, c" in sql_one_line
    assert "FROM   widgets" in sql_one_line
    assert extracted[0].kind == "named"  # :status placeholder


def test_extractor_skips_string_concat(tmp_path: Path) -> None:
    """Dynamically-built SQL (concat with non-constant) is recorded as skipped."""
    fixture = tmp_path / "fake_repo.py"
    fixture.write_text(
        """
def build(table_name: str) -> str:
    # Non-literal concat — extractor must NOT include this in PREPARE pass.
    return "SELECT * FROM " + table_name
""",
        encoding="utf-8",
    )
    extracted, skipped = extract_sql_from_file(fixture)
    # The literal "SELECT * FROM " by itself starts with SELECT, so it WOULD
    # match _looks_like_sql — but it's incomplete. Our extractor records it as
    # a standalone constant; the value of this test is that the *concatenation*
    # is also flagged as skipped.
    assert any(
        "string-concatenated" in s.reason or "dynamic" in s.reason for s in skipped
    ), f"expected concat to be flagged as skipped, got {skipped!r}"


def test_extractor_finds_at_least_100_statements() -> None:
    """Acceptance criterion: ≥ 100 SQL statements across the repo."""
    extracted, _ = extract_sql_from_repositories(REPO_ROOT)
    assert len(extracted) >= 100, (
        f"Expected ≥ 100 extracted SQL statements, got {len(extracted)}. "
        f"Either repositories drastically shrank, or the extractor regressed."
    )


def test_repository_files_walker_finds_files() -> None:
    """Sanity check: the walker discovers ≥ 50 repository files."""
    files = repository_files(REPO_ROOT)
    assert len(files) >= 50, (
        f"Expected ≥ 50 repository files, got {len(files)}. " f"Check the glob pattern in repository_sql_extractor.py."
    )


# ---------------------------------------------------------------------------
# Integration test (T-F-1-02 / T-F-1-03).
# ---------------------------------------------------------------------------

# We import psycopg lazily because the architecture test suite must remain
# runnable in environments without a Postgres client library installed.
try:
    import psycopg  # type: ignore[import-not-found]

    _HAS_PSYCOPG = True
except ImportError:  # pragma: no cover
    _HAS_PSYCOPG = False


def _intelligence_db_url() -> str | None:
    """Return a sync psycopg URL for intelligence_db, or None if not configured."""
    url = os.environ.get("INTELLIGENCE_DB_URL_TEST") or os.environ.get("INTELLIGENCE_DB_URL")
    if not url:
        return None
    # Strip async driver suffix so psycopg accepts it.
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


def _nlp_db_url() -> str | None:
    url = os.environ.get("NLP_DB_URL_TEST") or os.environ.get("NLP_DB_URL")
    if not url:
        return None
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


def _alembic_upgrade(service_dir: Path, db_url: str) -> None:
    """Run ``alembic upgrade head`` for the given service against ``db_url``.

    Used by the session fixture (T-F-1-03) so PREPARE validates against the
    true HEAD schema (R32 — never assume migration head, read from FS).
    """
    env = os.environ.copy()
    # Each service expects its own env var name; we set both common ones.
    env["INTELLIGENCE_DB_URL"] = db_url
    env["NLP_DB_URL"] = db_url
    env["ALEMBIC_ENABLED"] = "true"
    subprocess.run(  # — fixed argv, no shell
        ["alembic", "upgrade", "head"],
        cwd=service_dir,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def intelligence_db_conn():  # type: ignore[no-untyped-def]
    """Yield a psycopg connection to a HEAD-migrated intelligence_db.

    Skips the test if either psycopg or the DB URL is not available — the
    architecture suite must remain runnable everywhere; CI is the canonical
    enforcement point.
    """
    if not _HAS_PSYCOPG:
        pytest.skip("psycopg not installed — integration PREPARE pass skipped")
    url = _intelligence_db_url()
    if not url:
        pytest.skip("INTELLIGENCE_DB_URL[_TEST] not set — integration PREPARE pass skipped")
    # T-F-1-03: ensure HEAD is applied. We trust the operator to have run the
    # init container in CI; locally we attempt an upgrade but tolerate failure
    # (the connection itself proves the DB is reachable; PREPARE will surface
    # any missing tables).
    service_dir = REPO_ROOT / "services/intelligence-migrations"
    try:
        _alembic_upgrade(service_dir, url)
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        # Alembic missing or migrations already at head — both fine.
        pass
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


@pytest.fixture(scope="session")
def nlp_db_conn():  # type: ignore[no-untyped-def]
    """Yield a psycopg connection to a HEAD-migrated nlp_db (same rules)."""
    if not _HAS_PSYCOPG:
        pytest.skip("psycopg not installed — integration PREPARE pass skipped")
    url = _nlp_db_url()
    if not url:
        pytest.skip("NLP_DB_URL[_TEST] not set — integration PREPARE pass skipped")
    service_dir = REPO_ROOT / "services/nlp-pipeline"
    try:
        _alembic_upgrade(service_dir, url)
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        pass
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


def _prepare_one(conn, sql: str) -> str | None:  # type: ignore[no-untyped-def]
    """Run ``PREPARE`` + ``DEALLOCATE`` for a single SQL string.

    Returns ``None`` on success, or a string error message on failure. We
    always roll back the surrounding transaction so a failed PREPARE on one
    statement doesn't poison subsequent ones (Postgres aborts the txn on
    error).
    """
    cur = conn.cursor()
    try:
        # PREPARE wants the SQL as a literal — we have to embed it. Statements
        # may legitimately contain ``$$`` blocks (functions), so just inline.
        # We also strip a trailing semicolon to avoid syntax errors at PREPARE.
        cleaned = sql.strip().rstrip(";")
        # FIX-LIVE-F: SQLAlchemy uses ``:name`` placeholders; Postgres PREPARE
        # only understands ``$N``. Translate before PREPARE so legitimate
        # named-param SQL doesn't trip "syntax error at or near ':'" noise.
        cleaned = _translate_named_to_positional(cleaned)
        cur.execute(f"PREPARE _qatest_drift AS {cleaned}")
        cur.execute("DEALLOCATE _qatest_drift")
        conn.commit()
        return None
    except psycopg.Error as exc:  # type: ignore[union-attr]
        conn.rollback()
        # Keep the message short and grep-friendly.
        msg = str(exc).strip().splitlines()[0]
        return msg
    finally:
        cur.close()


def _run_prepare_pass(
    conn,  # type: ignore[no-untyped-def]
    statements: list[ExtractedSQL],
) -> list[tuple[ExtractedSQL, str]]:
    """PREPARE every statement and return the failures (sql, error_message)."""
    failures: list[tuple[ExtractedSQL, str]] = []
    for stmt in statements:
        skip_reason = _should_skip(stmt.sql_text)
        if skip_reason is not None:
            continue
        err = _prepare_one(conn, stmt.sql_text)
        if err is not None:
            failures.append((stmt, err))
    return failures


def test_all_intelligence_repository_sql_prepares_successfully(
    intelligence_db_conn,  # type: ignore[no-untyped-def]
) -> None:
    """T-F-1-02: every intelligence_db repository SELECT must PREPARE cleanly.

    Acceptance: 0 failures. Any failure is reported with file:line and the raw
    Postgres error message so an engineer can fix it in seconds (this is the
    F-2 work-list).
    """
    extracted: list[ExtractedSQL] = []
    for path in repository_files(REPO_ROOT):
        if _route_for(path) != "intelligence_db":
            continue
        items, _ = extract_sql_from_file(path)
        extracted.extend(items)

    failures = _run_prepare_pass(intelligence_db_conn, extracted)
    if failures:
        msg_lines = ["PREPARE failed for the following repository SQL:"]
        for stmt, err in failures:
            rel = stmt.file_path.relative_to(REPO_ROOT).as_posix()
            msg_lines.append(f"  {rel}:{stmt.line_number}  →  {err}")
        pytest.fail("\n".join(msg_lines))


def test_all_nlp_repository_sql_prepares_successfully(
    nlp_db_conn,  # type: ignore[no-untyped-def]
) -> None:
    """Same as above for the nlp_db repository root."""
    extracted: list[ExtractedSQL] = []
    for path in repository_files(REPO_ROOT):
        if _route_for(path) != "nlp_db":
            continue
        items, _ = extract_sql_from_file(path)
        extracted.extend(items)

    failures = _run_prepare_pass(nlp_db_conn, extracted)
    if failures:
        msg_lines = ["PREPARE failed for the following repository SQL:"]
        for stmt, err in failures:
            rel = stmt.file_path.relative_to(REPO_ROOT).as_posix()
            msg_lines.append(f"  {rel}:{stmt.line_number}  →  {err}")
        pytest.fail("\n".join(msg_lines))


def test_catches_known_column_typo(
    intelligence_db_conn,  # type: ignore[no-untyped-def]
) -> None:
    """T-F-1-02 acceptance: injecting a bogus column must fail PREPARE.

    This is the canary — if Postgres ever stops rejecting unknown columns
    inside PREPARE, this test catches that regression before it lets real
    drift slip through.
    """
    fake = ExtractedSQL(
        file_path=Path("fake.py"),
        line_number=1,
        # ``canonical_entities`` is a real table; ``totally_made_up_column``
        # is not — PREPARE should reject this.
        sql_text="SELECT totally_made_up_column FROM canonical_entities",
        kind="named",
    )
    err = _prepare_one(intelligence_db_conn, fake.sql_text)
    assert err is not None, "PREPARE should have rejected a non-existent column"
    assert "totally_made_up_column" in err or "does not exist" in err.lower()
    # Sanity: a valid SQL on the same table must still succeed.
    ok = _prepare_one(intelligence_db_conn, "SELECT entity_id FROM canonical_entities LIMIT 1")
    assert ok is None, f"baseline SELECT must succeed, got: {ok}"
    # Reference the unused fixture struct so flake8 sees it.
    _ = fake.kind
