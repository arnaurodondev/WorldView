---
id: QA-PLAN-0093-PHASE-5C-REQA
title: PLAN-0093 Phase 5c — Re-QA Results After 7 Fix Agents
date: 2026-05-24
predecessor: docs/audits/2026-05-24-qa-plan-0093-phase-5c-investigation-report.md
branch: feat/plan-0093-remediation
mode: LIVE (rag-chat rebuilt with FIX-LIVE-A/B/E; scheduler rebuilt with FIX-LIVE-C; gateway rebuilt with FIX-LIVE-D)
overall_verdict: PARTIAL_PASS — substantial wins, distinct new failure mode (zero-HARMFUL gate still violated by F-LIVE-J)
---

# Phase 5c Re-QA — Post-Remediation Results

## TL;DR

Of the 7 fix agents shipped (A through G + I), all landed and are confirmed live. The re-QA chat-eval shows substantial progress: 6 of 15 tests now pass (previously 3), 8 of 9 weak-point survey tests pass (previously 0/9), Q2 went from USELESS to PASS, Q4 went from 1 PASS to 3 PASS, cache poisoning is eliminated, and all infrastructure invariants (host-event survival, gateway resilience, scheduler /metrics, restart policies) are live-verified working.

**The plan still fails the zero-HARMFUL gate** — Q4 v1 and Q4 v6 still produce HARMFUL output containing "AMD revenue > $15B". But the failure mode is **fundamentally different** from the original Phase 5c finding:
- **Before**: cache served pre-FIX poisoned answer — FIX-2 never executed
- **Now**: FIX-2 + FIX-LIVE-A/B execute correctly, but the agent never receives tool results on the second LLM turn (`missing required tool from ['get_fundamentals_history']; got []`)

Three new live-only findings were surfaced that the previous static + investigation passes could not catch.

## Re-QA Test Matrix

| Test | Phase 5c (before fixes) | Re-QA (after fixes) | Δ |
|---|---|---|---|
| Q1 competitors | PASS | PASS | = |
| Q2 MSTR news | USELESS (all_tools_failed) | **PASS** | ↑ FIX-LIVE-E fallback works |
| Q3 Tim Cook | PASS | PASS | = |
| Q4 v1 compare | HARMFUL (cache + fabrication) | **HARMFUL** (different mode: agent never sees tool results) | = (new mode) |
| Q4 v2 NVDA single | FAIL (missing 68.127B) | FAIL (same) | = |
| Q4 v3 AMD rev+EPS | PASS | PASS | = |
| Q4 v4 NVDA margin | USELESS (refusal) | **PASS** (FIX-LIVE-B grader) | ↑ |
| Q4 v5 AMD YoY | USELESS (refusal) | **PASS** (FIX-LIVE-B grader + YoY hint) | ↑ |
| Q4 v6 full compare | USELESS (refusal) | **HARMFUL** | regressed grader scope vs HARMFUL — now LLM tries + fails |
| Q5 TSLA macro | HTTP 503 | USELESS (got past gateway, agent failed) | ↑ partial |
| Q6 AI chip screener | HTTP 503 | 0 tickers (got past gateway, screener empty) | ↑ partial |
| Q7 TSLA contradictions | HTTP 503 | HTTP 401 (gateway works, downstream auth) | ↑ partial |
| Q8 OpenAI→MSFT | PASS | **USELESS REGRESSED** (cache was hiding it) | ↓ |
| Aggregate score gate | FAIL (3/8 USEFUL) | FAIL (3/8 USEFUL on audit questions) | = |
| Weak-point survey | FAIL | 8/9 PASS | ↑ |

**Plus 5/5 new `test_grading.py` PASS** (FIX-LIVE-B grader unit tests).

**Final**: 6/15 chat-eval PASS + 5/5 grader + 8/9 survey = **19/31 total** (was 3/15).

## What Worked (live-confirmed)

### Cache invalidation (FIX-LIVE-A) ✓
- `rag:v1:completion:*` keys purged
- Q4 v1 now executes the full pipeline (39s latency vs 0.4s cache hit before)
- Tool calls present: `get_fundamentals_history(NVDA, 4)`, `get_fundamentals_history(AMD, 4)`
- **No more `$34.6B` fabrication from cached prose**

### Tool-fallback chain (FIX-LIVE-E) ✓
- Q2 MSTR went USELESS→PASS — `_run_fallback_chain` correctly tried 3 alts with arg projection
- SSE events visible for fallback attempts
- Tool errors now classified (`tool_argument_error` vs `tool_execution_error`)

### Grader hardening + YoY hint (FIX-LIVE-B) ✓
- Q4 v4 (gross margin trend) now PASS — grader recognises honest data-gap answers
- Q4 v5 (AMD YoY) now PASS — agent picks up `periods≥5` from new addendum
- 5/5 grader unit tests pass

### PathExplanation worker (FIX-LIVE-C) ✓
- 0 `AttributeError: 'ExtractionOutput' object has no attribute 'output'` post-restart
- 12 explanations persisted on first tick (was 0/12,910)
- Gauge `path_insight_explanation_pending_total` now scrapeable on scheduler:9108

### Gateway Valkey resilience (FIX-LIVE-D) ✓
- `valkey_health` event at startup
- Retry-with-backoff fires (50ms apart, confirmed live)
- `rate_limiting_unavailable_total` counter scrapes on /metrics
- Post-Valkey-restart: 33ms recovery (was instant 503)

### F-1 PREPARE noise reduction (FIX-LIVE-F) ✓
- 171 → 41 failures (78% reduction)
- `:name` translator + `Name+Constant` fold work as designed
- **0 hidden real schema bugs** — confirmed Phase 5c "2 real bugs" were extractor false positives

### FundamentalsRefresh observability (FIX-LIVE-G) ✓
- Per-call `failure_reason` field on every warning
- `failure_breakdown` aggregate shows real root cause is data coverage (98%) not JWT auth
- Coverage still 0/2405 (separate plans needed — documented in `2026-05-24-fix-live-g-fundamentals-refresh.md`)

## New Live-Only Findings (4)

### F-LIVE-J — DeepInfra tool-result follow-up failure (BLOCKING)
**Surfaced by**: FIX-LIVE-A live verification
**Symptom**: Q4 v1, v2, v6 + weak-point survey: agent calls `get_fundamentals_history` (tool call present in tool_calls), but the second LLM turn fails with empty `provider_chat_with_tools_failed` error. Result: agent never gets tool results back; rationalisation prose + fabricated numbers fill the void.
**Root cause hypothesis** (per FIX-LIVE-A report): DeepInfra rejects the tool-result follow-up message — likely payload size, role ordering, or tool_calls schema mismatch when injecting tool results.
**Fix needed**: investigate DeepInfra request shape on second turn; compare working (Q3 narrative) vs failing (Q4 fundamentals comparison) payload structure.
**Impact**: blocks the zero-HARMFUL gate. Until fixed, Q4 v1 can fabricate "AMD revenue > $15B" because the validator can't reject what isn't there.

### F-LIVE-K — Q7 HTTP 401 (CRITICAL)
**Surfaced by**: FIX-LIVE-D gateway resilience exposed
**Symptom**: Q7 "What contradictions exist around Tesla's outlook?" returns HTTP 401 `Authentication required` (was 503 before FIX-LIVE-D fixed the gateway).
**Root cause hypothesis**: `get_contradictions` tool path has separate JWT/auth wiring that's broken. Gateway is correctly enforcing auth (good); tool client missing the right token.
**Fix needed**: trace `get_contradictions` HTTP call from rag-chat → KG, identify auth header missing.

### F-LIVE-L — Q8 regressed PASS→USELESS (CRITICAL)
**Surfaced by**: FIX-LIVE-A cache invalidation
**Symptom**: Q8 "How is OpenAI connected to Microsoft?" was PASS before (cached). After cache invalidation, returns USELESS with HTTP_ERROR + `missing required tool from ['traverse_graph', 'get_entity_paths']`.
**Root cause hypothesis**: `traverse_graph` tool was already broken when Q8 was originally cached; the cached PASS was hiding the regression.
**Fix needed**: trace `traverse_graph` failure — likely related to F-LIVE-J (same second-LLM-turn pattern) OR separate KG-Cypher issue.

### F-LIVE-M — Q6 screener still returns 0 tickers (MAJOR)
**Surfaced by**: FIX-LIVE-D Valkey resilience exposed (gateway no longer 503s)
**Symptom**: Q6 "Find undervalued AI semiconductor companies..." returns 0 ticker mentions; the agent doesn't list NVDA/AMD/AVGO/TSM/etc.
**Root cause hypothesis**: `screen_universe` tool returns empty for the filter the LLM constructs OR the LLM doesn't construct the right filter (sector="Semiconductors" doesn't exist; closest is "Technology" — per INV-LIVE-D).
**Fix needed**: extend `_handle_screen_universe` to accept `industry` filter; update prompt to teach the LLM to compose screen + compare for narrow queries.

## Verdict Logic

Per the plan's gates:
- ≥ 6/8 USEFUL on audit questions: **3** USEFUL (Q1, Q2, Q3) → **FAIL**
- 0 HARMFUL: **2** HARMFUL (Q4 v1, Q4 v6) → **FAIL**

**Overall: still FAIL** on the strict letter of the law. But "FAIL with substantial movement and a clear next-step plan" is qualitatively different from "FAIL because the cache silently bypassed everything we shipped."

## Recommendations

### Path A — Continue (~1 day of focused work)
Spawn 4 focused fix agents:
- **FIX-LIVE-J**: investigate + fix DeepInfra tool-result follow-up (highest leverage — unblocks Q4 v1/v2/v6 + survey)
- **FIX-LIVE-K**: contradiction tool auth wiring
- **FIX-LIVE-L**: traverse_graph tool fix (likely same as J)
- **FIX-LIVE-M**: screen_universe industry filter + prompt hint
Then re-QA again. Expected: 8+/15 PASS, 0 HARMFUL.

### Path B — Ship what's done + plan follow-up
Accept the current wins (cache poisoning eliminated, fallback chain works, grader hardened, gateway resilient, scheduler observable, FundamentalsRefresh investigated). Document F-LIVE-J/K/L/M as PLAN-0094 scope. Mark PLAN-0093 as `complete with known regressions`.

### Path C — Hybrid (recommended)
- Ship FIX-LIVE-J only (the BLOCKING gate) — it's the single biggest unlock (Q4 v1/v2/v6 + survey)
- Defer K/L/M to a follow-up plan
- After FIX-LIVE-J, re-QA Q4 only; if 0 HARMFUL, declare PASS_WITH_NOTES and ship

## Phase 5c+Remediation Commit Log

| SHA | Scope |
|---|---|
| 95ac9769 | F-LIVE-001 APP_ENV templates |
| fc0466fb | F-LIVE-002+003 migration 0044+0046 fixes |
| 930a823d | F-LIVE-004+005 G-1 test SQL fixes |
| 8c02552e | Investigation consolidation (5 INV agents) |
| 07d8e8c9 | FIX-LIVE-C PathExplanation + scheduler /metrics |
| 0cc84ab0 + 868a7b3c | FIX-LIVE-D gateway Valkey resilience |
| c0e0be92 | FIX-LIVE-F PREPARE :name + AST fold |
| cc83a12e | FIX-LIVE-G FundamentalsRefresh observability |
| 4d5584ce (merged fea51bcc) | FIX-LIVE-A cache key v1→v2 |
| 8a58c1ad (merged 9af422b9) | FIX-LIVE-B validator + grader + YoY |
| ebf42ee7 (merged bdb4c904) | FIX-LIVE-E tool-fallback chain |

Total Phase 5c remediation effort: 11 fix commits + 3 merge commits + 6 investigation+audit doc commits = 20 commits across ~6 hours.

## Compounding (final tally for Phase 5c)

New BP/HR/R candidates surfaced across the 5 INV agents + 7 FIX agents:
- BP — Completion-cache poisoning across prompt versions (must bump key on prompt change)
- BP — Eval harness must always use fresh thread_id OR disable cache
- BP — Static SQL extractor must fold `Name + Constant` BinOp
- BP — `assert_*_or_die` shipped without env wiring → fresh-clone outage
- BP — Migration not run live before merging
- BP — `SET DEFAULT <column_name>` is not valid SQL
- BP — Worker happy-path tests use bare MagicMock instead of `spec=<DataclassType>`
- BP — ToolExecutor blanket Exception swallow masks tool-argument errors
- BP — Worker SLO test confuses upstream-empty with worker-broken
- BP — Long worker cycle on fresh boot triggers false SLO failure
- HR — Caching above a strict-output validator is unsafe by construction
- HR — Markdown-table cell context defeats local-window classifiers
- HR — Static QA cannot certify runtime correctness (the meta-finding)
- HR — Gitignored config + lifespan invariants = silent fresh-clone outage
- R-NEW — Static SQL drift checks operate on composed statements only
- R-NEW — Every new boot-time assertion must include env_var addition in every docker.env.example + a regression test that `docker compose config` resolves the env

These should be propagated into BUG_PATTERNS.md / HIGH_RISK_PATTERNS.md / RULES.md in a follow-up compounding commit.
