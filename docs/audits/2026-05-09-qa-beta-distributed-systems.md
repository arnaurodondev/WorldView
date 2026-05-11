# Beta-Readiness QA — Distributed Systems Review

**Date**: 2026-05-09
**Reviewer**: distributed_systems_reviewer (specialist agent)
**Scope**: 17 session commits on `feat/content-ingestion-wave-a1` (4f9662a3 → 2b359f73), with focus on PLAN-0087 demo-stabilization fixes
**Bar**: beta deployment for real analyst use; partial failures expected
**Mode**: read-only

---

## Executive Summary

The PLAN-0087 demo wave fixed several real distributed-systems bugs (R7 cross-DB violation in KG removed; cooperative-sticky assignor + max_poll_records propagation; chat-stream error propagation in sync mode). Idempotency contracts and the outbox pattern remain intact. However, **five issues are material to a beta launch** where partial failures are common:

| ID | Severity | Area | Title |
|----|----------|------|-------|
| F-DS-001 | HIGH | Concurrency | `BriefArchiveWriteAdapter` task GC risk: no strong reference retention on `asyncio.shield`'d save |
| F-DS-002 | HIGH | Rolling restart | Cooperative-sticky assignor change is **not safe to roll out partially**; mixed-protocol consumer groups will fail to form |
| F-DS-003 | MEDIUM | SSE streaming | `chat/stream` has no client-disconnect handler; cancellation mid-LLM-call leaks LLM provider request budget |
| F-DS-004 | MEDIUM | Multi-tenant | `ValkeyDedupMixin` keys are global (not tenant-scoped); will mis-dedup across tenants once Wave 0086 carries real traffic |
| F-DS-005 | MEDIUM | Beta resilience | DeepInfra outage: `NarrativeGenerationWorker` falls back silently to `template-v1` for 6 hours; `BriefArchiveWriteAdapter` swallows persistence errors with no surface |
| F-DS-006 | LOW | Backpressure | KG/`enriched_consumer` has no opt-in to the new `BackpressurePolicy`; LLM-bound consumers run unbounded under backlog |
| F-DS-007 | LOW | Migration 0038 | Demo entity seed inserts canonicals but NOT `entity_embedding_state`; semantic search misses these entities until DefinitionRefreshWorker has run |

No CRITICAL findings. The critical safety nets (outbox pattern, idempotency mixin, partition exclusivity, cooperative-sticky default) are in place.

---

## Specialist mandate — Q-by-Q answers

### Q1. New side-effect functions: failure modes & consistency

**Functions reviewed (new this session)**:
- `BriefArchiveWriteAdapter.save` — `services/rag-chat/src/rag_chat/infrastructure/clients/brief_archive_write_adapter.py`
- `_persist_brief` (closure) — `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py:1031-1045`
- `get_company_overview` KG fallback — `services/api-gateway/src/api_gateway/clients.py:227-310`
- `NarrativeGenerationWorker` (LLM call site rewired to `result.raw_response`) — `services/knowledge-graph/.../generate_narrative.py:455`
- `ChatOrchestratorUseCase.execute_sync` error mapping — `services/rag-chat/.../chat_orchestrator.py:423-505`

**Findings**:

```
1. BriefArchiveWriteAdapter.save — see F-DS-001
   Steps: (a) open session, (b) repo.save → INSERT, (c) commit, (d) close
   - (a) factory raises (DB pool exhausted) → log.warning, swallowed; user sees brief, archive misses
   - (b) INSERT fails (FK violation) → exception swallowed; same outcome
   - (c) commit fails (replica promote) → exception swallowed; same outcome
   - (d) close fails on already-failed session → swallowed
   System state: idempotent at row level (fresh uuid7 each call), so retry-safe.
   Concern: NO retry, NO outbox, NO observability surface — the only signal is a
   structlog warning. With repeated DB blips, briefs disappear silently.

2. get_company_overview KG fallback (D-F1-007)
   Steps: (a) lookup by id, (b) on 404, fetch KG entity, (c) lookup by ticker, (d) gather other legs
   - (a) market-data 404 → caught (good)
   - (b) KG 404 → caught with log.warning + exc_info=True (good)
   - (c) market-data 404 again → caller raises DownstreamError(404) — clean (good)
   Note: each lookup creates its own JWT (`_h()`) — JTI replay-cache safe.
   Verdict: clean, audit-trail visible, fail-closed.

3. NarrativeGenerationWorker (D-R3-NARR fix)
   Steps: LLM call → store narrative → schedule next refresh
   Pre-fix: `result.output` raised AttributeError → caught → fell back to template-v1
   Post-fix: `result.raw_response` is the correct field
   Failure mode: DeepInfra timeout → AttributeError no longer fires;
   `text_result` may still be < _MIN_NARRATIVE_LEN → returns template fallback.
   Acceptable but see F-DS-005 (silent degradation).
```

### Q2. Consumer offset commit semantics

`BaseKafkaConsumer._consumer_loop` (libs/messaging/src/messaging/kafka/consumer/base.py:794-840) commits AFTER `process_message` returns successfully. The new D-P3-006 change adds `await loop.run_in_executor(None, self._record_consumer_lag)` AFTER the commit — does not affect commit ordering.

`enable_auto_commit=False` is the default in ConsumerConfig (verified line ~85). Manual commit-after-process is correct. **Pass.**

### Q3. Concurrent writes / race conditions

- `canonical_entities` (intelligence_db): seed migration 0038 uses `ON CONFLICT (entity_id) DO NOTHING` — safe.
- `entity_aliases`: seed uses `ON CONFLICT (entity_id, normalized_alias_text, alias_type) WHERE is_active = true DO NOTHING` — pinned to the partial unique index, safe.
- `relation_evidence_raw`: source_name now propagated via Avro envelope (D-INIT-6); no more dual-DB lookup race.
- `path_insight_jobs`: still relies on `uq_path_insight_jobs_active` partial unique index per docstring.
- `user_briefs` (rag-chat archival): no upsert key documented — relies on fresh uuid7 per call. **Caveat**: if `GenerateBriefingUseCase.execute_sync` is invoked twice concurrently for the same user (race window between the user double-clicking "Generate"), both writes succeed — duplicate brief rows. Mitigation: read-side `get_latest(limit=1)` returns the most recent, so user-facing impact is "extra row in history". **Pass-with-caveat.**

### Q4. Cross-service direct DB access

D-INIT-6 (commit 493dcb4e) **explicitly removed** `RelationEvidenceRepository.lookup_source_metadata`, which had been querying `document_source_metadata` (an nlp_db table) from intelligence_db sessions. This was an R7/R9 violation that also threw asyncpg `UndefinedTableError` on every fallback. Tombstone comment + architectural-regression test added. **Pass.**

### Q5. Eventual consistency

- nlp-pipeline → KG (`nlp.article.enriched.v1`): latency typically <1s; KG narrative refresh runs every 6h and absorbs missing source_name as a logged warning (no DB re-query). **Acceptable.**
- API gateway page-bundle composition: KG-fallback is per-request (D-F1-007); accepts stale market-data id resolution implicitly. UI degrades to "—" on miss. **Acceptable.**
- BriefArchiveWriteAdapter: shielded background task; user sees the brief immediately, archive may lag the response by 100ms-2s. **Acceptable.**

### Q6. intelligence_db disjoint table sets (S6 vs S7)

`intelligence-migrations` owns DDL. S6 (nlp-pipeline) writes into:
- `chunks`, `chunk_embeddings`, `entity_mentions`, `mention_resolutions`, `routing_decisions`, `document_source_metadata`

S7 (knowledge-graph) writes into:
- `canonical_entities`, `entity_aliases`, `entity_embedding_state`, `relations`, `relation_evidence_raw`, `entity_narrative_versions`, `path_insight_jobs`, `temporal_events`, `geopolitical_events`

**Disjoint** at the table level. Both touch `canonical_entities` for reads but only S7 inserts (S6 reads to resolve mentions). DS-004 risk neutralized by table partitioning. **Pass.**

### Q7. Cache consistency (Valkey)

- Dedup keys: `{prefix}:{event_id}` with 24h TTL, no invalidation needed (TTL-based). **Pass.**
- API gateway page-bundle cache: not in scope of this session (no changes).
- ws_token (alert WebSocket): unchanged this session.
- **F-DS-004**: Dedup keys lack tenant_id — see below.

### Q8. Cooperative-sticky + max.poll.records — DEPLOYMENT VERIFICATION

Confirmed:
- `ConsumerConfig.partition_assignment_strategy` defaults to `"cooperative-sticky"` (libs/messaging/src/messaging/kafka/consumer/base.py:106)
- `to_dict()` now passes BOTH `max.poll.records` and `partition.assignment.strategy` to librdkafka (was silently dropped before — confirmed by the diff in commit 92915986).
- Single instantiation site: `Consumer(self._config.to_dict())` at base.py:386. No bypass paths.
- 30+ production consumer mains use `ConsumerConfig(...)` directly — they all inherit the new default unless explicitly overridden. Searched: zero overrides in services/*.

**However**, see F-DS-002 below for the rolling-restart hazard.

LLM-worker backpressure: `BackpressurePolicy` exists (libs/messaging) and `_maybe_apply_backpressure` is wired in BaseKafkaConsumer. Default is **off** (`backpressure_policy=None`). Of the 30 production consumer mains, none opt in to `BackpressurePolicy`. See F-DS-006.

### Q9. DS-001 .. DS-007, SA-001 .. SA-006 violations

| Pattern | Status |
|---------|--------|
| DS-001 (rebalance during processing) | Mitigated further by cooperative-sticky default |
| DS-002 (outbox dispatcher race) | Unchanged; consumers remain idempotent |
| DS-003 (eventual consistency) | source_name propagation reduces UI staleness |
| DS-004 (intelligence_db concurrent writes) | Disjoint tables; pass |
| DS-005 (non-idempotent consumer) | No new consumers added; existing mixin enforced |
| DS-006 (LLM fallback chain) | Narrative worker now actually uses LLM result; see F-DS-005 |
| DS-007 (claim-check dereference) | No changes to MinIO ref logic |

No new violations introduced. Two NEW concerns documented as F-DS-001 / F-DS-002.

### Q10. Partial-failure worst case

For each new write surface introduced this session, the worst-case state after a single-step failure:

| Operation | Worst case | Severity |
|-----------|------------|----------|
| `BriefArchiveWriteAdapter.save` (DB blip) | Brief returned to user, archive row missing forever | MEDIUM |
| `get_company_overview` (KG 503) | 200 OK with `instrument` populated but neighbours empty (legs gracefully fail) | LOW |
| `NarrativeGenerationWorker` (DeepInfra timeout > retries) | Entity narrative stays at `template-v1`; next refresh in 6h | LOW |
| `enriched_consumer` (source_name missing) | Logged warning, processing continues, evidence row has NULL source_name | LOW |
| `ChatOrchestratorUseCase.execute_sync` (LLM fail) | Now returns 503 (was 200 with empty answer — fixed by D-R1-005) | LOW |

---

## BETA-SPECIFIC ADDITIONS

### Container restart resilience: rag-chat dies mid-stream

**Surface**: `POST /api/v1/chat/stream` returns `EventSourceResponse(event_generator())`.

**Path**: `event_generator` opens `async with make_write_uow(request) as uow:` and iterates `orchestrator.execute_streaming(...)`.

**Failure modes**:
1. Container SIGTERM mid-stream: FastAPI's lifespan stops accepting new connections; in-flight generators get `CancelledError` → `make_write_uow.__aexit__` rolls back the UoW → user's HTTP connection drops with no `event: error` (just TCP FIN).
   - User-side: browser sees premature EOF; no SSE error event. Frontend EventSource auto-reconnects but the message is lost.
2. Pod restart during persistence: `_persist_brief` is shielded — but see F-DS-001: the task may be GC'd before the loop runs it. On a slow event loop (e.g. SIGTERM in flight), this is more likely than in steady state.

**Recommendation (beta)**: Frontend already handles SSE reconnection. Persistence is best-effort. Acceptable for beta. Document the lossy-cancellation contract.

### DeepInfra outage: graceful degradation

**Verified surfaces**:
- `NarrativeGenerationWorker`: retry loop in `generate_narrative.py` — caught broad `Exception`, falls back to `template-v1` placeholder. **Silent**: no metric, no on-call alert. See F-DS-005.
- `ProvisionalEnrichmentWorker` (KG noise classifier Layer 2): not modified this session.
- `rag-chat` chat stream: 4-tier fallback chain (Ollama → Groq → OpenRouter → OpenAI). Falls back to PROVIDER_UNAVAILABLE 503 if all fail. **Pass**.
- `EmbeddingAdapter` (S6/S7): Ollama `bge-large:latest` fallback when DeepInfra api_key empty. **Pass**.
- `UnresolvedResolutionWorker`, `ArticleRelevanceScoringWorker`: Ollama qwen3:0.6b fallback. **Pass**.

**Beta verdict**: chat degrades gracefully (503). KG narrative degrades silently (template). For an analyst-facing demo, the silent KG degradation (F-DS-005) is the riskiest.

### Kafka outage: producers buffer outbox? consumers reconnect?

- **Producers via outbox**: writes sit in `*_outbox` table with `dispatched_at IS NULL`. Outbox dispatcher re-tries on next poll. No data loss. **Pass.**
- **Consumers**: `BaseKafkaConsumer._consumer_loop` is a long-running `while not self._stop_event.is_set()` loop. On Kafka unavailability, `consumer.poll()` returns None / errors are caught. Health check (`/healthz`) does not separately health-check Kafka — depends on liveness probe spec. **Acceptable for beta.**
- **Schema Registry**: D-INIT-6 commit message explicitly notes: "*The running Schema Registry still has the old version; the operator must re-register the new subject and restart the affected producers/consumers.*" If operator skips this step, the new `nlp.article.enriched.v1` field `source_name` will be DLQ'd by old consumers, but the field is nullable with `default: null`, so forward-compat holds. **Pass.**

### Postgres outage / replica lag

- R23 read/write split was completed in PLAN-0076 Sub-Plan B. Read-only use cases use `ReadOnlyUnitOfWork` (replica). Writes use primary.
- During replica lag, read-only use cases see slightly stale data — **acceptable** per project design.
- During primary outage, writes raise `OperationalError`; FastAPI returns 500. No graceful 503 mode (read-only fallback) is implemented.
- Beta concern: a 5-minute primary outage during a demo would be visible. Mitigation: `pgbouncer` already in stack; failover is operational, not code-level.

**Verdict**: No change required for beta beyond ops runbook.

### Multi-tenant isolation under concurrent load (Wave 0086)

Wave 0086 introduced tenant_id propagation to `nlp.document.ready.v1` + ingestion path. Re-verification:

- `canonical_entities`: NO tenant_id (intentional — global ontology). Demo entities seeded in 0038 are also tenant-less. **Pass for the platform's design**, but be aware: an entity created by tenant A is visible to tenant B's KG queries. This is a deliberate design choice ("shared ontology, per-tenant articles").
- `relations`, `relation_evidence_raw`, `entity_narrative_versions`: same — global.
- `document_source_metadata`, `chunks`, `chunk_embeddings`, `entity_mentions`: per-tenant (tenant_id column).
- **F-DS-004 risk**: ValkeyDedupMixin keys are NOT tenant-scoped. The class docstring explicitly warns:
  > "WARNING (multi-tenant): dedup keys are global per consumer group, not per tenant."
  Two tenants posting the SAME `event_id` (extremely unlikely with uuid7, but possible if a malicious tenant replayed another tenant's event_id) would silently dedup the second one.

**Beta verdict**: Acceptable for beta (single deployment, friendly tenants). Block before a second hostile-tenant onboards.

---

## Findings

### F-DS-001 — `BriefArchiveWriteAdapter` task GC risk **(HIGH)**

**File**: `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py:1041-1049`

```python
_task = asyncio.ensure_future(asyncio.shield(_persist_brief(_record)))
_task.add_done_callback(lambda _: None)

return { ... }
```

**Issue**: `_task` is a function-local variable. Once `execute_sync` returns, only the asyncio loop's pending-task list keeps a reference. Python's GC documentation explicitly warns this is unreliable for fire-and-forget tasks; the canonical fix is a class-level set:

```python
self._pending_tasks.add(_task)
_task.add_done_callback(self._pending_tasks.discard)
```

The `add_done_callback(lambda _: None)` adds a strong ref from the task to the lambda, but does NOT add a strong ref FROM anywhere TO the task. Under CPython this is usually fine because the loop holds the task in `loop._ready`, but on `loop.run_until_complete` exits or under aggressive GC pressure (e.g. during SIGTERM), pending tasks have been observed to disappear.

**Severity**: HIGH for beta. A user briefing is the highest-value persisted artifact. Silent loss + no metric = invisible failure mode.

**Recommendation**:
1. Add `self._pending_persist_tasks: set[asyncio.Task] = set()` to `GenerateBriefingUseCase.__init__`.
2. Replace local `_task` with `self._pending_persist_tasks.add(task); task.add_done_callback(self._pending_persist_tasks.discard)`.
3. Add a Prometheus counter `rag_chat_brief_persist_failed_total` in `BriefArchiveWriteAdapter.save` exception path so silent failures become visible.

---

### F-DS-002 — Cooperative-sticky rolling-restart hazard **(HIGH)**

**File**: `libs/messaging/src/messaging/kafka/consumer/base.py:106` (default = `cooperative-sticky`)

**Issue**: Switching a Kafka consumer group's `partition.assignment.strategy` is **not safe to do via rolling restart**. Per librdkafka / KIP-429 semantics, all members of a group must agree on the protocol family (eager vs cooperative) at JoinGroup time. Mixed groups will fail GroupCoordinator's protocol selection and one set of members will be repeatedly evicted.

**Operational implication**: On the next deployment, **all** consumers in a given group MUST be stopped before any new-image consumer starts, OR the operator must do a "two-phase" deploy:
1. First deploy with `partition_assignment_strategy="range,cooperative-sticky"` (both names — librdkafka picks the highest the group agrees on).
2. After all members are on the new image, second deploy with just `"cooperative-sticky"`.

The current default is the single-protocol form. A naive `docker compose up -d --build` of just one service in a multi-replica deployment will wedge the group.

**Severity**: HIGH for beta if the deployment model is rolling restarts. LOW if every deploy is "stop all consumers, then start all" (single replica per service in dev = no exposure).

**Recommendation**:
1. Change default to `"cooperative-sticky,range"` (compatible-mode list) so first deploy is safe.
2. Document the two-phase rollout in `docs/services/messaging.md` and `RUNBOOK.md`.
3. Add an integration test that asserts a consumer started against a group with mixed strategies still consumes (currently no test covers protocol negotiation).

---

### F-DS-003 — `chat/stream` client-disconnect handling **(MEDIUM)**

**File**: `services/rag-chat/src/rag_chat/api/routes/chat.py:99-154`

**Issue**: `event_generator` does not catch `asyncio.CancelledError`. When the client closes the SSE connection mid-LLM-call:
1. Starlette cancels the generator.
2. `async with make_write_uow as uow:` catches the cancellation in `__aexit__` and rolls back. **Good**.
3. But the in-flight HTTP request to DeepInfra/OpenRouter does NOT get cancelled — the LLM call holds the provider's tokens-per-minute budget until the response or timeout completes.
4. The `_persist_brief` shielded task (if launched) continues to completion. **Good** (shield is intentional).

**Severity**: MEDIUM. Provider budget leak under heavy reload-spam. No silent data corruption.

**Recommendation**:
1. Make `httpx.AsyncClient` calls cancellation-propagating (currently most of the platform uses `asyncio.wait_for` which does propagate, but the LLM clients in `libs/ml-clients` should be reviewed — out of scope).
2. Add a `try / except CancelledError` in `event_generator` that emits one final SSE error event and re-raises. This at least gives the client clear closure semantics.

---

### F-DS-004 — Valkey dedup keys not tenant-scoped **(MEDIUM)**

**File**: `libs/messaging/src/messaging/kafka/consumer/dedup.py:99-104` (already documented in docstring)

**Issue**: As above. Documented but not fixed. With Wave 0086 having shipped, this is now a real exposure for any beta with > 1 tenant.

**Severity**: MEDIUM. uuid7 collision is astronomically unlikely; but a malicious tenant replaying another tenant's event_id IS a tenant-isolation hole.

**Recommendation**: Override `is_duplicate` / `mark_processed` in tenanted consumers (the article_consumer, document_ready_consumer, document_deletion_consumer at minimum) to incorporate tenant_id into the key:
```python
key = f"{self._dedup_prefix}:{tenant_id}:{event_id}"
```
The tenant_id is now propagated via Wave 0086, so it's available in the event payload.

---

### F-DS-005 — Silent template-v1 fallback in narrative worker **(MEDIUM)**

**File**: `services/knowledge-graph/src/knowledge_graph/application/use_cases/generate_narrative.py:455-475`

**Issue**: Post D-R3-NARR fix, `result.raw_response` is read correctly. But if `len(text_result) < _MIN_NARRATIVE_LEN` (after retries), the function silently returns the `template-v1` placeholder. The previous bug (`result.output` AttributeError) was visible because every entity got `template-v1`; once the field name is fixed, the worker is more reliable but the fallback path is identical.

**Beta exposure**: A 6-hour DeepInfra outage during the demo window would cause every NEW entity to land with `template-v1`. The Intelligence tab would render "[template-v1] X: Y with N known relations..." on cards. The previous demo audit (R3) caught this; it could happen again.

**Severity**: MEDIUM. Visible to user, not data-corrupting.

**Recommendation**:
1. Emit a counter `kg_narrative_template_fallback_total{reason="llm_short_or_failed"}` whenever the template fallback fires.
2. Add a Grafana panel + alert at >5/min.
3. Optionally, mark `entity_narrative_versions.model_id='template-v1'` rows with a `requires_retry=true` flag and have the periodic refresh prefer them on the next pass.

---

### F-DS-006 — LLM-bound consumers unbounded under backlog **(LOW)**

**Files**: `services/knowledge-graph/.../enriched_consumer_main.py`, `services/knowledge-graph/.../structured_enrichment_consumer_main.py`, `services/nlp-pipeline/.../article_consumer_main.py`

**Issue**: All production consumer mains instantiate `ConsumerConfig(...)` without supplying a `BackpressurePolicy`. `BaseKafkaConsumer.__init__` defaults `backpressure_policy=None` → no pause/resume on lag. Combined with per-message DeepInfra calls that can take 30-60s, a backlog of >100 messages can pile up and exhaust the LLM provider budget.

**Severity**: LOW for beta if traffic is shaped (single-tenant demo). MEDIUM under burst load.

**Recommendation**: Wire `BackpressurePolicy(enabled=True, lag_threshold=...)` into the LLM-bound consumers. The infrastructure exists (libs/messaging); only the wiring is missing.

---

### F-DS-007 — Demo-seed entities lack `entity_embedding_state` **(LOW)**

**File**: `services/intelligence-migrations/alembic/versions/0038_seed_demo_entities.py`

**Issue**: The 8 seeded canonicals (OpenAI, Anthropic, COIN, NFLX, INTC, QCOM, AMD, GOOG) have `description` populated but NO row in `entity_embedding_state`. Until `DefinitionRefreshWorker` runs and embeds the descriptions, these entities will not surface in semantic-similarity search (SearchByDescription / chat retrieval).

**Severity**: LOW. The `DefinitionRefreshWorker` runs on a schedule and will pick them up; just not immediately at boot.

**Recommendation**: Either (a) add a dummy row to `entity_embedding_state` with a "needs_recompute" flag in the same migration so the worker prioritises them, or (b) explicitly trigger `DefinitionRefreshWorker.refresh_all()` once after migration 0038 applies. Option (b) is the cleaner ops choice.

---

## Compounding updates recommended

1. **DISTRIBUTED_SYSTEM_PATTERNS.md**: add **DS-008 — Consumer assignment strategy mismatch on rolling restart** (capture F-DS-002 lesson).
2. **DISTRIBUTED_SYSTEM_PATTERNS.md**: add **DS-009 — Background asyncio task GC under SIGTERM** (capture F-DS-001 lesson).
3. **REVIEW_CHECKLIST.md / Concurrency**: add row "asyncio.create_task / ensure_future result is held in a strong reference (class-level set or instance attr)".
4. **bug-patterns/kafka-messaging.md**: add a "rolling-restart safety" section noting `cooperative-sticky,range` compatible default.

---

## Test surface review

The session added solid regression tests:
- `libs/messaging/tests/unit/kafka/consumer/test_consumer_config.py` — confirms cooperative-sticky default + max_poll_records pass-through (5 new tests).
- `services/knowledge-graph/tests/unit/test_consumer.py` — confirms source_name happy path + missing-source warning + architectural regression on `lookup_source_metadata` removal.
- `services/rag-chat/tests/unit/.../test_chat_orchestrator_execute_sync.py` — confirms error-event → exception mapping for execute_sync.
- `services/rag-chat/tests/unit/.../test_tool_registry_definitions.py` — confirms tool schemas line up with capability_manifest.yaml.

**Gaps** (not findings; tests-to-add for beta):
- No test for `BriefArchiveWriteAdapter` task GC under loop pressure (F-DS-001).
- No test for protocol mixing during rebalance (F-DS-002).
- No test for SSE client-disconnect mid-stream (F-DS-003).
- No test asserting that `BackpressurePolicy` is wired in production consumer mains (F-DS-006).

---

## Beta deployment verdict

**Conditional GO.**

Block on F-DS-002 if rolling restarts are part of the deployment model. Mitigate F-DS-001 with the class-level task set — it's a 5-line change. The remaining findings are acceptable for the demo window provided the operator runbook captures:
- DeepInfra outage → KG narratives go template; this is a known degraded state (not a bug).
- Schema Registry must be re-registered before deploying the source_name change (D-INIT-6).
- Single-tenant demo only; do not expose the dedup keys to a hostile tenant.

---

**Reviewed**: 17 commits (4f9662a3..2b359f73)
**Files inspected**: 24
**Time**: ~75 min
