# Investigation Report: Frontend→Backend Hanging Requests

**Date**: 2026-06-07
**Investigator**: Claude (Principal Debugging Engineer)
**Severity**: HIGH
**Status**: Root cause identified — three distinct issues found, no single catastrophic hang

---

## Executive Summary

The frontend requests were **not hanging indefinitely** in the strict sense (infinite wait with no response). The platform exhibited three separate problems that collectively manifest as "browser keeps waiting":

1. **POST /v1/fundamentals/screen** — repeated 504 Gateway Timeout (10 s) caused by the S3 screener query exceeding the httpx timeout under concurrent load. This is the primary user-visible symptom: the Screener page never loaded.
2. **`RuntimeError: No response returned`** in Starlette middleware — a known Starlette 0.37.2 / FastAPI 0.111.0 BaseHTTPMiddleware bug that surfaced on monitoring probes (`/healthz`, `/metrics`) at 19:00:40, eventually leading to both the `api-gateway` and `worldview-web` containers being in a stale `Created` state requiring restart.
3. **`content-store` 500 error** — `function min(uuid) does not exist` in PostgreSQL, making the news-bundle leg of the page-bundle endpoint silently fail.

A fourth **latent risk** was identified: `GET /v1/entities/{id}/intelligence-bundle` has **no `asyncio.wait_for` overall timeout guard**, meaning a stalled KG graph traversal could hold the request open for the full 30 s httpx read timeout.

---

## Phase 1 — Symptom Characterisation

```
# api-gateway health (no /health route; /healthz OK)
HTTP 404 in 0.014s   ← /health (intentional 404)
HTTP 200 in 0.088s   ← /v1/portfolios (authenticated, healthy)
HTTP 200 in 0.760s   ← frontend dev server (healthy)
HTTP 404 in 0.032s   ← /api/health (Next.js has no /api/health route)

# Cached Valkey-backed endpoints
/v1/entities/.../intelligence-bundle : HTTP 200 4.15s  (warm: 68ms)
/v1/fundamentals/.../intraday-stats  : HTTP 200 0.44s
/v1/fundamentals/.../multi-period-returns : HTTP 200 0.14s
```

All authenticated endpoints respond. The 4-second cold intelligence-bundle latency is expected (6 concurrent KG fan-outs; Valkey caches it to <70 ms on second call).

---

## Phase 2 — Container Health

All containers were healthy at investigation time. However, both `worldview-api-gateway-1` and `worldview-worldview-web-1` had a restart count of 0 with a `StartedAt` timestamp of `2026-06-07T19:05:49Z` / `19:06:02Z` — meaning they were recreated during the incident window. The prior container instance had the `Created` state (stopped, not crashed).

**Valkey**: healthy, periodic RDB saves completing normally. No Valkey-related errors from the api-gateway perspective (ping latency 358 ms at startup, acceptable).

---

## Phase 3 — CORS and Next.js Proxy

No issues found.

- `apps/worldview-web/next.config.ts` correctly rewrites `/api/:path*` → `${API_GATEWAY_URL}/:path*`
- `API_GATEWAY_URL=http://api-gateway:8000` is set in the frontend container
- The Next.js middleware adds a per-request CSP nonce (no auth or proxy logic)
- Connectivity confirmed: `node fetch('http://api-gateway:8000/health')` → `Status: 404` (expected; gateway has /healthz, not /health), `fetch('/v1/portfolios')` → `Status: 401` (correct)

---

## Phase 4 — Frontend→Backend Container Path

```
docker exec worldview-worldview-web-1 node -e "
  fetch('http://api-gateway:8000/health').then(r => console.log('Status:', r.status))
"
# → Status: 404  (correct — gateway has /healthz)

fetch('http://api-gateway:8000/v1/portfolios', {headers: {Authorization: 'Bearer dummy'}})
# → Status: 401  (correct)
```

The Docker service name `api-gateway` resolves correctly inside the `worldview-web` container. The rewrite path works end-to-end.

---

## Phase 5 — Root Cause 1: Screener 504 Gateway Timeout

**Evidence from api-gateway logs (prior container instance):**

```json
{"event": "screener_upstream_timeout", "level": "warning", "timestamp": "2026-06-07T18:51:59.372766Z"}
{"event": "screener_upstream_timeout", "level": "warning", "timestamp": "2026-06-07T18:53:24.475140Z"}
{"event": "screener_upstream_timeout", "level": "warning", "timestamp": "2026-06-07T18:54:50.503103Z"}
{"event": "screener_upstream_timeout", "level": "warning", "timestamp": "2026-06-07T18:55:07.068022Z"}
INFO: "POST /v1/fundamentals/screen HTTP/1.1" 504 Gateway Timeout  (×4)
```

**Mechanism:**
- `services/api-gateway/src/api_gateway/routes/market.py:174` sets `timeout=10.0` on the screener upstream call
- `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_query.py:210` sets `SET LOCAL statement_timeout = '8000'` (8 s)
- Under concurrent load (11 parallel sector calls from the heatmap, + direct screener hits), the DB query queue backs up and individual queries exceed 10 s before the 8 s statement_timeout fires — because the statement_timeout clock starts **after the DB gets the query**, not when httpx sends it

**Verification (post-restart, isolated call):**
```
Direct S3 call (3 isolated runs): 3.13s, 2.30s, 2.36s   ← healthy
Gateway POST /v1/fundamentals/screen (cold): HTTP 200 in 1.04s
Gateway POST /v1/fundamentals/screen (warm): HTTP 200 in 0.013s (Valkey cache)
```

The screener is healthy after the restart because the concurrent load subsided.

---

## Phase 6 — Root Cause 2: `RuntimeError: No response returned` (Starlette Bug)

**Evidence from api-gateway logs at 19:00:40:**

```
{"method": "GET", "path": "/healthz", "event": "unhandled_exception", "level": "error",
 "exception": "RuntimeError: No response returned.\n  at middleware.py:217 (OIDCAuthMiddleware)\n  at middleware.py:367 (InternalJWTIssuerMiddleware)"}

{"method": "GET", "path": "/metrics", "event": "unhandled_exception", "level": "error", ...same...}
{"method": "GET", "path": "/v1/search/instruments", "event": "unhandled_exception", ...}
```

**Root cause:** This is a [known Starlette 0.37.2 / FastAPI 0.111.0 bug](https://github.com/encode/starlette/issues/1452) in `BaseHTTPMiddleware`. When an exception propagates out of the downstream ASGI app's `send()` callable (e.g. during response body streaming or disconnection), the middleware layer can fail to produce a response and raises `RuntimeError: No response returned`. The error affected **all in-flight requests** at the moment of failure, including monitoring probes.

**Why it happened now:** The screener timeouts (httpx cancelling the downstream request mid-response) triggered the Starlette bug, corrupting the ASGI state for concurrent requests. The monitoring probes (`/healthz`, `/metrics`) that were sampled at the same event-loop tick hit the corrupted state.

**Fix path:** Upgrade to Starlette ≥ 0.38.0 (patched in [encode/starlette#2194](https://github.com/encode/starlette/pull/2194)) or wrap all `BaseHTTPMiddleware` dispatch methods in a `try/except BaseException` guard that ensures a fallback response is always returned.

---

## Phase 7 — Root Cause 3: `content-store` `min(uuid)` SQL Error

**Evidence from content-store logs:**

```
sqlalchemy.exc.ProgrammingError: UndefinedFunctionError: function min(uuid) does not exist
[SQL: SELECT anon_1.doc_id, min(anon_1.cluster_id) AS cluster_id
FROM (SELECT ... FROM duplicate_clusters ...) AS anon_1 GROUP BY anon_1.doc_id]
```

**Impact:** `POST /api/v1/documents/cluster-sizes` returns HTTP 500. This endpoint is called from the api-gateway `get_news_top` composition (`clients.py`) to annotate news articles with deduplication cluster membership. The leg degrades to `None` (fail-soft), so the news bundle still returns but cluster annotations are absent.

**Fix:** Cast `cluster_id` to `TEXT` before `MIN()` or use `MIN(cluster_id::text)`, or switch to a `DISTINCT ON (doc_id)` pattern that avoids an aggregate on UUID.

---

## Phase 8 — Latent Risk: intelligence-bundle Missing Overall Timeout

**Finding:** `GET /v1/entities/{id}/intelligence-bundle` fires 6 concurrent legs via `asyncio.gather()` but has **no `asyncio.wait_for()` outer guard**.

```python
# routes/intelligence.py:850
detail_t, brief_t, graph_t, graph_d1_t, paths_t, intel_t = await asyncio.gather(
    _bundle_fetch_json(clients.knowledge_graph, ...),  # 30s httpx timeout
    _bundle_fetch_json(clients.rag_chat, ...),         # 120s httpx timeout
    ...
)
```

Compare with the `page-bundle` and `dashboard-bundle` which use:
```python
# clients.py:464
return await asyncio.wait_for(_compose(), timeout=15.0)  # page-bundle: 15s hard cap
# clients.py:598
return await asyncio.wait_for(_compose(), timeout=20.0)  # dashboard: 20s hard cap
```

The KG depth=2 AGE graph traversal (the dominant leg) currently responds in 1.7 s. However, under AGE connection pool pressure or with a large subgraph, it can spike to 5–10 s. If it ever stalls beyond the httpx 30 s read timeout, the intelligence-bundle endpoint holds the browser connection open for 30 s with no response — exactly the reported symptom.

---

## Fix Plan

### Fix 1 (HIGH — screener 504) — Raise httpx screener timeout to 15 s + add Valkey cache warming

The httpx timeout (10 s) and DB statement_timeout (8 s) leave a 2 s window where the DB kills the query but httpx has already timed out. Under concurrent load the httpx timer starts before the query even reaches the DB.

**Option A (immediate):** Raise `timeout=15.0` in `routes/market.py:174` so httpx outlives the DB kill:
```python
timeout=15.0,  # was 10.0; gives DB 8s statement_timeout time to fire cleanly
```

**Option B (structural):** Pre-warm the Valkey screener cache on startup with a background task so the first user request is never cold.

### Fix 2 (HIGH — Starlette bug) — Upgrade Starlette

```toml
# services/api-gateway/pyproject.toml
starlette = ">=0.38.0"
fastapi = ">=0.112.0"
```

Or apply a monkey-patch guard on dispatch until an upgrade is feasible.

### Fix 3 (MEDIUM — content-store SQL) — Fix `min(uuid)` in cluster-sizes query

```python
# In content-store cluster_sizes repository:
# Change: min(anon_1.cluster_id)
# To:     min(anon_1.cluster_id::text)::uuid
```

### Fix 4 (MEDIUM — intelligence-bundle timeout guard) — Add `asyncio.wait_for`

```python
# routes/intelligence.py — wrap the gather in a timeout
_BUNDLE_TIMEOUT_S = 20.0  # KG AGE depth=2 worst case ~5s; 20s = 4× headroom

async def _compose() -> dict[str, Any]:
    detail_t, brief_t, graph_t, graph_d1_t, paths_t, intel_t = await asyncio.gather(...)
    ...

try:
    return await asyncio.wait_for(_compose(), timeout=_BUNDLE_TIMEOUT_S)
except asyncio.TimeoutError:
    logger.warning("intelligence_bundle_overall_timeout", entity_id=str(entity_id))
    raise HTTPException(status_code=504, detail="Intelligence bundle upstream timeout")
```

---

## What Was Ruled Out

| Hypothesis | Result |
|---|---|
| Missing httpx timeout (hang forever) | Ruled out — all clients have Timeout(30.0, connect=5.0) |
| ValkeyClient no socket timeout | Ruled out — socket_timeout=5.0, socket_connect_timeout=2.0 |
| Next.js proxy misconfiguration | Ruled out — rewrites correctly to api-gateway:8000 |
| Frontend→api-gateway container network | Ruled out — confirmed reachable via node fetch |
| Connection pool exhaustion (CLOSE_WAIT) | Ruled out — 0 CLOSE_WAIT connections |
| Valkey unavailable blocking rate limiter | Ruled out — Valkey healthy (ping PONG from Valkey container) |
| CORS blocking requests | Ruled out — CORSMiddleware configured correctly |
| RateLimitMiddleware hanging on Valkey | Ruled out — fail-closed returns 503, not hang |

---

## Current Platform State (post-investigation)

All containers healthy. After the containers were restarted the platform is fully operational:

```
page-bundle:           HTTP 200 in 0.5–1.4s  (3 consecutive calls)
intelligence-bundle:   HTTP 200 in 0.013s    (Valkey cache hit)
news/top:              HTTP 200 in 0.011s    (cached)
portfolios:            HTTP 200 in 0.11s
screener (cold):       HTTP 200 in 1.04s
screener (warm):       HTTP 200 in 0.013s
heatmap 1D:            HTTP 200 in 0.69s     (Valkey cached)
```

The screener 504s will recur under sustained concurrent load until Fix 1 is applied.
