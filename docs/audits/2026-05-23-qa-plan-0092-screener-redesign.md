# QA Audit Report — PLAN-0092: Screener Redesign + Financials Timeseries

**Date**: 2026-05-23
**Branch**: feat/plan-0089-w2
**Scope**: PLAN-0092 (all 5 waves)
**Services**: api-gateway (S9), worldview-web (frontend)

---

## Summary

| Severity | Count | Fixed | Notes |
|----------|-------|-------|-------|
| BLOCKING | 3 | 3 | All resolved before merge |
| CRITICAL | 1 | 1 | Resolved |
| MAJOR | 2 | 2 | Resolved |
| MINOR | 2 | 1 | One deferred |
| NIT | 3 | 3 | Auto-fixed by ruff |

---

## BLOCKING Issues (All Fixed)

### B-001 — NL Screener always 503 (pydantic-settings double env_prefix)
- **File**: `services/api-gateway/src/api_gateway/config.py`
- **Issue**: Field named `api_gateway_deepinfra_api_key` with `env_prefix="API_GATEWAY_"` caused pydantic-settings to look for `API_GATEWAY_API_GATEWAY_DEEPINFRA_API_KEY` instead of `API_GATEWAY_DEEPINFRA_API_KEY`. Field always read as empty SecretStr, so the endpoint returned 503 unconditionally.
- **Fix**: Renamed field to `deepinfra_api_key` → maps correctly to `API_GATEWAY_DEEPINFRA_API_KEY`.
- **Pattern**: BP-423 (env_prefix doubling)

### B-002 — NL Screener calling S8 with wrong payload schema
- **File**: `services/api-gateway/src/api_gateway/routes/market.py`
- **Issue**: Route was calling S8 `/api/v1/chat` with OpenAI-style `{messages: [{role, content}], stream: false}`. S8 expects `{message: str, entity_ids, thread_id}` (RAG chat schema). S8 returned 422 on every call.
- **Fix**: Route now calls DeepInfra directly at `https://api.deepinfra.com/v1/openai/chat/completions` with OpenAI-compatible payload. S8 is not used for NL screener translation (RAG pipeline is wasteful for a simple translation task).

### B-003 — handleCellMouseOut never clears toolbar
- **File**: `apps/worldview-web/app/(app)/screener/page.tsx`
- **Issue**: `setHoveredRow((current) => current)` returns the current state unchanged — React skips the re-render, and `setHoveredRow(null)` call inside the callback was never reached. Toolbar was sticky and never cleared.
- **Fix**: Replaced with `mouseOutPendingRef` flag + `requestAnimationFrame` pattern. `mouseOutPendingRef.current = true` in mouseOut; `mouseOutPendingRef.current = false` in mouseOver (cancels pending clear). rAF fires once and checks the flag before clearing.

---

## CRITICAL Issues (Fixed)

### C-001 — NL screener injects no valid field list into LLM prompt
- **File**: `services/api-gateway/src/api_gateway/routes/market.py`
- **Issue**: System prompt said "Valid field names will be provided" but the route never injected them. The example in the prompt used `sector` and `profit_margin` (not real screener fields), causing the LLM to consistently hallucinate those names.
- **Fix**:
  1. Updated system prompt to remove misleading example with fake fields.
  2. Valid fields from `GET /v1/fundamentals/screen/fields` are prepended to the user message as `ALLOWED FIELDS: field1, field2, ...`.
  3. Changed validation to strip unknown fields (log warning) instead of returning 422 — graceful degradation when fields API is unavailable or LLM still hallucinates.

---

## MAJOR Issues (Fixed)

### M-001 — NLScreenerInput uses createGateway inside mutation
- **File**: `apps/worldview-web/components/screener/NLScreenerInput.tsx`
- **Issue**: `createGateway(accessToken)` called inside a TanStack Query mutation instead of using the canonical `useApiClient()` hook. Creates a new gateway client on every mutation invocation; misses request dedup and token refresh.
- **Fix**: Changed to `const gateway = useApiClient()` + `gateway.translateNLScreenerQuery(q)` in mutation.

### M-002 — Query input field has no length validation
- **File**: `services/api-gateway/src/api_gateway/schemas/screener.py`
- **Issue**: `query: str` with no validation allows empty strings or extremely long strings to reach DeepInfra.
- **Fix**: `query: str = Field(min_length=1, max_length=500)`.

---

## MINOR Issues

### N-001 — "/" hotkey doesn't check contenteditable
- **File**: `apps/worldview-web/app/(app)/screener/page.tsx`
- **Issue**: Hotkey listener only checked `INPUT` and `TEXTAREA` tags; pressing "/" in a contenteditable div (e.g. rich text editor) would still focus the search box.
- **Fix**: Added `|| el.contentEditable === "true"` guard.

### N-002 — Missing component-level unit tests (deferred)
- **Files**: RowHoverToolbar, ScreenerHeader, FilterChipStrip, NLScreenerInput, FundamentalsTimeseriesChart
- **Issue**: No Vitest unit tests for these 5 components.
- **Status**: Deferred — components are tested via page-level screener.test.tsx integration tests; isolated unit tests are a follow-up task.

---

## Live Validation Results

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `POST /v1/screener/nl-translate` | POST | ✅ 200 | Returns valid filters, strips unknown fields |
| `GET /v1/screener` | GET | ✅ 200 | AG Grid renders, hover toolbar works |
| `GET /v1/fundamentals/screen/fields` | GET | ✅ 200 | Field list drives LLM prompt |

**Live NL translate response** (query: "profitable tech stocks with PE below 20"):
```json
{
  "filters": {"net_margin_pct": {"gte": 0}, "pe_ratio": {"lte": 20}},
  "natural_language_query": "profitable tech stocks with PE below 20",
  "explanation": "Profitable tech stocks with low price-to-earnings ratio"
}
```

---

## Test Suite Results

| Suite | Tests | Pass |
|-------|-------|------|
| api-gateway unit + NL screener | 168 | 168 |
| worldview-web Vitest | 2214 | 2214 |
