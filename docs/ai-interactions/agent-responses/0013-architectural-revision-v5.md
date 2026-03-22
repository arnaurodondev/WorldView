# Worldview Intelligence Pipeline — Architectural Revision v5

Version: 5.0
Date: 2026-03-21
Status: Draft
Supersedes: 0012-architectural-review-prd-v4.md
Author: Architecture Review Cycle

---

## A. Executive Synthesis

### A.1 Most Important Accepted Revisions

**1. Raw-then-aggregate relation write model.**
Relation evidence is written cheaply to a staging table first. A worker consolidates into the aggregate `relations` table on a configurable interval. This eliminates upsert contention on the hot path and decouples ingestion throughput from graph write latency. Query-time correctness is maintained by reading aggregate + recent unprocessed delta.

**2. Temporal-class-driven confidence recomputation cadences.**
Confidence is no longer recomputed on a single schedule. Each relation carries a `decay_class` (PERMANENT / DURABLE / SLOW / MEDIUM / FAST / EPHEMERAL) that drives its recomputation interval. Per-evidence temporal weights replace the single `days_since_latest_evidence` scalar. Old low-quality evidence decays naturally without being deleted.

**3. Contradiction worker decoupled from hot path.**
Contradiction detection moves to an async worker that consumes from Kafka (outbox pattern). This prevents growing `claims` table scans from degrading S6 ingestion latency. Linkage between `relation_evidence` and `claims` is explicit through a dedicated `relation_contradiction_links` table.

**4. Outbox/dispatcher as platform-wide invariant.**
Every service that emits Kafka events must write to a local outbox table first, with a dispatcher process publishing to Kafka. This applies without exception to S4, S5, S6, S7, and S10. Consumer-side idempotency is enforced through event_id uniqueness checks at the consumer.

**5. Valkey-backed LSH with source-type windowing.**
LSH bands move from in-memory rebuild on startup to Valkey-backed persistent storage with TTL-keyed sliding windows. Window duration varies by source type. The two-tier dedup model preserves corroborating evidence from different sources, suppressing only same-source near-duplicates by default.

**6. Two-stage novelty gate.**
Stage 1 runs pre-entity-resolution using unresolved mention strings and MinHash overlap — cheap and fast. Stage 2 runs post-resolution using resolved entity_ids, embedding neighborhood distance, and event-structure novelty — corrective and authoritative. Stage 1 feeds routing. Stage 2 can upgrade a document from a Stage 1 downgrade.

**7. Additive normalized routing score.**
Seven weighted signals replace the previous multiplicative structure. Signals are normalized to [0,1]. Hysteresis bands prevent cliff-edge tier oscillation. Forced `deep` overrides for all SEC documents are removed; document type is handled as one weighted signal among seven.

**8. entity.dirtied.v1 event-driven embedding refresh.**
Graph writes emit `entity.dirtied.v1` through the outbox pattern. Embedding refresh workers consume and coalesce per entity_id. Compacted topic or lightweight state table enables recovery. Stale entity embeddings are served at query time with a freshness metadata flag.

**9. Provider abstraction as first-class design.**
Python Protocol interfaces (`EmbeddingClient`, `ExtractionClient`, `NERClient`) define canonical input/output schemas. Provider-specific adapters implement the protocols. A `model_registry` table tracks active models per capability. Prompt versioning is stored in a `prompt_templates` table. Conformance tests validate all provider adapters against schema contracts.

**10. Relation summaries and relation embeddings.**
Each aggregated relation in the graph accumulates a periodically-refreshed text summary and a corresponding embedding. This enables relation-level semantic retrieval at query time without reconstructing narrative from raw evidence rows.

### A.2 Most Important Unresolved Issues

**1. Query pipeline is entirely undefined (CRITICAL).**
No retrieval ordering, no fusion formula, no ranking logic, no answer generation contract. This must be resolved before any embedding index decisions become final, because retrieval architecture determines what indexes are needed and at what granularity.

**2. PostgreSQL write contention under horizontal scaling.**
Managing concurrent relation aggregation workers across multiple replicas requires an explicit ownership strategy. Managed Postgres read replicas do not solve write-key contention on the `relations` table. Advisory locks, hash partitioning, or queue-based ownership must be chosen and specified.

**3. GLiNER ontology is not finalized.**
The current entity class list contains semantic errors (event_type), missing high-value classes (commodity, macroeconomic_indicator, index), and an overly broad `institution` class that inflates entity density signals incorrectly.

**4. Relation summary update cadence and change-detection strategy.**
When does a summary regenerate? What constitutes "enough new evidence" to justify a recompute? How does the summary interact with partial aggregation state (raw deltas not yet consolidated)?

**5. Embedding vector space maintenance over time.**
What is the pruning/TTL/archival strategy per source type? When do stale chunk embeddings degrade retrieval quality enough to require deletion? How does HNSW index bloat affect query latency?

**6. Temporal validity vs confidence decay is conflated in the current PRD.**
`valid_to` is an LLM-extracted field that is systematically unreliable. `confidence` decay is a system-computed property. These must be separated in schema and in the confidence formula.

### A.3 Highest-Priority PRD Changes

1. Define query pipeline (Section B.12 below) — blocks final embedding index decisions
2. Finalize relation write model and PostgreSQL scaling strategy (Section B.1, C.1)
3. Lock GLiNER ontology (Section B.6, C.6)
4. Specify relation summary schema and update rules (Section B.11, C.4)
5. Rewrite confidence formula with per-evidence temporal weighting (Section B.2)
6. Define embedding TTL/pruning policy per source type (Section B.8, C.3)
7. Lock provider abstraction Protocol interfaces and canonical schemas (Section B.9, C.5)
8. Adopt testing/evaluation PRD (Section D)

---

## B. Block-by-Block Revision

---

### B.1 — Knowledge Graph / Relations Aggregation / Write Scalability

#### Current Problem

The PRD specifies a single aggregation worker that upserts into `relations` on a UNIQUE constraint `(subject_entity_id, canonical_type, object_entity_id)`. Under burst ingestion, all workers contend on this constraint. Evidence appends to `relation_evidence` are serialized through the same lock domain. The confidence batch job processes 5,000 relations per 15-minute interval with no partitioning — permanent lag under high load. `entity_dirty_log` is polled by a single process, making it a hot table.

#### Accepted Direction

Relation evidence is written cheaply to a staging table first. A worker periodically consolidates into the aggregate `relations` table. A configurable environment variable controls the flush interval (target: 5 minutes default, reducible to 30 seconds). The worker cleans processed staging rows after successful aggregation. Eventual consistency for aggregation is accepted.

#### Revised Proposal

**Data model:**

```sql
-- Staging table: no UNIQUE constraints, append-only, indexed for worker reads
CREATE TABLE relation_evidence_raw (
    raw_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id UUID NOT NULL,
    object_entity_id  UUID NOT NULL,
    canonical_type    VARCHAR(100) NOT NULL,
    polarity          VARCHAR(20)  NOT NULL DEFAULT 'positive',
    claim_id          UUID,
    chunk_id          UUID,
    source_document_id UUID NOT NULL,
    extraction_confidence FLOAT NOT NULL,
    extracted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed         BOOLEAN NOT NULL DEFAULT false,
    processed_at      TIMESTAMPTZ,
    worker_claim_id   UUID  -- set by aggregation worker when claiming a batch
);

CREATE INDEX idx_rer_unprocessed
    ON relation_evidence_raw (subject_entity_id, canonical_type, extracted_at)
    WHERE processed = false;

CREATE INDEX idx_rer_worker_claim
    ON relation_evidence_raw (worker_claim_id)
    WHERE processed = false;
```

**Aggregation worker pattern (v1 — single process):**

```
1. SELECT raw_id, subject_entity_id, object_entity_id, canonical_type
   FROM relation_evidence_raw
   WHERE processed = false
   ORDER BY extracted_at
   LIMIT RELATION_AGGREGATION_BATCH_SIZE
   FOR UPDATE SKIP LOCKED;

2. Group claimed rows by (subject_entity_id, canonical_type, object_entity_id) triple.

3. For each unique triple:
   a. Acquire pg_try_advisory_xact_lock(hash(triple)) — prevents concurrent workers
      from racing on the same triple during horizontal scale-out.
   b. INSERT INTO relation_evidence (relation_id, ...) for each raw row
      (move evidence to permanent table).
   c. UPSERT INTO relations (subject_entity_id, canonical_type, object_entity_id, ...)
      SET evidence_count += N, confidence_stale = true,
          latest_evidence_at = max(extracted_at for this batch).
   d. Mark raw rows as processed = true, processed_at = now().

4. Commit transaction.
5. Sleep RELATION_AGGREGATION_INTERVAL_SECONDS (ENV var, default 300).
```

**PostgreSQL write contention under horizontal scale-out:**

See Section C.1 for full investigation. Summary of recommendation:

- v1 (single aggregation worker): advisory locks on triple hash suffice.
- v2 (multiple aggregation workers): hash-partition `relations` table by `subject_entity_id` into N partitions. Assign partition ownership to workers via Kafka partition key = `hash(subject_entity_id) % N`. No two workers own the same partition, eliminating lock contention entirely without distributed locks.
- Do NOT rely on managed Postgres read replicas — replicas do not solve write contention, only read fan-out.

**Query-time reads during aggregation lag:**

Consumers should read: `relations` (aggregate) UNION `relation_evidence_raw WHERE processed = false AND extracted_at > now() - (RELATION_AGGREGATION_INTERVAL_SECONDS * 2)`.

This provides a best-known-state view without waiting for next flush. The query layer must handle potential duplicates from the UNION (deduplicate by triple).

**Environment variables:**

```
RELATION_AGGREGATION_INTERVAL_SECONDS=300   # flush cadence
RELATION_AGGREGATION_BATCH_SIZE=500         # rows per worker cycle
RELATION_AGGREGATION_WORKERS=1              # v1: always 1
```

#### Pros / Cons

| Aspect | Pro | Con |
|--------|-----|-----|
| Cheap raw writes | No contention on staging table | Adds latency before relation is aggregated |
| Advisory locks | Safe concurrent aggregation per triple | Lock acquisition overhead at high cardinality |
| Hash partitioning (v2) | Linear scale-out, no cross-worker contention | Requires partition-aware routing in S7 |
| Query UNION pattern | Near-real-time reads without waiting for flush | Query complexity increases |

#### Impact on Ingestion Pipeline

S6 writes to `relation_evidence_raw` at full speed without any lock contention. Aggregation latency is `RELATION_AGGREGATION_INTERVAL_SECONDS`, not ingestion latency.

#### Impact on Query Pipeline

Query must merge `relations` + recent `relation_evidence_raw` rows. Confidence on raw rows is not yet batch-computed — query layer must treat raw-row confidence as extraction_confidence only (no corroboration/decay applied). Freshness flag must be returned to the caller.

#### Remaining Open Questions

- At what batch size does advisory lock acquisition become a bottleneck? (requires benchmarking)
- Should `relation_evidence_raw` be a partitioned table (by extracted_at monthly) to keep it small?
- How should the aggregation worker handle extraction_confidence outliers (e.g., a 0.99 confidence claim from an LLM that is clearly hallucinated)?

---

### B.2 — Confidence Recomputation

#### Current Problem

Single batch cadence (every 15 minutes), no differentiation by how quickly a relation type's validity decays. Formula uses `days_since_latest_evidence` as a single recency scalar, which gives equal weight to a 10-year-old evidence record and a 9-year-old one while dramatically penalizing 90-day-old evidence. Old contradictions maintain their full penalty indefinitely.

#### Accepted Direction

Recompute in batches at different cadences depending on `decay_class`. Incorporate per-evidence temporal weighting. Old low-quality evidence decays naturally. Old contradictory evidence also decays.

#### Revised Proposal

**Temporal decay classes and recomputation intervals:**

| decay_class | Half-life | Recompute interval | Example relation types |
|-------------|-----------|-------------------|------------------------|
| PERMANENT   | ∞         | On new evidence only (event-driven) | founded_in, headquartered_in |
| DURABLE     | 5 years   | Weekly | regulatory_capital_requirement, credit_rating |
| SLOW        | 1 year    | Daily | strategic_partnership, board_membership |
| MEDIUM      | 90 days   | Every 6 hours | supplier_of, employs, market_share_claim |
| FAST        | 14 days   | Every 1 hour | analyst_rating, price_target, guidance_claim |
| EPHEMERAL   | 1 day     | Every 15 minutes | intraday_sentiment, short_term_signal |

**Decay alpha per class** (for `exp(-alpha * days)`):

```
PERMANENT:  alpha = 0.0
DURABLE:    alpha = ln(2) / (5 * 365) ≈ 0.000380
SLOW:       alpha = ln(2) / 365 ≈ 0.001899
MEDIUM:     alpha = ln(2) / 90  ≈ 0.007701
FAST:       alpha = ln(2) / 14  ≈ 0.049510
EPHEMERAL:  alpha = ln(2) / 1   ≈ 0.693147
```

**Revised confidence formula:**

```
For relation R with evidence set E = {e1, ..., en} and contradiction set C = {c1, ..., cm}:

temporal_weight(e) = exp(-alpha_R * days(now, e.extracted_at))
quality_weight(e)  = e.extraction_confidence * source_trust(e.source_type)

evidence_score = sum(temporal_weight(e) * quality_weight(e) for e in E)
               / max(1, sum(temporal_weight(e) for e in E))   -- normalized average

corroboration_factor = log(1 + count_distinct_weighted_sources(E, temporal_weight))
                     * CORROBORATION_WEIGHT

contradiction_score = sum(
    temporal_weight(c.detected_at) * c.strength
    for c in C if c.invalidated_at IS NULL
  ) / max(1, count_active_contradictions)

recency_bonus = exp(-alpha_R * days(now, max(e.extracted_at for e in E)))

confidence = base_type_confidence(R.canonical_type)
           * evidence_score
           * (1 + corroboration_factor)
           * recency_bonus
           * max(0, 1 - contradiction_score)
```

This formula has the following properties:
- Old evidence contributes negligibly (temporal_weight → 0)
- Old contradictions decay (their temporal_weight → 0 as time passes)
- Corroboration is weighted by source diversity AND evidence recency
- PERMANENT relations use alpha = 0, so temporal_weight = 1.0 always (no decay)

**Scheduling model (APScheduler in S7):**

```python
scheduler.add_job(recompute_class, 'interval', minutes=15,
                  kwargs={'decay_class': 'EPHEMERAL'})
scheduler.add_job(recompute_class, 'interval', hours=1,
                  kwargs={'decay_class': 'FAST'})
scheduler.add_job(recompute_class, 'interval', hours=6,
                  kwargs={'decay_class': 'MEDIUM'})
scheduler.add_job(recompute_class, 'interval', hours=24,
                  kwargs={'decay_class': 'SLOW'})
scheduler.add_job(recompute_class, 'interval', days=7,
                  kwargs={'decay_class': 'DURABLE'})
# PERMANENT: triggered only by entity.dirtied.v1
```

**Worker query per cadence run:**

```sql
SELECT r.relation_id, r.decay_class, r.subject_entity_id, r.object_entity_id
FROM relations r
WHERE r.decay_class = :decay_class
  AND r.confidence_stale = true
ORDER BY r.latest_evidence_at DESC
LIMIT :batch_size
FOR UPDATE SKIP LOCKED;
```

After computing new confidence, update `confidence`, `confidence_last_computed_at`, `confidence_stale = false`.

**Query-time freshness:**

Relations with `confidence_stale = true` should be served with a `confidence_freshness = 'stale'` flag. Callers can request recomputation on-demand for critical queries (via a lightweight synchronous path) or accept stale confidence.

#### Remaining Open Questions

- Should `base_type_confidence` per canonical relation type be a stored constant or a learned value?
- How should the corroboration_weight be tuned initially? (Suggest: 0.15 as starting value)
- Should PERMANENT relations ever recompute on the weekly batch as a safety net, even when not stale?

---

### B.3 — Contradiction Modeling and Worker Architecture

#### Current Problem

Contradiction detection is inline on the S6 NLP hot path. As the `claims` table grows, the contradiction query (scanning for matching subject + claim_type + opposite polarity within 90 days) slows ingestion. There is no explicit linkage between a detected contradiction and the specific `relation_evidence` rows it affects. Contradiction penalty in the confidence formula is a global count, not a weighted per-link score.

#### Accepted Direction

Move contradiction detection to an async worker. Explicitly link `relation_evidence` to `claims` through a dedicated linkage table. Contradiction strength decays over time via `temporal_weight`.

#### Revised Proposal

**Schema:**

```sql
CREATE TABLE relation_contradiction_links (
    link_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_evidence_id  UUID NOT NULL REFERENCES relation_evidence(evidence_id),
    claim_id              UUID NOT NULL REFERENCES claims(claim_id),
    contradiction_type    VARCHAR(50) NOT NULL,
    -- POLARITY_CONFLICT: same claim_type, opposite polarity
    -- FACTUAL_CONFLICT: same subject, mutually exclusive claim values
    -- TEMPORAL_OVERLAP: conflicting during same time window
    strength              FLOAT NOT NULL DEFAULT 1.0,  -- [0,1]
    detected_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    temporal_weight       FLOAT NOT NULL,  -- exp(-alpha * days) at detection time (cached)
    invalidated_at        TIMESTAMPTZ,     -- when the contradiction is itself resolved
    invalidation_reason   TEXT,
    UNIQUE (relation_evidence_id, claim_id)
);

CREATE INDEX idx_rcl_relation_evidence ON relation_contradiction_links (relation_evidence_id)
    WHERE invalidated_at IS NULL;
CREATE INDEX idx_rcl_claim ON relation_contradiction_links (claim_id)
    WHERE invalidated_at IS NULL;
```

**Contradiction worker design:**

```
Consumer: reads nlp.signal.detected.v1 (claims emitted by S6 deep extraction)

For each new claim C with (subject_entity_id, claim_type, polarity, created_at):

1. Query matching claims:
   SELECT claim_id, polarity, claimer_entity_id, created_at
   FROM claims
   WHERE subject_entity_id = C.subject_entity_id
     AND claim_type = C.claim_type
     AND polarity != C.polarity
     AND polarity != 'neutral'
     AND C.polarity != 'neutral'
     AND created_at > now() - INTERVAL '90 days'
     AND claim_id != C.claim_id;
   (Uses idx_claims_contradiction_detection from PRD v4)

2. For each matching claim M:
   a. Find relation_evidence rows that cite M.claim_id:
      SELECT evidence_id FROM relation_evidence WHERE claim_id = M.claim_id;
   b. For each evidence row E:
      INSERT INTO relation_contradiction_links (
          relation_evidence_id = E.evidence_id,
          claim_id = C.claim_id,
          contradiction_type = 'POLARITY_CONFLICT',
          strength = compute_strength(C, M),  -- e.g., 1.0 if direct polarity flip
          detected_at = now(),
          temporal_weight = exp(-alpha_for_decay_class * 0)  -- fresh = 1.0
      ) ON CONFLICT (relation_evidence_id, claim_id) DO NOTHING;

3. For each relation containing affected evidence:
   UPDATE relations SET confidence_stale = true
   WHERE relation_id IN (
       SELECT DISTINCT re.relation_id
       FROM relation_evidence re
       WHERE re.claim_id = M.claim_id
   );

4. Emit intelligence.contradiction.v1 to outbox:
   {subject_entity_id, claim_type, contradicting_claim_ids, affected_relation_ids, detected_at}
```

**Idempotency:** `UNIQUE(relation_evidence_id, claim_id)` with `ON CONFLICT DO NOTHING` makes the worker safe to replay. Downstream relation confidence recomputation is triggered by `confidence_stale = true`, which is also idempotent.

**Contradiction erosion over time:**

When the confidence formula reads active contradiction links, it computes `temporal_weight` dynamically:

```
current_temporal_weight(link) = exp(-alpha_medium * days(now, link.detected_at))
```

This means a contradiction detected 90 days ago contributes only ~50% of its original strength, preventing stale contradictions from permanently suppressing relation confidence.

**Worker cadence:** ENV var `CONTRADICTION_WORKER_BATCH_INTERVAL_SECONDS` (default: 30). Worker processes a batch of N new claims per cycle. `CONTRADICTION_WORKER_BATCH_SIZE` (default: 100).

#### Impact on Ingestion Pipeline

S6 hot path no longer runs contradiction queries. Contradiction detection lag = worker batch interval (default 30 seconds). This is acceptable — contradictions affect confidence, not whether a document is ingested.

#### Impact on Query Pipeline

At query time, if a relation has active contradiction links, the confidence formula includes the contradiction penalty. The query response can surface contradiction metadata (which claims contradict, when detected, current strength) for auditability.

#### Remaining Open Questions

- How should `strength` be computed? A polarity flip between two high-confidence claims should score higher than low-confidence claims. Suggest: `strength = min(C.extraction_confidence, M.extraction_confidence)`.
- Should the worker also detect contradictions between `relation_evidence` rows directly (not mediated by claims)?
- When should a contradiction link be `invalidated_at`? Propose: when one of the two claims gets a superseding claim with higher confidence from the same claimer, or by explicit operator action.

---

### B.4 — Raw Ingestion + Deduplication (Valkey LSH Two-Tier Model)

#### Current Problem

LSH bands are stored in-memory, rebuilt on S5 startup (2–5 min dedup blind spot, ~768MB). Window is a single global 30-day window regardless of source type. Near-duplicate suppression treats all sources equally, discarding potentially corroborating evidence from a different outlet that happens to describe the same event. Char 5-gram shingling is fragile for financial text (ticker symbols, number strings produce false similarity).

#### Accepted Direction

Store LSH bands in Valkey with TTL-based sliding windows. Window duration varies by source type. Two-tier dedup: Tier 1 fast LSH candidate generation, Tier 2 exact similarity + optional embedding check for borderline cases. Corroborating evidence from different sources is preserved.

#### Revised Proposal

**Shingling strategy — word bigrams + char 3-grams (weighted):**

```python
def compute_shingles(text: str) -> set[str]:
    tokens = normalize_financial_text(text)  # lowercase, remove punctuation
    word_bigrams = {f"w:{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens)-1)}
    char_trigrams = {f"c:{text[i:i+3]}" for i in range(len(text)-3)}
    # Word bigrams capture meaning; char trigrams handle typos/OCR artifacts
    return word_bigrams | char_trigrams
```

Word bigrams capture semantic structure; char trigrams handle OCR artifacts and ticker formatting variation.

**Valkey LSH storage:**

```
Key:   lsh:band:{band_id}:{bucket_hash}:{source_type}
Value: Sorted set of (doc_id, extracted_at timestamp as score)
TTL:   window_seconds[source_type]
```

Window durations by source type:

| Source type | LSH window | Rationale |
|-------------|------------|-----------|
| NEWS        | 7 days     | Breaking news cycle; duplicate window is short |
| FILINGS     | 180 days   | SEC amendments reference original filing text |
| TRANSCRIPTS | 60 days    | Re-published transcripts after corrections |
| RESEARCH    | 30 days    | Research notes updated/revised |
| PRESS_RELEASE | 14 days  | Short PR cycle |

Jaccard thresholds by source type:

| Source type | Hard duplicate threshold | Soft threshold (for Tier 2) |
|-------------|--------------------------|------------------------------|
| NEWS        | 0.72                     | 0.55                         |
| FILINGS     | 0.85                     | 0.70                         |
| TRANSCRIPTS | 0.75                     | 0.60                         |
| RESEARCH    | 0.70                     | 0.55                         |

**Tier 1 — Fast LSH candidate lookup:**

```python
def find_lsh_candidates(doc_signature, source_type) -> list[str]:
    # For each of B bands, compute bucket hash, query Valkey ZRANGEBYSCORE
    # within the time window for this source_type
    window_start = now() - WINDOW_SECONDS[source_type]
    candidates = []
    for band_id in range(NUM_BANDS):  # 4 bands × 32 rows = 128 permutations
        bucket_hash = compute_band_hash(doc_signature, band_id)
        key = f"lsh:band:{band_id}:{bucket_hash}:{source_type}"
        candidates += valkey.zrangebyscore(key, window_start.timestamp(), "+inf")
    return deduplicate(candidates)
```

**Tier 2 — Batch exact Jaccard + optional embedding similarity:**

```python
def check_duplicates(doc_id, candidates, doc_signature, source_type):
    if not candidates:
        return DedupResult.UNIQUE

    # Fetch all candidate signatures in one PostgreSQL query
    sigs = db.query(
        "SELECT doc_id, minhash_signature FROM minhash_signatures WHERE doc_id = ANY(:ids)",
        ids=candidates
    )

    results = []
    for cand in sigs:
        jaccard = compute_exact_jaccard(doc_signature, cand.minhash_signature)
        hard_threshold = HARD_THRESHOLD[source_type]
        soft_threshold = SOFT_THRESHOLD[source_type]

        if jaccard >= hard_threshold:
            # Hard duplicate — check source
            if cand.source_id == doc.source_id:
                results.append((cand.doc_id, jaccard, 'SAME_SOURCE_DUPLICATE'))
            else:
                results.append((cand.doc_id, jaccard, 'CORROBORATING'))
        elif jaccard >= soft_threshold:
            # Borderline — compute embedding similarity
            emb_sim = compute_embedding_cosine(doc.embedding, cand.embedding)
            combined = 0.70 * jaccard + 0.30 * emb_sim
            if combined >= hard_threshold:
                results.append((cand.doc_id, combined, 'SEMANTIC_NEAR_DUPLICATE'))
    return classify_results(results)
```

**Corroborating evidence rule:**

- `SAME_SOURCE_DUPLICATE`: suppress the newer document (same outlet, same story).
- `CORROBORATING`: retain both documents. Mark with `corroborates_doc_id` foreign key. Route at least as `light` regardless of novelty gate (corroboration has graph value).
- `SEMANTIC_NEAR_DUPLICATE`: retain both if different source. Mark with `semantic_similarity_score`. Routing score receives a novelty penalty (lower novelty_signal) but document is not suppressed.

**Preserving corroborating evidence for graph quality:**

Corroborating documents from different sources should produce distinct `relation_evidence` rows. This strengthens the `corroboration_factor` in the confidence formula. Suppressing cross-source near-duplicates would systematically undercount corroboration, deflating confidence on real high-certainty relations.

**Semantic dedup (separate concept, not a suppression gate):**

Embedding-based semantic similarity detection runs as a background annotation job, not a real-time gate. Its output (`semantic_similarity_score` on the document) informs routing and novelty but does not trigger deletion.

**Updating Valkey after decision:**

```python
if decision != SAME_SOURCE_DUPLICATE:
    for band_id in range(NUM_BANDS):
        bucket_hash = compute_band_hash(doc_signature, band_id)
        key = f"lsh:band:{band_id}:{bucket_hash}:{source_type}"
        valkey.zadd(key, {doc_id: now().timestamp()})
        valkey.expire(key, WINDOW_SECONDS[source_type])
```

#### Impact on Ingestion Pipeline

No startup rebuild delay. Valkey TTL handles window expiry automatically. Duplicate check adds ~5–10ms Valkey round-trips + one PostgreSQL batch query. Total dedup overhead target: < 20ms per document.

#### Impact on Query Pipeline

`corroborates_doc_id` links allow query-time evidence deduplication — when surfacing multiple evidence records for the same relation, corroborating documents can be grouped rather than returned as independent items. This prevents the retrieval output from being dominated by the same event covered by 15 news outlets.

#### Remaining Open Questions

- Should `minhash_entity_mentions` be populated during dedup (Block 2) or only after entity resolution (Block 9)? See B.5 for recommendation: defer to post-resolution.
- How large will Valkey grow with 128 bands × source-type keys? Estimate: at 10,000 documents/day, with 7-day NEWS window = 70,000 documents × 128 bands × ~16 bytes/key entry ≈ 143MB for NEWS alone. Manageable within Valkey.
- Should band bucket hashes be stored per-document in Postgres for recovery? Suggest: yes, as a `minhash_band_hashes JSONB` column on `minhash_signatures`.

---

### B.5 — Two-Stage Novelty Gate

#### Current Problem

The PRD specifies a single novelty check using `minhash_entity_mentions` + `minhash_signatures`. This check runs post-dedup but the timing relative to entity resolution is unspecified. If it runs pre-resolution (using unresolved mention strings), it is fast but imprecise. If it runs post-resolution (using resolved entity_ids), it is accurate but adds resolution latency to the routing decision path. There is no mechanism to upgrade a document that Stage 1 downgrades.

#### Accepted Direction

Two-stage novelty gate: Stage 1 pre-resolution (cheap, approximate), Stage 2 post-resolution (corrective, authoritative). Stage 1 feeds initial routing tier. Stage 2 can upgrade or confirm a Stage 1 downgrade.

#### Revised Proposal

**Stage 1 — Pre-resolution novelty signal:**

Input: unresolved entity mentions (raw GLiNER output strings), document MinHash signature.

```python
def stage1_novelty(doc, unresolved_mentions) -> float:
    # Find candidate signatures that share unresolved mention strings
    # Approximate: match on normalized mention text, not canonical entity_id
    mention_hashes = [hash(normalize(m.text)) for m in unresolved_mentions]

    recent_doc_ids = db.query("""
        SELECT DISTINCT s.doc_id
        FROM minhash_signatures s
        JOIN minhash_entity_mentions mem ON s.sig_id = mem.sig_id
        WHERE mem.mention_text_hash = ANY(:hashes)
          AND s.created_at > now() - INTERVAL '7 days'
        LIMIT 100
    """, hashes=mention_hashes)

    if not recent_doc_ids:
        return 1.0  # No prior coverage — high novelty

    # Compute max Jaccard against recent docs for these entities
    max_sim = max(jaccard(doc.signature, fetch_sig(d)) for d in recent_doc_ids)
    return 1.0 - max_sim  # Novelty = inverse similarity
```

This requires `minhash_entity_mentions` to store `mention_text_hash` (the normalized unresolved string hash) as a pre-resolution field, separate from (or in addition to) the resolved `entity_id`.

**Stage 2 — Post-resolution corrective novelty:**

Input: resolved entity_ids, document embedding, extracted events/claim types.

```python
def stage2_novelty(doc, resolved_entity_ids, extracted_event_types) -> NoveltyCorrectionSignal:
    signals = {}

    # 2a. Entity-anchored MinHash novelty (post-resolution, precise)
    for entity_id in resolved_entity_ids:
        recent_sigs = db.query("""
            SELECT s.sig_id FROM minhash_signatures s
            JOIN minhash_entity_mentions mem ON s.sig_id = mem.sig_id
            WHERE mem.entity_id = :eid
              AND s.created_at > now() - :window
            LIMIT 50
        """, eid=entity_id, window=entity_novelty_window(entity_id))
        # compute per-entity max_similarity, store min novelty across entities
        signals['entity_minhash'] = 1 - max_entity_similarity(doc.signature, recent_sigs)

    # 2b. Embedding neighborhood novelty (ANN)
    nn_distances = embedding_index.query(doc.section_embedding, k=10)
    signals['embedding_novelty'] = min(nn_distances)  # large distance = high novelty

    # 2c. Event structure novelty
    # Does this claim_type + entity_pair already have recent evidence in relations?
    signals['event_novelty'] = check_event_structure_novelty(
        resolved_entity_ids, extracted_event_types
    )

    return NoveltyCorrectionSignal(
        upgrade=signals['event_novelty'] > EVENT_NOVELTY_UPGRADE_THRESHOLD,
        final_novelty=weighted_average(signals, NOVELTY_SIGNAL_WEIGHTS)
    )
```

**Decision flow:**

```
Stage 1 output → pre_novelty_score → feeds routing signal (initial tier assignment)

After entity resolution + extraction:
Stage 2 output:
  - If upgrade=True and current_tier == 'light' → upgrade to 'medium'
  - If upgrade=True and current_tier == 'suppress' → upgrade to 'light'
  - If upgrade=False → confirm current tier
  - Final novelty_signal value overwrites Stage 1 in routing metadata
```

**minhash_entity_mentions schema revision:**

```sql
CREATE TABLE minhash_entity_mentions (
    sig_id             UUID NOT NULL REFERENCES minhash_signatures(sig_id) ON DELETE CASCADE,
    entity_id          UUID,          -- nullable: populated in Stage 2 post-resolution
    mention_text_hash  BIGINT,        -- hash of normalized mention string: Stage 1 input
    mention_text       VARCHAR(200),  -- raw mention string (for debugging)
    resolution_status  VARCHAR(20) DEFAULT 'UNRESOLVED',  -- UNRESOLVED | RESOLVED | FAILED
    PRIMARY KEY (sig_id, mention_text_hash)
);

CREATE INDEX idx_mem_entity_id ON minhash_entity_mentions (entity_id, sig_id)
    WHERE entity_id IS NOT NULL;
CREATE INDEX idx_mem_mention_text_hash ON minhash_entity_mentions (mention_text_hash);
```

This allows Stage 1 to query by `mention_text_hash` (pre-resolution) and Stage 2 to query by `entity_id` (post-resolution), in separate index paths.

**Deferring entity_id population:**

After Block 9 (entity resolution), update `minhash_entity_mentions`:
```sql
UPDATE minhash_entity_mentions
SET entity_id = :resolved_id,
    resolution_status = 'RESOLVED'
WHERE sig_id = :sig_id
  AND mention_text_hash = :hash;
```

#### Impact on Ingestion Pipeline

Stage 1 adds ~5–15ms (one PostgreSQL query on indexed mention hashes). Stage 2 adds ~20–40ms (ANN query + relation existence check). Total novelty gate overhead: < 60ms, acceptable in a pipeline where LLM extraction takes seconds.

#### Impact on Query Pipeline

`event_novelty` from Stage 2 is a strong signal for query relevance. A document with high event_novelty contains something that is genuinely new in the graph — it is a high-value retrieval candidate. The query layer should consider `event_novelty_score` as a ranking signal.

#### Remaining Open Questions

- What is `entity_novelty_window(entity_id)`? Suggest: derive from the entity's most active sector. High-velocity entities (major tech companies) → 3-day window. Low-activity entities → 30-day window.
- Should Stage 1 use a simpler bloom filter instead of the hash lookup, trading recall for sub-1ms latency?
- How to handle documents with zero resolved entities in Stage 2? Fall back to Stage 1 signal only.

---

### B.6 — GLiNER / Entity Detection

#### Current Problem

The current entity class list includes `event_type`, which is semantically incorrect (events are not entities). `institution` is too broad, conflating corporations, governments, central banks, and regulatory agencies. Missing financially critical classes: `commodity`, `macroeconomic_indicator`, `index`, `currency`. Confidence scores are uncalibrated — GLiNER's raw output probability is not a reliable proxy for true precision at a given threshold. No non-maximum suppression (NMS) for overlapping spans.

#### Accepted Direction

Refine ontology, remove event_type, add missing classes, implement confidence calibration, implement NMS. Treat GLiNER as a supportive signal extractor, not a gating model.

#### Revised Proposal

**Revised entity class ontology:**

| Class | Description | Rationale |
|-------|-------------|-----------|
| `organization` | Companies, subsidiaries, joint ventures | Core class; rename from `institution` |
| `government_body` | Federal agencies, central banks, ministries | Split from `institution` |
| `regulatory_body` | SEC, CFTC, ECB, FDA | Split from `institution`; distinct from government |
| `financial_institution` | Banks, hedge funds, asset managers | Split from `institution` |
| `person` | Named individuals (executives, analysts, officials) | Keep |
| `financial_instrument` | Stocks, bonds, ETFs, options | Keep |
| `location` | Countries, cities, regions | Keep |
| `commodity` | Crude oil, natural gas, gold, wheat, lithium | Add: critical for supply-chain signals |
| `macroeconomic_indicator` | GDP, CPI, interest rate, unemployment rate | Add: macro signal extraction |
| `index` | S&P 500, NASDAQ, Nikkei, FTSE | Add: benchmark references common in filings |
| `currency` | USD, EUR, JPY, BTC | Add: FX exposure common in transcripts |
| `technology_platform` | GPU, AI accelerator, chiplet, cloud platform | Add: for tech/supply-chain research |

**Removed:**
- `event_type` — events (earnings, merger, lawsuit) are temporal structures, not entities. They are extracted by the LLM extraction block (Block 10). GLiNER should not detect them.

**Why institution split matters for routing:**

If `institution` is used to count entity density for the routing score, a filing that mentions "the Federal Reserve" once and "JP Morgan" twice produces the same density count as a filing mentioning three separate companies. After the split, the routing score can weight `organization` mentions more heavily than `regulatory_body` mentions (organizations are more likely to generate relation evidence).

**Span overlap and NMS:**

```python
def apply_nms(spans: list[Span], iou_threshold=0.5) -> list[Span]:
    # Sort by confidence descending
    spans = sorted(spans, key=lambda s: s.confidence, reverse=True)
    kept = []
    for span in spans:
        overlaps = [s for s in kept if overlap_ratio(s, span) > iou_threshold]
        if not overlaps:
            kept.append(span)
        # If overlapping with a higher-confidence span, discard
    return kept
```

Apply NMS per section before passing mentions to entity resolution. This prevents "TSMC" and "Taiwan Semiconductor Manufacturing" in the same sentence from generating two separate mentions that each propagate to resolution.

**Confidence calibration:**

Calibration is required if GLiNER confidence directly feeds the routing score. Without calibration, a threshold of 0.4 may have precision of 0.62 for `organization` but only 0.41 for `macroeconomic_indicator`.

Calibration approach for v1:
- Temperature scaling (Platt scaling): fit a single scalar `T` such that `p_calibrated = sigmoid(logit(p_raw) / T)` on a held-out labeled set.
- Per-class calibration: fit separate T per entity class. Require at minimum 500 labeled examples per class.
- If no labeled data is available at v1: use threshold tuning instead. Set per-class minimum confidence thresholds derived from manual review of 50–100 examples per class.

**GLiNER role in the pipeline:**

GLiNER is a supportive signal extractor. It:
1. Provides entity mentions for Stage 1 novelty (pre-resolution).
2. Provides entity_density_signal for routing.
3. Seeds entity resolution candidates (Block 9).

GLiNER does NOT:
- Gate document flow by itself.
- Determine entity confidence in the graph (that comes from Block 9 resolution and Block 10 LLM extraction).
- Replace the LLM extraction block for events/claims.

**Batch size and GPU optimization:**

Current PRD specifies batch size 16. For GPU inference:
- GLiNER (gliner_large-v2.1, 0.4B): optimal batch size 32–64 for A100, 16–32 for RTX 3090/4090.
- Increase batch size to 32 for v1 (local GPU). Make configurable via `GLINER_BATCH_SIZE` ENV var.

#### Impact on Ingestion Pipeline

More precise entity classes reduce false entity_density inflation. NMS reduces duplicate mention propagation to resolution. Calibrated confidence thresholds reduce resolution workload (fewer low-confidence mentions sent to the resolution cascade).

#### Impact on Query Pipeline

Richer entity class ontology enables class-filtered retrieval. A query for "commodity mentions in filings" can filter by `entity_class = 'commodity'`. Without this class, such queries are impossible at index time.

#### Remaining Open Questions

- Should `sector` (semiconductor, automotive, healthcare) be a GLiNER class? Risk: sectors are often implied, not named. Suggest: omit from v1, add if needed for routing signal.
- Should GLiNER run per-section (current) or per-document? Per-section is correct — entity salience varies by section.
- At what confidence threshold should a GLiNER mention be passed to Stage 1 novelty vs discarded? Suggest: 0.35 (lower than resolution threshold, to cast a wider novelty net).

---

### B.7 — Routing Score (Additive Normalized Formulation)

#### Current Problem

The previous multiplicative routing formula amplifies small variations non-linearly. The `watchlist_boost` factor was unbounded (0.3 × count, no cap). Long documents were penalized by a length factor even though longer SEC filings tend to have higher extraction value. A forced `deep` override for all SEC documents was wasteful (an SEC 8-K with zero named entities still consumed LLM capacity). Hard thresholds produced cliff-edge tier transitions.

#### Accepted Direction

Additive normalized formulation with seven signals. Weights sum to 1.0. Signals are normalized to [0, 1]. Hysteresis bands at tier boundaries. Document type as one weighted signal, not an override.

#### Revised Proposal

**Scoring formula:**

```
routing_score =
    w_entity    * entity_density_signal
  + w_source    * source_reliability_signal
  + w_novelty   * novelty_signal         (Stage 1 output)
  + w_recency   * recency_signal
  + w_watchlist * watchlist_signal
  + w_doctype   * document_type_signal
  + w_yield     * extraction_yield_signal
```

**Default weights (tunable per ENV or config table):**

| Signal | Weight | Rationale |
|--------|--------|-----------|
| entity_density | 0.30 | No entities = no graph value; highest discriminator |
| source_reliability | 0.20 | Source quality strongly predicts extraction precision |
| novelty | 0.15 | Redundant coverage is waste |
| recency | 0.10 | Stale documents contribute less to live graph |
| watchlist | 0.10 | Watchlisted entities justify extra processing cost |
| document_type | 0.10 | Filings/transcripts structurally richer than press releases |
| extraction_yield | 0.05 | Heuristic for expected LLM output quality |

**Signal definitions:**

```python
def entity_density_signal(gliner_mentions, doc_length_tokens) -> float:
    # Normalize by saturation threshold to prevent unbounded growth
    org_mentions = count_by_class(gliner_mentions, ['organization', 'financial_institution'])
    saturation = ENTITY_DENSITY_SATURATION  # e.g. 15 distinct organizations
    return min(1.0, org_mentions / saturation)

def source_reliability_signal(source_type, source_id) -> float:
    return source_trust_weights[source_type]  # from source_trust_weights table

def novelty_signal(stage1_novelty_score) -> float:
    return stage1_novelty_score  # already [0,1]

def recency_signal(published_at) -> float:
    hours_ago = (now() - published_at).total_seconds() / 3600
    return exp(-RECENCY_LAMBDA * hours_ago)
    # RECENCY_LAMBDA = 0.02 → half-life ≈ 35 hours

def watchlist_signal(gliner_mentions, active_watchlist_entity_ids) -> float:
    matched = count_watchlist_overlap(gliner_mentions, active_watchlist_entity_ids)
    return min(1.0, matched / WATCHLIST_SATURATION)  # saturate at e.g. 3 matches

def document_type_signal(doc_type) -> float:
    type_weights = {
        'sec_8k':          0.95,
        'sec_10k':         0.90,
        'sec_10q':         0.85,
        'earnings_call':   0.80,
        'analyst_report':  0.75,
        'news_article':    0.55,
        'press_release':   0.40,
        'blog_post':       0.25,
    }
    return type_weights.get(doc_type, 0.50)

def extraction_yield_signal(doc, gliner_mentions) -> float:
    # Heuristic: structured documents (many sections, high entity density) tend
    # to yield more extraction per LLM call
    section_count_signal = min(1.0, doc.section_count / 8)
    avg_section_length_ok = (150 <= doc.avg_section_length_tokens <= 600)
    return 0.6 * (len(gliner_mentions) / 20) + 0.4 * (section_count_signal if avg_section_length_ok else 0.3)
```

**Tier thresholds with hysteresis:**

```
Tier boundaries (initial values):
  suppress:  score < 0.20
  light:     0.20 <= score < 0.45
  medium:    0.45 <= score < 0.70
  deep:      score >= 0.70

Hysteresis bands (prevents oscillation at boundary):
  If current_tier = 'deep':    downgrade to 'medium' only if score < 0.62 for 2 consecutive evaluations
  If current_tier = 'medium':  downgrade to 'light'  only if score < 0.38 for 2 consecutive evaluations
  If current_tier = 'light':   upgrade to 'medium'   if score >= 0.48
  If current_tier = 'medium':  upgrade to 'deep'     if score >= 0.72
```

Note: for the first evaluation of a document (no prior tier), hysteresis is not applied.

**Why remove the SEC forced-deep override:**

The `document_type_signal` for `sec_8k = 0.95` combined with high `entity_density_signal` (most 8-Ks mention companies explicitly) will naturally push SEC filings to 0.70+ score, landing in `deep` without an override. A genuinely empty 8-K (boilerplate only, no entities) will correctly land at `medium`, saving LLM capacity. This is the right behavior.

**v1 vs learned ranker:**

v1: rules-based as specified above. Signals are interpretable and tunable.

Future (v2+): Train a lightweight binary classifier (LightGBM or logistic regression) on:
```
features: [entity_density, source_reliability, novelty, recency, watchlist, doc_type, extraction_yield]
label:     graph_update_value > threshold
           (derived from: did processing this doc produce ≥1 new high-confidence relation?)
```

This requires logging routing features per document + downstream extraction outcomes, which the v1 system should do as observability data even if the classifier is not yet trained.

**ENV vars:**

```
ROUTING_WEIGHT_ENTITY_DENSITY=0.30
ROUTING_WEIGHT_SOURCE=0.20
ROUTING_WEIGHT_NOVELTY=0.15
ROUTING_WEIGHT_RECENCY=0.10
ROUTING_WEIGHT_WATCHLIST=0.10
ROUTING_WEIGHT_DOCTYPE=0.10
ROUTING_WEIGHT_YIELD=0.05
ROUTING_THRESHOLD_DEEP=0.70
ROUTING_THRESHOLD_MEDIUM=0.45
ROUTING_THRESHOLD_LIGHT=0.20
ROUTING_HYSTERESIS_BAND=0.08
ENTITY_DENSITY_SATURATION=15
WATCHLIST_SATURATION=3
RECENCY_LAMBDA=0.02
```

#### Impact on Ingestion Pipeline

More accurate tier assignment reduces wasted LLM extraction cycles on low-value documents. Better novelty integration prevents reprocessing known content. Watchlist signal ensures user-relevant entities always receive adequate processing.

#### Impact on Query Pipeline

`routing_tier` per document is a query-time metadata field. The query layer can filter or downweight documents that were routed as `light` or `suppress` when the user requests high-confidence answers. Documents that are `deep`-processed have richer graph updates and more complete extraction — this should be surfaced in retrieval ranking.

#### Remaining Open Questions

- Should weights be stored in a `routing_config` table (runtime-tunable without redeploy) rather than ENV vars? Recommend: yes for production. ENV vars are sufficient for v1.
- How often should the routing score be logged for future classifier training? Suggest: always, in a `routing_audit` table with all signal values.
- Should document_type be detected automatically (from content structure) or always sourced from the adapter metadata? Suggest: adapter metadata is authoritative, content-based detection as fallback.

---

### B.8 — Embedding Generation and Vector-Space Maintenance

#### Current Problem

Fixed 50-token overlap cuts sentences mid-thought, producing chunks where the context boundary does not align with any natural unit of meaning. All chunk and section embeddings share the same HNSW index, causing retrieval pollution (section embeddings, which are longer and more diffuse, crowd out precise chunk matches). Document-level coarse embeddings are too unstable (one new sentence changes the whole vector). No TTL or pruning policy — vectors accumulate indefinitely, degrading retrieval quality and HNSW performance.

#### Accepted Direction

Sentence-aware overlap. Separate index per embedding granularity. TTL policy by source type. Relation-level summaries + embeddings investigated and proposed below (see B.11).

#### Revised Proposal

**Chunking strategy:**

| Source type | Target chunk size | Overlap strategy | Notes |
|-------------|------------------|-----------------|-------|
| NEWS | 256–300 tokens | Back up 2 complete sentences | Short paragraphs; keep sentences whole |
| FILINGS (10-K/10-Q) | 300–350 tokens | Back up 2 sentences; respect section headers | Never cross section header boundaries |
| EARNINGS CALL | Speaker-turn-aware | One turn = one chunk; split long turns at 300 tokens | Speaker context is the natural unit |
| PRESS RELEASE | 256 tokens | Back up 2 sentences | Similar to news |
| ANALYST REPORT | 300–350 tokens | Back up 2 sentences; section-aware | Similar to filings |

**Sentence-aware overlap implementation:**

```python
def chunk_with_sentence_overlap(tokens: list[str], target_size: int, nlp) -> list[Chunk]:
    sentences = nlp.sentencize(tokens)
    chunks = []
    current = []
    overlap_buffer = []  # last 2 sentences from previous chunk

    for sent in sentences:
        if len(current) + len(overlap_buffer) + len(sent) > target_size:
            chunks.append(Chunk(tokens=overlap_buffer + current))
            # New overlap: last 2 complete sentences of current chunk
            overlap_buffer = last_n_sentences(current, n=2)
            current = []
        current.extend(sent)

    if current:
        chunks.append(Chunk(tokens=overlap_buffer + current))
    return chunks
```

This guarantees overlap starts at a sentence boundary and ends at a sentence boundary. No sentence is split across a chunk boundary.

**Index separation (separate HNSW per granularity):**

```sql
-- Chunk embeddings: primary retrieval index (high-precision, short context)
CREATE TABLE chunk_embeddings (
    chunk_id          UUID PRIMARY KEY,
    document_id       UUID NOT NULL,
    section_id        UUID,
    chunk_index       INT NOT NULL,
    embedding         VECTOR(1024) NOT NULL,
    embedding_model   VARCHAR(200) NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT now(),
    expires_at        TIMESTAMPTZ,  -- NULL = retain forever
    source_type       VARCHAR(50)
);
CREATE INDEX hnsw_chunk_embeddings ON chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128)
    WHERE expires_at IS NULL OR expires_at > now();

-- Section embeddings: coarser retrieval (lower precision, higher recall)
CREATE TABLE section_embeddings (
    section_id        UUID PRIMARY KEY,
    document_id       UUID NOT NULL,
    section_type      VARCHAR(100),  -- 'risk_factors', 'md_and_a', 'discussion', etc.
    embedding         VECTOR(1024) NOT NULL,
    embedding_model   VARCHAR(200) NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT now(),
    expires_at        TIMESTAMPTZ
);
CREATE INDEX hnsw_section_embeddings ON section_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128)
    WHERE expires_at IS NULL OR expires_at > now();

-- Entity profile embeddings: entity-centric retrieval
CREATE TABLE entity_profile_embeddings (
    entity_id         UUID PRIMARY KEY REFERENCES canonical_entities(entity_id),
    embedding         VECTOR(1024) NOT NULL,
    embedding_model   VARCHAR(200) NOT NULL,
    profile_text      TEXT NOT NULL,
    embedding_stale   BOOLEAN DEFAULT false,
    last_refreshed_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX hnsw_entity_profile ON entity_profile_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE NOT embedding_stale;
```

Drop the document-level coarse embedding — it conflates sections with different topics and becomes stale any time the document is re-indexed.

**TTL and pruning policy by source type:**

| Source type | chunk_embeddings TTL | section_embeddings TTL | Rationale |
|-------------|---------------------|----------------------|-----------|
| NEWS | 90 days | 90 days | News loses relevance quickly |
| PRESS_RELEASE | 60 days | 60 days | Even shorter relevance cycle |
| FILINGS (10-K, 10-Q) | RETAIN FOREVER | RETAIN FOREVER | Historical record value |
| EARNINGS_CALL | 365 days | 365 days | Referenced for up to 4 quarters |
| ANALYST_REPORT | 180 days | 180 days | Superseded by next report |
| RESEARCH | 365 days | 365 days | Background reference value |

**Setting `expires_at` at write time:**

```python
expires_at = {
    'NEWS':            now() + timedelta(days=90),
    'PRESS_RELEASE':   now() + timedelta(days=60),
    'FILINGS':         None,   # Never expires
    'EARNINGS_CALL':   now() + timedelta(days=365),
    'ANALYST_REPORT':  now() + timedelta(days=180),
}.get(source_type, now() + timedelta(days=180))
```

**Pruning job (monthly):**

```sql
-- Soft-expire: mark as expired (fast)
UPDATE chunk_embeddings SET expires_at = now()
WHERE expires_at IS NOT NULL AND expires_at < now() AND source_type != 'FILINGS';

-- Hard-delete expired rows (background job, monthly)
DELETE FROM chunk_embeddings WHERE expires_at < now() - INTERVAL '7 days';

-- Rebuild HNSW index concurrently after significant deletion
REINDEX INDEX CONCURRENTLY hnsw_chunk_embeddings;
```

**Stale embeddings at query time:**

Entity profile embeddings with `embedding_stale = true` are still returned at query time (old vector is better than no vector). The response includes `embedding_freshness_days` = days since `last_refreshed_at`. Callers that require fresh vectors can request a synchronous refresh via an internal API.

**HNSW index bloat:**

pgvector HNSW does not support online deletion — deleted rows remain in the index until `REINDEX`. For source types with high churn (NEWS, PRESS_RELEASE), schedule monthly concurrent reindex. For FILINGS (never deleted), reindex annually or when `m` / `ef_construction` tuning changes.

#### Impact on Ingestion Pipeline

Sentence-aware overlap: adds ~10ms per document (sentence boundary detection). Separate indexes: no change to write path (different tables). TTL field is set at write time.

#### Impact on Query Pipeline

Separate indexes allow query to select granularity: chunk embeddings for precise passage retrieval, section embeddings for topic-level retrieval. This eliminates retrieval pollution from section embeddings crowding out chunk matches in a shared index.

#### Remaining Open Questions

- Should old NEWS chunk embeddings be archived to a cold table (slower index) rather than deleted, to support historical research queries?
- What is the HNSW `m` and `ef_construction` optimal setting for 1024-dim vectors at expected corpus sizes? (Requires benchmarking.)
- Should entity profile embeddings use a different model/dimension from chunk embeddings? (Suggest: same model for v1 — enables cross-granularity cosine comparison.)

---

### B.9 — Provider Abstraction

#### Current Problem

No adapter pattern is defined in the current PRD. `VECTOR(1024)` is hardcoded across all tables, making it impossible to switch to a model with a different output dimension without a migration. Model IDs, prompt templates, and output schemas are embedded in service code without versioning. There is no registry of what model is active for which capability. GLiNER has no hosted equivalent, and the pipeline is not designed to substitute it.

#### Accepted Direction

Python Protocol interfaces for all ML capabilities. Canonical input/output schemas decoupled from provider internals. `model_registry` table in `intelligence_db`. Prompt versioning in `prompt_templates` table. Conformance tests per provider adapter.

#### Revised Proposal

**Canonical internal schemas (dataclasses / Pydantic):**

```python
from dataclasses import dataclass
from typing import Literal, Any

@dataclass
class TextInput:
    text: str
    task: Literal["retrieval", "query", "classification", "extraction", "ner"]
    metadata: dict[str, Any]
    estimated_tokens: int  # platform-computed using tiktoken or char/4 fallback

@dataclass
class EmbeddingInput(TextInput):
    task: Literal["retrieval", "query"]

@dataclass
class EmbeddingOutput:
    vector: list[float]
    dimension: int
    model_id: str
    provider: str
    token_count: int | None  # provider-reported (may be None if not exposed)

@dataclass
class NERInput(TextInput):
    task: Literal["ner"]
    target_classes: list[str]
    min_confidence: float

@dataclass
class NERSpan:
    text: str
    start_char: int
    end_char: int
    entity_class: str
    confidence: float  # calibrated

@dataclass
class NEROutput:
    spans: list[NERSpan]
    model_id: str
    provider: str

@dataclass
class ExtractionInput(TextInput):
    task: Literal["extraction"]
    prompt_template_id: str
    prompt_template_version: int
    output_schema: dict   # JSON Schema for structured output validation

@dataclass
class ExtractionOutput:
    raw_json: dict          # model output parsed as JSON
    validated: bool         # whether output_schema validation passed
    model_id: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    extraction_confidence: float | None  # model self-reported, if available
```

**Protocol interfaces:**

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class EmbeddingClient(Protocol):
    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]: ...
    def model_info(self) -> ModelInfo: ...
    def estimate_tokens(self, text: str) -> int: ...  # provider-agnostic

@runtime_checkable
class NERClient(Protocol):
    async def detect(self, inputs: list[NERInput]) -> list[NEROutput]: ...
    def supported_classes(self) -> list[str]: ...
    def model_info(self) -> ModelInfo: ...

@runtime_checkable
class ExtractionClient(Protocol):
    async def extract(self, inputs: list[ExtractionInput]) -> list[ExtractionOutput]: ...
    def model_info(self) -> ModelInfo: ...

@dataclass
class ModelInfo:
    model_id: str
    provider: str
    capability: str  # EMBEDDING | NER | EXTRACTION | SUMMARIZATION
    dimension: int | None
    max_input_tokens: int
    version: str
    performance_tier: str  # PRIMARY | FALLBACK | EVALUATION
```

**Concrete adapters:**

```
OllamaEmbeddingAdapter   implements EmbeddingClient  → local bge-large-en-v1.5
OpenAIEmbeddingAdapter   implements EmbeddingClient  → text-embedding-3-large (dim=1024)
GLiNERLocalAdapter       implements NERClient        → gliner_large-v2.1
OllamaExtractionAdapter  implements ExtractionClient → Qwen2.5-7B-Instruct
AnthropicExtractionAdapter implements ExtractionClient → claude-sonnet-4-6
```

**Dimension compatibility:**

If the active `EmbeddingClient` changes from 1024-dim to 1536-dim, all existing HNSW indexes become incompatible. Mitigation:
- `model_registry` stores `dimension` per active model.
- Schema uses `VECTOR(:dimension)` with the dimension stored in `model_registry`.
- Shadow migration protocol (already defined in PRD v4) handles dimension changes: shadow column → dual write → backfill → cutover → cleanup.
- In practice: standardize on 1024-dim for v1 (bge-large = 1024, OpenAI text-embedding-3-large supports 1024 via truncation).

**model_registry table:**

```sql
CREATE TABLE model_registry (
    registry_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id         VARCHAR(200) NOT NULL,
    provider         VARCHAR(50)  NOT NULL,
    capability       VARCHAR(50)  NOT NULL,  -- EMBEDDING | NER | EXTRACTION
    version          VARCHAR(50),
    dimension        INT,          -- embedding models only
    max_input_tokens INT NOT NULL,
    is_active        BOOLEAN DEFAULT true,
    performance_tier VARCHAR(20) NOT NULL DEFAULT 'PRIMARY',
    config           JSONB,        -- endpoint URL, timeout, retry config
    registered_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (model_id, provider, version)
);
```

**prompt_templates table:**

```sql
CREATE TABLE prompt_templates (
    template_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             VARCHAR(200) NOT NULL,
    version          INT NOT NULL,
    capability       VARCHAR(50)  NOT NULL,
    template_text    TEXT NOT NULL,
    output_schema    JSONB NOT NULL,          -- JSON Schema for ExtractionOutput.raw_json
    model_constraints JSONB,                  -- {"compatible_models": ["qwen2.5-7b", "claude-*"]}
    is_active        BOOLEAN DEFAULT true,
    created_at       TIMESTAMPTZ DEFAULT now(),
    UNIQUE (name, version)
);
```

**Provider-specific differences to abstract away:**

| Concern | Abstract away | Preserve |
|---------|---------------|---------|
| HTTP endpoint format | Yes — adapter handles | No |
| Auth method (API key, local socket) | Yes — adapter handles | No |
| Tokenization (tiktoken vs BPE vs SentencePiece) | Estimate only (char/4 fallback) | Provider-reported token count preserved in output |
| Rate limits | Yes — adapter handles retries with backoff | Rate limit metadata exposed for observability |
| JSON output format variation | Yes — ExtractionOutput normalizes | No |
| Embedding dimension | Via model_registry dimension field | Yes — dimension is a property |
| Temperature/sampling params | In prompt_templates.model_constraints | No |

**Conformance test framework:**

For each (capability × provider) pair, define:
1. A set of canonical test inputs (golden inputs) stored in test fixtures.
2. Expected output shape assertions (not exact values — model outputs vary).
3. Schema validation: `ExtractionOutput.raw_json` must pass `output_schema` validation.
4. Latency threshold: p95 must be below provider-specific target (Ollama: 5s, API: 2s).
5. Dimension check: `len(EmbeddingOutput.vector) == model_registry.dimension`.

Run conformance tests:
- At adapter registration
- On provider config change
- In CI on any adapter code change

#### Impact on Ingestion Pipeline

Any provider can be swapped behind an adapter without changing pipeline logic. Prompt versioning allows A/B testing of extraction prompts without code changes.

#### Impact on Query Pipeline

Query-time embedding must use the same model as ingestion-time embedding. `model_registry` provides the active embedding model for both paths, ensuring consistency. If the embedding model changes, both ingestion and query paths switch simultaneously via registry update.

#### Remaining Open Questions

- Should adapters support streaming responses for LLM extraction? (Streaming complicates structured output parsing — suggest: no for v1.)
- How should the system handle a provider outage? Suggest: failover to FALLBACK tier model in model_registry if PRIMARY is unreachable after N retries.
- Should token estimation use a shared tokenizer library (tiktoken) or a per-provider estimate? Suggest: tiktoken with cl100k_base as the default estimator for all models. Provider-reported counts override when available.

---

### B.10 — Temporal Modeling

#### Current Problem

Current PRD conflates two distinct concepts: **relation validity** (is the relation still factually true?) and **confidence decay** (how much do we trust the evidence, given it ages?). The `valid_to` field is LLM-extracted, which is systematically unreliable — LLMs confuse evidence publication date with actual expiry date, hallucinate future expiry dates, and are unable to determine whether a relation is "still ongoing." Discrete temporal buckets (5 classes) are too coarse. There is no event-triggered invalidation mechanism.

#### Accepted Direction

Explicit separation of validity vs confidence decay. Discrete temporal classes with stored `decay_alpha` (allows per-relation-type overrides). Event-triggered invalidation. Field-level provenance for temporal attributes.

#### Revised Proposal

**Validity vs Confidence Decay — distinct fields:**

```
Validity fields (is the relation still factually true?):
  valid_from             TIMESTAMPTZ        — when the relation began (extracted or inferred)
  valid_to               TIMESTAMPTZ NULL   — when the relation ended (NULL = ongoing)
  valid_to_confidence    FLOAT NULL         — model confidence in the valid_to date [0,1]
  valid_to_source        VARCHAR(50)        — EXTRACTED | INFERRED | SYSTEM_ASSUMED | EVENT_TRIGGERED
  invalidated_by_event_id UUID NULL         — FK to events table
  relation_period_type   VARCHAR(30) DEFAULT 'ONGOING'
    -- ONGOING: relation is presumed active until invalidated
    -- BOUNDED: has known valid_from and valid_to
    -- POINT_IN_TIME: snapshot claim, not a durable relation
    -- HISTORICAL: known to have ended, valid_to recorded

Confidence decay fields (how much do we trust the evidence?):
  decay_class            VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'
  decay_alpha            FLOAT NOT NULL      — computed from decay_class; stored for fast batch queries
  confidence             FLOAT NOT NULL DEFAULT 0.0
  confidence_stale       BOOLEAN DEFAULT false
  confidence_last_computed_at TIMESTAMPTZ
```

**Revised decay classes with decay_alpha values:**

```sql
-- decay_alpha = ln(2) / half_life_days
-- PERMANENT: 0.0, DURABLE: 0.000380, SLOW: 0.001899,
-- MEDIUM: 0.007701, FAST: 0.049510, EPHEMERAL: 0.693147

CREATE TABLE decay_class_config (
    decay_class      VARCHAR(20) PRIMARY KEY,
    half_life_days   FLOAT,   -- NULL for PERMANENT
    decay_alpha      FLOAT NOT NULL,
    recompute_interval_minutes INT NOT NULL,
    description      TEXT
);

INSERT INTO decay_class_config VALUES
    ('PERMANENT',  NULL,    0.000000,  10080, 'No confidence decay; recomputed only on new evidence'),
    ('DURABLE',    1825.0,  0.000380,  10080, 'Regulatory/structural; 5-year half-life'),
    ('SLOW',       365.0,   0.001899,  1440,  'Annual cycle relations; 1-year half-life'),
    ('MEDIUM',     90.0,    0.007701,  360,   'Quarterly cycle; default class'),
    ('FAST',       14.0,    0.049510,  60,    'Analyst ratings, price targets'),
    ('EPHEMERAL',  1.0,     0.693147,  15,    'Intraday signals');
```

**valid_to reliability rules:**

The system must apply heuristic validation to all LLM-extracted `valid_to` values before persisting:

```python
def validate_valid_to(valid_to, evidence_date, claim_date) -> tuple[datetime | None, float, str]:
    if valid_to is None:
        return None, None, 'ONGOING'
    if valid_to <= evidence_date:
        # LLM extracted a past date — likely confused evidence date with expiry
        return None, 0.0, 'EXTRACTION_REJECTED'
    if valid_to > now() + timedelta(days=365 * 10):
        # Suspiciously far future — likely hallucinated
        return valid_to, 0.3, 'EXTRACTED_LOW_CONFIDENCE'
    # Plausible range
    confidence = 0.6  # Base; can be improved with calibration data
    return valid_to, confidence, 'EXTRACTED'
```

Store `valid_to_confidence` and `valid_to_source = 'EXTRACTED'` alongside the value.

**Event-triggered invalidation:**

```python
# In S7 event processing, after inserting a new event into events table:
INVALIDATION_RULES = {
    'ceo_departure':    [('employs', 'EXECUTIVE_ROLE')],
    'merger_completed': [('subsidiary_of', None), ('acquired_by', None)],
    'bankruptcy_filed': [('employs', None), ('supplier_of', None)],
    'delisted':         [('listed_on', None)],
}

def trigger_invalidation(event, subject_entity_id):
    for event_type_pattern, (relation_type, role_filter) in INVALIDATION_RULES.items():
        if event.event_type.matches(event_type_pattern):
            db.execute("""
                UPDATE relations SET
                    invalidated_by_event_id = :event_id,
                    valid_to = :event_date,
                    valid_to_source = 'EVENT_TRIGGERED',
                    relation_period_type = 'HISTORICAL',
                    confidence_stale = true
                WHERE subject_entity_id = :eid
                  AND canonical_type = :rel_type
                  AND (relation_period_type = 'ONGOING' OR valid_to IS NULL)
                  AND invalidated_by_event_id IS NULL
            """, event_id=event.event_id, event_date=event.occurred_at,
                 eid=subject_entity_id, rel_type=relation_type)
```

**How decay_class should be assigned:**

- System-assigned based on `canonical_type` (stored in relation type registry):
  ```sql
  ALTER TABLE relation_type_registry ADD COLUMN default_decay_class VARCHAR(20);
  ```
  Example: `supplier_of → MEDIUM`, `founded_in → PERMANENT`, `analyst_rating → FAST`.
- LLM extraction can propose a `decay_class` but it is overridden by the registry value unless `override_allowed = true` for that type.
- This prevents model-generated decay classes from creating inconsistent temporal behavior.

**Query-time temporal reasoning:**

At query time, relations should be filtered or scored by temporal state:

```sql
-- Active relations only
WHERE (relation_period_type = 'ONGOING' OR valid_to > now())
  AND invalidated_by_event_id IS NULL

-- Include recently invalidated for temporal range queries
WHERE (valid_from <= :query_date AND (valid_to >= :query_date OR valid_to IS NULL))
  AND (invalidated_by_event_id IS NULL OR invalidation_event.occurred_at > :query_date)
```

Confidence should be recomputed at query time for FAST and EPHEMERAL relations if `confidence_last_computed_at < now() - 30 minutes`, as their confidence changes significantly within the batch window.

#### Impact on Ingestion Pipeline

`valid_to` validation rejects or flags unreliable LLM extractions before persistence. Event-triggered invalidation runs synchronously in S7 after event insertion. Adds ~5ms per event with a fast indexed query.

#### Impact on Query Pipeline

Explicit `relation_period_type` allows temporal range queries ("what was the supplier relationship in Q3 2024?"). `invalidated_by_event_id` enables "why was this relation marked ended?" auditability. Query results can be filtered to `ONGOING` or scoped to a historical date range.

#### Remaining Open Questions

- Should `POINT_IN_TIME` relations have `confidence` decay at all? (A historical claim "as of Q3 2024, market share was 32%" is valid forever as a historical statement, but its relevance to today's decisions decays.) Suggest: separate `query_relevance_decay` from `evidence_confidence_decay`.
- How should the invalidation rules table be maintained? Suggest: version-controlled YAML in the intelligence-migrations repository, loaded into `invalidation_rules` table at migration time.

---

### B.11 — Relation Summaries and Relation Embeddings

#### Current Problem

Query-time retrieval of graph evidence requires reconstructing a narrative from potentially dozens of individual `relation_evidence` rows. Each row contains raw extraction output, not a coherent summary. Without a relation-level text summary, LLMs generating answers must process many individual evidence snippets instead of a pre-aggregated description. There is no embedding that represents the semantic content of an entire relation (what does it mean that TSMC supplies Nvidia?), making relation-level semantic search impossible.

#### Accepted Direction

Introduce `relation_summaries` table: one current text summary per aggregated relation, updated periodically. Add `relation_embedding` for relation-level semantic retrieval. Update on new evidence or on schedule.

#### Revised Proposal

**Schema:**

```sql
CREATE TABLE relation_summaries (
    summary_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_id             UUID NOT NULL REFERENCES relations(relation_id) ON DELETE CASCADE,
    summary_text            TEXT NOT NULL,
    evidence_count          INT NOT NULL,    -- evidence rows incorporated
    evidence_hash           VARCHAR(64) NOT NULL,  -- SHA-256 of sorted evidence_ids
    summary_embedding       VECTOR(1024),
    embedding_model         VARCHAR(200),
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_id                VARCHAR(200) NOT NULL,
    prompt_template_id      UUID NOT NULL REFERENCES prompt_templates(template_id),
    is_current              BOOLEAN NOT NULL DEFAULT true,
    -- Only one is_current=true per relation_id (enforced by partial unique index)
    generation_trigger      VARCHAR(50) NOT NULL  -- 'NEW_EVIDENCE' | 'SCHEDULED' | 'MANUAL'
);

CREATE UNIQUE INDEX uidx_relation_summaries_current
    ON relation_summaries (relation_id)
    WHERE is_current = true;

CREATE INDEX hnsw_relation_summary_embedding ON relation_summaries
    USING hnsw (summary_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE is_current = true;
```

**When to regenerate a summary:**

The system maintains a `summary_stale` flag on `relations`:

```sql
ALTER TABLE relations ADD COLUMN summary_stale BOOLEAN DEFAULT false;
```

Set `summary_stale = true` when:
1. `evidence_count` on the relation increases (new evidence incorporated by aggregation worker).
2. A contradiction is detected and affects this relation.
3. The relation is invalidated by an event (summary should reflect historical status).

Summary generation worker (runs in S7):
```
Cadence: every RELATION_SUMMARY_REFRESH_INTERVAL_SECONDS (default: 3600 = 1 hour)
Per cycle:
  SELECT relation_id FROM relations
  WHERE summary_stale = true
  ORDER BY confidence DESC, latest_evidence_at DESC
  LIMIT RELATION_SUMMARY_BATCH_SIZE
  FOR UPDATE SKIP LOCKED;

For each relation:
  1. Fetch top K evidence rows (K = min(10, evidence_count)), ordered by temporal_weight DESC.
  2. Compute evidence_hash = SHA-256(sorted evidence_ids).
  3. If evidence_hash matches current summary's evidence_hash → skip (no change).
  4. Generate summary via ExtractionClient with SUMMARIZATION prompt.
  5. INSERT new relation_summary with is_current = true.
  6. UPDATE previous summary: is_current = false.
  7. Generate embedding via EmbeddingClient.
  8. UPDATE relation: summary_stale = false.
```

**Summary prompt design:**

```
Given the following evidence records about the relationship [relation_type] between
[subject_entity_name] and [object_entity_name]:

Evidence (ordered by recency):
{evidence_1}: "{claim_text}" (source: {source_name}, date: {evidence_date}, confidence: {conf})
{evidence_2}: ...
...

Write a concise factual summary (2-4 sentences) of what is known about this relationship,
noting the strength of evidence, temporal range, and any contradictions.
Do not speculate beyond the evidence.
```

**Pair-level vs family-level summaries:**

- **Pair-level** (v1): one summary per (subject, relation_type, object) triple. Most useful for query.
- **Cluster-level** (v2+): one summary per entity for a given relation type, e.g., "All supplier_of relations for Nvidia." Generated weekly by aggregating pair-level summaries.
- **Family-level** (v2+): one summary per relation type across all pairs, e.g., "Current state of semiconductor supply relationships." Too coarse for most query types; defer.

**Update cadence by decay_class:**

| decay_class | Summary refresh interval |
|-------------|------------------------|
| PERMANENT | Only on new evidence |
| DURABLE | Weekly |
| SLOW | Daily |
| MEDIUM | Every 6 hours |
| FAST | Every 1 hour |
| EPHEMERAL | Every 15 minutes |

This aligns with confidence recomputation cadence (see B.2).

**Relation embedding quality:**

The summary embedding is computed from `summary_text`, which is a coherent narrative. This is a much higher-quality embedding than embedding raw extraction output. The HNSW index on relation summaries (`WHERE is_current = true`) enables:
- "Find relations semantically similar to this query text"
- "Find all relations about a topic (supply chain disruption) without entity specification"
- Cross-entity relation retrieval for thematic queries

#### Impact on Ingestion Pipeline

One additional LLM call per relation update, plus one embedding call. These run asynchronously in S7's summary worker, not on the hot path. Cost: ~$0.001 per summary at Qwen2.5-7B local; negligible for local deployment.

#### Impact on Query Pipeline

Relation summaries are a primary retrieval target for graph-grounded queries. The query pipeline reads:
1. `relation_summaries` (semantic search via HNSW) for thematic relation discovery.
2. `relation_evidence` for granular source attribution.
3. Summary text as context for answer generation.

Without relation summaries, query-time answer generation must reconstruct context from raw extraction output — slower, less coherent, harder to cite.

#### Remaining Open Questions

- Should old (is_current = false) summaries be retained for temporal queries ("what did we know about this relation in January 2025?")? Suggest: yes, retain with a `retained_for_audit = true` flag; delete after 90 days if not marked for retention.
- Should summary generation use the same ExtractionClient (Qwen2.5) as claim extraction, or a lighter model? Suggest: same client for v1 (simpler); consider lighter model for v2 if cost is material.
- How many evidence records should be incorporated into a summary? Suggest: top 10 by temporal weight. Including all evidence for a relation with 500 evidence rows would exceed context limits.

---

### B.12 — Query Pipeline Proposal

#### Current State

The query pipeline is entirely undefined in the current PRD. This is the most critical gap: all embedding index design, chunk size decisions, section granularity, and relation summary design ultimately exist to serve the query pipeline. Without defining what the query pipeline needs, it is impossible to validate that the ingestion pipeline is building the right structures.

#### Proposed Query Pipeline Architecture

**Query types the system must support (v1):**

1. **Entity-centric lookup**: "What is known about TSMC?" → entity profile + recent relations + recent events.
2. **Relation query**: "Who supplies Nvidia with advanced chips?" → graph traversal + relation retrieval.
3. **Signal query**: "What recent claims about Nvidia's AI revenue growth?" → claims retrieval + chunk retrieval.
4. **Contradiction query**: "Are there contradictions in Qualcomm's guidance?" → contradiction links + claims.
5. **Temporal query**: "How has Apple's relationship with TSMC evolved?" → time-filtered relation + evidence.
6. **Thematic query**: "What semiconductor supply chain disruptions are signaled this week?" → novelty-weighted chunk + event retrieval.

**Query pipeline stages:**

```
Stage 1: Query Understanding
  Input: raw query text
  Steps:
    a. Detect named entities in query using GLiNER (same adapter as ingestion)
    b. Resolve query entities to canonical entity_ids (same cascade as ingestion, Block 9)
    c. Classify query intent: ENTITY_LOOKUP | RELATION | SIGNAL | CONTRADICTION |
                              TEMPORAL | THEMATIC
    d. Extract temporal constraints from query ("this week", "in 2024", "last quarter")
    e. Extract relation type hints ("supplies", "employs", "acquired")

Stage 2: Multi-Source Retrieval (parallel)
  Given: resolved entity_ids, intent, temporal constraints, relation hints

  Retrieval A — Chunk embedding search (semantic):
    query_embedding = EmbeddingClient.embed(query_text, task='query')
    chunk_results = pgvector.query(
        hnsw_chunk_embeddings,
        query_embedding,
        k=50,
        filter="source_type != 'suppress' AND expires_at IS NULL OR expires_at > now()"
    )

  Retrieval B — Section embedding search (broader context):
    section_results = pgvector.query(
        hnsw_section_embeddings,
        query_embedding,
        k=20
    )

  Retrieval C — Relation summary search:
    relation_results = pgvector.query(
        hnsw_relation_summary_embedding,
        query_embedding,
        k=20,
        filter="is_current = true"
    )

  Retrieval D — Graph state retrieval (structured):
    If entity_ids resolved:
      relations = db.query("""
          SELECT r.*, rs.summary_text, rs.generated_at
          FROM relations r
          LEFT JOIN relation_summaries rs ON r.relation_id = rs.relation_id AND rs.is_current
          WHERE (r.subject_entity_id = ANY(:eids) OR r.object_entity_id = ANY(:eids))
            AND (r.relation_period_type = 'ONGOING' OR r.valid_to > :query_date)
            AND r.invalidated_by_event_id IS NULL
            AND r.confidence >= :min_confidence
          ORDER BY r.confidence DESC, r.latest_evidence_at DESC
          LIMIT 30
      """, eids=entity_ids, query_date=now(), min_confidence=0.3)

  Retrieval E — Claims retrieval:
    If intent in [SIGNAL, CONTRADICTION]:
      claims = db.query("""
          SELECT c.*, e.name as subject_name
          FROM claims c
          JOIN canonical_entities e ON c.subject_entity_id = e.entity_id
          WHERE c.subject_entity_id = ANY(:eids)
            AND c.created_at > now() - :recency_window
          ORDER BY c.extraction_confidence DESC, c.created_at DESC
          LIMIT 30
      """)

  Retrieval F — Contradiction retrieval:
    If intent = CONTRADICTION:
      contradict = db.query("""
          SELECT link.*, c1.claim_text, c2.claim_text
          FROM relation_contradiction_links link
          JOIN claims c1 ON link.claim_id = c1.claim_id
          JOIN relation_evidence re ON link.relation_evidence_id = re.evidence_id
          JOIN relations r ON re.relation_id = r.relation_id
          WHERE (r.subject_entity_id = ANY(:eids) OR r.object_entity_id = ANY(:eids))
            AND link.invalidated_at IS NULL
          ORDER BY link.detected_at DESC LIMIT 20
      """)

  Retrieval G — Delta merge (raw unprocessed):
    recent_raw = db.query("""
        SELECT * FROM relation_evidence_raw
        WHERE (subject_entity_id = ANY(:eids) OR object_entity_id = ANY(:eids))
          AND processed = false
          AND extracted_at > now() - interval '10 minutes'
    """)
    # Merge with relation results, mark as 'unconfirmed'

Stage 3: Ranking and Fusion
  Score each retrieved item:

  item_score(item) =
      alpha * semantic_relevance(item, query_embedding)
    + beta  * temporal_recency(item.created_at or evidence_date)
    + gamma * confidence_weight(item)
    + delta * source_reliability(item.source_type)
    - epsilon * contradiction_penalty(item.relation_id)

  Default weights: alpha=0.35, beta=0.20, gamma=0.25, delta=0.15, epsilon=0.05

  Special adjustments:
  - Items matching resolved entity_ids: +0.10 bonus
  - Items with summary_stale=true: -0.05 penalty (stale confidence)
  - Items from 'unconfirmed' delta merge: -0.10 penalty (not yet aggregated)
  - Items with event_novelty_score > 0.8: +0.10 bonus

  Deduplication:
  - Remove chunk results whose parent document is already represented by a section result
    covering the same text range, if section result scored higher.
  - Group corroborating documents: present as one result with source count metadata.

Stage 4: Context Window Assembly
  Select top K items (K = context_budget / avg_item_tokens; typically K=15-25)
  Order: contradictions first (if CONTRADICTION intent), then by item_score DESC
  Include metadata: source, date, confidence, freshness flag, decay_class

Stage 5: Answer Generation
  Pass assembled context to ExtractionClient with answer-generation prompt.
  Include temporal constraints in prompt: "Answer as of [query_date]."
  Include uncertainty instruction: "If evidence is stale or contradictory, say so."
  Return structured response with citations (chunk_id, relation_id, claim_id references).
```

**Reading from aggregate + delta at query time:**

For relations, the query always reads from `relations` (aggregate) and merges with `relation_evidence_raw WHERE processed = false AND extracted_at > now() - 10 minutes`. The delta items are labeled `confidence_source = 'RAW_UNCONFIRMED'` in the query response. This provides near-real-time freshness without waiting for the next aggregation flush.

**Staleness handling:**

- `confidence_stale = true` on a relation: compute approximate confidence synchronously using last 10 evidence rows (fast path, not full batch). Flag as `confidence_freshness = 'APPROXIMATE'`.
- `embedding_stale = true` on an entity profile: serve old embedding, flag as `embedding_freshness_stale = true` in response metadata.
- `summary_stale = true` on relation: serve old summary, flag as `summary_freshness_stale = true`.

**Indexes required by the query pipeline:**

| Index | Table | Purpose |
|-------|-------|---------|
| hnsw_chunk_embeddings | chunk_embeddings | Semantic chunk retrieval |
| hnsw_section_embeddings | section_embeddings | Semantic section retrieval |
| hnsw_relation_summary_embedding | relation_summaries | Relation semantic search |
| hnsw_entity_profile | entity_profile_embeddings | Entity profile retrieval |
| idx_relations_by_subject | relations | Entity-centric graph query |
| idx_relations_by_object | relations | Reverse graph traversal |
| idx_claims_by_subject | claims | Signal/contradiction query |
| idx_rcl_relation_evidence | relation_contradiction_links | Contradiction query |

#### Impact on Ingestion Pipeline

This query design confirms that the ingestion pipeline must produce, per document:
- Chunk embeddings (sentence-aware, separate index)
- Section embeddings (separate index)
- Resolved entity_ids on all evidence
- Claims with subject_entity_id (for Retrieval E, F)
- Relation summaries + embeddings (for Retrieval C)

Any ingestion block that fails to produce these outputs degrades a specific retrieval path.

#### Remaining Open Questions

- Should Stage 5 (answer generation) use streaming? Suggest: yes for user-facing queries; no for batch/analytical queries.
- What is `min_confidence` for Retrieval D? Suggest: 0.30 default, user-configurable per query.
- Should query pipeline cache results? Suggest: cache entity-centric lookups in Valkey with TTL = `decay_class` refresh interval of the slowest active relation for that entity.
- How does the query pipeline handle queries with no resolved entities? Fall through to purely semantic retrieval (Retrievals A + B only).

---

### B.13 — Testing / Evaluation Framework (Requirements)

Full standalone PRD is in Section D. Summary of requirements here:

- Datasets: curated golden sets per document type (news, filing, transcript), with expected NER output, expected dedup decisions, expected routing tier, expected extraction schema.
- Per-block metrics: dedup recall/precision, routing accuracy (F1 by tier), NER F1 by entity class, entity resolution accuracy, relation extraction precision/recall, contradiction detection precision/recall.
- Retrieval metrics: NDCG@10, MRR, recall@K for each retrieval path (chunk, section, relation summary, entity profile).
- Temporal reasoning metrics: temporal class assignment accuracy, valid_to extraction precision, invalidation trigger correctness.
- Provider parity tests: same golden inputs through multiple provider adapters, compare output shape conformance and quality score distributions.
- Regression tests: any PRD change that touches schema or algorithm must be accompanied by a passing regression test on the golden set.
- No backfill required. Local rebuild from scratch is acceptable. Tests run against local stack.

---

## C. Dedicated Investigation Sections

---

### C.1 — PostgreSQL Write-Scaling Strategy for Horizontal Microservice Scaling

#### Problem Statement

The current design assumes a single S7 process performs all relation aggregation writes. As document throughput increases, a single aggregation worker becomes a bottleneck. Naively running multiple S7 replicas creates write-key contention: two workers can race to upsert the same (subject_entity_id, canonical_type, object_entity_id) triple, causing lock waits, deadlocks, or duplicate increments.

Managed Postgres read replicas (e.g., AWS RDS Multi-AZ, Aurora read replicas) do not help here. Read replicas handle read fan-out, not write contention. All writes must go to the primary.

#### Design Options

**Option A: Advisory Locks (per-triple hash locking)**

Each aggregation worker acquires `pg_try_advisory_xact_lock(hash(triple))` before upserting. If the lock is not acquired, the worker skips that triple in this batch and retries next cycle.

```sql
SELECT pg_try_advisory_xact_lock(
    hashtext(subject_entity_id::text || canonical_type || object_entity_id::text)
);
```

Pros:
- Simple to implement.
- No coordination layer needed.
- Safe for 2–4 workers.

Cons:
- Lock namespace is 2^63 — hash collisions possible (two different triples get same lock).
- High-cardinality graphs (millions of triples) with many workers cause lock exhaustion.
- Does not partition the write space — any worker can contend with any other.

Verdict: **Sufficient for v1 with a single worker.** Not suitable beyond 3–4 workers.

**Option B: Queue-Based Partition Ownership (Kafka Partition Key)**

Assign `partition_key = hash(subject_entity_id) % N_PARTITIONS` to each `relation_evidence_raw` row (set at insert time by S6). Each aggregation worker owns a set of Kafka partitions, and processes only the rows corresponding to its partition ownership.

```sql
ALTER TABLE relation_evidence_raw ADD COLUMN partition_key SMALLINT NOT NULL
    GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 16) STORED;

CREATE INDEX idx_rer_partition ON relation_evidence_raw (partition_key, processed, extracted_at);
```

Worker claiming:
```sql
SELECT * FROM relation_evidence_raw
WHERE partition_key = ANY(:my_partitions)
  AND processed = false
ORDER BY extracted_at
LIMIT :batch_size
FOR UPDATE SKIP LOCKED;
```

Since worker i always owns partition_key values {i*k, ..., (i+1)*k-1}, no two workers ever contend on the same triple. No advisory locks needed.

Pros:
- Horizontally scalable without lock contention.
- Each worker's write pattern is predictable (only its partition's triples).
- Partition assignments can be redistributed dynamically (like Kafka consumer group rebalance).

Cons:
- Requires partition-aware worker assignment (similar to Kafka consumer group protocol).
- Hot partitions possible if a small number of entities generate disproportionate evidence volume.
- Rebalancing partitions across workers requires careful handoff.

Verdict: **Best option for v2+ horizontal scaling.** Implement v1 with single worker (no partitioning needed), design `partition_key` column from day one to avoid a migration later.

**Option C: Hash-Partitioned `relations` Table**

Partition the `relations` table itself by `subject_entity_id` using PostgreSQL declarative partitioning:

```sql
CREATE TABLE relations (
    relation_id        UUID NOT NULL,
    subject_entity_id  UUID NOT NULL,
    ...
) PARTITION BY HASH (subject_entity_id);

CREATE TABLE relations_p0 PARTITION OF relations FOR VALUES WITH (modulus 8, remainder 0);
CREATE TABLE relations_p1 PARTITION OF relations FOR VALUES WITH (modulus 8, remainder 1);
-- ... up to relations_p7
```

Each partition has its own index. Workers that own partition i write only to `relations_pi`. PostgreSQL partition pruning ensures queries targeting a specific `subject_entity_id` hit only one partition.

Pros:
- Reduces lock contention by 1/N (N = number of partitions).
- Partition pruning speeds up relation queries.
- Compatible with `FOR UPDATE SKIP LOCKED` within a partition.

Cons:
- Cross-partition queries (e.g., "find all relations where object_entity_id = X") require scanning all partitions.
- Partition count is fixed at creation time (changing requires rebuild).
- Does not eliminate contention within a partition if multiple workers write to the same partition.

Verdict: **Implement as a complementary optimization to Option B.** Hash-partition the `relations` table by `subject_entity_id` into 8 partitions from day one. This reduces contention and improves query locality even with a single worker.

**Option D: Optimistic Locking with Retry**

Workers attempt the upsert without locks. On conflict (deadlock or unique violation), retry with exponential backoff.

Pros: No coordination layer, simple code.
Cons: Under high contention, retry storms amplify load. Deadlock rate grows super-linearly with worker count. Not suitable beyond 2 workers.

Verdict: **Do not use.** Advisory locks are strictly better.

#### Recommended Architecture (v1 → v2 path)

**v1 (current scope):**
- Single aggregation worker process.
- `partition_key` column on `relation_evidence_raw` (computed, STORED) — schema is ready for v2.
- Hash-partitioned `relations` table (8 partitions) — established from day one.
- Advisory lock per triple hash as a safety net during development.

**v2 (future horizontal scaling):**
- Multiple workers, each owning a set of `partition_key` values.
- Worker assignment via a simple distributed lease (Valkey key per partition, with TTL = 2× batch interval).
- No cross-partition writes.
- Monitor for partition hot spots; rebalance by splitting hot partitions.

#### Interaction with Query-Time Reads

Hash partitioning of `relations` does NOT degrade query performance for entity-centric lookups (WHERE subject_entity_id = X) — the query hits exactly one partition. For object-centric lookups (WHERE object_entity_id = X), all partitions are scanned, which requires a parallel index scan across 8 partitions (PostgreSQL handles this automatically via partition pruning + parallel query).

For the delta merge at query time (`relation_evidence_raw WHERE processed = false`), the `partition_key` index allows each worker to quickly identify which rows it owns vs which are owned by other workers, avoiding cross-worker reads.

---

### C.2 — Query Pipeline Design (Full Investigation)

Already covered in B.12 above with concrete stage design. This section adds the unresolved design choices not yet addressed.

#### Unresolved: Retrieval Fusion Strategy

The scoring formula in B.12 Stage 3 combines semantic relevance, recency, confidence, source reliability, and contradiction penalty. The key unresolved question is: **should these weights be fixed or learned?**

**Option A: Fixed weights (v1)**

Fixed weights (alpha=0.35, beta=0.20, gamma=0.25, delta=0.15, epsilon=0.05) are interpretable and tunable. Engineers can reason about why a result was ranked highly.

Cons: Weights may be suboptimal for different query types. A temporal query should weight `beta` (recency) more heavily than a structural query.

Mitigation: weight profiles per intent:
```python
SCORING_WEIGHTS = {
    'ENTITY_LOOKUP':  (0.30, 0.15, 0.30, 0.20, 0.05),
    'SIGNAL':         (0.35, 0.30, 0.20, 0.10, 0.05),
    'TEMPORAL':       (0.20, 0.40, 0.25, 0.10, 0.05),
    'CONTRADICTION':  (0.25, 0.20, 0.15, 0.10, 0.30),
    'THEMATIC':       (0.45, 0.20, 0.20, 0.10, 0.05),
}
```

Verdict: **Use intent-specific fixed weight profiles for v1.** This is simple, interpretable, and sufficient.

**Option B: Learned re-ranker (v2+)**

Train a cross-encoder or LightGBM ranker on (query, candidate item, user click/relevance label). Requires relevance feedback data not yet available.

Verdict: Defer to v2. Log all retrieval results + query features as training data from day one.

#### Unresolved: How to Handle the Aggregate + Delta Merge Correctly

At query time, reading `relations` (aggregate) + `relation_evidence_raw WHERE processed = false` may return:
1. A relation in `relations` with confidence 0.72, plus 3 unprocessed raw rows that would push confidence higher if aggregated.
2. A brand new triple that exists only in `relation_evidence_raw` (no aggregate row yet).

Case 1: Return the aggregated confidence + flag "3 pending evidence records." Do not recompute inline (expensive).
Case 2: Construct an ephemeral relation from the raw rows with `confidence_source = 'RAW_UNCONFIRMED'` and `confidence = mean(extraction_confidence)` of the raw rows.

This requires the query layer to implement a merge step, not just a JOIN. The merge logic should be a library shared between S7 (aggregation worker) and the query service to avoid drift.

#### Unresolved: Query Caching

For entity-centric queries, results change only when:
- New evidence is aggregated (every RELATION_AGGREGATION_INTERVAL_SECONDS)
- A contradiction is detected
- An event invalidates a relation

Cache strategy: Valkey cache key = `query:entity:{entity_id}:{intent}:{temporal_hash}`, TTL = `min(decay_class.recompute_interval)` of all active relations for that entity.

Cache invalidation: on `entity.dirtied.v1`, delete all cache keys for that entity_id.

This provides significant latency reduction for repeated entity lookups without serving stale results for longer than one recomputation cycle.

---

### C.3 — Embedding Maintenance, Pruning, and Refresh Strategy

#### The Core Problem

Vector indexes are write-once-read-many structures. HNSW does not support online deletion — deleted rows remain in the graph structure until a full REINDEX. As chunk embeddings accumulate over months, two problems emerge:
1. **Index bloat**: deleted/expired rows remain in the HNSW graph, consuming memory and degrading search quality (results include deleted items that then fail the `WHERE expires_at IS NULL` filter).
2. **Semantic drift**: embedding models may change or be fine-tuned. Old vectors become inconsistent with new vectors from a different model version.

#### Strategy by Embedding Type

**Chunk embeddings (highest churn):**
- Set `expires_at` at write time by source_type (see B.8 table).
- Soft-expire: `UPDATE chunk_embeddings SET expires_at = now() WHERE expires_at < now()`.
- Hard-delete: monthly batch job deletes rows where `expires_at < now() - 7 days`.
- HNSW reindex: monthly `REINDEX INDEX CONCURRENTLY hnsw_chunk_embeddings` after deletions.
- FILINGS chunks: never expire. Accept permanent index growth for filings; offset by separate partition.

**Section embeddings:**
- Same TTL policy as parent chunks.
- Separate HNSW index — reindex on same monthly schedule.

**Entity profile embeddings:**
- Refresh-driven (not TTL-driven). Stale but retained until refreshed.
- Refresh trigger: `entity.dirtied.v1` event.
- Coalescing: if an entity receives 10 `dirtied` events in 1 hour, refresh once (deduplicate by entity_id with a 30-minute coalesce window in Valkey).
- No deletion — one embedding per entity, always retained, refreshed in place.

**Relation summary embeddings:**
- Refreshed when summary is regenerated (see B.11).
- Old summary rows (is_current = false) retain their embeddings for audit.
- Hard-delete old summaries after 90 days (also removes their embeddings).

#### Model Version Drift

If the embedding model changes (e.g., upgrade from bge-large-en-v1.5 to a newer model):
1. Register new model in `model_registry` with new `dimension` (if different).
2. If dimension is the same: dual-write period where both old and new models generate embeddings. New queries use new model. Old indexes still serve until backfill completes.
3. If dimension changes: shadow migration protocol (shadow_column → dual_write → backfill → cutover → cleanup).
4. Mark old model as `is_active = false` in registry.
5. Delete old embeddings after cutover.

Since this is a local rebuild-from-scratch project, a dimension change simply requires a full re-ingestion. Design the shadow migration protocol as documentation for future production use.

#### HNSW Tuning Over Time

As corpus size grows, `ef_construction` and `m` parameters may need tuning:
- `m = 16`: appropriate for < 10M vectors.
- `m = 32`: for 10M–100M vectors (better recall at cost of memory).
- `ef_construction = 128`: standard for high recall.

For the thesis project (< 1M vectors), `m = 16, ef_construction = 128` is sufficient. Log index size monthly.

---

### C.4 — Relation Summaries and Relation Embeddings (Full Investigation)

Already covered in B.11. Additional investigation: **should there be both evidence-level summaries and pair-level summaries?**

**Evidence-level summaries (not recommended for v1):**

Generating a summary per `relation_evidence` row (one per article) duplicates what is already in the `chunk_embeddings` for the source chunk. The chunk embedding IS the evidence-level semantic representation. A redundant summary adds LLM cost without retrieval benefit.

**Pair-level summaries (RECOMMENDED — B.11 design):**

One summary per (subject, relation_type, object) triple, refreshed as evidence accumulates. This is the right level of aggregation — coherent enough for answer generation, specific enough for precise retrieval.

**Cross-entity relation family summaries (v2+):**

Example: "All relations of type `supplier_of` where object = Nvidia." Useful for company-profile queries. Generated weekly by an LLM that summarizes all pair-level summaries for that entity-relation family. This is strictly additive — it does not replace pair-level summaries.

**Why relation embeddings are distinct from entity profile embeddings:**

An entity profile embedding captures "what is TSMC" — its sector, size, history, current events. A relation embedding captures "what is the TSMC-Nvidia supply relationship" — its nature, evidence base, temporal extent, confidence. These are orthogonal and both useful at query time. The entity profile embedding answers entity-centric queries; the relation embedding answers relationship-centric queries.

---

### C.5 — Provider Abstraction and Canonical I/O Contracts

Already covered in B.9. Additional investigation: **how should tokenization be handled cross-provider?**

#### Tokenization Problem

Different models use different tokenizers. The same text "Q3 2024 semiconductor revenue" produces:
- cl100k_base (OpenAI/Ollama): ~7 tokens
- SentencePiece (some open models): ~9 tokens

For chunking (target 300 tokens), using the wrong tokenizer produces chunks that are too large or too small for the actual model. For cost estimation (billed by tokens), wrong tokenizer produces incorrect estimates.

#### Recommended Approach

1. **Canonical token estimate**: use tiktoken cl100k_base as the platform-wide estimate. Accurate for OpenAI models; within 15% for most other models.
2. **Adapter override**: each adapter exposes `estimate_tokens(text) -> int`. Adapters that know their model's tokenizer return the precise count. Others fall back to the platform estimate.
3. **Provider-reported count**: `EmbeddingOutput.token_count` captures the provider's actual reported count post-inference. This is used for cost tracking, not for chunking decisions.
4. **Chunking uses platform estimate**: all chunking decisions use `estimate_tokens()` from the adapter that will process the chunk. This ensures the chunk size is calibrated to the actual model.

#### Cross-Provider Output Normalization

The most important normalization is for extraction outputs. Qwen2.5, Claude, and GPT-4o all produce JSON but with different structural habits:

- Qwen2.5: may wrap output in markdown code blocks (```json ... ```)
- Claude: may add explanatory text before/after the JSON
- GPT-4o: generally returns clean JSON when instructed

Each adapter must strip wrapper text and parse to a Python dict before returning `ExtractionOutput.raw_json`. The JSON Schema in `prompt_templates.output_schema` is validated after parsing, not before.

#### Capability Registry Pattern

The `model_registry` enables the pipeline to query "which model is currently active for EMBEDDING?":

```python
def get_active_client(capability: str) -> EmbeddingClient | ExtractionClient | NERClient:
    row = db.query(
        "SELECT model_id, provider, config FROM model_registry "
        "WHERE capability = :cap AND is_active = true AND performance_tier = 'PRIMARY' "
        "ORDER BY registered_at DESC LIMIT 1",
        cap=capability
    )
    return build_adapter(row.provider, row.model_id, row.config)
```

This function is called at service startup (not per-request). The active client is cached in memory. A config change (update `is_active` in model_registry) requires a service restart or a hot-reload signal.

---

### C.6 — GLiNER Ontology and Calibration (Full Investigation)

Already covered in B.6. Additional investigation: **what is the right level of ontology strictness for v1?**

#### The Strictness Trade-off

A strict ontology (few, precisely defined classes) produces:
- Higher per-class precision (model is not confused by overlapping classes)
- Lower recall (subtle entity types missed)
- Simpler downstream routing signal

A permissive ontology (many fine-grained classes) produces:
- Higher recall
- Lower per-class precision
- More complex routing signal
- More entity resolution candidates to handle

#### Recommendation for v1

Start with 12 classes (see B.6 table): 4 splits of `institution`, 5 retained classes, 3 new financial classes. Remove `event_type` unconditionally.

Do NOT add `sector` or `technology_platform` in v1 — these are implied categories, not named entities that appear literally in text with consistent surface forms. GLiNER struggles with implied categories.

#### Mismatch Between NER Ontology and Graph Ontology

A critical architectural clarification: **the NER ontology and the graph entity ontology are not the same.**

- **NER ontology**: what GLiNER detects from text. Coarse, surface-form-based. `organization`, `person`, `financial_instrument`.
- **Graph entity ontology**: the canonical types in `canonical_entities.entity_type`. Fine-grained, derived from resolution. `PUBLIC_COMPANY`, `PRIVATE_COMPANY`, `GOVERNMENT_AGENCY`, `EXECUTIVE`, `ANALYST`, `ETF`.
- **Extraction ontology**: what the LLM extracts from text. Events (`earnings_release`, `merger_announcement`), claims (`market_share_claim`, `guidance_claim`), relations (`supplier_of`, `employs`).

The mapping: GLiNER `organization` → resolution cascade → `canonical_entities.entity_type` = `PUBLIC_COMPANY` or `PRIVATE_COMPANY` etc. The NER class is a coarse pre-resolution hint. The graph type is the post-resolution ground truth.

This means: do not design GLiNER classes to match graph entity types. Design them to be easy to detect from surface text with high precision, then let the resolution cascade determine the graph type.

#### GLiNER as a Gating Model

The current PRD implicitly treats GLiNER output as a necessary precondition for routing. This is the right design: a document with zero GLiNER mentions above threshold should score very low on `entity_density_signal` and likely be routed as `light` or `suppress`.

However, GLiNER should NOT be a hard gate (zero mentions = never processed). Some documents contain implicit entity references ("the chipmaker" referring to TSMC) that GLiNER misses but the LLM extraction can resolve. A hard gate would discard these.

Soft gate: GLiNER feeds entity_density_signal (weight 0.30), which is one of seven routing signals. A document with zero GLiNER mentions can still score 0.35–0.40 on other signals and be routed as `light`, which triggers light extraction. Light extraction can surface entity mentions that GLiNER missed.

---

### C.7 — Testing/Evaluation Framework (Summary)

Full standalone PRD in Section D below. Key design principles:

1. **No backfill**: tests run on freshly ingested documents, not historical archives.
2. **Local rebuild**: the full stack is rebuilt from scratch for each test run if needed.
3. **Golden sets**: curated per document type, with expected outputs at each pipeline stage.
4. **Block-level isolation**: each block (dedup, routing, NER, resolution, extraction, graph, alert) can be tested independently using fixtures.
5. **End-to-end tests**: a subset of golden documents flows through the full pipeline, and final graph state is asserted against expected graph state.
6. **Provider parity**: the same golden inputs are run through all registered provider adapters; schema conformance must pass for all.
7. **Metrics dashboards**: per-block quality metrics are tracked over time, enabling regression detection across PRD versions.

---

## D. Testing and Evaluation Framework — Standalone PRD

Version: 1.0
Date: 2026-03-21
Status: Draft
Scope: Worldview Intelligence Pipeline (S4–S10)
Owner: Arnau Rodon

### D.1 Purpose and Scope

This PRD defines the testing and evaluation framework for the Worldview unstructured data ingestion and intelligence pipeline. It covers quality assurance, regression testing, performance testing, and evaluation methodology for all pipeline blocks.

**Critical constraints:**
- No backfill is required. The pipeline can be rebuilt from scratch.
- Local rebuild is acceptable as the baseline test strategy.
- All tests run against the local development stack.
- Production data is NOT required; synthetic and curated datasets are sufficient.

**In scope:**
- All pipeline blocks: S4 ingestion, S5 dedup/store, S6 NLP, S7 graph, S10 alerts.
- ML components: GLiNER, bge-large embedding, Qwen2.5 extraction.
- Query pipeline (once defined).
- Provider adapters.

**Out of scope:**
- Load testing at production scale.
- A/B testing with live users.
- Frontend/UI testing.

### D.2 Goals

1. Validate that each pipeline block produces correct outputs for known inputs.
2. Detect regressions when the pipeline code, schemas, or ML models change.
3. Measure quality improvements over time as the PRD evolves.
4. Validate provider adapter conformance (all providers produce valid output shapes).
5. Establish acceptance thresholds that block merges when quality degrades.
6. Provide a framework for evaluating query-time retrieval quality.

### D.3 Dataset Strategy

#### D.3.1 Golden Set Composition

The golden set is a curated collection of documents with fully annotated expected outputs at each pipeline stage. Each document in the golden set has:

- **Metadata**: doc_id, source_type, document_type, published_date, source_name.
- **Raw text**: the input text as the ingestion adapter would receive it.
- **Expected dedup decision**: UNIQUE | DUPLICATE | CORROBORATING, with reference doc_id if not UNIQUE.
- **Expected routing tier**: suppress | light | medium | deep.
- **Expected NER output**: list of (text, start_char, end_char, entity_class, min_confidence) spans.
- **Expected entity resolutions**: list of (mention_text, expected_entity_id or expected_entity_name).
- **Expected extractions**: list of (claim_type, subject_entity_name, object_entity_name, polarity, expected_relation_type).
- **Expected graph state delta**: list of (subject_entity_id, relation_type, object_entity_id) relations that should exist after processing.
- **Expected alert triggers**: which watchlist entity_ids should generate alerts (if any).

#### D.3.2 Document Type Coverage

| Document type | Target count | Why |
|--------------|-------------|-----|
| SEC 8-K (material events) | 20 | High extraction value; covers mergers, departures, guidance |
| SEC 10-K / 10-Q excerpts | 10 | Long-form; tests section-aware chunking |
| Earnings call transcripts | 15 | Speaker-turn chunking; dense entity mentions |
| Financial news articles | 30 | High volume; tests dedup and novelty gate |
| Press releases | 10 | Low content; tests suppress routing |
| Analyst reports (excerpts) | 10 | Tests corroborating evidence preservation |
| **Total** | **95** | |

#### D.3.3 Synthetic Test Cases

Beyond golden documents, synthetic cases cover edge conditions:

- **Near-duplicate pair**: two news articles covering the same event from different sources (test: CORROBORATING, not DUPLICATE).
- **Same-source near-duplicate**: same outlet re-publishes updated article (test: DUPLICATE).
- **Zero-entity document**: boilerplate legal text with no entities (test: suppress routing).
- **Contradiction pair**: two claims with opposite polarity for the same (subject, claim_type) (test: contradiction detection).
- **Temporal invalidation**: an executive departure event following an employment relation (test: relation invalidated).
- **Provider format variation**: extraction output with markdown wrapper (test: adapter strips wrapper correctly).

### D.4 Per-Block Quality Metrics

#### D.4.1 Block 2 — Deduplication Metrics

| Metric | Formula | Acceptance threshold |
|--------|---------|---------------------|
| Duplicate precision | TP_dup / (TP_dup + FP_dup) | ≥ 0.95 |
| Duplicate recall | TP_dup / (TP_dup + FN_dup) | ≥ 0.90 |
| Corroborating preservation rate | Correctly_kept / Total_corroborating | ≥ 0.95 |
| LSH false-negative rate | FN_dup / Total_true_duplicates | ≤ 0.10 |
| Dedup latency p95 | — | ≤ 30ms |

**Evaluation method**: feed near-duplicate pairs through S5, assert decision type matches golden annotation.

#### D.4.2 Block 5 — Routing Metrics

| Metric | Formula | Acceptance threshold |
|--------|---------|---------------------|
| Routing accuracy | Correct_tier / Total_docs | ≥ 0.85 |
| Deep tier precision | TP_deep / (TP_deep + FP_deep) | ≥ 0.80 |
| Deep tier recall | TP_deep / (TP_deep + FN_deep) | ≥ 0.85 |
| Suppress false positive rate | FP_suppress / Total_suppress | ≤ 0.05 |
| Routing latency p95 | — | ≤ 50ms |

**Note**: routing is inherently subjective for borderline documents. Allow ±1 tier error (medium predicted as deep) without counting as a full miss — use an "adjacent tier" metric.

#### D.4.3 Block 4 — GLiNER NER Metrics

Report per entity class:

| Metric | Formula | Global threshold |
|--------|---------|-----------------|
| Precision per class | TP / (TP + FP) | ≥ 0.75 each class |
| Recall per class | TP / (TP + FN) | ≥ 0.70 each class |
| F1 per class | 2 * P * R / (P + R) | ≥ 0.72 each class |
| Span boundary accuracy | Exact span match / Total_matches | ≥ 0.80 |
| NMS effectiveness | Spans after NMS / Spans before NMS | ≤ 0.80 (NMS removes ≥ 20% overlaps) |

**Golden annotation**: manually annotate NER spans on 30 news + 20 filing golden documents. Annotation disagreements resolved by majority vote (2 of 3 annotators).

#### D.4.4 Block 9 — Entity Resolution Metrics

| Metric | Formula | Acceptance threshold |
|--------|---------|---------------------|
| Resolution accuracy (exact match) | Correctly_resolved / Total_mentions | ≥ 0.85 |
| Precision (resolved mentions) | True_resolutions / All_resolved | ≥ 0.90 |
| Provisional queue rate | Provisional / Total_mentions | ≤ 0.15 |
| Auto-resolve precision | Correct_auto_resolve / Total_auto_resolve | ≥ 0.92 |
| Resolution latency p95 | — | ≤ 100ms per document |

**Note**: measure separately by resolution path (exact alias, ticker/ISIN, fuzzy, ANN).

#### D.4.5 Block 10 — Deep Extraction Metrics

| Metric | Formula | Acceptance threshold |
|--------|---------|---------------------|
| Relation extraction precision | True_relations / Extracted_relations | ≥ 0.75 |
| Relation extraction recall | True_relations / Expected_relations | ≥ 0.65 |
| Claim extraction precision | True_claims / Extracted_claims | ≥ 0.80 |
| Schema conformance rate | Valid_JSON / Total_extractions | ≥ 0.99 |
| Subject entity_id population rate | Claims_with_subject_id / Total_claims | ≥ 0.90 |
| Extraction latency p95 per document | — | ≤ 5s (local Ollama) |

**Evaluation method**: compare extracted (subject, relation_type, object) triples against golden annotations. Use exact triple match for precision; use liberal match (same entity pair, any relation type in the same family) for recall.

#### D.4.6 Block 12/13 — Graph Metrics

| Metric | Formula | Acceptance threshold |
|--------|---------|---------------------|
| Graph state correctness | Relations_matching_golden / Expected_relations | ≥ 0.80 |
| Confidence calibration (ECE) | Expected calibration error | ≤ 0.10 |
| Contradiction detection precision | TP_contra / (TP + FP) | ≥ 0.85 |
| Contradiction detection recall | TP_contra / (TP + FN) | ≥ 0.75 |
| Aggregation latency (raw → aggregate) | max(processed_at - extracted_at) | ≤ AGGREGATION_INTERVAL × 2 |

#### D.4.7 Alert Service Metrics

| Metric | Formula | Acceptance threshold |
|--------|---------|---------------------|
| Alert delivery recall | Alerts_delivered / Expected_alerts | ≥ 0.95 |
| Alert dedup precision | Unique_alerts / Total_alerts | ≥ 0.99 |
| Alert latency p95 | — | ≤ 500ms from event to WebSocket push |

### D.5 End-to-End Tests

#### D.5.1 Full Pipeline E2E

For a subset of 20 golden documents (mixed types):

1. Inject raw documents into S4 mock (or directly into content.article.raw.v1 topic).
2. Wait for propagation through S5 → S6 → S7 → S10 (use health probe + polling on Kafka consumer lag).
3. Assert final graph state: expected relations exist with confidence > 0.3, decay_class matches expected, valid_to validation matches.
4. Assert no unexpected alerts were generated.
5. Assert no documents were routed to wrong tier.

**Timeout**: 5 minutes for full E2E propagation on local stack.

#### D.5.2 Contradiction E2E

1. Inject Document A: "Company X's market share is 35%." (positive polarity)
2. Wait for full processing and relation creation.
3. Inject Document B: "Company X's market share is 12%." (contradictory claim, 3 days later)
4. Assert: contradiction link created between claim from A and claim from B.
5. Assert: relation confidence for `market_share_claim(X)` is reduced.
6. Assert: `intelligence.contradiction.v1` event published to Kafka.

#### D.5.3 Temporal Invalidation E2E

1. Inject transcript mentioning "John Smith is CEO of Company Y." → relation `employs(Y, John_Smith, EXECUTIVE_ROLE)` created.
2. Inject news article "John Smith steps down as CEO of Company Y." → event `ceo_departure` detected.
3. Assert: relation `employs(Y, John_Smith)` has `invalidated_by_event_id` set, `relation_period_type = 'HISTORICAL'`.

### D.6 Retrieval Quality Metrics

To be finalized once query pipeline is implemented. Proposed metrics:

| Metric | Description | Target |
|--------|-------------|--------|
| NDCG@10 | Normalized discounted cumulative gain at rank 10 | ≥ 0.70 |
| Recall@20 | Fraction of relevant items in top 20 | ≥ 0.80 |
| MRR | Mean reciprocal rank of first relevant result | ≥ 0.65 |
| Freshness coverage | Fraction of query results from docs < 7 days | Context-dependent |
| Stale result rate | Fraction of results with confidence_stale = true | ≤ 0.10 |
| Contradiction surfacing rate | When contradiction exists, it appears in top 5 | ≥ 0.90 |

**Evaluation method**: construct 50 query-answer pairs from the golden document set. For each query, run the retrieval pipeline and evaluate against golden relevant document list using NDCG/MRR.

### D.7 Temporal Reasoning Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| Decay class assignment accuracy | Correct_class / Total_relations | ≥ 0.90 |
| valid_to precision (when extracted) | Plausible_valid_to / Total_extracted_valid_to | ≥ 0.70 |
| valid_to rejection rate | Rejected_valid_to / Total_extracted_valid_to | Track (expected: 20–40%) |
| Invalidation trigger accuracy | Correct_invalidations / Expected_invalidations | ≥ 0.85 |
| Confidence decay curve calibration | Plot confidence vs age for MEDIUM class | Inspect for monotonic decay |

### D.8 Provider Parity Tests

For each registered provider adapter (capability × provider pair):

| Test | Expected behavior |
|------|------------------|
| Schema conformance | ExtractionOutput.raw_json passes output_schema validation |
| Dimension match | len(EmbeddingOutput.vector) == model_registry.dimension |
| Latency threshold | p95 latency ≤ provider target (local: 5s, API: 2s) |
| NER class coverage | All supported_classes() are in the canonical ontology |
| JSON wrapper stripping | Markdown-wrapped JSON is parsed correctly |
| Token count plausibility | Reported token count within 20% of platform estimate |

**Run**: on every adapter code change, at CI, and when a new model is registered.

### D.9 Performance and Load Tests

**Goal**: establish baseline latency and throughput for local single-node stack.

| Test | Target |
|------|--------|
| S5 dedup throughput | ≥ 50 documents/minute |
| S6 routing (no LLM) | ≥ 200 documents/minute |
| S6 GLiNER NER | ≥ 30 documents/minute (batch 32) |
| S6 embedding generation | ≥ 20 documents/minute (batch 16) |
| S6 deep extraction (Qwen2.5) | ≥ 5 documents/minute |
| S7 relation aggregation | ≥ 500 raw rows/minute |
| S7 confidence recompute (MEDIUM) | ≥ 1000 relations/minute |
| End-to-end latency (suppress tier) | ≤ 2s from raw event to stored |
| End-to-end latency (deep tier) | ≤ 30s from raw event to graph updated |

### D.10 Failure Injection Tests

| Scenario | Expected behavior |
|----------|-----------------|
| Kafka unavailable during S4 outbox publish | Rows remain in outbox_events; dispatcher retries with backoff |
| S5 crashes mid-dedup | Document re-processed on restart; idempotent dedup |
| Ollama unreachable during embedding | Chunk added to pending_embeddings queue; circuit breaker opens |
| intelligence-migrations fails | S6/S7 fail readiness check; do not start |
| Valkey unavailable during LSH | S5 falls back to PostgreSQL-only dedup; log metric |
| Contradiction worker crashes | Contradiction links may be missed; replay from Kafka offset |
| Aggregation worker crashes mid-batch | Raw rows remain with processed = false; next restart re-processes |

### D.11 Observability Requirements for Testing

All pipeline services must emit the following metrics (Prometheus) to support test evaluation:

- `documents_processed_total{service, source_type, routing_tier}` — counter
- `dedup_decision_total{decision_type}` — counter
- `entity_mentions_detected_total{entity_class}` — counter
- `entity_resolutions_total{resolution_path, outcome}` — counter
- `extractions_total{extraction_type, outcome}` — counter
- `relation_aggregations_total{outcome}` — counter
- `confidence_recomputed_total{decay_class}` — counter
- `contradiction_links_created_total` — counter
- `alerts_delivered_total{channel}` — counter
- `pipeline_stage_latency_seconds{stage}` — histogram (p50, p95, p99)
- `kafka_consumer_lag{topic, consumer_group}` — gauge

**Test dashboards**: a local Grafana dashboard should display all per-block metrics during E2E test runs to enable visual inspection of pipeline health.

### D.12 Acceptance Thresholds and CI Gates

A CI run FAILS if ANY of the following:

- Relation extraction precision < 0.70
- Duplicate precision < 0.92
- Schema conformance rate < 0.99 (provider parity)
- E2E test: any expected relation missing from graph after 5-minute timeout
- Any `relation_contradiction_links` expected by the contradiction E2E test are absent
- Any provider adapter latency p95 exceeds 2× its stated target

A CI run emits a WARNING (does not fail) if:

- Routing accuracy drops below 0.85 but remains above 0.78
- NER F1 for any class drops below 0.72 but remains above 0.65
- NDCG@10 < 0.70 (once query pipeline is implemented)

### D.13 Golden Set Maintenance

- Golden set is version-controlled in `tests/golden/` directory.
- When a schema change affects extraction output structure, update golden expected outputs.
- When a new entity class is added to GLiNER ontology, annotate 20 new examples for that class.
- When a new relation type is added to the registry, add 5 golden extraction examples.
- Golden set review: quarterly or on any major PRD version increment.

---

## E. Final Prioritized Action List

### E.1 Lock Immediately into the PRD

These decisions are architecturally sound, have no remaining open questions of substance, and should be written as non-negotiable constraints in PRD v5:

1. **Outbox/dispatcher is mandatory for all Kafka-emitting services** (S4, S5, S6, S7, S10). No exceptions.
2. **`relation_evidence_raw` staging table** with `partition_key SMALLINT STORED` and `processed BOOLEAN`. Single aggregation worker in v1.
3. **Hash-partitioned `relations` table** (8 partitions by subject_entity_id) established from day one.
4. **Decay class system** with 6 classes and stored `decay_alpha` values in `decay_class_config`. Confidence recomputation cadence per class.
5. **Validity vs confidence decay separation**: `relation_period_type`, `valid_to_confidence`, `valid_to_source`, `invalidated_by_event_id` fields on `relations`.
6. **valid_to heuristic validation**: LLM-extracted valid_to rejected if ≤ evidence_date.
7. **Contradiction linkage table** (`relation_contradiction_links`) as the authoritative link between claims and relation_evidence.
8. **Contradiction worker as async process** with ENV-controlled cadence.
9. **Valkey-backed LSH** with source-type windowing and TTL keys. No in-memory rebuild.
10. **Two-tier dedup**: corroborating evidence from different sources is NOT suppressed.
11. **Two-stage novelty gate**: Stage 1 pre-resolution (mention_text_hash), Stage 2 post-resolution (entity_id + embedding + event structure).
12. **`minhash_entity_mentions` dual-key** (mention_text_hash for Stage 1, entity_id for Stage 2).
13. **Additive normalized routing score** with 7 signals and intent-independent fixed weights (tunable via ENV).
14. **Routing hysteresis bands** at tier boundaries (±0.08 band).
15. **Sentence-aware chunk overlap** (back up 2 complete sentences, not fixed 50 tokens).
16. **Separate HNSW indexes** for chunk_embeddings, section_embeddings, entity_profile_embeddings, relation_summary_embeddings.
17. **Chunk embedding TTL by source type** (NEWS: 90 days, FILINGS: forever, etc.).
18. **Provider Protocol interfaces** (EmbeddingClient, NERClient, ExtractionClient).
19. **model_registry table** in intelligence_db. prompt_templates table.
20. **Relation summaries table** (`relation_summaries`) with `is_current` partial unique index and HNSW on embedding.
21. **GLiNER ontology revision**: 12 classes, `event_type` removed, institution split into 4 classes.
22. **`entity.dirtied.v1` outbox pattern** for embedding refresh.
23. **Testing/evaluation framework** as defined in Section D.

### E.2 Requires One More Architecture Decision

These areas have a recommended direction but need one explicit decision before writing into the PRD:

1. **Query pipeline ranking weights by intent**: the intent-specific weight profiles in B.12 Stage 3 are a reasonable starting point but need to be reviewed and confirmed before becoming a PRD constraint. Decision: accept the proposed profiles or define alternatives?

2. **Relation summary update cadence**: should the summary update be driven by `summary_stale = true` (event-driven) OR by a fixed schedule per decay_class OR both? Recommend: both — event-driven for immediate updates, scheduled for periodic refresh. Decision: confirm.

3. **Advisory lock vs partition ownership for aggregation (v1)**: is a single worker with advisory locks acceptable for v1, or should partition-key ownership be implemented from day one? Recommend: single worker + partition_key column (for schema readiness). Decision: confirm.

4. **GLiNER calibration approach**: threshold tuning (manual, 50 examples per class) vs temperature scaling (requires 500 labeled examples)? Decision: threshold tuning for v1.

5. **Relation summary LLM choice**: Qwen2.5-7B-Instruct (same as extraction) vs a lighter model? Decision: same model for v1.

6. **Old summary retention policy**: retain is_current=false summaries for how long? Decision: 90 days.

7. **Query pipeline caching strategy**: cache entity-centric results in Valkey, invalidate on entity.dirtied.v1? Decision: confirm for v1.

8. **Sector as a GLiNER class in v1**: add or defer? Recommend: defer.

### E.3 Defer to Later Revision

These areas are not blocking for v1 implementation:

1. **Learned re-ranker for routing** (v2+): log routing features now; train classifier later.
2. **Cross-entity relation family summaries** (v2+): pair-level summaries are sufficient for v1.
3. **Embedding model dimension change protocol**: shadow migration is documented; not needed until model changes.
4. **Multiple aggregation workers with partition ownership** (v2+): single worker is fine for local scale.
5. **Cold archive for expired chunk embeddings**: simple deletion is acceptable for v1.
6. **Streaming answer generation**: non-streaming for v1.
7. **Family-level GLiNER class detection** (sector, industry): needs more labeled data.
8. **Entity profile embeddings per entity-type-specific model**: one model for all entity types in v1.
9. **Continuous vs discrete temporal half-life**: discrete classes are sufficient for v1.
10. **Provider parity A/B testing**: conformance tests are sufficient; statistical A/B testing deferred.
11. **Query relevance feedback collection and ranker training**: deferred to post-v1.
12. **Graph-level analytics (family/cluster summaries)**: deferred to v2 after query pipeline is proven.

---

*End of Document — Architectural Revision v5*
*Next: incorporate Section E decisions into PRD v5 schema changes and update service specifications for S6, S7, S10.*
