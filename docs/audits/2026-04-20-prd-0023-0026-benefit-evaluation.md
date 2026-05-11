# PRD Benefit Evaluation: PRD-0023 vs PRD-0026

**Date**: 2026-04-20
**Author**: Investigation skill (PRD impact subagent)
**Scope**: PRD-0023 (Knowledge Graph Analytics & NLP Cache) and PRD-0026 (News Intelligence APIs)
**Decision needed**: Sequencing — which PRD to implement first

---

## 1. Executive Summary

Both PRDs are production-ready with all prerequisites met. They are architecturally independent and deliver complementary value:

- **PRD-0023** adds structural intelligence to the knowledge graph (community detection, hub scoring, graph evolution alerting) plus an NLP cache and SSRF hardening.
- **PRD-0026** closes the ranked-news delivery gap: multi-window price impact, LLM relevance scoring, and two ranked article endpoints that directly improve analyst workflows.

**Recommendation: PRD-0026 first.** It delivers visible, immediate user impact in Week 4. PRD-0023 follows in Weeks 5–8 with no architectural conflicts. Both are feasible within 8 weeks total.

---

## 2. Baseline: What Exists Today

### 2.1 Article Ranking Baseline

| Capability | Current State |
|-----------|--------------|
| Price impact windows | Single `day_t0` only in `article_price_impacts` table (PLAN-0020) |
| LLM relevance score | None — articles processed by extraction LLM but no user-facing score |
| Ranked news endpoints | `GET /api/v1/entities/{id}/articles` exists but returns unsorted |
| Global ranked feed | No `GET /api/v1/news/top` endpoint |
| Display ranking formula | No composite signal formula |

### 2.2 Knowledge Graph Analytics Baseline

| Capability | Current State |
|-----------|--------------|
| Community detection | None — entities exist but no cluster awareness |
| Hub scoring | None — no structural importance metric |
| Graph evolution alerts | None — S10 consumes signals but not graph structural changes |
| NER content cache | None — GLiNER re-runs on every re-delivered article |
| SSRF redirect validation | Partial — initial URL validated; intermediate redirect targets unvalidated |

---

## 3. PRD-0023: Knowledge Graph Analytics & NLP Cache Layer

### 3.1 What Changes vs Current Baseline

| Feature | Change |
|---------|--------|
| **Community detection worker** | New `CommunityDetectionWorker` (APScheduler, 30 min); runs Leiden algorithm on `canonical_entities` + `relations` graph; writes to `entity_communities` table |
| **Hub scoring** | `GET /api/v1/entities/hubs` endpoint returning top-N structurally important entities (degree × confidence × recency decay) |
| **Graph evolution worker** | New `GraphEvolutionWorker`; detects new entities + cross-community edges since last watermark; emits `graph.evolution.v1` via outbox |
| **S7 similarity endpoint extension** | `POST /api/v1/entities/similar` gains `surprise_score` (community distance × ANN distance); surfaces cross-domain connections |
| **S10 consumer** | `GraphEvolutionConsumer` subscribes to `graph.evolution.v1`; creates flash alerts for watched entities |
| **S6 NER cache** | Valkey content-addressed cache (SHA256 of article text, 24h TTL); skips GLiNER call on cache hit |
| **S4 SSRF redirect hardening** | `SSRFSafeTransport` validates every redirect hop (max 5); prevents DNS rebinding on intermediate hops |
| **New Kafka topic** | `graph.evolution.v1` (7-day retention) |
| **New DB tables** | `entity_communities` (~50K rows), `graph_evolution_watermarks` (1 row) |

### 3.2 User-Facing Benefits

| User | Benefit |
|------|---------|
| **Research Analysts** | Community endpoints enable "show me all entities in this sector cluster"; hub entities (Federal Reserve, S&P 500) surface as natural starting points |
| **Quant Traders** | `surprise_score` on the similarity endpoint reveals cross-domain connections invisible to pure vector distance — useful for basis trade signals |
| **All users** | Graph evolution alerts: "Apple just gained a structural connection to Rivian" → signals potential strategic move before traditional news cycle |
| **Security posture** | SSRF redirect hardening closes a TOCTOU vulnerability in content ingestion |

### 3.3 Technical Benefits

| Benefit | Detail |
|---------|--------|
| **Query latency** | `GET /api/v1/entities/hubs` < 100ms p95; `GET /api/v1/entities/{id}/community` < 50ms p95 |
| **NER cache hit rate** | Estimated 15–25% on re-delivered articles; saves ~2s GPU time per hit |
| **Graph evolution freshness** | < 35 min from entity creation to alert via S10 |
| **Security** | SSRF: redirect-chain validation closes CVE-class vulnerability |
| **Thesis demonstration** | Shows graph-structural intelligence beyond vector search |

### 3.4 Operational Impact

| Resource | Cost |
|----------|------|
| Container image delta | +15 MB (`leidenalg` ~5MB, `python-igraph` ~10MB) |
| Leiden CPU | ~60s wall-clock per 30-min cycle for 500K-node graph; negligible |
| Valkey NER cache | ~10 MB (80K articles × ~100 bytes/span); no growth beyond TTL |
| DB storage | `entity_communities` ~50K rows; `graph_evolution_watermarks` 1 row |
| New external APIs | None |

### 3.5 Risk Analysis

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Leiden non-determinism across runs | MEDIUM | Community IDs stable via UUIDv5(anchor_entity_id); soft-delete stale memberships; no data corruption |
| Community detection OOM (>500K nodes) | MEDIUM | Circuit breaker: skip run if entity count > configured limit |
| Graph evolution watermark desync | LOW | Singleton row updated atomically in same DB transaction as outbox events |
| NER cache stale state | LOW | 24h TTL; idempotent: cache hit reconstructs `EntityMention` objects with fresh UUIDs |
| SSRF redirect depth explosion | VERY LOW | httpx hard limit: 5 hops |
| leidenalg coupling | LOW | Lazy imports; no runtime penalty if worker disabled |

### 3.6 Dependencies and Prerequisites

| Prerequisite | Status |
|-------------|--------|
| PLAN-0018 (intelligence-migrations) | ✅ Complete |
| PRD-0021 (S10 flash alert fan-out) | ✅ Complete |
| PRD-0025 (Auth / InternalJWT) | ✅ Complete |
| Leiden algorithm available | ✅ pip install leidenalg python-igraph |
| No dependency on PRD-0026 | ✅ Fully independent |

### 3.7 Suggested Rollout Strategy (Phased)

**Phase 1 (Weeks 5–6)**: Community detection worker + `entity_communities` table + `GET /api/v1/entities/hubs` and `GET /api/v1/entities/{id}/community` endpoints. Validate community stability over 3 detection cycles.

**Phase 2 (Week 6)**: Graph evolution worker + `graph_evolution_watermarks` table + `graph.evolution.v1` topic + S10 `GraphEvolutionConsumer`. Gate behind `KNOWLEDGE_GRAPH_EVOLUTION_ENABLED` feature flag.

**Phase 3 (Week 7)**: S7 similarity endpoint extended with `surprise_score`. S6 NER cache.

**Phase 4 (Week 8)**: S4 SSRF redirect validation hardening. End-to-end test: create entity → observe evolution alert in S10 < 35 min.

### 3.8 KPIs to Validate Success

| KPI | Baseline | Target | Measurement |
|-----|----------|--------|-------------|
| Community detection cycle time | — | < 60s wall-clock per run | `s7_community_detection_duration_seconds` histogram |
| Community ID stability | — | Same ID for same anchor entity across 5 runs | Unit test + integration check |
| Evolution alert freshness | — | < 35 min from entity creation to S10 alert | Manual test + log timestamps |
| NER cache hit rate | 0% | 15–25% | Counter ratio `nlp_ner_cache_hits / (hits + misses)` |
| Hub endpoint latency | — | < 100ms p95 | `s7_hub_endpoint_query_duration_seconds` |
| Surprise score adoption | — | Qualitative: analyst reports finding novel cross-domain connections | User interview post-launch |

### 3.9 Recommendation

**Priority**: MEDIUM-HIGH | **Confidence**: HIGH | **Rationale**: Architecturally sound, low risk, meaningful thesis differentiation. Deferred to Week 5–8 because PRD-0026 has higher immediate user impact.

---

## 4. PRD-0026: News Intelligence APIs

### 4.1 What Changes vs Current Baseline

| Feature | Change |
|---------|--------|
| **Multi-window price impact** | `PriceImpactLabellingWorker` extended to compute day_t0, day_t1, day_t2, day_t5 windows; new `article_impact_windows` table replaces `article_price_impacts` |
| **LLM relevance scoring** | New `ArticleRelevanceScoringWorker` (30-min cycle); Qwen2.5:3b title-only scoring; writes `llm_relevance_score` + `llm_scored_at` to `document_source_metadata` |
| **Display relevance formula** | `display_relevance_score = 0.5 × market_impact + 0.4 × llm_relevance + 0.1 × routing_score`; computed at query time via SQL JOIN |
| **Global ranked news endpoint** | `GET /api/v1/news/top` (S6); returns globally ranked articles by display_relevance_score; date-range + limit params |
| **Enhanced entity articles endpoint** | `GET /api/v1/entities/{id}/articles` updated with date range, sort, pagination, and display_relevance_score in response |
| **S9 proxy routes** | 2 new routes: `/v1/news/top` (proxy to S6), `/v1/entities/{id}/articles` (path rewrite to S6) |
| **Signal producer update** | `nlp.signal.detected.v1` producer reads `market_impact_score` from new `article_impact_windows.window_type='day_t0'` |
| **Frontend types** | `RankedArticle`, `RankedNewsResponse` types; 2 new gateway client methods |
| **New DB table** | `article_impact_windows` (UNIQUE: article_id, entity_id, window_type); ~3M rows at steady state |
| **Modified table** | `document_source_metadata` gains `llm_relevance_score` (FLOAT), `llm_scored_at` (TIMESTAMPTZ) |
| **Dropped table** | `article_price_impacts` (replaced by `article_impact_windows`) |

### 4.2 User-Facing Benefits

| User | Benefit |
|------|---------|
| **Research Analysts** | "Top News" global feed with `display_relevance_score`: immediately surfaces market-moving articles; reduces manual triage time |
| **Retail Investors** | Company detail page shows ranked news (CEO resignation > routine filing); sentiment + impact score visible at a glance |
| **Quant Traders** | `display_relevance_score` + all 4 price-impact windows available as feature inputs for signal models |
| **ML Engineers** | `article_impact_windows` multi-window structure = ready-made training dataset for price-impact prediction (structured feature matrix) |
| **Thesis evaluators** | End-to-end intelligence pipeline: ingestion → 3-signal scoring → ranked display demonstrated in < 200ms |

### 4.3 Technical Benefits

| Benefit | Detail |
|---------|--------|
| **Query latency** | `GET /api/v1/news/top` < 200ms p95 with new indexes; `GET /api/v1/entities/{id}/articles` < 150ms p95 |
| **Signal completeness** | 4-window retrospective ground truth for articles ≥7 days old; enables time-series feature engineering |
| **Ranking stability** | 50% weight on market confirmation prevents rank churn on LLM-only scores; stability improves as OHLCV data arrives |
| **LLM throughput** | Qwen2.5:3b: ~0.5–1s/call; 50 articles × 48 cycles/day = 2,400 articles/day; sustainable |
| **ML-readiness** | Structured `(article_id, entity_id, window_type, price_open, price_close, impact_score)` is a training dataset |
| **Backward compatibility** | Existing `nlp.signal.detected.v1` consumers unaffected; `market_impact_score` still populated |

### 4.4 Operational Impact

| Resource | Cost |
|----------|------|
| Ollama inference (Qwen2.5:3b) | ~0.83 calls/min at steady state; minimal CPU; no GPU required |
| DB storage | `article_impact_windows` ~3M rows at steady state (500K articles × 4 windows × 1.5 entities avg); ~2GB with indexes |
| OHLCV polling | ~9,600 calls/day to S3 `/api/v1/ohlcv`; negligible |
| Valkey | No new caching requirements |
| Container image delta | None (Ollama + Qwen2.5:3b already present in docker-compose) |

### 4.5 Risk Analysis

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Score discontinuity on OHLCV data arrival | MEDIUM (UX) | Articles < 48h old show LLM-estimated scores; older articles show market-confirmed scores. Document for users: rank changes = accuracy improving, not a bug |
| Qwen2.5:3b relevance quality | MEDIUM | Benchmark on 50 known articles before prod deploy. Target precision@5 ≥ 70%. Fallback to routing_score if insufficient |
| OHLCV labelling startup backlog | LOW | 500K articles × 4 windows = 2M API calls over ~56h at cold start; graceful, no user impact |
| Ollama unavailability during scoring | LOW | Worker skips articles; retries next 30-min cycle; articles remain unscored but queryable |
| Missing OHLCV for symbol/date | LOW | Worker skips that window; article has fewer than 4 rows; no data loss |
| Migration data loss | LOW | Filter `price_open > 0` when migrating from `article_price_impacts`; no corruption possible |
| Display formula weight miscalibration | LOW | All 3 weights configurable via env vars; post-deployment tuning without code change |
| `nlp.signal.detected.v1` producer update | LOW | `day_t0` window extraction is backward-compatible; field semantics unchanged |

### 4.6 Dependencies and Prerequisites

| Prerequisite | Status |
|-------------|--------|
| PLAN-0020 (PriceImpactLabellingWorker, article_price_impacts) | ✅ Complete |
| PLAN-0021 (S10 AlertSeverity enum) | ✅ Complete |
| PRD-0025 (Auth / InternalJWT at S9) | ✅ Complete |
| Qwen2.5:3b in Ollama | ✅ Available in docker-compose |
| No dependency on PRD-0023 | ✅ Fully independent |

### 4.7 Suggested Rollout Strategy (Phased)

**Phase 1 (Week 1–2)**: Alembic migration — create `article_impact_windows`, add columns to `document_source_metadata`, drop `article_price_impacts`. Run forward/backward compat tests.

**Phase 2 (Week 2–3)**: Enhanced `PriceImpactLabellingWorker` (multi-window); `ArticleRelevanceScoringWorker`; `GetTopNewsUseCase` with display_relevance formula. Deploy workers with `PRICE_IMPACT_DRY_RUN=true` first — validate OHLCV fetch quality on 100 sample articles.

**Phase 3 (Week 3)**: Enhanced `GetEntityArticlesUseCase` (pagination, sort, scoring formula). S9 proxy routes.

**Phase 4 (Week 3–4)**: Frontend types + API client methods. `ArticleCard` updated to show `display_relevance_score`. End-to-end test: article published → ranked in `/v1/news/top` within 35 min.

### 4.8 KPIs to Validate Success

| KPI | Baseline | Target | Measurement |
|-----|----------|--------|-------------|
| Top news query latency | — | < 200ms p95 | `s6_top_news_query_duration_seconds` |
| LLM relevance score distribution | — | Mean 0.45–0.65, not bimodal | `s6_llm_relevance_score_histogram` |
| LLM precision@5 | — | ≥ 70% vs domain expert labels | Benchmark on 50 known articles |
| day_t5 window coverage | 0% | ≥ 95% for articles ≥ 7 days old | `COUNT(*) WHERE window_type='day_t5'` / total |
| LLM scoring throughput | 0 | 2,400 articles/day backlog cleared in 7 days | Counter `s6_llm_relevance_scored_total` |
| Analyst session engagement | — | Top News section in > 50% of analyst sessions | Frontend analytics |
| Rank stability | — | < 5% rank change after 48h for articles ≥ 48h old | A/B snapshot comparison |

### 4.9 Recommendation

**Priority**: HIGH | **Confidence**: HIGH | **Rationale**: Directly addresses the most visible missing UX feature (ranked news); prerequisites already complete; low implementation risk; enables PRD-0023 to build on a richer signal foundation.

---

## 5. Comparative Analysis

### 5.1 Impact Scoring Matrix

| Dimension | PRD-0023 | PRD-0026 | Winner |
|-----------|----------|----------|--------|
| Immediate analyst benefit | MODERATE | **HIGH** | PRD-0026 |
| Retail investor benefit | LOW | **HIGH** | PRD-0026 |
| Quant trader benefit | MODERATE | **HIGH** | PRD-0026 |
| Thesis evaluation impact | **HIGH** | HIGH | Tie |
| Architectural completeness | Adds graph structural dimension | Completes signal→display pipeline | Tie |
| Query performance improvement | MODERATE | **HIGH** | PRD-0026 |
| ML enablement (training data) | MODERATE (graph metadata) | **HIGH** (structured windows table) | PRD-0026 |
| Implementation effort (waves) | 8 waves | 7 waves | PRD-0026 |
| External API coupling | LOW (C++ library only) | MODERATE (OHLCV + Ollama) | PRD-0023 |
| Data migration complexity | LOW (new tables only) | MODERATE (table replacement) | PRD-0023 |
| Risk profile | LOW–MEDIUM | LOW–MEDIUM | Tie |
| Rollback difficulty | MEDIUM | LOW | PRD-0023 |
| Cascading failure potential | LOW | LOW | Tie |

### 5.2 Dependency Graph

```
PLAN-0018 (intelligence-migrations) ──→ PRD-0023 (KG Analytics)
                                     ↗ also required by PRD-0026 (intelligence_db schema)

PLAN-0020 (PriceImpact) ─────────────→ PRD-0026 (News Intelligence)
PLAN-0021 (AlertSeverity) ───────────↗

PRD-0023 ─────────────────────────────→ PRD-0026 OPTIONAL benefit
(graph.evolution.v1 → S10 alerts can    (score_source_distribution
 inform display_relevance weighting)     improved if graph evolution
                                         understood)
```

**Critical observation**: Neither PRD blocks the other. Both can be implemented independently. The only soft coupling is: PRD-0023's `graph.evolution.v1` topic + S10 consumer becomes more useful if PRD-0026's analyst news workflow is already live (more analysts to receive alerts).

### 5.3 Side-by-Side Technical Footprint

| | PRD-0023 | PRD-0026 |
|-|----------|----------|
| New services touched | S7 (large), S6 (small), S4 (very small), S10 (medium), intelligence-migrations | S6 (large), S9 (small), frontend (small) |
| New Kafka topics | `graph.evolution.v1` | None |
| New consumers | `GraphEvolutionConsumer` (S10) | None |
| New DB tables | `entity_communities`, `graph_evolution_watermarks` | `article_impact_windows` |
| Modified tables | None | `document_source_metadata` (+2 cols) |
| Dropped tables | None | `article_price_impacts` |
| New endpoints (S6/S7) | 3 (hubs, community, similar extension) | 2 (top news, entity articles enhanced) |
| New S9 proxy routes | 1 (evolution alerts) | 2 (top news, entity articles) |
| New Python deps | `leidenalg`, `python-igraph` (+15 MB) | None |
| Alembic migrations | 1 (intelligence-migrations) | 1 (S6) |

---

## 6. Sequencing Recommendation

### Final Sequence: PRD-0026 (Weeks 1–4) → PRD-0023 (Weeks 5–8)

#### Rationale

1. **Faster user value**: PRD-0026 ships ranked news feed in Week 4 — visible to every analyst on the platform. PRD-0023's community browsing requires a UI investment (pencil.dev canvas design not yet done).

2. **Simpler prerequisites**: PRD-0026 has no new Kafka topics, no new consumer coordination. PRD-0023 adds `graph.evolution.v1` + a new S10 consumer which must handle backpressure correctly.

3. **Lower migration risk**: PRD-0026's table replacement (`article_price_impacts` → `article_impact_windows`) is the only destructive migration, and it's reversible. PRD-0023 is append-only.

4. **Better feedback loop**: Shipping PRD-0026 first gives analysts a ranked news feed. Their engagement patterns (which articles they click on, which queries they ask) inform the calibration of PRD-0023's `surprise_score` formula in weeks 5–8.

5. **PRD-0026 enables PRD-0023 signal enrichment**: If the `display_relevance_score` in PRD-0026 can later incorporate graph community distance (a PRD-0023 output), this is a natural enhancement path — not a blocker.

#### Week-by-Week Plan

| Weeks | PRD | Deliverable |
|-------|-----|-------------|
| 1–2 | PRD-0026 | Alembic migration + multi-window PriceImpactLabellingWorker |
| 2–3 | PRD-0026 | ArticleRelevanceScoringWorker + GetTopNewsUseCase |
| 3 | PRD-0026 | Enhanced GetEntityArticlesUseCase + S9 proxy routes |
| 3–4 | PRD-0026 | Frontend types + integration tests + monitoring |
| 4 | PRD-0026 | ✅ PRD-0026 complete; begin KPI collection |
| 5–6 | PRD-0023 | Community detection worker + entity_communities table + hubs/community endpoints |
| 6–7 | PRD-0023 | Graph evolution worker + graph.evolution.v1 topic + S10 consumer |
| 7 | PRD-0023 | S7 similarity extension (surprise_score) + S6 NER cache |
| 8 | PRD-0023 | S4 SSRF redirect hardening + end-to-end tests + monitoring |
| 8 | PRD-0023 | ✅ PRD-0023 complete |

#### Critical Success Factors

1. **PRD-0026 Wave 1**: Forward/backward Alembic compat tests must pass before merge. Verify `article_price_impacts` data migration with `price_open > 0` filter.
2. **PRD-0026 Wave 2–3**: Qwen2.5:3b benchmark on 50 known articles before prod deploy. If precision@5 < 70%, fall back to routing_score-only.
3. **PRD-0023 Wave 2**: Community ID stability test — run detection 5 times; same anchor entity must yield same UUIDv5.
4. **PRD-0023 Wave 3**: Graph evolution watermark singleton — atomic UPDATE in same transaction as outbox INSERT; add integration test for crash-recovery scenario.

---

## 7. Open Questions

### PRD-0023 Open Questions

| ID | Question | Classification | Recommended Action |
|----|----------|----------------|--------------------|
| OQ-023-1 | Leiden resolution parameter = 1.0 — produces sensible communities for financial networks? | AMBIGUOUS | Validate on sample graph post-first-deployment; adjust if community count is too high or too low |
| OQ-023-2 | Should community anchor change trigger `entity.dirtied.v1`? | DEFERRED | OK to skip for v1; entity narrative still embeds old community |
| OQ-023-3 | Does SSRF redirect validation handle compressed responses (Content-Encoding: gzip)? | AMBIGUOUS | Write unit test with gzip mock response |
| OQ-023-4 | What does `GET /api/v1/entities/{id}/community` latency look like for an entity in 50+ communities? | UNKNOWN | Test with synthetic data: entity with `max_memberships=50` |
| OQ-023-5 | UI design for community browsing not started | DEFERRED | Requires `/design-ui` before `/implement-ui` |

### PRD-0026 Open Questions

| ID | Question | Classification | Recommended Action |
|----|----------|----------------|--------------------|
| OQ-026-1 | Qwen2.5:3b accuracy on financial news titles | UNKNOWN | Benchmark required pre-deploy (see Phase 2 rollout) |
| OQ-026-2 | Display formula weight ratio (0.5/0.4/0.1) empirically optimal? | DEFERRED | Starting values reasonable; tune post-deployment via env vars |
| OQ-026-3 | User perception of score discontinuity as data arrives | DOCUMENTED RISK | Add tooltip in UI: "Score may improve as market data arrives (< 48h)" |
| OQ-026-4 | OHLCV data gaps for penny stocks / delisted securities | UNKNOWN | Worker gracefully skips; article has fewer than 4 windows; no data loss |
| OQ-026-5 | `GET /api/v1/news/top` — is global feed tenant-aware or global? | AMBIGUOUS | Routing score is global; watchlist signal is tenant-aware. Document behavior: global feed + personal relevance boosted by watchlist |

---

## 8. Risk Matrix Summary

| Risk | PRD | Severity | Owner | Mitigation |
|------|-----|----------|-------|-----------|
| LLM weight miscalibration | 0026 | MEDIUM | S6 | Configurable env vars; post-deployment tuning |
| LLM model quality (Qwen2.5:3b) | 0026 | MEDIUM | S6 | Benchmark pre-deploy; fallback to routing_score |
| DB migration downtime | 0026 | MEDIUM | S6 DBA | Zero-downtime ALTERs for new columns; old table drop deferred by 1 week |
| Leiden OOM (>500K entities) | 0023 | MEDIUM | S7 | Circuit breaker: skip run if entity count exceeds threshold |
| Graph evolution watermark desync | 0023 | MEDIUM | S7 | Atomic singleton update in same transaction as outbox |
| NER cache stale state | 0023 | LOW | S6 | 24h TTL; idempotent EntityMention reconstruction |
| SSRF redirect attack surface | 0023 | VERY LOW | S4 | Hard 5-hop limit; IP validation at each hop |
| Cascading OHLCV failures during backfill | 0026 | LOW | S6 | Graceful skip; retry next 4h cycle |
| Kafka 7-day retention loss | Both | HIGH | Infra | Extend topic retention to 30 days (independent of PRDs) |
