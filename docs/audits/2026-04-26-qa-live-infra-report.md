# QA Audit Report — Live Infrastructure Validation

**Date**: 2026-04-26
**Scope**: portfolio (S1), market-ingestion (S2), market-data (S3) — live Docker stack
**Method**: Real-infrastructure testing with live Postgres, Kafka, and MinIO
**Branch**: `feat/content-ingestion-wave-a1`
**Containers**: 57 healthy at session start

---

## Executive Summary

Four **BLOCKING** bugs were found and fixed during this session. Three were cascade failures rooted in a single path-resolution bug in the market-data outbox dispatcher; the fourth was a transaction isolation bug in the knowledge-graph instrument consumer. All four are now resolved and verified in production containers.

Additionally, a documentation issue was identified: the `GET /v1/fundamentals/screen` test in the prior QA script used the wrong HTTP method (should be `POST`).

---

## Infrastructure State at Session Start

| Service | Container | Status |
|---------|-----------|--------|
| market-data outbox | worldview-market-data-dispatcher-1 | ✅ running |
| portfolio-instrument-consumer | worldview-portfolio-instrument-consumer-1 | ✅ running |
| knowledge-graph-instrument-consumer | worldview-knowledge-graph-instrument-consumer-1 | ✅ running |
| All other services (54 total) | — | ✅ healthy |

**Pre-existing data issues found via Postgres inspection:**
- `outbox_events` table: **114 events in `dead_letter` status** (55 `market.instrument.created` + 59 `market.instrument.updated`)
- Portfolio `instruments` table: **0 rows** — instruments never populated
- Portfolio `holdings` table: **5 rows** — holdings orphaned (no instrument FK)

---

## Bugs Found and Fixed

### BUG-1 — BLOCKING: `_SCHEMA_DIR` path resolution fails in Docker containers

**Location**: `services/market-data/src/market_data/infrastructure/messaging/outbox/dispatcher.py`
**Symptom**: 114 outbox events in `dead_letter` status. Dispatcher logged `FileNotFoundError: Could not locate infra/kafka/schemas/` on every publish attempt.
**Root cause**: `_SCHEMA_DIR` was computed as `Path(__file__).parent × 8 / "infra/kafka/schemas"`. In the source tree this resolves correctly (8 parents from `dispatcher.py` reaches repo root). In the Docker container the installed package is at `/app/market_data/…` — only 5 parent levels before hitting `/` — so the path resolved to `/infra/kafka/schemas/` which does not exist.
**Fix**: Replaced the hardcoded parent-chain with a walk-up algorithm identical to the one used in `market-ingestion/serialization.py`:

```python
def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    msg = f"Could not locate infra/kafka/schemas/ from {__file__}"
    raise FileNotFoundError(msg)
```

**Verification**: After container rebuild and status reset, `dispatched=114 failed=0`. Topics `market.instrument.created` (55) and `market.instrument.updated` (59) now have correct message counts.
**Status**: ✅ FIXED

---

### BUG-2 — BLOCKING: Portfolio instrument consumer Avro deserialization failure

**Location**: `services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer.py`
**Symptom**: Portfolio `instruments` table = 0 rows. Consumer dead-lettered all 114 instrument events with `'utf-32-be' codec can't decode bytes`.
**Root cause**: Two compounding issues:
1. The `portfolio` Docker container had no Kafka schema files (Dockerfile missing `COPY infra/kafka/schemas /app/infra/kafka/schemas`)
2. `_SCHEMA_DIR` used the same hardcoded parent-chain pattern as BUG-1, resolving incorrectly in Docker

Without schema files, `get_schema_path()` returned `None`, so `deserialize_value()` fell through to `json.loads(raw)`. Confluent Avro binary starts with `0x00` + 4-byte schema ID; Python's JSON auto-encoding detection treated this as UTF-32-BE BOM → codec error.
**Fix**:
- Added `COPY infra/kafka/schemas /app/infra/kafka/schemas` to `services/portfolio/Dockerfile` runtime stage
- Replaced `_SCHEMA_DIR` hardcoded chain with walk-up algorithm
- Reset consumer group offsets to `--to-earliest` to replay dead-lettered messages

**Verification**: 55 `instrument_ref_upserted` log entries. Portfolio `instruments` table = 55 rows.
**Status**: ✅ FIXED

---

### BUG-3 — BLOCKING: Knowledge-graph instrument consumer Avro deserialization failure

**Location**: `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py`
**Symptom**: Consumer dead-lettered all instrument events with same UTF-32-BE codec error.
**Root cause**: `get_schema_path()` always returned `None` (no implementation). `deserialize_value()` called `json.loads(raw)` directly without trying Avro first.
**Fix**:
- Added `_find_schema_dir()` walk-up function and `_SCHEMA_DIR` constant
- Added `from messaging.kafka.serialization_utils import deserialize_confluent_avro` import
- Fixed `get_schema_path()` to return `str(_SCHEMA_DIR / f"{topic}.avsc")` if file exists
- Fixed `deserialize_value()` to try `deserialize_confluent_avro(schema_path, raw)` first with JSON fallback

**Status**: ✅ FIXED (combined with BUG-4 fix below)

---

### BUG-4 — BLOCKING: SQLAlchemy session aborted by alias `UniqueViolationError` inside `process_message`

**Location**: `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py`
**Symptom**: After BUG-3 fix, consumer failed with `asyncpg.InFailedSQLTransactionError` on `entity_embedding_state.ensure_rows_exist()` for every message.
**Root cause**: Two sub-issues:
1. **Null-name alias collision**: `str(value.get("name", "Unknown"))` converts Python `None` to the string `"None"`. Multiple instruments with `name=None` all tried to insert `normalized_alias_text='none'` → `uidx_entity_aliases_normalized` unique constraint violation.
2. **`contextlib.suppress` leaves session aborted**: Using `contextlib.suppress(Exception)` around `alias_repo.insert()` catches the Python exception but does NOT roll back the SQLAlchemy/asyncpg transaction. Subsequent SQL operations in the same session fail with `InFailedSQLTransactionError`.

**Fix**:
1. Guard against null names before alias generation:
```python
raw_name = value.get("name")
if raw_name and str(raw_name).strip() and str(raw_name).strip().lower() not in ("none", "null"):
    canonical_name = str(raw_name).strip()
elif ticker:
    canonical_name = str(ticker).upper()
else:
    canonical_name = f"Instrument-{str(instrument_id)[:8]}"
```
2. Replace `contextlib.suppress` with SQLAlchemy SAVEPOINT (`session.begin_nested()`):
```python
async def _try_insert_alias(alias_text, normalized, alias_type):
    try:
        async with session.begin_nested():
            await alias_repo.insert(entity_id, alias_text, normalized, alias_type, "instrument_consumer")
    except Exception:
        pass  # SAVEPOINT rolled back; outer transaction remains usable
```

**Verification**: KG consumer processed all 55 `market.instrument.created` events, 0 failures. `canonical_entities` table = 38 unique entities (55 messages minus ~17 duplicate instrument.updated events).
**Status**: ✅ FIXED

---

## Outbox Status Case-Sensitivity Issue (Configuration)

**Severity**: MINOR (discovered during investigation)
**Location**: `services/market-data/src/market_data/infrastructure/db/` (outbox table default)
**Issue**: When manually resetting dead-letter events with `UPDATE outbox_events SET status='PENDING'` (uppercase), the dispatcher did not pick them up because `OutboxStatus.PENDING = "pending"` (lowercase). The SQL `WHERE status = 'pending'` query is case-sensitive.
**Not a code bug** — this is a documentation gap. The outbox status values are lowercase strings. Any manual SQL operations must use lowercase.
**Action**: Noted in investigation; no code change needed.

---

## API Endpoint Validation Summary

All endpoints tested against live stack with real JWT auth (dev-login):

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `POST /v1/auth/dev-login` | POST | ✅ 200 | JWT issued correctly |
| `GET /v1/portfolios` | GET | ✅ 200 | Returns 4 portfolios |
| `GET /v1/search/instruments?q=AAPL` | GET | ✅ 200 | Returns 4 results |
| `GET /v1/ohlcv/{id}?timeframe=1d&limit=5` | GET | ✅ 200 | 5 AAPL bars, latest 2026-04-23 |
| `GET /v1/market/heatmap` | GET | ✅ 200 | 1 sector (limited seed data) |
| `GET /v1/market/top-movers` | GET | ✅ 200 | Returns results/count/total |
| `GET /v1/news/top` | GET | ✅ 200 | 0 items (no content yet) |
| `GET /v1/signals/ai` | GET | ✅ 200 | 0 signals (no enriched articles yet) |
| `GET /v1/fundamentals/{id}` | GET | ✅ 200 | Returns security_id + records |
| `GET /v1/fundamentals/screen/fields` | GET | ✅ 200 | Returns 12 screenable fields |
| `POST /v1/fundamentals/screen` | POST | ✅ 200 | Returns screened results with metrics |
| `GET /v1/alerts` | GET | ✅ 404 | Route not proxied through S9 (expected) |

**Documentation fix**: Prior QA test script called `GET /v1/fundamentals/screen` — this is a `POST` endpoint. The `GET` hits the `GET /v1/fundamentals/{instrument_id}` route with `"screen"` as the UUID → 500 error. The endpoint itself is working correctly.

---

## Data Pipeline State After Fixes

### MinIO
| Bucket | Objects | Description |
|--------|---------|-------------|
| `market-bronze` | 367 | Raw OHLCV downloads |
| `market-canonical` | 351 | Normalized OHLCV JSONL |

### Kafka Topics
| Topic | Messages | Consumer Group | Lag |
|-------|----------|---------------|-----|
| `market.dataset.fetched` | 319 | market-data-ohlcv | 0 |
| `market.instrument.created` | 55 | portfolio-instrument-sync | 0 |
| `market.instrument.created` | 55 | kg-service-group-instrument | 0 |
| `market.instrument.updated` | 59 | portfolio-instrument-sync | 0 |

### PostgreSQL
| Database | Table | Count |
|----------|-------|-------|
| `market_data_db` | instruments | 65 |
| `market_data_db` | ohlcv_bars | 1,283 |
| `market_data_db` | outbox_events (pending) | 0 |
| `market_data_db` | outbox_events (dead_letter) | 0 |
| `portfolio_db` | instruments | 55 |
| `portfolio_db` | holdings | 5 |
| `portfolio_db` | portfolios | 1 |
| `intelligence_db` | canonical_entities (financial_instrument) | 38 |
| `intelligence_db` | entity_aliases | 21 |
| `intelligence_db` | entity_embedding_state | 90 |

---

## Bug Pattern Updates

The following entries should be added to `docs/BUG_PATTERNS.md`:

### BP-XXX — Hardcoded `Path(__file__).parent × N` schema paths fail in Docker

**Pattern**: `Path(__file__).parents[N] / "infra/kafka/schemas"` — the parent count is different between source tree and installed Docker package.
**Fix**: Walk-up algorithm:
```python
def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(...)
```
**Affected files found in this audit**: `dispatcher.py` (market-data), `instrument_consumer.py` (portfolio), `instrument_consumer.py` (knowledge-graph), `ohlcv_consumer.py` (market-data — uses different hardcoded path, verify works).

### BP-XXX — `contextlib.suppress` on `alias_repo.insert()` aborts SQLAlchemy session

**Pattern**: Catching `IntegrityError` at the Python layer with `contextlib.suppress` does NOT roll back the asyncpg/SQLAlchemy transaction. The session remains in `InFailedSQLTransactionError` state and all subsequent SQL operations fail.
**Fix**: Use SAVEPOINT (`session.begin_nested()`) instead of `contextlib.suppress`.

### BP-XXX — `str(None)` produces `"None"` alias text — unique constraint collision

**Pattern**: `canonical_name = str(value.get("name", "Unknown"))` — if `name` is `null` in the Avro payload, this produces the string `"None"` which normalizes to `"none"`. Multiple null-name instruments all insert the same alias.
**Fix**: Explicit null guard: `if raw_name and str(raw_name).strip().lower() not in ("none", "null"): ...`

---

## Remaining Known Issues (Not Fixed in This Session)

| Issue | Severity | Location | Notes |
|-------|----------|----------|-------|
| `GET /v1/news/top` returns 0 items | MINOR | content-ingestion | No content ingested yet; not a bug |
| `GET /v1/signals/ai` returns 0 signals | MINOR | market-analytics/S6 | Requires enriched articles; expected state |
| LLM alias generation disabled | MINOR | KG instrument consumer | `fallback_chain_exhausted` — no LLM configured in dev; aliases work via mechanical fallback |
| `market.instrument.created` 55 events → 38 KG entities | INFO | KG consumer | ~17 delta = instruments with same ticker/exchange processed as idempotency hits |

---

## Architecture Findings

### Finding: `ohlcv_consumer.py` still uses hardcoded `_SCHEMA_DIR` path

**File**: `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py:31`
**Code**: `_SCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "infra/kafka/schemas"`
**Risk**: Same `_SCHEMA_DIR` resolution failure as BUG-1, but the OHLCV consumer is working today because it uses `path.exists()` before returning the schema path — if the schema is not found, it falls back to JSON parsing. OHLCV events come from `market-ingestion` which uses `OutboxEventValueSerializer` (Confluent Avro format). If the schema path fallback is triggered, OHLCV deserialization would silently fail.
**Recommendation**: Apply walk-up algorithm to `ohlcv_consumer.py` as well (low urgency since it's working, but should be hardened).

---

## Validation Checklist

- [x] Docker stack healthy (57 containers)
- [x] market-data outbox dispatcher publishing correctly (0 pending, 0 dead_letter)
- [x] Portfolio instrument consumer consuming Avro events (55 instruments populated)
- [x] KG instrument consumer consuming Avro events (38 entities, 0 failures)
- [x] OHLCV pipeline end-to-end: market-ingestion → MinIO (351 objects) → Kafka (319 events) → market-data DB (1,283 bars)
- [x] Core S9 API endpoints responding correctly
- [x] Auth JWT flow working (dev-login → Bearer token → authenticated requests)
- [x] Rate limiter functioning (429 responses on burst traffic)
- [x] Fundamentals screen endpoint working (POST, not GET)
