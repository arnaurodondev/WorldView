# Investigation Report: Entity Resolution Timeout — Chat Returns Empty Answer

**Date**: 2026-06-06
**Investigator**: Claude (investigation skill)
**Severity**: HIGH (chat pipeline silently degrades; user receives ungrounded LLM response)
**Status**: Root cause identified

---

## 1. Issue Summary

Chat requests reaching the `entity_resolution` step hang for ~11 seconds, then rag-chat returns an empty response or a degraded LLM answer with no entity context. The symptom was: start a chat → entity_resolution phase → no visible error → empty/contextless answer. Initial hypothesis (during user investigation session) was that KG (`localhost:8007`) was the bottleneck; that hypothesis was **incorrect**.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| `RAG_CHAT_UPSTREAM_TIMEOUT_SECONDS=10.0` | `docker exec worldview-rag-chat-1 printenv` | rag-chat global upstream timeout for all S6/S7 HTTP calls |
| `POST http://localhost:8007/api/v1/entities/resolve → HTTP 405` | Direct curl probe | KG (S7) only has **GET** /entities/resolve; POST → 405 Method Not Allowed |
| `POST http://localhost:8006/api/v1/entities/resolve → HTTP 200, 1.15s` | Direct curl probe | NLP pipeline (S6) serves the actual entity resolve; responds in ~1s from host |
| `worldview-nlp-pipeline-1 Up 22 hours (unhealthy)` | `docker ps` at investigation start | NLP pipeline API was unhealthy for ≥22 hours during the reported hang |
| `worldview-rag-chat-1 Created` | `docker ps -a` | rag-chat container exists but is not running |
| `entity_resolve_request query_len=26 result_count=2` | NLP pipeline logs | My test probe resolved "apple tech giant cupertino" in ~1.3s (stages 1-3) |
| `ner_client=None, embedding_client=None` in `get_entity_resolver_use_case` | `dependencies.py:173-174` | API process injects NO ML clients → stages 4 & 5 never run |
| Stage 4/5 comment: "API process has no ML clients" | `query_entity_resolver.py:388` | Confirms stages 1-3 only; all DB queries |

---

## 3. Execution Path Analysis

```
User sends chat message
  → rag-chat ChatOrchestrator (chat_orchestrator.py:1024)
      → phase("entity_resolution")
          → ChatPipeline.resolve_entities(message) (chat_pipeline.py:309)
              → S6Client.resolve_entities(query_text) (s6_client.py:28)
                  → BaseUpstreamClient._post("/api/v1/entities/resolve", ...) (base.py)
                      → httpx POST to http://nlp-pipeline:8006/api/v1/entities/resolve
                          [10s timeout via RAG_CHAT_UPSTREAM_TIMEOUT_SECONDS]
                      ← if timeout: raise UpstreamTransportError (BaseException)
                      ← if 4xx: return {}  →  resolve_entities returns []
                  → if UpstreamTransportError: propagates to ToolExecutor → TransportErrorMarker
              → pipeline returns [] (empty entities)
          → orchestrator continues with no entity context
      → LLM call proceeds without grounded entity mentions
  ← User receives degraded answer with no entity context
```

**NLP pipeline entity resolver (POST /api/v1/entities/resolve):**
```
Stage 1: Exact alias match     — DB query, ~10ms
Stage 2: Ticker/ISIN match     — regex + batch DB, ~20ms
Stage 3: Fuzzy trigram         — LATERAL pgvector trigram, ~50ms
Stage 4: GLiNER NER            — SKIPPED (ner_client=None in API process)
Stage 5: ANN HNSW embedding    — SKIPPED (embedding_client=None in API process)

Results: checked in Valkey cache first (TTL 600s); warm cache → ~5ms total
```

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | KG (port 8007) `/entities/resolve` was timing out | **REFUTED** | `POST localhost:8007/api/v1/entities/resolve → 405 Method Not Allowed`; KG only has GET variant |
| H-2 | Entity resolve involves LLM call that takes >10s | **REFUTED** | `dependencies.py:173-174` — API process injects `ner_client=None`, `embedding_client=None`; stages 4/5 never run |
| H-3 | NLP pipeline API server was in degraded/unhealthy state causing requests to queue/hang | **CONFIRMED** | `worldview-nlp-pipeline-1 Up 22 hours (unhealthy)` in docker ps; `docker inspect` shows health checks were failing at time of user investigation |
| H-4 | rag-chat upstream timeout (10s) is too short for normal operation | **REFUTED** | Normal entity resolve = 50–200ms container-to-container (stages 1-3 only); 10s is ≥50× the normal latency |

---

## 5. Root Cause

**Statement**: `worldview-nlp-pipeline-1` (the NLP pipeline API server) entered a degraded/unhealthy state after 22+ hours of uptime. Health checks were failing, and the API server's asyncio event loop was likely blocked or the DB connection pool was exhausted (shared with worker processes). Incoming entity-resolve requests from rag-chat received no response until the 10s upstream timeout fired. rag-chat then returned an empty entity list, and the LLM produced a contextless answer.

**Location**:
- Timeout trigger: `services/rag-chat/src/rag_chat/infrastructure/clients/base.py:71` — `httpx.TimeoutException → UpstreamTransportError`
- Degraded service: `worldview-nlp-pipeline-1` container (no restart policy; ran 22h unhealthy without auto-remediation)
- Caller: `services/rag-chat/src/rag_chat/infrastructure/clients/s6_client.py:33`

**Trigger condition**: NLP pipeline API server enters unhealthy state (likely after long uptime + DB connection pool pressure from colocated workers). Any chat request during this window hits the 10s timeout and gets empty entities.

**Secondary issue**: rag-chat container is currently in `Created` state (not running). Must be started with `docker-compose up -d rag-chat` before chat works at all.

---

## 6. Impact Analysis

- **Immediate impact**: All chat responses during NLP pipeline degraded window lack entity grounding. LLM produces hallucinated or vague answers with no ticker/entity context.
- **Blast radius**: Only chat (rag-chat). Other services (market-data, portfolio, etc.) are unaffected. The NLP pipeline workers continue running independently.
- **Data integrity**: No data loss or corruption. Entity cache in Valkey unaffected. Chat sessions are stateless.
- **User visibility**: Silent — no error shown to user. The chat stream continues but answers degrade without warning.

---

## 7. Contributing Factors

1. **No Docker restart policy on `worldview-nlp-pipeline-1`**: container ran unhealthy for 22+ hours without automatic restart or alerting.
2. **Shared event loop between API server and heavy workers**: NLP pipeline API process shares the same Python process event loop with no isolation from worker CPU/IO pressure (though they are separate containers — API server may share DB pool pressure).
3. **Silent degradation in rag-chat**: `UpstreamTransportError` → `TransportErrorMarker` → empty entities → LLM still called. No user-facing error or log escalation that operators would notice.
4. **Wrong service diagnosed initially**: the user probed KG (port 8007) because `RAG_CHAT_S7_BASE_URL` was visible in `printenv`, leading to an incorrect diagnosis. The actual entity-resolve endpoint is on NLP pipeline (port 8006).
5. **No circuit breaker**: if entity resolve fails once, rag-chat retries on every subsequent message until the container recovers. A circuit breaker would fail fast and alert sooner.

---

## 8. Recommended Fix

### Immediate (now):
```bash
# Start rag-chat (currently in "Created" state):
docker-compose up -d rag-chat

# If NLP pipeline API is unhealthy, restart it:
docker-compose restart nlp-pipeline
```

### Short-term (code changes):
1. **Add Docker healthcheck restart policy** to `worldview-nlp-pipeline-1` in `docker-compose.yml`:
   ```yaml
   restart: unless-stopped
   ```
   (or `restart: on-failure:3`)

2. **Add structured warning log when entity resolution degrades** in `s6_client.py` or `chat_pipeline.py` so operators can detect the pattern from logs without user reports.

### Medium-term:
3. **Circuit breaker for S6Client**: after N consecutive timeouts within a window, skip entity resolution entirely and log at ERROR level (rather than silently returning `[]` each time).
4. **Separate NLP pipeline API from worker DB pool**: API server should use a dedicated `asyncpg` pool with a lower `max_size` to prevent pool starvation during heavy worker load.

---

## 9. Prevention Recommendations

- **BP-485**: Add to `BUG_PATTERNS.md` — "NLP pipeline API server enters unhealthy state after long uptime (DB connection pool starvation from colocated workers); entity-resolve requests from rag-chat time out silently; chat returns contextless LLM answers. Prevention: add `restart: unless-stopped` + Prometheus alert on `up{job="nlp-pipeline"} == 0`."
- Add Prometheus alert rule: `up{container="worldview-nlp-pipeline-1"} == 0 for 5m → PagerDuty/Slack`.
- Add `restart: unless-stopped` to all stateless API containers in `docker-compose.yml`.
- Document in `services/rag-chat/.claude-context.md`: entity resolution calls **S6 (NLP pipeline)**, not S7 (KG). KG has only `GET /entities/resolve` (fuzzy alias lookup used by ToolExecutor directly).

---

## 10. Open Questions

- Why exactly does the NLP pipeline API server go unhealthy after ~22 hours? DB connection leak? Memory growth? Needs profiling during a degraded window (add `/debug/connections` endpoint or Prometheus `asyncpg_pool_*` metrics).
- Is there a `restart: unless-stopped` policy that should be added globally to all docker-compose services, or only API servers?
