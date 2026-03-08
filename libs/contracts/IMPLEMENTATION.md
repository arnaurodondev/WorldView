# Implementation Guide — contracts

## Status: Complete

Migration verified: 2026-03-07

## Modules to Implement

- [x] `contracts.versions` — schema version constants (added `MARKET_DATASET_FETCHED_SCHEMA_VERSION`)
- [x] `contracts.canonical.ohlcv` — `CanonicalOHLCVBar` (reconciled: added `provider`, `timeframe`, `fetched_at`)
- [x] `contracts.canonical.quotes` — `CanonicalQuote`
- [x] `contracts.canonical.fundamentals` — `CanonicalFundamentals`
- [x] `contracts.canonical.article` — `CanonicalArticle` (new, aligned with `content.article.stored.v1.avsc`)
- [x] `contracts.canonical.entity` — `CanonicalEntity` (new)
- [x] `contracts.canonical.sentiment` — `CanonicalSentiment` (new)
- [x] `contracts.parsing` — JSONL/JSON/Parquet parsing utilities (structlog logging, pyarrow optional)

## Public API Exports

All models and utilities wired into `contracts/__init__.py` with complete `__all__`:
- Canonical models: `CanonicalOHLCVBar`, `CanonicalQuote`, `CanonicalFundamentals`, `CanonicalArticle`, `CanonicalEntity`, `CanonicalSentiment`
- Parsing: `parse_ohlcv_from_jsonl`, `parse_ohlcv_from_json`, `parse_ohlcv_from_parquet`, `to_jsonl`, `to_parquet`
- Versions: all 7 schema version constants

## Key Decisions

- **float vs Decimal**: All price/numeric fields use `float` (float64, ~15 sig digits). Documented in code and docs.
- **OHLCV field parity**: Added `provider`, `timeframe`, `fetched_at` optional fields to match legacy consumer expectations.
- **Parquet support**: Optional via `pyarrow` — graceful `ImportError` if not installed. Add `[parquet]` extra to enable.
- **Logging**: `structlog` used exclusively in `parsing.py` per project conventions.

## Tests

- `tests/test_ohlcv.py` — 10 test methods including new optional fields
- `tests/test_quotes.py` — 8 test methods
- `tests/test_fundamentals.py` — 8 test methods
- `tests/test_article.py` — 8 test methods including Avro-aligned field check
- `tests/test_entity.py` — 7 test methods
- `tests/test_sentiment.py` — 8 test methods
- `tests/test_parsing.py` — 11 test methods (JSONL, JSON, round-trip, edge cases)
- `tests/test_avro_alignment.py` — 6 test classes validating model fields against Avro schemas

## Migration Source

- `platform_repo/libs/contracts/` → copied & extended with new models
