# Bug Patterns — Frontend

> **Category**: frontend
> **Description**: React hooks, Next.js, WebSocket/SSE, TypeScript, CSS, component lifecycle, API contract mismatches in UI code
> **Count**: 39 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-087 — In-process WebSocket `ConnectionManager` dead in standalone consumer process

**Context**: Process topology refactoring — standalone `*_consumer_main.py` entry points

**Symptom**: WebSocket push notifications to browser clients never fire. `AlertFanoutUseCase.broadcast()` executes without error but no clients receive the message. Log shows events processed successfully.

**Root cause**: `ConnectionManager` maintains an in-memory set of WebSocket connections. When consumers run as separate OS processes, the consumer process has its own empty `ConnectionManager` instance with zero connections (all connections are registered in the API process).

**Fix**: Implement a cross-process pub/sub bridge (e.g., Valkey pub/sub). The consumer process publishes to a Valkey channel; the API process subscribes and broadcasts to WebSocket clients.

**Prevention**: Any in-process mutable state (connection registries, caches, queues) that was shared between the consumer and API in a monolithic deployment will break after process separation. Audit all stateful objects passed to use cases in standalone consumer entry points.

---

---

## BP-139 — Unguarded JSON.parse in WebSocket onmessage Crashes React Tree

**Symptom**: Component tree crashes with `SyntaxError: Unexpected token` when the WebSocket server sends a non-JSON frame (keepalive bytes, proxy error, partial flush). Error boundary catches it but the WS connection remains open and state stops updating.

**Root cause**: `JSON.parse(event.data)` called without try/catch inside `ws.onmessage`.

**Fix**:
```typescript
ws.onmessage = (event: MessageEvent) => {
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(event.data as string) as Record<string, unknown>;
  } catch {
    return; // skip malformed frame
  }
  ...
};
```

**Prevention**: Every React hook that wraps a WebSocket `onmessage` must wrap `JSON.parse` in try/catch. Add a unit test that passes a non-JSON string as `event.data`.

**First seen**: PLAN-0021 QA pass, 2026-04-10 (F-014/F-152 merged finding).

---

---

## BP-163 — Frontend Gateway Response Shape Mismatch (API Returns Different Field Names)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | CRITICAL |
| **Affected areas** | Frontend `lib/gateway.ts`, all pages using S1/S3 data |
| **Root cause** | S1 Portfolio service returns `{items: [{id, owner_id, ...}]}` paginated envelopes with `id` field. Frontend types expect `Portfolio[]` (bare array) with `portfolio_id` field. Same pattern for watchlists (`id` vs `watchlist_id`), holdings (bare array vs wrapped object), search (`symbol` vs `ticker`), prediction markets (`items` vs `markets`). |
| **Symptom** | Portfolio page crashes with error boundary. Dashboard portfolio widget shows "No portfolio" even though data exists. Search returns wrong field names. |
| **Fix** | Add response transformation layer in `gateway.ts` — unwrap envelopes, map field names. |

### Prevention

When adding a new S9 proxy route, always test the ACTUAL API response shape with `curl` and compare to the frontend TypeScript type. Never assume backend field names match frontend types — S1/S3 use ORM-generated names (`id`, `user_id`) while frontend uses domain names (`portfolio_id`, `owner_id`).

---

---

## BP-242 — Missing Error State in News Tab (Silent Empty on Fetch Failure)

| Field | Value |
|-------|-------|
| **Service** | worldview-web — `app/(app)/instruments/[entityId]/page.tsx` |
| **Severity** | MEDIUM (incorrect UX — user sees "no articles" instead of error) |
| **Discovered** | 2026-04-27 instrument page QA pass |
| **Root cause** | The news tab's conditional rendering checked `newsLoading` then `filteredArticles.length === 0`, but never checked `isError`. A network failure sets `newsResp = undefined` and `isError = true`, causing `filteredArticles = []`, which renders the empty state message instead of an error. |
| **Symptom** | When `GET /v1/entities/{id}/articles` returns 5xx or times out, the News tab silently shows "No news articles match the current filters." — no indication of a fetch failure. |
| **Fix** | Destructure `isError: newsError` from `useQuery`. Add an error branch (`newsError ? <InlineEmptyState message="Failed to load news..." />`) before the empty-articles branch in the conditional render. |

### Prevention

- In every TanStack Query-powered tab/panel: always destructure `isError` alongside `isLoading` and `data`.
- Render order must be: **loading skeleton → error state → empty state → data**. Skipping the error branch causes silent failures.
- Code review checklist: any `isLoading && !data ? skeleton : items.length === 0 ? empty : data` pattern is missing the error branch.

---

## BP-248 — WebSocket Path Mismatch: /v1/ vs /api/v1/ in Direct S10 Connection

| Field | Value |
|-------|-------|
| **Service** | worldview-web — `contexts/AlertStreamContext.tsx` |
| **Severity** | HIGH (alert stream never connects — WebSocket 403 on every page load) |
| **Discovered** | 2026-04-27 dev-login investigation |
| **Root cause** | `AlertStreamContext.tsx` connected directly to S10 at `ws://localhost:8010/v1/alerts/stream`. S10's `APIRouter` uses `prefix="/api/v1"`, so the real route is `/api/v1/alerts/stream`. Starlette returns HTTP 403 (not 404) for WebSocket upgrade requests that don't match any registered route, making the error appear to be an auth problem. |
| **Symptom** | Alert WebSocket always returns 403 Forbidden. No alerts appear in the UI. Alert badge count stays at 0. The 403 looks identical to BP-201 (wrong JWT sub), making the root cause easy to misdiagnose. |
| **Fix** | Change path from `/v1/alerts/stream` to `/api/v1/alerts/stream` in `AlertStreamContext.tsx` connect step. |

### Prevention

- When a service registers its router with `APIRouter(prefix="/api/v1")` and the main app does `app.include_router(router)` (no additional prefix), the full path includes `/api`. Direct (non-proxied) connections must use the full path.
- S9-proxied calls strip `/api` via Next.js rewrites (`/api/:path*` → `/:path*`), so they land at S9's `/v1/...` correctly. Direct connections (WebSocket, SSE) do NOT go through Next.js rewrites and must use the exact path registered on the target service.
- Contrast: S9 routes use `router = APIRouter(prefix="/v1")` (no `/api` prefix) because they are called via the Next.js rewrite layer that strips `/api`. S10 uses `prefix="/api/v1"` because it's called directly without a rewrite.

---

---

## BP-249 — BaseHTTPMiddleware Bypasses WebSocket ASGI Scopes

| Field | Value |
|-------|-------|
| **Service** | S10 alert — `api/routes.py`, `infrastructure/middleware/internal_jwt.py` |
| **Severity** | CRITICAL (all WebSocket auth bypassed — always 403 close even with valid token) |
| **Discovered** | 2026-04-27 follow-up to BP-248 |
| **Root cause** | Starlette `BaseHTTPMiddleware.__call__` has an early return: `if scope["type"] != "http": await self.app(scope, receive, send); return`. For WebSocket ASGI scopes (`scope["type"] == "websocket"`), `dispatch()` is never called. Any middleware extending `BaseHTTPMiddleware` is completely bypassed for WebSocket connections, regardless of the `Upgrade: websocket` header. `InternalJWTMiddleware` therefore never sets `websocket.state.user_id`, so the handler always hits the `not user_id_raw` guard and closes with code 4001 → HTTP 403. |
| **Symptom** | WebSocket always returns HTTP 403 (close code 4001) even with a valid `?token=` query param. The path is correct (BP-248 fixed). The token is valid. `Content-Type: text/plain, Content-Length: 0` in the response is the signature of a WS close-before-accept. |
| **Fix** | Add inline JWT validation directly in the WebSocket handler. Read `token = websocket.query_params.get("token")`, get `public_key = websocket.app.state._internal_jwt_public_key`, decode with `jwt.decode()` with `issuer="worldview-gateway"`. Store `skip_verification` flag on `app.state` so test/dev mode also works. |

### Prevention

- Any authentication that must apply to WebSocket connections MUST be done inline in the WebSocket route handler, NOT in `BaseHTTPMiddleware` subclasses.
- Starlette's `BaseHTTPMiddleware` is HTTP-only. Use a raw ASGI middleware (implementing `__call__` directly checking `scope["type"]`) if you need to intercept both HTTP and WebSocket scopes.
- The middleware code that reads `Upgrade: websocket` headers is testing the HTTP upgrade request (before connection, type="http") — this works in tests using ASGITransport but NOT for real WebSocket ASGI connections (type="websocket").
- Pattern: store the RSA public key and `skip_verification` flag on `app.state` during startup so WebSocket handlers can access them without importing the middleware class.

**Regression test**: `services/alert/tests/unit/api/test_alerts_api.py::TestWebSocketRoute::test_ws_inline_validation_no_token_rejects`

---

---

## BP-250 — Python StrEnum Lowercase vs TypeScript Uppercase AlertSeverity Mismatch

| Field | Value |
|-------|-------|
| **Service** | S10 alert → worldview-web `components/dashboard/RecentAlerts.tsx`, `lib/utils.ts` |
| **Severity** | HIGH (TypeError crash in React render → root error boundary fires → "Something went wrong" page) |
| **Discovered** | 2026-04-27 |
| **Root cause** | Python `AlertSeverity` is a `StrEnum` with lowercase values (`"low"`, `"critical"`). The TypeScript `AlertSeverity` union is `"LOW" | "MEDIUM" | "HIGH" | "CRITICAL"` (uppercase). `severityColor()` in `lib/utils.ts` had a `switch` with only uppercase cases and NO `default` branch. When REST alerts with lowercase severity arrive, `severityColor("low")` hits no case and returns `undefined`. Destructuring `const { text, bg } = undefined` throws `TypeError: Cannot destructure property 'text' of undefined` — a synchronous render-time crash caught by the root error boundary. |
| **Symptom** | `app/error.tsx` "Something went wrong" appears after login when seeded alerts exist. `console.error("[ErrorBoundary caught] TypeError: Cannot destructure property 'text' of undefined"`. |
| **Fix** | (1) `severityColor()`: change `severity` param type to `string`, add `.toUpperCase()` before switch, add `default` fallback. (2) `RecentAlerts.tsx`: normalise severity to uppercase when mapping REST response to `AlertPayload`. (3) `AlertStreamContext.tsx`: normalise WS-stream severity to uppercase in `dispatch()`. |

### Prevention

- Never use TypeScript string union types to match Python `StrEnum` values without explicit case normalization. Python `StrEnum` values are the raw string (lowercase by convention). TypeScript enums are often uppercase by convention.
- `switch` statements over string values MUST have a `default` branch, especially when the input may come from external API responses at runtime (not enforced by TypeScript's type system).
- Use `.toUpperCase()` normalization at the boundary (API response → React state) rather than defending everywhere in the render tree.

---

## BP-251 — S9 Passthrough Returns Upstream Contract Instead of Frontend Contract

| Field | Value |
|-------|-------|
| **Service** | api-gateway (S9) → any frontend |
| **Severity** | CRITICAL (frontend receives incompatible schema; widget silently empty or crashes) |
| **Discovered** | 2026-04-28 |
| **Root cause** | A proxy route in `proxy.py` used `return Response(content=resp.content, ...)` to forward the raw upstream response. The upstream service (S6 NLP Pipeline) has its own domain contract (`{items:[...]}` with `signal_type`/`confidence`/`detected_at`) that does not match the frontend API contract (`{signals:[...]}` with `label`/`score`/`created_at`). The response passes mypy and the route has a non-None return, so this isn't caught statically. |
| **Symptom** | Frontend widget shows empty (0 items) or fails to render. No error in S9 logs — only the frontend console shows "Cannot read property 'label' of undefined". |
| **Fix** | Add a transform layer in S9 that maps upstream fields to frontend fields. Never pass raw upstream responses through when the contracts differ. |

### Prevention

- Every S9 proxy route that transforms data MUST have a unit test that asserts the **output shape** (field names, envelope key), not just `resp.status_code == 200`.
- When writing a new proxy route: check if S9's `types/api.ts` and the upstream service's API schemas match. If they differ, add a transform and test it.
- Pattern: upstream `items` array → frontend named key (e.g., `signals`, `markets`, `articles`) almost always requires a transform.

---

---

## BP-251 — SnapTrade "User Already Registered" (409) Returns 503 After DB Wipe

| Field | Value |
|-------|-------|
| **Service** | S1 portfolio — `application/use_cases/brokerage_connection.py` |
| **Severity** | HIGH (brokerage connection initiation fails with 503 after every `make dev-rebuild`) |
| **Discovered** | 2026-04-28 investigation |
| **Root cause** | SnapTrade is a persistent external service. After a DB wipe (`make dev-rebuild`), `portfolio_db` is fresh but SnapTrade still has the demo user registered (user_id_hint = `01900000-...0010`). `SnapTradeClient.register_user()` correctly detects the 409 and raises `BrokerageApiError(reason="already_exists")`. The `InitiateBrokerageConnectionUseCase` did not catch this — it propagated to the exception handler which maps `BrokerageApiError → HTTP 503`. |
| **Symptom** | `POST /api/v1/brokerage-connections` → 503. Portfolio logs show `snaptrade_user_already_registered` warning immediately followed by the 503 response. Reproduces on every fresh dev rebuild. |
| **Fix** | `InitiateBrokerageConnectionUseCase` now catches `BrokerageApiError(reason="already_exists")` and applies two recovery paths: (a) credentials in DB → reuse stored `snaptrade_user_id/secret` to generate a new portal URL; (b) credentials lost (DB wiped) → call `brokerage_client.delete_user()` + re-register fresh. `delete_user` method added to `IBrokerageClient`, `SnapTradeClient`, and `FakeBrokerageClient`. |

### Prevention

- External services (SnapTrade, Stripe, Plaid) maintain state independently of the local DB. After any DB wipe, existing registrations in the external service will return "already exists" errors. The use case layer MUST handle these gracefully with explicit recovery logic — never let external API errors bubble up as 503 without a fallback.
- All `BrokerageApiError` catches must distinguish `reason == "already_exists"` (recoverable) from other SDK errors (genuinely unavailable → 503 is correct).
- Add `delete_user` / de-registration to the `IBrokerageClient` protocol alongside `register_user` so recovery paths can always be implemented without protocol changes.

**Regression tests**: `TestInitiateBrokerageConnection::test_already_registered_reuses_existing_db_credentials`, `test_already_registered_no_db_creds_deletes_and_reregisters`


---

---

## BP-252 — LLM Wraps Output in Markdown Code Fence Despite Prompt Saying "Return Markdown"

| Field | Value |
|-------|-------|
| **Service** | rag-chat (S8) / any service using an LLM for text generation |
| **Severity** | MAJOR (user sees raw ` ```markdown ``` ` backticks instead of formatted content) |
| **Discovered** | 2026-04-28 |
| **Root cause** | Meta-Llama-3.1-8B-Instruct (and similar instruction-tuned models) interpret "respond in markdown" as meaning they should wrap the entire response in a ` ```markdown ``` ` code fence. This is the model's interpretation of "show markdown" vs "use markdown formatting". The `_strip_reasoning()` function stripped `<think>` blocks but had no code-fence stripping. |
| **Symptom** | Frontend ReactMarkdown renders ` ```markdown ``` ` as a code block, displaying raw backticks and the word "markdown" at the top of the brief. |
| **Fix** | In `_strip_reasoning()` (or equivalent post-processing function), apply `_CODE_FENCE_RE = re.compile(r"^\s*\`\`\`(?:markdown)?\s*\n?(.*?)\n?\s*\`\`\`\s*$", re.DOTALL)` after reasoning-block stripping. |

### Prevention

- Any LLM output used as-is in a frontend component MUST be post-processed to strip: (1) `<think>…</think>` blocks, (2) outer markdown code fences, (3) orphaned citation markers.
- Add a unit test that feeds a code-fenced response through the stripping function and asserts the fences are removed.
- When the Valkey briefing cache is populated, clear `briefing:*` keys after deploying a fix to `_strip_reasoning()` — otherwise the old (broken) cached content is served for up to the cache TTL.

---

---

## BP-252 — S10 AlertSeverity StrEnum Returns Lowercase; Frontend Expects Uppercase

| Field | Value |
|-------|-------|
| **Service** | S10 alert → frontend (worldview-web) |
| **Severity** | HIGH (all severity indicators visually broken; switch/comparison mismatches produce invisible UI elements) |
| **Discovered** | 2026-04-28 investigation (PLAN-0045) |
| **Root cause** | S10's `AlertSeverity` StrEnum is defined as `LOW = "low"`, `MEDIUM = "medium"`, `HIGH = "high"`, `CRITICAL = "critical"` (all lowercase). The Python route serialises with `severity=str(alert.severity)` which produces the lowercase string. The frontend TypeScript type `AlertSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"` expects uppercase. `AlarmsPanel.severityDotClass()` switch has uppercase cases — falls through on lowercase input, returns `undefined`, producing no CSS class (invisible dots). |
| **Symptom** | Severity indicator dots in `AlarmsPanel` are invisible regardless of alert severity. `RecentAlerts` widget already applies `.toUpperCase()` correctly — only `AlarmsPanel` is broken. |
| **Fix** | In `AlarmsPanel.severityDotClass()`, normalise input: `const norm = severity.toUpperCase() as Alert["severity"]`. Apply same defensive normalisation anywhere `Alert.severity` is used in conditionals or switches. Alternatively, add `.toUpperCase()` when mapping REST alerts in `AlarmsPanel` (same pattern as `RecentAlerts`). |

### Prevention

- When consuming Pydantic StrEnum values from Python APIs in TypeScript, always verify whether the enum serialises as upper or lowercase. Python `StrEnum` preserves the assigned value (`LOW = "low"` → `"low"`), NOT the Python attribute name.
- Contract tests should verify the `severity` field casing against the TypeScript type.
- Frontend components consuming `Alert.severity` should normalise to uppercase at the mapping boundary (gateway method or context), not deep inside rendering logic.

---

---

## BP-253 — Price Change Always Zero: Resolver _build() Missing prev_close Parameter

| Field | Value |
|-------|-------|
| **Service** | market-data (S3) |
| **Severity** | MAJOR (all market quotes show `change=0.0, change_pct=0.0` regardless of actual price movement) |
| **Discovered** | 2026-04-28 |
| **Root cause** | `PriceSnapshotResolver._build()` always set `price_change=None` with the comment "computed in W1-9". W1-9 of PLAN-0036 was never implemented. `_build()` is called from all resolver steps (1–4) with no access to `ohlcv_bars`. S9 `_map_price_snapshot_to_quote()` converts `None→0.0`. |
| **Symptom** | Every instrument shows `change: 0.0, change_pct: 0.0` in the TopBar, portfolio, and watchlist despite real price movements. |
| **Fix** | Add `_prev_daily_close(bars, latest)` helper that finds the second-most-recent 1d bar. Add `prev_close: Decimal | None = None` to `_build()`. At Step 5 (DAILY_CLOSE), pass `prev_close=_prev_daily_close(ohlcv_bars, bar_1d)`. After deploying, flush `price_snapshot:*` Valkey keys (2h TTL) to bypass stale cached snapshots. |

### Prevention

- Resolver fallback chains that progressively lose data context (e.g., Step 1 has quote + OHLCV; Step 5 has only OHLCV) MUST explicitly propagate fields like `prev_close` to downstream builders.
- "TODO: computed in W1-X" comments in domain code are tech debt trackers — they MUST have a corresponding task in the plan. Never deploy code that permanently returns `None` for a field the frontend depends on.
- After deploying price-calculation fixes, always flush Valkey price snapshot cache to avoid serving stale zero-change values.

---

---

## BP-265 — Gateway Hard-Coded Empty Collections Mask Missing Endpoints

**Category**: Frontend / Gateway / API contract
**Severity**: HIGH
**First seen**: 2026-04-28 (PLAN-0046 Wave 2 — F-003)
**Services**: worldview-web (gateway), api-gateway (S9), portfolio (S1)

**Symptoms**:
- A real watchlist with N members rendered as the empty state ("Search above to add your first symbol.").
- Adds appeared to succeed (POST 201) but the row never appeared.
- Quotes never loaded for watchlist members because the upstream member array was [].

**Root cause**:
`apps/worldview-web/lib/gateway.ts::mapRawWatchlist` returned a hard-coded
`members: [] as WatchlistMember[]` because S1 had no `GET /watchlists/{id}/members`
endpoint at the time. The placeholder was never revisited when the rest of the
UI started consuming `watchlist.members`. The gateway was the ONLY layer that
"knew" the data was missing, but it returned a structurally valid empty array
that downstream code accepted as truth.

**Fix**:
1. Add backend endpoint: `GET /v1/watchlists/{id}/members` (S1) + S9 proxy.
2. Denormalise `ticker`/`name`/`instrument_id` onto `watchlist_members` at
   add-time so the read path stays a single-table query (R9).
3. Refactor `mapRawWatchlist` to accept an optional `members` array — callers
   that have it pass it in; callers that don't (create/rename payloads) get a
   `[]` default, but `getWatchlist` now fans out to `getWatchlistMembers` so
   the consumer always receives real data.
4. UI fetches members lazily for the active tab via
   `useQuery(["watchlist-members", id])`; cache invalidated on add/remove.

**Prevention**:
- Collections returned by gateway mappers must come from a real fetch — never
  default to `[]` because "we don't have the endpoint yet". Surface it as a
  TypeScript error or an explicit unimplemented stub instead.
- When adding a new collection field to a frontend type, audit every mapper
  that constructs that type and verify each populates it from a real source.
- Code-review checklist item: "any `[]` literal in a gateway mapper is
  flagged for justification".

**Regression test**:
- Backend: `services/portfolio/tests/unit/test_use_cases_watchlist.py::test_list_members_returns_members_for_owner`
- Gateway: `services/api-gateway/tests/test_s9_wave2_proxy.py::test_watchlist_members_list_proxies_to_s1`

---

## BP-267 — Screener-Based `getTopMovers()` Hardcodes `price: 0`

**Category**: Frontend / gateway
**Severity**: MAJOR
**Affected areas**: PreMarketMoversWidget, getTopMovers gateway function
**First seen**: 2026-04-28 (PLAN-0045 QA follow-up)

**Symptoms**:
- TOP MOVERS widget shows "$0.00" for all instrument prices
- The comment in gateway.ts explicitly states `price: 0, // Not available from screener`

**Root Cause**:
`getTopMovers()` calls the screener endpoint which returns `daily_return %` but no current price. A separate quote lookup would be needed for each instrument. The gateway transform hardcodes `price: 0` as a known placeholder.

The `MoverRow` component checks `mover.price != null ? ...` which is always truthy (0 is not null), so it renders "$0.00".

**Fix Applied**:
In `MoverRow`, changed condition to `mover.price != null && mover.price > 0`. Now shows "—" for unavailable prices.

**Prevention**:
- Numeric fields that represent prices/quantities must be treated as "unavailable" when 0, not just when null
- Document the `price: 0` placeholder in the type definition with a note that downstream renders must guard `> 0`

---

## BP-291 — `h-full` Loading Skeleton in `min-h-*` Parent Produces Black Overlay

**Category**: Frontend / Loading-state CSS
**Severity**: HIGH (visual defect on every page load)
**Affected areas**: any React component rendered inside a parent that applies `min-h-[X] bg-card` and uses `h-full` on its loading skeleton wrapper
**First seen**: 2026-04-29 (PLAN-0053 T-A-1-02 — user-reported "black widget on Holdings tab top")

**Symptoms**:
- During initial data load, a tall dark panel appears at the top of the page that "occupies half the viewport".
- Once data arrives the panel reflows to its proper height; scrolling down looks correct.
- Looks like a z-index/stacking-context bug but isn't.

**Root Cause**:
Pattern in the parent (correct, intentional): `<div className="min-h-[200px] bg-card ...">` reserves a 200px floor so the loaded card's height is stable across data states.

Pattern in the child loading branch (wrong): `if (isLoading) return <div className="flex flex-col gap-2 h-full">{skeletons}</div>`. The `h-full` makes the skeleton container fill the parent's enforced 200px. The skeleton items themselves sum to ~30-40px, leaving ~160px of empty `bg-card` (dark) space — the visible "black panel".

**Fix**:
Remove `h-full` from the loading-state wrapper. Let the skeleton items stack to natural height. The parent's `min-h-[200px]` still enforces the floor for the loaded card.

```tsx
// BEFORE (wrong)
if (isLoading) return <div className="flex flex-col gap-2 h-full">{skeletons}</div>

// AFTER (correct)
if (isLoading) return <div className="flex flex-col gap-2">{skeletons}</div>
```

**Prevention**:
- When the parent uses `min-h-*`, the child's loading skeleton should NOT use `h-full`. Only the loaded data branch (where content fills the panel intentionally) should use `h-full`.
- During code review, flag any `if (isLoading) return <div className="... h-full">` inside a component whose parent uses `min-h-*`.
- Snapshot tests at scroll position 0 during loading are the cheapest catch.

---

## BP-295 — Next.js 15 Page File Cannot Export Arbitrary Symbols (PageProps `never` Constraint)

**Category**: Build / framework constraint
**Severity**: CRITICAL (typecheck + production build fail)
**Affected areas**: Any `app/**/page.tsx` (App Router page) that exports symbols beyond the framework-recognized set.
**First seen**: 2026-04-30 (PLAN-0059 W0 commit `99b8bcf7`, fix F-001).

**Symptoms**:
- `pnpm typecheck` fails with `error TS2344: Type 'OmitWithTag<typeof import(".../page"), "default" | "viewport" | "metadata" | ... | "experimental_ppr", "">' does not satisfy the constraint '{ [x: string]: never; }'. Property 'X' is incompatible with index signature. Type 'Y' is not assignable to type 'never'.`
- `pnpm build` fails with the same error during type generation.
- `next dev` may succeed because the strict PageProps check is bypassed in dev.

**Root Cause**:
Next.js 15 App Router page files have a strict type constraint on what they may export. The recognized set is `default`, `metadata`, `viewport`, `dynamic`, `revalidate`, `fetchCache`, `runtime`, `preferredRegion`, `experimental_ppr`, `generateStaticParams`, `generateMetadata`, `generateViewport`. Any other export is mapped to type `never`, so `export const FOO = ...` collides with `Record<string, never>`.

In the Wave A diff a constant was made `export` so a test file could import it directly (avoiding a fragile dynamic import of the page module). The export survived ESLint/lint but blew up `tsc` and `next build`.

**Fix**:
Move the constants to a sibling module:
```ts
// app/some-route/page.tsx — page only
import { ERROR_MESSAGES } from "./error-messages";

// app/some-route/error-messages.ts — testable module
export const ERROR_MESSAGES = { ... };
```
Tests import from `@/app/some-route/error-messages` directly. Both the page and the test see the same constant; the page module stays clean of arbitrary exports.

**Prevention**:
- Lint rule (custom): forbid named exports from any `app/**/page.{ts,tsx}` other than `default` + the framework-recognized list.
- Code review check: if a page file has any `export const/function/class` other than the default component, ask “why isn’t this in a sibling module?”.
- Run `pnpm typecheck` AND `pnpm build` (not just lint) before committing — `next lint` does not catch this.

**Regression test**: `apps/worldview-web/__tests__/wave-a-config.test.ts` (`F-001 — ERROR_MESSAGES not exported from app/callback/page.tsx`).

---

---

## BP-296 — CSS Comment Containing `*/` Substring Breaks PostCSS

**Category**: Build / parser
**Severity**: CRITICAL (production build fails; dev `next dev` may tolerate it)
**Affected areas**: any `.css` file with comments that contain the literal sequence `*/` inside the comment body — typically when documenting Tailwind glob patterns (`text-amber-*/bg-amber-*`).
**First seen**: 2026-04-30 (PLAN-0059 W0, fix F-001b).

**Symptoms**:
- `next build` (or `pnpm build`) fails with: `Syntax error: <path>/globals.css Unknown word (NN:M)` where line NN is inside what was meant to be a `/* ... */` comment.
- The Docker image build of the frontend fails at the `pnpm build` stage; container falls back to the previous successful image (`up 21 hours`), making the bug invisible in `docker ps`.
- Dev mode (`pnpm dev`) often tolerates the parser oddity (CSS HMR is more forgiving), so the bug is invisible until production build.

**Root Cause**:
CSS uses `/* ... */` for comments. The first `*/` after `/*` closes the comment; everything after is parsed as CSS top-level. When a comment author writes `text-amber-*/bg-amber-*` to denote “any utility class matching `text-amber-*` or `bg-amber-*`”, the substring `*/` inside `text-amber-*` terminates the comment early. The text `bg-amber-* in AI panels...` then lands at top level → "Unknown word" parse error.

**Fix**:
Rewrite the comment to remove the inline `*/` sequence:
- Replace `text-amber-*/bg-amber-*` with `text-amber-NNN and bg-amber-NNN` (descriptive)
- Or with `text-amber-* / bg-amber-*` (space breaks the `*/` substring)
- Or escape: `text-amber-* /bg-amber-*`

**Prevention**:
- ESLint plugin (custom or stylelint `comment-no-empty` extended): scan CSS comments for the substring `*/` and warn.
- CI gate: `pnpm build` runs on every PR (not just `pnpm lint` + `pnpm typecheck`) so production CSS parsing is exercised.
- Code review: when documenting Tailwind glob patterns inside CSS comments, prefer `text-amber-NNN` (placeholder) over `text-amber-*` (real glob).

**Regression test**: catching this requires a successful `pnpm build` in CI.

---

---

## BP-297 — Docker `--build` ≠ `--no-cache`: Stale Frontend Bundle in Live Container

**Category**: Deploy / build cache
**Severity**: HIGH (silent — visual changes do not reach production)
**Affected areas**: any Next.js `output: standalone` Docker image that uses `pnpm build` inside the multi-stage Dockerfile.
**First seen**: 2026-04-30 (PLAN-0059 W0 QA).

**Symptoms**:
- Source files (`globals.css`, `next.config.ts`, etc.) are committed and look correct in `git diff`.
- `docker compose ... up -d --build worldview-web` reports success.
- The running container’s `Status` still shows `Up 21 hours`, NOT recently restarted.
- `curl /_next/static/css/<hash>.css` serves the OLD bundle — CSS hash is unchanged from before the commit.
- New brand assets (`/icon.svg`, `/manifest.webmanifest`, etc.) return 404.

**Root Cause**:
Docker's BuildKit layer cache reuses the prior `RUN pnpm build` output when its inputs (the COPY layer’s file digests) match. In a monorepo where the build context is large, BuildKit may decide a layer hasn’t changed even when source files within it have, depending on `.dockerignore` and `COPY` granularity.

`docker compose build` only forces a rebuild of the configured stages, not of cache-reusable layers. The `--build` flag on `up` is shorthand for "build first if needed", but it does NOT pass `--no-cache` to the underlying build.

**Fix**:
- Use `docker compose -f infra/compose/docker-compose.yml build --no-cache worldview-web` after any frontend visual change.
- Then `docker compose ... up -d --force-recreate worldview-web`.
- Verification (canary): `curl /_next/static/css/$(curl / | grep -oE '/_next/static/css/[a-f0-9]+\.css' | head -1) | grep <new-token>` — the hash must change AND the new token must appear.

**Prevention**:
- CI deploy job: always pass `--no-cache` to the frontend image build.
- Add a deploy smoke test: after frontend container restart, assert that the served CSS bundle contains a sentinel string from the latest commit.
- Add an `ARG GIT_SHA` to the Dockerfile that gets baked into a build label, so the image is bust-able by passing a fresh SHA.

**Regression test**: deploy smoke test (CI) — `apps/worldview-web/__tests__/wave-a-tokens.test.ts` covers the source-level invariants; the deploy-time canary is operational, not a unit test.

---

## BP-298 — `e.isTrusted` Guard Breaks `fireEvent`-Based Hotkey Tests

**Category**: Frontend / test infrastructure
**Severity**: HIGH (blocks a critical security hardening)
**Affected areas**: Any document-level keyboard listener that checks `e.isTrusted` + any test using `@testing-library/react`'s `fireEvent`.
**First seen**: 2026-04-30 (PLAN-0059-B QA pass).

**Symptoms**:
- Adding `if (!e.isTrusted) return;` at the top of a `keydown` listener causes all `fireEvent.keyDown(document, ...)` tests to silently fail — handlers are never called.
- The fix is correct for production; the failure is only in test.

**Root Cause**:
`fireEvent.keyDown()` from `@testing-library/react` internally calls `new KeyboardEvent('keydown', options)` and dispatches it. Synthetic events created via the `KeyboardEvent` constructor always have `isTrusted = false` per the Web spec — the browser only sets `isTrusted = true` on events originating from real user interaction.

**Fix**:
Create a `fireTrustedKey` helper in the test file or a shared test utility:
```ts
function fireTrustedKey(
  element: Document | HTMLElement,
  key: string,
  options: KeyboardEventInit = {}
): void {
  const evt = new KeyboardEvent("keydown", {
    key, bubbles: true, cancelable: true, ...options
  });
  Object.defineProperty(evt, "isTrusted", { value: true });
  element.dispatchEvent(evt);
}
```
Replace all `fireEvent.keyDown(document, ...)` calls in the affected test file with `fireTrustedKey(document, ...)`.

**Prevention**:
- Add the `fireTrustedKey` helper to `apps/worldview-web/vitest.setup.ts` as a named export so all keyboard tests can use it.
- Add a lint rule (or test) that bans `fireEvent.keyDown` in files that test keyboard listeners.

---

## BP-300 — `isMountedRef` Not Reset on Effect Re-Run → WebSocket Permanently Dead After Token Refresh

**Category**: React / WebSocket / reconnect
**Severity**: CRITICAL
**Affected areas**: `AlertStreamContext.tsx` and any component that uses `isMountedRef` as an unmount guard inside a multi-dependency `useEffect`.
**First seen**: 2026-04-30 (PLAN-0059-B stability review, F-STAB-002).

**Symptoms**:
- After a token refresh (or any dependency change that re-runs the WebSocket `useEffect`), the WS connects successfully.
- When the WS closes (network hiccup, server restart), no reconnect is scheduled.
- The AlertStream badge shows 0 alerts forever after the first token refresh, even though new alerts are being pushed.

**Root Cause**:
`isMountedRef` is initialized to `true` (`useRef(true)`) and set to `false` in the effect's cleanup function. When the effect re-runs (due to auth state change), the cleanup runs first — setting `isMountedRef.current = false` — but the new effect body never resets it to `true`. All subsequent `onclose` handlers check `if (!isMountedRef.current) return;` and bail out, silently skipping the reconnect timer.

```tsx
// Bad — isMountedRef stays false after first token refresh
useEffect(() => {
  void connect(); // connects OK
  return () => {
    isMountedRef.current = false; // cleanup sets false
    // ...
  };
}, [isAuthenticated, accessToken, connect]);
// Next run: cleanup fires (sets false), then effect body runs WITHOUT resetting to true.
// The onclose check fires and returns early — no reconnect ever scheduled.

// Good — reset at the top of every effect body run
useEffect(() => {
  isMountedRef.current = true; // <-- reset before any async work
  void connect();
  return () => {
    isMountedRef.current = false;
    // ...
  };
}, [isAuthenticated, accessToken, connect]);
```

**Fix**:
Add `isMountedRef.current = true;` as the first statement of the useEffect body.

**Prevention**:
- Whenever `isMountedRef` (or any boolean liveness ref) is set to `false` in cleanup, always add the corresponding reset to `true` at the top of the effect body.
- Code review heuristic: if you see `isMountedRef.current = false` in a cleanup inside a multi-dependency effect, check that the effect body resets it.

**Regression test**: `__tests__/AlertStreamContext.test.tsx` — the test for reconnect after token refresh would catch this.

---

## BP-302 — `next.config.ts` `env:` Default Masks `NEXT_PUBLIC_*` Absence Check

**Affected areas**: `apps/worldview-web/next.config.ts`; any `login/page.tsx`-style feature-gate that reads a `NEXT_PUBLIC_*` env var to detect whether a service is configured.

**First seen**: 2026-04-30 (O-AU-01 investigation — dev login button absent after security fix).

**Symptoms**:
- A feature is intentionally gated on `!process.env.NEXT_PUBLIC_SOME_VAR` (var absent = feature enabled).
- The feature never activates, even in local dev where the var is not set in `.env.local`.

**Root Cause**:
`next.config.ts` `env:` block uses `??` to supply a fallback:
```ts
NEXT_PUBLIC_SOME_VAR: process.env.NEXT_PUBLIC_SOME_VAR ?? "http://localhost:default",
```
Next.js evaluates this at build/startup time and bakes the string into the bundle. `process.env.NEXT_PUBLIC_SOME_VAR` inside browser code is always the fallback string — never `undefined` — so absence checks always fail.

**Fix**:
Remove the `??` fallback for any `NEXT_PUBLIC_*` var whose **absence** is a meaningful signal:
```ts
NEXT_PUBLIC_SOME_VAR: process.env.NEXT_PUBLIC_SOME_VAR,  // no default — absence is intentional
```
Ensure consuming code handles `undefined` gracefully (error message, disabled UI, etc.).

**Prevention**:
- Only use `?? default` for vars that are **always required** (WS URL, app name). Never for vars whose absence signals a "dev mode" or "feature not configured" state.
- Add a code comment explaining why no default is provided.

---

---

## BP-305 — Document-Level `copy` Listener Hijacks Native Selection Inside Component

**Affected areas**: any component that wants to override clipboard behavior (e.g. DataTable's "selected rows → TSV" feature). Originated in `apps/worldview-web/components/ui/data-table/data-table.tsx`.

**First seen**: 2026-05-01 (PLAN-0059 Wave F QA iter-1, security + correctness agents).

**Symptoms**:
- Component installs `document.addEventListener("copy", handler)` to override the clipboard payload.
- User selects PLAIN TEXT inside a cell (e.g. wants to copy a ticker symbol) and presses ⌘C.
- The handler fires, sees the component has focus, and `e.preventDefault()` + writes the row TSV instead — destroying the user's intended selection.

**Root Cause**:
1. Listener is at document level, so it fires for every copy event in the page (not just events originating inside the component).
2. The handler does not check `window.getSelection()` — it overrides regardless of whether a real text selection exists.

**Fix**:
1. Attach the listener to the COMPONENT'S root element, not document. Copy events bubble from contentEditable / selectable subtrees.
2. Skip the override when a real text selection exists:
```ts
const onCopy = (e: ClipboardEvent) => {
  const sel = window.getSelection();
  if (sel && !sel.isCollapsed && sel.toString().length > 0) return; // let native copy
  // ... override path
};
el.addEventListener("copy", onCopy);
```

**Prevention**:
- Never use `document`-level clipboard listeners unless the override is intentionally global.
- Always check `window.getSelection()` before hijacking — text-selection clipboard is a user expectation, not a feature opt-in.

---

---

## BP-307 — Compound Sign Operators Double-Negate in Numeric Parser

**Affected areas**: any parser that combines accounting parens (negative) with explicit `-` sign in user input. Originated in `apps/worldview-web/lib/format/parse-shorthand.ts`.

**First seen**: 2026-05-01 (PLAN-0059 final strict QA agent).

**Symptoms**:
- Input `(-100)` is parsed as `+100` instead of `-100`.
- Input `(-1.5m)` parsed as `+1_500_000` instead of `-1_500_000`.
- Cause: parser computed `negate ? -out * signMul : out * signMul`. With `negate=true` AND `signMul=-1`, the formula evaluates to `(-out) * -1 = +out`, silently inverting sign for accounting-style inputs.

**Root Cause**:
Two boolean indicators of negativity (paren-wrap, explicit `-`) were applied compositionally as if they were independent sign multipliers. They are NOT — accounting `(N)` and `-N` are equivalent representations of the same negative; `(-N)` is non-standard but unambiguously a single negative, not a double.

**Fix**:
Collapse to a single sign multiplier. Parens override inner sign:
```ts
const sign = negate ? -1 : signMul;
return n * sign;
```

**Prevention**:
- For ANY financial / numeric parser that supports multiple sign-syntaxes, write a truth table (paren × inner-sign × leading-+ × negative-suffix) in the test file.
- Test the FOUR specifically problematic inputs: `(N)`, `-N`, `(-N)`, `(+N)`.
- In code review, if a parser has both `negate` and `signMul` variables, demand a single derived `sign` and a test asserting all combinations.

---

---

## BP-308 — Backend/Frontend Field-Name Drift in Nested Payloads (Citation `source` vs `source_name`)

**Category**: Contract drift / serialization
**Severity**: HIGH (page-crashing on user click)
**First seen**: 2026-05-01 (chat thread click error)
**Services**: rag-chat (S8) → S9 → worldview-web

**Symptoms**:
- Clicking an old chat thread throws `TypeError: Cannot read properties of undefined (reading 'toLowerCase')` at `chat/page.tsx`.
- Citations show as blank or `0%` relevance, or the assistant message panel fails to render.
- Affected only threads that contain at least one assistant message with citations — empty/new threads work fine, masking the bug from new-user smoke tests.

**Root cause**:
The rag-chat `ThreadDetailResponse` serialises citations with the canonical `{ id, source_name, confidence, item_type, entity_name, ... }` shape (see `services/rag-chat/src/rag_chat/api/routes/threads.py::_citation_to_dict`). The frontend `Citation` type in `apps/worldview-web/types/api.ts` and consumers (`chat/page.tsx`, `CitationBar`, `CitationList`) still use the legacy `{ article_id, source, relevance_score }` names from PRD-0028. There is no contract test pinning the wire shape on either side, so the drift went unnoticed until a thread with citations was opened.

The same family caused the earlier `getThreads()` envelope mismatch — see comment in `lib/gateway.ts:1937`. That fix only patched the LIST shape; the per-thread DETAIL shape still leaks the canonical citation fields.

**Example**:
```ts
// Bad — direct passthrough
async getThread(id: string): Promise<Thread> {
  return apiFetch<Thread>(`/v1/threads/${id}`, { token });
}
// chat/page.tsx then crashes:
const src = cite.source.toLowerCase(); // cite.source is undefined
```

```ts
// Good — gateway-level normalization
async getThread(id: string): Promise<Thread> {
  const raw = await apiFetch<Thread>(`/v1/threads/${id}`, { token });
  return normalizeThread(raw); // maps source_name→source, id→article_id, confidence→relevance_score
}
```

**Fix**:
1. Add a per-payload normalizer at the gateway boundary (single point of translation).
2. Make it tolerant: prefer legacy fields if present, fall back to canonical, default to safe empty strings/zeros so `.toLowerCase()` etc. cannot crash.
3. Apply to every endpoint that returns the same nested type (here: `getThread` AND `updateThread`, since PATCH also returns `ThreadDetailResponse`).
4. Add a regression test pinning the contract — see `__tests__/gateway.test.ts::"createGateway() — getThread citation normalization"`.

**Prevention**:
- Whenever a frontend type and a backend Pydantic schema describe "the same object" but live in different repos/files, treat the gateway's per-endpoint mapper as a hard interface — do NOT use `apiFetch<FrontendType>` as identity. Always normalize.
- Code review red flag: a gateway method whose body is a single `apiFetch<T>(...)` for any endpoint that returns nested objects with field names that differ from the frontend type. Single-level primitive returns are fine; nested object trees are not.
- Smoke test for chat-like features must include "open an existing record with prior data," not just "create a new one then look at it."

**Regression test**: `apps/worldview-web/__tests__/gateway.test.ts::"createGateway() — getThread citation normalization"` (3 cases: canonical → legacy mapping, pathological/empty citation, idempotent legacy passthrough).

---

## BP-330 — Screener `entity_id` Slug Never Matched a Real Entity Page

**Category**: Frontend
**Symptom**: Clicking a screener row navigates to `/instruments/entity-aapl` (a slug) instead of `/instruments/01900000-0000-7000-8000-000000001001` (UUID). The entity page 404s because the slug is not a real entity_id.
**Root cause**: When the backend omits `entity_id` from the screener response, the gateway transformer previously synthesized `entity-${ticker.toLowerCase()}`. This pattern was copied from an early IndexTicker convention but was never valid for entity pages — the backend always emits UUIDv7 strings for entity IDs.
**Fix**: Fall back to `String(row["instrument_id"])`, not a slug. `instrument_id` is the same UUID the entity page uses as its path segment.

```ts
// lib/api/screener.ts — runScreener transformer
entity_id: (row["entity_id"] as string | undefined) ?? String(row["instrument_id"] ?? ""),
```

**Prevention**: Never synthesize entity IDs from human-readable strings (tickers, names). Only use values returned by the backend. Treat any `entity-*` pattern in a URL as a bug signal.

**Regression test**: `apps/worldview-web/__tests__/screener-entity-id.test.ts` (3 cases: missing entity_id → instrument_id fallback; entity_id present → passthrough; no slug pattern in output).

---

## BP-331 — Screener Revenue Column Always Blank: `revenue_usd` Nested Under `metrics`

**Category**: Frontend
**Symptom**: The Revenue column on the screener shows "—" for every row even when the backend returns revenue data.
**Root cause**: The backend embeds revenue as `metrics.revenue_usd` but the transformer only checked the top-level `row.revenue` key. Result: `num(row["revenue"])` always returned `null` because the field was one level deeper.
**Fix**: Check `metrics.revenue_usd` first (primary key for current backend), then `metrics.revenue` (older API versions), then `row.revenue` (top-level fallback for future schema changes).

```ts
// lib/api/screener.ts — runScreener transformer
revenue: num(metrics["revenue_usd"] ?? metrics["revenue"] ?? row["revenue"]),
```

**Prevention**: When mapping a backend response, always inspect the FULL nested structure, not just the top level. Add regression tests that verify nullable numeric columns before and after a backend API version bump.

**Regression test**: `apps/worldview-web/__tests__/screener-metric-mapping.test.ts` (4 cases: revenue_usd primary; metrics.revenue fallback; top-level row.revenue fallback; null when all absent).

---

---

## BP-332 — TanStack Table Controlled Sort Race: `getNextSortingOrder()` Captures Stale State Outside Updater

**Category**: Frontend
**Symptom**: In tests (and rarely in prod under rapid clicking), clicking a column header twice quickly sometimes cycles none→asc→asc instead of none→asc→desc. The second click seems "ignored" and the sort doesn't advance to descending.
**Root cause**: TanStack Table v8's `column.toggleSorting()` calls `column.getNextSortingOrder()` **synchronously at click time**, before the updater function is constructed. `getNextSortingOrder()` reads `column.getIsSorted()` from `table.getState().sorting` — which is the PREVIOUS committed sort state if React hasn't re-rendered yet. If a second click fires before React commits the first click's state update, TanStack computes `sortAction = 'asc'` (from-none) instead of `'desc'` (from-asc). The updater function itself correctly uses functional prev state, but the direction it will set is baked in at creation time.

In tests, `useDeferredValue` on the filtered rows creates a second low-priority render pass after the urgent one. Between the urgent render (which commits `aria-sort = "ascending"`) and the deferred render completing, TanStack's `table` instance may momentarily show a state mismatch. Using `waitFor` to wait for `aria-sort` doesn't fully guarantee TanStack's in-flight deferred pass is settled before the next click.

**Fix**: Mock `useDeferredValue` to be synchronous in screener sort tests so no deferred render window exists between clicks:

```tsx
// __tests__/screener.test.tsx
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  const syncUseDeferredValue = (
    (value: unknown) => value
  ) as typeof actual.useDeferredValue;
  return { ...actual, useDeferredValue: syncUseDeferredValue };
});
```

**Prevention**: Any test that simulates rapid sequential clicks on a TanStack-controlled sort that is bridge-proxied through `useDeferredValue` will hit this race. Apply the same mock pattern to any future test with multi-click sort assertions.

**Regression test**: `apps/worldview-web/__tests__/screener.test.tsx` — sort tests "clicking sorted column again changes sort to descending" and "clicking column third time clears sort (back to none)". Previously failed ~60% of full-suite runs; now stable.

---

## BP-335 — `z.number()` Without `.optional()` Silently Blocks RHF Submit for Empty Optional Fields

**Category**: Frontend
**Symptom**: An RHF form that uses `zodResolver` has an optional numeric field (e.g. "Avg Price (optional)"). When the field is left empty, the form never calls `onSubmit` — no network request is made, no error is shown, the submit button just does nothing.
**Root cause**: `z.number()` (and its modifiers `.positive()`, `.nonnegative()`) expects a JavaScript `number` at runtime. An empty form field stores `undefined` in RHF. Zod rejects `undefined` with `invalid_type_error: "Must be a number"`, which counts as a validation failure and causes `handleSubmit` to call `onError` (silently, if no `onError` handler is wired) instead of `onSubmit`.

**Fix**: Add `.optional()` to any schema field whose UI label says "(optional)":
```ts
avgPrice: z
  .number({ invalid_type_error: "Must be a number" })
  .nonnegative("Must be 0 or greater")
  .optional(),  // WHY: undefined is valid; onSubmit coalesces to 0 with `?? 0`
```

**Prevention**: Whenever a form field has "(optional)" in its label or is not required by the API, the Zod field must include `.optional()`. A field that is required at the Zod layer but optional in the UI will silently block submit.

**Fixed in**: `features/portfolio/components/AddPositionDialog.tsx` (`avgPrice`) — PLAN-0059 F-2.

---

## BP-336 — `user.tab()` Inside Radix Dialog Focus Trap Does Not Reliably Fire Blur in jsdom

**Category**: Frontend
**Symptom**: Tests that drive a `NumberInput` (or any commit-on-blur input) inside a Radix `Dialog` fail intermittently or consistently: the `onValueChange` callback is never called even though `user.type()` and `user.tab()` appear correct. The form's RHF field stays `undefined`, Zod validation fails, and gateway mocks are never called.
**Root cause**: `NumberInput` commits its parsed value via `onBlur`. `@testing-library/user-event` v14's `user.tab()` fires a synthetic Tab keydown, then programmatically moves focus. However, Radix UI's `@radix-ui/react-focus-trap` intercepts Tab keypresses for focus-scope management. Inside a Dialog, this focus-trap may call `event.stopPropagation()` or route focus in a way that prevents the blur event from landing on the currently-focused input element in jsdom's simulated DOM environment.

**Fix**: Use `fireEvent.blur` (wrapped in `act`) instead of `user.tab()` to commit a NumberInput inside a Dialog:
```tsx
import { render, screen, fireEvent, act } from "@testing-library/react";

async function fillNumberInput(user: ReturnType<typeof userEvent.setup>, label: string, value: string) {
  const input = screen.getByRole("textbox", { name: label });
  await user.clear(input);
  await user.type(input, value);
  // WHY fireEvent.blur not user.tab(): Radix Dialog focus-trap intercepts Tab
  // and may not fire blur on the current element in jsdom.
  await act(async () => { fireEvent.blur(input); });
}
```

**Prevention**: Any test for a NumberInput (or other commit-on-blur input) rendered inside a Radix Dialog, Sheet, or Popover should use `fireEvent.blur` to commit the value, not keyboard navigation.

**Regression test**: `apps/worldview-web/__tests__/add-position-dialog.test.tsx` — `fillQuantity()` helper uses `fireEvent.blur` — PLAN-0059 F-2.

---

## BP-357 — Unicode emoji characters render as colorful glyphs on Windows/Linux

**Symptom**: Warning/arrow/checkmark characters (⚠, ✓, →, ▴) in React TSX render as full-color emoji glyphs on Windows and inconsistently on Linux (depends on system emoji font). Design intention (inline amber warning icon) becomes a distracting multicolor symbol at 10-11px text size.

**Root cause**: These code points are in the Unicode Emoji range. When placed inside a styled `<span>`, the OS emoji font overrides the text color — Tailwind's `text-warning` has no effect because the glyph is rendered as a bitmap emoji, not a typeface glyph.

**Exceptions**: These Unicode characters ARE safe as text glyphs (not emoji) because they're in the block elements / arrows range that pre-dates the emoji standard: `—` (em-dash), `│` (box drawing), `▲`/`▼` (geometric shapes U+25B2/U+25BC) — all render reliably in `font-mono` contexts.

**Fix**: Use Lucide icons for all iconography in React components. Never use ⚠, ✓, →, ✕, ★, or any code point above U+25FF in visible UI text.

```tsx
// WRONG — renders as emoji on Windows:
<span className="text-warning">⚠ Limited coverage</span>

// CORRECT — respects text-warning color:
<AlertTriangle className="h-3 w-3 inline-block mr-1" strokeWidth={1.5} />
<span>Limited coverage</span>
```

**Prevention**: Lint rule (eslint-plugin-no-restricted-syntax on JSX text nodes containing ⚠/✓/→/✕) or code review check. The `/investigate` and `/review` checklists now flag Unicode emoji in JSX string literals.

---

## BP-354 — AI brief `[cN]` citation markers leak as raw text in lead block

**Symptom**: The AI brief lead sentence displays literal text like `[c6][c7][c10]` inline: "CBOE VIX fell to 16 [c6][c7][c10]." The citation markers appear as raw characters, not rendered links or footnotes.

**Root cause**: The backend `BriefingResponse.lead` field intentionally preserves `[cN]` markers (per schema comment: "inline [cN] markers"). The `LeadProse` component in `StructuredBrief.tsx` renders `{lead}` directly as text without stripping these markers. The frontend was expected to either render them as citation chips or strip them, but this was never implemented in `LeadProse`.

**Why markers are in the `lead` field**: The backend parses `## LEAD` block and populates `lead` with 1-3 sentences including citation references. `BriefBullet.citations` handles citation objects for the section bullets, but the lead block has no associated citations array — it references them inline only.

**Fix**: Strip `[cN]` markers from the lead before rendering:
```tsx
const cleanLead = lead.replace(/\[c\d+\]/g, "").replace(/\s{2,}/g, " ").trim();
// render {cleanLead} instead of {lead}
```

The citation context is already visible via `CitationChips` on the section bullets — stripping `[cN]` from the lead does not lose information for the user.

**Prevention**: When adding new string fields that contain markup tokens, document whether the frontend must process them. Fields like `lead` should be either (a) pre-processed by the backend or (b) have a frontend processing step documented in the component.

**Regression test**: `apps/worldview-web/__tests__/structured-brief.test.tsx` — verify lead renders without `[c` characters.

---

## BP-358 — shadcn Skeleton Primitive Uses animate-pulse — All Loading States Animated

**Context**: Bloomberg-grade terminal UI — `apps/worldview-web/components/ui/skeleton.tsx`

**Symptom**: Every data-loading skeleton in the app (instrument panel, news feed, dashboard widgets, screener rows) pulses with a fade animation. Bloomberg and Refinitiv Eikon terminals use static skeleton bars — animation signals "unstable" to professional finance users.

**Root cause**: The shadcn `Skeleton` base component sets `animate-pulse` in its default className. This cascades to every consumer without any per-callsite override.

**Fix**: Remove `animate-pulse` from `skeleton.tsx` base class; use `bg-muted/60` for lighter static placeholder appearance.

**Prevention**: Design system standard is "static skeleton bars only." Do not add `animate-pulse` to skeleton-type components. Use `animate-spin` only for explicit real-time streaming indicators (RefreshCw).

**Related**: BP-182 (no animate-pulse on any chrome element).

---

---

## BP-367 — PeerComparisonPanel: Case Mismatch on KG Edge Label + Wrong Screener Filter Format

**Context**: `apps/worldview-web/components/instrument/PeerComparisonPanel.tsx` — FundamentalsTab competitor comparison panel.

**Symptom**: Competitors panel always shows "No peer data available" even when 147+ `competes_with` relations exist in the knowledge graph.

**Root cause 1** (primary): `(graph?.edges ?? []).filter((e) => e.label === "COMPETES_WITH")` — uppercase filter. S9 proxy (`proxy.py:1649`) sets edge label from `canonical_type` which the DB stores lowercase ("competes_with"). The uppercase filter never matched any edge → `competitorEntityIds` was always empty.

**Root cause 2** (secondary): The screener queryFn used legacy `{field, operator, value}` format. Backend `ScreenFilterRequest` requires `{metric, min_value, max_value}` (pattern `^[a-z_][a-z0-9_]{0,63}$` on `metric`). Even if edges had been found, the screener call would have returned 422 or 0 results.

**Root cause 3** (architecture): The screener has no `entity_id` filter. Using screener to look up specific competitors by entity_id is architecturally unsupported — use `getCompanyOverview(entityId)` instead (works because entity_id = instrument_id per M-017 convention).

**Fix**:
1. `e.label === "competes_with"` (lowercase)
2. Replace entity_id screener call with `Promise.all(competitorEntityIds.map(id => gateway.getCompanyOverview(id)))`
3. Sector fallback: `{metric: "market_capitalization", min_value: 0, sector: gics_sector}` (correct API format)
4. Enhancement: fill remaining slots (up to 4 total) with sector peers sorted by |market_cap - current_market_cap|

**Prevention**:
- When filtering frontend graph edges by type, always verify the casing by checking `proxy.py`'s `_transform_graph_response` — canonical_type comes from DB lowercase.
- The screener API only supports metric range filters (`metric/min_value/max_value/sector`). Never attempt entity_id, ticker, or string-equality filters.
- To get fundamentals for a specific entity_id: use `getCompanyOverview(entityId)` not screener.

**Related**: BP-342 (entity_id vs instrument_id in market-data), M-017 convention (entity_id = instrument_id for cross-service references).

---

## BP-368 — Screener Default: Invalid Mandatory Enrichment Filters (current_price, pe_ratio, daily_return)

**Context**: `apps/worldview-web/features/screener/lib/build-filters.ts` — buildScreenerFilters function.

**Symptom**: Screener shows 0 stocks by default. No filter is visible in the UI but the backend returns 0 results.

**Root cause**: Three mandatory enrichment filters were always appended to every screener request:
1. `current_price` (min=0, max=9,999,999): `current_price` is NOT a valid metric in the `fundamentals_metrics` table. The backend performs INNER JOIN per filter metric — invalid metric → 0 rows matched → always 0 results.
2. `pe_ratio` (min=-999999, max=999999): Only 8/31 instruments have PE data. INNER JOIN excludes 23/31 instruments from all default screener views.
3. `daily_return` (min=-100, max=100): Only 8/31 instruments have daily_return data. Same INNER JOIN exclusion.

**Fix**: Remove all three mandatory enrichment filters. Use only `market_capitalization min=0` as the universal fallback filter when no user constraints are set. Users who want PE/daily_return-filtered views explicitly add those filters.

**Prevention**:
- Never add enrichment filters "so the column shows data" — the INNER JOIN semantics of the screener backend means mandatory metric filters silently exclude instruments that don't have that metric.
- The screener's NULL-safe formatters (`—` for missing values) handle missing metric columns correctly; there is no need for mandatory metric presence.
- When testing screener defaults, always check `total` in the response — 0 total with no 422 error indicates an invalid metric filter.

---

## BP-369 — FundamentalsTab: All Entries Empty — Records Format Mismatch

**Context**: `apps/worldview-web/lib/api/instruments.ts` — `getFundamentals()` gateway method.

**Symptom**: Fundamentals tab shows "—" for all fields even with EODHD premium API key and 823 records in the database.

**Root cause**: S3's `GET /v1/fundamentals/{id}` returns `{security_id, records: [{section, period_end, data: {...}}]}` — a list of records grouped by section. The frontend `getFundamentals()` was calling `apiFetch<Fundamentals>(...)` expecting a flat Fundamentals object, but receiving the raw records response. All fields were `undefined`.

**Fix**: Add a records→Fundamentals transformer in `getFundamentals()`:
1. Parse the `records` array, grouping by section: `highlights`, `valuation_ratios`, `technicals_snapshot`
2. Map fields: `pe_ratio` ← `hi.PERatio`, `forward_pe` ← `vr.ForwardPE`, etc.
3. Compute derived fields: `gross_margin = GrossProfitTTM / RevenueTTM`, `payout_ratio = DividendShare / EarningsShare`

**Prevention**:
- Always test gateway methods with the actual backend response (curl) before writing the transformer type.
- S3 fundamentals endpoint returns `records[]` not a flat object; every section-keyed field lookup requires finding the correct section first.
- Check the `section` field in records before accessing `data` — records include time-series sections (income_statement, balance_sheet) that should not be mapped to the spot fundamentals.

---

## BP-370 — EconomicCalendar: S7 Field Name Mismatch → RangeError crash

**Context**: `apps/worldview-web/lib/api/dashboard.ts` — `getEconomicCalendar()`, `components/dashboard/EconomicCalendar.tsx`.

**Symptom**: Economic calendar widget shows empty on the dashboard.

**Root cause**: S9 passes through S7's raw `TemporalEventsListResponse` without transformation. S7 uses:
- `active_from` (not `event_date`)
- `region` (not `country`)
- `confidence` (not `impact` enum)
- Description text "Actual: X, Previous: Y" (not separate `forecast`/`previous`/`actual` fields)

The component called `new Date(event.event_date)` which received `undefined`, then called `.toISOString()` on the Invalid Date → `RangeError: Invalid time value`. React error boundary caught the crash, showing an empty panel.

**Fix**: Add a S7→EconomicEvent transformer in `getEconomicCalendar()`:
- `active_from → event_date`
- `region → country`
- `confidence → impact` (≥0.8=HIGH, ≥0.5=MEDIUM, else LOW)
- Parse description text with regex for Actual/Previous/Forecast values

**Prevention**:
- When proxying through S9, always check whether the backend uses field aliases different from the frontend type. `apiFetch<FrontendType>(url)` does NOT validate field names at runtime — TypeScript types are erased.
- Any component that calls `.toISOString()` on a date field must guard against `undefined`: `event_date ? new Date(event_date).toISOString() : null`.

---

## BP-371 — WorkspaceScreenerWidget: Empty filters[] → 422 Backend Rejection

**Context**: `apps/worldview-web/components/workspace/WorkspaceScreenerWidget.tsx`.

**Symptom**: Workspace screener panel shows error state / no data.

**Root cause**: `runScreener({ filters: [] })` — the backend's `POST /v1/fundamentals/screen` validates `filters` with `min_length=1`. Empty array triggers HTTP 422: "List should have at least 1 item after validation, not 0". The component had no retry or fallback and showed permanent error state.

**Fix**: Use `filters: [{ metric: "market_capitalization", min_value: 0 }]` as the universal no-op filter. Every instrument has a market cap ≥ 0, so no rows are excluded.

**Prevention**:
- The screener API's `min_length=1` constraint on `filters[]` is documented in the OpenAPI schema. Any component that builds a screener request must ensure at least one filter is present.
- `buildScreenerFilters(DEFAULT_FILTERS)` from `features/screener/lib/build-filters.ts` already handles this correctly — reuse it instead of hardcoding filters.

---

---

## BP-372 — TickerPicker Recents: Synthetic `ins-${ticker}` instrumentId → 422 on OHLCV Fetch

**Context**: `apps/worldview-web/components/workspace/TickerPicker.tsx`, `lib/recent-instruments.ts`, `WorkspaceChartWidget.tsx`.

**Symptom**: Workspace chart panel shows "No chart data" for recently-viewed instruments. Network tab shows `GET /api/v1/ohlcv/ins-tsla?timeframe=1d → 422: Invalid instrument_id`.

**Root cause**: `saveRecentInstrument()` stored only `{entityId, ticker, name}` — no `instrumentId`. When recents were selected, `WorkspacePanelContainer` synthesized `ins-${ticker.toLowerCase()}` which the backend rejects (must be UUID). The real `instrumentId` was available in `SymbolLinkingContext` but was discarded via `void linkedInstrumentId`.

**Fix**:
1. Added `instrumentId?: string` to `RecentInstrument` interface and `saveRecentInstrument()` signature
2. `TickerPicker.handleSelect` now persists the real `instrumentId` to recents
3. Recents selection uses stored `r.instrumentId ?? \`ins-${r.ticker.toLowerCase()}\`` fallback
4. `WorkspacePanelContainer` passes `instrumentIdOrUndefined` to `WorkspaceChartWidget`
5. `WorkspaceChartWidget` accepts `instrumentId?: string` prop and uses it over synthetic fallback

**Prevention**:
- Any component that synthesizes IDs from display-names (ticker → `ins-${ticker}`) must be flagged. The backend only accepts real UUIDs.
- TickerPicker selection should always propagate the full ID set from the search result.

---

## BP-373 — Screener Navigation: `row.entity_id` Undefined → `/instruments/undefined`

**Context**: `app/(app)/screener/page.tsx`, portfolio/watchlist navigation.

**Symptom**: Clicking a screener row navigates to `/instruments/undefined` or `/instruments/null`. Instrument detail page immediately shows "not found" or fails to load.

**Root cause**: `onRowClick={(row) => router.push(\`/instruments/${row.entity_id}\`)}` but the screener API returns `entity_id: null` (not populated). The `entity_id` fallback in `runScreener()` maps to `instrument_id` (line 78 of screener.ts), but the navigation code reads the raw `entity_id` field first.

**Fix**: Changed navigation to use `row.instrument_id ?? row.entity_id` in screener, `member.instrument_id ?? member.entity_id` in watchlist, and `row.h.instrument_id ?? row.h.entity_id` in holdings table.

**Prevention**:
- Navigation to `/instruments/[id]` should always prefer `instrument_id` (market-data UUID) over KG entity_id, since the page-bundle endpoint resolves entity_id from the overview.
- Never use `row.entity_id` directly for navigation without a fallback — it may be null when the KG entity hasn't been seeded.

---

## BP-374 — Page-Bundle Fundamentals: KG entity_id Passed to Market-Data Endpoints → 404

**Context**: `services/api-gateway/src/api_gateway/clients.py`, `get_instrument_page_bundle`.

**Symptom**: Instrument detail page shows all fundamentals as "—". Bundle returns `fundamentals: null`.

**Root cause**: Phase 2 fundamentals/technicals/insider calls used the raw URL `instrument_id` parameter even after Phase 1 resolved the real market-data `instrument_id` from `overview.instrument.instrument_id`. When navigating with KG entity_id (e.g., `11111111-0001-7000-8000-000000000001`), the market-data `/api/v1/fundamentals/{entity_id}` returns 404 "No fundamentals found".

**Fix**: After Phase 1 overview, resolve `resolved_md_id = overview.instrument.instrument_id`. Use `resolved_md_id` for all Phase 2 market-data calls. Also guard `(all_fundamentals_raw or {}).get("records", [])` against None.

**Prevention**:
- In composite bundle endpoints, always extract the authoritative service-specific ID from Phase 1 response before using it in Phase 2 calls.
- ADR-F-12: entity_id ≠ instrument_id. Market-data endpoints require `instrument_id`; KG endpoints require `entity_id`.

---

## BP-379 — FundamentalsTab all "—": Page-Bundle Seeds Wrong Shape into TanStack Cache

**Context**: `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (cache priming effect).

**Symptom**: Instrument detail page Fundamentals tab shows "—" for every metric (Market Cap, P/E, margins, etc.) even though the DB and API have correct data. The issue is silent — no errors in console.

**Root cause**: The cache-priming `useEffect` called `queryClient.setQueryData(["fundamentals", md_id], bundle.fundamentals)` where `bundle.fundamentals` is `FundamentalsSectionResponse` (an object with `security_id` + `records: [...]` — raw section array). But `FundamentalsTab.useQuery` with `queryKey: ["fundamentals", instrumentId]` expects a flat `Fundamentals` object (with `pe_ratio`, `market_cap`, etc.) produced by `getFundamentals()` transformer. TanStack Query's `staleTime: 5min` prevented the correct `queryFn` from running — the component consumed the wrong shape for 5 minutes, every time.

**Fix**: Remove the `bundle.fundamentals` seed from the cache-priming effect. The `FundamentalsTab` already receives `initialData={overview?.fundamentals}` (a flat `Fundamentals` from `CompanyOverview`) as `placeholderData`, so the initial paint shows real data while the `getFundamentals()` query fires.

**Prevention**:
- `queryClient.setQueryData(key, value)` does NOT validate the shape against TypeScript. Seeding the wrong type silently produces misbehaving components.
- When a page bundle composes multiple sub-resources, each sub-resource shape must exactly match what the consuming component's `queryFn` would return — not the raw API response if the component uses a client-side transformer.
- Any cache seed should be paired with a TypeScript cast that confirms the shape matches the query's generic type: `queryClient.setQueryData<Fundamentals>(key, transformedValue)`.

---

## BP-380 — OHLCVChart Timeframe Switch Stays Anchored at Historical Bars

**Context**: `apps/worldview-web/components/instrument/OHLCVChart.tsx`.

**Symptom**: After switching from "1D" to "1H" (or any other timeframe change), the chart auto-scrolls to the oldest available bar (e.g. 1985 for AAPL 1D → shows 40+ years of history). User must manually scroll right to see recent prices.

**Root cause**: `hasScrolledToRealTime` ref was only reset in `useEffect(..., [instrumentId])` — not on `timeframe` changes. After the initial chart load, `hasScrolledToRealTime.current = true`. When the user switches timeframe, a new query fires with new bars; `setData()` auto-fits to show all bars. The scroll guard checks `!hasScrolledToRealTime.current` which is `false` → `scrollToRealTime()` is skipped → chart stays at historical position. This is a variant of BP-376 (same scroll guard mechanism).

**Fix**: Add `timeframe` to the reset effect's dependency array:
```typescript
useEffect(() => {
  hasScrolledToRealTime.current = false;
  pendingScrollToRealTime.current = false;
}, [instrumentId, timeframe]); // was: [instrumentId]
```

**Prevention**:
- Any `useRef` flag that guards a one-time action on "first load" must be reset when ANY property that triggers a "fresh load" changes — not just the primary entity ID.
- Lightweight-charts `setData()` always auto-fits when the data range changes significantly; any guard against that behaviour must account for all state changes that result in a full dataset replacement.

---

## BP-381 — Tailwind display class on Radix TabsContent overrides `hidden=""`, renders black block

**Category**: Frontend
**Severity**: HIGH (visible layout regression — black rectangle occupies ~50% of viewport)
**First seen**: 2026-05-04
**Services**: worldview-web (any page with shadcn Tabs + display-class on TabsContent)

**Symptoms**:
- An empty black rectangle fills approximately half the screen on a page that uses Tabs
- The culprit element has `data-state="inactive"` and `hidden=""` in DevTools but is visible
- `aria-labelledby` in DevTools points to an inactive tab trigger (e.g., `...-trigger-transactions`)
- The element has `bg-background` (dark/opaque) and `flex-1` so it fills its flex parent

**Root cause**:
Radix UI hides inactive `TabsContent` panels by setting the HTML `hidden` attribute (`hidden=""`).
Browsers apply `[hidden] { display: none }` from the **UA stylesheet** (low priority).
Tailwind's display utilities (`flex`, `grid`, `block`, etc.) live in the **author stylesheet** (higher priority).
When a caller passes `className="... flex flex-col ..."` to `TabsContent`, Tailwind's `display: flex`
wins the cascade and the inactive panel renders as a visible empty div.
With `flex-1` and `bg-background`, it expands to fill its flex parent and shows as a black rectangle.

```tsx
// Bad — flex overrides hidden=""
<TabsContent value="transactions" className="flex-1 min-h-0 overflow-y-auto flex flex-col bg-background">

// Good — display class is conditional on active state
<TabsContent value="transactions" className="flex-1 min-h-0 overflow-y-auto bg-background">
// (TransactionsTab's own root element carries its flex layout)
```

**Fix applied**:
Added `data-[state=inactive]:!hidden` to the base `TabsContent` component in
`components/ui/tabs.tsx`. This re-applies `display: none !important` for inactive panels
regardless of any display class in the caller's `className`, fixing all current and future
instances project-wide.

**Prevention**:
- Never put `flex`, `grid`, `block`, or any display utility directly on `TabsContent` — put it on the child component's root element instead.
- If a display class is needed at the `TabsContent` level, use `data-[state=active]:flex` so it only applies when the tab is active.
- Code review: flag any `TabsContent className` containing `\bflex\b|\bgrid\b|\bblock\b` without a `data-[state=active]:` guard.

**Regression test**: `apps/worldview-web/__tests__/tabs-hidden-override.test.tsx` (to be added)

---

## BP-389 — AG Grid CSP inline-style block, font-src data: violation, and missing module registration

**Context**: AG Grid v35 Community added to screener + portfolio holdings tables; running under Next.js 15 nonce-based CSP

**Symptom**: AG Grid renders as a black/blank rectangle; browser console shows:
- `Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline' does not appear in the style-src directive` (×25)
- `Refused to load data:font/woff2;...` (font-src violation)
- `AG Grid: error #272 — No AG Grid modules are registered`
- `ResizeObserver loop completed with undelivered notifications` (×170 — layout thrash from styless grid)
- Safari: `Failed to load resource: You do not have permission to access the requested resource` (Safari CSP block message)

**Root cause (three distinct issues)**:

1. **CSP nonce kills `'unsafe-inline'` in `style-src`**: `middleware.ts` included `'nonce-${nonce}'` in `style-src`. Per CSP Level 3 §6.8.2, presence of `nonce-*` in a directive causes browsers (Chrome, Firefox) to ignore `'unsafe-inline'` for inline `<style>` elements. AG Grid v35 dynamically injects ~20 `<style>` elements at grid init without nonces — all blocked.

2. **AG Grid icon font loaded via `data:` URI**: The `ag-theme-alpine` CSS includes `@font-face { src: url("data:font/woff2;base64,...") }` for its grid icon font. `font-src` was `'self' https://fonts.gstatic.com` with no `data:` allowed.

3. **`AllCommunityModule` never registered**: `AgGridBase.tsx` uses `<AgGridReact>` without calling `ModuleRegistry.registerModules([AllCommunityModule])`. AG Grid v32+ requires explicit module registration.

**Fix**:
- `middleware.ts`: remove `'nonce-${nonce}'` from `style-src` (Next.js static stylesheets are covered by `'self'`; inline Tailwind + AG Grid styles covered by `'unsafe-inline'` which is now active again). Add `data:` to `font-src`.
- `providers.tsx`: add `ModuleRegistry.registerModules([AllCommunityModule])` at module level (runs once before any `AgGridBase` mount, regardless of which page the user lands on).

**Prevention**:
- When adding a third-party library that injects inline `<style>` elements (AG Grid, some charting libs, styled-components), check whether the CSP `style-src` directive contains any `nonce-*` or `hash-*` source — if so, `'unsafe-inline'` will be silently ignored.
- Verify CSP compliance with browser devtools Network → Response Headers → Content-Security-Policy BEFORE shipping a new component to staging.
- For AG Grid specifically: `ModuleRegistry.registerModules(...)` must be called exactly once before any grid renders — put it in the providers/entry file, not inside the component.

---

## BP-453 — `scrollToRealTime()` on empty chart marks scroll guard `true` prematurely — chart scrolls to 1985

**Context**: `OHLCVChart.tsx` uses two refs to coordinate scrolling: `pendingScrollToRealTime` (data arrived before chart was ready) and `hasScrolledToRealTime` (one-shot guard so scroll fires only once).

**Symptom**: Every instrument page load starts pinned at the oldest available bar (~1985 for US equities). The chart never auto-advances to the most recent bar on initial load.

**Root cause**: In `initChart()`, when `pendingScrollToRealTime.current` was true, the code called `chart.timeScale().scrollToRealTime()` AND set `hasScrolledToRealTime.current = true`. But `initChart()` runs before the data-update effect populates bar data — calling `scrollToRealTime()` on an empty chart is a silent no-op. Setting `hasScrolledToRealTime.current = true` at this point permanently blocked the real `scrollToRealTime()` call when actual bars arrived in the data-update effect below.

**Fix**: In `initChart()`'s pending-scroll path, only clear `pendingScrollToRealTime.current = false`. Remove both the no-op `scrollToRealTime()` call and the premature `hasScrolledToRealTime.current = true` assignment. The data-update effect already handles calling `scrollToRealTime()` once it has real bar data.

**Prevention**:
- Any "done" guard (`hasX.current = true`) must only be set AFTER the operation succeeds on real data — never in a deferred-init path that runs before data is available.
- When a lightweight-charts `timeScale()` call is preceded by a data-load step, treat any pre-data call as a potential no-op and ensure the guard is not set until the call produces observable effect.

**Reference**: `apps/worldview-web/components/instrument/OHLCVChart.tsx` — `initChart()`, around line 529.

---

## BP-454 — `h-full` inside CSS Grid cell resolves to content height — black void below EntityGraph panel

**Context**: `OverviewLayout.tsx` lower section uses `<div className="grid grid-cols-3 min-h-[400px]">`. Zone 8 (Entity Graph) wraps `<EntityGraphPanel>` in `<div className="min-w-0">`. `EntityGraphPanel` uses `h-full` internally to fill its parent.

**Symptom**: Overview tab shows a black rectangle (~120px tall) below the entity graph in the bottom-right grid cell. The panel renders at its `min-h-[280px]` minimum and does not expand to fill the grid row.

**Root cause**: CSS Grid `min-h-[400px]` on the grid container sets the MINIMUM row height but does NOT give the individual cells an explicit height. `h-full` on a child resolves against its direct parent — in this case `<div class="min-w-0">` — which has no explicit height set. So `h-full` collapses to the component's own `min-h` (280px), leaving 120px of bare dark background visible below it (the "black void").

**Fix**: Add `h-full` to the intermediate wrapper div: `<div className="min-w-0 h-full">`. Every div between the CSS Grid item boundary and the component root that uses `h-full` must also carry `h-full`.

**Prevention**:
- When placing any component that uses `h-full` inside a CSS Grid cell, ALL intermediate wrapper divs between the grid item and the component must also have `h-full`.
- `min-h-[N]` on a grid container does NOT propagate explicit height to children — it only floors the row height. Components relying on `h-full` need an explicit height on every ancestor up to the grid item.
- Code-review signal: `h-full` on a component inside `<div className="min-w-0">` (or any single-utility wrapper) is a candidate for missing `h-full` propagation.

**Reference**: `apps/worldview-web/components/instrument/OverviewLayout.tsx` — Zone 8 wrapper, around line 391.

**Regression test**: `apps/worldview-web/__tests__/csp-headers.test.ts` (to be added)

---

## BP-455 — Hardcoded pixel-width `<div>` footer below AG Grid misaligns on column resize / pinned column

**Context**: Portfolio totals rendered as a sibling `<div>` below `<AgGridReact>`, with hardcoded `w-[640px]` spacer to align under the scrollable columns. TICKER column pinned left.

**Symptom**: Totals footer drifts left or right when the user resizes any column or when the grid's horizontal scroll position changes.

**Root cause**: AG Grid splits its viewport into two DOM containers — one for pinned columns (left) and one for the scrollable columns. A sibling `<div>` lives outside both containers and can only be aligned via hardcoded pixel values. Any column resize or horizontal scroll breaks the alignment.

**Fix**: Use `pinnedBottomRowData` prop on `<AgGridReact>`. AG Grid renders pinned rows inside the grid DOM, placing them in both the pinned and scrollable containers automatically.

```tsx
// Bad
<AgGridReact rowData={rows} />
<div style={{ paddingLeft: 640 }}>TOTAL …</div>

// Good
<AgGridReact rowData={rows} pinnedBottomRowData={[totalsRow]} />
```

Cell renderers check `params.node?.rowPinned === 'bottom'` and render totals values instead of normal cell content. Use optional chaining (`?.`) — `node` can be undefined in Vitest/jsdom environments.

**Prevention**: Never use a sibling `<div>` to represent a footer for an AG Grid table. Any footer/totals row must live inside the grid via `pinnedBottomRowData`.

**Reference**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx` and `ag-holdings-columns.tsx`.

---

## BP-457 — JSX block comment `{/* */}` at top level of `return()` outside any element

**Context**: `HoldingLotsPanel.tsx` had `{/* WHY … */}` placed at the top level of a `return()` directly before the root `<div>`. This is invalid JSX — a JSX comment expression outside any wrapping element is a compile-time error.

**Symptom**: TypeScript/ESLint parser error; component fails to build.

**Root cause**: JSX comments (`{/* */}`) are valid only inside a JSX element, not at the top level of a `return()` statement alongside a root element. The parser sees two top-level expressions.

**Fix**: Convert to a JS line comment (`// …`) which is valid at the top level of `return()`, or move the comment inside the root element.

```tsx
// Bad
return (
  {/* WHY border-y: … */}
  <div className="border-y">…</div>
);

// Good
return (
  // WHY border-y: …
  <div className="border-y">…</div>
);
```

**Prevention**: Never start a JSX `{/* */}` comment outside a JSX element. Top-level comments in `return()` must use `//` line syntax.

**Reference**: `apps/worldview-web/components/portfolio/HoldingLotsPanel.tsx` line 93.

---

## BP-458 — Signal label lookup set mismatched with LLM event_type enum

**Context**: S9 proxy `_signal_type_to_label()` was designed for broker-event labels (EARNINGS_BEAT, DOWNGRADE, etc.) but S6 NLP pipeline uses a different event_type enum (PRODUCT_LAUNCH, LEGAL, GEOPOLITICAL, etc.) from `deep_extraction.py`.

**Symptom**: All AI signals on the dashboard show "NEUTRAL" regardless of content.

**Root cause**: `_POSITIVE_SIGNAL_TYPES`/`_NEGATIVE_SIGNAL_TYPES` in proxy.py only contained broker-event labels. The LLM extracts `event_type` values from a separate enum (EARNINGS_RELEASE, PRODUCT_LAUNCH, CAPITAL_RAISE, LEGAL, NATURAL_DISASTER, GEOPOLITICAL, SANCTIONS, etc.) — none of which were in the lookup sets, so all fell through to the NEUTRAL default.

**Fix**: Add the NLP deep-extraction `event_type` values to the lookup sets in proxy.py. Also fix `_enqueue_signal_events` in `article_consumer.py` which hardcoded `"polarity": "neutral"` in the Avro payload — compute polarity from signal_type using the same lookup.

**Prevention**: When two systems exchange signal/event type enums, keep both lookup sets and the enum definition in sync. Add a comment citing the source of truth. When adding a new LLM extraction schema, immediately add its output labels to the downstream label mapping.

**Reference**: `services/api-gateway/src/api_gateway/routes/proxy.py` (_POSITIVE/_NEGATIVE sets), `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` (_enqueue_signal_events), `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py` (event_type enum).
