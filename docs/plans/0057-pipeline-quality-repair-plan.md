---
id: PLAN-0057
prd: docs/audits/2026-04-29-investigation-news-pipeline-quality-deep-dive.md
title: "News-Intelligence Pipeline Quality Repair — Implementation Plan"
status: in-progress
created: 2026-04-30
updated: 2026-04-30
plans: 6
waves: 24
tasks: 0
---

# PLAN-0057: News-Intelligence Pipeline Quality Repair

## Overview

**Source investigation**: [`docs/audits/2026-04-29-investigation-news-pipeline-quality-deep-dive.md`](../audits/2026-04-29-investigation-news-pipeline-quality-deep-dive.md) (with 2026-04-30 §6 update).

**Goal**: take the S4→S5→S6→S7 pipeline from "all containers green / zero usable intelligence" to "producing real entities, claims, relations, summaries end-to-end" by closing the 6 CRITICAL and 8 MAJOR audit findings (F-CRIT-02 through F-CRIT-12 plus selected MAJORs). The headline lever is F-CRIT-07 (silent transit-loss in `_build_raw_*`) plus F-CRIT-10 (canonical-seed bootstrap for the 7 GLiNER classes that have zero canonicals); each unlocks ~80% and 60-90% of currently-dropped extractions respectively.

**Total Scope**: 6 sub-plans, 24 waves, ≈70 tasks.
**Estimated effort**: ~12-15 implementer-days plus QA iterations.

**Branch**: continue on `feat/content-ingestion-wave-a1` (no merge yet).

**Compounding effect (expected)**:
- `intelligence_db.relations` 18 (seeded) → ~hundreds/day in production
- Resolution rate per-class lifts: org 10%→60%+, currency 0%→80%+, regulatory_body 0%→70%+
- Claims/events drop ratio (producer→consumer): currently ~80% lost → near 0% lost
- Aliases-per-canonical: 0.46 → 4-6
- AGE shadow graph: 0 nodes → live with the 18 seeded + new

---

## 0. Pre-Flight Gate Status

| Check | Status | Note |
|---|---|---|
| Source investigation has resolved findings | PASS | Audit + 5 fix-design subagents = concrete fix path per finding |
| No active cross-plan conflicts | PASS | PLAN-0053 frontend-only; PLAN-0055 auto-backfill on `sources` table only; PLAN-0056 Polymarket-only — none overlap with our changes |
| Architecture compliance (RULES.md) | PASS | Honors R24 (only `intelligence-migrations` owns intelligence_db DDL), R25 (use cases not infra in API), R27 (read-replica for reads) |
| External API field reality check | PASS | Fix-D limited to fields confirmed in `docs/references/eodhd-endpoints-reference.md` (`Code, Name, ISIN, OpenFigi, LEI, CUSIP, PrimaryTicker`). SEDOL is NOT in General on this account. |
| Cross-service architectural concerns | **CHECKPOINT-A** | Sub-Plan D Wave D-2 introduces a new event `market.instrument.discovered.v1` to defer `market.instrument.created` until fundamentals land. Needs sign-off before implementation (portfolio S2 InstrumentRef sync depends on it). |

---

## 1. Plan Dependency Graph

```
Sub-Plan A (Schema + Audit-Table Writes) ─┐
   ├── A-1 routing_decisions migration    │
   ├── A-2 entity_aliases UNIQUE index    │
   ├── A-3 canonical seeds bootstrap      │
   ├── A-4 mention_resolutions write      │
   └── A-5 usage_logger threading         │
                                          ├──→ Sub-Plan B (Resolution Unblocking)
                                          │      ├── B-1 _build_raw_* provisional flow (F-CRIT-07)
                                          │      ├── B-2 fix _PROVISIONAL_INSERT_SQL (F-MAJOR-10)
                                          │      └── B-3 UnresolvedResolutionWorker prompt (F-CRIT-05)
                                          │
                                          ├──→ Sub-Plan C (Alias Enrichment)
                                          │      ├── C-1 Avro v3 InstrumentCreated
                                          │      ├── C-2 fundamentals_consumer EODHD extras
                                          │      ├── C-3 instrument_consumer alias inserts (Fix-A + Fix-D.3)
                                          │      ├── C-4 ALIAS_GENERATION prompt v2.0 (F-MAJOR-09)
                                          │      └── C-5 Self-alias on canonical-create paths (Fix-B)
                                          │
                                          ├──→ Sub-Plan D (Hygiene & Dead-Code) — D-2 GATED on Checkpoint A
                                          │      ├── D-1 Remove claim.extracted producer (F-CRIT-08)
                                          │      ├── D-2 Defer InstrumentCreated from ohlcv/quotes (F-CRIT-12.E.2) ⚠
                                          │      └── D-3 Synthesised-name EXACT-alias guard (F-CRIT-12.E.3)
                                          │
                                          ├──→ Sub-Plan E (Config + Worker Wiring)
                                          │      ├── E-1 MarketDataClient internal-JWT (F-MAJOR-02)
                                          │      ├── E-2 Gemini description provider env (F-MAJOR-04)
                                          │      ├── E-3 cypher_enabled=true env (F-MAJOR-08)
                                          │      ├── E-4 EmbeddingRetryWorker main + lifespan (F-MAJOR-05)
                                          │      └── E-5 entity_embedding_state startup repair (F-MAJOR-06)
                                          │
                                          └──→ Sub-Plan F (Frontend Surface — DOWNSTREAM ONLY)
                                                 ├── F-1 Entity-detail page entity_type variants
                                                 └── F-2 Alias-pill rendering for new alias_types
```

### Execution Order
1. **Sub-Plan A first** — it adds observability columns + audit writes, so we can verify B/C/D actually work.
2. **Sub-Plan B in parallel with C** — touch different files (NLP vs market-data + KG), no overlap.
3. **Sub-Plan D after C** — D-3 depends on instrument_consumer changes from C-3.
4. **Sub-Plan E config waves can ship anytime** — E-2/E-3 are pure env-var. E-1/E-4/E-5 are isolated code.
5. **Sub-Plan F last** — surfaces new entity_type and alias_type values that A-3 and C-1..C-5 produce.

---

## 2. Codebase State Verification (read from source)

| Artifact | Type | Service | Actual current state | Target state | Delta |
|---|---|---|---|---|---|
| `routing_decisions.processing_path` | DB column | nlp-pipeline `nlp_db` | does not exist | TEXT NULL with CHECK | new column (A-1) |
| `routing_decisions.final_routing_tier` | DB column | nlp-pipeline `nlp_db` | declared in 0001 mig but production-DB drifted on some envs | TEXT NULL — defensive `ADD COLUMN IF NOT EXISTS` | idempotent re-add (A-1) |
| `entity_aliases` UNIQUE | DB index | intelligence_db | partial unique on `(normalized_alias_text)` filtered by `EXACT AND is_active`; non-EXACT types have NO uniqueness | new `uidx_entity_aliases_entity_norm_type ON (entity_id, normalized_alias_text, alias_type) WHERE is_active=true` | new index (A-2) |
| `canonical_entities` rows | data | intelligence_db | 83 (40 instruments, 27 industry_group, 11 sector, 4 technology_theme, 1 industry); ZERO for 7 of 11 NER classes | +~224 seed rows for currency / regulatory_body / government_body / index / commodity / macroeconomic_indicator / location / person / financial_institution | new data migration (A-3) |
| `entity_embedding_state` | data | intelligence_db | 206 rows (~43 missing for existing canonicals) | per A-3: +2 view rows per new canonical (definition + narrative) — `fundamentals_ohlcv` only for `financial_instrument` | new data migration (A-3) + repair task (E-5) |
| `mention_resolutions` writes | code | nlp-pipeline article_consumer.py:405-423 | `mr_repo` instantiated at line 403, audit list iterated for metrics, `add_batch` NEVER called | `await mr_repo.add_batch(resolution_audit)` after metrics loop | one-line fix (A-4) |
| `_PROVISIONAL_INSERT_SQL` | code | nlp-pipeline entity_resolution.py:247-272 | references columns `mention_id`, `doc_id` that DO NOT EXIST in `provisional_entity_queue` schema (which has `source_doc_id`, no `mention_id`); savepoint silently swallows errors → 0 rows ever inserted | match real schema columns; `RETURNING queue_id` on insert; stash on `mention.provisional_queue_id` | rewrite SQL + UoW change (B-2) |
| `entity_id_by_ref` | code | nlp-pipeline article_consumer.py:793-796 | built only from RESOLVED mentions | include unresolved-with-queue-id; track `provisional_refs: set[str]` | rewrite (B-1) |
| `_build_raw_relations/_events/_claims` | code | nlp-pipeline article_consumer.py:836-929 | silently `continue` on lookup miss | populate `entity_provisional` and `provisional_queue_id` fields (already accepted by KG consumer) | rewrite (B-1) |
| `usage_logger=None` hardcoded | code | nlp-pipeline `unresolved_resolution_worker_main.py:59` + `article_relevance_scoring_worker.py` + KG `instrument_consumer_main.py:62` + `entity_consumer_main.py` + `fundamentals_consumer_main.py` + `scheduler.py:166-249` | None hardcoded everywhere; `NlpUsageLogRepository` and KG `LlmUsageLogRepository` exist but never instantiated at construction | new `SessionScopedNlpUsageLogger`/`SessionScopedKgUsageLogger` helpers; thread through 6+ workers | new helper + 6 wiring changes (A-5) |
| `UnresolvedResolutionWorker` prompt | code | nlp-pipeline unresolved_resolution_worker.py:54-59 | "would have its own Wikipedia article" criterion; surface text only | financial-domain criterion + 4 worked examples + `context_sentence` (±200 chars from chunk) | rewrite + repo JOIN (B-3) |
| `InstrumentCreated` event | Avro + dataclass | market-data | schema_version=2 with `name, isin, description` | schema_version=3 + `cusip, figi (= EODHD OpenFigi), lei, primary_ticker` | Avro bump + dataclass extension (C-1) |
| `fundamentals_consumer.py` extraction | code | market-data line 280-301 | extracts only `Name, ISIN, Description` | also extract `OpenFigi → figi`, `LEI, CUSIP, PrimaryTicker` | rewrite extraction block (C-2) |
| `instrument_consumer.py` aliases | code | knowledge-graph line 113-262 | inserts EXACT (canonical_name), TICKER, exchange:TICKER, ISIN; calls `_add_llm_aliases` but prompt has no description placeholder | also insert NAME (when EODHD `name` differs from canonical), CUSIP, FIGI, LEI, PRIMARY_TICKER | rewrite mechanical-alias block + caller (C-3) |
| `ALIAS_GENERATION` prompt | code | libs/prompts/.../alias.py | v1.0; only `{name}, {ticker}` placeholders; no description, no aliases-so-far, no few-shots | v2.0 with `{name, ticker, description, aliases_so_far}` + 4 worked examples | full template rewrite (C-4) |
| `CanonicalEntityRepository.create()` | code | knowledge-graph repo | inserts canonical row only | also inserts EXACT self-alias in same SQL transaction | rewrite + tests (C-5) |
| `seed_demo_data.py:793` + `seeds/003_seed_sector_entities.sql` | code/SQL | scripts + intelligence-migrations | inserts canonical without EXACT alias | also insert EXACT self-alias `ON CONFLICT DO NOTHING` | both files (C-5) |
| `claim.extracted` topic producer | code | nlp-pipeline | `ClaimsRepository.write_via_outbox()` produces 141+ orphan messages; no consumer group anywhere | DELETE the entire repo + caller in deep_extraction.py + ClaimsRepository import in article_consumer.py + config.py setting | full removal (D-1) |
| `ohlcv_consumer.py:213` / `quotes_consumer.py:210` | code | market-data | emits `InstrumentCreated` with `name=None` → 6 `Instrument-019dbbdb` placeholders in S7 | (D-2) defer emission OR (alt) introduce `market.instrument.discovered.v1` event for portfolio sync; gate `created` on fundamentals | **CHECKPOINT-A required** — cross-service decision |
| Synthesised-name EXACT-alias guard | code | knowledge-graph instrument_consumer.py:135-192 | inserts `Instrument-019dbbdb` as EXACT alias when name was synthesised | skip EXACT alias when `synthesised_name == True` | guard (D-3) |
| `MarketDataClient` JWT | code | nlp-pipeline price_impact_labelling_worker.py + http/market_data_client.py | unsigned HTTP GET → 401 on every call → 0 `article_impact_windows` rows | mint HS256 X-Internal-JWT mirroring `portfolio.infrastructure.market_data.current_price_client._system_jwt_headers` | new helper + caller wire-up + env var (E-1) |
| `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER` | env | knowledge-graph config.py:107 | default `"none"` → 100% template descriptions for non-instruments | `"gemini"` (dev + prod) + `KNOWLEDGE_GRAPH_GEMINI_API_KEY` from secret + `KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD=50` | env-var only (E-2) |
| `KNOWLEDGE_GRAPH_CYPHER_ENABLED` | env | knowledge-graph configs/docker.env:78 + dev.local.env.example:30 | `false` → AGE shadow worker returns immediately every cycle | `true` (dev + prod) | env-var only (E-3) |
| `EmbeddingRetryWorker` entrypoint | code | nlp-pipeline workers/ | `embedding_retry_worker.py` exists in `infrastructure/workers/`; NO `embedding_retry_worker_main.py`; not started in `app.py` lifespan | new ~25-line entry-point + lifespan integration | new file + 1 lifespan change (E-4) |
| `entity_embedding_state` startup repair | code | knowledge-graph app.py | none | new `repair_missing_embedding_state()` task in lifespan | new ~25-line file + 1 lifespan change (E-5) |
| Frontend entity-detail | code | apps/worldview-web | renders `entity_type ∈ {financial_instrument, sector, industry, ...}` | also handle `currency, regulatory_body, government_body, location, person, financial_institution, commodity, macroeconomic_indicator, index` | type-mapping update (F-1) |

---

## 3. Operational Constraints

1. **Branch**: stay on `feat/content-ingestion-wave-a1`. Each wave commits separately; squash-merge after final QA.
2. **gitops sync**: every new env var must be added to `worldview-gitops` repo (Helm `values.yaml` + dev compose) — the user's setup-secrets.sh script is the source of truth.
3. **R24 enforcement**: only `intelligence-migrations` Alembic environment touches `intelligence_db` DDL. S6/S7 connect with `ALEMBIC_ENABLED=false`.
4. **Forward-compatible Avro**: every schema bump preserves backward compatibility (new fields nullable with `default: null`).
5. **Idempotent seeds**: every data migration uses `ON CONFLICT DO NOTHING` against stable hardcoded UUIDs.
6. **Pre-commit ruff sync** (BP-023, BP-127): use pinned ruff from `~/.cache/pre-commit/` not uvx/venv to avoid phantom reformat loop.

---

## 4. Sub-Plan Summaries

### Sub-Plan A — Schema + Audit-Table Writes (foundation; ships first)
**5 waves, ~14 tasks, ~2.5 days.**
Lays the observability + persistence groundwork so the rest of the plan is verifiable. After Sub-Plan A: `routing_decisions` carries `processing_path`, `entity_aliases` cannot accumulate non-EXACT duplicates, intelligence_db has 224 new canonicals + ~448 embedding-state rows, every LLM call writes to `llm_usage_log`, every resolution attempt writes to `mention_resolutions`.

### Sub-Plan B — Resolution Unblocking (highest leverage)
**3 waves, ~9 tasks, ~2 days.**
F-CRIT-07 + F-MAJOR-10 fix + F-CRIT-05 prompt rewrite. Unblocks ~80% of currently-dropped claims/events/relations. After Sub-Plan B: every UNRESOLVED mention gets a queue row + `provisional_queue_id`; KG receives `entity_provisional=True` flagged raw_relations and persists them; UnresolvedResolutionWorker stops over-suppressing real entities.

### Sub-Plan C — Alias Enrichment
**5 waves, ~16 tasks, ~3.5 days.**
Avro schema bump v3 + EODHD `OpenFigi/CUSIP/LEI/PrimaryTicker` extraction + alias inserts + ALIAS_GENERATION prompt v2 with description + few-shots + repo-level self-alias invariant. After Sub-Plan C: aliases-per-canonical ratio 0.46 → 4-6, LLM aliases produce non-empty results, `financial_instrument` resolution rate 17% → 60-80%.

### Sub-Plan D — Hygiene & Dead-Code Removal
**3 waves, ~7 tasks, ~1 day.**
Removes the orphan `claim.extracted` producer (5 file deletions / edits), defers `InstrumentCreated` from non-fundamentals consumers (D-2 GATED on Checkpoint A), guards synthesised-name EXACT-alias insert. After Sub-Plan D: no dead Kafka traffic, no `Instrument-019dbbdb` canonicals visible to users.

### Sub-Plan E — Config + Worker Wiring
**5 waves, ~13 tasks, ~1.5 days.**
Internal-JWT for MarketDataClient (unblocks `article_impact_windows`), Gemini description provider env, AGE cypher_enabled flip, EmbeddingRetryWorker entrypoint, entity_embedding_state startup repair. After Sub-Plan E: price-impact pipeline operational, non-template descriptions for non-instruments, AGE graph populated, embedding backlog drains, all canonicals have correct view rows.

### Sub-Plan F — Frontend Downstream Surfaces (conditional)
**2 waves, ~5 tasks, ~0.5 day.**
Entity-detail page handles 9 new `entity_type` variants; alias-pill UI renders 4 new alias_types. Only ships if A-3 + C-2/C-3 actually surface new types in API responses (verify post-A-3).

---

## 5. Sub-Plan A — Schema + Audit-Table Writes

### Pre-Read (agent must read before any wave)
- `RULES.md` (R24, R25, R27)
- `docs/services/nlp-pipeline.md` + `docs/services/knowledge-graph.md`
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` (full schema reference)
- `services/intelligence-migrations/seeds/003_seed_sector_entities.sql` (style reference for A-3)
- `services/nlp-pipeline/alembic/versions/0001_create_nlp_schema.py` (current routing_decisions schema)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` (full file)
- `docs/audits/2026-04-29-investigation-news-pipeline-quality-deep-dive.md` §2.1 + §6.2
- `docs/BUG_PATTERNS.md` §BP-007 (FK without rel), §BP-019 (DDL), §BP-126 (forward-compat schema)

---

### Wave A-1: Add `processing_path` column to `routing_decisions` (defensive `final_routing_tier` re-add) ✅

**Status**: **DONE** — 2026-04-30 · 4 new round-trip tests pass · 14 DDL-alignment tests pass · ruff + mypy clean. Migration is `0015_add_processing_path_to_routing_decisions` (revision 0015, not 0012 as initially scoped — the latest baseline was 0014). `ProcessingPath` enum moved from `application/blocks/suppression.py` to `domain/enums.py` (re-exported from suppression for backward compat); `RoutingDecision` dataclass and `RoutingDecisionRepository.add()` carry the new field. DDL-alignment regex updated to handle `ADD COLUMN IF NOT EXISTS` (general improvement).

**Goal**: persist Block 8 novelty downgrade + processing-path enum so downstream queries can filter on them.
**Depends on**: none
**Estimated effort**: 30-60 min
**Architecture layer**: schema (nlp_db) + ORM model + repo

#### Tasks

##### T-A-1-01: Alembic migration `0012_add_processing_path_to_routing_decisions`
**Type**: schema
**depends_on**: none
**blocks**: T-A-1-02, T-A-4-02
**Target files**:
- `services/nlp-pipeline/alembic/versions/0012_add_processing_path_to_routing_decisions.py` (NEW)

**What to build**: defensive Alembic migration that adds `final_routing_tier TEXT NULL` (idempotent) + `processing_path TEXT NULL` with CHECK constraints + partial index on `(final_routing_tier, decided_at) WHERE final_routing_tier IS NOT NULL`. Revision `0012`, down_revision `0011`.

**Concrete SQL** (full): see audit §6.2 → fix-design report A.3. Use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for both columns. CHECK constraint values: `processing_path IN ('FULL_PIPELINE','SECTION_EMBEDDINGS_ONLY','HALT')`, `final_routing_tier IN ('deep','medium','light','suppress')`.

**Tests to write**: migration round-trip test in `services/nlp-pipeline/tests/integration/test_migrations.py` — upgrade + downgrade, assert columns appear/disappear correctly, CHECK constraint rejects invalid values.

**Downstream test impact**: existing `routing_decisions` row tests don't break (columns nullable).

**Acceptance**: `alembic upgrade 0012` succeeds; `alembic downgrade 0011` succeeds; CHECK constraint exists; partial index exists.

##### T-A-1-02: Update `RoutingDecisionModel` ORM + domain entity
**Type**: impl
**depends_on**: T-A-1-01
**blocks**: T-A-4-02
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py:174-183`
- `services/nlp-pipeline/src/nlp_pipeline/domain/models.py` (RoutingDecision dataclass)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/routing_decision.py:22-31`

**What to build**:
- Add `processing_path: Mapped[str | None] = mapped_column(Text, nullable=True)` to `RoutingDecisionModel`.
- Add `processing_path: ProcessingPath | None = None` to `RoutingDecision` dataclass.
- Extend `RoutingDecisionRepository.add()` to write `processing_path=str(decision.processing_path) if decision.processing_path else None`.

**Tests**: extend `tests/unit/infrastructure/nlp_db/repositories/test_routing_decision_repo.py` with round-trip case for `processing_path=FULL_PIPELINE`.

**Acceptance**: SELECT after INSERT returns the value; mypy + ruff clean.

#### Validation Gate
- [ ] `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` succeeds
- [ ] ruff + mypy clean on changed files
- [ ] 1+ new unit tests pass
- [ ] Migration file follows BP-126 (forward-compatible — new columns nullable)

#### Break Impact
| Broken file | Why | Fix |
|---|---|---|
| `services/nlp-pipeline/tests/integration/test_consumer_pipeline.py` row assertions | adds nullable column | None — column is nullable, existing tests still pass |
| `news_query.py:89,109,156` | already uses `COALESCE(rd.final_routing_tier, rd.routing_tier)` | None |

#### Regression Guardrails
- BP-126 (forward-compat schema): both columns nullable, no default rewrite
- BP-019 (DDL ownership): nlp_db is owned by nlp-pipeline service, this migration is correct location

---

### Wave A-2: Add UNIQUE index on `entity_aliases` (intelligence_db) ✅

**Status**: **DONE** — 2026-04-30 · 4 new round-trip tests (uidx existence + duplicate-blocks + distinct-alias-types-allowed + distinct-entities-allowed) · ruff + mypy clean. Migration is `0008_alias_unique_per_entity` (intelligence-migrations 0008, not 0009 — latest baseline was 0007). Pre-clean DELETE keeps oldest `alias_id` per (entity_id, normalized, alias_type); UNIQUE INDEX `uidx_entity_aliases_entity_norm_type` complements the existing 0001 partial index.

**Goal**: prevent non-EXACT alias duplicates (TICKER/CUSIP/FIGI/...) from accumulating.
**Depends on**: none
**Estimated effort**: 30-60 min
**Architecture layer**: schema (intelligence_db)

#### Tasks

##### T-A-2-01: Alembic migration `0009_alias_unique_per_entity` (in intelligence-migrations)
**Type**: schema
**depends_on**: none
**blocks**: T-C-3-01, T-C-3-02 (alias inserts must observe new unique constraint)
**Target files**:
- `services/intelligence-migrations/alembic/versions/0009_alias_unique_per_entity.py` (NEW)

**What to build**: pre-clean DELETE that keeps oldest `alias_id` per `(entity_id, normalized_alias_text, alias_type)`, then `CREATE UNIQUE INDEX uidx_entity_aliases_entity_norm_type ON entity_aliases (entity_id, normalized_alias_text, alias_type) WHERE is_active=true`.

**Concrete SQL**: see fix-design report Fix-E.1.

**Tests**: in `services/intelligence-migrations/tests/test_migration.py` — upgrade migration, insert two identical `(entity_id='...', normalized='aapl', alias_type='TICKER')` rows, assert second raises `IntegrityError`.

**Downstream test impact**: any test that intentionally inserts duplicate aliases needs `is_active=false` on the dupe.

**Acceptance**: pre-clean removes 26 demo dupes; new index visible in `\di+ uidx_entity_aliases_entity_norm_type`.

#### Validation Gate
- [ ] migration round-trip succeeds
- [ ] pre-clean count matches expected (26 in dev DB)
- [ ] integration test for duplicate-rejection passes

#### Break Impact
| File | Why | Fix |
|---|---|---|
| `scripts/seed_demo_data.py` (when `--reset` re-runs) | new constraint blocks duplicates | None — `ON CONFLICT DO NOTHING` already present in the seed script |

#### Regression Guardrails
- BP-019 (intelligence_db DDL ownership — only intelligence-migrations): correct location

---

### Wave A-3: Canonical-Entity Bootstrap Seed (224 rows + 448 embedding-state rows) ✅

**Status**: **DONE** — 2026-04-30 · 6 new round-trip tests covering counts, descriptions, EXACT alias presence, embedding_state row count, currency iso_code metadata, and idempotency. Migration is `0009_seed_canonicals_bootstrap` (intelligence-migrations 0009). Seeded ~224 canonicals: 33 currencies, 25 regulators, 25 government bodies, 30 indices, 25 commodities, 30 macros, 30 locations, 20 persons, 6 non-listed financial institutions. Each carries hand-written 1-2 sentence factual description in `metadata.description` (UI-ready per the user's quality bar) + 2-3 EXACT/TICKER aliases + 2 embedding_state view rows (definition + narrative; fundamentals_ohlcv N/A — none are financial_instrument). Stable UUIDv7-shaped IDs `0195daad-c001..c009-...`. Idempotent via `metadata->>'seed_source' = 'F-CRIT-10'` + ON CONFLICT DO NOTHING.


**Goal**: seed canonical_entities + entity_aliases + entity_embedding_state for the 7 NER classes that currently have zero canonicals (currency, regulatory_body, government_body, index, commodity, macroeconomic_indicator, location), plus persons (~20) and financial_institutions (~6 non-listed).
**Depends on**: T-A-2-01 (so the new UNIQUE index exists when we INSERT alias rows)
**Estimated effort**: 1.5-2 days (data curation + migration + tests)
**Architecture layer**: data migration (intelligence_db)

#### Tasks

##### T-A-3-01: Curate seed data tables
**Type**: docs (precursor data)
**depends_on**: none
**blocks**: T-A-3-02
**Target files**:
- `services/intelligence-migrations/alembic/versions/0010_seed_canonicals_data.csv` (or inline Python lists in the migration file — choose one)

**What to build**: per-class lists from fix-design report B.1-B.9. Currency (33), regulatory_body (25), government_body (25), index (30), commodity (25), macroeconomic_indicator (30), location (30), person (20), financial_institution (~6 non-listed only — Vanguard, Fidelity, Bridgewater, BlackRock-as-asset-mgr, Brookfield, Apollo). Each row: stable hardcoded UUIDv7 (`0195daad-c001..c009-...`), canonical_name, entity_type, description text (1-2 sentences from templates), aliases[] (2-3 per row with alias_type EXACT/TICKER/SYMBOL).

**Tests**: implicit — data quality verified by T-A-3-03 integration test.

##### T-A-3-02: Alembic data migration `0010_seed_canonicals_bootstrap`
**Type**: schema (data migration)
**depends_on**: T-A-3-01, T-A-2-01
**blocks**: T-A-3-03
**Target files**:
- `services/intelligence-migrations/alembic/versions/0010_seed_canonicals_bootstrap.py` (NEW)

**What to build**: Alembic file with 9 SQL blocks (one per entity_type) — see fix-design report D for full skeleton. Each block: INSERT INTO canonical_entities ... ON CONFLICT (entity_id) DO NOTHING; INSERT INTO entity_aliases ... ON CONFLICT DO NOTHING; final block: INSERT INTO entity_embedding_state SELECT ce.entity_id, vt.view_type, now(), now(), 0 FROM canonical_entities ce CROSS JOIN (VALUES ('definition'), ('narrative')) vt WHERE ce.metadata->>'seed_source'='F-CRIT-10' AND ce.entity_type<>'financial_instrument' ON CONFLICT DO NOTHING;

For `financial_institution` overlap: use `DO $$ ... IF NOT EXISTS (SELECT 1 FROM entity_aliases WHERE normalized_alias_text='jpmorgan chase' AND alias_type='EXACT') THEN ... END $$` guards. Recommended: only seed 6 non-listed institutions to avoid overlap with publicly-traded `financial_instrument` canonicals.

`downgrade()`: `DELETE FROM canonical_entities WHERE metadata->>'seed_source' = 'F-CRIT-10'` (CASCADE removes aliases + embedding_state).

##### T-A-3-03: Migration tests
**Type**: test
**depends_on**: T-A-3-02
**blocks**: none
**Target files**:
- `services/intelligence-migrations/tests/test_migration.py` (extend)

**What to build**: per fix-design report E:
- `test_seed_canonicals_F_CRIT_10_present` — assert per-class min counts (currency≥30, regulator≥20, government≥20, index≥25, commodity≥20, macro≥25, location≥25, person≥15, financial_institution≥5)
- `test_seed_aliases_unique` — every seeded canonical has ≥1 EXACT alias
- `test_seed_embedding_state_two_rows` — every seeded non-instrument canonical has exactly 2 view rows (definition + narrative)
- `test_seed_round_trip` — upgrade → downgrade → upgrade with no duplicates

**Acceptance**: 4 new tests pass.

##### T-A-3-04: Resolver integration test (cross-service)
**Type**: test (integration)
**depends_on**: T-A-3-02
**blocks**: none
**Target files**:
- `services/nlp-pipeline/tests/integration/test_entity_resolution_seeded.py` (NEW)

**What to build**: drive a synthetic sentence "The Federal Reserve raised rates" through Block 9 → assert Stage-1 alias-exact match resolves to the seeded `regulatory_body` canonical with confidence 1.0.

**Acceptance**: end-to-end resolution succeeds for ≥5 surfaces from each new entity_type.

#### Validation Gate
- [ ] Alembic migration round-trip succeeds
- [ ] All 5 new tests pass (4 migration + 1 integration)
- [ ] Post-migration: `SELECT COUNT(*) FROM canonical_entities WHERE metadata->>'seed_source'='F-CRIT-10'` ≈ 224
- [ ] Post-migration: `SELECT COUNT(*) FROM entity_aliases WHERE source='seed:F-CRIT-10'` ≈ 527
- [ ] Post-migration: 2 embedding_state rows per non-instrument seed

#### Break Impact
| File | Why | Fix |
|---|---|---|
| `definition_refresh_worker` next cycle | 224 new entities with `next_refresh_at=now()` due | none — worker batches at 50/cycle, drains over ~9 cycles |
| `narrative_refresh_worker` next cycle | same | same |
| Frontend entity-search | now returns currency/regulator/etc. types | Sub-Plan F-1 handles UI |

#### Regression Guardrails
- BP-019 (intelligence_db DDL only via intelligence-migrations): correct
- BP-126 (forward-compat): pure data migration, no schema change
- Idempotency: ON CONFLICT DO NOTHING + stable UUIDs

---

### Wave A-4: Persist `mention_resolutions` audit + `processing_path` ✅

**Status**: **DONE** — 2026-04-30 · 2 surgical edits to `article_consumer.py`. Closes F-CRIT-02 (one-line `await mr_repo.add_batch(resolution_audit)` after the metrics loop, gated on non-empty list). Closes F-CRIT-06 (set `routing_decision.processing_path = final_path` immediately before `routing_repo.add()` so the new column from Wave A-1 gets populated). 565 unit tests pass; pre-existing integration test failures in test_consumer_pipeline.py predate this wave (verified via `git stash` round-trip).

**Goal**: close F-CRIT-02 (one-line audit-write fix) + complete A-1 by writing `processing_path` from Block 8 result.
**Depends on**: T-A-1-01, T-A-1-02
**Estimated effort**: 1-1.5 hours
**Architecture layer**: application + infrastructure (nlp-pipeline article_consumer)

#### Tasks

##### T-A-4-01: Write resolution audit
**Type**: impl + test
**depends_on**: none
**blocks**: T-B-1-* (audit observable)
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` (~line 423)
- `services/nlp-pipeline/tests/unit/infrastructure/messaging/consumers/test_consumer_persists_resolution_audit.py` (NEW)
- `services/nlp-pipeline/tests/integration/test_consumer_pipeline.py:226` (extend)

**What to build**: insert `if resolution_audit: await mr_repo.add_batch(resolution_audit)` after the metrics loop and before `nlp_session.commit()`. New unit test asserts `mr_repo.add_batch` is awaited once with the audit list and BEFORE the commit.

**Acceptance**: `mention_resolutions` table populates after a synthetic article is processed; audit-list size matches resolution-attempt count per mention.

##### T-A-4-02: Persist `processing_path` after suppression gate
**Type**: impl + test
**depends_on**: T-A-1-02
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:390` (after `final_path = apply_suppression_gate(routing_decision)`)
- `services/nlp-pipeline/tests/unit/.../test_consumer_routing_persistence.py` (extend or NEW)

**What to build**: `routing_decision.processing_path = final_path` line — the existing INSERT at line 462 then carries it. Unit test: novelty downgrade case → `routing_tier='deep', final_routing_tier='light', processing_path='FULL_PIPELINE'` round-trip.

**Acceptance**: post-pipeline DB row has all three fields populated correctly.

#### Validation Gate
- [ ] `mention_resolutions` non-empty after E2E run
- [ ] `processing_path` populated in 100% of new `routing_decisions` rows
- [ ] 2+ new unit tests pass

#### Break Impact
| File | Why | Fix |
|---|---|---|
| Existing tests asserting empty audit table | none caught the gap before; safe to update | re-baseline |

#### Regression Guardrails
- BP-feedback_audit_returned_value_persistence (memory): "audit return values must be persisted" — this fix IS the canonical example.

---

### Wave A-5 ✅: Thread `usage_logger` through every LLM call site

**Status**: **DONE** — 2026-04-30 · closes F-CRIT-03 — `llm_usage_log` now populated for every LLM call from nlp-pipeline + knowledge-graph (Ollama, DeepInfra, Gemini paths). Two new `SessionScopedNlpUsageLogger` / `SessionScopedKgUsageLogger` helpers + threaded into `unresolved_resolution_worker_main`, `article_relevance_scoring_worker` (constructor + per-call hook), `article_consumer_main` (deep-extraction), `instrument_consumer_main`, `fundamentals_consumer_main`, `scheduler_main` (FallbackChainClient + DefinitionRefreshWorker + ProvisionalEnrichmentWorker). 4 new unit-test files (10 net-new test cases) — all pass alongside 583 nlp-pipeline + 650 knowledge-graph existing unit tests. ruff + ruff format + mypy strict (1042 src files) all clean.

**Goal**: close F-CRIT-03 — `llm_usage_log` populates with model_id, tokens, latency for every LLM call from nlp-pipeline + knowledge-graph workers.
**Depends on**: none (independent of A-1..A-4)
**Estimated effort**: 1 day
**Architecture layer**: infrastructure + workers

#### Tasks

##### T-A-5-01: `SessionScopedNlpUsageLogger` helper (nlp-pipeline)
**Type**: impl + test
**depends_on**: none
**blocks**: T-A-5-02, T-A-5-03, T-A-5-04
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/usage_log_factory.py` (NEW)
- `services/nlp-pipeline/tests/unit/infrastructure/nlp_db/test_usage_log_factory.py` (NEW)

**What to build**: per fix-design report A.2 — class with `__init__(self, sf)` and `async def log(self, **kwargs)` that opens a short-lived session per call, swallows exceptions with structlog warning. Implements `LlmUsageLogProtocol`.

**Acceptance**: unit test verifies `log()` writes a row to `nlp_db.llm_usage_log` and exception path logs warning without raising.

##### T-A-5-02: Wire `usage_logger` into nlp-pipeline workers
**Type**: impl + test
**depends_on**: T-A-5-01
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/workers/unresolved_resolution_worker_main.py:59`
- `services/nlp-pipeline/src/nlp_pipeline/workers/article_relevance_scoring_worker.py:61` (main wiring)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py:74-96` (constructor + LLM-call hook)
- 3 new test files for `*_main.py` construction asserts

**What to build**:
- Replace `usage_logger=None` with `usage_logger=SessionScopedNlpUsageLogger(nlp_sf)` in unresolved_resolution_worker_main.py:59.
- Add `usage_logger: LlmUsageLogProtocol | None = None` kwarg to `ArticleRelevanceScoringWorker.__init__`; store on `self._usage_logger`; insert `await self._usage_logger.log(model_id=..., capability="classification", provider=..., tokens_in=..., tokens_out=..., latency_ms=..., success=...)` after every Ollama / DeepInfra HTTP call.
- Wire `usage_logger=SessionScopedNlpUsageLogger(nlp_sf)` in the `_main.py` for relevance-scoring worker.
- Same for deep-extraction call site in article_consumer (verify `ExtractionClient` accepts `usage_logger`; if not, add and wire).

**Acceptance**: 3 new unit tests pass; `nlp_db.llm_usage_log` has rows after a real worker cycle.

##### T-A-5-03: `SessionScopedKgUsageLogger` helper (knowledge-graph)
**Type**: impl + test
**depends_on**: none
**blocks**: T-A-5-04
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/usage_log_factory.py` (NEW, mirrors A-5-01)
- `services/knowledge-graph/tests/unit/infrastructure/test_usage_log_factory.py` (NEW)

##### T-A-5-04: Wire `usage_logger` into KG workers + consumers
**Type**: impl + test
**depends_on**: T-A-5-03
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer_main.py:62` (FallbackChainClient construction)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/entity_consumer_main.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/fundamentals_consumer_main.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py:166-249` (build_workers)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py` (add `usage_logger` kwarg + log calls at each LLM call site)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py:74` (already supports `usage_logger`; just wire from scheduler)

**What to build**: pass `usage_logger=SessionScopedKgUsageLogger(write_factory)` into every `FallbackChainClient(...)` and worker constructor. ProvisionalEnrichmentWorker needs new `usage_logger` kwarg + `await self._usage_logger.log(...)` at each LLM call.

**Acceptance**: 4-5 new tests; `intelligence_db.llm_usage_log` has rows after full pipeline run.

#### Validation Gate
- [ ] `nlp_db.llm_usage_log` rows match LLM-call counts from container logs
- [ ] `intelligence_db.llm_usage_log` rows match KG-side LLM calls
- [ ] All worker main.py construction tests pass

#### Break Impact
| File | Why | Fix |
|---|---|---|
| Tests using `usage_logger=AsyncMock()` | continue to work — None default preserved | none |
| `libs/ml-clients/test_adapters.py` `usage_logger=None` cases | continue to work | none |

#### Regression Guardrails
- BP-feedback_audit_returned_value_persistence: same pattern as A-4
- HR-019 (no blocking I/O in async): the helper opens a session inside `await` which is correct

---

## 6. Sub-Plan B — Resolution Unblocking (highest leverage)

### Pre-Read
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py` (full file — 4-stage cascade + `_PROVISIONAL_INSERT_SQL` at lines 247-272)
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py:158` (mention list build)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:380-460,790-929`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py:382-383` (provisional flag parsing)
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py:572-588` (`provisional_entity_queue` schema reference)
- `docs/audits/.../2026-04-29-investigation...md` §6.2 (F-CRIT-07 + F-MAJOR-10 + F-CRIT-05)

### Wave B-1: `_build_raw_*` carries provisional refs (F-CRIT-07) ✅

**Status**: **DONE** — 2026-04-30 · 9 new unit tests cover all 3 helpers (resolved-only / one-side-provisional / both-provisional / unresolved-still-dropped). 44 unit tests in test_consumer.py pass; mypy clean. Implementation: `entity_id_by_ref` now built from BOTH resolved mentions (real canonical UUID) AND provisional mentions (synthetic queue UUID stashed by Wave B-2). `provisional_refs: set[str]` tracks which keys are provisional. The 3 `_build_raw_*` helpers gain `provisional_refs` parameter and emit `entity_provisional=True` + `provisional_queue_id=<uuid>` on the appropriate endpoint(s). When both endpoints are provisional, subject queue id wins by convention. `deep_extraction.py:158` mention_names list now deduped via `dict.fromkeys()` (preserves order).

**Goal**: stop silent drop when LLM picks an unresolved mention surface; emit `entity_provisional=True` + `provisional_queue_id` so KG can persist provisional evidence and promote later.
**Depends on**: T-A-4-01 (audit observable), T-B-2-01 (real queue_id available)
**Estimated effort**: 4-6 hours

#### Tasks
##### T-B-1-01: extend `EntityMention` domain dataclass with optional `provisional_queue_id`
**Type**: impl
**depends_on**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/domain/models.py`
**What**: add `provisional_queue_id: UUID | None = None` (kw-only). Sweep any positional `EntityMention(...)` constructors via grep.

##### T-B-1-02: rebuild `entity_id_by_ref` to include provisional refs
**Type**: impl + test
**depends_on**: T-B-1-01, T-B-2-01
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:793-796` + new unit tests at `tests/unit/.../test_article_consumer_entity_id_by_ref.py`
**What**: fix-design report §2b. Build dict from RESOLVED ids OR `provisional_queue_id`; track `provisional_refs: set[str]`.

##### T-B-1-03: emit `entity_provisional` flag in raw_relations/events/claims
**Type**: impl + test
**depends_on**: T-B-1-02
**Target files**: `article_consumer.py:836-929` + `tests/unit/.../test_article_consumer_raw_builders.py` (NEW, ~6 cases per builder)
**What**: per fix-design §2c — set `entity_provisional` and `provisional_queue_id` based on whether the ref is in `provisional_refs`. Cases: both-resolved, one-provisional-subject, one-provisional-object, both-provisional, ref-not-in-dict (still skip).

##### T-B-1-04: dedup mention_names list passed to extraction prompt
**Type**: impl + test
**depends_on**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py:158` + extend `tests/unit/application/blocks/test_deep_extraction.py`
**What**: per fix-design §2e — preserve order, dedup by `mention_text`. Conservative; do NOT inject canonical aliases (defer to follow-up).

##### T-B-1-05: KG-side cross-service contract test
**Type**: test (integration)
**depends_on**: T-B-1-03, T-B-2-01
**Target files**: `services/knowledge-graph/tests/integration/test_enriched_consumer_provisional.py` (NEW)
**What**: send enriched event with provisional relation → assert `relation_evidence_raw` row has `entity_provisional=true` + matching `provisional_queue_id`; then send `entity.canonical.created.v1` with same queue_id → row's flag flips to false, subject/object_entity_id rewritten.

#### Validation Gate
- [ ] `_build_raw_*` unit tests cover all 5 entity-resolution outcomes per builder (15+ tests)
- [ ] integration test: producer log claims=N == consumer log claims=N for the same doc_id
- [ ] no existing tests broken (re-baseline tests asserting empty `mention_resolutions` / `provisional_entity_queue`)

#### Break Impact
| File | Why | Fix |
|---|---|---|
| `services/knowledge-graph/tests/.../test_enriched_consumer.py` mocks without `entity_provisional` key | KG consumer reads via `.get(...)` defaulting to False | none — backward compatible |
| Tests asserting `len(entity_id_by_ref) == resolved_count` | now includes provisional | re-baseline |

#### Regression Guardrails
- BP-prompt-input-mismatch (memory): the prompt advertises mention surfaces; the lookup table must contain them all. This wave fixes the mismatch.
- BP-orphan-outbox-topic (recommend new): handled in D-1.

---

### Wave B-2: Fix `_PROVISIONAL_INSERT_SQL` to match real schema (F-MAJOR-10) ✅

**Status**: **DONE** — 2026-04-30 · combined commit with B-1. The prior SQL referenced `mention_id` and `doc_id` columns that DO NOT EXIST in `provisional_entity_queue` (real columns: `mention_text`, `normalized_surface`, `mention_class`, `source_doc_id`, `context_snippet`, status/timestamps). The SAVEPOINT+except wrapper at the call site silently swallowed the SQL error → queue stayed empty. Rewrote SQL to match real schema, added `RETURNING queue_id`, used `ON CONFLICT (normalized_surface, mention_class) DO UPDATE SET retry_count = retry_count` (no-op enabling RETURNING on conflict path), updated `_insert_provisional()` signature to return `UUID`, caller in `run_entity_resolution_block` stashes the returned id on `mention.provisional_queue_id` (new domain field). This wave is the precursor to B-1: B-1's `entity_id_by_ref` build relies on the queue_id being available on the mention.

**Goal**: `provisional_entity_queue` actually populates. Currently the savepoint silently catches a SQL error from referencing nonexistent columns `mention_id` and `doc_id`.
**Depends on**: none (can ship in parallel with B-1, but B-1 needs B-2 done first to have real queue_ids)
**Estimated effort**: 2-3 hours

#### Tasks
##### T-B-2-01: rewrite `_PROVISIONAL_INSERT_SQL` and `_insert_provisional`
**Type**: impl + test
**depends_on**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py:247-272` (SQL constant) and ~lines 446-456 (the savepoint wrapper)
- `services/nlp-pipeline/tests/unit/application/blocks/test_entity_resolution_provisional_insert.py` (NEW)

**What**: per fix-design §2a:
```python
_PROVISIONAL_INSERT_SQL = """
INSERT INTO provisional_entity_queue
    (queue_id, mention_text, normalized_surface, mention_class, source_doc_id, context_snippet)
VALUES
    (:queue_id, :surface, lower(trim(:surface)), :mention_class, :doc_id, :ctx)
ON CONFLICT (normalized_surface, mention_class)
DO UPDATE SET retry_count = provisional_entity_queue.retry_count
RETURNING queue_id
"""
```
Also: `_insert_provisional` returns the canonical `queue_id` (via `RETURNING`); caller stashes it on `mention.provisional_queue_id`.

**Tests**: round-trip insert; `ON CONFLICT` returns existing queue_id; race-condition simulation (two inserts in same transaction → second returns winner's id).

##### T-B-2-02: stash `provisional_queue_id` on mentions in resolution block
**Type**: impl + test
**depends_on**: T-B-2-01
**Target files**: `entity_resolution.py:run_entity_resolution_block` (around line 446)
**What**: after successful `_insert_provisional`, set `mention.provisional_queue_id = qid`. Unit test: PROVISIONAL outcome → mention has populated queue_id.

#### Validation Gate
- [ ] `provisional_entity_queue` non-empty after E2E run
- [ ] no SQL errors swallowed by savepoint (add a structured log on conflict path)

#### Break Impact
| File | Why | Fix |
|---|---|---|
| Existing `test_entity_resolution.py` asserting old SQL columns | broken | rewrite to match real schema |

#### Regression Guardrails
- BP-019 (DDL ownership): no schema change in this wave; only SQL DML alignment

---

### Wave B-3: UnresolvedResolutionWorker prompt rewrite + context_sentence (F-CRIT-05)
**Goal**: stop over-suppressing real financial entities (subsidiaries, ETFs, lesser-known regulators).
**Depends on**: T-B-2-01 (so worker has provisional queue rows to operate on)
**Estimated effort**: 3-4 hours

#### Tasks
##### T-B-3-01: extend repository to return surrounding sentence
**Type**: impl + test
**depends_on**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/entity_mention.py` (`get_unresolved_batch`)
- the dataclass returned by it (likely in same file or domain/models.py)

**What**: add JOIN to `chunks` on `doc_id` + offset; extract ±200 chars around `mention_start`; return as `context_sentence: str | None` field. Option 1 (no migration) per fix-design §F-CRIT-05.

##### T-B-3-02: rewrite `_CLASSIFICATION_PROMPT_TEMPLATE` + caller
**Type**: impl + test
**depends_on**: T-B-3-01
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py:54-59` and call site at ~line 282-283
- `services/nlp-pipeline/tests/unit/infrastructure/workers/test_unresolved_resolution_worker.py` (extend with parametrised cases)

**What**: full new template with 4 worked examples (iShares Core S&P 500 ETF positive, MAS positive, "the company" negative, "Q3" negative) — see fix-design report §F-CRIT-05.

**Tests**: 4 parametrised cases each with mocked Ollama JSON returns; assert correct outcome. Plus snapshot test of prompt string contains all 4 examples (anti-regression).

#### Validation Gate
- [ ] All 4 example cases classify correctly under stub
- [ ] Integration: 50-mention fixture (subsidiaries, ETFs, regulators) → entity recall ≥ 90% (vs current ~40%)

#### Break Impact
| File | Why | Fix |
|---|---|---|
| Existing prompt-snapshot tests | template changed | re-record |

#### Regression Guardrails
- BP-prompt-vs-context-decoupling (memory): context now lives in the prompt body, not just `ExtractionInput.context=`

---

## 7. Sub-Plan C — Alias Enrichment

### Pre-Read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py` (full)
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:280-301`
- `services/market-data/src/market_data/domain/events.py:48-68`
- `infra/kafka/schemas/market.instrument.created.avsc` (current v2)
- `libs/prompts/src/prompts/knowledge/alias.py` (current template)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/canonical_entity.py:126-155`
- `scripts/seed_demo_data.py:793-851`
- `services/intelligence-migrations/seeds/003_seed_sector_entities.sql`
- `docs/references/eodhd-endpoints-reference.md:128-247`

### Wave C-1: Avro v3 InstrumentCreated + dataclass extension
**Depends on**: none
**Estimated effort**: 1-2 hours

#### Tasks
##### T-C-1-01: bump Avro schema to v3
**Type**: schema
**depends_on**: none
**blocks**: T-C-1-02, T-C-2-01
**Target files**:
- `infra/kafka/schemas/market.instrument.created.avsc` (full new file per fix-design §B)

**What**: add `cusip, figi, lei, primary_ticker` fields, all `["null","string"]` defaulting to null. Schema_version default = 3. Doc strings cite EODHD General field names (`OpenFigi` → `figi`, etc.). Forward + backward compatible (all new fields nullable with defaults).

**Downstream test impact**: `libs/contracts/tests/test_avro_alignment.py` (must pass once dataclass is updated in T-C-1-02). `tests/contract/test_avro_schemas.py` may have literal `"schema_version": 2` asserts to update.

##### T-C-1-02: extend `InstrumentCreated` domain event + canonical model
**Type**: impl + test
**depends_on**: T-C-1-01
**Target files**:
- `services/market-data/src/market_data/domain/events.py:48-68`
- `libs/contracts/src/contracts/...` if there's a canonical model for InstrumentCreated
- `tests/contract/test_avro_schemas.py` (extend round-trip test)

**What**: bump `schema_version: ClassVar[int] = 3`; add 4 new optional fields per fix-design §D.2. Round-trip test through Avro schema.

#### Validation Gate
- [ ] `libs/contracts/tests/test_avro_alignment.py` passes
- [ ] `tests/contract/test_avro_schemas.py` passes
- [ ] schema-registry compatibility check (BACKWARD) passes

#### Break Impact
| File | Why | Fix |
|---|---|---|
| `tests/contract/test_avro_schemas.py` literal `"schema_version": 2` | bumped to 3 | update |
| `services/market-data/tests/unit/test_fundamentals_consumer.py` event-equality asserts | new fields | use partial assertions or add `cusip=None,...` to fixtures |

---

### Wave C-2: market-data extracts EODHD CUSIP/FIGI/LEI/PrimaryTicker
**Depends on**: T-C-1-02
**Estimated effort**: 2-3 hours

#### Tasks
##### T-C-2-01: extract new fields in `fundamentals_consumer.py`
**Type**: impl + test
**Target files**:
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:280-301`
- `services/market-data/tests/unit/test_fundamentals_consumer.py`

**What**: per fix-design §D.1 — replace extraction block with the `_g(k)` helper, extract `Name, ISIN, Description, CUSIP, OpenFigi → figi, LEI, PrimaryTicker`. Construct `InstrumentCreated(...)` with all 4 new fields populated when present. EODHD `OpenFigi` (NOT `FIGI`) — confirmed by reference doc.

**Tests**: fixture with all 4 new fields populated → assert event has them; fixture missing them → fields default to None; assert no SEDOL extraction (out of scope on this account).

#### Validation Gate
- [ ] new field values flow through to InstrumentCreated event
- [ ] missing-field fixture preserves None defaults

#### Break Impact
| File | Why | Fix |
|---|---|---|
| EODHD response fixtures in test files | new keys checked | add the 4 keys to fixtures |

---

### Wave C-3: knowledge-graph instrument_consumer alias inserts (Fix-A + Fix-D.3)
**Depends on**: T-A-2-01, T-C-1-02
**Estimated effort**: 3-4 hours

#### Tasks
##### T-C-3-01: insert NAME alias when EODHD name differs from canonical
**Type**: impl + test
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py` (between line 203 ISIN block and line 206 LLM call)
- `services/knowledge-graph/tests/unit/infrastructure/consumer/test_instrument_consumer.py`

**What**: per fix-design §Fix-A. Fetch `value.get("name")`; if non-empty, non-placeholder, and differs from `normalized_name` → `_try_insert_alias(eodhd_name, eodhd_norm, "NAME")` with source `"eodhd_general_name"`.

**Tests**: 2 unit tests — name differs (NAME inserted), name equals canonical (no NAME inserted).

##### T-C-3-02: insert CUSIP/FIGI/LEI/PRIMARY_TICKER aliases
**Type**: impl + test
**depends_on**: T-C-3-01, T-C-1-02
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py` (alias inserts)
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py` (Stage-2 ticker/ISIN match SQL — extend `WHERE alias_type IN (...)`)

**What**: per fix-design §Fix-D.3 — loop over `(("cusip","CUSIP"),("figi","FIGI"),("lei","LEI"),("primary_ticker","PRIMARY_TICKER"))` and call `_try_insert_alias` for each populated field. **Decision (Checkpoint A)**: `primary_ticker` gets its own dedicated `alias_type='PRIMARY_TICKER'`. Stage-2 of the resolution cascade in `entity_resolution.py` must be updated so `WHERE alias_type IN ('TICKER', 'ISIN')` becomes `WHERE alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN')`. Frontend (Wave F-2) renders PRIMARY_TICKER as a subtly differentiated pill.

**Tests**: 4 unit tests — each new alias_type inserted; collision check (when same CUSIP value already exists for another entity, log warning, skip). Plus 1 unit test for Stage-2 resolver including PRIMARY_TICKER.

#### Validation Gate
- [ ] All 6 unit tests pass
- [ ] Integration: full flow with EODHD-rich fixture → instrument has ≥4 mechanical aliases (EXACT + TICKER + ISIN + NAME) + each of CUSIP/FIGI/LEI when present

---

### Wave C-4: ALIAS_GENERATION prompt v2 + caller (F-MAJOR-09)
**Depends on**: T-C-3-01 (so `aliases_so_far` includes the new mechanical aliases)
**Estimated effort**: 3-4 hours

#### Tasks
##### T-C-4-01: rewrite `ALIAS_GENERATION` template
**Type**: impl + test
**Target files**:
- `libs/prompts/src/prompts/knowledge/alias.py` (full rewrite to v2.0)
- `libs/prompts/tests/test_prompts.py`

**What**: per fix-design §C — full template with `{name, ticker, description, aliases_so_far}` parameters + 4 worked examples (Apple Computer Inc., Facebook → Meta, NVIDIA casing, empty-result obscure ticker). Snapshot test on render.

##### T-C-4-02: update caller in `instrument_consumer._add_llm_aliases`
**Type**: impl + test
**depends_on**: T-C-4-01
**Target files**: `services/knowledge-graph/.../instrument_consumer.py:223-247` + tests
**What**: per fix-design §C caller change. Fetch existing aliases via `alias_repo.get_for_entity(entity_id)`; build `aliases_so_far_str`; pass `description` directly into the prompt (move out of `ExtractionInput.context=`); empty `context=""`.

**Tests**: snapshot test of rendered prompt; assert it contains the description excerpt and existing aliases; LLM stub returning 2 aliases → both inserted.

#### Validation Gate
- [ ] LLM-alias path produces non-zero aliases on test fixture
- [ ] no regressions on existing _add_llm_aliases tests
- [ ] `entity_aliases` rows of type `LLM` post-E2E > 0

---

### Wave C-5: Self-alias on canonical-create paths (Fix-B revised)
**Depends on**: T-A-2-01
**Estimated effort**: 2-3 hours

#### Tasks
##### T-C-5-01: `CanonicalEntityRepository.create()` co-inserts EXACT alias
**Type**: impl + test
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/canonical_entity.py:126-155`
- `services/knowledge-graph/tests/unit/infrastructure/test_repositories.py`

**What**: per fix-design §Fix-B.2 — append `INSERT INTO entity_aliases ... ON CONFLICT DO NOTHING` in same transaction. Source `'canonical_entity_create'`.

##### T-C-5-02: `seed_demo_data.py` self-alias inserts
**Type**: impl + test
**Target files**:
- `scripts/seed_demo_data.py:793-832`
- `scripts/tests/test_seed_demo.py` (NEW)

**What**: per fix-design §Fix-B.1 — after each canonical INSERT in INSTRUMENTS and KG_EXTRA_ENTITIES blocks, add `INSERT INTO entity_aliases ... 'EXACT', true, 'seed_demo_self' ON CONFLICT DO NOTHING`.

##### T-C-5-03: sector seed SQL self-alias append
**Type**: schema (data fix-up)
**Target files**: `services/intelligence-migrations/seeds/003_seed_sector_entities.sql`
**What**: append `INSERT INTO entity_aliases SELECT entity_id, canonical_name, lower(canonical_name), 'EXACT', true, '003_seed' FROM canonical_entities WHERE entity_id IN (...) ON CONFLICT DO NOTHING;`. Also covers historical seeded canonicals that lack a self-alias.

#### Validation Gate
- [ ] every canonical in `canonical_entities` has ≥1 active EXACT alias
- [ ] post-fixture run: alias-per-canonical ratio ≥ 1.0

---

## 8. Sub-Plan D — Hygiene & Dead-Code Removal

### Pre-Read
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/claims.py` (entire file — to be deleted)
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py:299-318` + the `claims_repo` parameter at line 231
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py:213` and `quotes_consumer.py:210`
- `services/portfolio/.../instrument_consumer.py` (consumes `market.instrument.created`)

### Wave D-1: Remove `claim.extracted` orphan producer (F-CRIT-08)
**Depends on**: none
**Estimated effort**: 2-3 hours

#### Tasks
##### T-D-1-01: delete claims-extracted producer path
**Type**: refactor
**Target files**:
- DELETE `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/claims.py`
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py:231,299-318` (remove parameter + claims-write loop)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:425-444` (remove ClaimsRepository import + instantiation + kwarg)
- `services/nlp-pipeline/src/nlp_pipeline/config.py:60-62` (remove `topic_claim_extracted` setting)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/outbox/dispatcher.py:6` (update docstring)
- `services/nlp-pipeline/tests/unit/application/blocks/test_deep_extraction.py:203,246,261,287,302` (drop `claims_repo` mocks)
- one-off SQL cleanup: `DELETE FROM nlp_db.outbox_events WHERE topic LIKE 'claim.extracted%' AND status='dispatched'`

**Acceptance**: integration E2E shows zero `claim.extracted` rows after a fresh article cycle.

#### Validation Gate
- [ ] no Kafka producer references `claim.extracted` in nlp-pipeline
- [ ] all unit tests pass after `claims_repo` removal
- [ ] grep across services for `claim.extracted` returns only `.claude/worktrees/` archives

#### Break Impact
| File | Why | Fix |
|---|---|---|
| Tests using `claims_repo` mock | parameter removed | drop mock |

---

### Wave D-2: Defer `InstrumentCreated`; introduce `market.instrument.discovered.v1` (APPROVED 2026-04-30)
**Depends on**: T-A-2-01 (UNIQUE alias index, so KG-side discovered consumer's alias inserts are safe)
**Estimated effort**: 6-8 hours

#### Approach (locked)
- Producer-side (`market-data`): `ohlcv_consumer.py` and `quotes_consumer.py` no longer emit `market.instrument.created`. They emit `market.instrument.discovered.v1` (small payload). `fundamentals_consumer.py` is the sole emitter of `market.instrument.created` — gated on having a real `Name` from EODHD.
- Portfolio S2 subscribes to `discovered` for `InstrumentRef` materialisation (replaces its current `created` subscription for the discovery purpose).
- **Knowledge-graph subscribes to `discovered`** via a new `InstrumentDiscoveredConsumer` that creates a *lightweight* canonical entity:
  - `canonical_name = symbol` (placeholder, marked in metadata)
  - `entity_type = "financial_instrument"`
  - `ticker = symbol`, `exchange = exchange`, `isin = NULL`
  - `metadata = {"source": "discovered", "needs_fundamentals_enrichment": true, "discovered_at": "..."}`
  - Inserts EXACT alias for the symbol + TICKER alias (ON CONFLICT DO NOTHING)
  - Inserts `entity_embedding_state` rows for `definition` + `narrative` + `fundamentals_ohlcv` (3 rows; fundamentals_ohlcv left empty until enrichment)
- The existing `InstrumentEntityConsumer` (which consumes `market.instrument.created`) becomes an **UPSERT** path: when fundamentals arrives for an already-discovered instrument, it updates `canonical_name` from the placeholder to the real name, clears the `needs_fundamentals_enrichment` flag, and adds the rich alias suite (NAME / ISIN / CUSIP / FIGI / LEI / PRIMARY_TICKER).

#### Tasks
##### T-D-2-01: New Avro schema `market.instrument.discovered.v1`
**Type**: schema
**Target files**:
- `infra/kafka/schemas/market.instrument.discovered.v1.avsc` (NEW)

**What**: minimal payload — `event_id`, `event_type` (default `"market.instrument.discovered"`), `schema_version` (default 1), `occurred_at`, `instrument_id`, `symbol`, `exchange` (nullable), `correlation_id` (nullable), `causation_id` (nullable). All forward-compat (nullable + defaults).

##### T-D-2-02: Domain event + canonical model in shared library
**Type**: impl + test
**depends_on**: T-D-2-01
**Target files**:
- `services/market-data/src/market_data/domain/events.py` (add `InstrumentDiscovered` dataclass)
- `libs/contracts/src/contracts/instruments.py` or equivalent (add canonical model)
- `libs/contracts/tests/test_avro_alignment.py` (extend; assert dataclass fields align with Avro schema field-by-field)

##### T-D-2-03: Producer switch in `ohlcv_consumer.py` + `quotes_consumer.py`
**Type**: impl + test
**depends_on**: T-D-2-02
**Target files**:
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py:213` (replace `InstrumentCreated(...)` emit with `InstrumentDiscovered(...)`)
- `services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py:210` (same)
- `services/market-data/tests/unit/test_ohlcv_consumer.py`, `test_quotes_consumer.py` (assert no `InstrumentCreated` emit; assert `InstrumentDiscovered` emit)

##### T-D-2-04: KG `InstrumentDiscoveredConsumer` (new)
**Type**: impl + test
**depends_on**: T-D-2-02, T-A-2-01
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_discovered_consumer.py` (NEW, mirrors `instrument_consumer.py` structure)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_discovered_consumer_main.py` (NEW)
- `docker-compose.yml` (NEW container `worldview-knowledge-graph-instrument-discovered-consumer-1`)
- `services/knowledge-graph/tests/unit/infrastructure/consumer/test_instrument_discovered_consumer.py` (NEW)

**What**:
- Consumer group: `kg-instrument-discovered-group`
- Consumes: `market.instrument.discovered.v1`
- Per message:
  1. UPSERT canonical_entity (instrument_id as entity_id, canonical_name=symbol, entity_type='financial_instrument', ticker=symbol, exchange=exchange, metadata=`{...}`); on conflict (entity_id) → if metadata has `needs_fundamentals_enrichment=true`, do nothing (we already discovered it); if not, do nothing (already enriched, real canonical present).
  2. Insert EXACT alias for `symbol` (ON CONFLICT DO NOTHING)
  3. Insert TICKER alias for `symbol` (ON CONFLICT DO NOTHING)
  4. Call `EntityEmbeddingStateRepository.ensure_rows_exist(entity_id, "financial_instrument")` (creates 3 view rows with `next_refresh_at=now()`).
  5. No LLM alias generation (no description yet).

**Tests**:
- New instrument → 1 canonical + 2 aliases + 3 embedding-state rows
- Re-delivery (idempotency) → no duplicates
- Discovered then later Created (with fundamentals) → InstrumentEntityConsumer (T-D-2-05) UPSERTs name from symbol to EODHD name, clears `needs_fundamentals_enrichment`, adds rich aliases (NAME / CUSIP / FIGI / LEI / PRIMARY_TICKER)

##### T-D-2-05: Update `InstrumentEntityConsumer` for UPSERT-after-discover semantics
**Type**: impl + test
**depends_on**: T-D-2-04
**Target files**:
- `services/knowledge-graph/.../instrument_consumer.py` (update process_message to handle the case where canonical_entity already exists with placeholder name from discovered)
- existing tests extended

**What**: when consuming `market.instrument.created` (fundamentals-enriched) for an already-discovered instrument:
- UPDATE canonical_entities SET canonical_name=<real_name>, isin=<real_isin>, description=<real_desc>, metadata = metadata - 'needs_fundamentals_enrichment' WHERE entity_id=<instrument_id> AND metadata->>'needs_fundamentals_enrichment'='true'
- Then run the existing alias-enrichment block (NAME, ISIN, CUSIP, FIGI, LEI, PRIMARY_TICKER, LLM).

##### T-D-2-06: Portfolio S2 InstrumentRef switch
**Type**: impl + test
**depends_on**: T-D-2-02
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer.py` (update topic subscription from `market.instrument.created` to `market.instrument.discovered.v1` for the discovery purpose; keep `market.instrument.created` for any enrichment update if needed)
- corresponding tests

##### T-D-2-07: Docker-compose + worldview-gitops sync
**Type**: config
**Target files**:
- `docker-compose.yml` (new KG consumer container)
- `worldview-gitops` repo (new K8s deployment for the KG discovered consumer)

**What**: new container `worldview-knowledge-graph-instrument-discovered-consumer-1` mirroring the existing `instrument-consumer` config block. Helm values get a parallel deployment.

**Tests**:
- Cross-service contract test: producer in market-data emits `discovered.v1` → portfolio consumer + KG consumer both materialise correctly
- Avro round-trip in `tests/contract/test_avro_schemas.py`

#### Validation Gate
- [ ] `tests/contract/test_avro_schemas.py` passes (new schema + alignment)
- [ ] `libs/contracts/tests/test_avro_alignment.py` passes
- [ ] After E2E: every new instrument from market-ingestion gets a discovered → KG canonical (lightweight) → enriched (rich) flow
- [ ] No `Instrument-019dbbdb` placeholder names ever appear (because we now use the real `symbol` as the placeholder)

#### Break Impact
| File | Why | Fix |
|---|---|---|
| `services/portfolio/tests/.../test_instrument_consumer.py` | topic name change | update fixture topic |
| Existing `services/knowledge-graph/tests/.../test_instrument_consumer.py` | UPSERT semantics on already-discovered | extend with new fixture path |

#### Regression Guardrails
- BP-001 (idempotent Kafka consumers): both new consumers must idempotently handle re-delivery by `instrument_id`
- BP-126 (forward-compat schema): all new fields nullable

---

### Wave D-3: Synthesised-name EXACT-alias guard (F-CRIT-12.E.3)
**Depends on**: T-C-3-01 (works on top of the C-3 alias logic)
**Estimated effort**: 1 hour

#### Tasks
##### T-D-3-01: skip EXACT alias when name was synthesised
**Type**: impl + test
**Target files**: `services/knowledge-graph/.../instrument_consumer.py:135-192`
**What**: per fix-design §Fix-E.3:
```python
synthesised_name = not (raw_name and str(raw_name).strip())
# ...
if not synthesised_name:
    await _try_insert_alias(canonical_name, normalized_name, "EXACT")
```

#### Validation Gate
- [ ] no `Instrument-{8hex}` strings appear in `entity_aliases.alias_text` after fresh ingest

---

## 9. Sub-Plan E — Config + Worker Wiring

### Wave E-1: MarketDataClient internal-JWT (F-MAJOR-02)
**Estimated effort**: 3-4 hours

#### Tasks
##### T-E-1-01: add `_internal_jwt_headers` helper
**Type**: impl + test
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/http/market_data_client.py`
- `services/nlp-pipeline/src/nlp_pipeline/config.py` (add `internal_jwt_signing_key: SecretStr` setting)
- `services/nlp-pipeline/tests/unit/infrastructure/http/test_market_data_client.py`

**What**: per fix-design §F-MAJOR-02 — mirror `services/portfolio/.../current_price_client.py:51-75` `_system_jwt_headers`. HS256, `iss="worldview-gateway"`, `sub="system:nlp-pipeline-price-impact"`, `role="system"`, 1-day exp. Send `X-Internal-JWT` header on every GET.

##### T-E-1-02: env var + gitops sync
**Type**: config
**Target files**:
- `services/nlp-pipeline/configs/dev.local.env.example`
- `services/nlp-pipeline/configs/docker.env`
- `worldview-gitops` repo: Helm values + sealed secret reference (the user's `bootstrap/setup-secrets.sh` copies into worldview)

**What**: `NLP_PIPELINE_INTERNAL_JWT_SIGNING_KEY=dev-skip-verification-key-for-portfolio-current-price` in dev. Prod: from K8s secret `worldview-internal-jwt-key`.

#### Validation Gate
- [ ] `article_impact_windows` table receives rows after E2E run
- [ ] `price_impact` routing signal becomes non-zero for instruments with OHLCV history

#### Open Question
Same prod-RS256-issuer gap as portfolio. Phase 1 (this wave): HS256 in dev; prod stays HS256-on-skip-verification until gateway exposes a service-account RS256 issuer (separate ticket).

---

### Wave E-2: Gemini description provider env (F-MAJOR-04)
**Estimated effort**: 30 min (config-only)

#### Tasks
##### T-E-2-01: env vars + gitops sync
**Type**: config
**Target files**:
- `services/knowledge-graph/configs/dev.local.env.example`
- `services/knowledge-graph/configs/docker.env`
- `worldview-gitops` (Helm values)

**What**:
```
KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER=gemini
KNOWLEDGE_GRAPH_GEMINI_API_KEY=<dev-key>
KNOWLEDGE_GRAPH_DESCRIPTION_GEMINI_CONCURRENCY=4
KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD=50
```

Prod: cap at $200/mo, key from sealed secret.

#### Validation Gate
- [ ] After A-3 + this wave: ≥1 non-template description appears in `canonical_entities.description` (sample after 5 min)
- [ ] `intelligence_db.llm_usage_log` has Gemini rows with capability=`"description"`

---

### Wave E-3: AGE cypher_enabled flip (F-MAJOR-08)
**Estimated effort**: 30 min

#### Tasks
##### T-E-3-01: env vars + gitops sync
**Type**: config
**Target files**:
- `services/knowledge-graph/configs/docker.env:78` (`KNOWLEDGE_GRAPH_CYPHER_ENABLED=true`)
- `services/knowledge-graph/configs/dev.local.env.example:30`
- `worldview-gitops` Helm values

**What**: flip the flag. AgeSyncWorker is fully implemented (verified by fix-design agent); just disabled by config.

#### Pre-flight checks
1. AGE extension loaded + `worldview_graph` exists (audit confirms)
2. AgeSyncWorker registered in scheduler (verified)
3. Initial sync from epoch is heavy — schedule during off-peak first run
4. Cypher endpoints (`api/cypher.py`) start serving live data — ensure rate limiting / auth in place

#### Validation Gate
- [ ] After 1 scheduler tick: `MATCH (n) RETURN count(n)` > 0
- [ ] Watermark in Valkey (`s7:age:sync:watermark`) advances

---

### Wave E-4: EmbeddingRetryWorker entry point + lifespan (F-MAJOR-05)
**Estimated effort**: 2-3 hours

#### Tasks
##### T-E-4-01: new entry point file
**Type**: impl + test
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/workers/embedding_retry_worker_main.py` (NEW, ~25 lines per fix-design §F-MAJOR-05)
- `services/nlp-pipeline/src/nlp_pipeline/app.py` (lifespan integration: `asyncio.create_task(worker.run_forever(stop_event))`)

##### T-E-4-02: optional `last_attempted_at` migration
**Type**: schema
**Target files**: `services/nlp-pipeline/alembic/versions/0013_add_embedding_pending_last_attempted.py`
**What**: `ALTER TABLE embedding_pending ADD COLUMN last_attempted_at TIMESTAMPTZ`; update `mark_failure()` repo method to set it. Add `embedding_retry_abandoned` log when `retry_count >= 5`.

#### Validation Gate
- [ ] `embedding_pending` row count drops after worker starts
- [ ] rows with `retry_count >= 5` get logged-abandoned, not retried infinitely

---

### Wave E-5: entity_embedding_state startup repair (F-MAJOR-06)
**Estimated effort**: 1-2 hours

#### Tasks
##### T-E-5-01: startup repair task
**Type**: impl + test
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/embedding_state_repair.py` (NEW)
- `services/knowledge-graph/src/knowledge_graph/app.py` (lifespan call)

**What**: per fix-design §F-MAJOR-06 — query canonical_entities with fewer view rows than expected (3 for `financial_instrument`, 2 for others); call `EntityEmbeddingStateRepository.ensure_rows_exist()` for each.

#### Validation Gate
- [ ] post-startup: every canonical has the correct number of view rows
- [ ] re-run is idempotent (ON CONFLICT DO NOTHING)

---

## 10. Sub-Plan F — Frontend Surface (downstream-only, conditional)

**Trigger**: only ship if A-3 + C-2/C-3 surface new entity_type/alias_type values that the frontend currently can't render.

### Wave F-1: Entity-detail page entity_type variants
**Depends on**: T-A-3-02
**Estimated effort**: 3-4 hours

#### Tasks
- T-F-1-01: add type-mapping for 9 new entity_types in `apps/worldview-web/.../entity-detail.tsx` (icon, badge color, layout variant)
- T-F-1-02: e2e snapshot tests for each new type
- T-F-1-03: update `apps/worldview-web/__tests__/...`

### Wave F-2: Alias-pill rendering
**Depends on**: T-C-3-02
**Estimated effort**: 2 hours

#### Tasks
- T-F-2-01: render new alias_types (CUSIP / FIGI / LEI / PRIMARY_TICKER / NAME) as labelled pills with subtle differentiation
- T-F-2-02: ensure entity-detail page lists all aliases sorted by alias_type

---

## 11. Cross-Cutting Concerns

### 11.1 Avro schema changes
- C-1: `market.instrument.created.avsc` v3 (add 4 nullable fields). Schema-registry compatibility: BACKWARD.
- B-1: `nlp.article.enriched.v1` payload — gains `entity_provisional` + `provisional_queue_id` inside `raw_relations[]`/`raw_events[]`/`raw_claims[]`. The schema is JSON-encoded outbox payload, NOT a strict Avro schema (verified yesterday) — additive change is forward/backward compat by construction.

### 11.2 DB migrations (ordered)
1. `intelligence-migrations/0009_alias_unique_per_entity` (A-2)
2. `intelligence-migrations/0010_seed_canonicals_bootstrap` (A-3)
3. `nlp-pipeline/0012_add_processing_path_to_routing_decisions` (A-1)
4. `nlp-pipeline/0013_add_embedding_pending_last_attempted` (E-4)

### 11.3 New Kafka topics
- D-2 (CHECKPOINT-A only): `market.instrument.discovered.v1`

### 11.4 Configuration changes
- E-1: `NLP_PIPELINE_INTERNAL_JWT_SIGNING_KEY`
- E-2: `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER`, `KNOWLEDGE_GRAPH_GEMINI_API_KEY`, `KNOWLEDGE_GRAPH_DESCRIPTION_GEMINI_CONCURRENCY`, `KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD`
- E-3: `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true`

All require gitops sync (Helm values + sealed secrets) per the user's setup-secrets.sh workflow.

### 11.5 Documentation updates
- `docs/services/nlp-pipeline.md` (routing_decisions schema, mention_resolutions persistence, new prompt)
- `docs/services/knowledge-graph.md` (new alias_types, AGE cypher_enabled default, embedding_state repair)
- `docs/services/market-data.md` (InstrumentCreated v3 fields, new topic if D-2 ships)
- `docs/MASTER_PLAN.md` (alias-type list, canonical seed bootstrap)
- `docs/BUG_PATTERNS.md` (5 new patterns: BP-prompt-input-mismatch, BP-orphan-outbox-topic, BP-seed-non-idempotent, BP-class-without-canonicals, BP-prompt-vs-context-decoupling)
- `docs/references/eodhd-fundamentals-fields.md` (add CUSIP/OpenFigi/LEI/PrimaryTicker as confirmed available)

---

## 12. Risk Assessment

### 12.1 Critical path
A-1, A-2, A-3, A-4, A-5 → B-1 → B-2 → C-3 → C-4. Until A-3 ships, B-1's effectiveness is bounded by ~17% `financial_instrument` resolution rate. Until B-2 ships, B-1 has no real `provisional_queue_id` to thread.

### 12.2 Highest risk
- **D-2** (defer InstrumentCreated): cross-service contract change, can break portfolio. **MUST NOT ship without Checkpoint A approval.** Default fallback if not approved: ship D-3 only.
- **A-3** (canonical seeds): largest data migration in plan; rollback by `metadata->>'seed_source' = 'F-CRIT-10'` deletion. Tested via round-trip in T-A-3-03.
- **C-1** (Avro v3): schema-registry compatibility check is mandatory before any service deploys with v3.

### 12.3 Rollback strategy
- Each wave commits independently. `git revert <sha>` per wave.
- Alembic migrations all have working `downgrade()` functions tested in their migration test files.
- Config changes (E-2, E-3) are reversible via env-var flip.

### 12.4 Testing gaps
- No held-out evaluation set for relation/claim/entity quality. Adding such a set is in audit Tier-1.1; deferred to a separate plan.
- No production-like load testing for the post-fix throughput (LLM call rate may exceed DeepInfra account limits if all extractions suddenly succeed).

---

## 13. QA Gate (post-implementation)

After all waves committed, launch a strict QA agent (per user's spec):
1. Read PLAN-0057 + audit doc to understand expected delivery
2. Spin up real containers (`make dev`)
3. Test every changed endpoint
4. Sample DB after a fresh ingest cycle:
   - `mention_resolutions` non-empty
   - `provisional_entity_queue` non-empty
   - `relation_evidence_raw` non-empty
   - `relations` row count > 18 (i.e., real production rows beyond seeded)
   - `entity_aliases` ≥4-per-canonical for instruments
   - `llm_usage_log` populated in BOTH nlp_db and intelligence_db
   - `article_impact_windows` non-empty
   - AGE: `MATCH (n) RETURN count(n) > 0`
5. Sample LLM outputs for quality (random 10 claims, 10 relations) — judge GOOD/MEDIOCRE/BROKEN
6. Surface any newly-discovered issues: edge cases, regressions, optimisation opportunities
7. Iterate until QA reports zero outstanding issues

---

## 14. Compounding Updates

### Memory entries to add
- `feedback_avro_optional_fields_default_null.md` — schema evolution best practice
- `project_canonical_seed_namespacing.md` — UUIDv7 prefix convention `c001..c009`
- `feedback_session_scoped_usage_logger.md` — pattern for plumbing optional logger through async workers

### BUG_PATTERNS.md additions
- BP-XXX-prompt-input-mismatch (already in memory; promote to BUG_PATTERNS)
- BP-XXX-orphan-outbox-topic
- BP-XXX-seed-non-idempotent
- BP-XXX-class-without-canonicals
- BP-XXX-prompt-vs-context-decoupling

### REVIEW_CHECKLIST additions
- "When a function looks up values produced by an LLM against a dict, verify the dict was populated from the same source the prompt told the LLM to draw from." (already noted in audit §6.8)
- "When a Kafka topic is added to the producer side, verify a consumer group exists somewhere; otherwise it's an orphan write."

---

## 15. Decisions Locked (2026-04-30 Checkpoint A)

1. **Wave D-2 — APPROVED + EXTENDED**. Defer `market.instrument.created` from `ohlcv_consumer`/`quotes_consumer`; introduce `market.instrument.discovered.v1` event. Portfolio S2 subscribes to it for `InstrumentRef`. **Knowledge-graph also subscribes** via a new `InstrumentDiscoveredConsumer` that creates a lightweight canonical entity (symbol-only placeholder name, `entity_type=financial_instrument`, `metadata={"source": "discovered", "needs_fundamentals_enrichment": true}`). When fundamentals arrives later, the existing `InstrumentEntityConsumer` enriches the same canonical (UPSERT by instrument_id) with the full alias suite. Shared library `libs/contracts` gets the new event model; both producer-side and KG-consumer-side tests added. See expanded D-2 task list below.
2. **Wave A-3 — APPROVED with quality bar**. Only seed 6 non-listed institutions (Vanguard, Fidelity, Bridgewater, BlackRock-as-asset-manager, Brookfield, Apollo). Each must have: hand-written 1-2 sentence description in `metadata.description`, populated `entity_embedding_state` for `definition` + `narrative` views (so refresh workers can pick them up), and frontend rendering verified in Wave F-1. The same quality bar applies to all ~224 seeds — every one must be UI-ready (not just resolution-ready).
3. **Wave C-3 — `PRIMARY_TICKER` alias_type**. Migrate to a new dedicated `alias_type='PRIMARY_TICKER'`. Stage-2 of the resolution cascade (ticker/ISIN match) must be extended to include `PRIMARY_TICKER` in its `WHERE alias_type IN (...)` predicate. Frontend pill-rendering treats it as a separate (subtly differentiated) badge.
4. **Wave E-1 — HS256 in dev confirmed**. Prod stays HS256-on-skip-verification until the gateway exposes an RS256 service-account issuer (separate ticket). All env-var seams stay identical so the prod swap is a single-config change.
5. **Sub-Plan F — APPROVED**. Will ship F-1 + F-2 after A-3 + C-2/C-3 verifies new types appear in API responses.

These decisions are locked. Implementation proceeds without further checkpoints until **Checkpoint B** (pre-gitops sync) and **Checkpoint C** (post-QA before fix-loop on schema/contract regressions).
