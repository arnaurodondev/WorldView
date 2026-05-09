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
