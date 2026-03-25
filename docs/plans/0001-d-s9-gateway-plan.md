---
id: PLAN-0001-D
prd: PRD-0001
title: "S9 API Gateway: External Ingestion + Intelligence Query Proxy"
status: draft
created: 2026-03-25
updated: 2026-03-25
plans: 1
waves: 2
tasks: 8
---

# PLAN-0001-D: S9 API Gateway — Intelligence Routes

## Overview

**PRD Reference**: [PRD-0001](../specs/0001-intelligence-pipeline.md) — §6.2.5
**Goal**: Add external content ingestion endpoints and intelligence/content query proxy routes to S9. This enables external webhook receivers, manual content submission, and frontend access to intelligence data — all through the unified gateway.
**Total Scope**: 1 plan, 2 waves, 8 tasks
**Depends on**: PLAN-0012 (S4+S5 operational) + PLAN-0013 Sub-Plans C+D (S6+S7 API available)

---

## Plan Dependency Graph

```
PLAN-0012 (S4 operational) ──→ Wave 1: Ingestion routes (proxy to S4)
PLAN-0013 Sub-Plan C+D ──→ Wave 2: Intelligence routes (proxy to S6+S7)
```

Wave 1 can start as soon as S4 has its API endpoints. Wave 2 requires S6+S7 APIs.

---

### Wave 1: S9 External Ingestion Routes

**Goal**: Add ingestion endpoints to S9 — content submission, webhook receiver, source management proxy, and pipeline status proxy. All route to S4 internal API.
**Depends on**: PLAN-0012 Wave A-3 (S4 API operational)
**Estimated effort**: 30–45 minutes
**Architecture layer**: API

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-D-1-01 | Ingestion proxy routes | impl | `services/api-gateway/src/gateway/routes/ingest.py` | 5 routes: `POST /api/v1/ingest/submit` (proxy to S4 internal submit, auth required, 10 req/min rate limit), `POST /api/v1/ingest/webhook/{source_type}` (webhook secret validation per-source), `GET /api/v1/ingest/sources` (proxy to S4), `GET /api/v1/ingest/status` (proxy to S4), `POST /api/v1/ingest/sources/{source_id}/trigger` (proxy to S4) |
| T-D-1-02 | Webhook secret validation | impl | `services/api-gateway/src/gateway/middleware/webhook_auth.py` | Per-source webhook secrets via `WEBHOOK_SECRET_{SOURCE_TYPE}` env vars; `X-Webhook-Secret` header validation; 401 on invalid |
| T-D-1-03 | Unit tests for ingestion routes | test | `services/api-gateway/tests/unit/routes/test_ingest.py` | ≥8 tests: submit auth required, submit rate limited, webhook valid/invalid secret, source proxy, status proxy, trigger proxy, submit validates url/raw_content constraint |

#### Validation Gate
- [ ] `ruff check services/api-gateway/` passes
- [ ] `mypy services/api-gateway/src/ --config-file mypy.ini` passes
- [ ] ≥8 unit tests pass
- [ ] Rate limit: 10 req/min on submit endpoint verified

---

### Wave 2: S9 Intelligence + Content Query Routes

**Goal**: Add intelligence and content query proxy routes with Valkey caching. These enable the future frontend to query entities, relations, signals, and articles through S9.
**Depends on**: Wave 1 + PLAN-0013 Waves C-4 + D-4 (S6+S7 APIs operational)
**Estimated effort**: 30–45 minutes
**Architecture layer**: API

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-D-2-01 | Content query routes | impl | `services/api-gateway/src/gateway/routes/content.py` | 2 routes: `GET /api/v1/content/articles` (proxy to S5, cache 1min), `GET /api/v1/content/articles/{doc_id}` (proxy to S5) |
| T-D-2-02 | Intelligence query routes | impl | `services/api-gateway/src/gateway/routes/intelligence.py` | 7 routes per PRD §6.2.5: entities/{id}, entities/{id}/articles, entities/{id}/relations, signals, search (vector), graph/neighborhood (cache 2min), graph/relations, graph/stats (cache 10min) |
| T-D-2-03 | Valkey caching layer | impl | `services/api-gateway/src/gateway/middleware/cache.py` | Cache configuration per PRD §6.2.5: `gw:v1:entity:{id}` TTL 5min, `gw:v1:graph:nbr:{id}:{depth}:{hash}` TTL 2min, `gw:v1:graph:stats` TTL 10min, `gw:v1:articles:{query_hash}` TTL 1min; cache-aside pattern; fail-open (Valkey unavailable → skip cache, don't block) |
| T-D-2-04 | Route registration + docs update | impl | `services/api-gateway/src/gateway/main.py`, `services/api-gateway/.claude-context.md` | Register all new routes in main.py; update .claude-context.md with new endpoints |
| T-D-2-05 | Unit tests for intelligence routes + caching | test | `services/api-gateway/tests/unit/routes/test_intelligence.py` | ≥10 tests: each route proxies correctly, cache hit returns cached, cache miss fetches upstream, cache TTLs match spec, Valkey unavailable → fail-open |

#### Validation Gate
- [ ] `ruff check services/api-gateway/` passes
- [ ] `mypy services/api-gateway/src/ --config-file mypy.ini` passes
- [ ] ≥18 total tests pass across both waves
- [ ] All routes respond with correct proxy behavior
- [ ] Cache TTLs match PRD §6.2.5 specification

---

## Tracking

| Wave | Status | Tasks Done | Tasks Total | Blockers |
|------|--------|-----------|-------------|----------|
| 1 | pending | 0 | 3 | PLAN-0012 Wave A-3 |
| 2 | pending | 0 | 5 | Wave 1 + PLAN-0013 Waves C-4, D-4 |
