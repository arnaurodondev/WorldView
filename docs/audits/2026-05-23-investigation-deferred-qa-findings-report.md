# Investigation Report: Deferred QA Findings — feat/plan-0089-w2

**Date**: 2026-05-23
**Branch**: feat/plan-0089-w2
**Investigator**: 6 parallel specialist agents (Explore)
**Source**: `docs/audits/2026-05-22-qa-branch-feat-plan-0089-w2-report.md` — deferred items G-002, G-003, G-006/G-007, G-016, G-018, G-042

---

## Executive Summary

| ID | Title | Severity | Root Cause Type | Long-Term Decision | Effort |
|----|-------|----------|-----------------|-------------------|--------|
| G-016 | entity_id: str not UUID on content routes | MEDIUM (security) | Missing input validation | Change `str` → `UUID` on 8 routes | XS |
| G-003 | useTriggerNarrativeGeneration retry:3 | MEDIUM (latent) | Wrong code comment + TanStack API misuse | Add `shouldRetry` guard on all affected mutations | XS |
| G-006/G-007 | KG OutboxRepository non-idempotent | MAJOR (latent) | NLP outbox pattern not applied to KG | Optional `event_id` param + `ON CONFLICT DO NOTHING` | S |
| G-042 | POST /entities/similar uses system JWT | LOW (inconsistency) | Explicit design decision from PRD-0017 | Add user auth guard + forward user JWT | XS |
| G-018 | SENTI chip hardcodes days=90 | MEDIUM (PRD violation) | Integration never wired; timeframe not plumbed | Add `timeframe` prop + `timeframe-to-days.ts` utility | S |
| G-002 | depth=4/5 dead code in limitByDepth | LOW (dead code) | Incomplete PLAN-0088 P0-8 implementation | Remove dead map entries + fix misleading comment | XS |

**Recommended fix order**: G-016 → G-003 → G-006/G-007 → G-042 → G-018 → G-002

---

## G-002: depth=4/5 Dead Code in limitByDepth

### Root Cause

**File**: `apps/worldview-web/lib/api/knowledge-graph.ts:76`

```typescript
const limitByDepth: Record<number, number> = { 1: 15, 2: 40, 3: 80, 4: 120, 5: 160 };
```

The comment above this line (lines 65-70) states that "S9 gateway cap was also lifted from 50→200" during PLAN-0088 P0-8. That statement is **false** — S9's route has never been changed from `depth: int = Query(ge=1, le=3)` (`services/api-gateway/src/api_gateway/routes/intelligence.py:173`). The UI slider (`GraphToolbar.tsx:106`) enforces max=3. The depth=4/5 entries have been dead code since they were written.

### Execution Path Trace

```
User selects depth → slider (max=3) → GraphColumn.tsx → getEntityGraph(entityId, depth)
  → limitByDepth[depth] lookup (only depth ∈ {1,2,3} ever reached)
  → GET /v1/entities/{id}/graph?depth=N&limit=M
  → S9 validates depth ≤ 3 → 422 if depth > 3 (unreachable from current UI)
```

### Long-Term Decision

**Remove depth=4/5 from the map.** No backend support exists; no PRD plans to add it; AGE Cypher depth>3 routinely times out at current data volumes. Adding a `Math.min(depth, 3)` clamp would hide the issue instead of fixing it.

### Impact if Left Unfixed

LOW — dead code only. Risk: the next developer reading the comment assumes depth=4/5 work, writes a test, gets a 422, and wastes time debugging.

### Minimal Fix

```typescript
// knowledge-graph.ts:76
// Before:
const limitByDepth: Record<number, number> = { 1: 15, 2: 40, 3: 80, 4: 120, 5: 160 };
// After:
const limitByDepth: Record<number, number> = { 1: 15, 2: 40, 3: 80 };
```

Update comment lines 65-70 to reflect: S9 caps at `le=3`; depth>3 not supported.

---

## G-003: useTriggerNarrativeGeneration retry:3 Amplifies 429s

### Root Cause

**File**: `apps/worldview-web/lib/api/intelligence.ts:265-267`

```typescript
retry: 3,
retryDelay: (attemptIndex: number) =>
  Math.max(1000 * 2 ** (attemptIndex - 1), 4000),
```

The code comment at lines 261-264 states:
```typescript
// retries won't fire on 4xx (TanStack default)
```

**This comment is incorrect.** TanStack Query's default `shouldRetry` guard applies only to `useQuery`, not `useMutation`. `useMutation` with `retry: 3` retries on **all errors including 429**. S9 returns 429 from its Valkey-based narrative generation rate limiter (1 request per hour per entity). When rate-limited, the client sends 4 identical POST requests in 7 seconds.

### Execution Path Trace

```
User clicks "Regenerate" → handleRegenerate() → POST /v1/entities/{id}/narratives/generate
  → S9 rate limit check (Valkey key: narrative_gen_proxy:<tenant>:<entity>:<user>)
  → 429 Too Many Requests returned
  → TanStack useMutation sees error → retries (no shouldRetry guard)
  → 3 more POSTs fired (delays: 1s, 2s, 4s)
  → S9 rate limiter sees 3 more 429s → S7 never reached but load amplified
```

### Additional Finding: 5 Other Mutations Affected

All 5 other `useMutation` calls in the codebase have `retry: 3` without a `shouldRetry` guard:
- `usePatchFeedbackSubmission` — NEEDS AUDIT (PATCH)
- `useInitiateBrokerageConnection` — NEEDS AUDIT (POST OAuth flow, retry may spam OAuth callbacks)
- `useDisconnectBrokerageConnection` — NEEDS AUDIT (comment says "retry only on 5xx" but no code guard)
- `useTriggerBrokerageSync` — SAFE AS-IS (202 Accepted, comment confirms retry-safe by design)
- `useTriggerNarrativeGeneration` — **NEEDS FIX NOW**

### Long-Term Decision

Add a `shouldRetry` guard to all mutations that return non-202 responses. The standard guard:

```typescript
retry: (failureCount, error) => {
  // WHY: 4xx errors (including 429 rate limit) are permanent within their window;
  // retrying them amplifies load. Only 5xx/network failures (transient) should retry.
  if (error instanceof GatewayError && error.status !== 0 && error.status < 500) {
    return false;
  }
  return failureCount < 3;
},
```

This should be extracted to a shared `shouldRetryOnServerError` helper in `lib/gateway.ts` and applied to all affected mutations.

### Impact if Left Unfixed

MEDIUM latent. On 429: 4× POSTs fired in 7s, wasting S7 LLM capacity. Worse if multiple users regenerate the same entity within the 1-hour window (shared rate limit key).

### Minimal Fix

**File**: `apps/worldview-web/lib/api/intelligence.ts:265`

Replace `retry: 3,` with the `shouldRetry` function shown above. Also audit and fix `useInitiateBrokerageConnection` and `useDisconnectBrokerageConnection`.

---

## G-006/G-007: KG OutboxRepository Non-Idempotent append()

### Root Cause

**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/outbox.py:40-60`

**Current signature**:
```python
async def append(self, topic: str, partition_key: str, payload_avro: bytes) -> UUID:
```

**Current INSERT SQL**:
```sql
INSERT INTO outbox_events (topic, partition_key, payload_avro, status)
VALUES (:topic, :partition_key, :payload_avro, 'pending')
RETURNING event_id
```

No `event_id` parameter, no `ON CONFLICT` clause. The database generates a fresh `gen_random_uuid()` on every insert. On Kafka redelivery of the same triggering message, a second outbox row is created → duplicate downstream Kafka event.

### NLP Pipeline Contrast (Correct Pattern)

**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/outbox.py:23-53`

```python
async def add(self, topic, partition_key, payload_avro, *, event_id: UUID | None = None) -> UUID:
    resolved_id = event_id if event_id is not None else common.ids.new_uuid7()
    stmt = (
        pg_insert(OutboxEventModel)
        .values(event_id=resolved_id, ...)
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
```

The NLP pipeline correctly: (1) accepts an optional deterministic `event_id`, (2) falls back to `new_uuid7()`, (3) uses `ON CONFLICT (event_id) DO NOTHING`.

### Call Sites

7 call sites, all in KG service workers, none pass `event_id`:
1. `graph_write.py:577` — `TOPIC_GRAPH_STATE_CHANGED`
2. `contradiction.py:148` — `TOPIC_CONTRADICTION`
3. `canonicalization.py:194` — `TOPIC_RELATION_PROPOSED`
4. `generate_narrative.py:618` — `_ENTITY_NARRATIVE_GENERATED_TOPIC`
5. `trigger_entity_refresh.py:157` — `_ENTITY_REFRESH_TOPIC`
6. `provisional_enrichment.py:385` — `_ENTITY_DIRTIED_TOPIC`
7. `provisional_enrichment_core.py:120` — `_ENTITY_CANONICAL_CREATED_TOPIC`

All callers have deterministic data available (entity_id, doc_id, event type) to compute stable event_ids.

### Blast Radius

6 outbox topics produce ~1000 duplicate events/day per topic at 99.9% uptime SLA (from Kafka redelivery baseline). Downstream consumers of `graph.state.changed.v1`, `entity.dirtied.v1`, `entity.canonical.created.v1` etc. may:
- Fire redundant S7 re-enrichment cycles (wasted LLM inference)
- Send duplicate notifications to S10 (false repeated alerts)
- Inflate worker monitoring metrics

Data corruption risk: LOW — most downstream consumers are idempotent.

### Long-Term Decision

**Phase 1** (backward-compatible, deploy now): Add optional `event_id: UUID | None = None` param + `ON CONFLICT DO NOTHING` to `append()`. Existing callers continue generating fresh UUIDs; at least the schema is prepared.

**Phase 2** (follow-up, per call site): Update each caller to compute a deterministic event_id:
```python
from common.ids import uuid5_from_parts
event_id = uuid5_from_parts(str(doc_id), "graph_state_changed", str(entity_id))
await outbox_repo.append(..., event_id=event_id)
```

### Minimal Fix (Phase 1)

```python
# outbox.py — updated append() signature and INSERT
async def append(
    self,
    topic: str,
    partition_key: str,
    payload_avro: bytes,
    *,
    event_id: UUID | None = None,
) -> UUID:
    resolved_id: UUID = event_id if event_id is not None else new_uuid7()
    result = await self._session.execute(
        text("""
    INSERT INTO outbox_events (event_id, topic, partition_key, payload_avro, status)
    VALUES (:event_id, :topic, :partition_key, :payload_avro, 'pending')
    ON CONFLICT (event_id) DO NOTHING
    RETURNING event_id
    """),
        {"event_id": str(resolved_id), "topic": topic,
         "partition_key": partition_key, "payload_avro": payload_avro},
    )
    row = result.fetchone()
    return UUID(str(row[0])) if row else resolved_id
```

Also update `OutboxRepositoryPort` ABC to match. Add 1 test: "same event_id twice → second insert silently ignored."

---

## G-016: entity_id: str Not UUID on Content Routes (Path Traversal)

### Root Cause

**File**: `services/api-gateway/src/api_gateway/routes/content.py`

Two routes accept `entity_id: str` (not `UUID`) and embed it directly in downstream URLs via f-string interpolation:

```python
# Line 82-83 — get_entity_articles
@router.get("/entities/{entity_id}/articles")
async def get_entity_articles(entity_id: str, ...) -> Any:
    resp = await clients.nlp_pipeline.get(f"/api/v1/entities/{entity_id}/articles", ...)
```

```python
# Line 245-246 — get_news_entity
@router.get("/news/entity/{entity_id}")
async def get_news_entity(entity_id: str, ...) -> Any:
    resp = await clients.nlp_pipeline.get(f"/api/v1/entities/{entity_id}/articles", ...)
```

Correct pattern already exists at line 49 (`get_entity_detail(entity_id: UUID, ...)`), which is documented as F-S04.

### Path Traversal Exploitability

A caller can send `entity_id = "../admin/something"`. S9 extracts the raw string and constructs:
`/api/v1/entities/../admin/something/articles` → resolved by httpx to `/api/v1/admin/something/articles`

S6 NLP pipeline routes include `admin.py`, `dlq.py`, and internal analytics endpoints. S6 enforces `AdminAuthDep` on admin routes, so exploitation is limited — but the gateway should be the validation boundary, not S6.

### Full Scope: 8 Routes Affected

The investigation found a wider scope than the QA originally flagged:

| File | Route | Parameter | Risk |
|------|-------|-----------|------|
| `content.py:83` | `GET /entities/{entity_id}/articles` | `entity_id: str` | Path traversal → S6 |
| `content.py:246` | `GET /news/entity/{entity_id}` | `entity_id: str` | Path traversal → S6 |
| `content.py:221` | `GET /news/cluster/{cluster_id}` | `cluster_id: str` | Path traversal → content-store |
| `content.py:335` | `GET /documents/{doc_id}` | `doc_id: str` | Path traversal → content-store |
| `content.py:378` | `DELETE /documents/{doc_id}` | `doc_id: str` | Path traversal → content-store |
| `chat.py:346` | `GET /briefings/instrument/{entity_id}` | `entity_id: str` | Weak; fallback path in resolve_security_id |
| `chat.py:381` | `POST /briefings/instrument/{entity_id}/generate` | `entity_id: str` | Same as above |
| `portfolio.py:1124` | `DELETE /watchlists/{wid}/members/{eid}` | `watchlist_id: str`, `entity_id: str` | Both unvalidated |

### Long-Term Decision

**Change all entity/document ID path parameters from `str` to `UUID`** (or appropriate structured type). FastAPI validates at the boundary before the handler runs — a 422 is returned before any downstream call. No sanitization or encoding logic needed; the type annotation does all the work.

For `chat.py`: the `resolve_security_id()` fallback (`canonical_entity_id = entity_id`) on line 367 negates the validation even if the type is changed. Remove the fallback or add explicit UUID validation after resolution.

### Minimal Fix

Per route, one change:
```python
# Before:
async def get_entity_articles(entity_id: str, ...) -> Any:
# After:
async def get_entity_articles(entity_id: UUID, ...) -> Any:
```

Add from the test file:
```python
async def test_get_entity_articles_rejects_non_uuid(authed_app):
    resp = await authed_app.get("/v1/entities/../admin/articles")
    assert resp.status_code == 422
```

---

## G-018: SENTI Chip Hardcodes days=90 vs Chart Timeframe

### Root Cause

**File**: `apps/worldview-web/components/instrument/quote/TAOverlayPanel.tsx:244`

```typescript
const { data: sentimentData } = useEntitySentimentTimeseries(
  sentiActive ? (entityId ?? null) : null,
  90,  // ← hardcoded
);
```

`TAOverlayPanel` is not yet integrated into `OHLCVChart` or `QuoteTab` — this is a **pre-integration bug** discovered before the component is wired. Once integrated, users with any non-default timeframe will see the SENTI overlay only covering the rightmost 90 days.

### Timeframe Type (Correction from QA Assumptions)

The actual `Timeframe` type is `"5M" | "1H" | "1D" | "1W" | "1M"` (from `lib/chart-adapter.ts`), not the `1D/5D/1M/3M/1Y/5Y` assumed in the original QA finding. This changes the mapping values.

### S9 Constraint

`GET /v1/entities/{id}/sentiment-timeseries` accepts `days: int = Query(default=90, ge=1, le=365)`. No changes needed to the backend.

### PRD Violation

PLAN-0091 Wave F-2 acceptance criterion explicitly states: "Days aligns with current chart period selection." The hardcoded 90 violates this.

### Long-Term Decision

**Architecture**: Create `lib/ta/timeframe-to-days.ts` utility, add `timeframe: Timeframe` prop to `TAOverlayPanel`, compute `days` before the hook call, wire `timeframe` from `OHLCVChart` when integrating.

```typescript
// lib/ta/timeframe-to-days.ts
import type { Timeframe } from "@/lib/chart-adapter";

export const TIMEFRAME_TO_DAYS: Record<Timeframe, number> = {
  "5M": 7,    // 1 trading week
  "1H": 14,   // 2 trading weeks
  "1D": 30,   // ~1 month
  "1W": 30,   // ~4 trading weeks
  "1M": 90,   // ~3 months
};

// Capped to S9 max of 365
export function getMaxDaysForTimeframe(tf: Timeframe): number {
  return Math.min(TIMEFRAME_TO_DAYS[tf] ?? 90, 365);
}
```

```typescript
// TAOverlayPanel.tsx — updated props
export interface TAOverlayPanelProps {
  bars: OHLCVBar[];
  onOverlaysChange: (overlays: OverlaySeries[]) => void;
  entityId?: string | null;
  timeframe: Timeframe;  // NEW
}

// Inside component:
const sentiDays = getMaxDaysForTimeframe(timeframe);
// ... replace 90 with sentiDays in useEntitySentimentTimeseries call
```

### Impact if Left Unfixed

MEDIUM-HIGH once integrated. On `1M` chart: only the last 90 days of 30+ days visible — acceptable but stale. On any longer timeframe: overlay "dies" at the left edge with no data. PRD acceptance criterion is unmet.

Since TAOverlayPanel is not yet wired, fixing this before integration costs near-zero effort and zero risk.

---

## G-042: POST /entities/similar Uses System JWT

### Root Cause

**File**: `services/api-gateway/src/api_gateway/routes/content.py:29-43`

The endpoint was **intentionally designed as public** per PRD-0017 Wave C-1. The docstring says `"Public endpoint — issues a system JWT for backend authentication."` It calls `_system_headers()` which issues a nil-UUID system JWT.

**Irony**: The frontend (`knowledge-graph.ts:202-216`) already sends a valid user Bearer token with every call. S9 receives the user JWT, discards it, and replaces it with a system JWT before calling S7. The user auth is present but silently ignored.

### Is This an Active Security Gap?

**No.** Three layers of defense prevent exploitation:
1. Browser CORS — restricts cross-origin JavaScript from reading S9 responses
2. OIDC login required — to get to the frontend UI, a caller must authenticate with Zitadel
3. Data is not sensitive — entity names, tickers, and similarity scores are public metadata

### Inconsistency with All Other Entity Endpoints

| Endpoint | Auth Required |
|----------|---------------|
| `GET /v1/entities/{id}` | Yes |
| `GET /v1/entities/{id}/graph` | Yes |
| `GET /v1/entities/{id}/contradictions` | Yes |
| `POST /v1/entities/similar` | **No** ← inconsistent |

### Long-Term Decision

**Add user auth guard.** The endpoint is only called by the authenticated frontend. Making it consistently authenticated:
- Ensures future developers don't add portfolio-sensitive logic assuming the endpoint is public
- Aligns with the principle that all entity operations are user-scoped
- Honors the user JWT already sent by the frontend (instead of silently discarding it)
- Enables future personalization (e.g., "similar entities in your portfolio")

**Change**: Replace `_system_headers()` with `_auth_headers()` (forward user JWT) and add the standard 401 guard.

### Minimal Fix

```python
# content.py:29-43 — updated find_similar_entities
@router.post("/entities/similar")
async def find_similar_entities(request: Request) -> Any:
    """Proxy POST /api/v1/entities/similar → S7 Knowledge Graph.
    Requires authentication. S7 returns 404, 422, 503.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        "/api/v1/entities/similar",
        content=body,
        headers={"Content-Type": "application/json", **_auth_headers(request)},  # user JWT
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
```

Update `api-gateway.md` to mark `/v1/entities/similar` auth column as "Yes". Update test to include user state in mock request.

---

## Prioritized Action Plan

| Priority | Issue | File | Effort | Action |
|----------|-------|------|--------|--------|
| P0 | G-016 | `content.py`, `chat.py`, `portfolio.py` | 30 min | Change `str` → `UUID` on 8 routes + add 422 tests |
| P1 | G-003 | `lib/api/intelligence.ts` | 20 min | Add `shouldRetry` guard to all affected mutations |
| P2 | G-006/G-007 | `outbox.py` (KG service) | 2h | Add optional `event_id` param + ON CONFLICT DO NOTHING + test |
| P3 | G-042 | `content.py` (gateway) | 15 min | Add 401 guard + switch to `_auth_headers` |
| P4 | G-018 | `TAOverlayPanel.tsx` + new utility | 1h | Create `timeframe-to-days.ts` + add `timeframe` prop |
| P5 | G-002 | `knowledge-graph.ts:76` | 5 min | Remove depth=4/5 map entries + fix comment |

**P0 (G-016) should be fixed before the next merge** — it's a security boundary issue, 2-line change per route, zero risk.

**P2 (G-006/G-007) Phase 1** can be deployed independently of Phase 2 (call site updates). Phase 1 closes the schema gap without breaking any existing callers.

**P4 (G-018)** is most efficiently done before `TAOverlayPanel` is wired into `QuoteTab` (pre-integration).

---

## Compounding Updates

### New Bug Patterns (to add to BUG_PATTERNS.md)
- **BP-537**: `useMutation` retry:N without `shouldRetry` guard retries 429/4xx — TanStack's default 4xx filter applies to `useQuery` only, not `useMutation`. Any mutation with `retry: N` will retry rate-limit responses, amplifying load.
- **BP-538**: Misleading code comment claims TanStack won't retry 4xx on mutations — incorrect. Always verify TanStack behavior per hook type (query vs mutation) rather than relying on comments.

### Files to Update
- `docs/BUG_PATTERNS.md` — add BP-537, BP-538
- `docs/services/api-gateway.md` — mark `/v1/entities/similar` auth as Yes (after G-042 fix)
- `RULES.md` or `AGENTS.md` — consider adding: "All `useMutation` with `retry` MUST include `shouldRetry` filtering 4xx" as a frontend rule
