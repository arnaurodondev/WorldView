# Worldview Intelligence Layer — PRD Addendum v1.0

**Version**: 1.0
**Date**: 2026-03-19
**Status**: Active
**Supersedes**: Nothing — this document supplements PRD v2.0, it does not replace it.
**Purpose**: Resolves all critical, significant, and moderate gaps identified in the PRD gap analysis. Every section in this document corresponds to a gap item. When this addendum conflicts with the base PRD on a specific point, this addendum takes precedence.

---

## Table of Contents

A. [Critical Fixes](#a-critical-fixes)
B. [Significant Fixes](#b-significant-fixes)
C. [Moderate Fixes](#c-moderate-fixes)

---

## A. Critical Fixes

### A.1 — Missing Topic: `portfolio.watchlist.updated.v1`

This topic is produced by S1 Portfolio whenever a user modifies their watchlist (add entity, remove entity, create watchlist, delete watchlist). S10 Alert Service consumes it to invalidate the Valkey reverse-index cache.

**Topic definition:**

| Field | Value |
|-------|-------|
| Topic name | `portfolio.watchlist.updated.v1` |
| Producer | S1 · Portfolio |
| Consumer | S10 · Alert Service (consumer group: `alert-service-watchlist-group`) |
| Partition key | `user_id` |
| Partitions | 3 |
| Retention | 7 days |
| Offset strategy | At-least-once; S10 commits after Valkey cache invalidation |

**Message schema:**

```json
{
  "event_id": "string (UUIDv7)",
  "event_type": "portfolio.watchlist.updated",
  "schema_version": 1,
  "occurred_at": "string (ISO 8601 UTC)",
  "user_id": "string (UUID)",
  "watchlist_id": "string (UUID)",
  "change_type": "string (entity_added | entity_removed | watchlist_created | watchlist_deleted)",
  "entity_id": "string (UUID) or null",
  "entity_ids_affected": ["string (UUID)"]
}
```

`entity_ids_affected` contains all entity IDs whose Valkey reverse-index cache key must be invalidated. For `entity_added` and `entity_removed`, this is a single-element array. For `watchlist_deleted`, this is all entities that were on the watchlist.

**S10 consumer logic:**

```python
async def on_watchlist_updated(event: WatchlistUpdatedEvent):
    keys_to_delete = [
        f"s10:v1:watchlist:by_entity:{eid}"
        for eid in event.entity_ids_affected
    ]
    if keys_to_delete:
        valkey.delete(*keys_to_delete)
```

**S1 Portfolio obligation.** S1 must publish this event from within the same database transaction that modifies the watchlist, using the outbox pattern (same pattern as other S1 events). This topic definition must be added to `infra/kafka/schemas/portfolio.watchlist.updated.avsc` and to the service catalog in the base PRD Section 3 table.

---

### A.2 — Contradiction Detection Logic: Semantic Incompleteness Fix

**Problem.** The query in Block 12 of the base PRD compares claims by `claimer_entity_id + claim_type + polarity != $polarity`. This incorrectly flags every positive claim as contradicting every negative claim about the same claimer, regardless of subject matter. A CEO saying "our margins are improving" does not contradict an analyst saying "guidance was cut" — these are different subjects.

**Fix: add a `subject_entity_id` column to `claims` and anchor contradiction on subject.**

**Schema change — add column to `claims`:**

```sql
ALTER TABLE claims ADD COLUMN subject_entity_id UUID REFERENCES canonical_entities(entity_id);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `subject_entity_id` | UUID | YES | NULL | The entity that the claim is *about* (distinct from the claimer). For "CEO says TSMC margins will improve", `claimer_entity_id = CEO_entity`, `subject_entity_id = TSMC_entity`. NULL when subject is the same as claimer or cannot be extracted. |

**Updated extraction schema.** Add `subject_entity_id` to the LLM extraction output schema in Block 10:

```json
"claims": [{
  "claimer_entity_id": "string or null",
  "subject_entity_id": "string or null",
  "claim_type": "forward_guidance|factual|projection|denial|opinion",
  "claim_text": "string",
  "polarity": "positive|negative|neutral",
  "confidence": "float",
  "evidence_text": "string",
  "char_start": "int",
  "char_end": "int"
}]
```

**Updated contradiction detection query (replaces Block 12 original):**

```sql
-- Find contradicting claims:
-- Same subject entity, same claim type, opposite polarity, within 90 days
SELECT c.claim_id
FROM claims c
WHERE
  -- Match on subject (the thing being claimed about)
  c.subject_entity_id = $subject_entity_id
  AND c.subject_entity_id IS NOT NULL
  -- Same claim type (compare like with like)
  AND c.claim_type = $claim_type
  -- Opposite polarity only
  AND c.polarity != $polarity
  -- Do not compare neutral claims (neutral does not contradict positive or negative)
  AND c.polarity != 'neutral'
  AND $polarity != 'neutral'
  -- Rolling 90-day window
  AND c.created_at > NOW() - INTERVAL '90 days'
  -- Do not self-contradict
  AND c.claim_id != $current_claim_id
```

**Updated index on `claims`** (replaces the incorrect index from base PRD Section 4.5):

```sql
-- Drop old index
DROP INDEX IF EXISTS idx_claims_type_polarity;

-- New index serves the corrected contradiction query
CREATE INDEX idx_claims_contradiction
  ON claims (subject_entity_id, claim_type, polarity, created_at DESC)
  WHERE subject_entity_id IS NOT NULL AND polarity != 'neutral';
```

**Contradiction type classification** (replaces the vague `contradiction_type` field):

| `contradiction_type` | Definition |
|---------------------|------------|
| `guidance_conflict` | Both claims are `forward_guidance`, same subject, opposite polarity within 7 days |
| `factual_conflict` | Both claims are `factual`, same subject, opposite polarity |
| `projection_conflict` | Both claims are `projection`, same subject, opposite polarity within 30 days |
| `retraction` | A `denial` claim directly follows a `factual` or `forward_guidance` claim by the same claimer about the same subject |

---

### A.3 — Outbox Dispatcher Specification

The outbox pattern is referenced in S4 (and S1) but the dispatcher component — the process that reads `outbox_events WHERE status = 'pending'` and produces messages to Kafka — was never specified.

**Dispatcher design.** The outbox dispatcher runs as a background thread within the same service process (not a sidecar). It shares the service's database connection pool. Running it in-process ensures that if the service crashes, the dispatcher crashes with it and messages are not double-sent.

**Algorithm:**

```python
class OutboxDispatcher:
    POLL_INTERVAL_SECONDS = 2        # env: OUTBOX_POLL_INTERVAL_SECONDS
    BATCH_SIZE = 100                 # env: OUTBOX_BATCH_SIZE
    MAX_RETRY_ATTEMPTS = 5
    KAFKA_UNAVAILABLE_BACKOFF = [5, 15, 30, 60, 120]  # seconds, exponential

    async def run(self):
        while True:
            try:
                await self._dispatch_batch()
            except KafkaUnavailableError as e:
                attempt = self._consecutive_kafka_failures
                backoff = self.KAFKA_UNAVAILABLE_BACKOFF[
                    min(attempt, len(self.KAFKA_UNAVAILABLE_BACKOFF) - 1)
                ]
                log.warning("kafka_unavailable", backoff_seconds=backoff)
                await asyncio.sleep(backoff)
                self._consecutive_kafka_failures += 1
                continue
            self._consecutive_kafka_failures = 0
            await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

    async def _dispatch_batch(self):
        # SELECT ... FOR UPDATE SKIP LOCKED: prevents two dispatcher instances
        # from processing the same row if ever run with two replicas
        rows = await db.fetch("""
            SELECT outbox_id, event_type, aggregate_id, payload_json
            FROM outbox_events
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT $1
            FOR UPDATE SKIP LOCKED
        """, self.BATCH_SIZE)

        if not rows:
            return

        produced_ids = []
        for row in rows:
            try:
                kafka_producer.produce(
                    topic=row.event_type,
                    key=row.aggregate_id,
                    value=row.payload_json
                )
                produced_ids.append(row.outbox_id)
            except KafkaException as e:
                log.error("outbox_produce_failed", outbox_id=row.outbox_id, error=str(e))
                await self._increment_retry(row.outbox_id)

        # Flush ensures delivery before marking as dispatched
        kafka_producer.flush(timeout=10)

        if produced_ids:
            await db.execute("""
                UPDATE outbox_events
                SET status = 'dispatched', dispatched_at = NOW()
                WHERE outbox_id = ANY($1)
            """, produced_ids)

    async def _increment_retry(self, outbox_id: str):
        await db.execute("""
            UPDATE outbox_events
            SET retry_count = retry_count + 1,
                status = CASE WHEN retry_count + 1 >= $2 THEN 'failed' ELSE 'pending' END
            WHERE outbox_id = $1
        """, outbox_id, self.MAX_RETRY_ATTEMPTS)
```

**Kafka unavailability.** If Kafka is unavailable for the entire poll cycle, the dispatcher backs off exponentially (capped at 120 seconds). Messages remain in `outbox_events` with `status = 'pending'`. PostgreSQL is the durable store; no messages are lost. When Kafka recovers, the dispatcher resumes from where it left off.

**Failed messages.** After `MAX_RETRY_ATTEMPTS` (5), `outbox_events.status` is set to `'failed'`. Failed outbox entries are written to the `dead_letter_queue` table by a separate cleanup job that runs hourly:

```sql
INSERT INTO dead_letter_queue
  (source_service, pipeline_block, kafka_topic, failure_reason, payload_json)
SELECT
  'content-ingestion', 'outbox_dispatcher', event_type, 'max_retries_exceeded', payload_json
FROM outbox_events
WHERE status = 'failed' AND created_at > NOW() - INTERVAL '24 hours';
```

**Startup ordering.** The dispatcher thread starts only after the Kafka producer has successfully connected (verified by a synchronous metadata request on startup). If the producer cannot connect within 30 seconds on startup, the service fails its readiness check and does not start dispatching.

---

### A.4 — Kafka Topic Creation Script

Because `KAFKA_AUTO_CREATE_TOPICS_ENABLE: 'false'`, all topics must be created before any service starts. The creation script lives at `infra/kafka/create-topics.sh` and is run by a Docker Compose init container.

```bash
#!/bin/bash
# infra/kafka/create-topics.sh
# Run once after broker is ready. Idempotent (--if-not-exists).

set -e
BOOTSTRAP="kafka:9092"
KAFKA_BIN="/usr/bin/kafka-topics"

wait_for_kafka() {
  echo "Waiting for Kafka broker..."
  until $KAFKA_BIN --bootstrap-server $BOOTSTRAP --list > /dev/null 2>&1; do
    sleep 2
  done
  echo "Kafka ready."
}

create_topic() {
  local name=$1 partitions=$2 retention_ms=$3 replication=$4
  $KAFKA_BIN --bootstrap-server $BOOTSTRAP \
    --create --if-not-exists \
    --topic "$name" \
    --partitions "$partitions" \
    --replication-factor "$replication" \
    --config "retention.ms=$retention_ms" \
    --config "cleanup.policy=delete" \
    --config "min.insync.replicas=1"
  echo "Topic created (or already exists): $name"
}

wait_for_kafka

# retention.ms: 3d=259200000, 7d=604800000, 14d=1209600000, 30d=2592000000

create_topic "content.article.raw.v1"            3  259200000  1
create_topic "content.article.stored.v1"         6  604800000  1
create_topic "nlp.article.enriched.v1"           6  1209600000 1
create_topic "nlp.signal.detected.v1"            3  604800000  1
create_topic "graph.state.changed.v1"            6  604800000  1
create_topic "intelligence.contradiction.v1"     3  1209600000 1
create_topic "relation.type.proposed.v1"         1  2592000000 1
create_topic "alert.delivered.v1"                3  2592000000 1
create_topic "portfolio.watchlist.updated.v1"    3  604800000  1

echo "All topics created."
```

**Docker Compose init container** (add to `docker-compose.yml`):

```yaml
  kafka-init:
    image: confluentinc/cp-kafka:7.6.0
    depends_on:
      kafka:
        condition: service_healthy
    volumes:
      - ./infra/kafka/create-topics.sh:/create-topics.sh
    command: ["/bin/bash", "/create-topics.sh"]
    restart: "no"
```

**Kafka healthcheck** (add to the `kafka` service in Docker Compose):

```yaml
  kafka:
    # ... existing config ...
    healthcheck:
      test: ["CMD", "kafka-topics", "--bootstrap-server", "localhost:9092", "--list"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
```

---

### A.5 — Schema Migration Ownership for `intelligence_db`

**Problem.** Both S6 (NLP Pipeline) and S7 (Knowledge Graph) write to `intelligence_db`. With no stated owner, both services will attempt to run Alembic migrations against the same database on startup, causing migration conflicts and duplicate migration history entries.

**Resolution: a dedicated `intelligence-migrations` init container owns all DDL for `intelligence_db`.**

```
services/
  intelligence-migrations/      ← new, thin service: only runs Alembic
    alembic.ini
    migrations/
      versions/
        001_initial_schema.py
        002_add_subject_entity_id_to_claims.py
        ...
    Dockerfile
```

```yaml
# docker-compose.yml addition
  intelligence-migrations:
    build: ./services/intelligence-migrations
    environment:
      DATABASE_URL: postgresql://user:pass@pgbouncer:6432/intelligence_db
    depends_on:
      postgres-primary:
        condition: service_healthy
    command: ["alembic", "upgrade", "head"]
    restart: "no"
```

S6 and S7 depend on `intelligence-migrations` completing (via `condition: service_completed_successfully`) before they start:

```yaml
  s6-nlp-pipeline:
    depends_on:
      intelligence-migrations:
        condition: service_completed_successfully
      # ... other deps ...

  s7-knowledge-graph:
    depends_on:
      intelligence-migrations:
        condition: service_completed_successfully
      # ... other deps ...
```

**Rule.** S6 and S7 are configured with `ALEMBIC_ENABLED=false`. They never run migrations themselves. They connect to `intelligence_db` but do not touch `alembic_version`. If a developer adds a new table to `intelligence_db`, the migration file goes in `services/intelligence-migrations/migrations/versions/` and is reviewed independently of either service's code changes.

**Migration ownership table:**

| Database | Migration owner | Framework |
|----------|----------------|-----------|
| `content_ingestion_db` | S4 Content Ingestion | Alembic (runs on startup) |
| `content_store_db` | S5 Content Store | Alembic (runs on startup) |
| `nlp_db` | S6 NLP Pipeline | Alembic (runs on startup) |
| `intelligence_db` | `intelligence-migrations` init container | Alembic (runs once, then exits) |
| `alert_db` | S10 Alert Service | Alembic (runs on startup) |

---

## B. Significant Fixes

### B.1 — MinHash Entity Linkage: Block 8 Implementability Fix

**Problem.** Block 8 (Novelty Scoring) queries `minhash_signatures` for documents mentioning the same entity, but `minhash_signatures` has no entity_id column and no entity linkage whatsoever.

**Fix: add `minhash_entity_mentions` junction table.**

```sql
CREATE TABLE minhash_entity_mentions (
  sig_id   UUID NOT NULL REFERENCES minhash_signatures(sig_id) ON DELETE CASCADE,
  entity_id UUID NOT NULL,
  PRIMARY KEY (sig_id, entity_id)
);

CREATE INDEX idx_minhash_entity_mentions_entity
  ON minhash_entity_mentions (entity_id, sig_id);
```

**Population.** After deduplication (Block 2, S5), S5 writes the MinHash signature and simultaneously inserts rows into `minhash_entity_mentions` for each resolved entity ID in the document's `entity_mentions` table. At Block 2 time, entity resolution has not run yet (it runs in Block 9). Therefore, S5 uses **pre-resolution entity linkage**: it performs a fast alias lookup against `entity_aliases` for the mention surface forms detected by GLiNER in the same pipeline tick. Only high-confidence alias matches (exact match only, not fuzzy) are used for MinHash entity linkage. This is acceptable because the novelty check is a best-effort suppression, not a hard correctness gate.

**Updated Block 8 novelty query** (replaces the original):

```python
async def compute_novelty(doc_id: str, resolved_entity_ids: list[str]) -> NoveltDecision:
    if not resolved_entity_ids:
        return NoveltyDecision(tier='high', reason='no_entities')

    low_novelty_entities = []

    for entity_id in resolved_entity_ids:
        # Find signatures for documents mentioning this entity in last 48 hours
        candidates = await db.fetch("""
            SELECT ms.sig_id, ms.signature_bytes, ms.doc_id as candidate_doc_id
            FROM minhash_signatures ms
            JOIN minhash_entity_mentions mem ON mem.sig_id = ms.sig_id
            JOIN routing_decisions rd ON rd.doc_id = ms.doc_id
            WHERE mem.entity_id = $1
              AND ms.created_at > NOW() - INTERVAL '48 hours'
              AND ms.doc_id != $2
              AND rd.final_routing_tier IN ('medium', 'deep')
            LIMIT 50
        """, entity_id, doc_id)

        current_sig = await db.fetchval(
            "SELECT signature_bytes FROM minhash_signatures WHERE doc_id = $1", doc_id
        )

        for candidate in candidates:
            jaccard = compute_jaccard(current_sig, candidate.signature_bytes)
            if jaccard >= NOVELTY_JACCARD_THRESHOLD:  # env: 0.60
                low_novelty_entities.append(entity_id)
                break

    if len(low_novelty_entities) == len(resolved_entity_ids):
        return NoveltyDecision(tier='low', reason='all_entities_covered')

    return NoveltyDecision(tier='high', reason='new_entities_or_content')
```

---

### B.2 — S1 Portfolio Internal API Contract

S10 depends on two S1 endpoints that were referenced but never defined. These are internal APIs (not exposed through the API Gateway to external clients).

**Endpoint 1: Get users watching a single entity**

```
GET /internal/v1/watchlists/by-entity/{entity_id}
Authorization: Internal-Service-Token {INTERNAL_SERVICE_TOKEN}
```

Response `200 OK`:
```json
{
  "entity_id": "string (UUID)",
  "user_ids": ["string (UUID)"],
  "cached_at": "string (ISO 8601)"
}
```

Response `404 Not Found` (entity_id not known to portfolio service):
```json
{"error": {"code": "ENTITY_NOT_FOUND", "status": 404, "message": "Entity not found in watchlist registry"}}
```

---

**Endpoint 2: Batch get users watching multiple entities**

```
POST /internal/v1/watchlists/by-entities
Authorization: Internal-Service-Token {INTERNAL_SERVICE_TOKEN}
Content-Type: application/json
```

Request body:
```json
{
  "entity_ids": ["string (UUID)"],
  "max_entity_ids": 500
}
```

Response `200 OK`:
```json
{
  "results": {
    "{entity_id_1}": ["user_id_a", "user_id_b"],
    "{entity_id_2}": ["user_id_c"],
    "{entity_id_3}": []
  },
  "unknown_entity_ids": ["string (UUID)"]
}
```

`unknown_entity_ids` contains entity IDs that are not referenced by any watchlist in the portfolio service. S10 treats unknown entities as having zero watchers (empty array) — it does not fail.

**Authentication.** Both endpoints require the `INTERNAL_SERVICE_TOKEN` header. This shared secret is injected via environment variable `INTERNAL_SERVICE_TOKEN` on both S1 and S10. It is never exposed through the API Gateway.

**S1 implementation obligation.** S1 must implement both endpoints and maintain a denormalised `watchlist_entity_index` table:

```sql
-- In portfolio_db
CREATE TABLE watchlist_entity_index (
  user_id   UUID NOT NULL,
  entity_id UUID NOT NULL,  -- intelligence_db entity_id (no FK, cross-DB)
  watchlist_id UUID NOT NULL,
  added_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, entity_id)
);

CREATE INDEX idx_watchlist_entity_by_entity
  ON watchlist_entity_index (entity_id);
```

This index allows `GET /by-entity/{entity_id}` to resolve in O(log N) without scanning full watchlist records.

---

### B.3 — Missing `valid_to IS NULL` Partial Index on `relations`

**Problem.** Queries filtering for currently-valid relations (`WHERE valid_to IS NULL OR valid_to > CURRENT_DATE`) are extremely common (graph traversal, exposure scoring, dossier assembly) and are unindexed.

**Fix:** Add two partial indexes:

```sql
-- Most common traversal pattern: active relations starting from a subject entity
CREATE INDEX idx_relations_active_subject
  ON relations (subject_entity_id, canonical_type, status, current_confidence DESC)
  WHERE valid_to IS NULL AND status IN ('active', 'confirmed');

-- Reverse traversal: active relations ending at an object entity
CREATE INDEX idx_relations_active_object
  ON relations (object_entity_id, canonical_type, status, current_confidence DESC)
  WHERE valid_to IS NULL AND status IN ('active', 'confirmed');
```

These replace the base PRD's general traversal indexes for the hot path. The original full-table indexes (without `WHERE valid_to IS NULL`) are still needed for historical queries (e.g. "what relations existed on 2024-01-01?") and should be retained.

---

### B.4 — Claims Contradiction Index Fix

**Problem.** The base PRD defines `idx_claims_type_polarity` on `(claim_type, polarity, created_at DESC)`, but the corrected contradiction query (see A.2) filters by `subject_entity_id`. This index does not serve the query.

**Fix:** Drop the old index, add the correct one (already specified in A.2 above, consolidated here for clarity):

```sql
-- Remove old, non-serving index
DROP INDEX IF EXISTS idx_claims_type_polarity;

-- Serves contradiction detection: filter by subject + type + polarity + recency
CREATE INDEX idx_claims_contradiction_detection
  ON claims (subject_entity_id, claim_type, polarity, created_at DESC)
  WHERE subject_entity_id IS NOT NULL AND polarity != 'neutral';

-- Separate index for claimer-based queries (who has made claims recently)
CREATE INDEX idx_claims_by_claimer
  ON claims (claimer_entity_id, claim_type, created_at DESC)
  WHERE claimer_entity_id IS NOT NULL;
```

---

### B.5 — `build_context_text` Specification

This function is called in Block 9 (entity resolution) for every entity mention that reaches the ANN embedding step (Step 4 of the cascade). It must be fully specified because it runs on the hot ingestion path.

```python
def build_context_text(
    mention: EntityMention,
    all_sentences: list[str],   # All sentences in the document, 0-indexed
    max_total_tokens: int = 128  # Keep context window small; this is for disambiguation
) -> str:
    """
    Build a short context string for embedding-based entity disambiguation.

    Strategy:
    - Use the mention's own sentence as the core.
    - Prepend one sentence before and append one sentence after if available
      and if the total token estimate stays under max_total_tokens.
    - If the mention is in the first sentence (index 0): use sentences 0, 1.
    - If the mention is in the last sentence: use sentences [-2, -1].
    - For transcripts: include the speaker label prefix.
    - Prepend the document title if available (adds entity type context).
    """

    idx = mention.sentence_index

    # Guard against missing sentence index
    if idx is None or not all_sentences:
        return mention.surface_form

    sentences = []

    # Before context (one sentence)
    if idx > 0:
        sentences.append(all_sentences[idx - 1])

    # Core sentence (always included)
    sentences.append(all_sentences[idx])

    # After context (one sentence)
    if idx < len(all_sentences) - 1:
        sentences.append(all_sentences[idx + 1])

    context = " ".join(sentences)

    # Token budget check (rough: 4 chars ≈ 1 token)
    if len(context) / 4 > max_total_tokens:
        # Fall back to mention sentence only
        context = all_sentences[idx]

    # Prepend entity type hint for better embedding alignment
    type_hint = f"[{mention.entity_type.upper()}] "
    return type_hint + context
```

**Section boundary handling.** If `mention.section_id` differs from `all_sentences[idx-1]`'s section, the sentence before belongs to a different section. In this case, do not include the cross-section sentence. This is enforced by checking:

```python
if idx > 0 and sentence_section_map[idx - 1] == mention.section_id:
    sentences.append(all_sentences[idx - 1])
```

`sentence_section_map` is built during sectioning by assigning each sentence its parent `section_id`. This map is stored in memory for the duration of the document's pipeline execution; it is not persisted to the database.

---

### B.6 — Entity Refresh LLM Prompt Specification

Block 13 (Embedding Refresh Scheduler) references "summary text via Qwen2.5-7B-Instruct with fixed prompt" without defining the prompt. Two prompts are needed: one for static profile refresh and one for recent-signal summary.

**Prompt A — Static Profile (runs when `reason = 'metadata_changed'`):**

```
SYSTEM: You are a financial entity profiling engine. Generate a concise, factual profile for the given entity. Output ONLY the profile text — no preamble, no JSON, no formatting.

ENTITY TYPE: {entity_type}
CANONICAL NAME: {canonical_name}
KNOWN ALIASES: {comma_separated_aliases}
DESCRIPTION (if available): {existing_description_text or "None"}

Write a 2–3 sentence factual profile of this entity for use in a financial intelligence system.
Focus on: what the entity does, its primary market or geographic exposure, and its key relationships.
Do not speculate. Do not include financial metrics. Do not use hedging language.
Maximum 150 words.
```

**Example output for TSMC:**
> Taiwan Semiconductor Manufacturing Company (TSMC) is the world's largest dedicated independent semiconductor foundry, manufacturing chips designed by fabless customers including Apple, NVIDIA, AMD, and Qualcomm. The company operates primarily in Taiwan with expanding facilities in Japan, Arizona, and Germany. TSMC is the sole manufacturer of leading-edge process nodes including N3 and N2, making it a critical node in the global semiconductor supply chain.

**Prompt B — Recent Signal Summary (runs every 30 minutes for dirty entities):**

```
SYSTEM: You are a financial intelligence analyst. Summarise recent developments for the given entity based on the evidence provided. Output ONLY the summary text — no preamble, no JSON.

ENTITY: {canonical_name} ({entity_type})

RECENT EVIDENCE (last 30 days, sorted by date descending):
{for each evidence item: "[{date}] [{source_type}] {evidence_text}"}

Write a 3–5 sentence summary of the most significant recent developments for this entity.
Focus on: events that affect valuation, supply chain, regulatory status, or strategic direction.
Do not repeat information already implied by earlier items.
If there are no significant developments, write: "No significant recent developments."
Maximum 200 words.
```

**Template versioning.** Both prompts are stored as versioned files at `services/knowledge-graph/prompts/entity_profile_v{N}.txt` and `entity_signal_v{N}.txt`. The version number is recorded in `entity_embeddings.embedding_version` alongside the model version. When either the prompt template or the model changes, the version is incremented and all entity embeddings are queued for refresh via `entity_dirty_log`.

---

### B.7 — Source Trust Weight Table

**Problem.** Source trust weights are hardcoded in the confidence formula and in Block 5 scoring. If a source is found to be unreliable (e.g. a NewsAPI source consistently produces inaccurate claims), there is no mechanism to update historical confidence scores because the weight mapping has no durable home.

**Fix: add `source_trust_weights` table to `intelligence_db`.**

```sql
CREATE TABLE source_trust_weights (
  weight_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type       TEXT NOT NULL,     -- matches documents.source_type
  source_name       TEXT,              -- NULL = applies to all sources of this type
  trust_weight      DOUBLE PRECISION NOT NULL CHECK (trust_weight > 0 AND trust_weight <= 2.0),
  is_active         BOOLEAN NOT NULL DEFAULT true,
  effective_from    DATE NOT NULL,
  effective_to      DATE,              -- NULL = currently active
  change_reason     TEXT,
  created_by        TEXT NOT NULL DEFAULT 'system_seed',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_source_trust_weights_lookup
  ON source_trust_weights (source_type, source_name, effective_from DESC)
  WHERE is_active = true;
```

**Seed data:**

```sql
INSERT INTO source_trust_weights (source_type, source_name, trust_weight, effective_from, change_reason, created_by) VALUES
  ('sec_filing',          NULL,       1.4, '2026-01-01', 'Initial seed: authoritative regulatory source', 'system'),
  ('finnhub_transcript',  NULL,       1.3, '2026-01-01', 'Initial seed: primary source management statements', 'system'),
  ('finnhub_news',        NULL,       1.1, '2026-01-01', 'Initial seed: curated financial news', 'system'),
  ('eodhd',               NULL,       1.0, '2026-01-01', 'Initial seed: baseline market data provider', 'system'),
  ('newsapi',             NULL,       0.9, '2026-01-01', 'Initial seed: broad news aggregator, lower precision', 'system');
```

**Weight lookup at extraction time.** When S6 writes `relation_evidence.source_weight`, it queries the active weight:

```python
def get_source_weight(source_type: str, source_name: str) -> float:
    # Check specific source_name first, then type-level fallback
    result = db.fetchval("""
        SELECT trust_weight FROM source_trust_weights
        WHERE source_type = $1
          AND (source_name = $2 OR source_name IS NULL)
          AND is_active = true
          AND effective_from <= CURRENT_DATE
          AND (effective_to IS NULL OR effective_to > CURRENT_DATE)
        ORDER BY source_name NULLS LAST, effective_from DESC
        LIMIT 1
    """, source_type, source_name)
    return result or 1.0  # Fallback to neutral weight if not found
```

**Recomputation on weight change.** When a weight changes, the confidence batch job needs to recompute affected relations. Insert all affected `relation_id`s into `entity_dirty_log` (via their entity IDs) on weight update:

```sql
-- After updating source_trust_weights, flag affected relations for recompute
-- by inserting their entities into dirty log
INSERT INTO entity_dirty_log (entity_id, reason, source_doc_id)
SELECT DISTINCT r.subject_entity_id, 'source_weight_changed', NULL
FROM relations r
JOIN relation_evidence re ON re.relation_id = r.relation_id
JOIN documents d ON d.doc_id = re.doc_id
WHERE d.source_type = $updated_source_type
ON CONFLICT DO NOTHING;
```

---

## C. Moderate Fixes

### C.1 — Health Check and Readiness Endpoints

Every service must expose two endpoints:

| Path | Method | Purpose |
|------|--------|---------|
| `GET /health` | GET | Liveness: is the process alive? |
| `GET /ready` | GET | Readiness: is the service ready to handle requests? |

**Liveness check (`/health`).** Returns `200 OK` with `{"status": "ok"}` as long as the process is running. No dependency checks. Used by Docker/Kubernetes to decide whether to restart the container.

**Readiness check (`/ready`).** Returns `200 OK` only when all critical dependencies are available. Returns `503 Service Unavailable` with a reason when not ready. Used by load balancers and Docker Compose `condition: service_healthy`.

**Readiness conditions per service:**

| Service | Ready when |
|---------|------------|
| S4 Content Ingestion | PostgreSQL `content_ingestion_db` is reachable AND Kafka producer has connected AND MinIO is reachable |
| S5 Content Store | PostgreSQL `content_store_db` is reachable AND Kafka consumer group has received partition assignment |
| S6 NLP Pipeline | PostgreSQL `nlp_db` AND `intelligence_db` reachable AND Kafka consumer partition assigned AND Ollama `/api/tags` responds with `bge-large-en-v1.5` in model list |
| S7 Knowledge Graph | PostgreSQL `intelligence_db` reachable AND Kafka consumer partition assigned |
| S10 Alert Service | PostgreSQL `alert_db` reachable AND Kafka consumer partitions assigned AND Valkey PING returns PONG AND S1 `/health` returns 200 |

**Implementation pattern** (same for all FastAPI services):

```python
@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

@app.get("/ready")
async def ready():
    checks = {}
    ok = True

    # Database check
    try:
        await db.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        ok = False

    # Kafka consumer check (S5, S6, S7, S10 only)
    if hasattr(app.state, "kafka_consumer"):
        assignment = app.state.kafka_consumer.assignment()
        if assignment:
            checks["kafka_consumer"] = f"ok ({len(assignment)} partitions)"
        else:
            checks["kafka_consumer"] = "waiting_for_assignment"
            ok = False

    # Ollama check (S6 only)
    if settings.SERVICE_NAME == "nlp-pipeline":
        try:
            resp = await http_client.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3.0)
            models = [m["name"] for m in resp.json().get("models", [])]
            if settings.EMBEDDING_MODEL in models:
                checks["ollama"] = "ok"
            else:
                checks["ollama"] = f"model_not_loaded: {settings.EMBEDDING_MODEL}"
                ok = False
        except Exception as e:
            checks["ollama"] = f"error: {e}"
            ok = False

    status_code = 200 if ok else 503
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=status_code)
```

**Docker Compose healthcheck block** (add to every service):

```yaml
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:{PORT}/ready"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 30s
```

---

### C.2 — Prometheus Metrics Catalogue

All Prometheus metrics used across the pipeline, consolidated. Metric names follow the convention `{service_prefix}_{component}_{measurement}_{unit}`.

**S4 · Content Ingestion**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `s4_adapter_fetch_total` | Counter | `source_name`, `status` (success\|error) | Total article fetch attempts per adapter |
| `s4_adapter_quota_remaining` | Gauge | `source_name` | Remaining daily quota (where applicable) |
| `s4_outbox_pending_total` | Gauge | — | Rows in outbox with status='pending' |
| `s4_outbox_dispatch_latency_seconds` | Histogram | `event_type` | Time from outbox write to Kafka produce |
| `s4_adapter_rate_limit_hits_total` | Counter | `source_name` | Times rate limit was hit |

**S5 · Content Store**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `s5_dedup_decisions_total` | Counter | `decision` (canonical\|duplicate_exact\|duplicate_near\|suppressed) | Deduplication outcome |
| `s5_minhash_compute_duration_seconds` | Histogram | — | Time to compute MinHash signature |
| `s5_consumer_lag` | Gauge | `topic`, `partition` | Kafka consumer lag in messages |
| `s5_documents_processed_total` | Counter | `source_type` | Total canonical documents stored |

**S6 · NLP Pipeline**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `s6_gliner_inference_duration_seconds` | Histogram | — | Per-batch GLiNER inference time |
| `s6_gliner_skip_section_total` | Counter | `reason` (oom\|empty) | Sections skipped by GLiNER |
| `s6_routing_tier_total` | Counter | `tier` (suppress\|light\|medium\|deep) | Routing decisions by tier |
| `s6_embedding_batch_duration_seconds` | Histogram | `model` | Per-batch embedding time |
| `s6_embedding_pending_total` | Gauge | — | Chunks awaiting embedding (catch-up queue) |
| `s6_novelty_check_skipped_total` | Counter | `reason` | Novelty checks skipped |
| `s6_novelty_tier_total` | Counter | `tier` (high\|low) | Novelty decisions |
| `s6_entity_resolution_decisions_total` | Counter | `method`, `decision` | Resolution outcomes by method |
| `s6_provisional_queue_depth` | Gauge | — | Rows in provisional_entity_queue with status='pending' |
| `s6_extraction_parse_failure_total` | Counter | — | JSON parse failures from LLM |
| `s6_extraction_duration_seconds` | Histogram | `source_type` | Per-document LLM extraction time |
| `s6_extraction_window_count` | Histogram | — | Windows per document |
| `s6_consumer_lag` | Gauge | `topic`, `partition` | Kafka consumer lag |
| `s6_ollama_queue_depth` | Gauge | `model` | Estimated in-flight Ollama requests |

**S7 · Knowledge Graph**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `s7_graph_upsert_duration_seconds` | Histogram | `object_type` (relation\|event\|claim) | Per-object graph write time |
| `s7_contradiction_links_created_total` | Counter | `contradiction_type` | New contradiction links created |
| `s7_confidence_batch_duration_seconds` | Histogram | — | Total confidence batch job duration |
| `s7_confidence_batch_relations_processed` | Gauge | — | Relations processed in last batch run |
| `s7_relation_status_counts` | Gauge | `status` | Count of relations per status |
| `s7_type_proposals_pending_total` | Gauge | — | Unreviewed relation type proposals |
| `s7_entity_refresh_duration_seconds` | Histogram | `refresh_type` (profile\|signal) | Per-entity refresh time |
| `s7_embedding_migration_coverage_pct` | Gauge | `migration_id` | Shadow column backfill coverage |
| `s7_consumer_lag` | Gauge | `topic`, `partition` | Kafka consumer lag |

**S10 · Alert Service**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `s10_alerts_delivered_total` | Counter | `alert_type`, `channel` (websocket\|pending_queue) | Alerts delivered |
| `s10_alerts_deduplicated_total` | Counter | `alert_type` | Alerts suppressed by dedup window |
| `s10_websocket_connections_active` | Gauge | — | Active WebSocket connections |
| `s10_pending_alerts_depth` | Gauge | — | Undelivered pending alerts |
| `s10_watchlist_cache_hits_total` | Counter | — | Watchlist cache hits |
| `s10_watchlist_cache_misses_total` | Counter | — | Watchlist cache misses (triggered S1 API call) |
| `s10_s1_api_duration_seconds` | Histogram | `endpoint` | S1 Portfolio API call latency |
| `s10_fan_out_batch_size` | Histogram | — | Entities per fan-out batch |

**Alerting thresholds** (Prometheus Alertmanager rules):

```yaml
groups:
  - name: worldview_intelligence
    rules:
      - alert: KafkaConsumerLagHigh
        expr: s6_consumer_lag > 5000
        for: 5m
        labels: {severity: warning}
        annotations: {summary: "NLP pipeline consumer lag > 5000 messages"}

      - alert: OllamaQueueSaturated
        expr: s6_ollama_queue_depth > 20
        for: 2m
        labels: {severity: warning}
        annotations: {summary: "Ollama queue depth high — consider pausing consumer"}

      - alert: EmbeddingMigrationStalled
        expr: delta(s7_embedding_migration_coverage_pct[30m]) == 0
               AND s7_embedding_migration_coverage_pct < 95
        for: 30m
        labels: {severity: warning}
        annotations: {summary: "Embedding migration backfill not progressing"}

      - alert: ProvisionalQueueOverflow
        expr: s6_provisional_queue_depth > 500
        for: 10m
        labels: {severity: warning}
        annotations: {summary: "Provisional entity queue backing up — check enrichment rate limit"}

      - alert: DLQDepthNonZero
        expr: increase(s4_adapter_fetch_total{status="error"}[1h]) > 50
        for: 0m
        labels: {severity: warning}
        annotations: {summary: "High adapter error rate — check API keys and rate limits"}
```

---

### C.3 — Relation Type Prompt Construction Strategy

**Problem.** At 20+ canonical types, the relation type section of the LLM extraction prompt can exceed 1,000 tokens before any document text is added. The context budget for the extraction window is 6,000 tokens of document text; the full prompt overhead (metadata + entity list + relation types + instructions + schema) must stay under 8,000 tokens, leaving approximately 2,000 tokens for non-document prompt content.

**Strategy: two-tier relation list in the prompt.**

**Tier 1 — Always included (compact form):** All `is_active = true` AND `is_extractable = true` types. Listed as `canonical_type: short_description` pairs only (no example strings). Approximately 20 types × 8 tokens average = ~160 tokens. This is always safe.

**Tier 2 — Example strings (selective):** Include example strings only for the 8 highest-priority types (those with `corroboration_tier = 1` and `decay_class IN ('slow', 'permanent')`). These are the types where extraction precision matters most. For lower-priority types, the model relies on the short description alone.

**Prompt section template:**

```
CANONICAL RELATION TYPES — use ONLY these type names in the "raw_relation_type" field:

CORE TYPES (include example surface strings):
- supplier_of: Subject supplies components or services to object.
  Examples: "supplies to", "is a supplier to", "provides X to", "manufactures for"
- customer_of: Subject is a buyer from object.
  Examples: "buys from", "sources from", "purchases from"
- owns: Subject has ownership stake in object.
  Examples: "owns", "acquired", "holds stake in", "parent company of"
[... 5 more core types with examples ...]

OTHER TYPES (use by description only):
- competitor_of: Direct market competition between subject and object.
- partnered_with: Formal business partnership.
- operates_in: Subject has operations or revenue in location object.
- regulated_by: Subject is regulated by government body object.
[... remaining types ...]

If none of these types fit, use your best match and set "proposed_new_relation": true.
Do NOT use "exposed_to" — this is computed, not extracted.
```

**Token budget enforcement.** Before building the prompt, the prompt construction function computes the estimated token count of the relation type section:

```python
def build_relation_type_prompt_section(registry: list[RelationType]) -> str:
    CORE_TYPE_LIMIT = 8
    MAX_RELATION_SECTION_TOKENS = 600

    core_types = [t for t in registry
                  if t.is_extractable and t.is_active
                  and t.corroboration_tier == 1
                  and t.decay_class in ('slow', 'permanent')][:CORE_TYPE_LIMIT]

    other_types = [t for t in registry
                   if t.is_extractable and t.is_active
                   and t not in core_types]

    lines = ["CANONICAL RELATION TYPES:\n", "CORE TYPES:"]
    for t in core_types:
        examples = ", ".join(f'"{s}"' for s in t.example_strings[:4])
        lines.append(f"- {t.canonical_type}: {t.description}")
        if examples:
            lines.append(f"  Examples: {examples}")

    lines.append("\nOTHER TYPES:")
    for t in other_types:
        lines.append(f"- {t.canonical_type}: {t.description}")

    section = "\n".join(lines)

    # Hard truncation if still too long (rare, only if registry grows large)
    estimated_tokens = len(section) // 4
    if estimated_tokens > MAX_RELATION_SECTION_TOKENS:
        log.warning("relation_section_truncated",
                    estimated_tokens=estimated_tokens,
                    limit=MAX_RELATION_SECTION_TOKENS)
        # Include only canonical_type names without descriptions as fallback
        section = "CANONICAL RELATION TYPES: " + ", ".join(
            t.canonical_type for t in registry if t.is_extractable and t.is_active
        )

    return section
```

---

### C.4 — Data Retention and Partition Drop Schedule

**Policy table:**

| Table | Partitioned | Partition Key | Partition Unit | Drop After | Archive Before Drop |
|-------|-------------|--------------|----------------|------------|---------------------|
| `events` | YES | `created_at` | Monthly | 24 months | No (relation_evidence contains provenance) |
| `claims` | YES | `created_at` | Monthly | 24 months | No |
| `entity_mentions` | NO | — | — | 12 months (DELETE) | No |
| `relation_evidence` | NO | — | — | Never | Retain permanently — provenance anchor |
| `chunk_embeddings` | NO | — | — | Never (unless doc deleted) | — |
| `routing_decisions` | NO | — | — | 6 months (DELETE) | No |
| `minhash_signatures` | NO | — | — | 60 days (DELETE) | No |
| `minhash_entity_mentions` | NO | — | — | 60 days (DELETE, cascade) | No |
| `entity_dirty_log` | NO | — | — | 7 days post-processed (DELETE) | No |
| `dead_letter_queue` | NO | — | — | 90 days (DELETE) | No |
| `outbox_events (dispatched)` | NO | — | — | 7 days (DELETE) | No |
| `pending_alerts (delivered)` | NO | — | — | 30 days (DELETE) | No |
| `eval.run_results` | NO | — | — | Never | Retain for trend analysis |

**Partition creation and drop procedure for `events` and `claims`:**

```sql
-- Partition creation (run monthly via APScheduler job in S7, first day of month)
CREATE TABLE IF NOT EXISTS events_2026_04
  PARTITION OF events
  FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

-- Partition drop (run monthly, 24 months after partition end date)
DROP TABLE IF EXISTS events_2024_03;  -- dropped in 2026-04
```

**Cleanup jobs** (APScheduler in S7, daily at 03:00 UTC):

```python
async def run_retention_cleanup():
    cutoff_routing = datetime.now() - timedelta(days=180)
    cutoff_minhash = datetime.now() - timedelta(days=60)
    cutoff_entity_mentions = datetime.now() - timedelta(days=365)
    cutoff_dirty_log = datetime.now() - timedelta(days=7)
    cutoff_dlq = datetime.now() - timedelta(days=90)
    cutoff_outbox = datetime.now() - timedelta(days=7)

    await db.execute("DELETE FROM routing_decisions WHERE created_at < $1", cutoff_routing)
    await db.execute("DELETE FROM minhash_entity_mentions mem USING minhash_signatures ms WHERE mem.sig_id = ms.sig_id AND ms.created_at < $1", cutoff_minhash)
    await db.execute("DELETE FROM minhash_signatures WHERE created_at < $1", cutoff_minhash)
    await db.execute("DELETE FROM entity_mentions WHERE created_at < $1", cutoff_entity_mentions)
    await db.execute("DELETE FROM entity_dirty_log WHERE processed_at IS NOT NULL AND processed_at < $1", cutoff_dirty_log)
    await db.execute("DELETE FROM dead_letter_queue WHERE created_at < $1 AND resolved_at IS NOT NULL", cutoff_dlq)
    await db.execute("DELETE FROM outbox_events WHERE status = 'dispatched' AND dispatched_at < $1", cutoff_outbox)

    log.info("retention_cleanup_complete")
```

**Row volume estimates at steady state (50,000 documents/day):**

| Table | Est. rows/day | Est. total at retention limit |
|-------|--------------|-------------------------------|
| `entity_mentions` | ~500,000 | ~180M (12-month window) |
| `chunks` | ~1,000,000 | Unbounded (no retention — searchable corpus) |
| `chunk_embeddings` | ~1,000,000 | Unbounded |
| `routing_decisions` | ~50,000 | ~9M (6-month window) |
| `minhash_signatures` | ~50,000 | ~3M (60-day window) |
| `events` | ~25,000 | ~18M (24-month window, partitioned) |
| `claims` | ~75,000 | ~54M (24-month window, partitioned) |
| `relation_evidence` | ~30,000 | Grows permanently — partition by year at 36M rows |

`chunk_embeddings` and `chunks` grow permanently because they form the searchable corpus. At 1M chunks/day × 365 days = 365M chunks. Each chunk embedding is ~4KB (1024 floats × 4 bytes). At 365M rows: ~1.5TB for embeddings alone. At thesis scale (30 days, 10 sources), this is ~30M rows × 4KB = ~120GB — manageable on a single node with NVMe storage. For production, the chunks and embeddings tables should be partitioned by `created_at` month, with older partitions moved to cheaper storage.

---

### C.5 — `build_graph_change_payload` Specification

This function is referenced in Block 12 and Section 9.2 of the base PRD but never defined. It produces the alert payload that users see in the frontend.

```python
def build_graph_change_payload(
    event: GraphStateChangedEvent,
    affected_entities: list[str]  # Entity IDs for this specific user
) -> dict:
    """
    Build the alert payload for a graph state change event.
    This is what the frontend renders in the alert feed.
    """
    # Fetch entity names for display (from Valkey cache or DB)
    entity_summaries = []
    for entity_id in affected_entities[:10]:  # Cap at 10 entities per alert
        name = get_entity_name_cached(entity_id)  # Valkey: is:v1:entity_name:{id}
        entity_summaries.append({"entity_id": entity_id, "name": name})

    # Build human-readable description based on change_type
    if event.change_type == 'new_evidence':
        description = f"New intelligence on {len(affected_entities)} watched {'entity' if len(affected_entities) == 1 else 'entities'}"
    elif event.change_type == 'confidence_updated':
        significant_changes = [
            d for d in event.confidence_deltas
            if abs(d['new_confidence'] - d['old_confidence']) >= 0.10
        ]
        if significant_changes:
            description = f"Relationship confidence changed for {len(affected_entities)} watched {'entity' if len(affected_entities) == 1 else 'entities'}"
        else:
            return None  # Suppress minor confidence changes from alert payload
    elif event.change_type == 'contradiction_detected':
        description = "Conflicting information detected for watched entity"
    else:
        description = f"Intelligence update: {event.change_type}"

    return {
        "alert_type": "graph_change",
        "change_type": event.change_type,
        "description": description,
        "entities": entity_summaries,
        "entity_count": len(affected_entities),
        "occurred_at": event.occurred_at,
        "source_doc_id": event.doc_id,
        "confidence_deltas": [
            {
                "relation_id": d["relation_id"],
                "old_confidence": round(d["old_confidence"], 3),
                "new_confidence": round(d["new_confidence"], 3),
                "delta": round(d["new_confidence"] - d["old_confidence"], 3)
            }
            for d in (event.confidence_deltas or [])
            if abs(d["new_confidence"] - d["old_confidence"]) >= 0.05
        ][:5],  # Show at most 5 confidence changes
        "frontend_action": {
            "type": "open_dossier",
            "entity_id": affected_entities[0] if len(affected_entities) == 1 else None,
            "label": "View details"
        }
    }
```

**Frontend alert card structure.** The payload above renders as:

```
┌─────────────────────────────────────────────────────┐
│ [GRAPH CHANGE]  New intelligence on 2 watched       │
│                 entities                             │
│                                                      │
│ TSMC · ASML                                         │
│                                                      │
│ ASML supplier_of TSMC: 0.71 → 0.85 (+0.14)         │
│                                                      │
│ [View details]              2 min ago               │
└─────────────────────────────────────────────────────┘
```

---

### C.6 — Backpressure and Flow Control

**Problem.** When Ollama is saturated (common during filing season bursts), S6's Kafka consumer accumulates lag without bound. No mechanism exists to slow ingestion when processing capacity is exceeded.

**Fix: Kafka consumer pause/resume based on Ollama queue depth.**

```python
class NLPPipelineConsumer:
    MAX_OLLAMA_QUEUE_DEPTH = 20    # env: MAX_OLLAMA_QUEUE_DEPTH
    RESUME_OLLAMA_QUEUE_DEPTH = 5  # Resume when queue drains below this
    CHECK_INTERVAL_SECONDS = 5

    async def run(self):
        paused = False
        while True:
            # Measure Ollama queue depth via Prometheus metric or internal counter
            current_depth = self.ollama_queue_tracker.current_depth

            if not paused and current_depth > self.MAX_OLLAMA_QUEUE_DEPTH:
                self.consumer.pause(self.consumer.assignment())
                paused = True
                prometheus.gauge('s6_consumer_paused', 1)
                log.warning("consumer_paused_ollama_saturated", queue_depth=current_depth)

            elif paused and current_depth < self.RESUME_OLLAMA_QUEUE_DEPTH:
                self.consumer.resume(self.consumer.assignment())
                paused = False
                prometheus.gauge('s6_consumer_paused', 0)
                log.info("consumer_resumed", queue_depth=current_depth)

            if not paused:
                msg = self.consumer.poll(timeout=1.0)
                if msg:
                    await self.process_message(msg)
            else:
                await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
```

**Circuit breaker for Ollama endpoint.** Using `pybreaker` or equivalent:

```python
# Ollama circuit breaker: open after 5 consecutive failures, reset after 60s
ollama_breaker = CircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    name="ollama_embedding"
)

@ollama_breaker
async def embed_batch(texts: list[str]) -> list[list[float]]:
    response = await http_client.post(
        f"{settings.OLLAMA_BASE_URL}/api/embed",
        json={"model": settings.EMBEDDING_MODEL, "input": texts},
        timeout=30.0
    )
    return response.json()["embeddings"]
```

When the circuit is open, embedding requests fail fast. Chunks with failed embeddings are marked `embedding_status = 'pending'` and processed by the catch-up worker when Ollama recovers.

**Kafka consumer lag alerting thresholds** (adds to Prometheus alerting rules from C.2):

```yaml
      - alert: NLPPipelineLagCritical
        expr: s6_consumer_lag{topic="content.article.stored.v1"} > 50000
        for: 10m
        labels: {severity: critical}
        annotations: {summary: "NLP pipeline critically behind — check Ollama and GPU"}

      - alert: NLPConsumerPausedLong
        expr: s6_consumer_paused == 1
        for: 15m
        labels: {severity: warning}
        annotations: {summary: "NLP consumer paused for 15+ minutes — Ollama queue not draining"}
```

---

---

## D. Remaining Gap Resolution

*This section resolves the gaps identified as "partially addressed" or "still missing" after Addendum v1.0. Each item below corresponds directly to the gap analysis feedback.*

---

### D.1 — Monthly Partition Creation: Concrete Implementation

**Gap.** Section C.4 shows comment-style SQL DDL and a comment "run monthly via APScheduler job in S7" but provides no Python function that computes partition boundaries, no catch-up logic for missed months (S7 down on day 1), and no partition scheme for `chunks`, `chunk_embeddings`, or `relation_evidence`.

#### D.1.1 — APScheduler Registration in S7

Add `apscheduler[asyncio]` to `services/knowledge-graph/pyproject.toml` dependencies. Register both jobs in the S7 lifespan:

```python
# services/knowledge-graph/src/knowledge_graph/app.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from knowledge_graph.jobs.partitions import monthly_partition_job, yearly_partition_job

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Monthly: runs at 00:05 UTC on the 1st of each month.
    # misfire_grace_time=86400 means: if S7 was down at 00:05 on day 1,
    # APScheduler will still fire the job when S7 next starts, as long as
    # less than 24 hours have passed. If more than 24 hours have passed
    # (S7 was down for >1 day), the catch-up loop in monthly_partition_job
    # handles the gap by scanning for missing partitions.
    scheduler.add_job(
        monthly_partition_job,
        trigger=CronTrigger(day=1, hour=0, minute=5),
        id="monthly_partition_job",
        replace_existing=True,
        misfire_grace_time=86400,
    )

    # Yearly: runs at 00:00 UTC on January 1st to pre-create relation_evidence
    # partition for the new year. misfire_grace_time=86400 covers the same
    # "S7 down at midnight" scenario.
    scheduler.add_job(
        yearly_partition_job,
        trigger=CronTrigger(month=1, day=1, hour=0, minute=0),
        id="yearly_partition_job",
        replace_existing=True,
        misfire_grace_time=86400,
    )

    scheduler.start()
    # Run both jobs immediately on startup to catch up any partitions
    # that were missed while S7 was not running.
    await monthly_partition_job()
    await yearly_partition_job()

    yield

    scheduler.shutdown(wait=False)
```

Running `monthly_partition_job` immediately on every startup (not just on the first of the month) is the primary catch-up mechanism. If S7 is down for an entire month and comes back up on the 15th, the startup run creates both the missed month's partition and the current month's partition without operator intervention.

#### D.1.2 — Partition Job Implementation

Create `services/knowledge-graph/src/knowledge_graph/jobs/partitions.py`:

```python
"""Monthly and yearly partition management for partitioned tables in intelligence_db."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

# Tables partitioned monthly.
# Tuple: (table_name, retain_months | None).
# None means no automatic drop — partition is retained indefinitely.
MONTHLY_PARTITIONED = [
    ("events", 24),
    ("claims", 24),
    ("chunks", None),          # No auto-drop: searchable corpus
    ("chunk_embeddings", None), # No auto-drop: searchable corpus
]

# Tables partitioned yearly (relation_evidence).
YEARLY_PARTITIONED = [
    ("relation_evidence", None),  # Retain permanently — provenance anchor
]

# Regex for recognising auto-managed partition names.
_MONTHLY_PARTITION_RE = re.compile(r"^(?P<table>.+)_(?P<year>\d{4})_(?P<month>\d{2})$")
_YEARLY_PARTITION_RE  = re.compile(r"^(?P<table>.+)_(?P<year>\d{4})$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _monthly_bounds(year: int, month: int) -> tuple[str, str]:
    """Return (from_date, to_date) ISO strings for a monthly partition."""
    from_date = date(year, month, 1)
    if month == 12:
        to_date = date(year + 1, 1, 1)
    else:
        to_date = date(year, month + 1, 1)
    return str(from_date), str(to_date)


def _yearly_bounds(year: int) -> tuple[str, str]:
    return str(date(year, 1, 1)), str(date(year + 1, 1, 1))


def _advance_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


# ---------------------------------------------------------------------------
# Partition creation / drop
# ---------------------------------------------------------------------------

async def _existing_monthly_partitions(db, table: str) -> set[tuple[int, int]]:
    """Return set of (year, month) for existing monthly partitions of *table*."""
    rows = await db.fetch(
        """
        SELECT child.relname
        FROM pg_inherits
        JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
        JOIN pg_class child  ON pg_inherits.inhrelid  = child.oid
        WHERE parent.relname = $1
        """,
        table,
    )
    result: set[tuple[int, int]] = set()
    for row in rows:
        m = _MONTHLY_PARTITION_RE.match(row["relname"])
        if m:
            result.add((int(m["year"]), int(m["month"])))
    return result


async def _existing_yearly_partitions(db, table: str) -> set[int]:
    rows = await db.fetch(
        """
        SELECT child.relname
        FROM pg_inherits
        JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
        JOIN pg_class child  ON pg_inherits.inhrelid  = child.oid
        WHERE parent.relname = $1
        """,
        table,
    )
    result: set[int] = set()
    for row in rows:
        m = _YEARLY_PARTITION_RE.match(row["relname"])
        if m and m["table"] == table:
            result.add(int(m["year"]))
    return result


async def ensure_monthly_partitions(db, table: str, months_ahead: int = 2) -> None:
    """
    Create all missing monthly partitions for *table* from the earliest
    existing partition to today + *months_ahead* months.

    This function is idempotent (CREATE TABLE IF NOT EXISTS) and handles
    the "S7 was down on day 1" scenario: because it checks every month in
    the range rather than only the current month, any gap is automatically
    filled when S7 next starts.
    """
    today = date.today()
    existing = await _existing_monthly_partitions(db, table)

    if existing:
        min_year, min_month = min(existing)
        cur_year, cur_month = min_year, min_month
    else:
        cur_year, cur_month = today.year, today.month

    # Compute the end of the range: today + months_ahead
    end_year, end_month = today.year, today.month
    for _ in range(months_ahead):
        end_year, end_month = _advance_month(end_year, end_month)

    while (cur_year, cur_month) <= (end_year, end_month):
        if (cur_year, cur_month) not in existing:
            partition_name = f"{table}_{cur_year}_{cur_month:02d}"
            from_date, to_date = _monthly_bounds(cur_year, cur_month)
            await db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {partition_name}
                  PARTITION OF {table}
                  FOR VALUES FROM ('{from_date}') TO ('{to_date}')
                """
            )
            log.info("partition_created", table=table, partition=partition_name)
        cur_year, cur_month = _advance_month(cur_year, cur_month)


async def drop_expired_monthly_partitions(db, table: str, retain_months: int) -> None:
    """Drop monthly partitions whose end date is older than *retain_months* ago."""
    today = date.today()
    existing = await _existing_monthly_partitions(db, table)

    for year, month in existing:
        # The partition END date is the first day of (year, month+1).
        partition_end_year, partition_end_month = _advance_month(year, month)
        partition_end = date(partition_end_year, partition_end_month, 1)

        # Distance in months from partition_end to today.
        months_old = (today.year - partition_end.year) * 12 + (today.month - partition_end.month)
        if months_old >= retain_months:
            partition_name = f"{table}_{year}_{month:02d}"
            await db.execute(f"DROP TABLE IF EXISTS {partition_name}")
            log.info("partition_dropped", table=table, partition=partition_name, months_old=months_old)


async def ensure_yearly_partitions(db, table: str, years_ahead: int = 1) -> None:
    """Create yearly partitions for *table* from current year to current year + years_ahead."""
    today = date.today()
    existing = await _existing_yearly_partitions(db, table)

    for year in range(today.year, today.year + years_ahead + 1):
        if year not in existing:
            partition_name = f"{table}_{year}"
            from_date, to_date = _yearly_bounds(year)
            await db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {partition_name}
                  PARTITION OF {table}
                  FOR VALUES FROM ('{from_date}') TO ('{to_date}')
                """
            )
            log.info("partition_created", table=table, partition=partition_name)


# ---------------------------------------------------------------------------
# Scheduled job entry points
# ---------------------------------------------------------------------------

async def monthly_partition_job() -> None:
    """
    APScheduler entry point — runs at 00:05 UTC on the 1st of each month
    and on every S7 startup (catch-up).

    Creates partitions 2 months ahead and drops expired ones.
    """
    from knowledge_graph.db import get_db  # import here to avoid circular at module load

    db = get_db()
    for table, retain_months in MONTHLY_PARTITIONED:
        await ensure_monthly_partitions(db, table, months_ahead=2)
        if retain_months is not None:
            await drop_expired_monthly_partitions(db, table, retain_months)

    log.info("monthly_partition_job_complete")


async def yearly_partition_job() -> None:
    """
    APScheduler entry point — runs at 00:00 UTC on January 1st
    and on every S7 startup (catch-up).
    """
    from knowledge_graph.db import get_db

    db = get_db()
    for table, _ in YEARLY_PARTITIONED:
        await ensure_yearly_partitions(db, table, years_ahead=1)

    log.info("yearly_partition_job_complete")
```

#### D.1.3 — Partition Strategy for `chunks`, `chunk_embeddings`, and `relation_evidence`

**`chunks` and `chunk_embeddings` (monthly, no auto-drop).**

Both tables must be declared `PARTITION BY RANGE (created_at)` from the start (migration `001_initial_schema.py`). They are included in `MONTHLY_PARTITIONED` with `retain_months=None`, so `ensure_monthly_partitions` creates partitions but `drop_expired_monthly_partitions` is never called. This is intentional: chunks form the searchable corpus and must not be deleted. At thesis scale (~30 days), 2 monthly partitions suffice. At production scale, VACUUM and partition-level storage tiering (e.g. `ALTER TABLE ... SET TABLESPACE cold_storage`) can be applied per partition without a drop schedule.

**`relation_evidence` (yearly, permanent retention).**

Declared `PARTITION BY RANGE (created_at)`. Included in `YEARLY_PARTITIONED` with `retain_months=None`. The yearly partition job creates the current year's partition and next year's partition (1 year ahead). This eliminates the "no maintenance path at 36M rows" concern: `VACUUM`, index rebuilds, and statistics updates can be targeted at individual year partitions. No drop schedule — all partitions are retained permanently as provenance anchors.

**Updated partition policy table** (replaces the C.4 table):

| Table | Partitioned | Partition Key | Partition Unit | Drop After | Notes |
|-------|-------------|--------------|----------------|------------|-------|
| `events` | YES | `created_at` | Monthly | 24 months | Job: S7 monthly |
| `claims` | YES | `created_at` | Monthly | 24 months | Job: S7 monthly |
| `chunks` | YES | `created_at` | Monthly | Never | Job: S7 monthly; corpus retention |
| `chunk_embeddings` | YES | `created_at` | Monthly | Never | Job: S7 monthly; corpus retention |
| `relation_evidence` | YES | `created_at` | Yearly | Never | Job: S7 yearly; provenance anchor |
| `entity_mentions` | NO | — | — | 12 months (DELETE) | Daily cleanup job |
| `routing_decisions` | NO | — | — | 6 months (DELETE) | Daily cleanup job |
| `minhash_signatures` | NO | — | — | 60 days (DELETE) | Daily cleanup job |

---

### D.2 — Intelligence-Migrations: Concrete Migration Files

**Gap.** Section A.5 defines the `intelligence-migrations` service structure and lists example filenames but provides no migration file content. The addendum introduces four schema changes in sections A.2, B.1, B.3/B.4, and B.7 — each requires a numbered migration file whose existence and coverage was unconfirmed.

#### D.2.1 — Service Directory Structure (Confirmed)

```
services/intelligence-migrations/
  Dockerfile
  alembic.ini
  migrations/
    env.py
    versions/
      001_initial_schema.py          ← base PRD intelligence_db schema
      002_add_subject_entity_id.py   ← A.2
      003_add_minhash_entity_mentions.py  ← B.1
      004_add_source_trust_weights.py    ← B.7
      005_add_relations_partial_indexes.py  ← B.3 + B.4
```

**Mapping between addendum sections and migration files:**

| Addendum section | Schema change | Migration file |
|-----------------|--------------|----------------|
| A.2 | `ALTER TABLE claims ADD COLUMN subject_entity_id` | `002_add_subject_entity_id.py` |
| B.1 | `CREATE TABLE minhash_entity_mentions` + index | `003_add_minhash_entity_mentions.py` |
| B.7 | `CREATE TABLE source_trust_weights` + index + seed data | `004_add_source_trust_weights.py` |
| B.3 + B.4 | Two partial indexes on `relations`; drop old index on `claims`, add two new ones | `005_add_relations_partial_indexes.py` |

#### D.2.2 — Migration File: `002_add_subject_entity_id.py`

```python
"""Add subject_entity_id to claims; replace idx_claims_type_polarity.

Revision ID: 002
Revises: 001
Create Date: 2026-03-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A.2: add subject column
    op.add_column(
        "claims",
        sa.Column("subject_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_claims_subject_entity",
        "claims", "canonical_entities",
        ["subject_entity_id"], ["entity_id"],
        ondelete="SET NULL",
    )

    # B.4: drop old non-serving index (created in migration 001)
    op.drop_index("idx_claims_type_polarity", table_name="claims", if_exists=True)

    # B.4: contradiction detection index
    op.create_index(
        "idx_claims_contradiction_detection",
        "claims",
        ["subject_entity_id", "claim_type", "polarity", "created_at"],
        postgresql_where=sa.text("subject_entity_id IS NOT NULL AND polarity != 'neutral'"),
        postgresql_ops={"created_at": "DESC"},
    )

    # B.4: claimer-based index
    op.create_index(
        "idx_claims_by_claimer",
        "claims",
        ["claimer_entity_id", "claim_type", "created_at"],
        postgresql_where=sa.text("claimer_entity_id IS NOT NULL"),
        postgresql_ops={"created_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("idx_claims_by_claimer", table_name="claims")
    op.drop_index("idx_claims_contradiction_detection", table_name="claims")
    op.create_index("idx_claims_type_polarity", "claims", ["claim_type", "polarity", "created_at"])
    op.drop_constraint("fk_claims_subject_entity", "claims", type_="foreignkey")
    op.drop_column("claims", "subject_entity_id")
```

#### D.2.3 — Migration File: `003_add_minhash_entity_mentions.py`

```python
"""Add minhash_entity_mentions junction table (B.1).

Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "minhash_entity_mentions",
        sa.Column("sig_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("sig_id", "entity_id"),
        sa.ForeignKeyConstraint(
            ["sig_id"], ["minhash_signatures.sig_id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "idx_minhash_entity_mentions_entity",
        "minhash_entity_mentions",
        ["entity_id", "sig_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_minhash_entity_mentions_entity", table_name="minhash_entity_mentions")
    op.drop_table("minhash_entity_mentions")
```

#### D.2.4 — Migration File: `004_add_source_trust_weights.py`

```python
"""Add source_trust_weights table with seed data (B.7).

Revision ID: 004
Revises: 003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_trust_weights",
        sa.Column("weight_id", postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("trust_weight", sa.Double(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="'system_seed'"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("trust_weight > 0 AND trust_weight <= 2.0",
                           name="chk_trust_weight_range"),
    )
    op.create_index(
        "idx_source_trust_weights_lookup",
        "source_trust_weights",
        ["source_type", "source_name", "effective_from"],
        postgresql_where=sa.text("is_active = true"),
        postgresql_ops={"effective_from": "DESC"},
    )

    # Seed data (idempotent via ON CONFLICT DO NOTHING would require a unique key;
    # instead, we rely on migration running exactly once via Alembic version tracking).
    op.execute("""
        INSERT INTO source_trust_weights
          (source_type, source_name, trust_weight, effective_from, change_reason, created_by)
        VALUES
          ('sec_filing',         NULL, 1.4, '2026-01-01', 'Initial seed', 'system'),
          ('finnhub_transcript', NULL, 1.3, '2026-01-01', 'Initial seed', 'system'),
          ('finnhub_news',       NULL, 1.1, '2026-01-01', 'Initial seed', 'system'),
          ('eodhd',              NULL, 1.0, '2026-01-01', 'Initial seed', 'system'),
          ('newsapi',            NULL, 0.9, '2026-01-01', 'Initial seed', 'system')
    """)


def downgrade() -> None:
    op.drop_index("idx_source_trust_weights_lookup", table_name="source_trust_weights")
    op.drop_table("source_trust_weights")
```

#### D.2.5 — Migration File: `005_add_relations_partial_indexes.py`

```python
"""Add partial indexes for active-relation traversal (B.3).

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # B.3: active-relation traversal indexes
    op.create_index(
        "idx_relations_active_subject",
        "relations",
        ["subject_entity_id", "canonical_type", "status", "current_confidence"],
        postgresql_where=sa.text("valid_to IS NULL AND status IN ('active', 'confirmed')"),
        postgresql_ops={"current_confidence": "DESC"},
    )
    op.create_index(
        "idx_relations_active_object",
        "relations",
        ["object_entity_id", "canonical_type", "status", "current_confidence"],
        postgresql_where=sa.text("valid_to IS NULL AND status IN ('active', 'confirmed')"),
        postgresql_ops={"current_confidence": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("idx_relations_active_object", table_name="relations")
    op.drop_index("idx_relations_active_subject", table_name="relations")
```

#### D.2.6 — Portfolio Migration `0004_add_watchlist_entity_index.py`

This migration belongs in `services/portfolio/alembic/versions/` (not in `intelligence-migrations`), because `watchlist_entity_index` lives in `portfolio_db`.

**Implementation note.** The existing `watchlist_members` table (created in `0002_add_watchlists.py`) already has `ix_watchlist_members_entity_id` on `(entity_id)`. The B.2 specification calls for a separate denormalised `watchlist_entity_index` table. Given the existing schema, both approaches satisfy the query contract (`GET /by-entity/{entity_id}` in O(log N)). The decision: **use the existing `watchlist_members` table as the backing store** — a separate `watchlist_entity_index` table is redundant given the `entity_id` index already present. Migration `0004` adds only the `user_id` composite index needed by the batch endpoint:

```python
"""Add composite index on watchlist_members for S10 internal API (B.2).

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Covers GET /internal/v1/watchlists/by-entity/{entity_id}:
    # entity_id → list of (user_id, watchlist_id) for all active watchlists
    op.create_index(
        "ix_watchlist_members_entity_user",
        "watchlist_members",
        ["entity_id", "user_id"],
    )
    # Partial index for join with active watchlists:
    # watchlist_id FK to watchlists.id where status = 'active'
    op.create_index(
        "ix_watchlist_members_watchlist_entity_active",
        "watchlist_members",
        ["watchlist_id", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_members_watchlist_entity_active", table_name="watchlist_members")
    op.drop_index("ix_watchlist_members_entity_user", table_name="watchlist_members")
```

The `/internal/v1/watchlists/by-entity/{entity_id}` endpoint queries:

```sql
SELECT wm.user_id, wm.watchlist_id
FROM watchlist_members wm
JOIN watchlists w ON w.id = wm.watchlist_id
WHERE wm.entity_id = $1
  AND w.status = 'active'
```

This is served by the existing `ix_watchlist_members_entity_id` index on `watchlist_members.entity_id` — the new `0004` indexes improve the join and batch path without requiring a separate denormalised table.

---

### D.3 — Ollama Model Pre-Pull on First Startup

**Gap.** The Docker Compose stack defines the `ollama` service with no healthcheck and no mechanism to pull required models. S6's readiness check (C.1) correctly refuses to mark itself ready until Ollama has `bge-large-en-v1.5` in its model list — which means S6 will **never** become ready on a fresh deployment until models are manually pulled.

#### D.3.1 — Ollama Entrypoint Script

Create `infra/ollama/entrypoint.sh`:

```bash
#!/usr/bin/env bash
# infra/ollama/entrypoint.sh
#
# Starts the Ollama server and pre-pulls all required models on first boot.
# On subsequent boots, models are already in the volume — pulls are skipped.
# This script replaces the default Ollama container entrypoint.
set -euo pipefail

REQUIRED_MODELS=(
    "bge-large-en-v1.5"
    "qwen2.5:7b-instruct"
)

# Start the Ollama server in the background.
ollama serve &
SERVE_PID=$!

# Wait until the Ollama HTTP API accepts connections.
echo "[ollama-init] Waiting for Ollama server to start..."
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 2
done
echo "[ollama-init] Ollama server ready."

# Pull each required model if it is not already present in the volume.
LOADED_MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c \
    "import sys, json; print('\n'.join(m['name'] for m in json.load(sys.stdin).get('models', [])))")

for MODEL in "${REQUIRED_MODELS[@]}"; do
    if echo "$LOADED_MODELS" | grep -qF "$MODEL"; then
        echo "[ollama-init] Model already present: $MODEL"
    else
        echo "[ollama-init] Pulling model: $MODEL (this may take several minutes on first run)"
        ollama pull "$MODEL"
        echo "[ollama-init] Model pulled: $MODEL"
    fi
done

echo "[ollama-init] All required models ready."

# Hand off to the Ollama server process.
wait $SERVE_PID
```

#### D.3.2 — Docker Compose `ollama` Service Update

Replace the existing `ollama` service block in `docker-compose.yml`:

```yaml
  ollama:
    image: ollama/ollama:latest
    profiles: [infra]
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
      - ./infra/ollama/entrypoint.sh:/entrypoint.sh:ro
    entrypoint: ["/bin/bash", "/entrypoint.sh"]
    healthcheck:
      # Healthy only when the server is up AND both required models are present.
      # grep -c returns 0 (fail) if fewer than 2 matches are found.
      test: >
        bash -c "curl -sf http://localhost:11434/api/tags |
          python3 -c \"import sys,json; models=[m['name'] for m in json.load(sys.stdin)['models']];
          assert 'bge-large-en-v1.5' in models and any('qwen2.5' in m for m in models)\""
      interval: 30s
      timeout: 10s
      retries: 20          # 20 × 30s = 10 minutes; large models take time to pull
      start_period: 120s   # Give Ollama time to start before healthchecks begin
```

#### D.3.3 — S6 Dependency on Ollama Healthcheck

Add to the `svc-nlp-pipeline` service in `docker-compose.yml`:

```yaml
  svc-nlp-pipeline:
    depends_on:
      ollama:
        condition: service_healthy   # ← add this
      # ... other deps ...
```

This ensures S6 never starts before Ollama is up and models are loaded. On a fresh deployment, `svc-nlp-pipeline` will simply wait (up to 10 minutes by default) for the model pull to complete.

---

### D.4 — S1 Portfolio: Implementation Dependency Statement and Gap Cross-Reference

**Gap.** Section B.2 defines the internal API contract and `watchlist_entity_index` table that S1 must provide, but the addendum contains no formal dependency statement gating S10's deployment on S1's completion, and does not cross-reference what parts of S1 are already implemented versus still missing.

#### D.4.1 — Formal Dependency Statement

> **S10 Alert Service cannot be deployed until S1 Portfolio implements all features listed below.** The intelligence layer PRD owns the contract (API shapes, event schema, topic names); S1 owns the implementation. S10's Kafka consumer for `portfolio.watchlist.updated.v1` and its calls to `GET /internal/v1/watchlists/by-entity/{entity_id}` will fail at runtime until S1 exposes these endpoints and produces to the topic.

S1 must complete the following before S10 is deployed:

| Feature | Status (as of 2026-03-20) | Required by |
|---------|--------------------------|-------------|
| `watchlists` DB table + migrations | ✓ Implemented (`0002_add_watchlists.py`) | S10 internal API |
| `watchlist_members` DB table | ✓ Implemented | S10 internal API |
| `watchlist_entity_index` composite indexes | ✓ Implemented (`0004` — D.2.6 above) | S10 `/by-entity/` query |
| Domain entities: `Watchlist`, `WatchlistMember` | ✓ Implemented | — |
| Domain events: `WatchlistItemAdded`, `WatchlistItemRemoved`, `WatchlistCreated`, `WatchlistDeleted` | ✓ Implemented | Kafka producer |
| Avro schemas: `watchlist.item_added.avsc`, `watchlist.item_removed.avsc` | ✓ Implemented | Schema Registry |
| Kafka topic routing: `watchlist.item_added` → `portfolio.watchlist.updated.v1` | ✓ Implemented (`topics.py`) | S10 consumer |
| **Watchlist API routes** (`POST /watchlists`, `GET /watchlists`, `POST /watchlists/{id}/items`, `DELETE /watchlists/{id}/items/{entity_id}`, `DELETE /watchlists/{id}`) | **MISSING** | Users / S10 indirect |
| **Watchlist use cases** (`create_watchlist`, `add_watchlist_item`, `remove_watchlist_item`, `delete_watchlist`) | **MISSING** | API routes |
| **Watchlist outbox producer** (use case writes event → outbox inside transaction) | **MISSING** | `portfolio.watchlist.updated.v1` topic |
| **Internal API** (`GET /internal/v1/watchlists/by-entity/{entity_id}`, `POST /internal/v1/watchlists/by-entities`) | **MISSING** | S10 fan-out |

#### D.4.2 — S1 Internal API Implementation Notes

The internal endpoints query `watchlist_members` joined to `watchlists WHERE status = 'active'`, served by the indexes added in migration `0004`. Authentication uses `INTERNAL_SERVICE_TOKEN` injected as an environment variable — the header name is `Internal-Service-Token` as defined in B.2. These endpoints are **not** registered on the public `api_router` (`prefix="/api/v1"`); they must be registered on a separate internal router (`prefix="/internal/v1"`) that is not exposed through the API Gateway.

#### D.4.3 — Event Schema Alignment Note

The A.1 addendum defines a unified `portfolio.watchlist.updated` message schema with a `change_type` discriminator field. The current implementation emits **separate** event types (`watchlist.item_added`, `watchlist.item_removed`) to the `portfolio.watchlist.updated.v1` topic. This is functionally equivalent for S10: S10 must handle both event types from this topic. The two Avro schemas (`watchlist.item_added.avsc`, `watchlist.item_removed.avsc`) cover both cases. S10 should not assume a single unified schema; it should branch on `event_type` after deserialization.

---

### D.5 — Dead Letter Queue Management API

**Gap.** The `dead_letter_queue` table is well-defined and the outbox dispatcher correctly writes to it, but no document specifies who reads the DLQ, how failed messages are replayed, or whether an admin API exists. At production scale, DLQ entries accumulate silently with no operational path to replay them.

#### D.5.1 — Design Decision: Per-Service Admin Router

Each service with an outbox (S4, S6, S7, S1) independently exposes a `/admin/dlq` sub-API. This is preferable to a centralised DLQ service because each service owns its own `dead_letter_queue` table in its own database. A centralised aggregation API can be built later if needed.

All admin endpoints require the `X-Admin-Token` header. The token is injected as `ADMIN_API_TOKEN` environment variable and checked server-side. This is not a substitute for mTLS in production but is sufficient for the thesis deployment context.

#### D.5.2 — Shared DLQ Admin Router Pattern

Add to `libs/messaging/src/messaging/admin/dlq_router.py`:

```python
"""Reusable FastAPI router for dead-letter queue management.

Mount this router on each service that has a dead_letter_queue table.

Usage in a service:
    from messaging.admin.dlq_router import build_dlq_router
    app.include_router(build_dlq_router(get_dlq_repo), prefix="/admin")
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query


def _require_admin_token(x_admin_token: str = Header(alias="X-Admin-Token")) -> None:
    import os
    expected = os.environ.get("ADMIN_API_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Invalid admin token")


def build_dlq_router(get_repo) -> APIRouter:
    """
    Build a DLQ admin router.

    *get_repo* is a FastAPI dependency that returns an object with the
    following async methods:
        - list(limit, offset, status) -> list[dict]
        - get(record_id) -> dict | None
        - requeue(record_id) -> bool      # reset status to 'pending', decrement retry_count
        - resolve(record_id, note) -> bool # set status to 'resolved'
    """
    router = APIRouter(tags=["admin-dlq"])

    @router.get("/dlq")
    async def list_dlq(
        limit: int = Query(default=50, le=200),
        offset: int = Query(default=0, ge=0),
        status: str | None = Query(default=None),
        _: None = Depends(_require_admin_token),
        repo=Depends(get_repo),
    ) -> dict[str, Any]:
        """List dead-letter queue entries. Filter by status: failed | resolved."""
        records = await repo.list(limit=limit, offset=offset, status=status)
        return {"count": len(records), "offset": offset, "records": records}

    @router.get("/dlq/{record_id}")
    async def get_dlq_entry(
        record_id: UUID,
        _: None = Depends(_require_admin_token),
        repo=Depends(get_repo),
    ) -> dict[str, Any]:
        record = await repo.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="DLQ entry not found")
        return record

    @router.post("/dlq/{record_id}/retry")
    async def retry_dlq_entry(
        record_id: UUID,
        _: None = Depends(_require_admin_token),
        repo=Depends(get_repo),
    ) -> dict[str, str]:
        """
        Re-queue a failed DLQ entry. Resets status to 'pending' and
        decrements retry_count so the outbox dispatcher will attempt
        delivery again. The entry is removed from the DLQ and returned
        to outbox_events.
        """
        ok = await repo.requeue(record_id)
        if not ok:
            raise HTTPException(status_code=404, detail="DLQ entry not found or not retryable")
        return {"status": "requeued", "record_id": str(record_id)}

    @router.post("/dlq/{record_id}/resolve")
    async def resolve_dlq_entry(
        record_id: UUID,
        note: str = Query(default=""),
        _: None = Depends(_require_admin_token),
        repo=Depends(get_repo),
    ) -> dict[str, str]:
        """
        Mark a DLQ entry as resolved (will not be retried).
        Use this when manual intervention has addressed the root cause
        and replay is not needed (e.g. downstream system already processed
        the event through another channel).
        """
        ok = await repo.resolve(record_id, note=note)
        if not ok:
            raise HTTPException(status_code=404, detail="DLQ entry not found")
        return {"status": "resolved", "record_id": str(record_id)}

    return router
```

#### D.5.3 — DLQ Repository Schema

The `dead_letter_queue` table must include a `resolved_at` and `resolution_note` column to support the `resolve` operation. Add to `001_initial_schema.py` (or as migration `006` for the intelligence-migrations service):

```sql
CREATE TABLE dead_letter_queue (
  dlq_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_service   TEXT NOT NULL,
  pipeline_block   TEXT NOT NULL,
  kafka_topic      TEXT NOT NULL,
  failure_reason   TEXT NOT NULL,
  payload_json     JSONB NOT NULL,
  retry_count      INT NOT NULL DEFAULT 0,
  status           TEXT NOT NULL DEFAULT 'failed'   -- failed | resolved
    CHECK (status IN ('failed', 'resolved')),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at      TIMESTAMPTZ,
  resolution_note  TEXT
);

CREATE INDEX idx_dlq_status_created ON dead_letter_queue (status, created_at DESC)
  WHERE status = 'failed';
```

The `requeue` operation moves the record back into `outbox_events` (resetting `retry_count = 0, status = 'pending'`) inside a single transaction, then deletes the DLQ entry.

#### D.5.4 — Operational Runbook Entry

Add to `docs/runbooks/`: a DLQ runbook covering:

1. **How to detect DLQ entries**: Prometheus alert `DLQDepthNonZero` fires when `SELECT COUNT(*) FROM dead_letter_queue WHERE status = 'failed' > 0`.
2. **How to inspect**: `GET /admin/dlq` with the admin token.
3. **How to retry a single entry**: `POST /admin/dlq/{id}/retry`. Check Prometheus `s4_outbox_dispatch_latency_seconds` to confirm delivery.
4. **How to bulk retry**: Call retry for each entry returned by `GET /admin/dlq?status=failed`. There is intentionally no bulk-retry endpoint to avoid thundering-herd re-delivery.
5. **How to resolve without retry**: `POST /admin/dlq/{id}/resolve?note=<reason>` when the downstream system already received the event through another channel or the event is stale.

---

### D.6 — Schema Registry: Compatibility Mode and Evolution Rules

**Gap.** The base PRD states "Avro serialization for all topics" and the `register-schemas.py` init script registers `.avsc` files. However, no document specifies: (a) which Schema Registry subject naming convention is used, (b) what compatibility mode is set per subject, (c) how producers and consumers are configured to use the registry, or (d) what to do when a field needs to be added to an existing schema. Without this, any schema change risks silent deserialization failures in consumers.

#### D.6.1 — Subject Naming Convention

**Convention (already implemented by `register-schemas.py`):**

```
subject = {filename without .avsc} + "-value"
```

Examples:

| `.avsc` filename | Schema Registry subject |
|-----------------|------------------------|
| `content.article.raw.v1.avsc` | `content.article.raw.v1-value` |
| `portfolio.events.v1.avsc` | `portfolio.events.v1-value` |
| `watchlist.item_added.avsc` | `watchlist.item_added-value` |

The Kafka topic name and the Schema Registry subject name are **not** required to match. For the `portfolio.watchlist.updated.v1` topic, two schemas are registered under two subjects (`watchlist.item_added-value` and `watchlist.item_removed-value`). S10 consumers must handle both schemas by reading the magic byte + schema ID from the message header and resolving via the registry client.

#### D.6.2 — Missing Schema: `portfolio.watchlist.updated.v1.avsc`

The `portfolio.watchlist.updated.v1` topic (as used for S10 cache invalidation) currently has no dedicated top-level Avro schema file. Messages on this topic use the `watchlist.item_added` or `watchlist.item_removed` schemas. Create `infra/kafka/schemas/portfolio.watchlist.updated.v1.avsc` as a union schema:

```json
[
  {
    "type": "record",
    "name": "WatchlistItemAdded",
    "namespace": "portfolio.events",
    "doc": "Entity added to a watchlist — emitted on portfolio.watchlist.updated.v1",
    "fields": [
      {"name": "event_id",       "type": "string"},
      {"name": "event_type",     "type": "string", "default": "watchlist.item_added"},
      {"name": "aggregate_type", "type": "string", "default": "watchlist"},
      {"name": "aggregate_id",   "type": "string"},
      {"name": "tenant_id",      "type": "string"},
      {"name": "occurred_at",    "type": "string"},
      {"name": "schema_version", "type": "int",    "default": 1},
      {"name": "correlation_id", "type": ["null", "string"], "default": null},
      {"name": "causation_id",   "type": ["null", "string"], "default": null},
      {"name": "watchlist_id",   "type": "string", "default": ""},
      {"name": "user_id",        "type": "string", "default": ""},
      {"name": "entity_id",      "type": "string", "default": ""},
      {"name": "entity_type",    "type": "string", "default": "company"}
    ]
  },
  {
    "type": "record",
    "name": "WatchlistItemRemoved",
    "namespace": "portfolio.events",
    "doc": "Entity removed from a watchlist — emitted on portfolio.watchlist.updated.v1",
    "fields": [
      {"name": "event_id",       "type": "string"},
      {"name": "event_type",     "type": "string", "default": "watchlist.item_removed"},
      {"name": "aggregate_type", "type": "string", "default": "watchlist"},
      {"name": "aggregate_id",   "type": "string"},
      {"name": "tenant_id",      "type": "string"},
      {"name": "occurred_at",    "type": "string"},
      {"name": "schema_version", "type": "int",    "default": 1},
      {"name": "correlation_id", "type": ["null", "string"], "default": null},
      {"name": "causation_id",   "type": ["null", "string"], "default": null},
      {"name": "watchlist_id",   "type": "string", "default": ""},
      {"name": "user_id",        "type": "string", "default": ""},
      {"name": "entity_id",      "type": "string", "default": ""},
      {"name": "entity_type",    "type": "string", "default": "company"}
    ]
  }
]
```

#### D.6.3 — Compatibility Mode

**Default mode for all subjects: `BACKWARD`.**

BACKWARD compatibility means: a new schema version can always be used to read data written with the previous schema version. This is the safest default for Kafka topics where consumers may be running an older version than producers during a rolling deploy.

**Setting compatibility mode.** Extend `register-schemas.py` to set compatibility after registration:

```python
def set_compatibility(registry_url: str, subject: str, mode: str = "BACKWARD") -> None:
    """Set Schema Registry compatibility mode for a subject."""
    payload = json.dumps({"compatibility": mode}).encode()
    url = f"{registry_url}/config/{subject}"
    req = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        method="PUT",
    )
    try:
        with urlopen(req) as resp:
            logger.info("Compatibility set for %s: %s", subject, mode)
    except HTTPError as e:
        logger.error("Failed to set compatibility for %s: HTTP %s", subject, e.code)
```

Call `set_compatibility(registry_url, subject)` for every subject immediately after `register_schemas()` in the init script.

**Per-topic compatibility exceptions:**

| Subject | Mode | Reason |
|---------|------|--------|
| All others | `BACKWARD` | Default: rolling deploys safe |
| `relation.type.proposed.v1-value` | `FULL` | Both producers and consumers are manual/operator-driven; full compatibility required |
| `nlp.article.enriched.v1-value` | `BACKWARD` | High-volume; consumers may lag behind producers |

#### D.6.4 — Schema Evolution Rules

**Allowed changes (BACKWARD compatible):**
- Adding a new field with a default value.
- Removing a field that has a default value (the consumer still reads the old default for older messages).

**Forbidden changes (break BACKWARD compatibility):**
- Removing a required field (no default).
- Renaming a field.
- Changing a field's type.
- Adding a required field with no default.

**Process for a BACKWARD-compatible change:**

1. Add the new field to the `.avsc` file **with a default value**.
2. Increment `schema_version` in the message payload (convention, not enforced by Avro).
3. Verify locally: `python3 infra/kafka/init/register-schemas.py --schema-dir infra/kafka/schemas --registry-url http://localhost:8081` — the registry will reject the registration if compatibility is violated.
4. Run the init script in CI. The script is idempotent (`409` = already registered is treated as success).
5. Deploy producers before consumers (producers write the new schema; consumers must be able to read it via BACKWARD compatibility).

**Example — adding `source_count` to `nlp.signal.detected.v1`:**

```diff
  {"name": "signal_type",  "type": "string"},
  {"name": "confidence",   "type": "double"},
+ {"name": "source_count", "type": "int", "default": 1}
```

This is BACKWARD compatible: old consumers that do not have `source_count` in their reader schema will simply ignore the field; new consumers will read it. Consumers that have `source_count` but receive an old message (before the schema change) will get the default value `1`.

---

*End of Worldview Intelligence Layer PRD Addendum v1.0 (including Remaining Gap Resolution — Section D)*

*Together with PRD v2.0 and this addendum, all critical, significant, moderate, partially-addressed, and previously-missing gaps are now resolved. Section D adds: concrete monthly/yearly partition job implementation (D.1), all intelligence-migrations migration files (D.2), Ollama model pre-pull mechanism (D.3), S1 Portfolio dependency statement and implementation gap register (D.4), DLQ management API pattern (D.5), and Schema Registry subject naming, compatibility mode, and evolution rules (D.6).*
