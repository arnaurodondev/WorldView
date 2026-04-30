# Investigation Report — News-Intelligence Pipeline Quality Deep-Dive

**Date**: 2026-04-29 (initial), **Updated 2026-04-30** with significant new evidence on transit loss, alias generation, and resolution-rate pathology
**Investigator**: Claude (`/investigate` skill, 5 parallel specialist agents on 2026-04-29 + 1 follow-up agent on 2026-04-30)
**Severity**: **CRITICAL — KG is effectively non-functional in spite of all green health checks**
**Scope**: S4 → S5 → S6 (NLP) → S7 (KG) end-to-end. Quality of NER, resolution, scoring, LLM extraction, embeddings, descriptions, relations, summaries, contradictions, AGE shadow.

> **2026-04-30 update note**: Yesterday's headline finding "deep extraction returns `relations: []` for 100% of articles" was a **sample-window bias**, since corrected. The model **does** produce relations and claims; they are silently destroyed in transit by a different bug (F-CRIT-07). The downstream effect (empty KG) is the same, but the fix sequence is materially different. See **Section 6 — 2026-04-30 Update** for the revised picture.

---

## 0. Executive Verdict

The pipeline **looks healthy** (54 containers green, no dead-letter rows, no consumer crashes, ~3,200 articles ingested) but **is producing almost no usable intelligence**. The system is in a state where:

- **The knowledge graph is essentially seeded data only.** 18 of 18 relations in `intelligence_db.relations` are bootstrap rows from 2026-04-24; `relation_evidence_raw`, `relation_evidence`, `relation_summaries`, `relation_contradiction_links` are all **empty**. The Apache AGE shadow graph has **0 nodes / 0 edges**.
- **The LLM extraction layer fires reliably** (Llama-3.1-8B-Instruct via DeepInfra; HTTP 200 OK on every call) and produces claims/events sporadically (intelligence_db: 6 claims / 7 events accumulated over ~5h), but **`relations` is `[]` in 100% of `deep_extraction.complete` log lines**. The model is not producing relational triples.
- **Five different audit-trail tables that exist in the schema are silently empty** (`mention_resolutions`, `article_impact_windows`, `llm_usage_log`, `provisional_entity_queue`, `relation_summaries`). Each has a distinct, identifiable code defect.
- **Three of the eight routing signals are stuck at zero** (`watchlist`, `price_impact`, `novelty`), and a fourth (`source_reliability`) is hardcoded 0.5. Routing tier thresholds were lowered (0.45/0.35/0.20 vs. PRD spec 0.70/0.45/0.20) as a band-aid, hiding the upstream signal failures.
- **The `entity.canonical.created.v1` consumer is half-finished**: 83 canonicals but 38 aliases (≈46% have no alias of their own legal name) and only 206 of 249 expected `entity_embedding_state` rows.

The architecture is sound. The implementation has a series of **integration gaps** that compound — each individually a 1–4-hour fix, but together they make the system look like it works while delivering ~1% of designed value.

**Net intelligence yield**: ~0.2% of articles produce any persisted claim or event. **Zero** articles have produced an extracted relation that survived to `relations`. The display-relevance ranking falls back to `0.4 × routing_score` for 87% of articles, so the front-end news ordering is basically randomised within a tier.

---

## 1. Pipeline State Snapshot (Ground Truth)

### 1.1 Row counts (audit time, 2026-04-29 ~19:00 UTC)

| Stage | Table | Count | Expected (rough) | Verdict |
|---|---|---:|---:|---|
| S5 stored | `content_store_db.documents` | **3,233** | — | OK |
| S6 sectioned | `nlp_db.sections` | **2,839** | ≈3,233 | OK (≈88% reach) |
| S6 chunked | `nlp_db.chunks` | **3,061** | — | tiny ratio (1.08/section) — see §2.2 |
| S6 NER | `nlp_db.entity_mentions` | **18,695** | — | OK class-wise |
| S6 resolution audit | `nlp_db.mention_resolutions` | **0** | ~18,695 | **BROKEN** |
| S6 routing | `nlp_db.routing_decisions` | **2,771** | ≈2,839 | OK volume; field gap |
| S6 routing finalisation | `routing_decisions.final_routing_tier` populated | **0** | ≈2,771 | **BROKEN** |
| S6 embedding (chunk) | `nlp_db.chunk_embeddings` | **2,385** | 3,061 | 78% — backlog |
| S6 embedding (section) | `nlp_db.section_embeddings` | **2,714** | 2,839 | 96% |
| S6 embedding backlog | `nlp_db.embedding_pending` | **310** | 0 | **GROWING** |
| S6 LLM relevance | `document_source_metadata.llm_relevance_score` populated | **400 / 3,081** | ≈2,398 | 17% reach (in-progress) |
| S6 sentiment | `document_source_metadata.sentiment` populated | **400 / 3,081** | ≈2,398 | tied to relevance |
| S6 price-impact | `nlp_db.article_impact_windows` | **0** | hundreds | **BROKEN (auth)** |
| S6 LLM cost log | `nlp_db.llm_usage_log` | **0** | ≈hundreds | **BROKEN (logger=None)** |
| S7 entities | `intelligence_db.canonical_entities` | **83** | — | tiny seed |
| S7 aliases | `intelligence_db.entity_aliases` | **38** | ≥83 | **GAP** (alias < canonical) |
| S7 embedding state | `intelligence_db.entity_embedding_state` | **206** | 249 (83×3) | **GAP (43 missing)** |
| S7 raw relations staging | `intelligence_db.relation_evidence_raw` | **0** | hundreds | **BROKEN (LLM emits []) ** |
| S7 evidence | `relation_evidence` | **0** | — | downstream of above |
| S7 relations | `intelligence_db.relations` | **18** (seeded 2026-04-24) | — | **NO PRODUCTION** |
| S7 summaries | `intelligence_db.relation_summaries` | **0** | — | downstream |
| S7 claims | `intelligence_db.claims` | **6** | hundreds | **starved** |
| S7 events | `intelligence_db.events` | **7** | tens | starved |
| S7 contradictions | `relation_contradiction_links` | **0** | — | starved |
| S7 LLM cost log | `intelligence_db.llm_usage_log` | **0** | — | **Gemini disabled** |
| S7 AGE shadow | Cypher `MATCH (n) RETURN count(n)` | **0** | 83+ | **NEVER POPULATED** |
| Outbox health | `*.outbox_events` status=stuck | 0 | 0 | OK |
| DLQ health | all DLQs | 0 / 0 / 0 | 0 | OK |

### 1.2 Kafka consumer lag

- `content-store-consumer`: 1–30 lag/partition (acceptable, catching up after a polling burst)
- `market-data-prediction-markets`: ~2,000 lag/partition (separate concern, out-of-scope)
- `intelligence.contradiction.v1`: `LOG-END=0` → producer has never emitted (consistent with `relation_contradiction_links=0`)
- `entity.canonical.created.v1`, `entity.dirtied.v1`: low traffic, no backlog
- All other consumer groups: lag = 0

### 1.3 Routing tier distribution (real numbers from `routing_decisions.feature_scores_json`)

| Tier | Count | Pct | Avg composite | Range |
|---|---:|---:|---:|---|
| MEDIUM | 1,785 | 64.5% | 0.409 | 0.350 – 0.592 |
| DEEP | 613 | 22.1% | 0.494 | 0.450 – 0.654 |
| LIGHT | 373 | 13.5% | 0.330 | 0.292 – 0.350 |
| SUPPRESS | 0 | 0% | — | — |

### 1.4 Per-signal contribution (averaged across tiers)

| Signal | weight | MEDIUM avg | DEEP avg | LIGHT avg | Status |
|---|---:|---:|---:|---:|---|
| entity_density | 0.25 | 0.256 | 0.471 | 0.110 | **working** |
| source_reliability | 0.20 | 0.500 | 0.500 | 0.500 | **stuck constant** |
| novelty | 0.15 | 1.000 | 1.000 | 1.000 | **stuck constant** |
| recency | 0.10 | 0.587 | 0.851 | 0.176 | **working** |
| watchlist | 0.10 | 0.000 | 0.000 | 0.000 | **DEAD** |
| price_impact | 0.10 | 0.000 | 0.000 | 0.000 | **DEAD** |
| extraction_yield | 0.05 | 0.233 | 0.321 | 0.198 | **working** |
| document_type | 0.05 | 0.500 | 0.500 | 0.500 | **stuck constant** |

Only **3 of 8 signals (40% of total weight) are dynamic**. The other 5 are constants or zero. A score that varies between 0.29 and 0.65 is doing so on 40% of its nominal information capacity.

### 1.5 Sentiment distribution (n=400, 13% of articles)

- neutral 52.8% (211)
- negative 25.8% (103)
- positive 20.5% (82)
- mixed 1.0% (4)

Plausible distribution; volume bottlenecked by relevance-worker batch cadence.

---

## 2. Findings — Ranked by Severity

Each finding is annotated with **file:line**, the underlying **root cause**, the **observable symptom**, and a **recommended skill**.

### 2.1 CRITICAL findings (block end-to-end intelligence; fix first)

#### F-CRIT-01 · Deep extraction never returns relations (the headline problem)
- **Symptom**: 100% of `deep_extraction.complete` log lines show `relations: 0`. `intelligence_db.relation_evidence_raw` and `relations` are empty (only seeded data).
- **Root cause**: Two-part. (a) Most articles are EODHD/Finnhub blurbs: `section_count=1, chunk_count=1, mention_count=3-4` — too sparse for relational content. (b) The deep-extraction prompt at `libs/prompts/src/prompts/extraction/deep.py` allows free-form `predicate` strings with no vocabulary, no few-shot examples, and an internal contradiction ("Only extract information EXPLICITLY STATED" + "0.50–0.69 = implied or inferred"). With Llama-3.1-8B and short context, the model defaults to producing claims (which are simpler, single-entity) and emitting `relations: []`.
- **Why claims trickle through but relations don't**: Claims are entity-attribute pairs ("Apple revenue +5%"); a single mention is enough. Relations require *two* resolved canonical entities + a meaningful predicate; with only 38 aliases for 83 entities, Stage-1 alias matching fails frequently, so even when the model produces a relation candidate, both `subject_canonical_id` and `object_canonical_id` cannot be filled in `_build_raw_relations` (article_consumer.py:798), and the relation is silently dropped.
- **Fix path**: (1) add 5–10 few-shot examples to the extraction prompt with worked relation outputs; (2) constrain `predicate` to the 27 entries in `relation_type_registry` via the prompt; (3) backfill aliases for the 45 canonical entities currently missing one (see F-CRIT-04); (4) consider upgrading deep-extraction model to Llama-3.1-70B or DeepSeek-R1-Distill-32B for relation tasks specifically.
- **Skill**: `/fix-bug` (prompt) + `/investigate` (model selection)

#### F-CRIT-02 · `mention_resolutions` audit trail never persisted
- **Symptom**: 18,695 entity mentions but 0 audit rows. The 4-stage cascade (alias / ticker / fuzzy / ANN) cannot be observed, debugged, or tuned.
- **Root cause**: `services/nlp-pipeline/.../article_consumer.py:405-423`. `resolution_audit` is returned by `run_entity_resolution_block(...)` and bound to a local; only used to call `record_entity_resolved(...)` Prometheus counters. **The repository call `await mr_repo.add_batch(resolution_audit)` is missing** before `nlp_session.commit()`.
- **Fix**: one line. Insert `await mr_repo.add_batch(resolution_audit)` after metrics emission and before commit.
- **Skill**: `/fix-bug`

#### F-CRIT-03 · `llm_usage_log` permanently empty in nlp-pipeline (cost blind)
- **Symptom**: 0 rows in both `nlp_db.llm_usage_log` and `intelligence_db.llm_usage_log`. We are running ~50 Llama-3.1-8B calls every 30 minutes (relevance worker) plus deep-extraction calls per MEDIUM/DEEP article and have no record of cost, latency, or token counts.
- **Root cause**: `services/nlp-pipeline/.../unresolved_resolution_worker_main.py:59` hardcodes `usage_logger=None`. The `ArticleRelevanceScoringWorker` and the deep-extraction `ExtractionClient` similarly do not receive a logger. The `NlpUsageLogRepository` exists but is not instantiated anywhere.
- **Fix**: instantiate `NlpUsageLogRepository(nlp_session_factory)` at worker construction and thread through to `FallbackChainClient.complete(..., usage_logger=logger)`.
- **Skill**: `/fix-bug` (3 worker entrypoints)

#### F-CRIT-04 · `entity_consumer` does not insert default alias when canonical is created
- **Symptom**: 83 canonical entities but only 38 aliases. Stage-1 alias-exact-match (the highest-confidence resolution path, conf=1.0) misses ~54% of entities outright. This cascades into low resolution → unresolved subject/object refs → relations dropped (F-CRIT-01).
- **Root cause**: `entity.canonical.created.v1` consumer (likely `services/knowledge-graph/.../entity_consumer.py`) creates the row in `canonical_entities` but does not insert a default `entity_aliases` row with `alias_text = canonical_name`. The alias-generation worker (`AliasGenerationClient` via Llama-3.1-8B) was meant to enrich; with the prompt's vague "well-established" criterion (see F-MAJOR-04) it produces ~0–1 aliases per entity, but the *self* alias should not depend on an LLM.
- **Fix**: in `entity_consumer.process_message`, after `canonical_repo.save(...)`, also call `alias_repo.save(EntityAlias(entity_id=..., alias_text=canonical_name, source="self", confidence=1.0))` in the same transaction.
- **Skill**: `/fix-bug`

#### F-CRIT-05 · Wikipedia-article criterion in `UnresolvedResolutionWorker`
- **Symptom**: Provisional entities silently rejected; `provisional_entity_queue` empty. Many real financial entities (subsidiaries, ETFs, sector indices, lesser-known regulators) have no Wikipedia article and are mis-classified as noise.
- **Root cause**: prompt at `services/nlp-pipeline/.../unresolved_resolution_worker.py:54` uses *"would have its own Wikipedia article"* as the entity-vs-noise filter. Trained Llama-3.1-8B treats this very literally.
- **Fix**: replace with a financial-domain criterion + 2–3 worked examples (real entities including obscure ones; non-entity examples like "the company", "shares", date phrases). Add a `context_sentence` parameter so the model has more than the surface text.
- **Skill**: `/fix-bug` (prompt revision)

#### F-CRIT-06 · `routing_decisions` schema missing `final_routing_tier` / `processing_path` columns
- **Symptom**: `SELECT count(*) FILTER (WHERE final_routing_tier IS NOT NULL) FROM routing_decisions` errors with *column does not exist*. Block 8 novelty gate has no place to write its downgrade. Sentinel `processing_path` (full_pipeline / section_embeddings_only / halt) is referenced in code but the column was never added by any Alembic migration.
- **Root cause**: design document `docs/services/nlp-pipeline.md` describes these columns as the way Block 8 communicates with downstream blocks, but the actual migration only created `routing_score`, `tier`, `feature_scores_json`. The novelty downgrade currently mutates an in-memory variable that is discarded at end of consumer cycle.
- **Fix**: Alembic migration adding both columns + repository UPDATE; persist Block 8's decision.
- **Skill**: `/migrate-db` then `/fix-bug`

### 2.2 MAJOR findings (limit yield severely; fix soon)

#### F-MAJOR-01 · Articles are too short for meaningful extraction (`chunks ≈ sections`)
- **Symptom**: 2,839 sections but only 3,061 chunks (1.08 chunks/section). Most EODHD/Finnhub items are 1–3 sentence headlines/leads. Deep extraction on such snippets is the hardest case for LLMs — and the empirical relation yield is 0.
- **Root cause**: ingestion adapters store the *summary* / *title* fields verbatim; full article HTML is not fetched for sources where it would be available.
- **Fix path**: enrich the S4 EODHD adapter to follow the `link` URL and fetch full body via the existing relay (Trafilatura/Readability is already in S5). Long-form sources (SEC EDGAR 8-K, earnings transcripts) work fine; news adapters underperform because they're operating on titles.
- **Note**: This single fix would likely 5–10× the relation/claim/event yield, more than any prompt tuning.
- **Skill**: `/investigate` then `/implement` (S4 adapter wave)

#### F-MAJOR-02 · `PriceImpactLabellingWorker` blocked by 401 Unauthorized
- **Symptom**: every HTTP request to `http://market-data:8003/api/v1/market-data/ohlcv/{symbol}` returns 401. `article_impact_windows = 0`. The `price_impact` routing signal stuck at 0.0 for everyone.
- **Root cause**: market-data S2 enforces `InternalJWTMiddleware` (PRD-0025); `MarketDataClient` in nlp-pipeline does not attach an internal JWT.
- **Fix**: same pattern S6 already uses for other internal calls — sign an `X-Internal-JWT` with the system service account.
- **Skill**: `/fix-bug`

#### F-MAJOR-03 · Watchlist Valkey set is empty
- **Symptom**: `redis-cli SMEMBERS nlp:v1:watched_entities` → empty. `watchlist` routing signal = 0.0 for every article. The portfolio.watchlist.updated.v1 consumer is healthy but has nothing to consume because portfolio S3 has not emitted any watchlist-add events (probably no test users have a watchlist with mapped instruments yet).
- **Fix**: seed a small watchlist for the test/dev tenant; add a healthcheck that warns when the set has been empty for >24h.
- **Skill**: `/investigate` (data seeding)

#### F-MAJOR-04 · Description provider defaulted to `none` → all non-instrument entities have template descriptions
- **Symptom**: `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER=none` (default in `config.py:107`); `EntityDescriptionClient` returns the deterministic fallback `"{name} is a {type}."` for every non-financial entity. Non-instrument `definition` view embeddings are clustered near a degenerate centroid, so semantic search across non-instruments collapses.
- **Fix**: enable Gemini 3.1 Flash Lite (cheap, ≈$0.075/1M input tokens) — set `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER=gemini` + `KNOWLEDGE_GRAPH_GEMINI_API_KEY`. Cost cap (`KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD=50.0`) is already implemented.
- **Skill**: configuration change (no code) + verify against `llm_usage_log`

#### F-MAJOR-05 · `embedding_pending` backlog grows unbounded (310 rows)
- **Symptom**: failed chunk embeddings are written to `embedding_pending` but never retried successfully. Each failing chunk re-enqueues, no max-attempts → unbounded growth.
- **Root cause**: `EmbeddingRetryWorker` either is not registered with the scheduler or its retry attempts hit the same DeepInfra rate-limit/timeout window that caused the original failure. No exponential backoff. No dead-letter cap.
- **Fix**: add `(retry_count, last_attempted_at)` columns; drop after 5 failures with reason logged; verify the worker is actually scheduled.
- **Skill**: `/fix-bug` + `/migrate-db`

#### F-MAJOR-06 · 43 missing `entity_embedding_state` rows (provisioning race)
- **Symptom**: 206 rows for 83 canonicals; 75 financial_instrument × 3 + 8 non-instrument × 2 = 241 expected (rough). Either the `ensure_rows_exist` initialiser is racing the first enrichment cycle, or the migration that backfills was incomplete.
- **Fix**: add a startup repair task that calls `ensure_rows_exist(entity_id, entity_type)` for every canonical entity that has fewer than the expected number of view rows.
- **Skill**: `/fix-bug`

#### F-MAJOR-07 · `relation_summaries` empty (downstream of F-CRIT-01)
- **Symptom**: SummaryWorker (13C) runs every 60min, finds 0 summary-stale relations with non-zero evidence count → does nothing. `relation_summaries` empty → `EmbeddingRefreshWorker` (13F) has nothing to embed → relation semantic search returns nothing.
- **Fix**: starts working as soon as F-CRIT-01 is fixed; verify `prompt_templates` table has a row for relation summary template.

#### F-MAJOR-08 · AGE shadow graph never populated
- **Symptom**: `worldview_graph` exists in `ag_graph` catalog but `MATCH (n) RETURN count(n)` returns 0. Cypher endpoints `/api/v1/graph/cypher/path` and `/neighborhood` return empty results.
- **Root cause**: `AgeSyncWorker` is registered (per scheduler) but no Cypher CREATE statements appear in logs — likely the watermark cursor is at 0 but the implementation has a bug fetching from the partitioned `relations` table, or the worker is silently skipping due to a feature flag.
- **Fix**: trace the worker; add structured log per CREATE attempt. With only 18 relations to sync, this should be trivial.
- **Skill**: `/investigate`

### 2.3 MINOR findings (quality drag; fix opportunistically)

#### F-MIN-01 · `source_reliability` hardcoded constant 0.5
- 20% of routing weight is informationless. `source_trust_weights` table exists in migrations but is not populated and not queried.

#### F-MIN-02 · `novelty` hardcoded 1.0 in initial routing
- Block 8 novelty gate downgrades the *tier* but cannot update the *score* (F-CRIT-06 missing column). Pre-novelty routing optimistically assumes every article is novel. Even after the column is added, if MinHash/Valkey LSH is unavailable, fallback is 1.0 (assume novel), so duplicates aren't penalised at routing time.

#### F-MIN-03 · `document_type` hardcoded 0.5
- Same pattern as source_reliability. Document-type weight contributes nothing to routing. SEC 8-K should score very differently from a Finnhub headline.

#### F-MIN-04 · Section truncation uses word-count, not GLiNER subword tokenizer
- 450-word truncation → potential off-by-30%-on-token-count mismatch. Long sentences get clipped mid-clause occasionally. Use GLiNER's actual tokenizer.

#### F-MIN-05 · Deep-extraction prompt internal contradiction
- "Only extract information EXPLICITLY STATED" then "0.50–0.69 = implied or inferred". With small models this is observably reducing extraction recall. Either remove the contradiction or align (e.g., `< 0.70 do not include`).

#### F-MIN-06 · No few-shot examples in any extraction prompt
- Deep extraction, alias generation, unresolved resolution, relation summary — none have worked examples. Adding 3–5 examples per prompt typically yields 20–40% F1 improvement on small models.

#### F-MIN-07 · Alias generation prompt vague on "well-established"
- Gives no source (SEC vs Wikipedia vs Bloomberg) and no examples. Recall is poor; combined with the missing self-alias (F-CRIT-04) this is the alias-table 38<83 gap.

#### F-MIN-08 · Relation-summary prompt template not integrated
- `libs/prompts/src/prompts/knowledge/summary.py` has `{evidence_statements}` as the only placeholder and no docstring binding to the worker. Whether this is dead code or wired but never called isn't fully clear from the audit.

#### F-MIN-09 · LLM relevance worker batch size 50 / 30 min
- Throughput ≈1,800 articles/day. Backlog of MEDIUM/DEEP articles never fully drains under load. Increase batch to 200 (DeepInfra rate limit allows) or shorten cadence.

#### F-MIN-10 · `intelligence.contradiction.v1` topic never produced
- Downstream of F-CRIT-01 (no extraction → no contradictions to detect). Will resolve naturally.

### 2.4 Architectural / strategic findings

#### A-ARCH-01 · `chunk_text_key` (MinIO Option B) costs storage with no current consumer
- Every chunk is uploaded to MinIO at `nlp-pipeline/chunk-text/{doc_id}/{chunk_id}/body/v1.txt` for ALL tiers. Nothing currently reads these objects. Unless RAG/Chat (S8) starts reading them for retrieval, this is pure storage growth.

#### A-ARCH-02 · No evaluation/eval-set framework for any LLM output
- We have no held-out test set, no inter-rater agreement scoring, no precision/recall metric on entity extraction or relation extraction. Without this, prompt tuning is just opinion.

#### A-ARCH-03 · No prompt versioning or A/B testing
- Prompts live in `libs/prompts` as Python strings. No version pinning per article. Re-prompting with a better template won't be possible without re-running the pipeline.

#### A-ARCH-04 · `prompt_templates` table exists in `intelligence_db` but is unused
- The table seems intended to be the version registry for relation-summary prompts. Currently unused — schema drift between intent and implementation.

---

## 3. Bloomberg-Grade Enhancement Roadmap

The system has the right *shape* of a Bloomberg/FactSet/Sentieo competitor — entity-centric news + KG + relations + screener. To actually compete, the gap analysis below is what matters most.

### 3.1 First, fix what's broken (Tier-0 — blocking)

| # | Item | Effort | Unlock |
|---|---|---|---|
| 0.1 | F-CRIT-02..F-CRIT-06 (5 audit-trail / persistence bugs) | 1–2 days | Visibility into what the pipeline is doing |
| 0.2 | F-MAJOR-02 (price-impact 401) | 0.5 day | Real `price_impact` signal + `display_relevance_score` |
| 0.3 | F-MAJOR-04 (Gemini description provider on) | 0.5 day | Non-template descriptions for non-instruments |
| 0.4 | F-MAJOR-01 (full article body, not just summary) | 2–3 days | 5–10× extraction yield |
| 0.5 | Few-shot deep-extraction prompt + predicate vocabulary constraint | 1 day | First non-zero relation production |

Until tier 0 is done, every other enhancement is premature optimisation.

### 3.2 Quality systematics (Tier-1 — core competitor parity)

| # | Item | Why Bloomberg has this | Effort |
|---|---|---|---|
| 1.1 | **Eval set + auto-grading harness** for entity, claim, relation, sentiment. ~500 hand-labelled articles; nightly precision/recall report. | Bloomberg's news desk has this. Without it, prompt iteration is blind. | 1 week |
| 1.2 | **Prompt versioning** in `prompt_templates` with `template_id` recorded on every output row (claims, relations, summaries). Allows A/B and rollback. | Industry standard. | 3 days |
| 1.3 | **Source trust matrix** populated and used. SEC 8-K trust 0.95; Reuters 0.85; Finnhub 0.55; Reddit (if added) 0.30. Per-source decay weights too. | This is the single biggest differentiator: known-good sources should drive deeper extraction. | 2 days |
| 1.4 | **Document-type-aware extraction prompts**. 8-K filings, earnings transcripts, analyst notes, press releases each have characteristic structures. Currently one prompt for all. | FactSet/Sentieo do this. | 1 week |
| 1.5 | **Multi-document cross-validation**: when N independent sources report the same claim, boost confidence; when they disagree, raise contradiction *immediately* (don't wait for the 30-min ContradictionBatchWorker). | Bloomberg flags conflicting analyst calls in real time. | 1–2 weeks |
| 1.6 | **Coreference + cluster resolution per article** before entity resolution. "Apple" / "the company" / "AAPL" / "the iPhone maker" all resolve to one entity within an article. Currently each surface is resolved independently → noisy relations. | Standard NLP pipeline. | 1 week |

### 3.3 Differentiated capabilities (Tier-2 — beat the incumbents)

| # | Item | Differentiator |
|---|---|---|
| 2.1 | **Causal chain reconstruction**: when a Fed rate decision triggers a sell-off in regional banks, surface the chain (Fed → rates → bank funding → deposit risk → KRE) as a navigable graph in the UI. Bloomberg shows the news; we show the *transitive* impact. | Cypher path queries (`/api/v1/graph/cypher/path`) already exist; need a UI surface and a "blast radius" scoring algorithm |
| 2.2 | **Entity event timelines** — for each canonical entity, an automatically curated timeline of major events (M&A, earnings, regulatory, management). Powered by `events` partitioned table; needs UI + dedup logic. | Sentieo's "company timeline" is its biggest selling point |
| 2.3 | **Relation provenance + replay**: for any edge in the graph, show every supporting evidence statement with source and date. Click an edge → modal with all evidence rows. | This makes the KG *auditable*, which is a finance-compliance requirement and a moat |
| 2.4 | **"Why now?" briefing on every alert**: when a flash alert fires, generate a 3-bullet "what changed in the last 24h that matters for entity X" using KG neighborhood + relation summaries. | Most platforms surface alerts; few explain them |
| 2.5 | **Sector-level narrative coherence checks**: when 5+ articles in a sector cluster shift sentiment in the same direction within a window, raise a "regime shift" signal. | This is what hedge funds pay $2k/seat for in Sigmoidal/RavenPack |
| 2.6 | **Earnings-window anomaly detection**: cross-reference deep-extraction `claim_type=GUIDANCE_CUT` events with `article_impact_windows` price moves; flag when guidance cuts are *not* moving the stock (positioning-implied surprise) | Differentiator vs. read-only news terminals |
| 2.7 | **Insider transaction × news cooccurrence**: 13D-8 worker (PRD-0018) ingests insider txns; cooccur with same-week news. Rare, high-signal pattern. | Bloomberg has this but it's expensive and clunky |
| 2.8 | **Polymarket × news consistency**: PRD-0019 ingests Polymarket odds; flag when news sentiment trends one way but odds trend the opposite. | Novel; we'd be the first finance platform with this |
| 2.9 | **Macro-regime conditioning**: relation `EXPOSED_TO_THEME` tags entities to themes (rates, AI, China). Allow filtering `news/top` by *theme* not just entity. | First-class theme querying is Bloomberg-grade |
| 2.10 | **Knowledge-graph-conditioned RAG**: S8 RAG/Chat currently retrieves chunks; route queries through the KG first to ground generation in canonical relations + recent claims. | This is the *correct* architecture for finance LLMs; we already have all the pieces, just not connected |

### 3.4 Observability / production hygiene (Tier-3 — never-mentioned-but-essential)

| # | Item |
|---|---|
| 3.1 | Per-stage Prometheus counters with per-tier breakdowns: `articles_processed{tier="deep"}`, `extractions_attempted`, `extractions_with_relations`, `mention_resolution_outcome{stage,result}`. Wire to a Grafana board. |
| 3.2 | DLQ + outbox sweep dashboards (we have the tables, not the views) |
| 3.3 | LLM cost dashboard once F-CRIT-03 is fixed: spend per worker, per provider, per article tier; budget alerts |
| 3.4 | Ingestion freshness SLO: P95 from `published_at` to `nlp.article.enriched.v1` < 5 min; alarm on breach |
| 3.5 | Embedding model coverage SLO: ≥95% of canonical entities have all expected views populated within 24h |
| 3.6 | Per-source extraction yield (claims/article, relations/article, events/article) reported daily; alert if a source's yield drops by >50% week-over-week (regression detector) |
| 3.7 | Periodic LLM eval runs against the held-out set (3.1 above), failing the build if precision drops below threshold |

---

## 4. Recommended Next Steps

A staged plan, ordered for compounding leverage.

### Sprint 1 — "Make it work" (1 week)

1. **`/fix-bug`** F-CRIT-02 (mention_resolutions write) — 1h
2. **`/fix-bug`** F-CRIT-03 (`llm_usage_log` writers in 3 workers) — 2h
3. **`/fix-bug`** F-CRIT-04 (`entity_consumer` self-alias insert) — 1h
4. **`/fix-bug`** F-CRIT-05 (UnresolvedResolutionWorker prompt) — 2h
5. **`/migrate-db`** + **`/fix-bug`** F-CRIT-06 (routing_decisions schema) — 4h
6. **`/fix-bug`** F-MAJOR-02 (price-impact internal JWT) — 4h
7. **`/fix-bug`** F-MAJOR-04 (Gemini provider config) — 1h + monitor
8. **`/fix-bug`** F-MAJOR-05 (embedding_pending bound + retry caps) — 4h
9. **`/fix-bug`** F-MAJOR-06 (entity_embedding_state repair task) — 2h

End-of-sprint expectation: KG starts producing real claims/events; descriptions become real; cost log populates; routing tier finalisation tracked end-to-end.

### Sprint 2 — "Make it good" (2 weeks)

1. **`/prd`** for full-article-body S4 enrichment (F-MAJOR-01) — produces a PRD; then `/plan`, then `/implement`
2. **`/fix-bug`** all F-MIN items (especially few-shots, predicate vocab) — 2 days
3. **`/investigate`** AGE shadow worker (F-MAJOR-08) — half day
4. Stand up the eval set (Tier-1.1) — 1 week labelling effort, 2 days harness

### Sprint 3 — "Make it Bloomberg-grade" (2–4 weeks)

1. **`/prd`** Tier-2 differentiated capabilities (causal chain, entity timeline, KG-conditioned RAG, sector regime detection)
2. Plan the most leveraged 2 of the 10 (suggestion: 2.1 Causal chain + 2.10 KG-conditioned RAG)

---

## 5. Compounding Updates Applied

Per the investigation skill's mandatory compounding step:

| Document | Update |
|---|---|
| `docs/BUG_PATTERNS.md` | **Should add** BP-26x..BP-26y for the six patterns: (a) audit-table writer omitted while data is computed, (b) `usage_logger=None` hardcode, (c) Avro/JSON dual-mode where dropped fields silently disappear, (d) `EntityDescriptionClient` `provider="none"` default, (e) routing-decision finalisation columns missing, (f) Wikipedia-criterion as entity classifier. Recommend `/fix-bug` apply these. |
| `.claude/review/checklists/REVIEW_CHECKLIST.md` | Add: "When a function returns an audit/diagnostic value, verify it is also persisted, not only used for metrics." |
| `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` | Add: "`*_logger=None` parameter at call site = persistent silent failure." |
| `docs/services/nlp-pipeline.md` | Note that `final_routing_tier` and `processing_path` are documented but not implemented in schema — flag as drift. |

Memory updates (auto-memory): I'll record the key non-obvious findings (deep-extraction returns 0 relations universally; routing thresholds were lowered as band-aid; Gemini default off; AGE shadow empty) so future sessions don't have to re-derive them.

---

## Open Questions

- Should we set a **service-level extraction yield SLO** (e.g., relations/article ≥ 0.5 averaged over 7d)? The current implicit SLO is 0, which is why nobody noticed.
- The 6 claims that *did* land in `intelligence_db.claims` — do they have valid `entity_id` references and meaningful `claim_text`? Worth a 5-minute sanity check before declaring the whole thing zero-output. (Their timestamps 14:44–15:47 suggest they came from the same window as the recent Llama calls; a likely-good sample.)
- For Tier-2 enhancements, what's the user's priority — UX (timelines, briefings) or analytics (causal chain, regime shift)?

---

**Verdict reiterated**: the platform's bones are right. About 12 well-scoped fixes (≈1 sprint) move it from "all-green dashboards / zero output" to "actually producing intelligence". From there, two more sprints buy genuinely Bloomberg-competitive capabilities that the incumbents charge $2k+/seat for.

---

## 6. 2026-04-30 Update — Transit Loss, Alias Generation, Resolution Pathology

User flagged that the alias-generation logic was supposed to be richer (EODHD ticker/name/ISIN + Gemini-context-aware alias generation per new entity) and that claims/events should be much higher. A focused follow-up investigation produced six **CRITICAL** new findings and substantially revised yesterday's headline. Net effect: the **single biggest cause of empty KG is not LLM behaviour, it is silent drop on entity-resolution miss in the producer's `_build_raw_*` helpers**, made catastrophic by an under-seeded canonical store and a half-wired alias enrichment path.

### 6.1 Headline correction

**Yesterday's claim** (F-CRIT-01 in §2.1): *"Deep extraction never returns relations — `relations: 0` in 100% of `deep_extraction.complete` log lines"*. **This was sample bias** — the 30-line tail I happened to read was a low-yield window. A wider sample shows ~14-20% of articles produce non-empty relations (e.g., `relations: 6, claims: 3` on doc `019dd9c0-…`; `relations: 4` on doc `019dd9ad-…`). The LLM is doing its job. The empty-KG symptom is real, but the **root cause is downstream** (see F-CRIT-07 below). This update **supersedes F-CRIT-01**'s root-cause statement; F-CRIT-01 is reclassified as a yield-quality issue (deep extraction yield is lower than it should be, but it is not zero).

### 6.2 New CRITICAL findings

#### F-CRIT-07 · LLM extractions silently dropped on resolution miss (THE main bottleneck)
- **Symptom**: For the same `doc_id`, producer log shows `claims: 5` but consumer log shows `claims: 1` or `claims: 2`. For relations, ~100% drop. The transit between `deep_extraction.complete` and `enriched_article_processed` is destroying most of the work.
- **Root cause**: `services/nlp-pipeline/.../article_consumer.py:793-796` builds `entity_id_by_ref` ONLY from RESOLVED mentions (`if m.resolved_entity_id is not None`). The deep-extraction prompt at `libs/prompts/.../deep.py` instructs the LLM to use entity_ref values "drawn ONLY from this list: {entities}" — but `{entities}` is filled at `services/nlp-pipeline/.../deep_extraction.py:158` with `[m.mention_text for m in mentions]`, i.e., **all mentions including unresolved ones**. So the LLM is encouraged to pick surfaces that don't have a canonical ID, then `_build_raw_relations` (line 852), `_build_raw_events` (line 890), `_build_raw_claims` (line 918) silently `continue` on the lookup miss.
- **Why relations drop ~100% but claims drop ~50-60%**: relations need TWO resolved endpoints; claims need ONE. With per-class resolution rates as low as 0% (currencies, regulators, gov bodies — see F-CRIT-09), conjunction probability collapses.
- **Fix**: either (a) build `entity_id_by_ref` to include unresolved mentions with a synthetic `provisional_queue_id` and pass `entity_provisional=True` flag to S7 (the `_build_raw_relations` already accepts this field, line 860), or (b) restrict the LLM prompt to resolved mentions only. Option (a) preserves the data and lets S7 attach the provisional queue.
- **Skill**: `/fix-bug` (3 functions to update, ~2h)

#### F-CRIT-08 · `claim.extracted` Kafka topic is orphan
- **Symptom**: `nlp_db.outbox_events` has **141 dispatched** rows for topic `claim.extracted`. The topic exists (`claim.extracted` and `claim.extracted.v1` are both registered). Kafka `consumer-groups --describe --all-groups` returns **no consumer group** subscribed to it. Grep across all services confirms: only the NLP-side producer references the topic name; **nothing on the KG side or any other service consumes it**.
- **Root cause**: Either deprecated dual-write path (claims now flow inside `nlp.article.enriched.v1` as `raw_claims`) or planned consumer that was never built. The dispatcher's docstring at `services/nlp-pipeline/.../outbox/dispatcher.py:6` lists "claim.extracted" as one of three output topics, indicating the producer side was finished and the consumer side was forgotten.
- **Impact**: 141 messages produced, zero processed. Storage waste only (no functional impact since `raw_claims` carries the same payload via the enriched topic).
- **Fix**: either remove the dual-write at the producer (recommended), or build/wire the consumer if an independent claims pipeline is intended.
- **Skill**: `/refactor` (remove dead-write) or `/investigate` (decide intent first)

#### F-CRIT-09 · Resolution rates per entity class are catastrophically low
- **Data** (from `entity_mentions` GROUP BY `mention_class`):

  | mention_class | total | resolved | pct |
  |---|---:|---:|---:|
  | organization | 10,394 | 1,060 | **10.2%** |
  | person | 1,850 | 7 | **0.4%** |
  | financial_institution | 1,740 | 99 | **5.7%** |
  | financial_instrument | 1,706 | 295 | **17.3%** |
  | location | 1,545 | 1 | **0.1%** |
  | index | 470 | 10 | **2.1%** |
  | commodity | 367 | 35 | **9.5%** |
  | macroeconomic_indicator | 225 | 2 | **0.9%** |
  | currency | 202 | 0 | **0.0%** |
  | regulatory_body | 115 | 0 | **0.0%** |
  | government_body | 81 | 0 | **0.0%** |

- **Per-document distribution**: **1,833 of 2,839 docs (66%) have ZERO entity resolution.** Only 5 docs cleared the 80% bar.
- **Implication for F-CRIT-07**: in 66% of documents, every extracted claim/event/relation is silently dropped because `entity_id_by_ref` is empty.
- **Skill**: this is structural; root cause is F-CRIT-04 (sparse aliases) + F-CRIT-10 (missing canonical seeds for entire classes). Fix those.

#### F-CRIT-10 · Seven of eleven GLiNER classes have ZERO canonical entities
- **Data** (from `canonical_entities` GROUP BY `entity_type`):

  | entity_type | count |
  |---|---:|
  | financial_instrument | 40 |
  | industry_group | 27 |
  | sector | 11 |
  | technology_theme | 4 |
  | industry | 1 |

- **Notably missing** (zero canonicals despite NER finding mentions): `government_body`, `regulatory_body`, `currency`, `person`, `financial_institution`, `location`, `commodity`, `macroeconomic_indicator`, `index`. The KG cannot resolve "Federal Reserve", "ECB", "Janet Yellen", "USD", "Crude Oil", "S&P 500", or any commodity / regulator / central banker because **the canonical store has nothing for them to match against**.
- **Fix path**: bootstrap-load canonical entities for the missing classes from authoritative open sources:
  - **Currencies**: ISO-4217 list (~180 entries) → seed all as `entity_type=currency` with their codes as TICKER aliases
  - **Regulatory & government bodies**: hand-curated list of ~50 (SEC, FCA, ECB, BoE, BoJ, PBoC, RBI, Fed, FOMC, FINRA, CFTC, SEBI, BaFin, ESMA, …) with common abbreviations as aliases
  - **Indices**: ~30 majors (S&P 500, NASDAQ-100, DJIA, FTSE 100, DAX, CAC 40, Nikkei 225, Hang Seng, Shanghai Composite, EURO STOXX 50, …) with abbreviations as aliases
  - **Commodities**: ~30 majors (Crude Oil, Brent, WTI, Natural Gas, Gold, Silver, Copper, Wheat, Corn, Soybeans, …) with their futures tickers
  - **Macroeconomic indicators**: ~50 (CPI, PPI, NFP, GDP, ISM Manufacturing, Unemployment Rate, Fed Funds Rate, 10Y Treasury Yield, …)
  - **Persons**: rely on per-article provisional creation (this is too long-tail for seed); but ensure provisional path actually works (currently `provisional_entity_queue` is empty, suggesting that pipeline is broken too — see F-MAJOR-10)
- **Skill**: `/prd` for the seed-data initiative; produces a list of authoritative bootstraps that can be loaded by Alembic data migration

#### F-CRIT-11 · Instrument consumer ignores EODHD `name` field as alias
- **Symptom**: `entity_aliases` shows **0 NAME aliases**. Only TICKER (32, mostly seed_demo duplicates) and EXACT (6, mostly synthetic placeholders).
- **Root cause**: `services/knowledge-graph/.../instrument_consumer.py:129` reads `value.get("name")` from the InstrumentCreated event (which IS populated by S3 fundamentals_consumer from EODHD `General.Name`). The name is sanitised at line 130-135 and used to set `canonical_name`. **It is never inserted as an `EntityAlias` row.** The `_try_insert_alias(canonical_name, normalized_name, "EXACT")` at line 192 inserts the canonical_name (which is *also* the company name in most cases), but if the EODHD `Name` differs from the canonical (e.g., legal name vs trade name), the difference is lost.
- **Fix**: after line 203, if `value.get("name")` is non-empty and differs from canonical_name (case-insensitive), insert it as `alias_type="NAME"`.

#### F-CRIT-12 · Seed data duplicated 4× per ticker; instrument creation creates "Instrument-{uuid}" placeholders
- **Symptom**: 32 TICKER aliases / 8 unique tickers = **each seeded ticker has 4 alias rows**. 6 EXACT aliases for instruments named `Instrument-019dbbdb`, `Instrument-019dbf56`, etc.
- **Root cause #1 (duplication)**: seed_demo data is being inserted on every container restart without `ON CONFLICT DO NOTHING`, OR the Kafka `market.instrument.created` topic has duplicate messages and `_try_insert_alias` doesn't have an alias-level idempotency guard for the (entity_id, alias_text) combination, OR the seed script runs on N ≥ 4 boots.
- **Root cause #2 (placeholder names)**: `instrument_consumer.py:128-135` accepts any `raw_name` and replaces null/empty/"None"/"null" with `f"Instrument-{instrument_id.hex[:8]}"`. The producer (market-ingestion) is sending null `name` for several instruments. These placeholder canonicals are useless for resolution.
- **Fix**: (a) add a unique constraint on (entity_id, normalized) for entity_aliases (likely already exists — verify); (b) at the producer, never emit `market.instrument.created` for an instrument lacking a real name — defer until fundamentals enrichment provides one.

### 6.3 New MAJOR finding — alias enrichment dead

#### F-MAJOR-09 · LLM alias generation never produces output
- **Symptom**: 0 rows in `entity_aliases` with `alias_type='LLM'`. The `_add_llm_aliases` method (`instrument_consumer.py:223-261`) is wired and called for every instrument, but produces nothing.
- **Root causes (compounding)**:
  1. **Prompt has no `{description}` placeholder** (`libs/prompts/.../alias.py:11-25`). The call site (`instrument_consumer.py:237`) renders with only `name=` and `ticker=`, then passes `description[:500]` as `context=` to the `ExtractionInput` — but the prompt template never references context, so the LLM gets a boilerplate ask with no concrete material to draw from. With Llama-3.1-8B and a vague "well-established" criterion, the model returns `{"aliases": []}` to be safe.
  2. **No `llm_usage_log` rows** (compound with F-CRIT-03) means there's no telemetry to confirm the call even fires successfully — possible silent timeout / fallback exhaustion.
  3. **5-alias cap** (`instrument_consumer.py:247`) is fine in principle but combined with the prompt issue means the 5-element ceiling is irrelevant.
- **Fix sequence**:
  - Add `{description}` placeholder to ALIAS_GENERATION template
  - Pass it from the call site
  - Move `description[:500]` from `context=` to the prompt body
  - Increase cap to 8 once quality is verified
- **Skill**: `/fix-bug` (template + caller, ~1h)

### 6.4 New MAJOR finding — provisional pipeline silent

#### F-MAJOR-10 · `provisional_entity_queue` empty despite many unresolved mentions
- **Symptom**: 0 rows in `intelligence_db.provisional_entity_queue`. The 4-stage resolution cascade is supposed to write to this queue when score ≥0.45 but <0.72 (PROVISIONAL band).
- **Hypothesis**: with most non-instrument classes at 0% AUTO_RESOLVE, the cascade should be producing tons of UNRESOLVED *or* PROVISIONAL outputs. The fact that BOTH are silent (no `mention_resolutions` either — F-CRIT-02) suggests the audit and provisional-queue writes share a common omission point (probably the same `nlp_session.commit()` block that's missing the `mr_repo.add_batch` call also doesn't persist the provisional inserts).
- **Fix**: investigate shared write path; likely a one-line fix per missing repository call.
- **Skill**: `/investigate` (1-2h to confirm), then `/fix-bug`

### 6.5 Revised yield arithmetic

Putting the new findings into a single number:

```
articles processed                         = 2,839
articles where ALL entities unresolved     = 1,833 (66%)
                          → drop everything
articles where some entities resolved      = 1,006
LLM produces relations on ~14-20% of these = ~150-200 articles produce relations
relations actually surviving _build_raw_*   = ?? but DB shows 0 net new relations
                          → indicates near-100% drop even for resolved-some docs
```

The math says: if articles have ~3-4 mentions and only ~10% resolve, then `P(both endpoints of a relation are resolved) ≈ 0.10² × ~6 (relation count factor) ≈ 0.06`. Empirically observed near-zero, so the model is also picking unresolved entities ~80% of the time even when resolved alternatives exist (the prompt encourages this by listing all surfaces).

### 6.6 Revised priority sequence (replaces §4 Sprint 1)

The optimal Sprint-1 order, given the new evidence:

| Order | Item | Why first |
|---:|---|---|
| 1 | **F-CRIT-07** — fix `entity_id_by_ref` to include unresolved mentions with provisional flag | Single largest yield unlock; turns 80%+ silent drops into provisional-queued data |
| 2 | **F-CRIT-10** — seed canonical entities for the 7 missing classes | Unblocks resolution for currencies, regulators, gov bodies, indices, commodities, macroeconomic indicators |
| 3 | **F-CRIT-04** + **F-CRIT-11** + **F-MAJOR-09** — fix alias generation: insert EODHD name + add description-aware LLM prompt + extend EODHD identifiers (CUSIP, FIGI, LEI, SEDOL) | Brings alias ratio from 0.46:1 to 3-5:1, raising `financial_instrument` resolution rate from 17% toward 60-80% |
| 4 | **F-CRIT-12** — make seed idempotent + reject null-name instruments | Cleans up the canonical store |
| 5 | **F-CRIT-02** — write `mention_resolutions` audit | Makes resolution observable so the above can be verified |
| 6 | **F-CRIT-03** — wire `usage_logger` | Makes LLM cost observable |
| 7 | **F-CRIT-08** — remove dead `claim.extracted` write | Hygiene |
| 8 | **F-CRIT-06** — add `final_routing_tier` / `processing_path` columns | Persists novelty downgrades |
| 9 | **F-CRIT-05** — fix UnresolvedResolutionWorker prompt | Now that provisional queue can fill (F-MAJOR-10), this matters |
| 10 | **F-MAJOR-02 / -04 / -05 / -06 / -10** — auth, descriptions, embedding-pending, provisioning, provisional-pipeline | Quality + volume |

### 6.7 New BUG_PATTERNS to record

| Pattern | Lesson |
|---|---|
| **BP-prompt-input-mismatch** | When a prompt instructs the LLM to use values from a list, the call-site lookup table that resolves those values must contain *every entry the prompt advertised*. Otherwise the LLM's correct outputs become silent drops. |
| **BP-orphan-outbox-topic** | When a topic appears in a service's outbox but no consumer group subscribes, Kafka still happily accepts producer writes — there's no built-in alarm. Periodic check: `for each consumer-group-less topic, alert`. |
| **BP-seed-data-non-idempotent** | Seed scripts that run on container start without `ON CONFLICT DO NOTHING` will multiply data on every restart. Always idempotent. |
| **BP-class-without-canonicals** | If GLiNER configures an entity class but the canonical_entities table has zero seeds for that class, NER produces unresolvable mentions forever. Resolution coverage check should be a startup health-check. |
| **BP-prompt-vs-context-decoupling** | Passing `description` as `context=` to an LLM client is meaningless if the *prompt template* has no placeholder for it. The model will not infer that it should consult context outside its instructions. Always thread context through the rendered prompt. |

### 6.8 Compounding updates applied

- Added two new memory entries: `project_pipeline_quality_2026_04_30.md` (revised state) and `feedback_prompt_input_mismatch.md` (the silent-drop pattern)
- Recommended `docs/BUG_PATTERNS.md` additions (5 new patterns above)
- Recommended `.claude/review/checklists/REVIEW_CHECKLIST.md` add: "If a function looks up values produced by an LLM against a dict, verify the dict was populated from the *same source* the prompt told the LLM to draw from."

### 6.9 Open questions (revised)

- The 2026-04-30 view changes the priority of seed-data work — should the user authorise a small Alembic data-migration with the bootstrap canonicals (currencies, regulators, indices, commodities, macros) as an immediate ship rather than waiting for a PRD?
- The `claim.extracted` topic — was an independent claims pipeline ever PRD'd, or is this dead code? (No PRD reference found in `docs/specs/` — leaning toward dead code.)
- Should we set `processed_at` columns and unique constraints across audit tables to detect future audit-write omissions automatically?

---

**2026-04-30 verdict revision**: yesterday's "12 fixes ≈ 1 sprint" estimate is still right *in count*, but the **highest-impact fix is now F-CRIT-07 (one function), not F-MAJOR-01 (full-article body, multi-day)**. F-CRIT-07 + F-CRIT-10 (canonical seeds) together would likely lift relation production from 0/day to several hundred/day with no other changes. The big-effort F-MAJOR-01 stays valuable for *quality* (richer extraction context) but is no longer the bottleneck for *volume*.
