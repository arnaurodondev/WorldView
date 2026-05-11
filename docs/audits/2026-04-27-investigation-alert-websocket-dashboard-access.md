# Investigation Report: Alert WebSocket Failure — Dashboard Inaccessible

**Date**: 2026-04-27
**Investigator**: Claude (investigation skill)
**Severity**: CRITICAL (dashboard page crashes on load for all authenticated users)
**Status**: Root cause identified and fixed ✓

---

## 1. Issue Summary

After `make dev-rebuild && make seed`, the dashboard page was inaccessible. The `AlertStreamProvider` wraps the entire app, and a fatal crash inside it caused React's error boundary to fire (`app/error.tsx`), showing "Something went wrong" instead of the dashboard. The crash was traced to three compounding bugs: the wrong WebSocket URL path, WebSocket middleware bypass, and a Python StrEnum vs. TypeScript case mismatch.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| WS URL `/v1/alerts/stream` | `AlertStreamContext.tsx` | Wrong — S10 uses `/api/v1` prefix |
| `BaseHTTPMiddleware` WS bypass | Starlette source | `dispatch()` never runs for `scope["type"]=="websocket"` |
| `websocket.state.user_id` always empty | `routes.py` (old code) | Auth check always failed → close 4001 |
| `severityColor()` returns `undefined` | `lib/utils.ts` | No `default` branch → TypeError crash |
| Python `StrEnum` lowercase output | S10 domain/enums.py | `"critical"` not `"CRITICAL"` |
| 57 containers healthy | `docker ps` | Stack started correctly |
| WS connects + receives ping | Python websockets client test | Fix confirmed working |

---

## 3. Execution Path Analysis

```
1. User logs in → AuthProvider sets accessToken
2. AlertStreamProvider.connect() fires
3. Fetch ws-token from S9 GET /v1/auth/ws-token → OK (RS256 token, 30s TTL)
4. new WebSocket("ws://localhost:8010/v1/alerts/stream?token=...") ← WRONG PATH
   └─ Starlette: no route matches /v1/alerts/stream → HTTP 403 (not 404)
   └─ Even if path were correct:
      └─ S10 InternalJWTMiddleware extends BaseHTTPMiddleware
         └─ BaseHTTPMiddleware.__call__: early return for scope["type"]=="websocket"
         └─ dispatch() never runs → websocket.state.user_id never set
         └─ handler checks `not user_id_raw` → True → websocket.close(4001) → HTTP 403
5. WS onerror → ws.close() → reconnect loop begins (backoff 1s/2s/4s...)
6. Meanwhile: REST alerts arrive via GET /api/v1/alerts/pending
7. REST response has severity="low" (lowercase StrEnum)
8. RecentAlerts.tsx passes "low" to severityColor()
9. severityColor() switch: no "low" case, no default → returns undefined
10. Caller: const { bg, text } = severityColor(...) → TypeError: Cannot destructure undefined
11. React error boundary catches → app/error.tsx renders → "Something went wrong"
```

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | WebSocket URL path wrong (/v1/ vs /api/v1/) | CONFIRMED | Code read: S10 APIRouter has `prefix="/api/v1"`; AlertStreamContext used `/v1/` |
| H-2 | BaseHTTPMiddleware skips WebSocket ASGI scopes | CONFIRMED | Code read: Starlette source `if scope["type"] != "http": return` |
| H-3 | Python StrEnum sends lowercase; TypeScript expects uppercase | CONFIRMED | S10 `AlertSeverity` is StrEnum → lowercase; `severityColor()` switch has uppercase cases only |
| H-4 | daily_return decimal fraction treated as percentage | CONFIRMED | S3 stores 0.015 (=1.5%) but S9 heatmap and frontend returned it as-is (appeared as 0.015%) |

---

## 5. Root Causes

### RC-1: WebSocket URL path mismatch (BP-248)
**Statement**: `AlertStreamContext.tsx` connected to `ws://localhost:8010/v1/alerts/stream` but S10's router registers at `/api/v1/alerts/stream`.
**Location**: `apps/worldview-web/contexts/AlertStreamContext.tsx:140`
**Trigger**: Every WebSocket connection attempt since the AlertStream feature was added.
**Fix**: Change path to `/api/v1/alerts/stream`.

### RC-2: BaseHTTPMiddleware bypasses WebSocket ASGI scopes (BP-249)
**Statement**: `InternalJWTMiddleware` inherits `BaseHTTPMiddleware` which never calls `dispatch()` for WebSocket scopes. `websocket.state.user_id` was therefore never populated; the handler closed all WS connections with code 4001.
**Location**: `services/alert/src/alert/api/routes.py:135-172`
**Fix**: Inline JWT validation in the WebSocket handler using `websocket.query_params.get("token")` + `websocket.app.state._internal_jwt_public_key`.

### RC-3: Python StrEnum lowercase vs TypeScript uppercase (BP-250)
**Statement**: `AlertSeverity` StrEnum returns lowercase values. `severityColor()` switch had no `default` branch. On any REST alert, `severityColor("low")` returned `undefined` → TypeError crash → error boundary.
**Location**: `apps/worldview-web/lib/utils.ts:254`, `components/dashboard/RecentAlerts.tsx:67`
**Fix**: `switch (severity.toUpperCase())` + `default` fallback; normalize severity to uppercase at REST/WS ingestion points.

---

## 6. Impact Analysis

- **Immediate**: Dashboard completely inaccessible for all users with any seeded alerts. Error boundary fires on page load.
- **Blast radius**: Any component that calls `severityColor()` without pre-normalizing severity crashes. `FlashOverlay`, `AlertsPage` also affected.
- **Data integrity**: No data corrupted. Alert data in DB is correct; the failure is purely at display/connection layer.

---

## 7. Additional Fixes Included

| Bug | Fix | Location |
|-----|-----|----------|
| BP-243: `daily_return` fraction vs. percentage | `* 100` in S9 `clients.py` heatmap + `lib/gateway.ts` movers | `api_gateway/clients.py:426`, `lib/gateway.ts:1360` |
| OHLCVChart stale `isFullscreen` closure in ResizeObserver | Add `isFullscreenRef` synced by `useEffect` | `components/instrument/OHLCVChart.tsx:144` |
| `RecentAlerts` message fallback for payload vs. body shape | `payload?.message ?? body ?? alert_type` chain | `components/dashboard/RecentAlerts.tsx:72` |
| ARIA combobox role missing `aria-controls` | Add `role="combobox"` + `aria-controls` | `components/portfolio/WatchlistsTabPanel.tsx:271` |
| `error.tsx` missing `error` prop + console logging | Add `useEffect(() => console.error(error), [error])` | `app/error.tsx:51` |

---

## 8. Validation Results

| Check | Result |
|-------|--------|
| `make dev-rebuild` | ✓ 57 containers healthy |
| `make seed` | ✓ demo@worldview.dev + 5 holdings + 5 watchlists confirmed |
| S9 `GET /healthz` | ✓ `{"status":"ok"}` |
| S10 `GET /healthz` | ✓ `{"status":"ok"}` |
| Frontend `GET /` (port 3001) | ✓ HTTP 200 |
| Alert WebSocket end-to-end | ✓ Connects + receives `{"type":"ping"}` within 30s |
| `GET /api/v1/alerts/pending` via S9 | ✓ `{"alerts_count":0}` (no seeded alerts) |
| Alert unit tests (15) | ✓ 15/15 pass |
| Api-gateway heatmap tests (4) | ✓ 4/4 pass |
| Alpaca adapter tests (17) | ✓ 17/17 pass |

---

## 9. New Bug Patterns

- **BP-248**: WebSocket path mismatch: `/v1/` vs `/api/v1/` for direct S10 connections
- **BP-249**: `BaseHTTPMiddleware` bypasses WebSocket ASGI scopes — auth middleware never runs for WS
- **BP-250**: Python `StrEnum` lowercase vs TypeScript uppercase — `switch` without `default` causes runtime crash

All three patterns have been added to `docs/BUG_PATTERNS.md`.

---

## 10. Prevention Recommendations

1. **Starlette WebSocket + Middleware**: Document in `.claude-context.md` that any middleware extending `BaseHTTPMiddleware` does NOT apply to WebSocket connections. Auth for WS must be inline in the route handler.
2. **API path consistency**: S9 proxied routes strip `/api` via Next.js rewrites. Direct connections (WS/SSE) must use the full registered path (`/api/v1/...`). Add to `docs/services/alert.md`.
3. **StrEnum normalization at boundary**: Establish a pattern: always call `.toUpperCase()` or `.toLowerCase()` when mapping Python StrEnum values to TypeScript discriminated unions at API ingestion. Document in `AGENTS.md`.
4. **Switch exhaustiveness**: All `switch` statements over external string values must have a `default` branch. Add to `REVIEW_CHECKLIST.md`.
