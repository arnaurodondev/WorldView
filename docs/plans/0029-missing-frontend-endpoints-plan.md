# PLAN-0029 — Missing Frontend Endpoints

> **PRD**: PRD-0028 §6.2 (route gaps identified by investigation)
> **Created**: 2026-04-18
> **Updated**: 2026-04-19
> **Status**: completed

---

## Overview

The PRD-0028 frontend investigation identified 3 endpoint gaps and 1 stub that must be resolved before the frontend can be feature-complete. This plan addresses all 4 items across 3 services (S1 Portfolio, S8 RAG/Chat, S9 API Gateway).

### Codebase State (verified from code)

| PRD Reference | Type | Service | Current State | Required State | Delta |
|--------------|------|---------|---------------|----------------|-------|
| `PATCH /v1/watchlists/:id` | endpoint | S1 + S9 | S1: no rename endpoint; S9: TODO comment at proxy.py:814 | PATCH route + use case | **new use case + route + proxy** |
| `GET /api/v1/briefings/morning` | endpoint | S8 + S9 | S8: only `POST /internal/v1/briefings`; S9 proxy exists (proxy.py:692) | public GET route in S8 | **new route in S8** (S9 already done) |
| `GET /api/v1/briefings/instrument/:id` | endpoint | S8 + S9 | S8: no GET route; S9 proxy exists (proxy.py:713) | public GET route in S8 | **new route in S8** (S9 already done) |
| `GET /v1/signals/ai` | endpoint | S9 | S9: stub returns `{"signals":[], "total":0}` (proxy.py:992); `nlp_pipeline` client exists and is wired in app.py:131 | real proxy to S6 `GET /api/v1/signals` | **replace stub with proxy** |

### Dependency Graph

```
Wave 1 (S1 + S9: Watchlist rename + Signals proxy fix)  — no deps
Wave 2 (S8: Briefing GET endpoints)                      — no deps
         ↓
Both waves independent — can run in parallel
```

### Wave Summary

| # | Wave | Status | Depends On | Effort |
|---|------|--------|-----------|--------|
| 1 | S1 Watchlist Rename + S9 Proxy (PATCH + Signals fix) | ✅ done | none | 45 min |
| 2 | S8 Briefing GET Endpoints (morning + instrument) | ✅ done | none | 45 min |

---

## Wave 1: S1 Watchlist Rename + S9 Proxy Updates

**Goal**: Add `PATCH /api/v1/watchlists/{watchlist_id}` to S1 (rename), proxy it through S9, and replace the S9 signals/ai stub with a real proxy to S6.
**Depends on**: none
**Estimated effort**: 45 min
**Architecture layer**: application + API

### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/application/use_cases/portfolio_ops.py` — `RenamePortfolioUseCase` pattern (lines 79–112)
- `services/portfolio/src/portfolio/application/use_cases/watchlist.py` — existing watchlist use cases
- `services/portfolio/src/portfolio/domain/entities/watchlist.py` — frozen dataclass, `name` field
- `services/portfolio/src/portfolio/api/routes/watchlist.py` — existing routes
- `services/portfolio/src/portfolio/api/schemas.py` — existing watchlist schemas
- `services/api-gateway/src/api_gateway/routes/proxy.py` — S9 proxy patterns (line 814 TODO)

### Tasks

#### T-1-01: S1 RenameWatchlistUseCase + Domain Logic

**Type**: impl
**depends_on**: none
**blocks**: T-1-02
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/watchlist.py`
- `services/portfolio/src/portfolio/domain/entities/watchlist.py`

**What to build**: Add `RenameWatchlistCommand` and `RenameWatchlistUseCase` to watchlist.py, mirroring the exact pattern of `RenamePortfolioCommand` / `RenamePortfolioUseCase` in portfolio_ops.py.

**Entities / Components**:
- **RenameWatchlistCommand** (frozen dataclass):
  - `watchlist_id: UUID`
  - `owner_id: UUID`
  - `tenant_id: UUID`
  - `new_name: str`
- **RenameWatchlistUseCase**:
  - `execute(cmd, uow) -> Watchlist`
  - Steps: (1) fetch watchlist by id+tenant; (2) verify owner; (3) update name via repo; (4) emit `watchlist.renamed` outbox event; (5) commit

**Domain entity change**: The `Watchlist` entity is a frozen dataclass. Since portfolio uses `portfolio.rename(new_name)` (a method that mutates), check if the portfolio entity has `kw_only=True` with non-frozen behavior OR if the repository does a raw UPDATE. The approach must mirror whatever pattern portfolio uses. If Watchlist remains frozen, the use case should construct a new Watchlist with the updated name and call `repo.save()`.

**Note on events**: No new Avro schema needed for MVP. The outbox event is optional — only add if `watchlist.renamed` already exists in the event mapper. If not, skip the event emission and add a TODO comment.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_rename_watchlist_success` | Name updated, returned watchlist has new name | unit |
| `test_rename_watchlist_not_found` | WatchlistNotFoundError raised for unknown ID | unit |
| `test_rename_watchlist_wrong_owner` | AuthorizationError raised for non-owner | unit |

**Acceptance criteria**:
- [ ] `RenameWatchlistCommand` and `RenameWatchlistUseCase` exist in watchlist.py
- [ ] Use case mirrors portfolio rename pattern exactly
- [ ] 3 unit tests pass

---

#### T-1-02: S1 PATCH Watchlist Route + Schema

**Type**: impl
**depends_on**: T-1-01
**blocks**: T-1-03
**Target files**:
- `services/portfolio/src/portfolio/api/routes/watchlist.py`
- `services/portfolio/src/portfolio/api/schemas.py`

**What to build**: Add `PATCH /api/v1/watchlists/{watchlist_id}` route to S1. Follow the exact pattern of the portfolio PUT rename route.

**Schema** (add to schemas.py):
```python
class WatchlistRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
```

**Route**:
```python
@router.patch("/{watchlist_id}", response_model=WatchlistResponse)
async def rename_watchlist(
    watchlist_id: UUID,
    body: WatchlistRenameRequest,
    uow: UoWDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    x_owner_id: UUID = Header(..., alias="X-Owner-ID"),
) -> WatchlistResponse:
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_patch_watchlist_rename_200` | Returns 200 with new name | unit |
| `test_patch_watchlist_not_found_404` | Returns 404 for unknown ID | unit |
| `test_patch_watchlist_wrong_owner_403` | Returns 403 for non-owner | unit |

**Acceptance criteria**:
- [ ] `PATCH /api/v1/watchlists/{watchlist_id}` registered in S1 router
- [ ] `WatchlistRenameRequest` schema validated (min 1, max 100 chars)
- [ ] Existing watchlist tests still pass
- [ ] 3 new tests pass

---

#### T-1-03: S9 PATCH Watchlist Proxy + Signals/AI Proxy Fix

**Type**: impl
**depends_on**: T-1-02
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/routes/proxy.py`

**What to build**: Two changes in proxy.py:

**Part A — PATCH /v1/watchlists/{watchlist_id}**:
Add proxy route after the existing DELETE watchlist route, following the same pattern. Use `_portfolio_headers(request)` for `X-Owner-ID` mapping. Forward request body.

```python
@router.patch("/watchlists/{watchlist_id}")
async def rename_watchlist(watchlist_id: str, request: Request) -> Any:
    """Proxy PATCH /api/v1/watchlists/{watchlist_id} → S1 Portfolio service.

    Requires authentication. Renames the watchlist (body: {"name": "New Name"}).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.patch(
        f"/api/v1/watchlists/{watchlist_id}",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
```

Remove the TODO comment at line 814.

**Part B — Replace signals/ai stub**:
Replace the stub `GET /v1/signals/ai` (currently returns hardcoded empty list) with a real proxy to `clients.nlp_pipeline`. The `nlp_pipeline` client already exists in `ServiceClients` and is wired in `app.py:131`.

```python
@router.get("/signals/ai")
async def ai_signals(request: Request) -> Any:
    """Proxy GET /api/v1/signals → S6 NLP Pipeline.

    Returns price-impact signals with optional min_impact_score filter.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.nlp_pipeline.get(
        "/api/v1/signals",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_patch_watchlist_proxy_requires_auth` | 401 without auth | unit |
| `test_patch_watchlist_proxy_forwards_body` | Body forwarded to S1 with X-Owner-ID | unit |
| `test_signals_ai_proxy_to_s6` | Proxied to nlp_pipeline client (not stub) | unit |
| `test_signals_ai_requires_auth` | 401 without auth | unit |

**Acceptance criteria**:
- [ ] `PATCH /v1/watchlists/{watchlist_id}` proxied to S1 with `_portfolio_headers`
- [ ] TODO comment removed
- [ ] `GET /v1/signals/ai` proxied to S6 `nlp_pipeline` client (no longer stub)
- [ ] All 127 existing api-gateway tests still pass + 4 new tests

### Validation Gate
- [ ] `cd services/portfolio && python -m pytest tests/ -v` — all pass
- [ ] `cd services/api-gateway && python -m pytest tests/ -v` — all pass (127 existing + 4 new)
- [ ] ruff + mypy clean on both services

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `services/api-gateway/tests/test_s9_wave3_proxy.py::test_ai_signals_stub_returns_empty` | No longer returns hardcoded empty — now proxies to S6 | Update test to mock `nlp_pipeline.get` and verify proxy behavior |

### Regression Guardrails
- **BP-064**: FastAPI ≤0.111 `status_code=204` + body → validation error. Use `status_code=200` for PATCH if returning body, or default (no explicit status_code on decorator).
- **BP-159**: `BaseHTTPMiddleware` dual-instance `startup()` bypass — don't add any new middleware. Only adding routes.

---

## Wave 2: S8 Briefing GET Endpoints

**Goal**: Add `GET /api/v1/briefings/morning` and `GET /api/v1/briefings/instrument/{entity_id}` to S8 so the frontend Dashboard and Instrument Detail pages can fetch AI briefings. S9 proxy routes already exist (proxy.py:692 and proxy.py:713).
**Depends on**: none
**Estimated effort**: 45 min
**Architecture layer**: application + API

### Pre-read (agent must read before starting)
- `services/rag-chat/src/rag_chat/api/routes/briefings.py` — existing POST internal route
- `services/rag-chat/src/rag_chat/api/schemas.py` — existing BriefingRequest/BriefingResponse
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` — existing use case
- `services/rag-chat/src/rag_chat/app.py` — how briefing_uc is wired (line 214–218)
- `services/rag-chat/.claude-context.md`

### Tasks

#### T-2-01: S8 Public Briefing Route File + Schemas

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (new file)
- `services/rag-chat/src/rag_chat/api/schemas.py` (add new response schema)
- `services/rag-chat/src/rag_chat/app.py` (register new router)

**What to build**: Create a new public briefing route file with two GET endpoints. These differ from the existing internal POST in that they:
1. Are called via S9 proxy (not S10 scheduler) — auth via `X-Internal-JWT` header
2. Generate/retrieve briefings on-demand for the authenticated user
3. Use Valkey caching (24h TTL for morning, 24h for instrument)

**Endpoints**:

```python
# GET /api/v1/briefings/morning
# - Extracts user_id from X-Internal-JWT (request.state.user_id)
# - Checks Valkey cache: key = f"briefing:morning:{user_id}"
# - If cached: return immediately
# - If not: generate via briefing_uc with default market context, cache result, return
# - On generation failure: return 503 {"detail": "Briefing generation unavailable"}

# GET /api/v1/briefings/instrument/{entity_id}
# - Extracts user_id from X-Internal-JWT (request.state.user_id)
# - Checks Valkey cache: key = f"briefing:instrument:{entity_id}:{user_id}"
# - If cached: return immediately
# - If not: generate via briefing_uc with entity-focused context, cache result, return
# - On generation failure: return 503 {"detail": "Briefing generation unavailable"}
```

**New schema** (add to schemas.py):
```python
class PublicBriefingResponse(BaseModel):
    """Response for GET /api/v1/briefings/* (called via S9 proxy)."""
    narrative: str
    risk_summary: dict[str, Any] = {}
    citations: list[dict[str, Any]] = []
    generated_at: str
    cached: bool = False  # True if served from Valkey cache
    entity_id: str | None = None  # Set for instrument briefings
```

**Router registration**: Add to `app.py` alongside existing briefings_router. Use prefix `/api/v1` (not `/internal/v1`).

**Implementation notes**:
- The `GenerateBriefingUseCase` requires `portfolio_context`, `market_snapshots`, and `active_signals`. For the public GET endpoints, these must be gathered server-side. The simplest MVP approach: return a pre-built "no portfolio context" briefing that focuses on market-wide news and signals. Add a TODO for enriching with user's actual portfolio context once the S1→S8 internal call is established.
- For the **instrument briefing**, use the entity_id to focus the LLM prompt on that specific entity. Pass it as part of the `portfolio_context` or `active_signals` fields.
- **Valkey caching**: Use `request.app.state.valkey` (already wired in S8 app.py). Cache key pattern: `briefing:{type}:{user_id}`. TTL: 86400 (24h).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_morning_briefing_returns_200` | GET /api/v1/briefings/morning returns briefing | unit |
| `test_morning_briefing_requires_auth` | 401 without X-Internal-JWT | unit |
| `test_instrument_briefing_returns_200` | GET /api/v1/briefings/instrument/{id} returns briefing | unit |
| `test_instrument_briefing_requires_auth` | 401 without X-Internal-JWT | unit |
| `test_morning_briefing_cached` | Second call within 24h returns cached=true | unit |
| `test_morning_briefing_generation_failure_503` | LLM unavailable → 503 | unit |

**Acceptance criteria**:
- [ ] `GET /api/v1/briefings/morning` returns 200 with `PublicBriefingResponse`
- [ ] `GET /api/v1/briefings/instrument/{entity_id}` returns 200 with `PublicBriefingResponse`
- [ ] Both require `X-Internal-JWT` (enforced by InternalJWTMiddleware)
- [ ] Results cached in Valkey with 24h TTL
- [ ] 503 returned on LLM provider failure
- [ ] Existing internal POST briefing endpoint unaffected
- [ ] 6 new tests pass
- [ ] `cd services/rag-chat && python -m pytest tests/ -v` — all pass

### Validation Gate
- [ ] `cd services/rag-chat && ruff check . --fix && ruff format .`
- [ ] `cd services/rag-chat && mypy src/`
- [ ] `cd services/rag-chat && python -m pytest tests/ -v` — all pass
- [ ] Existing S9 proxy routes (proxy.py:692, proxy.py:713) now return 200 when S8 is running

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None — only additions | New route file + schema addition | None |

### Regression Guardrails
- **BP-064**: Don't use `status_code=204` with a response body. Use default 200.
- **BP-159**: `BaseHTTPMiddleware` dual-instance `startup()` bypass — don't add new middleware to S8. The existing `InternalJWTMiddleware` already protects all `/api/v1/*` routes.
- **BP-145**: Ensure the new router uses the existing `/api/v1` prefix (not `/internal/v1`) so it goes through InternalJWTMiddleware for auth.

---

## Cross-Cutting Concerns

- **No Alembic migrations needed** — no new tables or columns
- **No Avro schema changes** — `watchlist.renamed` event is optional for MVP (skip if not in mapper)
- **No new Kafka topics** — all communication is REST
- **No configuration changes** — S6 `nlp_pipeline` client already wired in S9

## Risk Assessment

- **Critical path**: Wave 1 and Wave 2 are independent — can run in parallel
- **Highest risk**: S8 briefing generation depends on LLM availability. The caching layer mitigates cold-start latency.
- **Rollback**: All changes are additive (new routes). Safe to revert individually.
- **Testing gap**: S8 briefing tests will need to mock the LLM provider. Follow existing `GenerateBriefingUseCase` test patterns.
