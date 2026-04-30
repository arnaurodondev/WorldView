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
