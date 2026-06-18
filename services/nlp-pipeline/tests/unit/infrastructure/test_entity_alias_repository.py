"""Unit tests for nlp_pipeline EntityAliasRepository (Stage-2 ticker/ISIN match).

PLAN-0057 Wave C-3-02 extended ``ticker_isin_match`` and
``batch_ticker_isin_match`` so that lookups falling through canonical_entities
also probe ``entity_aliases`` with ``alias_type IN ('TICKER',
'PRIMARY_TICKER', 'ISIN')``.  The PRIMARY_TICKER alias_type was newly
introduced for EODHD ``General.PrimaryTicker`` values.

These tests assert:
  1. The SQL string sent to the session contains the PRIMARY_TICKER clause.
  2. When canonical lookup returns no row, the alias-fallback row is returned.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import (
    EntityAliasRepository,
)

pytestmark = pytest.mark.unit


def _mk_session() -> tuple[MagicMock, list[str]]:
    """Build an AsyncMock session that records every SQL string executed."""
    session = MagicMock()
    sql_strings: list[str] = []

    async def _execute(sql_obj: object, params: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
        # Capture the SQL text.  The repo passes a sqlalchemy.text() object.
        sql_strings.append(str(sql_obj))
        result = MagicMock()
        result.fetchone = MagicMock(return_value=None)
        result.fetchall = MagicMock(return_value=[])
        return result

    session.execute = AsyncMock(side_effect=_execute)
    return session, sql_strings


@pytest.mark.asyncio
async def test_ticker_isin_match_falls_back_to_alias_table_with_primary_ticker() -> None:
    """When canonical_entities.ticker yields nothing, the SQL fallback hits entity_aliases
    with alias_type IN (...) including PRIMARY_TICKER."""
    session, sql_strings = _mk_session()
    repo = EntityAliasRepository(session)

    await repo.ticker_isin_match(ticker="AAPL", isin=None)

    # Two queries should have run: canonical_entities then entity_aliases fallback.
    assert len(sql_strings) == 2
    fallback_sql = sql_strings[1]
    assert "entity_aliases" in fallback_sql
    assert "PRIMARY_TICKER" in fallback_sql
    assert "TICKER" in fallback_sql
    assert "ISIN" in fallback_sql


@pytest.mark.asyncio
async def test_ticker_isin_match_alias_fallback_returns_entity_id() -> None:
    """When the canonical lookup returns no row but the alias fallback finds one,
    the entity_id from the alias row is returned."""
    session = MagicMock()
    matched_entity_id = uuid4()

    call_count = {"n": 0}

    async def _execute(sql_obj: object, params: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
        call_count["n"] += 1
        result = MagicMock()
        if call_count["n"] == 1:
            # First call (canonical_entities) returns no match
            result.fetchone = MagicMock(return_value=None)
        else:
            # Second call (entity_aliases) returns the matched entity
            row = MagicMock()
            row.__getitem__ = lambda self, idx: str(matched_entity_id)
            result.fetchone = MagicMock(return_value=row)
        return result

    session.execute = AsyncMock(side_effect=_execute)
    repo = EntityAliasRepository(session)

    out = await repo.ticker_isin_match(ticker="AAPL.US", isin=None)
    assert out == matched_entity_id


@pytest.mark.asyncio
async def test_batch_ticker_isin_match_includes_primary_ticker_fallback() -> None:
    """The batch path also extends to entity_aliases with PRIMARY_TICKER."""
    session, sql_strings = _mk_session()
    repo = EntityAliasRepository(session)

    await repo.batch_ticker_isin_match(tickers=["AAPL", "MSFT"], isins=[])

    # Two queries: canonical_entities for tickers + entity_aliases fallback for missed ones.
    assert len(sql_strings) == 2
    fallback_sql = sql_strings[1]
    assert "entity_aliases" in fallback_sql
    assert "PRIMARY_TICKER" in fallback_sql


@pytest.mark.asyncio
async def test_batch_ticker_isin_match_alias_fallback_finds_missed_tickers() -> None:
    """A ticker that's missing from canonical_entities but present as an entity_aliases
    PRIMARY_TICKER alias is found via the fallback."""
    session = MagicMock()
    matched = uuid4()

    call_count = {"n": 0}

    async def _execute(sql_obj: object, params: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
        call_count["n"] += 1
        result = MagicMock()
        if call_count["n"] == 1:
            # canonical_entities returns nothing
            result.fetchall = MagicMock(return_value=[])
        else:
            # entity_aliases fallback returns the missed ticker (lower-cased
            # because the SQL uses normalized_alias_text).
            row = MagicMock()
            row.__getitem__ = lambda self, idx: ("aapl.us", str(matched))[idx]
            result.fetchall = MagicMock(return_value=[row])
        return result

    session.execute = AsyncMock(side_effect=_execute)
    repo = EntityAliasRepository(session)

    out = await repo.batch_ticker_isin_match(tickers=["AAPL.US"], isins=[])
    # The original input casing is the dict key.
    assert out == {"AAPL.US": matched}


@pytest.mark.asyncio
async def test_ticker_isin_match_canonical_hit_does_not_call_fallback() -> None:
    """When canonical_entities returns a row, the alias fallback is NOT executed
    (preserves the existing fast path)."""
    session = MagicMock()
    matched = uuid4()

    call_count = {"n": 0}

    async def _execute(sql_obj: object, params: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
        call_count["n"] += 1
        result = MagicMock()
        # First call returns a match.
        row = MagicMock()
        row.__getitem__ = lambda self, idx: str(matched)
        result.fetchone = MagicMock(return_value=row)
        return result

    session.execute = AsyncMock(side_effect=_execute)
    repo = EntityAliasRepository(session)

    out = await repo.ticker_isin_match(ticker="AAPL", isin=None)
    assert out == matched
    # Only one call — the canonical_entities path; alias fallback never runs.
    assert call_count["n"] == 1


# ── PLAN-0087 F-LLM-001: class-aware canonical-name resolver tests ───────────


def test_candidate_entity_types_for_organization_includes_financial_instrument() -> None:
    """The pivotal mapping: GLiNER 'organization' → financial_instrument first.

    This is the key behavioural assertion of the F-LLM-001 fix.  The
    relation extractor's silent-drop pattern hinges on this expansion: a
    bare "Apple" mention tagged ``organization`` MUST consult
    ``entity_type='financial_instrument'`` candidates because that is
    where listed-company canonicals are stored (61 financial_instrument
    rows vs 2 organization rows in the production canonical_entities
    table at the time of the fix).
    """
    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import (
        candidate_entity_types_for,
    )

    types = candidate_entity_types_for("organization")
    # financial_instrument is FIRST so it wins the priority CASE WHEN tie-break.
    assert types[0] == "financial_instrument"
    # organization stays in the list as a self-match fallback.
    assert "organization" in types
    assert "financial_institution" in types


def test_candidate_entity_types_for_unknown_class_falls_back_to_self() -> None:
    """Forward-compat: an unrecognised mention_class returns ``[mention_class]``.

    Lets new GLiNER classes work as-is without a code change here, with no
    extra fallback breadth (so an unrecognised class doesn't accidentally
    match unrelated canonicals).
    """
    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import (
        candidate_entity_types_for,
    )

    assert candidate_entity_types_for("brand_new_class") == ["brand_new_class"]


@pytest.mark.asyncio
async def test_class_aware_canonical_match_uses_class_filter() -> None:
    """SQL emitted by class_aware_canonical_match constrains entity_type via IN().

    Asserts the SQL contains the ``entity_type IN (...)`` filter so a
    surface like "Apple" is not matched against unrelated entity types.
    """
    session, sql_strings = _mk_session()
    repo = EntityAliasRepository(session)

    await repo.class_aware_canonical_match(mention_text="Apple", mention_class="organization")

    assert len(sql_strings) == 1
    sql = sql_strings[0]
    assert "canonical_entities" in sql
    assert "entity_type IN" in sql
    # Prefix match clause is present so "Apple" matches "Apple Inc.".
    assert "LIKE lower(trim(:surface))" in sql


@pytest.mark.asyncio
async def test_class_aware_canonical_match_returns_entity_id_for_organization_to_financial_instrument() -> None:
    """The headline F-LLM-001 case: "Apple" (organization) resolves to AAPL canonical."""
    session = MagicMock()
    aapl_entity_id = uuid4()

    async def _execute(sql_obj: object, params: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
        # Verify the class filter expansion is in the params.
        assert params is not None
        type_params = {k: v for k, v in params.items() if k.startswith("t")}
        # GLINER_TO_CANONICAL_TYPES['organization'] expands to
        # ['financial_instrument', 'organization', 'financial_institution'].
        assert "financial_instrument" in type_params.values()
        assert params["surface"] == "Apple"
        result = MagicMock()
        row = MagicMock()
        row.__getitem__ = lambda self, idx: str(aapl_entity_id)
        result.fetchone = MagicMock(return_value=row)
        return result

    session.execute = AsyncMock(side_effect=_execute)
    repo = EntityAliasRepository(session)

    out = await repo.class_aware_canonical_match(mention_text="Apple", mention_class="organization")
    assert out == aapl_entity_id


@pytest.mark.asyncio
async def test_class_aware_canonical_match_returns_none_when_no_row() -> None:
    """A surface with no matching canonical_entities row returns None."""
    session, _ = _mk_session()
    repo = EntityAliasRepository(session)

    out = await repo.class_aware_canonical_match(mention_text="Nonexistent", mention_class="organization")
    assert out is None


@pytest.mark.asyncio
async def test_batch_class_aware_canonical_match_groups_by_class() -> None:
    """Batch path issues one SQL query per distinct mention_class.

    Two organization mentions + one person mention → two queries (not three)
    so we keep the round-trip count proportional to class diversity, not
    to mention count.
    """
    session, sql_strings = _mk_session()
    repo = EntityAliasRepository(session)

    await repo.batch_class_aware_canonical_match(
        [
            ("Apple", "organization"),
            ("Microsoft", "organization"),
            ("Tim Cook", "person"),
        ]
    )

    # One query per distinct class: organization + person = 2 queries.
    assert len(sql_strings) == 2
    # All SQL strings should reference canonical_entities and entity_type IN.
    for sql in sql_strings:
        assert "canonical_entities" in sql
        assert "entity_type IN" in sql


@pytest.mark.asyncio
async def test_batch_class_aware_canonical_match_returns_input_keyed_dict() -> None:
    """Output dict is keyed by ``(input_surface, mention_class)`` for caller convenience."""
    session = MagicMock()
    apple_id = uuid4()

    async def _execute(sql_obj: object, params: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
        result = MagicMock()
        # The CTE returns (lower-cased-surface, entity_id) tuples.
        row = MagicMock()
        row.__getitem__ = lambda self, idx: ("apple", str(apple_id))[idx]
        result.fetchall = MagicMock(return_value=[row])
        return result

    session.execute = AsyncMock(side_effect=_execute)
    repo = EntityAliasRepository(session)

    out = await repo.batch_class_aware_canonical_match([("Apple", "organization")])
    # Key uses the ORIGINAL casing of the input surface, not the lower form.
    assert out == {("Apple", "organization"): apple_id}


@pytest.mark.asyncio
async def test_batch_class_aware_canonical_match_empty_input_returns_empty_dict() -> None:
    """Defensive: empty input returns ``{}`` without issuing any queries."""
    session, sql_strings = _mk_session()
    repo = EntityAliasRepository(session)

    out = await repo.batch_class_aware_canonical_match([])
    assert out == {}
    assert sql_strings == []


# ── RC-3 (2026-06-18): GIN-index-usable fuzzy-trigram rewrite ────────────────
#
# The fuzzy-trigram queries were rewritten from the function-form predicate
# ``similarity(col, x) > t`` (opaque to the GIN trigram index → full Seq Scan,
# the contention hot spot of the chat pipeline's entity-resolution phase) to the
# pg_trgm similarity *operator* ``%`` (probes ``idx_entity_aliases_trgm``).  The
# operator's cutoff is the ``pg_trgm.similarity_threshold`` GUC, set per-call via
# ``set_limit(:threshold)`` so the match boundary stays identical to the old
# strict ``> :threshold`` predicate (re-imposed by an outer/inner strict filter).
#
# These tests pin the SQL shape and parameters (the session is mocked, exactly
# like the Stage-2 tests above) and assert the grouping/top_k/result-shape
# behaviour is preserved.


def _mk_capturing_session() -> tuple[MagicMock, list[str], list[dict]]:
    """Session mock that records both SQL strings AND params per execute() call."""
    session = MagicMock()
    sql_strings: list[str] = []
    params_list: list[dict] = []

    async def _execute(sql_obj: object, params: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
        sql_strings.append(str(sql_obj))
        params_list.append(params or {})
        result = MagicMock()
        result.fetchone = MagicMock(return_value=None)
        result.fetchall = MagicMock(return_value=[])
        return result

    session.execute = AsyncMock(side_effect=_execute)
    return session, sql_strings, params_list


@pytest.mark.asyncio
async def test_fuzzy_trigram_sets_threshold_guc_then_probes_with_operator() -> None:
    """fuzzy_trigram first calls set_limit(:threshold), then probes with ``%``.

    Two executes: (1) ``SELECT set_limit(:threshold)`` to align the ``%``
    cutoff with the caller's threshold, then (2) the index-usable probe using
    the ``%`` operator with a strict outer ``sim > :threshold`` re-filter so the
    match set is identical to the old ``similarity(...) > :threshold`` predicate.
    """
    session, sql_strings, params_list = _mk_capturing_session()
    repo = EntityAliasRepository(session)

    await repo.fuzzy_trigram("Apple", threshold=0.55, top_k=5)

    # Three executes: (1) set_limit GUC, (2) SET LOCAL random_page_cost so the
    # planner actually picks the GIN index (RC-3, 2026-06-18), (3) the probe.
    assert len(sql_strings) == 3
    # First call sets the operator cutoff to the caller's threshold.
    assert "set_limit" in sql_strings[0]
    assert params_list[0]["threshold"] == 0.55
    # Second call lowers random_page_cost to the SSD value for THIS transaction
    # so the Bitmap Index Scan on idx_entity_aliases_trgm is chosen over a Seq
    # Scan (PG default rpc=4 over-prices random index I/O at ~37k rows).
    assert "SET LOCAL random_page_cost = 1.1" in sql_strings[1]
    # Third call uses the GIN-index-usable ``%`` operator (NOT the opaque
    # function-form predicate ``similarity(col, x) > t`` that forced a Seq Scan).
    probe_sql = sql_strings[2]
    assert "normalized_alias_text % lower(:mention_text)" in probe_sql
    # The old function-form WHERE predicate must be gone.
    assert "WHERE similarity(normalized_alias_text" not in probe_sql
    # Strict boundary preserved (``%`` is inclusive >=, so we re-apply > t).
    assert "sim > :threshold" in probe_sql
    # Ordering + limit unchanged.
    assert "ORDER BY sim DESC" in probe_sql
    assert "LIMIT :top_k" in probe_sql
    assert params_list[2] == {"mention_text": "Apple", "threshold": 0.55, "top_k": 5}


@pytest.mark.asyncio
async def test_fuzzy_trigram_returns_entity_sim_pairs_in_order() -> None:
    """Result shape preserved: list of (entity_id, similarity) from the probe rows."""
    session = MagicMock()
    e1, e2 = uuid4(), uuid4()

    call = {"n": 0}

    async def _execute(sql_obj: object, params: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
        call["n"] += 1
        result = MagicMock()
        if call["n"] <= 2:
            # set_limit() (1) + SET LOCAL random_page_cost (2) — no rows consumed.
            result.fetchall = MagicMock(return_value=[])
        else:
            r1, r2 = MagicMock(), MagicMock()
            r1.__getitem__ = lambda self, idx: (str(e1), 0.92)[idx]
            r2.__getitem__ = lambda self, idx: (str(e2), 0.71)[idx]
            result.fetchall = MagicMock(return_value=[r1, r2])
        return result

    session.execute = AsyncMock(side_effect=_execute)
    repo = EntityAliasRepository(session)

    out = await repo.fuzzy_trigram("Apple", threshold=0.55, top_k=5)
    assert out == [(e1, 0.92), (e2, 0.71)]


@pytest.mark.asyncio
async def test_batch_fuzzy_trigram_uses_lateral_operator_join() -> None:
    """batch_fuzzy_trigram sets the GUC then uses a per-term LATERAL ``%`` probe.

    The old form joined the term list against the whole alias table on
    ``similarity(...) > t`` — a Nested Loop that Seq-Scanned ~37k rows *per
    term*.  The rewrite uses ``JOIN LATERAL`` so each term independently probes
    ``idx_entity_aliases_trgm`` via ``%`` and is capped at ``top_k`` inside the
    lateral.
    """
    session, sql_strings, params_list = _mk_capturing_session()
    repo = EntityAliasRepository(session)

    await repo.batch_fuzzy_trigram(["Apple", "Microsoft"], threshold=0.55, top_k_per_mention=5)

    # Three executes: set_limit GUC, SET LOCAL random_page_cost (RC-3), lateral probe.
    assert len(sql_strings) == 3
    assert "set_limit" in sql_strings[0]
    assert params_list[0]["threshold"] == 0.55
    assert "SET LOCAL random_page_cost = 1.1" in sql_strings[1]

    batch_sql = sql_strings[2]
    # Per-term lateral probe using the index-usable operator + distance order.
    assert "JOIN LATERAL" in batch_sql
    assert "ea.normalized_alias_text % q.search_term" in batch_sql
    assert "ea.normalized_alias_text <-> q.search_term" in batch_sql
    # Strict boundary preserved inside the lateral.
    assert "similarity(ea.normalized_alias_text, q.search_term) > :threshold" in batch_sql
    # Per-term cap pushed into the lateral (was a post-hoc Python slice before).
    assert "LIMIT :top_k" in batch_sql
    # The old full-table function-predicate JOIN must be gone.
    assert "JOIN entity_aliases ea ON" not in batch_sql
    # Terms are normalised (lower+strip) and passed as a text[] in one round-trip.
    assert params_list[2]["terms"] == ["apple", "microsoft"]
    assert params_list[2]["top_k"] == 5


@pytest.mark.asyncio
async def test_batch_fuzzy_trigram_groups_by_term_and_caps_top_k() -> None:
    """Rows are grouped by search_term and capped at top_k_per_mention each."""
    session = MagicMock()
    a1, a2, a3, m1 = uuid4(), uuid4(), uuid4(), uuid4()

    call = {"n": 0}

    async def _execute(sql_obj: object, params: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
        call["n"] += 1
        result = MagicMock()
        if call["n"] <= 2:
            # set_limit() (1) + SET LOCAL random_page_cost (2) — no rows consumed.
            result.fetchall = MagicMock(return_value=[])
        else:
            # (search_term, entity_id, sim) — three rows for "apple", one for "msft".
            rows = []
            for term, eid, sim in [
                ("apple", a1, 0.90),
                ("apple", a2, 0.80),
                ("apple", a3, 0.70),
                ("msft", m1, 0.95),
            ]:
                row = MagicMock()
                row.__getitem__ = lambda self, idx, _t=term, _e=eid, _s=sim: (_t, str(_e), _s)[idx]
                rows.append(row)
            result.fetchall = MagicMock(return_value=rows)
        return result

    session.execute = AsyncMock(side_effect=_execute)
    repo = EntityAliasRepository(session)

    out = await repo.batch_fuzzy_trigram(["Apple", "MSFT"], threshold=0.55, top_k_per_mention=2)
    # "apple" capped at 2 (the third row dropped); "msft" keeps its single match.
    assert out == {"apple": [(a1, 0.90), (a2, 0.80)], "msft": [(m1, 0.95)]}


@pytest.mark.asyncio
async def test_batch_fuzzy_trigram_empty_input_issues_no_queries() -> None:
    """Empty input short-circuits before touching the session (incl. set_limit)."""
    session, sql_strings, _ = _mk_capturing_session()
    repo = EntityAliasRepository(session)

    out = await repo.batch_fuzzy_trigram([], threshold=0.55)
    assert out == {}
    assert sql_strings == []
