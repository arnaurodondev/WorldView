# Internal Tool / Chat Pipeline Latency Investigation — 2026-06-18

**Scope:** Root-cause the 35-85s rag-chat turn latency observed in the chat benchmark.
**Method:** READ-ONLY — live `chat_phase_timings_ms` logs, container `docker stats`, `pg_stat_activity`, and `EXPLAIN ANALYZE` of suspect queries. No code or data was mutated.
**Environment note:** Containers were restarted ~07:46 UTC; the platform was under far less load at probe time (postgres 30% CPU, load avg ~15) than when the original 300-463% CPU / load 23-37 symptoms were captured. This is itself a key data point (see §6).

---

## 1. Executive summary — the hypothesis is wrong

The investigation brief assumed the bottleneck was **tools / DB / entity-resolution**. The phase timings show the opposite: **~94% of wall-clock time is spent in LLM calls to DeepInfra (Qwen3-235B-A22B)**, not in tools or Postgres.

Phase breakdown across 5 live turns (current, lightly-loaded logs):

| Phase | mean ms | p50 ms | max ms | % of total | What it is |
|---|---|---|---|---|---|
| `llm_tool_planning` | 20,380 | 18,330 | 33,533 | **37.7%** | LLM call — agent tool-selection loop (multi-iteration) |
| `grounding_validation` | 16,186 | 105 | 41,500 | **29.9%** | **LLM call** — numeric-grounding rewrite |
| `llm_direct_text_generation` | 14,199 | 15,297 | 30,941 | **26.2%** | LLM call — final answer synthesis |
| `entity_resolution` | 7,368 | 7,672 | 10,027 | 13.6% | HTTP→S6 SQL cascade (no ML) |
| `tool_execution` | 4,609 | 4,830 | 7,495 | 8.5% | upstream tool HTTP (market-data/KG) |
| `entity_grounding_validation` | 3,814 | — | 7,217 | 2.8% | **LLM call** — entity-name rewrite |
| `validate_input` | 1,693 | 1,581 | 2,778 | 3.1% | input guard |
| others (cache/history/persist) | <600 | — | — | ~2% | |
| **TOTAL** | **54,111** | 55,724 | 84,624 | | |

(Percentages sum >100% because phases overlap/are summed independently; the LLM phases — planning + direct gen + both grounding passes — together dominate.)

**The model itself synthesising 2-7s** (as measured separately) is the cost of ONE completion. A single chat turn fires **multiple sequential completions**: the tool-planning loop runs N iterations (one completion per tool-selection round — observed up to 4 iterations), then a direct-generation completion, then up to **two more LLM rewrite passes** (numeric grounding + entity grounding). Log evidence: a single request issues 3-4 `POST .../chat/completions` calls plus reranker calls. That is why a 2-7s model turns into a 35-85s pipeline.

---

## 2. Ranked root causes

### RC-1 (STRUCTURAL, dominant) — Serial multi-call LLM orchestration on a large MoE model
`llm_tool_planning` + `llm_direct_text_generation` + `grounding_validation` + `entity_grounding_validation` = **~96% of total time**. Each is a full Qwen3-235B-A22B completion on DeepInfra, run **sequentially**:
- The tool-planning loop is multi-iteration (`tool_selection_resolved iteration: 0,1,2,3` seen on one COMPARISON turn — 4 sequential planning completions before any answer).
- Then a direct-generation completion.
- Then `grounding_validation` (numeric rewrite) — observed up to **41.5s** alone.
- Then `entity_grounding_validation` (entity rewrite) — up to **7.2s**.

`chat_orchestrator.py:3471` (BP-670 comment) documents this exact failure: "the live 50s Apple-news turn burned 16.5s on a numeric rewrite AND a further 15s on an entity-grounding rewrite" — i.e. **two sequential repair completions stacked on top of planning + generation**. The code already caps repair to one rewrite, but both grounding phases still each cost a full large-model call when they fire.

This is intrinsic, not contention: even idle, four-plus sequential 235B completions cannot be fast.

### RC-2 (CONTENTION-INDUCED) — Tool latency inflates under Postgres/CPU saturation
The brief's headline `get_market_movers latency_ms=9423-9616` is **NOT an intrinsic tool cost**. `EXPLAIN ANALYZE` of the exact movers query on an idle DB:
- **Planning 19ms, Execution 317ms.** The query is a per-instrument double `LATERAL` over the TimescaleDB `ohlcv_bars` hypertable (~20 chunks), but every access is an index scan. Sub-second when the DB is idle.
- At probe time the same tool logged 2.7s (`get_market_movers latency_ms=2737`) — already 8× the idle cost at only 30% postgres CPU.
- At symptom time (postgres 300-463% CPU) it was 9.4-9.6s — ~30× the idle cost.

So the slow tools track Postgres CPU saturation linearly. The saturation source is the **KG/market-data consumer backlog catch-up** after restart: top CPU consumers were `gliner-server (179%)`, `market-data-intraday-resampling-consumer (54%)`, and a fleet of knowledge-graph dataset consumers (9-10% each ×8). At symptom time these were heavier and starved query-time tool calls of CPU/IO.

### RC-3 (STRUCTURAL, secondary) — Entity-resolution fuzzy stage does a Seq Scan
`entity_resolution` (7.4s mean) calls S6 `POST /api/v1/entities/resolve`, which returns HTTP 200 quickly in logs — so the wall time is the SQL cascade, not network. The cascade's Stage-3 fuzzy-trigram query (`entity_alias.py:452 batch_fuzzy_trigram`) is:
```sql
WHERE similarity(normalized_alias_text, :term) > :threshold
```
`EXPLAIN ANALYZE` (idle): **Seq Scan on entity_aliases, Rows Removed by Filter: 36400, Execution 41ms.** The GIN trigram index `idx_entity_aliases_trgm` exists but is **NOT used** — `similarity(col, x) > t` cannot use the GIN index; only the `col % x` operator (or `col <-> x` distance ordering) can. 41ms idle on 36k rows, but it is a full linear scan that (a) scales with alias-table growth and (b) is the most contention-sensitive part of resolution. S6's API resolver runs with `ner_client=None, embedding_client=None` (`dependencies.py:213-214`), so GLiNER/embedding are NOT in this path — the 7s is the SQL cascade running multiple fuzzy windows per query under contention, not ML inference.

### RC-4 (NON-ISSUE at probe time) — Postgres is not the standing bottleneck
`pg_stat_statements` is **not enabled**. `pg_stat_activity` at probe time showed exactly ONE active query (a 203ms `INSERT INTO chunk_embeddings`, IO-wait) — no long-running query-time queries. So Postgres is not intrinsically slow for the chat path; it becomes a bottleneck only transiently when the consumer fleet floods it (RC-2). The `ohlcv-consumer` is in a restart loop (`Restarting (1) 4s ago`) and the `nlp-pipeline-dispatcher` is `unhealthy` — both worth noting as instability but not the latency root cause.

---

## 3. Quick wins vs structural fixes

### Quick wins (low risk, high leverage)
1. **Make the trigram fuzzy query index-usable (RC-3).** Rewrite `batch_fuzzy_trigram` to use the GIN-supported operator + distance ordering instead of `similarity() > t`:
   `WHERE normalized_alias_text % :term ORDER BY normalized_alias_text <-> :term LIMIT k`, then filter by `similarity()` in a thin outer layer. This converts the Seq Scan (36,400 rows discarded) into an index probe — eliminates the only seq scan in the hot resolution path and removes its contention sensitivity. (One-line-ish SQL change; behaviour-preserving with `set_limit`/`pg_trgm.similarity_threshold` aligned to the current 0.3.)
2. **Skip / short-circuit `grounding_validation` when there is nothing to validate.** The p50 is 105ms (no-op) but the mean is 16s and max 41.5s — i.e. it is cheap most turns but occasionally fires a full 235B rewrite. Gate the rewrite more aggressively (only when numeric tokens actually exist AND a citation is actually missing) so it stays a no-op rather than a second large-model call. The BP-670 single-rewrite cap helps; tightening the *trigger* helps more.
3. **Load isolation for the read path (RC-2).** Point the chat tool reads (market-data movers, KG) at a read replica / separate connection pool, OR throttle the KG/market-data dataset-consumer backlog catch-up (lower consumer concurrency / batch size) so query-time tool calls aren't starved. `RAG_CHAT_DATABASE_URL_READ` is currently empty — wiring a read replica is the intended lever.
4. **Cap GLiNER server CPU** (179%, 2.5/4GB RAM) — it is the single largest CPU consumer and competes with everything; it is not even on the chat resolve path (S6 API has `ner_client=None`), so its load is pure background contention. A CPU/replica limit isolates it.

### Structural fixes (higher effort, address RC-1 — the 96%)
5. **Parallelise or collapse the LLM passes.** The four sequential 235B completions (planning loop → direct gen → numeric grounding → entity grounding) are the dominant cost. Options, in increasing order of effort:
   - Use a **smaller/faster model for the grounding-rewrite passes** (validation does not need the 235B; a 0.6-8B model can re-cite numbers). The classification model `Meta-Llama-3.1-8B` is already wired.
   - **Merge the two grounding passes** into a single rewrite prompt (numeric + entity in one call) — halves the repair cost when both fire.
   - **Bound the tool-planning loop iterations** (it ran 4 on one turn) and/or let the planner emit multiple tool calls per iteration so fewer planning round-trips are needed.
6. **Stream the final answer while grounding runs**, or run grounding as a non-blocking post-pass, so the user-perceived latency is the direct-generation time, not direct-gen + two rewrites.

---

## 4. Top 3 recommended fixes (priority order)

1. **RC-1 — Offload grounding/validation rewrites off the 235B model (and merge the two passes).** This is 30%+ of total time on the turns where it fires; moving it to the already-configured 8B classification model and combining numeric+entity into one rewrite is the single highest-leverage change for tail latency. (Structural, but bounded — fix #5.)
   - **IMPLEMENTED (2026-06-18):** the numeric + entity-name grounding passes are merged into a single `ChatOrchestratorUseCase._run_combined_grounding_validation` — both deterministic validators still run, but at most ONE repair completion fires per turn (its prompt lists the ungrounded numbers AND names, so a name issue that co-occurs with a number issue is now FIXED, not bannered as under BP-670). A fully-grounded answer triggers no rewrite (stricter trigger). The repair model is configurable via `RAG_CHAT_GROUNDING_REWRITE_MODEL` (default unset → existing completion model; set to e.g. `openai/gpt-oss-120b` / `-20b` to A/B the rewrite off the 235B without a code change). All anti-fabrication safeguards (phantom-citation + empty-pool refusals, BP-671 divergence guard, BP-674/675 stub guard, BP-670 worse-than-original guard, `[unverified]` banner) are preserved. NOTE: if a gpt-oss model is selected, the adapter must send `reasoning_effort` for that family — `RAG_CHAT_GROUNDING_REWRITE_MODEL` does NOT set it; configure reasoning_effort separately.
2. **RC-3 — Convert the entity-resolution fuzzy query from `similarity() > t` Seq Scan to a `%`/`<->` GIN-index probe.** Removes the only seq scan in the hot resolve path; makes `entity_resolution` (7.4s mean) fast and contention-immune. (Quick win #1.)
3. **RC-2 — Isolate the read path / throttle consumer catch-up.** Wire `RAG_CHAT_DATABASE_URL_READ` to a replica or cap KG/market-data dataset-consumer + GLiNER concurrency, so tool queries (intrinsically <320ms) stop inflating to 9.6s under backlog. (Quick wins #3-#4.)

---

## 5. Evidence appendix
- Phase aggregation: `docker logs worldview-rag-chat-1 | grep chat_phase_timings_ms` → table in §1 (N=5 turns).
- LLM multiplicity: 3-4 `POST https://api.deepinfra.com/v1/openai/chat/completions` per request_id; `tool_selection_resolved iteration: 0..3` on a COMPARISON turn.
- Model config: `RAG_CHAT_COMPLETION_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507`, provider `deepinfra`; `RAG_CHAT_DATABASE_URL_READ=` (empty); `RAG_CHAT_UPSTREAM_TIMEOUT_SECONDS=10.0`.
- Movers query `EXPLAIN ANALYZE` (market_data_db, idle): Planning 19.4ms / Execution **316.9ms** — vs 2.7s logged at 30% CPU and 9.6s at symptom-time CPU.
- Fuzzy query `EXPLAIN ANALYZE` (intelligence_db): **Seq Scan, Rows Removed by Filter 36,400, Execution 41ms**; GIN index `idx_entity_aliases_trgm` present but unused (function-form predicate).
- S6 resolver wiring: `nlp_pipeline/api/dependencies.py:213-214` → `ner_client=None, embedding_client=None` (resolve path is pure SQL).
- DB load: `pg_stat_activity` 1 active query (203ms INSERT, IO); `pg_stat_statements` extension **not installed**. Top CPU: gliner-server 179%, intraday-resampling-consumer 54%, postgres 30%, kafka 25%.
- Instability flags (not root cause): `worldview-market-data-ohlcv-consumer-1` restart loop; `worldview-nlp-pipeline-dispatcher-1` unhealthy.

## 6. Load vs intrinsic — the key distinction
- **Intrinsic (slow even idle):** the LLM orchestration (RC-1) — 4+ sequential 235B completions. No amount of load reduction fixes this; only model/architecture changes do.
- **Contention-induced (slow only under saturation):** the tool queries (RC-2). Movers is 317ms idle, 9.6s saturated. The original 9.4-9.6s `tool_slow` warnings were measured at postgres 300-463% CPU and are an artifact of consumer-backlog contention, not an expensive tool. The fix is load isolation, not query rewriting (the query is already well-indexed).
- **Borderline:** entity-resolution fuzzy (RC-3) is 41ms idle but is a seq scan, so it degrades faster than indexed queries under contention — worth fixing structurally (index) AND isolating (load).
