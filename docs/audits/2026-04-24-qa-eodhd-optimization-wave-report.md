# QA Report: EODHD Optimization Wave (OPT-3/10 + D-W1/2/3/5)

**Date**: 2026-04-24 UTC
**Skill**: qa
**Scope**: commit f0a031f — content-ingestion, market-ingestion, knowledge-graph
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: PASS_WITH_WARNINGS
**Report file**: docs/audits/2026-04-24-qa-eodhd-optimization-wave-report.md

---

## Executive Summary

5-agent review of commit f0a031f (EODHD optimization wave: OPT-3/10 + D-W1/2/3/5). The commit
implements a pagination cap, weekly insider_transactions interval, a canonical passthrough serializer
for 7 dataset types, expanded economic event countries, 3 new Kafka consumers replacing direct EODHD
polling, and tombstoning of the 3 retired KG workers.

**Critical findings fixed in this QA pass**:
- **BLOCKING** (F-ARCH-001/F-DS-004): 3 new consumers were absent from docker-compose.yml — they
  would never run in any deployed environment. Added 3 service definitions.
- **BLOCKING** (F-DP-001): `_parse_symbol()` in macro_indicator consumer had inverted symbol format
  assumption (`rsplit` on `"USA.gdp_current_usd"` returned indicator="usa", country="gdp_current_usd"`).
  Fixed with `partition(".")` + swapped return order. All tests updated.
- **CRITICAL** (F-DP-002/F-ARCH-002): Economic events consumer passed alpha-3 codes ("USA", "JPN")
  to `find_country_entity()` which expects alpha-2. Added `_ISO3_TO_ISO2` mapping. Entity exposure
  linking now works for all 6 seeded countries.
- **MAJOR** (F-DS-005): `_download_envelope()` swallowed all storage exceptions as `None` → base class
  committed offset with no data processed. Now re-raises transient exceptions (JSON decode errors
  still return None as non-retryable).
- **MAJOR** (F-DS-002): Valkey dedup TTL was 24h but insider_transactions polling interval is 7 days.
  Extended to 7 days (`ex=7 * 86400`) across all 3 consumers.
- **MAJOR** (F-QA-002): Tombstone test files contained only comments with zero tests. Replaced with
  ImportError verification tests for all 4 tombstoned modules.

Post-fix: 631/631 KG unit tests pass, 548/548 content-ingestion, 224/224 market-ingestion.
Ruff clean, format clean. Branch verdict: **PASS_WITH_WARNINGS** — several architectural patterns
(outbox for entity.dirtied, TOCTOU on macro_indicators JSONB) are known limitations deferred to
future waves.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 38 | 18 | 0 | 0 | 7 | 8 | 3 |
| Security | 10 | 8 | 0 | 0 | 0 | 6 | 2 |
| Data Platform | 38 | 10 | 1 | 1 | 2 | 3 | 3 |
| Distributed Systems | 38 | 11 | 1 | 1 | 4 | 4 | 1 |
| Architecture | 38 | 14 | 1 | 1 | 3 | 3 | 6 |
| **Total** | — | **61** | **3** | **3** | **16** | **24** | **15** |

### Cross-Agent Signals (HIGH Confidence — Multiple Agents)

| Signal | Agents | Verdict |
|--------|--------|---------|
| 3 consumers missing from docker-compose | DS + ARCH | FIXED |
| ISO3→ISO2 mismatch in economic events consumer | DP + ARCH | FIXED |
| `_parse_symbol()` format inversion in macro consumer | DP (HIGH confidence) | FIXED |
| entity.dirtied.v1 outside outbox (best-effort) | DS + ARCH + DP | OPEN — deferred (documented) |

### Fixes Applied

| Finding | Fix | Status |
|---------|-----|--------|
| F-ARCH-001/F-DS-004 | Added 3 docker-compose service definitions | APPLIED |
| F-DP-001 | Fixed `_parse_symbol()` symbol format inversion; updated all tests | APPLIED |
| F-DP-002/F-ARCH-002 | Added `_ISO3_TO_ISO2` + updated `_extract_country_from_symbol()` | APPLIED |
| F-DS-005 | Re-raise transient storage exceptions in `_download_envelope()` (all 3) | APPLIED |
| F-DS-002 | Extended Valkey dedup TTL: 86400s → 7 * 86400s (all 3 consumers) | APPLIED |
| F-QA-002 | Added ImportError tests for 4 tombstoned modules | APPLIED |
| F-SEC-001 | Added `ge=1, le=50` bound to `max_pages_per_cycle` in content-ingestion | APPLIED |
| F-SEC-004 | Truncate officer name to 500 chars before INSERT in `find_or_create_person()` | APPLIED |
| F-SEC-005 | Added `[:2000]` description size cap in economic events consumer | APPLIED |
| F-DP-009/F-ARCH-008 | Replaced `datetime.now(tz=UTC)` with `utc_now()` in `serialize_passthrough()` | APPLIED |
| F-ARCH-003 | Updated `app.py` docstring with all 10 standalone processes | APPLIED |
| F-ARCH-005 | Fixed metric name in docs: `s7_insider_transactions_updates_total` → `s7_insider_transactions_relations_total` | APPLIED |
| F-QA-016 | Tombstone test storage error tests updated to expect exception propagation | APPLIED |
| ruff format | 2 pre-existing format violations in KG consumer mains | APPLIED |

### Decisions Deferred (Open Items)

| Finding | Status | Rationale |
|---------|--------|-----------|
| F-DS-001: Batch commit + offset advance on exception | OPEN | Per-event commit vs per-batch is an architectural trade-off; upsert idempotency provides safety net |
| F-DS-003: TOCTOU JSONB merge race in macro_indicator | OPEN | Low probability under single-consumer topology; SELECT FOR UPDATE deferred to perf wave |
| F-DS-007/F-ARCH-011: entity.dirtied outside outbox | OPEN | Documented as best-effort; outbox migration tracked for D-W6 |
| F-SEC-006: MinIO bucket allowlist in consumers | OPEN | Internal-only topic; allowlist adds value but requires config decision |
| F-DP-010: Missing UNIQUE constraint on canonical_entities(entity_type, canonical_name) | OPEN | Pre-existing schema gap; migration required in intelligence-migrations |
| F-ARCH-014: EODHD API country codes for JPN/CHN | OPEN | Verify EODHD accepts 3-letter codes at runtime |
| F-QA-001: Missing dedup/mark_processed tests (positive path) | OPEN | Low risk; dedup logic covered in base class tests |
| F-QA-003: `deserialize_value()` untested in new consumers | OPEN | BP-122 fix is identical to existing consumers; test coverage gap |
| F-QA-005: EntityRepository new methods untested | OPEN | Integration-only path; unit mock needed |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Lint (ruff) | Changed files | — | — | 0 errors | — | PASS |
| Format (ruff) | Changed files | — | — | 0 errors | — | PASS |
| Service Unit | knowledge-graph | 631 | 631 | 0 | 0 | PASS |
| Service Unit | content-ingestion | 548 | 548 | 0 | 0 | PASS |
| Service Unit | market-ingestion | 224 | 224 | 0 | 5 skip | PASS |

### Per-Service Breakdown (scope: changed services)

| Service | Unit | Status |
|---------|------|--------|
| knowledge-graph | 631/631 | PASS |
| content-ingestion | 548/548 | PASS |
| market-ingestion | 224/224 (5 skip — infra) | PASS |

---

## Issues — Full Investigation

### F-DP-001 / F-DS-004-equivalent: `_parse_symbol()` Format Inversion (FIXED)

**Severity**: BLOCKING
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/macro_indicator_dataset_consumer.py:108`
**Root Cause**: S2 seeds and emits symbols as `"COUNTRY.indicator_code"` (e.g. `"USA.gdp_current_usd"`)
per `0002_initial_seeds.py` line 345: `_insert_policy("eodhd", "macro_indicator", f"USA.{indicator}", ...)`.
The consumer's `_parse_symbol()` used `rsplit(".", 1)` and returned `(parts[0].lower(), parts[1])` =
`(indicator_code, iso3)`. Applied to `"USA.gdp_current_usd"`: `indicator_code="usa"`, `iso3="gdp_current_usd"`.
Both values were wrong. The entity lookup `find_country_entity("gdp_current_usd")` always returned None,
and the indicator was never stored.

**Fix Applied**: Changed to `symbol.partition(".")` returning `(indicator_code.lower(), country)` =
`("gdp_current_usd", "USA")`. All 30+ test cases updated to use `"USA.gdp_current_usd"` format.

---

### F-DP-002/F-ARCH-002: ISO3 Country Code Mismatch (FIXED)

**Severity**: CRITICAL
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/economic_events_dataset_consumer.py:91`
**Root Cause**: `_extract_country_from_symbol("EVENTS.USA")` returned `"USA"` (alpha-3).
`find_country_entity()` queries `WHERE metadata->>'country_iso' = :iso2` — country entities are seeded
with alpha-2 codes (`"US"`, `"GB"` etc). No entity was ever linked to any economic event. New D-W2
countries (JPN, CHN) would also fail.

**Fix Applied**: Added `_ISO3_TO_ISO2` dict covering all 6 seeded event countries. Updated
`_extract_country_from_symbol()` to normalize alpha-3→alpha-2. Updated tests.

---

### F-ARCH-001/F-DS-004: Missing docker-compose Entries (FIXED)

**Severity**: BLOCKING
**File**: `infra/compose/docker-compose.yml:1396`
**Root Cause**: D-W3 created 3 standalone consumer entry points but docker-compose was not updated.
APScheduler's 3 cron jobs (D-W5) were removed. Result: zero processing of economic_events,
macro_indicator, and insider_transactions datasets in any deployed environment.

**Fix Applied**: Added 3 service definitions following the `knowledge-graph-temporal-event-consumer`
pattern exactly.

---

### F-DS-005: Storage Exception Swallowed → Data Loss (FIXED)

**Severity**: MAJOR
**File**: All 3 `_download_envelope()` methods
**Root Cause**: A bare `except Exception: return None` caused transient MinIO errors to appear as
"skip this message" to the base class, which then committed the Kafka offset. Data was permanently
lost.

**Fix Applied**: Split into `except json.JSONDecodeError` (data quality issue → return None) and
`except Exception` → re-raise (transient → base class handles, offset not committed).

---

### F-DS-002: Valkey Dedup TTL Too Short (FIXED)

**Severity**: MAJOR
**Root Cause**: `ex=86400` (24h) < `insider_transactions` polling interval (604,800s / 7 days).
Dedup key could expire before re-delivery window, causing re-processing.

**Fix Applied**: Changed to `ex=7 * 86400` across all 3 consumers.

---

## Decisions Needed

| ID | Question | Context |
|----|----------|---------|
| D-1 | Should `entity.dirtied.v1` go through the outbox pattern? | Currently fire-and-forget; guaranteed delivery requires refactor |
| D-2 | Add UNIQUE constraint on `(entity_type, canonical_name)` in `canonical_entities`? | Needed for correct `ON CONFLICT` semantics in `find_or_create_person()` |
| D-3 | MinIO bucket allowlist in claim-check consumers? | Security hardening for internal Kafka compromise scenario |
| D-4 | Confirm EODHD API accepts `JPN`/`CHN`/`EU` for economic events endpoint? | Runtime verification needed before D-W2 goes live |

---

## New Bug Patterns to Add

### BP-215: Consumer `_parse_symbol()` format inversion
**Pattern**: Consumer assumes `INDICATOR.COUNTRY` format but S2 seeds use `COUNTRY.INDICATOR`.
`rsplit(".", 1)` on `"USA.gdp_current_usd"` returns wrong tuple order.
**Detection**: Check `_parse_symbol()` return order matches `(indicator_code, country)` against seed format.
**Fix**: Use `partition(".")` and verify against actual seed data before writing consumers.

### BP-216: ISO3 country codes not normalized for entity lookups
**Pattern**: Country entity metadata uses alpha-2 (`country_iso`). Consumer receives alpha-3 from
S2 symbol suffix. Without normalization, `find_country_entity()` always returns None.
**Detection**: Check all `find_country_entity()` call sites pass alpha-2 codes.
**Fix**: Add `_ISO3_TO_ISO2` lookup in consumer before passing to entity repo.

### BP-217: New consumer processes absent from docker-compose.yml
**Pattern**: Standalone entry point created + committed but docker-compose not updated. Service
never runs in any deployed environment. Especially dangerous when replacing a cron-based worker
(double gap: old worker removed, new consumer never started).
**Detection**: After adding `_main.py` entrypoints, grep `docker-compose.yml` for the module name.
**Fix**: Add docker-compose service definition immediately in the same commit.

---

## Recommendations

1. **Ship now** — BLOCKING and CRITICAL fixes are applied. All unit tests pass. Ready to merge.
2. **Add D-2 migration** — `UNIQUE INDEX uidx_canonical_entities_type_name` on `(entity_type, canonical_name)` to make `ON CONFLICT` in `find_or_create_person()` semantically correct.
3. **Runtime verify D-4** — Confirm EODHD accepts `JPN`/`CHN`/`EU` codes by testing one economic events fetch.
4. **Add `/test-feature` pass** — `EntityRepository.find_instrument_by_ticker()`, `find_or_create_person()`, `get_metadata_field()` lack unit tests; `deserialize_value()` in all 3 consumers is untested.
5. **Add TOCTOU fix** — Replace double-read in `macro_indicator_consumer._process_indicator()` with atomic JSONB merge update (`jsonb_set`) or SELECT FOR UPDATE.
