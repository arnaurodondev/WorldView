# ADR-0006: TimescaleDB Hypertable for OHLCV Storage

**Date**: 2026-03-10
**Status**: Accepted
**Deciders**: Data Platform Engineer, Architecture Decision Lead

---

## Context

The market-data service stores high-volume time-series OHLCV (Open/High/Low/Close/Volume)
data in the ``ohlcv_bars`` table.  The legacy implementation used native PostgreSQL
`LIST` partitioning on the ``timeframe`` column (9 child tables: `ohlcv_bars_1m` through
`ohlcv_bars_1M`).

The target architecture (``docs/MASTER_PLAN.md``) specifies **TimescaleDB** as the
time-series database engine.  We must choose between:

1. Retaining PostgreSQL LIST partitioning (legacy approach)
2. Using TimescaleDB hypertable partitioned on `bar_date` (new approach)

### Forces at play

- **Query performance**: OHLCV queries always filter on `(instrument_id, timeframe, bar_date range)`.
  Time-based chunk pruning is more efficient than timeframe-based LIST partitions for
  range queries.
- **Operational complexity**: LIST partitioning requires 9 child tables in the ORM,
  migrations, and query layer.  The hypertable is a single table to all clients.
- **Ecosystem fit**: TimescaleDB provides `time_bucket()` aggregates for resampling
  (e.g., 1m → 5m) without custom SQL, directly supporting the downsample query utility.
- **Chunk management**: TimescaleDB automatically creates and maintains time-based chunks;
  LIST partitioning requires manual partition management as timeframes are added.
- **Migration risk**: The existing worldview service uses no production data, so a
  fresh hypertable carries no migration risk.

---

## Decision

Use a **TimescaleDB hypertable** for `ohlcv_bars`, partitioned on `bar_date` with
1-month chunk intervals.

Implementation:
- Migration 001 creates `ohlcv_bars` as a standard PostgreSQL table.
- Migration 002 enables the `timescaledb` extension and calls
  `create_hypertable('ohlcv_bars', 'bar_date', chunk_time_interval => INTERVAL '1 month')`.
- The ORM defines a single `OHLCVBarModel` class (not 9 child models).
- TimescaleDB chunk pruning automatically optimises range queries on `bar_date`.

---

## Consequences

### Positive

- Single `OHLCVBarModel` class — no per-timeframe partition models.
- `time_bucket()` aggregate available for resampling queries (MD-018).
- Automatic chunk creation as data arrives — no manual partition management.
- Range queries on `bar_date` benefit from chunk exclusion (PostgreSQL constraint exclusion
  is equivalent but requires explicit partition bounds).
- Compression and continuous aggregates are available for future optimisation.

### Negative

- Requires `timescaledb` PostgreSQL extension — increases infrastructure dependency.
- Downgrade path for migration 002 drops and recreates `ohlcv_bars` (data loss).
  Acceptable for the current development stage (no production data).
- Local development requires `timescale/timescaledb` Docker image instead of plain
  `postgres`.

### Neutral

- The composite primary key `(instrument_id, timeframe, bar_date)` is unchanged from
  the legacy schema.
- Chunk interval of 1 month is configurable via a future ALTER TABLE call if query
  patterns change.

---

## Alternatives Considered

| Alternative | Pros | Cons | Why Rejected |
|---|---|---|---|
| PostgreSQL LIST partitioning on `timeframe` | Zero external dependency; existing ORM pattern | 9 child tables in ORM/migrations; no time_bucket; manual chunk management; range queries must scan all partitions | Adds complexity without time-range query benefits |
| pg_partman (range partitioning by date) | Automatic partition creation; pure PostgreSQL | No time_bucket; requires pg_partman extension; more config complexity than TimescaleDB | TimescaleDB is already in the target stack (MASTER_PLAN) |
| No partitioning | Simplest possible schema | Table scan on full history at scale; no time_bucket | Unacceptable performance for OHLCV range queries |

---

## Rollback Path

If TimescaleDB must be removed:

1. Run `alembic downgrade 001` — migration 002 downgrade drops and recreates `ohlcv_bars`
   as a plain table (data loss; only acceptable with a full data reload from object storage).
2. Remove `timescaledb` extension: `DROP EXTENSION timescaledb CASCADE`.
3. Optionally re-implement LIST partitioning by adding 9 partition tables in a new migration.

For production rollback, take a full pg_dump of `ohlcv_bars` before downgrading.

---

## References

- `docs/MASTER_PLAN.md` — specifies TimescaleDB as the time-series engine
- `docs/services/market-data.md` — migration section
- `services/market-data/alembic/versions/002_timescaledb_hypertable.py`
- TimescaleDB docs: https://docs.timescale.com/use-timescale/latest/hypertables/
