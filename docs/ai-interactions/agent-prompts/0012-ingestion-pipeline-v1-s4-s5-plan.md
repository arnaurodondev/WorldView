# Prompt 0012 — Ingestion Pipeline v1: S4 Content Ingestion + S5 Content Store

> **Status**: ⏳ Pending implementation

Act as the **Backend Engineer** (`.claude/agents/backend-engineer.md`) and **Data Platform Engineer** (`.claude/agents/data-platform-engineer.md`).

## Goal

Produce a highly detailed implementation plan (NO code) for the ingestion pipeline S4 and S5 services, then decompose it into independent, executable atomic tasks.

**Prerequisites**: Prompt 0015 foundations scope must be complete before this plan is executed:
- `libs/ml-clients` library exists
- `content_ingestion_db` and `content_store_db` schemas + Alembic migrations are in place
- All Avro schemas for `content.article.raw.v1` and `content.article.stored.v1` are registered
- Kafka topics for `content.article.raw.v1` and `content.article.stored.v1` are created

## Mandatory pre-read

All of the following must be read before producing the plan. Do not skip any.

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. `docs/MASTER_PLAN.md`
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` — **read §2 (pipeline), §5 §Block1, §Block2, §Block3 (S4 blocks), §6.1 (content_ingestion_db), §6.2 (content_store_db), §8 (partition policy), §9 (outbox/DLQ), §11 (observability/backpressure), §14 (boot order) in full**
6. `docs/services/content-ingestion.md` — current S4 service spec
7. `docs/services/content-store.md` — current S5 service spec
8. `docs/libs/contracts.md`
9. `docs/libs/messaging.md`
10. `docs/libs/storage.md`
11. `docs/libs/observability.md`
12. `libs/contracts/**` — canonical models
13. `libs/messaging/**` — outbox, Kafka producer
14. `libs/storage/**` — MinIO client
15. `services/content-ingestion/**` — S4 current stub state
16. `services/content-store/**` — S5 current stub state
17. `infra/kafka/schemas/content.article.raw.v1.avsc`
18. `infra/kafka/schemas/content.article.stored.v1.avsc`
19. `.claude/agents/backend-engineer.md` — service implementation standards
20. `.claude/agents/data-platform-engineer.md` — DB/Kafka ownership rules

## Directories to scan

### Target (worldview)
- `worldview/services/content-ingestion/**` — S4 (full current state)
- `worldview/services/content-store/**` — S5 (full current state)
- `worldview/libs/` — all 6 libs (especially messaging, storage, contracts)
- `worldview/infra/kafka/` — schemas, init
- `worldview/docs/services/content-ingestion.md`
- `worldview/docs/services/content-store.md`

## Constraints

- **Hexagonal architecture only**: `api/ → application/use_cases/ → domain/ → infrastructure/`
- **Outbox mandatory**: S4 and S5 must write to their outbox table in the same DB transaction as domain writes. Never produce to Kafka directly inside a handler.
- **MinIO**: S4 writes raw payloads to MinIO bronze tier. S5 writes canonical docs to MinIO silver tier. Key format: `<service>/<domain>/<resource_id>/<artifact>/<version>.<ext>`
- **No cross-DB FK constraints**: `minhash_entity_mentions.entity_id` is a logical FK to `intelligence_db.canonical_entities` — stored as UUID, no Postgres FK constraint.
- **MinHash `INTEGER[]`**: `minhash_signatures.signature` is `INTEGER[]` (128-band), never BYTEA.
- **Idempotency**: all consumers and processors must be idempotent — processing the same message twice must produce the same result.
- **UUIDv7** for all entity IDs, UTC-only timestamps.
- **`structlog` only** — no `print()` or stdlib `logging`.
- **Ruff + mypy strict** must pass before any wave is considered done.

## Out of scope

- S6 NLP Pipeline processing — in Prompt 0017
- S7 Knowledge Graph — in Prompt 0017
- S10 Alert Service — in Prompt 0017
- S8 RAG/Chat — out of scope for this initiative

## S4 Content Ingestion — Plan Coverage

### Block 1: Source Adapters + Polling Scheduler
- APScheduler-based polling scheduler (not APScheduler workers — this is a cron-style fetch loop)
- Source adapters: EODHD news API, SEC EDGAR (EDGAR full-text search), Finnhub news API, NewsAPI
- Each adapter: `FetchResult(raw_payload, source_type, url, fetched_at)` return type
- Polling interval per source (from `sources` table `polling_interval_seconds`)
- Rate limiting per source: token-bucket pattern, `RetryableError` on 429
- Relay fallback: configurable fallback source URL when primary is blocked
- APScheduler job: `poll_source(source_id)` — one job per enabled source

### Fetch + Write Pipeline (hot path)
- Fetch raw article payload from source adapter
- Compute `url_hash = sha256(url)` — dedup key
- Write raw payload to MinIO bronze: `content-ingestion/raw/{source_type}/{url_hash}/payload.json`
- Insert `raw_article_metadata` row
- Insert `outbox_events` row in the same DB transaction — event type `article.raw.created.v1`
- Outbox dispatcher publishes to `content.article.raw.v1`
- `fetch_logs` record for every poll attempt (success or failure)

### Admin API
- `GET /api/v1/sources` — list configured sources
- `POST /api/v1/sources` — add source (admin only, X-Admin-Token auth)
- `PUT /api/v1/sources/{id}` — update source config
- `POST /api/v1/ingest/trigger` — manual trigger for one source
- `GET /api/v1/ingest/status` — recent fetch log (last N entries)

### Readiness + Observability
- `GET /health` (liveness), `GET /ready` (DB + Kafka producer + MinIO)
- Prometheus metrics: `s4_fetches_total{source,status}`, `s4_fetch_duration_seconds`, `s4_outbox_pending_total`
- DLQ endpoints: `/admin/dlq` (list, get, retry, resolve) — X-Admin-Token required

## S5 Content Store — Plan Coverage

### Block 2: Two-Tier Deduplication + Canonical Doc Write
- S5 consumes from `content.article.raw.v1`
- **Tier 1 — Exact dedup**: SHA-256 hash of normalized body; check `canonical_documents.content_hash`
- **Tier 2 — Normalized hash**: strip whitespace/punctuation, recompute; secondary exact check
- **Tier 3 — Near-dup MinHash**: compute 128-band MinHash signature from token set; LSH bucket lookup in Valkey
  - Valkey LSH keys: `lsh:{band_index}:{band_hash}` → `[sig_id, ...]`
  - TTL per source type: news=7d, earnings=30d, SEC=180d, permanent=no TTL
  - Near-dup threshold: Jaccard similarity ≥ 0.80 → suppress
- On non-duplicate: write canonical doc body to MinIO silver: `content-store/canonical/{doc_id}/body.json`
- Insert `canonical_documents` row
- Insert `minhash_signatures` row (`signature INTEGER[]`)
- Insert `minhash_entity_mentions` rows (logical FK to `canonical_entities`, no Postgres FK constraint)
- Insert `outbox_events` in same transaction — event type `article.stored.created.v1`
- Outbox dispatcher publishes to `content.article.stored.v1`

### Novelty Score Tracking
- `novelty_scores` table: per-entity Jaccard similarity score from MinHash comparison
- Written after dedup check, before emit
- Consumed by S6 Block 8 (novelty routing downgrade)

### S5 Admin + Observability
- `GET /health`, `GET /ready` (DB + Kafka assignment)
- Prometheus metrics: `s5_articles_received_total`, `s5_duplicates_suppressed_total{tier}`, `s5_canonical_written_total`, `s5_outbox_pending_total`
- DLQ endpoints: `/admin/dlq` — X-Admin-Token required

## Testing requirements (task-level)

For each task, include:

- **Unit tests**: domain logic (dedup tiers, MinHash computation, token-bucket rate limiting, state machines)
- **Integration tests** (marked `@pytest.mark.integration`):
  - S4: fetch adapter tests against mock HTTP server (pytest-httpserver or similar), outbox → Kafka round-trip
  - S5: end-to-end `content.article.raw.v1` → canonical doc write → `content.article.stored.v1` emit
  - MinHash dedup: near-duplicate detection at Jaccard ≥ 0.80 threshold
  - Idempotency: processing the same message twice produces same result, no duplicate DB rows
- **Service container tests**: full S4 + Postgres + MinIO + Kafka stack (via docker-compose)
- **Platform QA impact**: S4 → S5 → S6 pipeline continuity (can be stubbed at S6 boundary for this scope)

## Output format (strict)

1. **Executive summary** — what S4 + S5 deliver and where they hand off to S6
2. **Current-state vs target-state matrix** — per service (S4, S5), per layer (domain, application, infrastructure, API)
3. **Dependency graph** — which tasks block which; parallel work opportunities
4. **Atomic task backlog** — ticket style, each with:
   - ID (prefix `T-S4-` or `T-S5-`), title, objective
   - Paths to read / paths to create or modify
   - Prerequisites/dependencies (including Prompt 0015 task IDs)
   - Implementation steps (numbered, concrete)
   - Tests required and expected evidence
   - Documentation updates required
   - Definition of Done
   - Risks + mitigation
   - Effort estimate
5. **Milestones**:
   - M1: S4 domain + infrastructure layer complete (scheduler, adapters, outbox dispatcher)
   - M2: S4 API + observability complete (admin endpoints, DLQ, Prometheus metrics, readiness)
   - M3: S5 domain + dedup pipeline complete (all 3 dedup tiers, MinHash, LSH Valkey)
   - M4: S5 canonical write + outbox complete (MinIO silver, novelty scores, outbox)
   - M5: Full S4 → S5 pipeline validated end-to-end
6. **Open questions and assumptions**

## Response artifact required

After execution, create a response report in:

- `worldview/docs/ai-interactions/agent-responses/`

Filename: `0016-response-<YYYYMMDD>-ingestion-pipeline-v1-s4-s5.md`

The response must include: what was planned, how decisions were made, full atomic task backlog with IDs.

Then generate execution wave prompt files in:

- `worldview/docs/ai-interactions/agent-prompts/`

Naming: `0016-exec-ingestion-pipeline-v1-s4-s5-wave-<nn>.md`

Each execution prompt must follow the structure in `docs/ai-interactions/agent-prompts/0000-exec-wave-generation-template.md`:
- reference planning prompt and response files
- specify exact task IDs per wave
- mark parallel vs sequential groups
- include required test commands, documentation obligations, and handoff evidence requirements
- enforce Documentation quality standard (all 8 criteria)
- enforce incremental fail-fast gates per task
- commit message proposal per wave; highly detailed PR description on final wave only
