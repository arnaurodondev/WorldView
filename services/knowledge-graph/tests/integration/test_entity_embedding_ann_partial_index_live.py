"""Live-EXPLAIN regression test — partial HNSW index usage on entity_embedding_state (S7).

Context (BP-730, 2026-07-22 postgres OOM): the existing unit tests
(``tests/unit/infrastructure/repositories/test_entity_embedding_ann_partial_index.py``)
only assert the SQL *shape* against a mocked session — they never run the query
against a real Postgres and never inspect the actual query plan. A regression
that silently turns the literal ``view_type`` predicate back into a bound
parameter (planner-opaque, defeats the partial index, re-triggers the
Parallel-Seq-Scan-+-Sort work_mem OOM) would stay green under the mocked
suite forever.

This test spins up a throwaway ``pgvector/pgvector:pg16`` Postgres container
(the same image already used for intelligence_db in
``infra/compose/docker-compose.test.yml``), recreates the minimal
``canonical_entities`` + ``entity_embedding_state`` schema and partial HNSW
indexes exactly as intelligence-migrations 0001 defines them, seeds a handful
of rows across multiple ``view_type`` values, then runs the REAL
``SqlalchemyEntityEmbeddingANNRepository.find_nearest`` method — not a
hand-written SQL string — and EXPLAIN (FORMAT JSON)-s the EXACT statement +
params the repository sent to the session. It asserts the plan uses an
``Index Scan`` on the expected partial index, never a ``Seq Scan``.

Custom vs. generic plan pitfall (discovered while writing this test): a naive
``EXPLAIN (FORMAT JSON) <captured statement>`` re-issued with the SAME named
bind parameters is planned as a Postgres **custom plan** — for a one-off
bind+execute (no reused server-side PREPARE), Postgres substitutes the actual
bound value before costing/qual-matching, so even a bind-param ``view_type``
happens to still match the partial index and the regression this test exists
to catch would NOT reproduce. The real production failure mode (BP-730) only
manifests once PgBouncer / prepared-statement reuse promotes the query to a
**generic plan** (Postgres's ``plan_cache_mode = auto`` switches after ~5
executions of the same named prepared statement) — under a generic plan,
``predicate_implied_by`` must prove the partial-index predicate for EVERY
possible parameter value, and a bind param is permanently opaque to that
proof, defeating the index regardless of what value is actually supplied at
runtime. This test forces that exact scenario deterministically — no warm-up
executions needed — via ``SET plan_cache_mode = force_generic_plan`` plus an
explicit SQL-level ``PREPARE ... AS <positional form of the captured
statement>`` / ``EXPLAIN (FORMAT JSON) EXECUTE ...``, translating the
repository's ``:name`` bind params into ``$1, $2, ...`` positional form and
literal argument values.

Skips gracefully when Docker / testcontainers / asyncpg are unavailable.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Iterator
from typing import Any
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

# view_type -> partial HNSW index name, from intelligence-migrations 0001.
_VIEW_TYPE_INDEX = {
    "definition": "idx_entity_emb_definition_hnsw",
    "narrative": "idx_entity_emb_narrative_hnsw",
    "fundamentals_ohlcv": "idx_entity_emb_fstate_hnsw",
}

_DDL = """
CREATE TABLE IF NOT EXISTS canonical_entities (
    entity_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name VARCHAR(500)  NOT NULL,
    entity_type    VARCHAR(50)   NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_embedding_state (
    entity_id        UUID         NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    view_type        VARCHAR(30)  NOT NULL,
    embedding        VECTOR(1024),
    PRIMARY KEY (entity_id, view_type)
);

CREATE INDEX IF NOT EXISTS idx_entity_emb_definition_hnsw ON entity_embedding_state
    USING hnsw (embedding vector_cosine_ops)
    WHERE view_type = 'definition' AND embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_emb_narrative_hnsw ON entity_embedding_state
    USING hnsw (embedding vector_cosine_ops)
    WHERE view_type = 'narrative' AND embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_emb_fstate_hnsw ON entity_embedding_state
    USING hnsw (embedding vector_cosine_ops)
    WHERE view_type = 'fundamentals_ohlcv' AND embedding IS NOT NULL;
"""


# ── Override the shared docker-compose-DB autouse fixture from conftest.py ────
# tests/integration/conftest.py's ``_clean_tables(db_engine)`` targets the
# docker-compose ``intelligence_db`` at S7_TEST_DATABASE_URL (localhost:55433)
# and — being autouse — would skip THIS module too when that shared instance
# isn't reachable, even though this module manages its own throwaway
# testcontainers Postgres and never touches the shared one.
@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncGenerator[None, None]:  # type: ignore[override]
    """No-op override: this module manages its own testcontainers Postgres."""
    yield


@pytest.fixture(scope="module")
def _pg_url() -> Iterator[str]:
    pytest.importorskip("testcontainers", reason="testcontainers not installed")
    pytest.importorskip("asyncpg", reason="asyncpg not installed")
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-not-found]

    # Same image already designated for intelligence_db/nlp_db pgvector needs
    # in infra/compose/docker-compose.test.yml — has the `vector` extension
    # preinstalled (no Apache AGE build required for this table).
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg.get_connection_url().replace("psycopg2", "asyncpg")


@pytest.fixture
async def _engine(_pg_url: str) -> AsyncGenerator[Any, None]:
    """Function-scoped: a fresh engine per test avoids reusing an asyncpg
    connection/pool across the different event loops pytest-asyncio spins up
    per test function (module-scoped async engines intermittently raised
    ``InterfaceError: another operation is in progress`` across parametrized
    tests). DDL is idempotent (``IF NOT EXISTS``) so re-running it per test
    against the same long-lived container is safe and cheap.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_pg_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        for statement in _DDL.strip().split(";\n\n"):
            statement = statement.strip()
            if statement:
                await conn.execute(text(statement))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def _session(_engine: Any) -> AsyncGenerator[Any, None]:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


async def _seed_rows(session: Any, *, per_view_type: int = 5) -> None:
    """Seed a handful of entities with embeddings across every view_type."""
    from sqlalchemy import text

    for view_type in _VIEW_TYPE_INDEX:
        for i in range(per_view_type):
            entity_id = uuid4()
            # Deterministic-ish pseudo-random unit-ish vector; exact values are
            # irrelevant — only presence + view_type partitioning matters here.
            vector = [((i + 1) * 0.001 + j * 1e-6) for j in range(1024)]
            await session.execute(
                text("INSERT INTO canonical_entities (entity_id, canonical_name, entity_type) VALUES (:id, :n, :t)"),
                {"id": str(entity_id), "n": f"Entity {view_type} {i}", "t": "organization"},
            )
            await session.execute(
                text(
                    "INSERT INTO entity_embedding_state (entity_id, view_type, embedding) "
                    "VALUES (:id, :vt, CAST(:emb AS vector))"
                ),
                {"id": str(entity_id), "vt": view_type, "emb": str(vector)},
            )
    await session.commit()


class _CapturingSession:
    """Thin wrapper that records the last (raw SQL text, params) passed to
    ``execute`` while still delegating to the real ``AsyncSession`` — lets the
    test run the REAL repository method and then re-issue the EXACT statement
    it produced, wrapped in ``EXPLAIN (FORMAT JSON)``, instead of hand-writing
    a parallel SQL string that could drift from the production query.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.last_statement_text: str | None = None
        self.last_params: dict[str, Any] | None = None

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        self.last_statement_text = str(stmt)
        self.last_params = params
        return await self._inner.execute(stmt, params)


def _iter_plan_nodes(plan_node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield plan_node
    for child in plan_node.get("Plans", []):
        yield from _iter_plan_nodes(child)


def _to_positional(sql_text: str, params: dict[str, Any]) -> tuple[str, list[Any]]:
    """Translate a SQLAlchemy ``:name``-style ``text()`` query into Postgres
    positional-parameter form (``$1, $2, ...``) plus an ordered value list,
    suitable for a real SQL-level ``PREPARE ... AS <sql>`` / ``EXECUTE``.

    Each distinct ``:name`` gets ONE positional slot, assigned in order of
    first appearance (matching how repeated references to the same bind name
    would be handled by a real driver-level PREPARE).
    """
    import re

    order: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in order:
            order.append(name)
        return f"${order.index(name) + 1}"

    # Negative lookbehind excludes Postgres's `::type` cast operator (e.g.
    # `embedding::vector`) — only a SINGLE leading colon is a bind param.
    positional_sql = re.sub(r"(?<!:):(\w+)", _replace, sql_text)
    values = [params[name] for name in order]
    return positional_sql, values


def _sql_literal(value: Any) -> str:
    """Render a Python value as a Postgres SQL literal for an EXECUTE arg list.

    Only used against internal, allow-listed, or test-seeded values (never
    live user input) — this is test-harness code, not production SQL building.
    """
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, list):
        return "ARRAY[" + ",".join(_sql_literal(v) for v in value) + "]"
    return str(value)


async def _explain_captured(session: Any, capturing: _CapturingSession) -> list[dict[str, Any]]:
    """EXPLAIN the EXACT statement the repository emitted, under a Postgres
    **generic plan** — the only mode that reproduces BP-730 (see module
    docstring for why a naive custom-plan EXPLAIN does not).
    """
    from sqlalchemy import text

    assert capturing.last_statement_text is not None, "repository method never called session.execute"
    positional_sql, values = _to_positional(capturing.last_statement_text, capturing.last_params or {})
    literal_args = ", ".join(_sql_literal(v) for v in values)

    plan_name = "bp730_regression_plan"
    await session.execute(text("SET plan_cache_mode = force_generic_plan"))
    await session.execute(text(f"PREPARE {plan_name} AS {positional_sql}"))
    try:
        result = await session.execute(text(f"EXPLAIN (FORMAT JSON) EXECUTE {plan_name}({literal_args})"))
        row = result.fetchone()
        plan_json = row[0]
        # asyncpg/SQLAlchemy may return the JSON already decoded as a
        # list[dict], or as a raw JSON string depending on driver JSON codec
        # configuration.
        plan_doc = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
        top_plan = plan_doc[0]["Plan"]
        return list(_iter_plan_nodes(top_plan))
    finally:
        await session.execute(text(f"DEALLOCATE {plan_name}"))


@pytest.mark.parametrize("view_type", sorted(_VIEW_TYPE_INDEX))
async def test_find_nearest_uses_partial_hnsw_index(_session: Any, view_type: str) -> None:
    """The REAL find_nearest query must plan to an Index Scan on the matching
    partial HNSW index for every indexed view_type — never a Seq Scan.
    """
    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
        SqlalchemyEntityEmbeddingANNRepository,
    )

    await _seed_rows(_session)

    capturing = _CapturingSession(_session)
    repo = SqlalchemyEntityEmbeddingANNRepository(capturing)  # type: ignore[arg-type]

    results = await repo.find_nearest(query_embedding=[0.0005] * 1024, view_type=view_type, limit=10)
    assert results, f"expected seeded rows to be returned for view_type={view_type}"

    nodes = await _explain_captured(_session, capturing)
    # find_nearest JOINs canonical_entities — a tiny, unindexed-by-view-type
    # table that the planner is entitled to Seq Scan regardless of the
    # entity_embedding_state access path under test, so the assertion must
    # target ONLY the entity_embedding_state scan node, not "any Seq Scan
    # anywhere in the plan" (which would also flag that unrelated, correct
    # join-side scan as a false failure).
    ees_nodes = [n for n in nodes if n.get("Relation Name") == "entity_embedding_state"]
    assert ees_nodes, f"no scan node found for entity_embedding_state, view_type={view_type}: {nodes}"
    ees_node_types = [n.get("Node Type") for n in ees_nodes]
    assert "Seq Scan" not in ees_node_types, f"partial index defeated for view_type={view_type}: {ees_node_types}"
    index_scan_nodes = [n for n in ees_nodes if n.get("Node Type") in ("Index Scan", "Index Only Scan")]
    assert index_scan_nodes, f"no Index Scan node found for view_type={view_type}: {ees_node_types}"
    index_names = {n.get("Index Name") for n in index_scan_nodes}
    expected_index = _VIEW_TYPE_INDEX[view_type]
    assert (
        expected_index in index_names
    ), f"expected partial index {expected_index!r} for view_type={view_type}, got {index_names}"
