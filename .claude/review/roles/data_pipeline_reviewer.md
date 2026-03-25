# Data Pipeline Reviewer

> Specialist role for reviewing NLP, ML, and data transformation pipeline correctness.

## Mission

Review data pipeline code (S4→S5→S6→S7) for data quality, ML model correctness, embedding integrity, entity resolution accuracy, and pipeline stage ordering.

## Review Checklist

### Data Quality
- [ ] Input validation at pipeline boundaries (malformed HTML, missing fields)
- [ ] Dedup thresholds correct (news: hard=0.72, soft=0.55; filings: hard=0.85)
- [ ] MinHash signatures stored as INTEGER[] (not BYTEA)
- [ ] NULL handling explicit throughout pipeline
- [ ] Data type consistency (UUIDs, timestamps, enums validated)

### ML Model Usage
- [ ] All ML calls via `libs/ml-clients` (EmbeddingClient, NERClient, ExtractionClient)
- [ ] No direct Ollama, Anthropic, or OpenAI imports
- [ ] Model versions pinned (BGE-large-en-v1.5, GLiNER, Qwen2.5-7B)
- [ ] Embedding dimensions consistent (1024-dim for BGE)
- [ ] Confidence scores bounded [0, 1]
- [ ] Confidence is NOT a retrieval relevance score

### NER & Entity Resolution (S6)
- [ ] GLiNER ontology: 10 classes only (organization, government_body, regulatory_body, financial_institution, person, financial_instrument, location, commodity, index, currency)
- [ ] Entity resolution cascade: exact match → fuzzy match → create new
- [ ] Entity mentions linked to chunks (chunk_entity_mentions table)
- [ ] Routing thresholds: deep >= 0.70, medium >= 0.45, light >= 0.20

### Embeddings (S6)
- [ ] Chunk and section embeddings in SEPARATE HNSW indexes
- [ ] HNSW indexes include partial predicate: `WHERE (expires_at IS NULL OR expires_at > now())`
- [ ] Embedding refresh: 4 separate indexes (chunk, section, entity profile, relation summary)
- [ ] No embedding computation inside DB transactions

### Knowledge Graph (S7)
- [ ] Relations have correct semantic mode (RELATION_STATE vs TEMPORAL_CLAIM)
- [ ] Confidence formula: 4-step, bounded
- [ ] Contradiction detection: runs on 30s cycle
- [ ] entity.dirtied.v1: compacted topic, key = entity_id
- [ ] Graph neighborhood queries bounded (max depth, max nodes)

### Pipeline Ordering
- [ ] S4 → S5 → S6 → S7 → S10 (correct flow)
- [ ] No stage skipping (every article goes through all applicable blocks)
- [ ] Backfill flag (`is_backfill`) propagated through pipeline
- [ ] Each stage produces the event that triggers the next stage

### intelligence_db Safety
- [ ] DDL only from intelligence-migrations init container
- [ ] S6 and S7: `ALEMBIC_ENABLED=false`
- [ ] No CREATE TABLE, ALTER TABLE, or DROP in S6/S7 code
- [ ] Monthly partitions managed by S7's monthly_partition_job

## Compounding Updates
Update this role when new pipeline stages are added, ML models change, or data quality issues are discovered.

Last updated: 2026-03-25
