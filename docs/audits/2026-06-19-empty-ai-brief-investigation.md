# Investigation: Empty Dashboard AI Brief (2026-06-19)

**Status:** Root cause CONFIRMED. Read-only; no changes made.
**Classification:** (b) generated-but-empty — brief generates with all-placeholder content because the generator cannot reach any upstream data source.

## Symptom
Dashboard "Morning Briefing" card renders effectively empty: six section headings each
followed by "No specific items today." `confidence: 0.0`.

## Root cause (CONFIRMED)
The api-gateway (S9) service-token mint endpoint returns **503 `service_token_unconfigured`**
because `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` is **not set** on the gateway container.

Chain of evidence:
1. `POST http://api-gateway:8000/internal/v1/service-token` → **503** (gateway log:
   `service_token_unconfigured`, repeated 5x with retry).
2. Gateway guard fires when `settings.service_account_token` is empty:
   `services/api-gateway/src/api_gateway/routes/internal.py:130-142`.
   Default is `SecretStr("")` — `services/api-gateway/src/api_gateway/config.py:105`.
3. Gateway env source `services/api-gateway/configs/docker.env` contains **NO**
   `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` line (grep → no match).
   `docker exec worldview-api-gateway-1 env` → `WORLDVIEW_SERVICE_ACCOUNT_TOKEN=[]` (empty).
4. With no service token, the brief-scheduler's upstream calls ALL return **401**:
   - S1 `/internal/v1/users/.../portfolio/context` → 401 (`has_portfolio: false`)
   - S3 market-data lookup/tape/earnings → 401
   - S6 news/top → 401 (`news_count: 0`)
   - S7 events/search → 401, S5 alerts → 401
5. `brief_context_availability_score`: `score: 0.0`, `sections_populated: 0`
   → `brief_low_context_refusal` (threshold 0.3) → `brief_pregeneration_user_empty_context`.
6. The brief is still generated + cached as all-placeholder ("No specific items today")
   with `confidence: 0.0`. Two such briefs exist today (05:28:32, 05:28:58 UTC); the diff
   endpoint reports `new_count: 0, removed_count: 0` (both empty).

The scheduler IS correctly configured: `RAG_CHAT_SERVICE_ACCOUNT_TOKEN=dev-service-account-secret-plan-0094`
(`services/rag-chat/configs/docker.env:61`). The mismatch is **gateway-side only** — the
matching `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` is missing. (The scheduler's own docker.env
comment at line 58 documents that the gateway must carry this value.)

This is a regression of the earlier "brief-scheduler token" class of bug, but with a new
cause: the MINT endpoint itself is unconfigured (503), not an allowlist gap.

## Frontend (not the bug, but a confounding factor)
`apps/worldview-web/components/dashboard/MorningBriefCard.tsx`:
- Hook: TanStack `useQuery(["morning-brief"])` → `getMorningBrief()`
  (`apps/worldview-web/lib/api/dashboard.ts:381` → `GET /v1/briefings/morning`).
- The endpoint returns **200** with a populated `narrative` (300 chars of placeholders),
  so the card does NOT hit its loading/error/empty branches. It renders the placeholder
  markdown verbatim (MorningBriefCard.tsx:366 empty-guard passes because `narrative` is
  non-empty). To the user this looks "empty/useless" even though it's a 200.
- So the frontend is behaving correctly; it is faithfully rendering a content-free brief.

## Impact
- **Morning brief:** all users get a content-free brief (no portfolio, news, market, events).
- **Instrument brief:** the GET instrument route returned 200 in logs. The instrument path
  uses `execute_public_instrument` (entity-scoped, mostly S7/S3/S6 via the same gatherer);
  it ALSO depends on the service token for its upstream calls when invoked by background/
  no-JWT paths. On the live on-demand path it forwards the *caller's* JWT
  (`set_current_jwt(request.headers.get("X-Internal-JWT"))`), so interactive instrument
  briefs still work. **Only the brief-scheduler (no inbound JWT → must mint) is broken.**
- Chat is unaffected (it forwards the user JWT).

## Ranked fix

### P0 — Set the gateway service-account token (config, not code)
Add to `services/api-gateway/configs/docker.env`:
```
API_GATEWAY_SERVICE_ACCOUNT_TOKEN=dev-service-account-secret-plan-0094
```
Must EXACTLY equal `RAG_CHAT_SERVICE_ACCOUNT_TOKEN` in `services/rag-chat/configs/docker.env:61`.
Then recreate api-gateway (+ brief-scheduler) so the mint succeeds. After the next
pregeneration run (hourly, `interval[1:00:00]`) the cached brief will populate. To verify
without waiting: `POST /v1/briefings/morning/generate` (force-regen) once the token is set.
- File:line: `services/api-gateway/configs/docker.env` (add line); gating guard at
  `services/api-gateway/src/api_gateway/routes/internal.py:130-142`.

### P1 — Don't cache a refused/zero-context brief as if it were real
`services/rag-chat/src/rag_chat/application/workers/morning_brief_pregeneration_worker.py`
+ `public_briefings.py` cache-write path: when `brief_low_context_refusal` fires
(`score < 0.3` / `sections_populated == 0` / `confidence == 0.0`), do NOT overwrite the
`briefing:morning:v2` / `lastgood` cache with the placeholder payload. Preserve the previous
known-good brief instead, so a transient upstream-auth blip doesn't replace a good brief
with "No specific items today." (Today both cached briefs are placeholders precisely because
the refusal result was cached.)

### P1 — Frontend: treat a zero-confidence all-placeholder brief as empty
`apps/worldview-web/components/dashboard/MorningBriefCard.tsx:366` — the empty guard only
checks for empty strings. A brief with `confidence === 0` AND every section reading
"No specific items today" should fall through to the named EmptyState (with Regenerate)
rather than render six placeholder lines that look broken. This is a UX safety net, not the
root fix.

## Verification commands used
- `curl POST /v1/auth/dev-login` → JWT (sub `01900000-0000-7000-8000-000000000010`).
- `curl GET /v1/briefings/morning` → 200, narrative all "No specific items today", confidence 0.0, cached true.
- `docker logs worldview-rag-chat-brief-scheduler-1` → 401 on every upstream; `service-token` mint → 503.
- `docker logs worldview-api-gateway-1` → `service_token_unconfigured` 503.
- `docker exec worldview-api-gateway-1 env` → `WORLDVIEW_SERVICE_ACCOUNT_TOKEN` empty.
- `grep API_GATEWAY_SERVICE_ACCOUNT_TOKEN services/api-gateway/configs/docker.env` → no match.
