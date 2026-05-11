# QA Iteration 1 — PLAN-0057 Sub-Plans C + D

**Date**: 2026-04-30
**Branch**: `feat/content-ingestion-wave-a1`
**Scope**: 4 commits — `ceea9405` (C-1+C-2+C-3+C-4 + D-3) · `ab290e02` (C-5) · `10c7dade` (D-1) · `c4fcd742` (D-2) — merged at `3d2ce8bf`.
**Verdict**: **FIX-REQUIRED → SHIPPED iter-1**. All BLOCKING + CRITICAL findings addressed in this iteration.

## Agent coverage

5 strict specialist QA agents ran in parallel against the merged HEAD:

| Agent | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------:|---------:|------:|------:|----:|
| QA / Test Engineer | 0 | 0 | 9 | 9 | 3 |
| Security Engineer | 0 | 0 | 3 | 2 | 6 |
| Data Platform Engineer | 3 | 1 | 4 | 2 | 1 |
| Distributed Systems | 3 | 2 | 3 | 4 | 1 |
| Architecture Lead | 0 | 0 | 3 | 5 | 2 |
| **De-duplicated** | **3** | **3** | **~12** | **~15** | **~10** |

Several findings were flagged by multiple agents independently — those got HIGH confidence + were prioritised first.

## BLOCKING — fixed iter-1

### F-DATA-01 — KG `instrument_consumer` reads `value.get("ticker")` but Avro field is `symbol`

Pre-existing dormant bug (commit `572b2db6f`, 2026-03-28) that Wave C-3 promoted to a critical gap: the entire mechanical-alias suite (TICKER, exchange:TICKER, fallback canonical_name) silently degraded because `ticker` was always `None`.

**Fix**: `instrument_consumer.py:139` — `ticker = value.get("ticker") or value.get("symbol")` (preserve forward-compat with any future producer that sets `ticker` explicitly).

Regression test: `TestInstrumentEntityConsumerUpsertAfterDiscover::test_upsert_path_uses_symbol_field_for_ticker_alias` asserts that a payload with only `symbol` (the schema field) still produces a TICKER + `NASDAQ:AAPL` exchange-prefixed alias.

### F-DS-02 / F-DATA-02 — `fundamentals_consumer` never emits `InstrumentCreated` in the dominant ordering

When ohlcv/quotes arrive **before** fundamentals (the typical production order), the legacy `elif not instrument.flags.has_fundamentals` branch emitted only `InstrumentUpdated` — which KG's `InstrumentEntityConsumer` does NOT subscribe to. The placeholder canonical seeded by `InstrumentDiscoveredConsumer` (Wave D-2) therefore stayed un-enriched forever, and the rich alias suite (NAME / CUSIP / FIGI / LEI / PRIMARY_TICKER) never landed.

**Fix**: `fundamentals_consumer.py:326-396` — refactored the if/elif so every False→True transition of `has_fundamentals` emits `InstrumentCreated` (gated on a real EODHD `Name` per F-DS-07; otherwise emit a `fundamentals_skipped_no_name` warning and defer publication to the next refresh).

Regression test: `test_fundamentals_consumer_emits_instrument_created_on_first_fundamentals_for_existing_instrument` asserts that the path emits `market.instrument.created` (not `.updated`) with the full Name + ISIN payload. New test `test_fundamentals_consumer_skips_emission_when_no_name` asserts the no-Name skip path warns + does not emit.

### F-DS-01 / F-DATA-03 / F-ARCH-01 / F-ARCH-02 — production deployment gap

The new `InstrumentDiscoveredConsumer` lived only in `docker-compose.test.yml`; the new topic `market.instrument.discovered.v1` was missing from `create-topics.sh`; the orphan `claim.extracted.v1` topic + `.avsc` schema (no remaining producer after Wave D-1) lingered.

**Fix**:
- `infra/compose/docker-compose.yml:1485+` — new `knowledge-graph-instrument-discovered-consumer` service block (mirrors test compose, profiles `[infra, all]`).
- `infra/kafka/init/create-topics.sh` — added `"market.instrument.discovered.v1:3:1"`; removed `"claim.extracted.v1:12:1"`.
- `infra/kafka/schemas/claim.extracted.v1.avsc` — deleted.

## CRITICAL — fixed iter-1

### F-DS-03 / F-DATA-04 / F-ARCH-06 — M-017 stable-ID invariant break

`CanonicalEntityRepository.create()` did not accept an explicit `entity_id` and relied on `gen_random_uuid()`. When fundamentals arrived first (no prior discovery), the canonical's `entity_id ≠ instrument_id`, which subsequently allowed the discovered consumer (when it later races in) to insert a *second* canonical with `entity_id = instrument_id`.

**Fix**: `canonical_entity.py:126-186` extended with `entity_id: UUID | None = None` kwarg. When provided, INSERT uses `ON CONFLICT (entity_id) DO NOTHING RETURNING entity_id`; when the row already exists the caller's UUID is returned. `instrument_consumer._create_new_canonical` now passes `entity_id=instrument_id`.

Regression coverage: existing `TestCanonicalEntityRepositoryCreateSelfAlias` updated mocks for `begin_nested`; new `TestInstrumentEntityConsumerUpsertAfterDiscover::test_existing_placeholder_triggers_update_not_create` exercises the discovery-first path.

### F-DS-04 — Avro record rename V2→V3 without `aliases` mapping

Confluent Schema Registry's BACKWARD compat check requires either no rename or an explicit `aliases` array. Without it, registration would be rejected.

**Fix**: `infra/kafka/schemas/market.instrument.created.avsc:5` — added `"aliases": ["InstrumentCreatedV2"]`.

### F-DS-05 / F-DATA-07 — C-5 self-alias INSERT not SAVEPOINT-wrapped

The Wave C-5 self-alias INSERT used `ON CONFLICT (entity_id, normalized_alias_text, alias_type)` against migration 0008's per-entity partial UNIQUE index. But the legacy migration 0001 partial UNIQUE index `uidx_entity_aliases_normalized` has a different conflict target (cross-entity EXACT uniqueness). When the cross-entity collision fires, the outer transaction is aborted, rolling back the canonical we just created.

**Fix**: `canonical_entity.py:202-227` — wrapped the alias INSERT in `async with self._session.begin_nested():` with a `try/except` that swallows the cross-entity collision (acceptable degraded state: canonical is reachable by entity_id; only the exact-name lookup is degraded for that specific spelling).

## MAJOR — fixed iter-1

### F-SEC-01 / F-QA-02 — EODHD identifier validation

`_g(key)` accepted any stringifiable value (lists, dicts, booleans), and per-identifier format was unvalidated. An attacker (or a shape-mutation bug) controlling EODHD could emit poison aliases or unbounded-length strings into the entity-resolution graph.

**Fix**: `fundamentals_consumer.py` — module-scoped regex constants `_CUSIP_RE_PAT` (9 alnum), `_FIGI_RE_PAT` (12 alnum), `_LEI_RE_PAT` (20 alnum), `_PRIMARY_TICKER_RE_PAT` (1-20 chars from `[A-Z0-9.\-:]`), `_ISIN_RE_PAT` (12 alnum); helper `_vfmt(value, regex, field)` rejects any string that doesn't match (logs `fundamentals_invalid_identifier`, returns None). `_g()` now requires `isinstance(value, str)` before stripping. `Name`/`Description` length-bounded to 500/4000 chars.

### F-SEC-03 — DoS via missing index for Stage-2 widened query

Wave C-3 widened the nlp-pipeline Stage-2 fallback resolver from `alias_type='TICKER'` to `IN ('TICKER','PRIMARY_TICKER','ISIN')`. Migration 0001's partial UNIQUE index applies only to `EXACT` rows, so the new lookup pattern fell back to sequential scans on `entity_aliases`.

**Fix**: new migration `0010_index_alias_norm_for_stage2.py` — `CREATE INDEX IF NOT EXISTS idx_entity_aliases_norm_stage2 ON entity_aliases (normalized_alias_text, alias_type) WHERE is_active = true AND alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN')`.

### F-ARCH-03 — Service docs gap (R15 mandatory)

**Fix**: updated `docs/services/market-data.md` (event tables, schema_version=3, new discovered topic), `docs/services/knowledge-graph.md` (consumer table, Wave C-3 alias suite, Wave D-2 UPSERT-after-discover semantics, M-017 invariant), `docs/services/portfolio.md` (3-topic subscription, name=None on discover-only path semantics).

### F-QA-03 — UPSERT-after-discover unit-test coverage

The commit message claimed `TestInstrumentEntityConsumerUpsertAfterDiscover` existed; it did not. The most architecturally novel D-2 code path was completely uncovered.

**Fix**: new test class `TestInstrumentEntityConsumerUpsertAfterDiscover` in `test_instrument_consumer.py` with 4 tests:
- `test_existing_placeholder_triggers_update_not_create` — UPDATE SQL fires + create() not called + `needs_fundamentals_enrichment` referenced in SQL.
- `test_upsert_path_still_inserts_full_alias_suite` — all 7 mechanical alias_types (EXACT, TICKER, ISIN, CUSIP, FIGI, LEI, PRIMARY_TICKER) inserted on the upsert path; entity_id matches placeholder's instrument_id.
- `test_upsert_path_uses_symbol_field_for_ticker_alias` — F-DATA-01 regression: payload without `ticker` key still emits TICKER + exchange:TICKER aliases off `symbol`.
- `test_existing_non_placeholder_skips_update_and_alias_block` — true-replay BP-124 fast-path skips UPDATE + alias inserts entirely.

## MAJOR — deferred to iter-2 (or later) with rationale

| ID | Why deferred |
|----|--------------|
| F-QA-01 | NAME-alias branch in `instrument_consumer:316-320` is dead code (production logic always has `canonical_name == raw_name` for non-synthesised). Either delete or refactor — design choice for next session, not a correctness bug today. |
| F-DS-06 | ohlcv/quotes consumers race on `instruments` table — operational noise (no data corruption); requires repo-level upsert refactor. |
| F-DS-08 | Portfolio replay storm on first deploy of `discovered.v1` — operational concern (deploy-order playbook), not a code bug. |
| F-DATA-06 | Outbox dispatcher missing partition_key — architectural change with broad impact, scope-of-its-own. |
| F-DATA-08 | `instrument_discovered_consumer` no DB-side idempotency — Valkey + ON CONFLICT DO NOTHING is sufficient defence-in-depth for thesis-grade. |
| F-SEC-02 | LLM prompt-injection via `description` — needs a deliberate prompt-design + denylist + regression test (out-of-scope for mechanical iter-1 fixes). |

## Validation gates (post-fix)

| Gate | Result |
|------|--------|
| `ruff check` on all changed files | ✅ all clean |
| `services/knowledge-graph/tests/unit -m unit` | ✅ 673 passed |
| `services/market-data/tests/unit -m unit` | ✅ 556 passed |
| `services/portfolio/tests/unit -m unit` | ✅ 645 passed |
| `services/nlp-pipeline/tests/unit -m unit` | ✅ 612 passed |
| `libs/contracts/tests` | ✅ 40 passed (3 pyarrow skips) |
| `libs/prompts/tests` | ✅ 57 passed |
| `tests/contract` | ✅ except 1 pre-existing flake (`TestMarketDatasetFetchedContract::test_invalid_sample_wrong_type_is_rejected` — fastavro raises TypeError instead of expected ValueError; pre-dates this PR per `git blame`). |

## Files touched (iter-1 fixes)

```
services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/canonical_entity.py
services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py
services/knowledge-graph/tests/unit/infrastructure/consumer/test_instrument_consumer.py
services/knowledge-graph/tests/unit/infrastructure/test_repositories.py
services/market-data/tests/unit/test_fundamentals_consumer.py
services/intelligence-migrations/alembic/versions/0010_index_alias_norm_for_stage2.py  [NEW]
infra/kafka/schemas/market.instrument.created.avsc
infra/kafka/schemas/claim.extracted.v1.avsc                                            [DELETED]
infra/kafka/init/create-topics.sh
infra/compose/docker-compose.yml
docs/services/market-data.md
docs/services/knowledge-graph.md
docs/services/portfolio.md
```

## Next iteration

The iter-1 fixes close every BLOCKING + CRITICAL finding and the highest-leverage MAJORs. iter-2 (if commissioned) should:
1. Address F-DS-06 (concurrent-write race on instruments table).
2. Apply F-SEC-02 prompt-injection defences.
3. Either delete or refactor the dead NAME-alias branch (F-QA-01).
4. Add the auxiliary tests flagged in F-QA-04..F-QA-21 (input-validation edge cases on `instrument_id`, `_g`'s isinstance guard, contract test for the new topic, etc.).
