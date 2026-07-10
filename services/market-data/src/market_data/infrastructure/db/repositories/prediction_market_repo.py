"""PostgreSQL adapters for PredictionMarketRepository and PredictionMarketSnapshotRepository."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from market_data.application.ports.repositories import (
    PredictionMarketEventsRepository,
    PredictionMarketOIRepository,
    PredictionMarketPricesRepository,
    PredictionMarketRepository,
    PredictionMarketSnapshotRepository,
    PredictionMarketTradesRepository,
)
from market_data.domain.entities import (
    PredictionEvent,
    PredictionMarket,
    PredictionMarketOI,
    PredictionMarketPrice,
    PredictionMarketSnapshot,
    PredictionMarketTrade,
)
from market_data.infrastructure.db.models.prediction_markets import (
    PredictionEventModel,
    PredictionMarketModel,
    PredictionMarketOIModel,
    PredictionMarketPriceModel,
    PredictionMarketSnapshotModel,
    PredictionMarketTradeModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# --- Free-text search tokenisation (R2 fix: multi-word chat queries) --------
#
# WHY: the previous free-text branch matched the ENTIRE query phrase as one
# ILIKE substring (`%<whole phrase>%`). Natural chat queries such as
# "2028 Democratic presidential nomination" never appear verbatim inside a
# single market `question`, so realistic multi-word questions returned 0 rows
# even though single keywords ("election") matched fine. We now split the query
# into meaningful word tokens and require the question to contain ALL of them
# (AND-of-tokens). AND (not OR) is deliberate: OR-of-any-token would match
# almost every market via a common word like "the"/"win" and return the whole
# table; AND keeps precision so a nonsense phrase still yields nothing.
#
# There is no tsvector/GIN full-text index on `prediction_markets.question`
# (checked migrations 005/009/010/015), so a proper `websearch_to_tsquery`
# ranked match is not available without new DDL — tokenised ILIKE is the
# correct in-place fix and stays consistent with the existing wildcard-escape
# + single-char ESCAPE safety (M-002 / BP-712).

# Very common words that carry no discriminating signal for market lookup.
# Kept intentionally small — over-aggressive stopword removal can strip real
# query intent. Anything short (< 3 chars) is dropped by length anyway.
_QUERY_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "will",
        "who",
        "what",
        "when",
        "which",
        "that",
        "this",
        "with",
        "from",
        "does",
        "did",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "into",
        "about",
    }
)

# Meaningful tokens are runs of alphanumerics PLUS the ILIKE wildcard chars
# (% and _). Sentence punctuation (?, ., ,, !, etc.) acts as a delimiter and is
# stripped, so "nomination?" tokenises to "nomination". The wildcard chars are
# deliberately KEPT inside a token so a literal "50%" survives as a distinct
# token and, once escaped below, matches a literal "50%" rather than the number
# "50" — this preserves the M-002 wildcard-escape contract (a query "win 50%"
# must not wildcard-match "win 50k").
_TOKEN_RE = re.compile(r"[a-z0-9%_]+")


def _tokenize_query(query: str) -> list[str]:
    """Split a free-text query into meaningful, de-duplicated search tokens.

    Lower-cases, keeps alphanumeric runs of length >= 3 that are not trivial
    stopwords, and preserves first-seen order without duplicates. Returns an
    empty list when nothing meaningful survives (caller falls back to matching
    the whole phrase so single short/stopword queries still behave sanely).
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(query.lower()):
        if len(raw) < 3 or raw in _QUERY_STOPWORDS or raw in seen:
            continue
        seen.add(raw)
        tokens.append(raw)
    return tokens


def _escape_like_token(token: str) -> str:
    """Escape ILIKE metacharacters so the token matches literally (M-002).

    Mirrors the escaping used for the whole-phrase fallback: literal backslashes
    are doubled, then %/_ are backslash-prefixed. Pairs with the single-char
    ``ESCAPE '\\'`` clause (BP-712).
    """
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_market(row: Any) -> PredictionMarket:
    """Map a raw DB row to a ``PredictionMarket`` domain entity.

    ``category`` (PLAN-0049 T-C-3-03) is read with ``getattr`` and a None
    default so this mapper still works on tests that fabricate row mocks
    without the new column — keeps the migration roll-out forward-compat.
    """
    return PredictionMarket(
        id=str(row.id),
        market_id=row.market_id,
        source=row.source,
        question=row.question,
        description=row.description,
        outcomes=row.outcomes if row.outcomes is not None else [],
        close_time=row.close_time,
        resolution_status=row.resolution_status,
        resolved_answer=row.resolved_answer,
        market_slug=row.market_slug,
        category=getattr(row, "category", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_snapshot(row: Any) -> PredictionMarketSnapshot:
    """Map a raw DB row to a ``PredictionMarketSnapshot`` domain entity."""
    prices: dict[str, float] = row.outcomes_prices if row.outcomes_prices is not None else {}
    return PredictionMarketSnapshot(
        id=str(row.id),
        market_id=row.market_id,
        snapshot_at=row.snapshot_at,
        outcomes_prices=prices,
        volume_24h=Decimal(str(row.volume_24h)) if row.volume_24h is not None else None,
        liquidity=Decimal(str(row.liquidity)) if row.liquidity is not None else None,
        source_event_id=row.source_event_id,
    )


def _dec(value: Any) -> Decimal | None:
    """Coerce a nullable DB numeric to ``Decimal`` (or ``None``).

    Mirrors the ``Decimal(str(...))`` round-trip used by ``_row_to_snapshot`` so
    values keep full NUMERIC precision regardless of the driver's Python type.
    """
    return Decimal(str(value)) if value is not None else None


def _row_to_price(row: Any) -> PredictionMarketPrice:
    """Map a raw DB row to a ``PredictionMarketPrice`` domain entity."""
    return PredictionMarketPrice(
        market_id=row.market_id,
        token_id=row.token_id,
        interval=row.interval,
        window_start_ts=row.window_start_ts,
        # price is NOT NULL in the schema, but str()-round-trip keeps precision.
        price=Decimal(str(row.price)),
        outcome_name=row.outcome_name,
        source=row.source,
        is_backfill=row.is_backfill,
    )


def _row_to_trade(row: Any) -> PredictionMarketTrade:
    """Map a raw DB row to a ``PredictionMarketTrade`` domain entity."""
    return PredictionMarketTrade(
        market_id=row.market_id,
        trade_id=row.trade_id,
        token_id=row.token_id,
        price=Decimal(str(row.price)),
        side=row.side,
        ts=row.ts,
        size_usd=_dec(row.size_usd),
    )


def _row_to_oi(row: Any) -> PredictionMarketOI:
    """Map a raw DB row to a ``PredictionMarketOI`` domain entity."""
    return PredictionMarketOI(
        market_id=row.market_id,
        snapshot_date=row.snapshot_date,
        total_oi_usd=_dec(row.total_oi_usd),
        total_volume_24h_usd=_dec(row.total_volume_24h_usd),
    )


def _row_to_event(row: Any) -> PredictionEvent:
    """Map a raw DB row to a ``PredictionEvent`` domain entity."""
    return PredictionEvent(
        event_id=row.event_id,
        name=row.name,
        category=getattr(row, "category", None),
        start_date=row.start_date,
        end_date=row.end_date,
        market_count=int(row.market_count),
    )


class PgPredictionMarketRepository(PredictionMarketRepository):
    """SQLAlchemy-backed implementation of PredictionMarketRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, market: PredictionMarket) -> PredictionMarket:
        """Insert or update a prediction market; return the persisted entity."""
        stmt = (
            pg_insert(PredictionMarketModel)
            .values(
                id=market.id,
                market_id=market.market_id,
                source=market.source,
                question=market.question,
                description=market.description,
                outcomes=market.outcomes,
                close_time=market.close_time,
                resolution_status=market.resolution_status,
                resolved_answer=market.resolved_answer,
                market_slug=market.market_slug,
                category=market.category,
            )
            .on_conflict_do_update(
                index_elements=["market_id"],
                set_={
                    "question": pg_insert(PredictionMarketModel).excluded.question,
                    "description": pg_insert(PredictionMarketModel).excluded.description,
                    "outcomes": pg_insert(PredictionMarketModel).excluded.outcomes,
                    "close_time": pg_insert(PredictionMarketModel).excluded.close_time,
                    "resolution_status": pg_insert(PredictionMarketModel).excluded.resolution_status,
                    "resolved_answer": pg_insert(PredictionMarketModel).excluded.resolved_answer,
                    # WHY update market_slug on conflict: slug may arrive on a later poll
                    # if the Gamma API added it after initial ingestion. Always take the
                    # newest non-null value. COALESCE keeps existing slug if new one is null.
                    "market_slug": text("COALESCE(EXCLUDED.market_slug, prediction_markets.market_slug)"),
                    # F-QAC-02 fix: same COALESCE policy as market_slug — once a
                    # category is recorded for a market we never blank it back
                    # to NULL on a subsequent poll that didn't include the field.
                    # Polymarket's Gamma API may surface category on event
                    # metadata refreshes that arrive after the initial ingest.
                    "category": text("COALESCE(EXCLUDED.category, prediction_markets.category)"),
                    "updated_at": text("now()"),
                },
            )
            .returning(
                PredictionMarketModel.id,
                PredictionMarketModel.market_id,
                PredictionMarketModel.source,
                PredictionMarketModel.question,
                PredictionMarketModel.description,
                PredictionMarketModel.outcomes,
                PredictionMarketModel.close_time,
                PredictionMarketModel.resolution_status,
                PredictionMarketModel.resolved_answer,
                PredictionMarketModel.market_slug,
                PredictionMarketModel.category,
                PredictionMarketModel.created_at,
                PredictionMarketModel.updated_at,
            )
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        if row is None:
            # Should never happen — upsert always returns a row
            return market
        return _row_to_market(row)

    async def find_by_market_id(self, market_id: str) -> PredictionMarket | None:
        result = await self._session.execute(
            text(
                "SELECT id, market_id, source, question, description, outcomes, "
                "close_time, resolution_status, resolved_answer, market_slug, "
                "category, "
                "created_at, updated_at "
                "FROM prediction_markets WHERE market_id = :market_id LIMIT 1"
            ).bindparams(market_id=market_id)
        )
        row = result.fetchone()
        return _row_to_market(row) if row is not None else None

    async def list_markets(
        self,
        *,
        status: str | None,
        query: str | None,
        limit: int,
        offset: int,
        category: str | None = None,
    ) -> tuple[list[tuple[PredictionMarket, Decimal | None]], int]:
        """Return paginated ``(market, latest_volume_24h)`` pairs and total count.

        Adds a ``LEFT JOIN LATERAL`` to ``prediction_market_snapshots`` that
        pulls the single newest snapshot per market (ORDER BY snapshot_at
        DESC LIMIT 1).  PLAN-0048 D-1: the list endpoint must surface real
        24-hour volume — previously the field was hardcoded to ``None``
        because it lives on the hypertable, not the master ``prediction_markets``
        row.  LATERAL keeps the join evaluated per-row (uses the partial
        per-market index on snapshot_at) instead of a window function over
        the whole snapshot table.
        """
        # F-101: build WHERE clause from static string segments only; all user
        # values are bound via named parameters — no f-string interpolation of
        # user data.
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        # Base query — always-true predicate allows clean appending below.
        # WHY LEFT JOIN LATERAL (not DISTINCT ON over snapshots): we want at
        # most ONE additional column per market row, no behaviour change to
        # the existing pagination/ORDER/COUNT(*) OVER() shape.  LEFT (not
        # INNER) ensures markets without snapshots still appear with NULL
        # volume — matches the previous behaviour where volume was always
        # NULL.
        base = (
            "SELECT m.id, m.market_id, m.source, m.question, m.description, m.outcomes, "
            "m.close_time, m.resolution_status, m.resolved_answer, m.market_slug, "
            "m.category, "
            "m.created_at, m.updated_at, latest.volume_24h AS latest_volume_24h, "
            "COUNT(*) OVER() AS total "
            "FROM prediction_markets m "
            "LEFT JOIN LATERAL ("
            "  SELECT volume_24h "
            "  FROM prediction_market_snapshots s "
            "  WHERE s.market_id = m.market_id "
            "  ORDER BY s.snapshot_at DESC "
            "  LIMIT 1"
            ") latest ON TRUE"
        )
        predicates: list[str] = []

        if status is not None:
            predicates.append("m.resolution_status = :status")
            params["status"] = status

        # PLAN-0049 T-C-3-03: optional category filter. Lower-cased on bind so
        # callers don't have to worry about Polymarket's mixed casing — the
        # adapter writes lowercase tags. NULL category rows never match.
        if category is not None:
            predicates.append("LOWER(m.category) = :category")
            params["category"] = category.lower()

        if query is not None:
            # R2 fix: tokenise the free-text query and require the question to
            # ILIKE-match ALL meaningful tokens (AND), instead of matching the
            # whole phrase as one substring. This makes natural multi-word chat
            # queries ("2028 Democratic presidential nomination") actually match
            # markets whose question contains those words in any order, while a
            # nonsense phrase still matches nothing.
            #
            # BP-712: the ESCAPE clause must be a SINGLE character. Each Python
            # literal below renders to SQL `ESCAPE '\'` (one backslash). The
            # previous `ESCAPE '\\\\'` rendered to SQL `ESCAPE '\\'` which, under
            # standard_conforming_strings=on (the Postgres default), is a
            # TWO-char string literal → asyncpg InvalidEscapeSequenceError →
            # HTTP 500 on every free-text query. A single backslash matches the
            # escape char used by `_escape_like_token`, so metacharacter
            # escaping stays consistent (M-002).
            tokens = _tokenize_query(query)
            if tokens:
                # One AND-ed ILIKE predicate per token, each a separately-bound
                # parameter (no user data ever interpolated into the SQL string).
                for idx, token in enumerate(tokens):
                    param_name = f"query_tok_{idx}"
                    predicates.append(f"m.question ILIKE :{param_name} ESCAPE '\\'")
                    params[param_name] = f"%{_escape_like_token(token)}%"
            else:
                # Fallback: nothing meaningful survived tokenisation (e.g. the
                # query was all stopwords or a single very short token). Match
                # the whole phrase so short keyword queries still behave sanely.
                predicates.append("m.question ILIKE :query_like ESCAPE '\\'")
                params["query_like"] = f"%{_escape_like_token(query)}%"

        where_sql = (" WHERE " + " AND ".join(predicates)) if predicates else ""
        # WHY COALESCE(volume_24h, 0) DESC first: surfaces active/liquid markets
        # (high-volume = recently traded, real price discovery). Previous
        # updated_at DESC sorted by ingestion-crawler touch time — stale 900-day
        # markets were bumped by metadata refreshes, flooding the dashboard with
        # noise at 1%Y/99%N fixed prices. close_time ASC as secondary key shows
        # nearest-to-resolving markets first within the same volume tier, giving
        # the widget a useful "urgency" signal on ties (e.g. two $100k markets:
        # one closes in 3d, the other in 30d — show the 3d one first).
        full_sql = (
            base
            + where_sql
            + " ORDER BY COALESCE(latest.volume_24h, 0) DESC, m.close_time ASC, m.updated_at DESC"
            + " LIMIT :limit OFFSET :offset"
        )

        result = await self._session.execute(text(full_sql).bindparams(**params))
        rows = result.fetchall()
        if not rows:
            return [], 0
        total = int(rows[0].total)
        # Project each row into (market, latest_volume_24h).  Decimal cast
        # mirrors the snapshot row mapper for type consistency on the wire.
        pairs: list[tuple[PredictionMarket, Decimal | None]] = [
            (
                _row_to_market(row),
                Decimal(str(row.latest_volume_24h)) if row.latest_volume_24h is not None else None,
            )
            for row in rows
        ]
        return pairs, total

    async def count_open_by_category(self) -> list[tuple[str | None, int]]:
        """Return ``[(category, count), ...]`` for currently-open markets.

        PLAN-0053 T-C-3-05.  Single ``GROUP BY category`` query with
        ``WHERE resolution_status = 'open'`` — uses the existing index on
        resolution_status from migration 005 to avoid a sequential scan.
        """
        # WHY ORDER BY count DESC: frontend pills render highest-count buckets
        # first so the most useful filters are visually prominent.
        # WHY LOWER(category): PLAN-0049 T-C-3-03 stores categories lower-cased
        # at write time, but defensive in case any historical row escaped the
        # adapter normalisation. NULL stays NULL through LOWER (no coercion).
        # WHY ``open_count`` (and not ``count``): ``Row.count`` shadows the
        # built-in ``tuple.count`` method on SQLAlchemy Row, breaking attribute
        # access (mypy flags it as "object is callable"). Aliasing to
        # ``open_count`` sidesteps the collision while keeping the SQL clear.
        result = await self._session.execute(
            text(
                """
                SELECT LOWER(category) AS category, COUNT(*) AS open_count
                FROM prediction_markets
                WHERE resolution_status = 'open'
                GROUP BY LOWER(category)
                ORDER BY open_count DESC
                """
            )
        )
        return [(row.category, int(row.open_count)) for row in result.fetchall()]


class PgPredictionMarketSnapshotRepository(PredictionMarketSnapshotRepository):
    """SQLAlchemy-backed implementation of PredictionMarketSnapshotRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_if_not_exists(self, snapshot: PredictionMarketSnapshot) -> bool:
        """Atomically insert a snapshot; return ``True`` if new, ``False`` on conflict."""
        stmt = (
            pg_insert(PredictionMarketSnapshotModel)
            .values(
                id=snapshot.id,
                market_id=snapshot.market_id,
                snapshot_at=snapshot.snapshot_at,
                outcomes_prices=snapshot.outcomes_prices,
                volume_24h=snapshot.volume_24h,
                liquidity=snapshot.liquidity,
                source_event_id=snapshot.source_event_id,
            )
            # WHY index_elements not constraint: migration 005 created uq_pms_market_snapshot
            # as a UNIQUE INDEX (not a UNIQUE CONSTRAINT), so ON CONFLICT ON CONSTRAINT raises
            # UndefinedObjectError. index_elements works with unique indexes.
            .on_conflict_do_nothing(index_elements=["market_id", "snapshot_at"])
            .returning(PredictionMarketSnapshotModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_snapshots(
        self,
        market_id: str,
        *,
        from_dt: datetime | None,
        to_dt: datetime | None,
        limit: int,
    ) -> list[PredictionMarketSnapshot]:
        # F-101: static SQL base; all user values bound via named parameters.
        params: dict[str, Any] = {"market_id": market_id, "limit": limit}
        predicates = ["market_id = :market_id"]

        if from_dt is not None:
            predicates.append("snapshot_at >= :from_dt")
            params["from_dt"] = from_dt

        if to_dt is not None:
            predicates.append("snapshot_at <= :to_dt")
            params["to_dt"] = to_dt

        where_sql = " AND ".join(predicates)
        full_sql = (
            "SELECT id, market_id, snapshot_at, outcomes_prices, "
            "volume_24h, liquidity, source_event_id "
            "FROM prediction_market_snapshots "
            "WHERE " + where_sql + " "
            "ORDER BY snapshot_at DESC "
            "LIMIT :limit"
        )

        result = await self._session.execute(text(full_sql).bindparams(**params))
        return [_row_to_snapshot(row) for row in result.fetchall()]

    async def get_earliest_snapshot_at_or_after(
        self,
        market_id: str,
        at_or_after: datetime,
    ) -> PredictionMarketSnapshot | None:
        """Return the earliest in-window snapshot (``ORDER BY snapshot_at ASC LIMIT 1``).

        This is the authoritative window-start baseline for the move detector — it
        is NOT bounded by the ``list_snapshots`` LIMIT, so a slow move measured
        over the full configured window is not silently truncated.
        """
        # F-101: static SQL; user values bound via named parameters.
        sql = text(
            "SELECT id, market_id, snapshot_at, outcomes_prices, "
            "volume_24h, liquidity, source_event_id "
            "FROM prediction_market_snapshots "
            "WHERE market_id = :market_id AND snapshot_at >= :at_or_after "
            "ORDER BY snapshot_at ASC "
            "LIMIT 1"
        ).bindparams(market_id=market_id, at_or_after=at_or_after)
        result = await self._session.execute(sql)
        row = result.fetchone()
        return _row_to_snapshot(row) if row is not None else None

    async def get_latest_prices_batch(
        self,
        market_ids: list[str],
    ) -> dict[str, dict[str, float]]:
        """Return latest ``outcomes_prices`` per market using a single DISTINCT ON query."""
        if not market_ids:
            return {}
        sql = text(
            "SELECT DISTINCT ON (market_id) market_id, outcomes_prices "
            "FROM prediction_market_snapshots "
            "WHERE market_id = ANY(CAST(:market_ids AS TEXT[])) "
            "ORDER BY market_id, snapshot_at DESC"
        ).bindparams(market_ids=market_ids)
        result = await self._session.execute(sql)
        return {
            row.market_id: (row.outcomes_prices if row.outcomes_prices is not None else {}) for row in result.fetchall()
        }


class PgPredictionMarketPricesRepository(PredictionMarketPricesRepository):
    """SQLAlchemy-backed per-token interval price history (PLAN-0056 A2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_if_not_exists(self, price: PredictionMarketPrice) -> bool:
        """Insert one price bar; ``True`` if new, ``False`` on conflict.

        WHY ``index_elements`` (not ``constraint``): the UNIQUE index
        ``uq_pmp_market_token_interval_window`` is a unique index, so
        ``ON CONFLICT (cols)`` targets it directly (mirrors the snapshot repo).
        ``id`` is omitted so the DB generates it via ``gen_random_uuid()``.
        """
        stmt = (
            pg_insert(PredictionMarketPriceModel)
            .values(
                market_id=price.market_id,
                token_id=price.token_id,
                outcome_name=price.outcome_name,
                interval=price.interval,
                window_start_ts=price.window_start_ts,
                price=price.price,
                source=price.source,
                is_backfill=price.is_backfill,
            )
            .on_conflict_do_nothing(index_elements=["market_id", "token_id", "interval", "window_start_ts"])
            .returning(PredictionMarketPriceModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def bulk_insert(self, prices: list[PredictionMarketPrice]) -> int:
        """Insert many price bars in a single multi-row INSERT … ON CONFLICT DO NOTHING."""
        if not prices:
            return 0
        values = [
            {
                "market_id": p.market_id,
                "token_id": p.token_id,
                "outcome_name": p.outcome_name,
                "interval": p.interval,
                "window_start_ts": p.window_start_ts,
                "price": p.price,
                "source": p.source,
                "is_backfill": p.is_backfill,
            }
            for p in prices
        ]
        stmt = (
            pg_insert(PredictionMarketPriceModel)
            .values(values)
            .on_conflict_do_nothing(index_elements=["market_id", "token_id", "interval", "window_start_ts"])
            .returning(PredictionMarketPriceModel.id)
        )
        result = await self._session.execute(stmt)
        # RETURNING yields one row per row actually inserted; conflicts are skipped.
        return len(result.fetchall())

    async def list_prices(
        self,
        market_id: str,
        *,
        token_id: str | None,
        interval: str | None,
        from_dt: datetime | None,
        to_dt: datetime | None,
        limit: int,
    ) -> list[PredictionMarketPrice]:
        # F-101: static SQL base; all user values bound via named parameters.
        params: dict[str, Any] = {"market_id": market_id, "limit": limit}
        predicates = ["market_id = :market_id"]
        if token_id is not None:
            predicates.append("token_id = :token_id")
            params["token_id"] = token_id
        if interval is not None:
            predicates.append("interval = :interval")
            params["interval"] = interval
        if from_dt is not None:
            predicates.append("window_start_ts >= :from_dt")
            params["from_dt"] = from_dt
        if to_dt is not None:
            predicates.append("window_start_ts <= :to_dt")
            params["to_dt"] = to_dt

        full_sql = (
            "SELECT market_id, token_id, outcome_name, interval, window_start_ts, "
            "price, source, is_backfill "
            "FROM prediction_market_prices "
            "WHERE " + " AND ".join(predicates) + " "
            "ORDER BY window_start_ts DESC "
            "LIMIT :limit"
        )
        result = await self._session.execute(text(full_sql).bindparams(**params))
        return [_row_to_price(row) for row in result.fetchall()]


class PgPredictionMarketTradesRepository(PredictionMarketTradesRepository):
    """SQLAlchemy-backed individual-trade repository (PLAN-0056 A2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_if_not_exists(self, trade: PredictionMarketTrade) -> bool:
        """Insert one trade; ``True`` if new, ``False`` on conflict on ``(market_id, trade_id, ts)``."""
        stmt = (
            pg_insert(PredictionMarketTradeModel)
            .values(
                market_id=trade.market_id,
                trade_id=trade.trade_id,
                token_id=trade.token_id,
                price=trade.price,
                size_usd=trade.size_usd,
                side=trade.side,
                ts=trade.ts,
            )
            .on_conflict_do_nothing(index_elements=["market_id", "trade_id", "ts"])
            .returning(PredictionMarketTradeModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def bulk_insert(self, trades: list[PredictionMarketTrade]) -> int:
        """Insert many trades in a single multi-row INSERT … ON CONFLICT DO NOTHING."""
        if not trades:
            return 0
        values = [
            {
                "market_id": t.market_id,
                "trade_id": t.trade_id,
                "token_id": t.token_id,
                "price": t.price,
                "size_usd": t.size_usd,
                "side": t.side,
                "ts": t.ts,
            }
            for t in trades
        ]
        stmt = (
            pg_insert(PredictionMarketTradeModel)
            .values(values)
            .on_conflict_do_nothing(index_elements=["market_id", "trade_id", "ts"])
            .returning(PredictionMarketTradeModel.id)
        )
        result = await self._session.execute(stmt)
        return len(result.fetchall())

    async def list_trades(
        self,
        market_id: str,
        *,
        since: datetime | None,
        limit: int,
    ) -> list[PredictionMarketTrade]:
        params: dict[str, Any] = {"market_id": market_id, "limit": limit}
        predicates = ["market_id = :market_id"]
        if since is not None:
            predicates.append("ts >= :since")
            params["since"] = since
        full_sql = (
            "SELECT market_id, trade_id, token_id, price, size_usd, side, ts "
            "FROM prediction_market_trades "
            "WHERE " + " AND ".join(predicates) + " "
            "ORDER BY ts DESC "
            "LIMIT :limit"
        )
        result = await self._session.execute(text(full_sql).bindparams(**params))
        return [_row_to_trade(row) for row in result.fetchall()]


class PgPredictionMarketOIRepository(PredictionMarketOIRepository):
    """SQLAlchemy-backed daily open-interest / 24h-volume roll-up (PLAN-0056 A2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, oi: PredictionMarketOI) -> None:
        """Insert or overwrite the daily roll-up (last-write-wins on the money fields).

        Conflict target is the composite PK ``(market_id, snapshot_date)``. On
        conflict the money fields are overwritten so a later same-day poll
        supersedes an earlier partial reading; ``updated_at`` is bumped to now().
        """
        stmt = pg_insert(PredictionMarketOIModel).values(
            market_id=oi.market_id,
            snapshot_date=oi.snapshot_date,
            total_oi_usd=oi.total_oi_usd,
            total_volume_24h_usd=oi.total_volume_24h_usd,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["market_id", "snapshot_date"],
            set_={
                "total_oi_usd": stmt.excluded.total_oi_usd,
                "total_volume_24h_usd": stmt.excluded.total_volume_24h_usd,
                "updated_at": text("now()"),
            },
        )
        await self._session.execute(stmt)

    async def list_oi(
        self,
        market_id: str,
        *,
        from_date: date | None,
        to_date: date | None,
        limit: int,
    ) -> list[PredictionMarketOI]:
        params: dict[str, Any] = {"market_id": market_id, "limit": limit}
        predicates = ["market_id = :market_id"]
        if from_date is not None:
            predicates.append("snapshot_date >= :from_date")
            params["from_date"] = from_date
        if to_date is not None:
            predicates.append("snapshot_date <= :to_date")
            params["to_date"] = to_date
        full_sql = (
            "SELECT market_id, snapshot_date, total_oi_usd, total_volume_24h_usd "
            "FROM prediction_market_oi "
            "WHERE " + " AND ".join(predicates) + " "
            "ORDER BY snapshot_date DESC "
            "LIMIT :limit"
        )
        result = await self._session.execute(text(full_sql).bindparams(**params))
        return [_row_to_oi(row) for row in result.fetchall()]

    async def get_latest(self, market_id: str) -> PredictionMarketOI | None:
        """Return the most recent daily roll-up for ``market_id`` (or ``None``)."""
        result = await self._session.execute(
            text(
                "SELECT market_id, snapshot_date, total_oi_usd, total_volume_24h_usd "
                "FROM prediction_market_oi "
                "WHERE market_id = :market_id "
                "ORDER BY snapshot_date DESC "
                "LIMIT 1"
            ).bindparams(market_id=market_id)
        )
        row = result.fetchone()
        return _row_to_oi(row) if row is not None else None


class PgPredictionMarketEventsRepository(PredictionMarketEventsRepository):
    """SQLAlchemy-backed Polymarket "event" group repository (PLAN-0056 A2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, event: PredictionEvent) -> None:
        """Insert or update the event keyed on ``event_id`` (last-write-wins metadata).

        ``id`` is omitted so the DB generates it via ``gen_random_uuid()``; on
        conflict every mutable metadata column is refreshed and ``updated_at``
        bumped. ``event_id`` is the natural business key (UNIQUE index).
        """
        stmt = pg_insert(PredictionEventModel).values(
            event_id=event.event_id,
            name=event.name,
            category=event.category,
            start_date=event.start_date,
            end_date=event.end_date,
            market_count=event.market_count,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["event_id"],
            set_={
                "name": stmt.excluded.name,
                "category": stmt.excluded.category,
                "start_date": stmt.excluded.start_date,
                "end_date": stmt.excluded.end_date,
                "market_count": stmt.excluded.market_count,
                "updated_at": text("now()"),
            },
        )
        await self._session.execute(stmt)

    async def find_by_event_id(self, event_id: str) -> PredictionEvent | None:
        result = await self._session.execute(
            text(
                "SELECT event_id, name, category, start_date, end_date, market_count "
                "FROM prediction_events WHERE event_id = :event_id LIMIT 1"
            ).bindparams(event_id=event_id)
        )
        row = result.fetchone()
        return _row_to_event(row) if row is not None else None

    async def list_events(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[PredictionEvent], int]:
        """Return a page of events + total count.

        Ordered ``start_date DESC NULLS LAST`` so events with a known start date
        surface first (most recent first); undated events sort last.
        ``COUNT(*) OVER()`` piggybacks the total onto the same query.
        """
        result = await self._session.execute(
            text(
                "SELECT event_id, name, category, start_date, end_date, market_count, "
                "COUNT(*) OVER() AS total "
                "FROM prediction_events "
                "ORDER BY start_date DESC NULLS LAST, event_id ASC "
                "LIMIT :limit OFFSET :offset"
            ).bindparams(limit=limit, offset=offset)
        )
        rows = result.fetchall()
        if not rows:
            return [], 0
        total = int(rows[0].total)
        return [_row_to_event(row) for row in rows], total
