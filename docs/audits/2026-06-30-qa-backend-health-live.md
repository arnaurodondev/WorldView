# Backend Health & Pipeline Sweep — Live QA

**Date:** 2026-06-30 (log timestamps 2026-07-01 UTC)
**Scope:** Read-only. Docker Compose project `worldview`. Post DeepInfra key-rotation + force-recreate of rag-chat, api-gateway, all knowledge-graph-*, all nlp-pipeline-*.
**Verdict:** Platform is healthy. ML pipeline is confirmed working post-key-rotation (DeepInfra 200 OK across embedding, extraction, relevance-scoring, unresolved-resolution). One unhealthy container (kafka connectivity probe), plus a small set of pre-existing / latent issues. No new crash loops. No fixes applied.

---

## 1. Container health

**Freshly recreated services all started cleanly (0 restarts):**

| Service | Started | Restarts | State |
|---|---|---|---|
| rag-chat | 04:31 | 0 | healthy, `Application startup complete.` |
| api-gateway | 04:33 | 0 | healthy, service-token 200 OK |
| knowledge-graph (+ all 15 consumers) | 04:36 | 0 | all healthy |
| knowledge-graph-path-insight-worker | 04:36 | 0 | healthy, **crash-loop history resolved** (finding paths: 7/2/3/11 per job) |
| nlp-pipeline (+ all consumers/workers) | 04:38–04:42 | 0 | all healthy |

**Problem containers:**

| Container | Status | Assessment |
|---|---|---|
| `worldview-alert-intelligence-consumer-1` | **Up 38h (unhealthy)** | THE 1 unhealthy container — see §2 |
| `worldview-intelligence-migrations-1` | Exited (255) 38h ago | Latent migration-history break — see §3 (I-1) |
| `worldview-alert-rule-poller-1` | Exited (137) 40h ago | SIGKILL/OOM, never restarted — see §3 (I-2) |
| `unit_*` (backend/kafka/vault/watcher) | Exited 7d ago | Unrelated non-worldview stack; ignore |
| `*-migrate-1`, `*-init-1`, bundle-prewarmer | Exited (0) | One-shot jobs, completed normally; expected |

Everything else (portfolio, market-data, market-ingestion, content-store, content-ingestion, alert core, observability stack, worldview-web) is **Up/healthy**.

---

## 2. The unhealthy container: `alert-intelligence-consumer`

**Root cause:** The container's Docker healthcheck is a **kafka connectivity probe** that persistently times out talking to the broker (`kafka:29092`). `FailingStreak: 2186`, every probe `ExitCode 1` for ~38h.

Log signature (continuous):
```
%4|REQTMOUT|rdkafka#consumer-1| kafka:29092/1: Timed out ListOffsetsRequest / FetchRequest / ApiVersionRequest in flight
%4|SESSTMOUT| Consumer group session timed out ... revoking assignment and rejoining group
kafka_connectivity_probe_failed  error=KafkaError{_TIMED_OUT}/_TRANSPORT "Failed to get metadata: Local: Timed out"
```

**Functional impact: LOW.** Despite the probe failing, the consumer is still the live member of `alert-service-group` (rdkafka-ac1a80c5 @ 172.20.0.61) and **lag is 0 on all its partitions** (`nlp.signal.detected.v1` p0/1/2 and `graph.state.changed.v1` p0). So it has drained its topics; it is not dropping work right now. The failure is the dedicated liveness probe (and the health flag), not message processing.

**Likely cause:** A stale/half-open rdkafka connection on this one consumer — repeated metadata/ApiVersion timeouts to the broker while every other consumer on the same broker is fine. A restart of just this container would almost certainly clear it. This is the same class as the broker GC-freeze / connectivity-wedge patterns previously seen (BP-705/706), scoped to a single consumer here. **Recommend: restart `worldview-alert-intelligence-consumer-1`** (out of scope for this read-only pass).

---

## 3. Ranked real errors / issues

| # | Sev | Service | Issue | Freq | Likely cause |
|---|-----|---------|-------|------|--------------|
| I-1 | **Medium** | intelligence-migrations | Alembic `Can't locate revision identified by '0063'` → FAILED (exit 255) | one-shot, 38h ago | Migration-history mismatch: DB `alembic_version` points at `0063` but no such revision file in the image. Not blocking now (services healthy on existing schema) but **the next intelligence_db migration run will fail**. Needs reconciliation of the intelligence-migrations revision chain vs DB `alembic_version`. |
| I-2 | **Medium** | alert-rule-poller | Exited (137) 40h ago, never restarted; last logs show tick jobs then SIGKILL | one-shot | SIGKILL (137) — OOM or manual stop during a recreate/compose-down. **Alert rule polling is currently NOT running.** Confirm intended; if not, `docker compose up -d` this service. (Possible profile/recreate no-op — cf. compose-profile-recreate gotcha.) |
| I-3 | Low-Med | rag-chat → api-gateway | `GET /v1/signals/prediction-markets` → **401 Unauthorized** | 1 in 35m | The chat prediction-markets tool call reaches the gateway without a valid user/internal JWT for that route. Functional: the chat prediction-market tool fails auth. Ties into the known prediction-markets defect cluster (news-momentum investigation). |
| I-4 | Low | synthetic-monitor → api-gateway | `GET /v1/quotes/019000...1001` → **401 Unauthorized** | 10 in 35m | Synthetic monitor probes an auth-required quote endpoint without a token. Recurring but benign (monitor mis-scope / expected probe); no user impact. |
| I-5 | Low | market-data-fundamentals | Consumer group lag ~1169 on `market.dataset.fetched`, effectively static (1170→1169) | steady | Slow/idle drain of a large backlog topic (199,890 msgs); not growing. Cosmetic unless fundamentals freshness matters. |

**No tracebacks, CRITICALs, PROVIDER_UNAVAILABLE, or api_error** found in rag-chat, nlp-pipeline (relevance-scoring / unresolved-resolution / embedding / article-consumers), knowledge-graph (enriched/entity/scheduler/path-insight), content-store, content-ingestion, or market-data over the last ~35m. The 401s above are the only recurring app-level errors; everything else is transient startup noise (OIDC discovery skipped by design: `OIDC_DISCOVERY_OPTIONAL=true`).

---

## 4. ML pipeline — CONFIRMED HEALTHY post-key-rotation

DeepInfra is returning 200 OK across the board (no 401s):

- **Embedding**: `embedding_deepinfra_adapter_selected` model `BAAI/bge-large-en-v1.5` @ deepinfra.
- **Extraction**: `extraction_deepinfra_adapter_selected` model `openai/gpt-oss-120b` (fallback `gpt-oss-20b`) @ deepinfra.
- **Relevance-scoring**: repeated `POST .../chat/completions 200 OK`; `relevance_scoring_cycle_done articles_scored=50`, batches of 50 flowing.
- **Unresolved-resolution**: repeated `POST .../chat/completions 200 OK`.
- **Enriched-consumer**: processing articles (`enriched_article_processed`) with 0 errors.

**Note (not a key issue):** extraction is emitting `relations: 0` on the few articles processed in the last 3h. This is throughput, not failure — only 2–3 new articles arrived (EODHD `new: 2` — most of today's news already ingested). EODHD news fetch is **live and 200 OK** (`eodhd_fetch_complete`, `sec_edgar_fetch_complete`), so the previously-dead-key ingestion halt is cleared. Relation extraction will be visible again as fresh multi-entity articles flow.

**path-insight-worker:** stable, 0 restarts, actively discovering paths — the DNS/perf crash-loop history is resolved.

---

## 5. Kafka consumer-group lag

Broker `worldview-kafka-1` healthy. All groups current or trivially behind:

| Group | Topic | Lag | Note |
|---|---|---|---|
| alert-service-group | nlp.signal.detected / graph.state.changed | **0** | consumer container unhealthy (probe) but fully caught up |
| content-store-consumer / dedup-consumer | content.article.* | 0 | healthy |
| kg-service-group-enriched / entity / temporal | nlp.article.enriched / entity.canonical | 0 / 2 / 0 | healthy |
| kg-*-dataset-group (earnings/econ/insider/macro/fundamentals) | market.dataset.fetched | 0 | at 199,890, drained |
| kg-provisional-queued-group | entity.provisional.queued | **28** | small, draining |
| nlp-pipeline-group | content.article.stored | **33–46** per partition | small; consumers recreated 3m ago, catching up |
| market-data-fundamentals | market.dataset.fetched | **1169** | static backlog (I-5) |
| market-data-* (ohlcv/quotes/insider/intraday/prediction) | — | 0 | healthy |

**No badly backed-up or stuck groups.** The only non-trivial lag (market-data-fundamentals, 1169) is static, not growing. nlp-pipeline small lag is post-recreate catch-up and will clear.

**FTS consumers:** nlp-pipeline-1 (search API) healthy; article-consumer-0/1 healthy and consuming (lag 33–46, draining). Confirmed processing.

---

## 6. Recommended follow-ups (not applied — report only)

1. Restart `alert-intelligence-consumer` to clear the wedged rdkafka probe connection and the unhealthy flag.
2. Reconcile intelligence-migrations revision chain vs DB `alembic_version` (missing rev `0063`) before the next intelligence_db migration.
3. Confirm whether `alert-rule-poller` being down is intentional; if not, bring it back up.
4. Investigate rag-chat's prediction-markets tool 401 (auth/token propagation for that gateway route) — part of the known prediction-markets defect cluster.
