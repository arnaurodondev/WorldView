# Architectural Review — PRD v4.0 (0011)

**Reviewer**: Claude Sonnet 4.6
**Date**: 2026-03-21
**Document under review**: 0011-PRD-ingestion-pipeline-unstructured-data-final.md
**Format**: Per-section Validation → Weak Points → Improvements → Strong Points, then system-wide synthesis.

---

## 1. Knowledge Graph — Scalability & Write Bottleneck

### Validation

The single-writer constraint is honest and acceptable at thesis scale (< 5,000 enriched documents/day). The append-only evidence model (`relations_raw` → `relation_evidence` → aggregate `relations`) is architecturally sound: writes to `relation_evidence` are always inserts, not upserts, which means the contention point is isolated to the aggregate `relations` row. Advisory locks keyed on `(subject_entity_id, canonical_type, object_entity_id)` would work for moderate scale (< 50 concurrent writers). The 5,000-relation cap on the confidence batch is a reasonable operational bound.

### Weak Points / Risks

**1. Upsert contention is at the worst possible granularity.**
The UNIQUE constraint on `(subject_entity_id, canonical_type, object_entity_id)` means every concurrent INSERT to `relations` for a popular entity triple (e.g., `Apple supplier_of TSMC`) will serialize on PostgreSQL's index lock. During filing season bursts, multiple S6 workers finishing simultaneously will all try to upsert the same hot triples. PostgreSQL serializes these at the tuple level, causing lock queue buildup and timeout cascades on the S7 Kafka consumer commit path.

**2. The confidence batch is a single-process, polling-based job.**
At 5,000 relations per run × 15-minute interval, the batch can process 20,000 relations/hour. If the ingestion rate creates 30,000+ dirty relations/hour during peak load, the batch falls behind permanently. There is no catch-up mechanism — the batch simply caps at 5,000 and moves on, leaving stale confidence values indefinitely.

**3. `entity_dirty_log` becomes a hot table.**
Every graph write inserts two rows (subject and object entity). At 30,000 relations/day × 2 = 60,000 dirty log inserts/day. The cleanup job (delete processed entries after 7 days) is a bulk DELETE that causes table bloat and autovacuum pressure. Under high load, this table has competing read (batch job polling `processed_at IS NULL`) and write (pipeline inserts) patterns on the same index.

**4. Contradiction detection runs inline in Block 12 (hot path).**
The contradiction query joins `claims` on `(subject_entity_id, claim_type, polarity, created_at DESC)` during the Kafka consumer commit path. As the `claims` table grows into tens of millions of rows (partitioned but still large), even the partial index `idx_claims_contradiction_detection` may cause latency spikes if partition pruning doesn't engage correctly on monthly partition boundaries.

**5. S7 holds `intelligence_db` write locks while also being the confidence batch runner.**
If the Kafka consumer is mid-batch upsert and the confidence batch job fires, they compete on the same connection pool and the same rows in `relations`. APScheduler shares the asyncio event loop with the consumer — a slow confidence batch can delay consumer commits.

**6. No horizontal write scaling path is defined.**
The PRD mentions row-level advisory locks as the production-scale path but doesn't define how the key space is sharded across replicas. Without a shard key strategy, adding a second S7 replica reintroduces the same upsert contention.

### Improvements / Alternatives

**A. Decouple `relations_raw` writes from aggregate upserts.**

Make Block 12 write-only to `relations_raw` (always a fast INSERT, no contention). Run a separate periodic "aggregation worker" that reads `relations_raw WHERE NOT aggregated AND created_at < NOW() - INTERVAL '5 minutes'` and performs the aggregate upsert in batches of related triples. This removes the upsert from the Kafka hot path entirely.

```python
# Aggregation worker (runs every 5 minutes, not in Kafka consumer)
async def aggregate_raw_relations():
    pending = await db.fetch("""
        SELECT DISTINCT subject_entity_id, canonical_type, object_entity_id
        FROM relations_raw
        WHERE aggregated = false AND canonical_type IS NOT NULL
        LIMIT 1000
    """)
    for triple in pending:
        async with advisory_lock(hash_triple(triple)):
            await upsert_aggregate(triple)
            await db.execute("""
                UPDATE relations_raw SET aggregated = true
                WHERE subject_entity_id = $1 AND canonical_type = $2 AND object_entity_id = $3
            """, *triple)
```

**B. Partition the `relations` table by `subject_entity_id` hash.**

```sql
CREATE TABLE relations (
  -- same columns
) PARTITION BY HASH (subject_entity_id);

CREATE TABLE relations_p0 PARTITION OF relations FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE relations_p1 PARTITION OF relations FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE relations_p2 PARTITION OF relations FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE relations_p3 PARTITION OF relations FOR VALUES WITH (MODULUS 4, REMAINDER 3);
```

Each S7 replica can be assigned to a non-overlapping partition range (sticky assignment via env var `PARTITION_RANGE=0,1`), eliminating cross-partition contention entirely while allowing horizontal scale to N replicas.

**C. Cursor-based confidence batch with parallel sub-ranges.**

Replace the simple `LIMIT 5000` query with cursor-based pagination over `entity_id` ranges, allowing parallel confidence workers:

```python
# Worker 0: entity_id >= '00000000' AND < '40000000'
# Worker 1: entity_id >= '40000000' AND < '80000000'
# ...
```

Each worker processes its slice of the UUID space independently. No coordination needed.

**D. Move contradiction detection off the hot path.**

Buffer new claim IDs in `entity_dirty_log` with `reason = 'new_claim'`. A dedicated contradiction worker (separate APScheduler job, every 5 minutes) processes the dirty log and emits contradiction events asynchronously. This trades real-time contradiction detection (currently inline) for near-real-time (< 5-minute lag) with no hot-path latency impact.

**E. Replace `entity_dirty_log` polling with a Kafka-based fan-out.**

Emit a lightweight `entity.dirtied.v1` Kafka event (key: `entity_id`, payload: `{entity_id, reason}`) from Block 12. The embedding refresh job consumes this topic instead of polling the DB table. Benefits: no DB hot table, natural at-least-once guarantee, consumer can be paused under load.

### Strong Points

- The append-only evidence model (`relation_evidence` is insert-only) correctly isolates write amplification. Only the aggregate `relations` row contends.
- Separating confidence recomputation from the ingestion hot path is architecturally correct; the evidence-first, confidence-later model is robust.
- The `embedding_migration_state` table for zero-downtime model upgrades is well-designed and rarely seen in MLsys PRDs at this level.
- Advisory lock recommendation for production is pragmatic and implementable without external coordination infrastructure.

---

## 2. Block 2 — Raw Document Ingestion & Near-Duplicate Detection

### Validation

The three-stage pipeline (exact hash → normalised hash → MinHash near-dup) is correct in ordering — cheap checks gate the expensive ones. MinHash with 128 permutations at LSH bands (4 × 32) gives a Jaccard threshold of approximately 0.7, which is standard. Source-type tuned thresholds (0.80/0.95/0.98) are sensible — filings should only be suppressed when nearly identical (errata/amended filings vs originals), while news articles tolerate more variation.

### Weak Points / Risks

**1. The 30-day windowed in-memory LSH introduces recall gaps and fragile startup.**

A breaking story that runs for 45 days will deduplicate correctly within each 30-day window, but article #31 will not detect article #1 as a near-duplicate. For slow-moving regulatory stories (GDPR enforcement, antitrust investigations, long-running SEC inquiries), this causes re-ingestion of near-identical content as the story ages.

The in-memory rebuild on startup at 50K docs/day × 30 days = 1.5M signatures × 512 bytes ≈ **768MB** just for signatures, before LSH index overhead (~200MB per band for 1.5M items). At S5 scale with multiple workers, each worker rebuilds independently — no sharing. At steady-state, a worker restart takes 2–5 minutes to rebuild the index, during which no near-dup detection runs (missing the dedup window silently).

**2. Character 5-gram shingling is fragile for financial text.**

Financial text has low lexical variance: "Q3 2025 revenue grew 12%" and "Revenue in Q3 2025 increased by 12%" have very different 5-gram signatures despite being semantically identical. Conversely, boilerplate legal disclaimers ("This is not financial advice. Past performance...") at the end of every article will generate high-Jaccard similarity between articles that are not duplicates in content.

**3. `minhash_entity_mentions` population at Block 2 is semantically incomplete.**

The novelty gate (Block 8) relies on `minhash_entity_mentions` to ask "has this entity's story been covered recently?" But at Block 2 time, entity resolution has not run. Only entities with exact alias matches are linked. Entities resolved later via fuzzy alias or ANN (which may represent the majority of correctly resolved entities in novel text) are absent from this table. This means the novelty gate will over-emit `high novelty` for entities where the exact alias lookup fails — bypassing the suppression it was designed for, and causing unnecessary LLM extraction on redundant content.

**4. `duplicate_clusters` has no representative stability guarantee.**

If the representative document is later suppressed (e.g., source retracted), deleted, or merged, the cluster orphans its members. There is no cascading update path from `documents.status` to `duplicate_clusters.representative_doc_id`. A query for "all canonical documents about topic X" would traverse the cluster and follow a dead representative.

**5. No cross-source semantic deduplication.**

An SEC 10-K filing and a Finnhub earnings transcript for the same company event are not content-duplicates (different words, different structure) but are semantically redundant for extraction purposes. MinHash will not detect this. The pipeline will run full deep extraction on both, producing redundant (and potentially conflicting) relation extractions from the same underlying facts.

**6. The exact Jaccard refinement step queries `minhash_signatures` per candidate.**

The LSH candidate retrieval (Block 2 step 4c) returns up to N candidates from the in-memory LSH, then the code says "compute exact Jaccard from stored signatures." But `signature_bytes` is stored in PostgreSQL. For N candidates, this is N round-trips to PostgreSQL during the dedup hot path. At 50ms latency per query and N=20 candidates, that's 1 second of blocking per document.

### Improvements / Alternatives

**A. Persistent Valkey-backed LSH instead of in-memory.**

Store LSH bands in Valkey using sorted sets or hashed keys:
```
Key: lsh:band:{band_id}:{bucket_hash}  →  Set of {doc_id, sig_id} tuples
TTL: 90 days
```
Benefits: shared across all S5 replicas, survives restarts, supports sliding windows without rebuild. The 90-day window can be implemented by setting TTL on bucket entries and using Valkey's lazy expiry.

**B. Switch from char 5-gram to word bigram + char 3-gram hybrid shingling.**

Word-level bigrams are more semantically discriminative for financial text and less sensitive to punctuation. Char 3-grams catch abbreviation/spacing variants. A 70/30 weighted blend of the two shingle sets into a single MinHash signature captures both surface and content similarity.

**C. Batch exact Jaccard computation by prefetching candidate signatures.**

In one query:
```sql
SELECT sig_id, signature_bytes FROM minhash_signatures
WHERE sig_id = ANY($candidate_sig_ids)
```
One round-trip for all candidates. Compute Jaccard in-process.

**D. Defer `minhash_entity_mentions` population to after Block 9.**

Move `minhash_entity_mentions` population from Block 2 (S5) to after Block 9 (entity resolution, S6). S6 has the resolved entity IDs available and can write the exact mappings. This costs: novelty gate cannot use the signatures for the current document's own batch (it needs to query other documents). Workaround: pass resolved entity IDs from Block 9 back to a retrospective `minhash_entity_mentions` insert step before Block 10.

**E. Add semantic deduplication via document-level embedding ANN.**

For `medium` and `deep` routed documents, after Block 7 embedding, compute a document-level ANN query on the `chunk_embeddings` HNSW index (using the document's title embedding). If a document from a different source with > 0.92 cosine similarity and same date range exists: downgrade extraction to `light` and link as `semantic_duplicate`. This catches cross-source redundancy MinHash misses.

### Strong Points

- The three-stage ordering (exact → normalised → MinHash) is optimal: cheap checks eliminate most duplicates before the expensive MinHash step.
- Source-type tuned thresholds correctly reflect domain knowledge about acceptable near-dup tolerance.
- Retaining the MinIO silver object for 7 days on suppressed documents enables retroactive reprocessing when thresholds are recalibrated.
- The `duplicate_clusters` table provides explicit cluster membership, enabling better dedup auditing than a simple boolean flag.

---

## 3. Block 4 — GLiNER Entity Detection

### Validation

The current ontology (12 types) is reasonable for a v1 system. GLiNER's zero-shot design means adding types is cheap — no retraining. The per-section batching (16 sections, 450-token truncation) correctly respects the 512-token context window. A 0.30 confidence floor for retention with 0.70 for routing is a pragmatic two-tier approach.

### Weak Points / Risks

**1. Critical missing entity types that degrade graph richness:**

| Missing Type | Why It Matters |
|---|---|
| `commodity` | Oil, gas, lithium, wheat, copper appear in supply chain and macro-exposure chains. Without detection, `supplier_of(TSMC, lithium)` cannot be extracted |
| `sector` | "semiconductor sector", "defense industry" are subjects of macro claims; missing these breaks sector-exposure graph edges |
| `macroeconomic_indicator` | CPI, Fed Funds Rate, yield curve — essential for claims about macro impact on entities |
| `fund_vehicle` | ARKK, Berkshire, pension funds — needed for `invested_in` and `co_invests_with` relations |
| `time_period` | "Q3 2025", "fiscal year 2026" — without this, temporal grounding of events is lost |
| `technology_platform` | AWS, Azure, CUDA, AI models — supply chain and customer-of relations in tech sector |

**2. `event_type` is semantically incorrect as a GLiNER entity class.**

`event_type` in the ontology labels spans like "merger", "IPO", "bankruptcy filing" — these are events, not entities. GLiNER is designed to detect noun phrase entities, not event type mentions. This mismatch will confuse the model and produce low-precision extractions. The downstream `events` table (extracted by Qwen2.5-7B-Instruct) already captures events. This GLiNER class should be removed or renamed to `corporate_action` and scoped to noun phrases like "the acquisition", "the merger" as event references, not event type labels.

**3. `institution` is too broad, reducing alias resolution precision.**

Banks (JPMorgan), universities (MIT), government agencies (Treasury), NGOs (WHO) all share the `institution` type. When `entity_aliases.alias_type` disambiguates by entity type, `institution` provides no useful discrimination. A mention of "The Fed" and "The World Bank" will both match `institution` entities, making the alias lookup pool unnecessarily large.

**4. GLiNER confidence scores are not calibrated probabilities.**

The 0.30 and 0.70 thresholds treat raw model logits as if they were calibrated probabilities. In practice, GLiNER's confidence distribution is model-specific and often biased high or low for specific entity types. Using uncalibrated scores for routing decisions (which then determine whether to spend GPU time on a document) introduces systematic routing errors that cannot be detected without calibration data.

**5. Batch size of 16 at 450 tokens is suboptimal for GPU inference.**

On a modern GPU (A10/RTX 3090), GLiNER's optimal throughput comes from larger batches. 16 sections × 450 tokens = 7,200 tokens per batch — well within GPU memory. Benchmarks suggest doubling to 32 sections per batch reduces per-section latency by 30–40% on GPU with comparable CPU memory usage. The current batch size appears calibrated for CPU (where memory is the constraint), but if GPU is available, it leaves significant throughput on the table.

**6. No handling of overlapping or nested spans.**

GLiNER may detect both "Apple" (company) and "Apple Inc." (company) in the same span range, or "TSMC" (company) within "TSMC CEO" where the correct extraction is "TSMC" (company) + implicit person detection. The current post-processing only filters spans < 2 characters — no non-maximum suppression for overlapping spans of the same or different types.

### Improvements / Alternatives

**A. Add 5 high-priority missing types:**
- `commodity`: oil, gas, lithium, copper, wheat, iron ore
- `macroeconomic_indicator`: CPI, GDP, interest rate, yield, inflation
- `sector`: semiconductor, defense, healthcare, energy, financial services
- `fund_vehicle`: ETF, hedge fund, mutual fund, pension fund
- `time_period`: Q1 2025, fiscal year 2026, "the next three years"

Remove `event_type`. Consider splitting `institution` into `financial_institution` and `government_body`.

**B. Implement confidence calibration via temperature scaling.**

Hold out 500 annotated mentions (manual annotation or GPT-4 silver labels). Fit a temperature parameter `T` such that `sigmoid(logit / T)` aligns with empirical precision at each threshold. Replace raw confidence with calibrated confidence throughout.

**C. Apply soft NMS for overlapping spans.**

```python
def apply_nms(spans: list[Span], iou_threshold=0.5) -> list[Span]:
    spans = sorted(spans, key=lambda s: s.confidence, reverse=True)
    kept = []
    for span in spans:
        if not any(iou(span, k) > iou_threshold for k in kept):
            kept.append(span)
    return kept
```

**D. Increase GPU batch size to 32–64 sections.**

Guard with OOM handler: try batch_size=64, on CUDA OOM reduce to 32, then 16, then 1.

### Strong Points

- Separating NER (GLiNER, Block 4) from entity resolution (Block 9) is architecturally clean — detection and resolution are different problems with different error modes.
- Per-section inference correctly handles documents of arbitrary length without context truncation artifacts.
- The two-threshold design (0.30 for storage, 0.70 for routing) is pragmatic and avoids the common mistake of using a single threshold for both.

---

## 4. Block 5 — Document Routing Score

### Validation

The routing score separates signal assessment from compute-expensive downstream steps. The structure is correct: cheap signals (entity detection output, source metadata) gate expensive operations (embedding, LLM extraction). The forced `deep` for SEC filings and transcripts is operationally pragmatic.

### Weak Points / Risks

**1. Multiplicative structure creates non-linear amplification.**

`routing_score = source_weight × document_length_factor × base_entity_score + watchlist_boost`

With `source_weight = 1.4` (SEC filing), `document_length_factor = 1.0`, and a high `base_entity_score = 3.0`, the score is 4.2 — already above the `deep` threshold. The same entity score from a NewsAPI document (`source_weight = 0.9`) yields 2.7 — also `deep`. The multiplicative source weight doesn't meaningfully change the tier outcome in the high-signal case; it only affects borderline documents, where its influence is disproportionate.

**2. `watchlist_boost = 0.3 × count` is unbounded.**

A document mentioning 20 watched entities adds `6.0` to the score — more than the maximum possible `base_entity_score` in most cases. This makes watchlist presence dominate the routing decision regardless of document quality. A 50-word article mentioning 20 watched entities in passing gets `deep` extraction while a high-quality 2,000-word filing with 5 untracked entities gets `medium`. The signal is inverted.

**3. `document_length_factor = min(1.0, tokens/500)` penalizes breaking news.**

A 150-word breaking-news alert gets factor = 0.30. A 2,000-token SEC filing gets 1.0. Breaking news alerts are often high-priority intelligence (CEO resignation in a tweet-style article, unexpected FDA decision). Length is a poor proxy for importance.

**4. Forced `deep` for all SEC and transcript regardless of content.**

An 8-K cover page, a routine quarterly cash flow disclosure, or a transcript of a scripted investor call intro all get `deep` extraction. These documents have near-zero extraction yield (no novel claims, relations, or events) but consume 3–6 seconds of Qwen2.5-7B-Instruct capacity. At 200 SEC filings/day, this wastes approximately 600–1,200 Qwen inference seconds/day on trivially empty documents.

**5. No recency signal.**

A document published 30 minutes ago and one published 15 days ago receive identical routing scores. For alert-driven use cases, recency is a critical signal: a 15-day-old article about an executive change has lower urgency than a 30-minute-old one. Query-time retrieval would also benefit from recency-weighted routing, as fresh documents are more likely to reflect current entity states.

**6. Hard thresholds produce cliff-edge behavior near boundaries.**

A score of 1.99 → `medium` (no LLM extraction). A score of 2.01 → `deep` (full LLM extraction, ~5s GPU time). This 0.02 score difference should not determine whether 5 GPU-seconds are spent. Threshold tuning changes (recalibration when new sources are added) will cause bulk tier flipping.

### Improvements / Alternatives

**A. Replace multiplicative with additive, normalized formulation:**

```python
def compute_routing_score(doc):
    entity_signal = min(base_entity_score(doc), 3.0) / 3.0  # normalize to [0,1]
    source_signal = (source_credibility(doc) - 0.9) / 0.5   # normalize [0.9, 1.4] → [0,1]
    recency_signal = exp(-hours_since_published(doc) / 48)    # 1.0 now → 0.5 at 48h
    watchlist_signal = min(watched_entity_count(doc) / 5, 1.0) # saturate at 5 entities
    novelty_signal = 1.0  # set to 0.3 if fast MinHash indicates low novelty

    score = (
        0.40 × entity_signal +
        0.20 × source_signal +
        0.15 × recency_signal +
        0.15 × watchlist_signal +
        0.10 × novelty_signal
    )
    return score  # in [0, 1]
```

Tiers: `suppress < 0.15`, `light < 0.40`, `medium < 0.70`, `deep >= 0.70`.

**B. Replace forced `deep` for SEC/transcript with `medium` minimum + content check.**

```python
if source_type in ('sec_filing', 'finnhub_transcript'):
    routing_tier = max(routing_tier, 'medium')  # floor at medium, not deep
    # A separate lightweight LLM call (fast classification, not extraction)
    # can upgrade medium → deep if the document contains forward guidance or events
```

**C. Soft threshold with hysteresis band.**

Documents within ±5% of a tier boundary get `borderline` flag. A secondary re-scoring pass (with embedding-based signals available after Block 7) resolves borderline documents. This prevents bulk tier flipping on threshold recalibration.

**D. Entity density as an additional signal.**

`entity_density = distinct_entity_count / (document_length_tokens / 100)` — articles dense with relevant entities per 100 tokens are higher signal regardless of absolute length.

### Strong Points

- Pre-embedding routing is architecturally correct and materially reduces GPU waste.
- The `feature_scores_json` audit column is excellent — enables offline threshold recalibration with full explainability.
- `watchlist_boost` as a signal (not a tier override) is the right design — it biases rather than dictates.
- The `threshold_version` column in `routing_decisions` enables reproducible re-routing experiments without schema changes.

---

## 5. Block 7 — Embedding Generation

### Validation

BGE-large-en-v1.5 at 1024 dimensions is a strong choice for financial retrieval. The asymmetric instruction prefix (`"Represent this financial document passage for retrieval: "`) is correctly applied as per the BGE paper. The 300-token target with 50-token overlap is a widely used configuration.

### Weak Points / Risks

**1. Fixed 50-token overlap cuts sentences mid-thought.**

A 50-token overlap starting at a token boundary will frequently start mid-sentence, mid-clause, or even mid-word (with subword tokenizers). The resulting embedding for the overlap region carries a dangling context that adds noise without semantic coherence. In retrieval, this manifests as a chunk that appears relevant (the entity name is present) but lacks the predicate that makes it meaningful (the claim about the entity started in the previous chunk).

**2. Section and chunk embeddings share the same HNSW index.**

`is_section_level = true` rows in `chunk_embeddings` sit in the same HNSW index as chunk-level embeddings. At query time, S8 cannot separate "retrieve the most relevant passage" from "retrieve the most relevant section" without filtering on `is_section_level`. HNSW with a boolean filter degrades to a linear scan over filtered results — defeating the purpose of the index. More importantly, section-level embeddings (longer texts, more averaged semantic signal) pollute the k-nearest-neighbours of chunk-level embeddings (shorter, more specific), reducing retrieval precision.

**3. Document-level coarse embedding is too crude.**

`title + first 200 chars of body` is not a meaningful document representation. Titles can be misleading or generic ("Q3 Results"), and the first 200 chars of an SEC filing is the cover page. This embedding will be used nowhere except perhaps for document-level dedup (not specified) and wastes one Ollama call per document.

**4. 300-token chunks are poorly suited for short-turn transcripts.**

Finnhub earnings call transcripts have speaker turns of 20–100 tokens. A 300-token chunk window will merge 3–10 speaker turns, crossing the semantic boundary between analysts' questions and management answers. At retrieval time, a query for "CEO guidance on Q4 margins" will match a chunk that also contains analyst question context, degrading response generation precision.

**5. BGE-large context limit is 512 tokens, not 512 semantic tokens.**

The 300-token target + asymmetric instruction prefix (~8 tokens) + BPE expansion of financial abbreviations (numbers, tickers, SEC form names tokenize to more subwords than word count) means the effective content may be closer to 250 real words. This is not a bug but should be explicitly documented: the "300-token target" is in model subword tokens after the instruction prefix.

### Recommendation

**Keep 300-token target chunk size.** The BGE model is optimized for this range. Increasing to 400–500 tokens risks the instruction prefix + BPE overhead hitting the 512-token hard limit, causing silent truncation.

**Switch to sentence-aware overlap:**

```python
def build_chunk_with_sentence_overlap(sentences, target_tokens=300, overlap_sentences=2):
    chunks = []
    i = 0
    while i < len(sentences):
        chunk_sentences = []
        token_count = 0
        j = i
        while j < len(sentences) and token_count < target_tokens:
            chunk_sentences.append(sentences[j])
            token_count += count_tokens(sentences[j])
            j += 1
        chunks.append(chunk_sentences)
        # Overlap: back up 2 complete sentences, not 50 tokens
        i = max(i + 1, j - overlap_sentences)
    return chunks
```

Two-sentence overlap preserves semantic coherence at chunk boundaries at the cost of marginally more storage (~8% overlap vs current ~17%) but higher retrieval precision.

**Separate section embeddings into `section_embeddings` table:**

```sql
CREATE TABLE section_embeddings (
  section_id UUID PRIMARY KEY REFERENCES sections(section_id),
  embedding VECTOR(1024) NOT NULL,
  -- separate HNSW index -- not contaminating chunk index
);
```

**Speaker-turn-aware chunking for transcripts:**

For `section_type = 'speaker'`, each speaker turn is a natural chunk boundary. Merge short turns (< 50 tokens) with the next turn only. Never split a turn across chunks.

**Drop document-level coarse embedding.** It adds Ollama calls without retrieval benefit. If document-level retrieval is needed by S8, generate it on-demand at query time from cached section embeddings.

### Strong Points

- The 64-text-per-batch Ollama call with 4 concurrent semaphore is correctly calibrated — avoids Ollama queue saturation while saturating GPU.
- The `embedding_status = 'pending'` catch-up worker is a robust fallback for transient Ollama failures.
- Separate `embedding_version` tracking enables the shadow migration protocol in Section 13.
- BGE asymmetric instruction prefix is correctly applied per the model's intended usage.

---

## 6. Model Provider Abstraction (Cross-cutting Concern)

### Validation

The PRD relies on Ollama as the unified local serving layer, which is a reasonable choice. Ollama provides a consistent REST API across different model formats. However, the abstraction is implicit — no adapter pattern is defined anywhere in the PRD, and model names appear hardcoded in env vars throughout.

### Weak Points / Risks

**1. No adapter pattern — model swap requires code changes in multiple locations.**

Swapping BGE for Cohere Embed v3 requires changes in: S6 embedding call (Block 7), S7 embedding refresh (Block 13), S6 entity resolution ANN step (Block 9), S7 relation type canonicalization (Block 11). Each location has its own API call format, error handling, and batching logic. There is no single swap point.

**2. Embedding dimension is hardcoded as `VECTOR(1024)`.**

If a superior embedding model with 2048 dimensions is released (e.g., `text-embedding-3-large` at 3072 dims), a schema migration is required to change the column type on every embedding table. The shadow migration protocol handles this for chunk_embeddings, but not for entity_embeddings, relation_embeddings, or relation_type_registry.embedding.

**3. Output schema drift between models.**

Qwen2.5-7B-Instruct with JSON grammar enforcement produces a known output structure. GPT-4o with JSON mode, or Gemma-27B with GBNF grammar, may produce subtly different null handling, array serialization, or field ordering. The validation logic in Block 10 ("validate entity IDs against known list") may silently accept malformed outputs from alternative models.

**4. Latency calibration is model-local.**

Backpressure thresholds (`MAX_OLLAMA_QUEUE_DEPTH = 20`), timeout values (30s per extraction window), and retry budgets are calibrated for local Ollama inference on a single GPU. If a provider is switched to an external API (e.g., Together.ai for Qwen, Cohere for embeddings), the latency characteristics change by 10–100× and the backpressure thresholds become wrong in both directions: too conservative for fast APIs (throttling unnecessarily) or too permissive for slow APIs (not pausing when overloaded).

**5. No model registry or version tracking.**

`embedding_version = '1'` is a string with no semantic content. If the version is incremented because the prompt changed (not the model), or the model changed (not the prompt), or both, there is no structured way to know what version 1 means vs version 2. At query time, S8 needs to know which embedding version is current to apply the correct query prefix.

**6. GLiNER is local-only with no hosted equivalent.**

The provider abstraction cannot uniformly handle GLiNER (local Python library) and an OpenAI NER endpoint (REST API with different input/output format). Any abstraction layer must accommodate models that have no hosted equivalent.

### Proposed Design

**A. Define a typed `InferenceClient` protocol:**

```python
from typing import Protocol

class EmbeddingClient(Protocol):
    model_id: str
    embedding_dim: int

    async def embed(self, texts: list[str], instruction: str | None = None) -> list[list[float]]:
        ...

class ExtractionClient(Protocol):
    model_id: str
    context_window: int

    async def extract(self, prompt: str, output_schema: type[BaseModel]) -> BaseModel:
        ...

class NERClient(Protocol):
    model_id: str

    async def detect_entities(self, texts: list[str], labels: list[str],
                              threshold: float) -> list[list[EntitySpan]]:
        ...
```

**B. Implement concrete adapters:**

```
services/nlp-pipeline/
  ml/
    embedding/
      ollama_adapter.py      # OllamaEmbeddingClient(EmbeddingClient)
      cohere_adapter.py      # CohereEmbeddingClient(EmbeddingClient)
      openai_adapter.py      # OpenAIEmbeddingClient(EmbeddingClient)
    extraction/
      ollama_adapter.py      # OllamaExtractionClient(ExtractionClient)
      openai_adapter.py      # OpenAIExtractionClient(ExtractionClient)
    ner/
      gliner_adapter.py      # GLiNERClient(NERClient)  (always local)
    factory.py               # build_embedding_client(settings) -> EmbeddingClient
```

**C. Add a `model_registry` table to `intelligence_db`:**

```sql
CREATE TABLE model_registry (
  model_id         TEXT PRIMARY KEY,  -- e.g. 'bge-large-en-v1.5'
  model_type       TEXT NOT NULL,     -- 'embedding', 'extraction', 'ner'
  provider         TEXT NOT NULL,     -- 'ollama', 'openai', 'cohere'
  provider_model_name TEXT NOT NULL,  -- provider-specific ID
  embedding_dim    INT,               -- NULL for non-embedding
  context_window   INT NOT NULL,
  is_active        BOOLEAN NOT NULL DEFAULT true,
  activated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`entity_embeddings.embedding_model` becomes a FK to `model_registry.model_id`, making embedding version semantics structured and queryable.

**D. Provider-specific timeout and retry config:**

```python
PROVIDER_CONFIG = {
    'ollama':  {'timeout': 30.0, 'max_concurrent': 4, 'batch_size': 64},
    'openai':  {'timeout': 60.0, 'max_concurrent': 10, 'batch_size': 20},
    'cohere':  {'timeout': 45.0, 'max_concurrent': 5, 'batch_size': 96},
}
```

Backpressure thresholds in `NLPPipelineConsumer` should adapt based on the active provider's `max_concurrent` setting rather than using the hardcoded `MAX_OLLAMA_QUEUE_DEPTH`.

### Strong Points

- Ollama as the local serving layer is the correct choice — it unifies GGUF, safetensors, and other formats under one REST API, reducing per-model integration surface.
- Using env vars for model names (`EMBEDDING_MODEL`, `EXTRACTION_MODEL`) provides a swap point, even if the adapter code behind it doesn't yet abstract the provider.
- The shadow migration protocol (Section 13) correctly handles the embedding dimension change problem when model upgrades require schema evolution.

---

## 7. Relations Decay & Temporal Modeling

### Validation

The discrete decay class approach is pragmatic and correctly addresses the core requirement: not all facts age equally. The `exp(-α × days)` formula is mathematically well-grounded and computationally cheap. LLMs can reliably output one of 5 class labels — this is a reasonable prompt design choice.

### Weak Points / Risks

**1. Discrete buckets are too coarse for contract-based relations.**

A supply agreement signed for 3 years should have `valid_to ≈ agreement_date + 3 years`. The `slow` decay class (365-day half-life) will keep this relation `active` for years past expiry. The system has no mechanism to model fixed-duration relations. The `valid_to` field exists in the schema but is "rarely extractable" — and when the LLM cannot extract it, there is no fallback other than indefinite retention.

**2. `valid_to` extraction is systematically unreliable.**

Most news articles do not state expiration dates. The LLM will either hallucinate a date, output null (correct but unhelpful), or confuse the evidence date with the validity end date. In testing, LLMs consistently confuse "the partnership was announced on Dec 1, 2025" (evidence date) with "the partnership runs through Dec 2025" (valid_to). Without explicit extraction validation (e.g., `valid_to > evidence_date` constraint), corrupted valid_to values will silently expire valid relations.

**3. No event-triggered relation invalidation.**

When Block 12 extracts an `executive_change` event (e.g., "Tim Cook steps down as Apple CEO"), the `employs(Apple, Tim Cook)` relation should immediately set `valid_to = event_date`. Currently the system waits for decay — at `medium` decay class (90-day half-life), the confidence drops to 0.50 after ~90 days. During those 90 days, the system believes Tim Cook is still employed at Apple. This is a significant graph correctness failure for high-value entity states.

**4. Decay applies to the aggregate relation, not to individual evidence records.**

If a relation has 5 pieces of evidence spanning 3 years, the recency weight applies to `days_since_latest_evidence` — which is the most recent evidence date. All older evidence items decay at the same rate as the most recent one, regardless of their individual ages. An old piece of evidence from 2 years ago contributes the same source weight as a recent one.

**5. Missing schema fields for proper temporal reasoning:**

- `evidence_temporal_confidence FLOAT`: How confident is the LLM that the `evidence_date` is correct? Dates in articles are often ambiguous ("last quarter", "earlier this year").
- `relation_period_type TEXT`: `point_in_time` (e.g., earnings surprise) vs `ongoing` (e.g., supplier agreement). Point-in-time relations should not have decay applied after the event date.
- `invalidated_by_event_id UUID FK events(event_id)`: Enables traversal to understand why a relation ended.
- `contract_start_date DATE`, `contract_end_date DATE`: For contractual relations, explicit dates override decay computation.

**6. The confidence batch does not distinguish stale confidence from current confidence.**

`current_confidence` in `relations` is the batch-computed value, which may be up to 15 minutes stale. At query time, S8 reads `current_confidence` as if it represents the confidence right now. For `fast` decay class relations (14-day half-life), a 15-minute lag is negligible. But for `ephemeral` relations (1-day half-life), a 15-minute lag represents ~1% of the half-life — meaningful for real-time alert use cases.

### Improvements / Alternatives

**A. Event-triggered relation invalidation:**

```python
EVENT_INVALIDATES_RELATIONS = {
    'executive_change': [('employs', None)],           # employs(company, person)
    'acquisition_of':   [('competitor_of', None),      # acquisition changes competitive landscape
                          ('subsidiary_of', None)],
    'merger_with':      [('competitor_of', None),
                          ('partnered_with', None)],
}

async def apply_event_invalidations(event: ExtractedEvent, entity_ids: list[str]):
    for event_type, relation_specs in EVENT_INVALIDATES_RELATIONS.items():
        if event.event_type == event_type:
            for (relation_type, role_filter) in relation_specs:
                await db.execute("""
                    UPDATE relations SET valid_to = $1, invalidated_by_event_id = $2
                    WHERE canonical_type = $3
                      AND (subject_entity_id = ANY($4) OR object_entity_id = ANY($4))
                      AND valid_to IS NULL
                      AND status IN ('active', 'confirmed')
                """, event.event_date, event.event_id, relation_type, entity_ids)
```

**B. Add `valid_to_extraction_confidence` to `relations_raw`:**

Validate in code: if `valid_to IS NOT NULL AND valid_to <= evidence_date`, discard `valid_to` (LLM confused evidence date with expiry date). This simple heuristic eliminates a large class of hallucination errors.

**C. Separate `point_in_time` from `ongoing` relations:**

Add `temporal_class TEXT CHECK (temporal_class IN ('point_in_time', 'ongoing', 'unknown'))` to `relation_type_registry`. For `point_in_time` relations (e.g., `merger_with` after the deal closes), disable decay — the fact that the merger occurred does not decay. For `ongoing` relations (e.g., `supplier_of`), apply decay normally.

**D. Per-evidence recency weight in confidence computation:**

Instead of applying `recency_weight` to the maximum evidence date, compute per-evidence weights:

```
current_confidence = clip(
  Σ(evidence_i.extraction_confidence × evidence_i.source_weight × exp(-α × days_since_evidence_i))
  / Σ(evidence_i.source_weight × exp(-α × days_since_evidence_i)),
  0.0, 1.0
) × corroboration_factor × contradiction_penalty
```

This correctly discounts old evidence individually rather than using the most recent evidence date as a global recency anchor.

**E. Query-time dynamic confidence for S8:**

For `fast` and `ephemeral` relations, pass `days_since_latest_evidence` to S8 and compute confidence dynamically at query time rather than relying on the cached batch value:

```python
def dynamic_confidence(relation, as_of: datetime) -> float:
    days = (as_of - relation.latest_evidence_date).days
    α = DECAY_CLASS_ALPHA[relation.decay_class]
    recency = exp(-α * days)
    return min(relation.batch_base_confidence * recency, 1.0)
```

### Strong Points

- Five decay classes covering ∞ to 1-day half-life correctly span the range of financial relationship temporality.
- Storing `source_weight` at the time of extraction in `relation_evidence` is excellent: if source trust weights change later, historical confidence can be recomputed without re-reading the source documents.
- The confidence batch status transition rules (`candidate → active → inactive → expired`) are well-defined and prevent zombie relations.
- `valid_from` in the aggregate `relations` row enables correct "point-in-time" graph queries at query time ("what did the graph look like on 2025-01-01?").

---

## System-Wide Analysis

### System-Wide Bottlenecks

**Rank 1 — Ollama (single GPU, all inference services competing).**

S6 (GLiNER + BGE embeddings + Qwen extraction) and S7 (BGE entity refresh + Qwen signal summaries) share one Ollama instance. There is no workload separation, priority queue, or admission control. During peak ingestion (e.g., filing season, morning news burst), S6 saturates the GPU and S7's embedding refresh job will silently time out or queue indefinitely. The backpressure mechanism (consumer pause at `MAX_OLLAMA_QUEUE_DEPTH=20`) handles S6 self-regulation but has no effect on S7 embedding jobs competing for the same GPU.

**Mitigation**: Run two Ollama instances — one for S6 (ingestion-path, lower latency SLA) and one for S7 (batch jobs, higher latency tolerance). Route by job type in `factory.py`.

**Rank 2 — `intelligence_db` as the sole shared write database.**

S6 writes `entity_mentions`, `mention_resolutions`, `provisional_entity_queue`. S7 writes `relations_raw`, `relations`, `relation_evidence`, `events`, `claims`. Both run under high concurrency from multiple Kafka consumer threads. The missing write partitioning strategy (see §1) means this is the single largest scale bottleneck in the system.

**Rank 3 — In-memory LSH index rebuild on S5 startup.**

At 1.5M signatures and ~1GB memory, a 2-5 minute cold start window disables near-dup detection. In a rolling restart scenario (e.g., config change), near-duplicates ingested during the cold start window will be stored as canonical documents and then processed through the full pipeline. For high-volume sources (EODHD at 500 articles/instrument/day), this can create thousands of redundant extractions per restart.

**Rank 4 — Confidence batch single-process cap at 5,000 relations.**

If steady-state creates more than 20,000 dirty relations per hour (plausible at 50K documents/day × avg 0.5 new relations per document = 25K relations/day), the batch permanently lags. Stale confidence values in `relations` affect: graph traversal quality in S8, contradiction detection thresholds, and status transitions.

**Rank 5 — Contradiction detection on the Kafka hot path (Block 12).**

The contradiction query joins a large, partitioned `claims` table inline during Kafka consumer processing. As monthly partitions accumulate and the `created_at > NOW() - INTERVAL '90 days'` window spans two partitions, partition pruning may not engage correctly. This is a latency time bomb that manifests only at scale.

---

### Critical Redesign Areas

**1. Ollama multi-instance workload separation** (Rank 1 bottleneck, immediate impact on thesis correctness):
Define `OLLAMA_INGESTION_URL` and `OLLAMA_BATCH_URL` as separate config values. S6 uses ingestion; S7 embedding refresh uses batch. Even a single GPU running two Ollama instances with separate VRAM partitions provides workload isolation.

**2. `intelligence_db` hash-partitioned `relations` table** (Rank 2, prevents production scale):
Hash-partition by `subject_entity_id` as described in §1. This is a schema migration but not a logic change — it's the single most impactful scalability improvement available.

**3. Persistent Valkey-backed LSH** (Rank 3, improves correctness immediately):
Replace in-memory datasketch LSH with Valkey-backed LSH. Eliminates cold start dedup gap. Shared across all S5 replicas. Sliding window via TTL. Cost: one Valkey pipeline call per document during dedup (~2ms).

**4. Event-triggered relation invalidation** (§7 improvement, graph correctness):
The current design will have `employs`, `merger_with`, and `acquisition_of` relations lingering as `active` after the real-world relationship ends. For a financial intelligence system, this is a correctness failure, not a performance issue.

**5. Sentence-aware chunk overlap** (§5 improvement, retrieval quality):
Fixed-token overlap degrades retrieval precision in a way that accumulates silently. At query time, a user asking about specific claims will receive chunks with dangling context. This is correctness-adjacent (wrong information surfaced) not just performance.

---

### Key Strengths of the Overall Architecture

**1. Evidence-first append-only graph model.**
Writing `relation_evidence` as insert-only and computing confidence in a batch job is the correct separation. It enables: temporal versioning (what did the graph look like at time T?), confidence recomputation without re-parsing documents, provenance tracing from any confidence value back to specific sentences, and retroactive source trust updates.

**2. Three-stage deduplication with correct ordering.**
Exact hash → normalised hash → MinHash is optimal: cheap gates eliminate most duplicates before expensive steps. The parameterisation per source type and the 7-day MinIO retention for suppressed documents are operationally mature decisions.

**3. Outbox pattern for reliable Kafka event publishing.**
Using transactional outbox (same DB transaction as the write + separate dispatcher) is the industry-correct approach for exactly-once semantic guarantees over at-least-once Kafka delivery. Most MLsys architectures at this scale skip this and accept message loss.

**4. Subject-based contradiction detection.**
Anchoring contradiction on `subject_entity_id` rather than `claimer_entity_id` is semantically correct. The original (claimer-based) design would produce false contradictions for any entity that makes multiple statements. This fix is non-obvious and represents domain understanding.

**5. intelligence-migrations init container with single ownership.**
Separating DDL ownership for the shared `intelligence_db` from the services that write to it is the correct operational pattern. Without this, migration conflicts, duplicate history entries, and failed service starts due to schema version mismatches are inevitable.

**6. Routing score computed before embedding.**
Block 5 (routing) runs before Block 7 (embedding). This is architecturally correct: the entire embedding + novelty + resolution + extraction stack is gated by a cheap, compute-free signal. At thesis scale, this prevents 30-40% of ingested documents from consuming any GPU time.

**7. Shadow embedding migration protocol.**
The five-phase (shadow_column_added → dual_write → backfill → cutover → cleanup) protocol for zero-downtime model upgrades is rarely implemented this rigorously in research-adjacent systems. Its inclusion demonstrates operational maturity and prevents the common failure mode of all embeddings becoming stale on a model upgrade.

**8. Separation of NER from entity resolution.**
GLiNER detects surface-form mentions; the cascade in Block 9 resolves them to canonical entities. These are different problems: NER is a span detection problem, resolution is a disambiguation/matching problem. Systems that conflate the two (asking the LLM to resolve entities at detection time) suffer from hallucinated canonical IDs and incomplete graphs.

---

*End of review.*
