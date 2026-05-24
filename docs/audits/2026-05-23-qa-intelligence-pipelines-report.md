# QA Report — Intelligence Pipelines (KG-RAG + Infrastructure)

**Date**: 2026-05-23 22:30 UTC
**Skill**: `qa`
**Scope**: KG-RAG knowledge layer (full) + Postgres/container deep audit
**Branch**: `feat/plan-0089-w2`
**Verdict**: **FAIL** — multiple BLOCKING data-corruption issues + agent unsafe for investor use

---

## Executive Summary

Seven specialist agents audited every layer of the intelligence stack — NLP pipeline (S6), Knowledge Graph extraction & refresh (S7), RAG chat (S8) code + live, plus a postgres anomaly hunt and container-log sweep. The audit surfaced **66 distinct findings**, of which **4 are BLOCKING**, **9 CRITICAL**, **24 MAJOR**. Multiple findings converge from independent angles, raising confidence to HIGH on the root causes.

The headline result: **the agent fabricated a $34.6B AMD revenue figure** (actual: $10.253B) when fundamentals_history returned only 1 row — wrapping the invention in plausible analyst prose about "potential volatility or a one-time event." Across 8 realistic investor questions, **only 1 produced a useful answer**; 3 returned hard 503 refusals on single-tool failure, and 3 hallucinated narratives. The infrastructure is real — graph traversal, screener, entity resolution all work — but the LLM synthesis layer is currently a liability multiplier, not a value-add.

Underneath the agent, the data layer is significantly degraded: **70% of relations are missing from AGE** (5,553 of 7,884); **100% of temporal events have NEVER synced to AGE** (0 of 14,762); **60% of relations have NULL confidence**; **100% (12,689) of path_insights lack the LLM explanation** that the flagship Intelligence-tab feature requires; **100% (2,197) of fundamentals_ohlcv embeddings are empty**; **34% of entities have no description**. Three of eight routing signals (watchlist, novelty, price_impact) are silently dead. The RAG agent's intent classifier is hard-coded to GENERAL (all per-intent prompts are dead code); its tool-use system prompt explicitly invites hallucination from training data; 4 of its KG tools silently return `[]` without entity context.

Infrastructure was unhealthy at the start of the audit (postgres/kafka/valkey/ollama/schema-registry/market-data all exited at 21:40:21 UTC due to a host event); 21 Kafka consumers were silently DNS-frozen on the old broker IP after Kafka restarted. **All of this was restored during the QA pass** — but the underlying fragility (no `restart: unless-stopped` on 3 deps, no `depends_on: { service_healthy }` on retry workers, no rdkafka `broker.address.ttl` override, no `APP_ENV` enforcement, no startup-DB retry) remains.

**The platform is not ready for paying investor use.** The data corruption blocks the value proposition (path_insights, contradictions, summaries are empty or meaningless); the agent's confident hallucinations would get a real analyst fired. Remediation requires a focused 2-week sprint on the eight BLOCKING/CRITICAL items below.

---

## Multi-Agent Review Summary

| Agent | Scope | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|-------|----------|----------|----------|-------|-------|-----|
| A1 NLP Pipeline (S6) | Blocks 1-7 + routing | 13 | 1 | 1 | 5 | 5 | 1 |
| A2 KG Extraction (S7) | Blocks 13A-13E | 8 | 0 | 0 | 1 | 3 | 4 |
| A3 Refresh/Embedding | AGE sync + workers | 10 | 1 | 2 | 5 | 1 | 1 |
| A4 RAG-chat Code | Intent/tools/prompts | 12 | 0 | 2 | 6 | 3 | 1 |
| A5 RAG-chat Live | 8 investor questions | 6 | 0 | 1 | 4 | 1 | 0 |
| B1 Postgres Health | Anomaly hunt | 12 | 2 | 3 | 5 | 1 | 1 |
| B2 Container Logs | All containers | 5 | 1 | 3 | 1 | 0 | 0 |
| **Total** | — | **66** | **5** | **12** | **27** | **14** | **8** |

### Cross-Agent Signals (HIGH Confidence — flagged by 2+ agents independently)

| Convergence | Severity | Agents |
|---|---|---|
| **Infrastructure outage** (postgres/kafka/valkey/ollama/schema-registry/market-data exited 21:40:21) | BLOCKING | A1, A2, A3, B2 |
| **`fundamentals_ohlcv` embeddings 100% NULL (2,197 rows)** | CRITICAL | A1 (F-NPL-007), A3 (F-REF-003), B1 (F-DB-005) |
| **Restart loops on path-insight + embedding-retry workers** | CRITICAL | A1 (F-NPL-002), A3 (F-REF-006), B2 (F-LOG-002) |
| **`document_source_metadata.impact_score` 100% NULL** | CRITICAL | A1 (F-NPL-008), B1 (F-DB-004) |
| **34% of entities missing description (BP-541 regression)** | CRITICAL | A3 (F-REF-004), B1 (F-DB-005) |
| **AGE undercount (70% relations + 100% events missing)** | BLOCKING | A2 (F-KG-103), A3 (F-REF-001/002), B1 (F-DB-009) |

### Fixes Applied During This QA Pass

| Action | Status | Notes |
|---|---|---|
| Restart postgres + kafka + valkey | ✅ DONE | Auto-restart picked them up |
| Restart minio | ✅ DONE | `docker start worldview-minio-1` |
| Restart ollama + schema-registry + market-data | ✅ DONE | These had no `restart: unless-stopped` |
| Restart 21 Kafka clients to flush stale DNS | ✅ DONE | rdkafka was cached on old kafka IP |
| Restart core API service containers | ✅ DONE | api-gateway, knowledge-graph, rag-chat, etc. |

Pipeline ingestion is now flowing again — but every data-quality and code finding below remains.

---

## BLOCKING Issues (must fix before any production use)

### F-KG-PERSIST-001 — AGE graph is missing 70% of relations and 100% of temporal events
**Severity**: BLOCKING | **Confidence**: HIGH | **Flagged by**: A2, A3, B1

**Root cause analysis**

- **What**: Apache AGE (`worldview_graph`) has 2,331 edges versus 7,884 rows in `intelligence_db.relations` (70% missing). AGE has 0 `TemporalEvent` vertices and 0 `EVENT_EXPOSES` edges versus 14,762 rows in `intelligence_db.temporal_events` (100% missing).
- **Why**: Two compounding bugs in `age_sync_worker.py`:
  1. `_sync_temporal_events` (line 445-527) has **never** successfully written a single event. Most likely cause: the `TemporalEvent` vlabel and `EVENT_EXPOSES` elabel were never created via `SELECT create_vlabel(...)` / `SELECT create_elabel(...)`. The first MERGE raises `ProgrammingError` → the outer try-except swallows it → the watermark advances → next cycle finds nothing newer than watermark.
  2. The bootstrap relation pagination short-circuits on partial failures combined with `OFFSET` skew when `_derive_edge_label` returns None and the loop `continue`s. Watermark advances on partial success.
- **When**: Since the worker first ran. Persistent failure mode.
- **Where**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:218-265,373-527`
- **History**: Not BP-tagged. New finding.

**Impact**

- **PathDiscovery, path_insight, traverse_graph all operate on a fractional graph.**
- **All "events" features in the Intelligence tab are dead** — economic events, earnings exposures, macro impacts don't appear in any Cypher query.
- **F-KG-103 (QW-3)** compounds this: even the relations that ARE in AGE don't carry a `direction` field, so the frontend can't render edges correctly.

**Recommended fix**

1. Add a `_bootstrap_age_labels()` helper that runs `SELECT create_vlabel('worldview_graph','TemporalEvent')` and `create_elabel('worldview_graph','EVENT_EXPOSES')` idempotently (wrap with `IF NOT EXISTS` semantics).
2. `docker exec worldview-valkey-1 valkey-cli DEL s7:age:sync:watermark` to force a full resync — AGE MERGE is idempotent.
3. Split the outer try-except so `ProgrammingError` in one sub-sync doesn't skip the others.
4. Move watermark to per-phase (entities, relations, events) so a failure in one phase doesn't strand the others.
5. Add `age_sync_phase_stalled` warning if any phase has `synced=0` across N consecutive runs while DB has rows newer than the watermark.
6. Add `direction` field to graph_query.py response (QW-3 from F-KG-103).

**Verification**

```bash
docker exec worldview-postgres-1 psql -U postgres -d intelligence_db -c "
  LOAD 'age'; SET search_path = ag_catalog, public;
  SELECT count(*) FROM cypher('worldview_graph', \$\$ MATCH (n:TemporalEvent) RETURN n \$\$) AS (n agtype);
  SELECT count(*) FROM cypher('worldview_graph', \$\$ MATCH ()-[r]->() RETURN r \$\$) AS (r agtype);
"
# Expected: TemporalEvent = 14762, edges >= 7700
```

---

### F-KG-PERSIST-002 — 60% of relations have NULL confidence + orphan foreign keys
**Severity**: BLOCKING | **Confidence**: HIGH | **Flagged by**: B1

**Root cause analysis**

- **What**: 4,683 of 7,884 relations (59%) have NULL `confidence` AND `confidence_stale=true`. 4,740 relations have subject FK pointing to a non-existent canonical_entity. 4,816 have orphan object FK. 4 self-loops point to phantom UUID `11111111-0004-7000-8000-000000000001` (the macro sentinel).
- **Why**:
  1. `ConfidenceDecayWorker` is not running or running on a subset partition only — every NULL-confidence row also carries `confidence_stale=true`, meaning they were queued for compute but never received it.
  2. The relation writer does NOT enforce FK — there is no actual FK constraint on `relations.subject_entity_id` / `object_entity_id`. Rows point to UUIDs that were never inserted (or were deleted before promotion).
  3. The macro sentinel entity is referenced as a fallback when extraction cannot resolve both subject and object — but the sentinel row was never seeded in `canonical_entities`.
- **Where**: Multiple — relation writer, ConfidenceDecayWorker, seed migration
- **History**: BP-539 fixed AGE sync of NULL-confidence rows but never addressed the underlying NULL-write pattern.

**Impact**

Every screener score, path-insight ranking, narrative summary, and contradiction computation reads `confidence` and either treats NULL as 0 (suppressing real signal) or as the default base (inflating noise). The orphan FKs mean Cypher path queries traverse to dead entity IDs that resolve to nothing.

**Recommended fix**

1. Make `confidence` NOT NULL with default = `base_confidence` (migration with `UPDATE … WHERE confidence IS NULL SET confidence = base_confidence` first).
2. Re-run decay sweep over all `confidence_stale=true` rows.
3. Seed the macro sentinel entity row (`11111111-0004-7000-8000-000000000001`) in `canonical_entities`.
4. Add a `DEFERRABLE INITIALLY DEFERRED` FK constraint on `relations.subject_entity_id`/`object_entity_id` → `canonical_entities.entity_id` (catches future drift without blocking outbox).
5. Prometheus alert: `relations_null_confidence_total > 0` and `relations_orphan_fk_total > 0`.

---

### F-KG-PERSIST-003 — 100% of path_insights have NULL llm_explanation (flagship feature broken)
**Severity**: BLOCKING | **Confidence**: HIGH | **Flagged by**: B1

**Root cause analysis**

- **What**: 12,689 of 12,689 path_insights rows have `llm_explanation IS NULL`. `explanation_at` and `explanation_model` columns are entirely unpopulated. 258 distinct anchors covered, all blank.
- **Why**: Commit `99f1845a feat(knowledge-graph): path insight LLM explanations + hub-penalty re-scoring` shipped the worker but it is either not deployed, has a silent failure, or is gated behind a flag that's off. Path-insight worker was crash-looping prior to this QA pass — even after restoration, no successful explanation writes are visible in the data.
- **Where**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_worker_main.py`
- **History**: Recent commit, never reached production data.

**Impact**

The flagship Intelligence-tab feature ("why are these entities connected?") shows the raw composite score with no narrative. Investors see a number, not an explanation — defeating the entire user value of paths.

**Recommended fix**

1. Verify worker is scheduled in `infra/compose/docker-compose.yml` and the scheduler is enabling it.
2. Add a metric `path_insight_explanation_pending_total` exposed by knowledge-graph.
3. Backfill the existing 12,689 rows now (no harm — they're all current).
4. Add alert: `explanation_at IS NULL AND computed_at < now() - interval '1 hour'`.
5. Add `depends_on: { postgres: service_healthy, valkey: service_healthy }` on the worker so transient infra blips don't restart-loop it (F-REF-006).

---

### F-LOG-INFRA-001 — Three dependencies have no restart policy; entire pipeline froze for 50 minutes
**Severity**: BLOCKING (transient — restored) | **Confidence**: HIGH | **Flagged by**: B2, A1, A2, A3

**Root cause analysis**

- **What**: `worldview-ollama-1`, `worldview-schema-registry-1`, and `worldview-market-data-1` exited at exactly `2026-05-23T21:40:21Z` with ExitCode=255 (not OOM-killed). Postgres + Kafka rotated PIDs at the same instant. The three deps stayed DOWN while every other service auto-restarted, because they lack `restart: unless-stopped`. This triggered a 50-minute cascade: 3 restart-looping workers, 21 Kafka consumers DNS-frozen on the old Kafka IP, AGE sync gaps, embedding workers crash-looping, etc.
- **Why**: Docker daemon / host-level event (likely Docker Desktop sleep/wake). The `restart: unless-stopped` policy is missing on these 3 services in `infra/compose/docker-compose.yml`.
- **Where**: `infra/compose/docker-compose.yml` (ollama, schema-registry, market-data service blocks)
- **History**: Latent for the lifetime of the stack.

**Impact**

Whenever the host blips, every Kafka consumer + 3 workers enter unrecoverable failure states. The fact that 21 consumers silently stopped consuming with only `FAIL` lines (no metric, no alert, no page) means the pipeline can be **silently dead for hours** before anyone notices.

**Recommended fix**

1. Add `restart: unless-stopped` to ollama, schema-registry, market-data in `infra/compose/docker-compose.yml`.
2. Set `broker.address.ttl=30000` and `broker.address.family=v4` explicitly in `libs/messaging` consumer/producer config so rdkafka re-resolves DNS every 30s.
3. Add a `kafka_connectivity_probe` background task in `BaseKafkaConsumer` that exits the process if it cannot reach the bootstrap server for >5 minutes — letting compose restart with a fresh DNS lookup.
4. Add `make doctor` target that diffs `docker ps --filter status=running` against the expected service list.
5. Wrap startup DB calls in worker entrypoints (`embedding_retry_worker_main.py:84`, `unresolved_resolution_worker_main.py:83`, `path_insight_worker_main.py`) with retry decorator (3 attempts × 5s backoff) before `sys.exit(1)`.

---

### F-CHAT-AGENT-001 — RAG agent fabricates numeric data when tools return sparse rows
**Severity**: BLOCKING (for investor use) | **Confidence**: HIGH | **Flagged by**: A5, A4

**Root cause analysis**

- **What**: Asked "Compare the revenue trajectories of NVIDIA and AMD over the last 4 quarters", the agent called `get_fundamentals_history` once (returned 1 row), then **invented AMD Q1'26 revenue as $34.6B** (actual: $10.253B — 3.4× wrong), scrambled NVDA quarter labels (correct numbers, wrong period names), and **volunteered a fabricated narrative about "potential volatility or a one-time event"** to rationalize its own bad number.
- **Why**: Two compounding bugs in the RAG agent:
  1. The tool-use system prompt (`chat_orchestrator.py:323-339`) explicitly invites pretraining knowledge supplement: *"For well-known entity relationships where tools return sparse results, you may supplement from your training knowledge..."* — this directly contradicts the strict `FINANCIAL_DATA` prompt in `libs/prompts/.../intent.py` (which is loaded but **dead code** because intent is hard-coded to GENERAL).
  2. There is no post-tool validation that the LLM's numerical claims match the tool's returned rows. The egress filter scrubs only `entity:UUID` and `article:UUID` patterns, not `[N1]` citations or numeric assertions.
- **Where**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:323-339,353,119-145`
- **History**: New finding — not BP-tagged.

**Impact**

A PM acting on $34.6B AMD revenue would build a 3× wrong thesis. Across 8 investor questions, only 1 was useful (Q8 OpenAI→MSFT paths), 1 was marginal-but-grounded (Q3 Tim Cook), 3 returned hard 503 refusals on single-tool failure, and 3 produced confident hallucinations including invented product names ("MI300 series gaining design wins"). **The agent's confident wrongness is the single most dangerous failure mode in financial AI.**

**Recommended fix**

1. **Replace the tool-use system prompt** with `get_system_prompt(intent)` from `libs/prompts`. Remove the "supplement from training knowledge" clause for financial numbers entirely.
2. **Wire intent classification** — either a lightweight one-shot LLM call upstream of the tool loop, or infer intent from the first tool calls and inject it for prompt + metrics.
3. **Add a post-tool numeric-grounding validator**: parse every numeric claim in the LLM output, require it to either appear verbatim in a tool result or be explicitly labelled `[derived]` with the formula shown. Reject responses that fail validation; force retry with stricter prompt.
4. **Add multi-tool fallback**: when a tool returns 0 items, the orchestrator should attempt 1 alternate tool (e.g., `search_documents` empty → try `get_entity_intelligence`) before surfacing `[PROVIDER_UNAVAILABLE] 503` (F-CHAT-001/004/006).
5. **Fix response duplication** (F-CHAT-002): the sync coalescer in `execute_sync` is emitting intermediate + final tokens.

---

## CRITICAL Issues

### F-DB-RELATIONS-001 — Relations have orphan FKs because of missing constraint (BP candidate)
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: B1

Already covered in F-KG-PERSIST-002. The DDL gap (no FK constraint on relations) is the root architectural cause of the orphan-FK problem.

---

### F-DB-IMPACT-SCORE-001 — `document_source_metadata.impact_score` 100% NULL
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: A1 (F-NPL-008), B1 (F-DB-004)

- **What**: 6,424 of 6,424 docs (100%) have `impact_score IS NULL`. PRD-0026 `display_relevance_score = 0.5*market + 0.4*llm + 0.1*routing` collapses to 2 components.
- **Why**: Column added in PRD-0026 but no writer was wired. Possibly dependent on F-NPL-006 (`article_impact_windows` empty → no source data for market component).
- **Fix**: Either (a) implement the writer in `PriceImpactLabellingWorker` — when it computes windows, also update `document_source_metadata.impact_score`; OR (b) update PRD-0026 to formally drop the column and re-weight.

---

### F-NPL-FUNDAMENTALS-001 — `article_impact_windows` empty; market-data 404s on every ticker
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: A1 (F-NPL-006), A3 (F-REF-003)

- **What**: `article_impact_windows` has 0 rows. `entity_embedding_state.fundamentals_ohlcv` has 2,197 rows with 100% NULL embedding AND 100% NULL source_text. `PriceImpactLabellingWorker` and `fundamentals_refresh` worker both hit `market-data/api/v1/instruments/symbol/<TICKER>` → 404 for AAPL, MSFT, NVDA, GOOGL, TSLA, U, VRTX, WAB, UPS, UNP, WDC, XRAY, XYL, ...
- **Why**: Wrong URL pattern (market-data may expose `/v1/instruments/{ticker}` not `/symbol/{ticker}`), missing instrument seeding, OR market-data has no symbol→ID resolver endpoint. Worker has no backoff — retries every cycle.
- **Fix**: (1) Audit the market-data API contract — current path returns 404. (2) Verify instrument seeding. (3) Add exponential backoff on persistent 404 in fundamentals_refresh (bump `next_refresh_at` by 1d/7d/30d after N failures). (4) Log actual HTTP status code instead of generic "unavailable".

---

### F-DB-ENRICHMENT-001 — `enrichment_attempts` counter frozen at 0 → sweep never advances
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: B1 (F-DB-005)

- **What**: 1,790 of 5,230 canonical_entities (34%) have never been enriched (`enriched_at IS NULL`) AND every single row has `enrichment_attempts=0`. The `ix_canonical_entities_enrichment_sweep` partial index (`WHERE attempts < 3`) keeps including these rows forever, but the worker still skips them.
- **Why**: The EnrichmentWorker increments attempts in memory but never UPDATEs the row. BP-541 memory entry says "3,440 descriptions backfilled" — this fix appears to have regressed.
- **Fix**: Make `enrichment_attempts` UPDATE atomic and required. Add a sweep job: `WHERE attempts=0 AND enriched_at IS NULL AND created_at < now() - interval '1 day'`. Investigate why `fundamentals_ohlcv` source_text is never populated for non-equity types (`product`, `event`, `macro_indicator` are 100% empty).

---

### F-DB-SUMMARIES-001 — 98.7% of relations have no human-readable summary
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: B1 (F-DB-003)

- **What**: Only 101 of 7,884 relations (1.3%) have a summary; 6,346 (80%) carry `summary_stale=true`.
- **Why**: `SummaryWorker` (BP-407 / PRD-0076 B-1) is not keeping up. Compounded by F-KG-PERSIST-002: SummaryWorker requires confidence as input, but 60% of relations have NULL confidence.
- **Fix**: Investigate SummaryWorker scheduling lag; expose `relation_summary_backlog` Prometheus gauge; backfill once F-KG-PERSIST-002 is fixed.

---

### F-NPL-ROUTING-001 — 3 of 8 routing signals are permanently zero
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: A1 (F-NPL-003/004/006)

- **What**: Three signals contributing to `composite_score` are always 0:
  1. **`watchlist_signal`**: checks `m.resolved_entity_id`, but `compute_routing_score` runs BEFORE entity resolution. Always 0.0.
  2. **`novelty_score`**: hardcoded to `1.0` at call site (`article_consumer.py:575`) — MinHash runs AFTER routing.
  3. **`price_impact_score`**: derived from `article_impact_windows` (empty — see F-NPL-FUNDAMENTALS-001).
- **Why**: Single-pass architecture (route → resolve) when a two-pass design (route → resolve → re-route) is needed.
- **Fix**: Either (a) route after resolution + MinHash, OR (b) drop these signals from the PRD formula and re-weight remaining signals to sum to 1.0.

---

### F-RAG-PROMPT-001 — Tool-use system prompt invites hallucination
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: A4 (F-RAG-001), A5

Covered in F-CHAT-AGENT-001. The string at `chat_orchestrator.py:331` reads *"For well-known entity relationships where tools return sparse results, you may supplement from your training knowledge but must label it 'Based on public knowledge:'."* This produced Q4's $34.6B AMD fabrication and Q6's invented "MI300 gaining design wins".

---

### F-RAG-INTENT-001 — Intent hard-coded to GENERAL; per-intent prompts are dead code
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: A4 (F-RAG-002)

- **What**: `intent = QueryIntent.GENERAL` set once and never updated. PLAN-0067 deleted the `IntentClassifier` and never re-introduced a signal. `FINANCIAL_DATA`/`FACTUAL_LOOKUP`/etc. prompt templates in `libs/prompts/.../intent.py` are dead code in the tool-use path.
- **Impact**: No intent observability; reranker uses generic config regardless of query type.
- **Fix**: Either (a) one-shot LLM intent classification upstream of the tool loop, OR (b) infer intent from the first set of tool calls (e.g. `compare_entities` → COMPARISON; `traverse_graph` → RELATIONSHIP).

---

### F-LOG-MIGRATION-001 — SQL queries reference non-existent columns post-migration
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: B2 (F-LOG-004)

- **What**: Postgres logs show ongoing errors: `column "gliner_score" does not exist`, `column "updated_at" does not exist`, `column "entity_provisional" does not exist`, `column "embedding_type" does not exist`, `column "published_at" does not exist` (4 occurrences), `column "label" does not exist`. ~10 errors/min.
- **Why**: Migrations 0026-0029 renamed/moved columns; consumers still reference stale names. Each error rolls back a transaction.
- **Fix**: Repository CI test — run every `SELECT … FROM` declared by repositories against an empty schema; pgsql's `PREPARE` catches "column does not exist" without needing real data. Trace each query to its source file.

---

### F-LOG-JWT-001 — RAG-chat skips JWT verification because APP_ENV unset
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: B2 (F-LOG-005)

- **What**: `worldview-rag-chat-1` startup logs `SECURITY: internal_jwt_skip_verification=True with APP_ENV unset`. Every request bypasses signature validation.
- **Fix**: Add `APP_ENV=local` to rag-chat env in `infra/compose/docker-compose.yml`. Add a service-startup assertion that refuses to boot if `APP_ENV` is unset AND `internal_jwt_skip_verification=True`.

---

## MAJOR Issues (summary table — full details in source agent reports)

| ID | Source | File | One-line |
|---|---|---|---|
| F-NPL-005 | A1 | `embedding_writes.py:90-124` | gliner_mention_floor only filters JSONB cache, not entity_mentions table (26% sub-floor mentions persisted) |
| F-NPL-007 | A1 | live data | `entity_embedding_state.fundamentals_ohlcv` 100% NULL (cross-confirmed) |
| F-NPL-011 | A1 | `article_consumer.py:407-443` | `_write_source_metadata` silently swallows all exceptions; no metric |
| F-NPL-012 | A1 | live data | 93 articles DLQ on extraction timeout (BP-534) — needs replay |
| F-KG-103 | A2 | `graph_query.py:60-66` | QW-3 `direction` field missing from graph response — frontend can't render edges correctly |
| F-KG-104 | A2 | `graph_write.py:522-534` | BP-521 direction normalization only fires when both entity types present |
| F-KG-107 | A2 | `graph_write.py:151-166` | `_DETERMINISTIC_CREATED_AT_FALLBACK=2024-01-01` has no metric — silent fallback to wrong partition |
| F-REF-002 | A3 | `age_sync_worker.py:373-441` | 70% of relations missing from AGE; watermark advances on partial sync |
| F-REF-004 | A3 | live data | 3,475 definition embeddings overdue (BP-541 regression) |
| F-REF-005 | A3 | live data | 603 narrative embeddings empty (transient outage backlog) |
| F-REF-007 | A3 | `age_sync_worker.py:218-265` | Watermark advances on phase failure → strands unsynced rows |
| F-REF-009 | A3 | `embedding_retry_worker_main.py:84-86` | Startup pre-checks have no retry guard |
| F-RAG-003 | A4 | `intelligence.py:144-154` | 4 KG tools silently return [] without scoped entity (no name resolution) |
| F-RAG-004 | A4 | `intelligence.py:363-364` | `search_entity_relations` uses zero-vector ANN placeholder → noise results |
| F-RAG-005 | A4 | `news.py:124-143` | `entity_tickers` accepted but ignored → multi-entity queries silently degrade |
| F-RAG-006 | A4 | `chat_orchestrator.py:119-145` | `[N1]` citation markers not validated against retrieved items |
| F-RAG-007 | A4 | `chat_orchestrator.py:368-588` | No tool-call dedup across iterations → budget waste on confused models |
| F-RAG-008 | A4 | `chunk_search.py:131-200` | HNSW sparse-filter recall collapse — no `hnsw.ef_search` tuning |
| F-CHAT-001 | A5 | runtime | Single-tool failure → 503; no fallback to alternate tools |
| F-CHAT-003 | A5 | runtime | **Numeric hallucination** — invented $34.6B AMD figure (covered in F-CHAT-AGENT-001) |
| F-CHAT-004 | A5 | runtime | Macro-events question never combines calendar + exposures tools |
| F-CHAT-005 | A5 | runtime | Can't operationalize screener — doesn't translate "rising sentiment" into screener params |
| F-CHAT-006 | A5 | runtime | Contradictions tool returns 0 for TSLA — flagship feature dead |
| F-DB-006 | B1 | live data | 924 + 1,218 articles + 800 predictions dead-lettered; no replay job |
| F-DB-007 | B1 | live data | 88 provisional pending >18h; 1,115 noise rows never cleaned (10-day-old) |
| F-DB-008 | B1 | live data | 100% of relation_evidence_raw has NULL claim_id AND chunk_id → zero traceability |
| F-DB-009 | B1 | live data | AGE label case gotcha — `MATCH (n:Entity)` returns 0 (actual: `entity`) |
| F-DB-010 | B1 | live data | 100% NULL tenant_id on entity_mentions (51,761 rows) → schema lies |
| F-LOG-002 | B2 | runtime | 3 workers in 55-72 restart loop (transient — restored) |

---

## MINOR + NIT Findings (one-liners)

- **F-NPL-009**: Duplicate MinIO GET in `extract_url_from_silver` + `download_article`
- **F-NPL-010**: NER UUID7 immediately overwritten by UUID5 — wasted allocation
- **F-NPL-013**: `_AUTHORITATIVE_FILING_SOURCES` carve-out rarely fires — needs counter
- **F-KG-105**: 3 new Lever-4 predicates missing prompt examples (`divested_from`, `downgraded_by`, `filed_lawsuit_against`)
- **F-KG-106**: Narrative grounding query lacks confidence/freshness weighting
- **F-KG-102**: Path-insight `sys.exit(1)` causes restart loop on transient outages (covered in F-REF-006)
- **F-KG-108**: ✅ BP-539, BP-521, BP-520, BP-385 verified in place (positive finding)
- **F-REF-008**: `region or ""` in `_sync_temporal_events` substitutes empty string for NULL — semantically misleading
- **F-REF-010**: `age_sync_worker_complete` doesn't warn on per-phase stalls
- **F-RAG-009**: 4 graph tools have overlapping descriptions — routing ambiguity
- **F-RAG-010**: System prompt has no few-shot examples despite `example_queries` in tool manifest
- **F-RAG-011**: Tool calls > 5 silently truncated (no warning)
- **F-RAG-012**: `_TOOL_RESULT_MAX_CHARS=4000` is the binding constraint — per-chunk cap of 4000 is dead
- **F-DB-011**: 98% of temporal_events have empty `source_article_ids`
- **F-DB-012**: 4 self-loops on phantom macro sentinel (root in F-KG-PERSIST-002)
- **F-LOG-003**: rdkafka stale DNS cache — restored, but `broker.address.ttl=30000` still needed
- **F-CHAT-002**: Response duplication in sync coalescer (cosmetic but very visible)
- **F-CHAT-INFRA-001**: Local platform doesn't survive overnight — 6 of 7 API containers exited

---

## Recommended Remediation Roadmap (2-Week Sprint)

### Week 1 — Data layer integrity

| Day | Owner | Task | Verifies |
|---|---|---|---|
| 1 | Backend | Fix F-KG-PERSIST-001: bootstrap AGE labels + reset watermark + force full resync | AGE has 14,762 events + 7,884 edges |
| 1 | Backend | Fix F-KG-PERSIST-002 part 1: seed macro sentinel + add FK constraint | Zero orphan FKs |
| 2 | Backend | Fix F-KG-PERSIST-002 part 2: backfill NULL confidence + add NOT NULL | Zero NULL confidence |
| 2 | Backend | Deploy + verify F-KG-PERSIST-003 (path-insight worker) + backfill 12,689 rows | All path_insights have explanations |
| 3 | Backend | Fix F-DB-IMPACT-SCORE-001: wire `impact_score` writer | Zero NULL impact_score |
| 3 | Backend | Fix F-NPL-FUNDAMENTALS-001: market-data symbol resolver + backoff | First 100 fundamentals embeddings populated |
| 4 | Backend | Fix F-DB-ENRICHMENT-001: atomic enrichment_attempts UPDATE + sweep | 100 entities re-enriched in test |
| 4 | Backend | Fix F-NPL-ROUTING-001: either two-pass routing OR drop dead signals | Composite score reflects real signals only |
| 5 | Backend | Fix F-DB-SUMMARIES-001: SummaryWorker catchup + metric | Backlog < 10% |

### Week 2 — Agent quality + infrastructure hardening

| Day | Owner | Task | Verifies |
|---|---|---|---|
| 6 | Backend | Fix F-CHAT-AGENT-001 part 1: replace tool-use prompt + wire intent | Q4 NVDA/AMD returns only quoted numbers |
| 7 | Backend | Fix F-CHAT-AGENT-001 part 2: numeric-grounding validator | Numeric claims fail-closed when not in tool output |
| 7 | Backend | Fix F-RAG-003: name resolution path for 4 KG tools | All 4 tools return data without scoped entity |
| 8 | Backend | Fix F-RAG-004: real embedding for `search_entity_relations` | Relations sorted by semantic relevance |
| 8 | Backend | Fix F-RAG-005: ticker→UUID resolution OR remove `entity_tickers` field | Multi-entity comparison works |
| 9 | Infra | Fix F-LOG-INFRA-001: add `restart: unless-stopped` + `depends_on` healthchecks + rdkafka TTL | Survive host reboot without intervention |
| 9 | Infra | Fix F-LOG-JWT-001: APP_ENV=local + boot-time assertion | RAG-chat refuses to boot without APP_ENV |
| 10 | Backend | Fix F-LOG-MIGRATION-001: CI test that prepares every repo SELECT | Zero "column does not exist" errors |
| 10 | Backend | Re-run A5 (8 investor questions) and gate at ≥ 6/8 useful | Verdict reversal: PASS_WITH_WARNINGS |

### Backlog (not blocking but high-value)

- F-RAG-006 (citation marker validation), F-RAG-007 (tool-call dedup), F-RAG-008 (HNSW ef_search tuning)
- F-DB-008 (relation_evidence_raw backfill of claim_id/chunk_id)
- F-DB-010 (entity_mentions tenant_id wire or drop)
- F-DB-006 (DLQ replay job for 93+924+1218 articles + 800 predictions)
- F-KG-103 (QW-3 `direction` field) — frontend depends on this
- F-CHAT-002 (response duplication)

---

## Compounding Notes

- **New BP candidates**:
  - BP-NEW-1: "AGE vlabel/elabel must be explicitly bootstrapped; missing label causes silent ProgrammingError → watermark advance" (root of F-KG-PERSIST-001)
  - BP-NEW-2: "rdkafka DNS cache holds stale broker IPs after Kafka restart; consumers silently stop with FAIL lines, no metric" (F-LOG-003)
  - BP-NEW-3: "Repository SELECT with stale column name fails at execution time, not parse time; passes import + lint but errors per-row" (F-LOG-MIGRATION-001)
  - BP-NEW-4: "LLM agent extrapolates from N=1 tool row; numeric hallucination wrapped in plausible prose" (F-CHAT-AGENT-001)
  - BP-NEW-5: "`enrichment_attempts` counter that never UPDATEs makes a partial-index sweep look correct but never advances" (F-DB-ENRICHMENT-001)
- **HIGH_RISK_PATTERNS.md additions**: agent system prompts that explicitly invite training-knowledge supplement for factual queries; watermark advances on partial sync; FK without DB constraint.
- **REVIEW_CHECKLIST.md additions**: "Does this worker have `depends_on: { dep: service_healthy }` on every external dependency?"; "Does this query reference only columns confirmed to exist in the current migration head?"; "Does this LLM prompt forbid pretraining-knowledge for numerical claims?".
- **Memory note correction**: BP-541 (description backfill) is **regressed** — 34% of entities still lack descriptions. `PrunedDescriptionAdapter` referenced in memory does NOT exist in the codebase.

---

## TRACKING.md

This QA pass should be recorded in `docs/plans/TRACKING.md` against any plan that touches knowledge-graph, nlp-pipeline, rag-chat, or intelligence-migrations. The 10 BLOCKING/CRITICAL findings are too broad to attribute to a single plan; they reflect cumulative drift since PLAN-0089.

---

**Report written**: `docs/audits/2026-05-23-qa-intelligence-pipelines-report.md`
**Verdict**: **FAIL** — not deployable. 2-week remediation sprint required before any paying-investor exposure.
