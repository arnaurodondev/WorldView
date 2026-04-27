# Live QA — Stability Pass (2026-04-28)

**Date**: 2026-04-28
**Branch**: feat/content-ingestion-wave-a1
**Triggered by**: User request — "priority #1 is stability; increase rate limit to ~500/min"
**Services rebuilt**: api-gateway, rag-chat, market-data

---

## Summary

4 bugs found and fixed. All 57 containers remained healthy throughout.

| # | Severity | Service | Issue | Status |
|---|----------|---------|-------|--------|
| 1 | CRITICAL | api-gateway | AI Signals S9 passthrough — S6 `{items:[...]}` passed raw; frontend expected `{signals:[...]}` with mapped field names | FIXED |
| 2 | MAJOR | rag-chat | Morning brief narrative wrapped in `\`\`\`markdown...\`\`\`` code fence by LLM; ReactMarkdown rendered raw backticks | FIXED |
| 3 | MAJOR | market-data | `price_change` / `price_change_pct` always `None` in PriceSnapshotResolver (W1-9 not implemented); S9 converted to 0.0 | FIXED |
| 4 | CONFIG | api-gateway | Rate limit was 100 req/min (hardcoded in docker.env); user requested ~500/min | FIXED → 500 |

---

## Bug Details

### BUG-1: AI Signals field mismatch (CRITICAL)
**Root cause**: `GET /v1/signals/ai` in proxy.py did `return Response(content=resp.content)` passing S6's raw `{items:[...]}` to frontend. S6 uses `signal_type`/`confidence`/`detected_at`/`evidence_text`; frontend types/api.ts expects `label`/`score`/`created_at`/`article_title` in a `{signals:[...]}` envelope.
**Fix**: Added transform in `proxy.py:ai_signals()` — maps `items→signals`, `confidence→score`, `signal_type→label` (via 25-entry positive/negative set), `detected_at→created_at`, `article_title→null` (evidence_text is a claim UUID, not readable text).
**Files**: `services/api-gateway/src/api_gateway/routes/proxy.py`, `services/api-gateway/tests/test_s9_wave3_proxy.py`

### BUG-2: Morning brief markdown fence (MAJOR)
**Root cause**: LLM (Meta-Llama-3.1-8B-Instruct via DeepInfra) wraps output in ` ```markdown...``` ` fences. `_strip_reasoning()` in S8 stripped `<think>` blocks but not code fences. Frontend ReactMarkdown renders backtick markers as literal text.
**Fix**: Added `_CODE_FENCE_RE` regex in `generate_briefing.py` — strips outer ` ```markdown ` / ` ``` ` fence after stripping reasoning blocks.
**Files**: `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py`
**Note**: Cleared Valkey `briefing:*` keys to force regeneration without cached fenced content.

### BUG-3: price_change always 0.0 in batch quotes (MAJOR)
**Root cause**: `PriceSnapshotResolver._build()` always set `price_change=None` with comment "computed in W1-9" — W1-9 of PLAN-0036 was never implemented. S9 `_map_price_snapshot_to_quote()` converted `None→0.0`, giving all instruments 0.0 change/change_pct.
**Fix**: Added `_prev_daily_close(bars, latest)` helper and `prev_close: Decimal | None = None` param to `_build()`. At Step 5 (DAILY_CLOSE), passes previous session's close from the 7-day OHLCV bar window. Intraday paths (Steps 1-4) still return 0.0 — accurate for quote-sourced data without prior-day context.
**Files**: `services/market-data/src/market_data/domain/price_snapshot.py`
**Note**: Cleared Valkey `price_snapshot:*` keys (7 entries, 2h TTL) to bypass stale cache.

### BUG-4: Rate limit too low (CONFIG)
**Change**: `API_GATEWAY_RATE_LIMIT_REQUESTS=100→500` in `services/api-gateway/configs/docker.env`. Unauthenticated limit unchanged (20/min). The Valkey sliding-window rate limiter reads this at startup; api-gateway restart applied the new limit.

---

## Test Results (post-fix)

| Service | Tests | Result |
|---------|-------|--------|
| api-gateway | 209 | PASS |
| market-data | 522 | PASS |
| rag-chat | 350+ | PASS |
| alert | 350 | PASS |

## Ruff / Mypy
- `ruff check` — zero issues on all changed files
- `mypy src/` — Success (api-gateway, market-data)

## Live Endpoint Validation
- `GET /v1/signals/ai` → `{"signals":[{label, score, created_at, ...}]}` ✓
- `POST /v1/quotes/batch` (instrument 1002) → `change_pct=-1.28%` ✓
- Rate limit → `API_GATEWAY_RATE_LIMIT_REQUESTS=500` ✓
