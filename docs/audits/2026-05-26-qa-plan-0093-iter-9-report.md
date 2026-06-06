---
id: QA-PLAN-0093-ITER-9
title: PLAN-0093 Iter-9 QA — Multi-Agent Adversarial Review
date: 2026-05-26
predecessor: docs/audits/2026-05-25-qa-plan-0093-phase-5c+1-reqa-results.md
branch: feat/plan-0093-remediation
head: 0b929611
agents: 5 (live-chat, code-review, data-infra, tests-arch, docs-completion)
overall_verdict: FAIL
---

# QA Report: PLAN-0093 (Iter-9 Multi-Agent Adversarial)

**Date**: 2026-05-26 22:26 UTC
**Skill**: qa
**Scope**: PLAN-0093 implementation + PLAN-0094 overlay (same branch)
**Branch**: `feat/plan-0093-remediation` @ `0b929611`
**Verdict**: **FAIL** — two distinct failure modes (data-layer SLOs + PLAN-0094 regressions)

---

## Executive Summary

Five parallel adversarial QA agents reviewed PLAN-0093's implementation 8 commits after the most recent audit (2026-05-25). The encouraging finding: **PLAN-0093's own code is clean** — architecture-compliant, BP-405-verified, test-passing, migration-safe, and the compounding artefacts (BP-551..570, R35, HR-051/052/053) are well-formed and ingested. The agent's hallucination-defence layer is now correctly distinguishing `[unverified]`-quoted suspect data from outright fabrication (F-LIVE-N **RESOLVED**), which saved the platform on Q4 — the agent refused to compare AMD/NVDA revenues rather than asserting the bad numbers.

But the **data layer underneath is still broken**. AGE has 0 of 14,822 TemporalEvent nodes (T-B-1-01 fix doesn't work in practice). `document_source_metadata.impact_score` is 100% NULL across 7,062 docs. `entity_embedding_state.fundamentals_ohlcv` is 100% NULL across 2,405 rows. `get_fundamentals_history` is mixing annual and quarterly periods — the $34.6B AMD figure is the FY2025 annual row leaking into a "Q1 FY2026" query result. And critically, **the NLP pipeline has been stalled for ~24h** — `entity_mentions=0`, `mention_resolutions=0`, 94 DLQ rows accumulating on `content.article.stored.v1`.

A second, distinct failure mode comes from the PLAN-0094 daily-brief overlay that landed on this branch in the last 8 commits: 8 api-gateway test failures (rate-limit middleware missing kwargs), 5 architecture-test failures (layer-isolation + `datetime.utcnow` + direct `redis.asyncio` import), a JWT contextvar leak that pollutes the parent request, and silent data destruction where the pre-generation worker passes `internal_jwt=None`, gets 401s from S5/S6/S7, "degrades safely" to an empty payload, then **overwrites the last-good brief key with empty content on every "successful" run**.

The platform's user-facing chat is **safer than before** — refusal works, no PASS_WITH_WARNINGS regression on PLAN-0094's morning brief endpoint. But the implementation cannot be marked complete: F-LIVE-O (Tesla resolver) and F-LIVE-P (period mixing) remain open, and FIX-LIVE-II introduced a new false-positive (F-LIVE-NEW-001: "AI semiconductor space" fuzzy-matched to **SpaceX**). Verdict reversal requires (1) data-layer fixes on AGE / impact_score / fundamentals / NLP restart, (2) backing out the PLAN-0094 architecture regressions, and (3) tightening the entity-resolver similarity threshold (likely too relaxed after FIX-LIVE-II).

---

## Multi-Agent Review Summary

| Agent | Mandate | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT | Verdict |
|-------|---------|----------|----------|----------|-------|-------|-----|---------|
| QA-1 Live Chat | 8 audit questions vs live `/v1/chat`; verify F-LIVE-N/O/P/Q status | 5 | 0 | 2 | 1 | 2 | 0 | **FAIL** |
| QA-2 Code Review | Adversarial review of 8 post-2026-05-25 commits | 11 | 0 | 0 | 3 | 5 | 3 | PASS_WITH_WARN |
| QA-3 Data + Infra | Live SLO queries vs original audit targets + infra survival | 7 | 1 | 3 | 0 | 2 | 1 | **FAIL** |
| QA-4 Tests + Arch | Architecture + per-service unit + frontend + BP-405 + migration safety | 13 | 0 | 0 | 13 | 0 | 0 | **FAIL** |
| QA-5 Docs + Completion | BP/RULES/HR artefacts + task completion sampling + audit closeout | 4 | 0 | 0 | 0 | 3 | 1 | PASS_WITH_WARN |
| **Total** | — | **40** | **1** | **5** | **17** | **12** | **5** | **FAIL** |

### Cross-Agent Signals (HIGH Confidence — flagged by 2+ agents independently)

| Convergence | Severity | Agents | Evidence |
|---|---|---|---|
| Q4 NVDA/AMD data layer wrong (period mixing) | **BLOCKING** | QA-1 (F-LIVE-P), QA-3 (impact_score / fundamentals_ohlcv) | live query + grader output |
| AGE TemporalEvent sync broken despite T-B-1-01 fix | **CRITICAL** | QA-3 (live), QA-1 (chat tools can't traverse events) | `MATCH (n:TemporalEvent)` returns 0 |
| PLAN-0094 overlay introduced architecture violations | CRITICAL | QA-2 (F-CR-003/004), QA-4 (5 arch failures) | layer-isolation + utcnow + redis import |
| Entity resolver false-positives | CRITICAL | QA-1 (F-LIVE-O Tesla + F-LIVE-NEW-001 SpaceX), QA-2 (FIX-LIVE-II "generic but no threshold check") | both questions failed |
| Silent worker failure pattern | MAJOR | QA-2 (F-CR-004 empty-brief worker), QA-3 (NLP pipeline stalled 24h) | both produce "successful" logs with broken outputs |

### Fixes Applied During This QA
None — this was a read-only audit pass.

### Decisions Made
None — all decisions deferred to the user for follow-up plan scoping.

### Open Items (priority order)

| ID | Description | Owner |
|---|---|---|
| **F-LIVE-P** | `get_fundamentals_history` mixes annual + quarterly periods (root of Q4 fabrication) | follow-up plan |
| **F-DB-NEW-001** | NLP pipeline stalled 24h — `entity_mentions=0`, 94 DLQ accumulating | immediate ops |
| **F-DB-002** | AGE TemporalEvent sync still broken (0 of 14,822) — T-B-1-01 fix is wrong | follow-up plan |
| **F-LIVE-O** | Tesla contradictions classifier returns `intent=GENERAL` | follow-up plan |
| **F-LIVE-NEW-001** | Entity resolver false-positive: "AI semiconductor space" → SpaceX | follow-up plan |
| **F-DB-003** | `document_source_metadata.impact_score` 100% NULL despite T-C-3-03 wiring | follow-up plan |
| **F-DB-004** | `entity_embedding_state.fundamentals_ohlcv` 100% NULL despite T-C-4-03 scoping | follow-up plan |
| **F-CR-003** | PLAN-0094: JWT contextvar leak in `public_briefings.py` | PLAN-0094 fix |
| **F-CR-004** | PLAN-0094: pre-gen worker passes `internal_jwt=None`, overwrites lastgood with empty | PLAN-0094 fix |
| **F-ARCH-001..005** | PLAN-0094: 5 architecture violations in scheduler/worker code | PLAN-0094 fix |
| **F-TEST-001..008** | PLAN-0094: 8 api-gateway middleware tests need kwargs update | PLAN-0094 fix |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Architecture | full | — | — | 5 | — | **FAIL** (all PLAN-0094) |
| knowledge-graph unit | service | 1420 | 1415 | 0 | 5 (+2 xfail) | PASS |
| nlp-pipeline unit | service | 1009 | 1006 | 0 | 3 xfail | PASS |
| rag-chat unit | service | 1273 | 1273 | 0 | 0 | **PASS** |
| api-gateway unit | service | 579 | 571 | 8 | 0 | **FAIL** (all PLAN-0094) |
| market-data unit | service | 738 | 738 | 0 | 0 | PASS |
| Frontend Vitest | apps/worldview-web | — | — | — | — | NOT-RUN (harness issue) |
| Static validation | tests/validation | 4 | 3 | 0 | 1 | PASS |
| Live chat-eval | 8 questions | 8 | 6 | 2 | 0 | **FAIL** |

### Per-Service Breakdown
| Service | Unit | Notes |
|---|---|---|
| knowledge-graph | PASS | 1415/1420; ITER-8 test inversion (F-CR-001) is a R19-borderline NIT |
| nlp-pipeline | PASS | 1006/1009 |
| rag-chat | **PASS** | All 1273 tests pass — agent code is clean |
| api-gateway | **FAIL** | 8 tests fail because PLAN-0094 added 3 RateLimitMiddleware kwargs without updating tests |
| market-data | PASS | clean |

---

## Supplementary Checks

| Check | Status | Notes |
|---|---|---|
| BP-405 name verification | PASS | All 5 spot-checked classes exist |
| R10 (UUIDv7) | PASS | No `uuid.uuid4` in PLAN-0093 diffs |
| R11 (UTC) | **FAIL** | `brief_scheduler_main.py:209` uses `datetime.utcnow()` (PLAN-0094) |
| R12 (structlog) | PASS | No stdlib `logging` in PLAN-0093 diffs |
| R25 (ABC ports) | **FAIL** | `morning_brief_pregeneration_worker.py:240` imports `rag_chat.api.schemas` (PLAN-0094) |
| R8 (outbox) | PASS | Preserved |
| R32 (Alembic head) | PASS | Migrations 0044-0048 + 0020 all present and applied |
| R35 (depends_on healthchecks) | PASS | Verified at `RULES.md:347` |
| Migration TRUNCATE safety | PASS | 0045/0047/0020 all carry `APP_ENV=production` guard |
| BP-551..570 ingestion | PASS | 20 well-formed entries, 250-500 words each |
| HR-051/052/053 | PASS | All 3 present |
| Restart policies | PASS | ollama / schema-registry / market-data all `unless-stopped` |
| APP_ENV propagation | PASS | Set on rag-chat / kg / nlp / api-gateway |

---

## Issues — Full Investigation

### Issue F-LIVE-P: Q4 NVDA/AMD revenue — period mixing in `get_fundamentals_history`

**Severity**: BLOCKING | **Confidence**: HIGH | **Flagged by**: QA-1 (live), QA-3 (data)

#### Root Cause Analysis
- **What**: When the chat agent asks "AMD Q1 FY2026 revenue", the `get_fundamentals_history` tool returns `$34.639B` labeled as Q1 FY2026. Ground truth verified in `market_data_db.fundamental_metrics`: AMD Q1 2026 = **$10.253B**. The $34.639B value IS in the DB — it's the FY2025 **annual** row. The query is not filtering by `period_type` (quarterly vs annual).
- **Why**: The fundamentals query / repository likely uses `ORDER BY period_end DESC LIMIT N` without a `WHERE period_type = 'quarterly'` clause, so the annual row (with period_end = 2025-12-31) sorts above the quarterly rows when the LLM asks for recent quarters.
- **When**: every call to `get_fundamentals_history(period_type='quarterly')` for any ticker where the most recent annual row is more recent than the most recent quarterly row
- **Where**: `services/market-data/src/market_data/api/routers/fundamental_metrics.py` (the router) + the repository it calls
- **History**: F-LIVE-P was identified on 2026-05-25; classified as "data gap" rather than period-mixing. This audit narrows the diagnosis.

#### Evidence
```
Q4 chat response (verbatim):
> "AMD's Q1 FY2026 revenue was $34.639B [unverified]"

Ground truth:
docker exec worldview-postgres-1 psql -U postgres -d market_data_db -c "
  SELECT period_type, period_end, revenue
  FROM fundamental_metrics
  WHERE entity_id = (SELECT entity_id FROM instruments WHERE symbol='AMD')
  ORDER BY period_end DESC LIMIT 5"
-- Returns: 2025-12-31 annual $34.639B; 2026-03-31 quarterly $10.253B
```

The agent's `[unverified]` marker (F-LIVE-N RESOLVED) prevented user-visible fabrication — but the bad data IS flowing to the LLM.

#### Impact
- **Immediate**: every Q-style chat question (revenue, EPS, FCF for a recent quarter) gets the most recent annual row instead of the most recent quarterly row.
- **Blast radius**: any tool consumer of `get_fundamentals_history` — `compare_entities`, `get_entity_intelligence`, screener with growth filters
- **Data risk**: zero — the agent refuses correctly; PLAN-0093's defence-in-depth saves the platform
- **User impact**: every comparison/trend question returns "I cannot verify" rather than useful data → bad UX, not bad data

#### Solution Options
**Option A (recommended): Period-type filter in fundamentals repository**
Add `WHERE period_type = :period_type` to the SQL in the repository. Default `period_type` for `get_fundamentals_history` should be `'quarterly'` (LLM almost always asks for quarters). Add a separate `get_annual_fundamentals` tool if the LLM needs annual.
- Effort: Low
- Risk: Low

**Option B: Tool schema split**
Split `get_fundamentals_history` into two tools: `get_quarterly_fundamentals` and `get_annual_fundamentals`. LLM picks based on question.
- Effort: Medium (tool catalogue change, prompt update)
- Risk: Medium (need to re-tune LLM behavior)

**Option C: Defer to follow-up plan**
Document F-LIVE-P as out-of-scope for PLAN-0093 (since the agent's refusal saves the user). Schedule for PLAN-0095.
- Effort: zero now
- Risk: high (the data layer stays wrong)

**Recommended: Option A** — narrowest correct fix, no LLM retraining needed.

---

### Issue F-DB-002: AGE TemporalEvent sync still broken (T-B-1-01 fix doesn't work)

**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: QA-3

#### Root Cause
- **What**: `MATCH (n:TemporalEvent) RETURN count(n)` returns **0** in AGE; DB has **14,822** rows in `intelligence_db.temporal_events`. T-B-1-01 was supposed to add `_bootstrap_age_labels()` that creates the `TemporalEvent` vlabel before first sync.
- **Why**: Either (a) the bootstrap helper IS in the code but is silently raising and being caught, or (b) it ran successfully but the sync loop's MERGE still fails for a different reason (label exists but property type mismatch?), or (c) the bootstrap runs once at startup but the watermark advances past the existing 14,822 rows on first iteration so they're never re-scanned.
- **History**: Original BLOCKING from 2026-05-23 audit. Was supposed to be fixed by T-B-1-01.

#### Recommended Fix
Investigation task — read `age_sync_worker.py` and find why the bootstrap helper doesn't produce live data. Likely fix: run the watermark reset script + bootstrap once explicitly. If the bootstrap IS running, instrument it with a Prometheus counter so future runs are observable.

---

### Issue F-DB-NEW-001: NLP pipeline stalled ~24h

**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: QA-3

#### Root Cause
- **What**: `entity_mentions=0`, `mention_resolutions=0`, `chunk_entity_mentions=0` despite 7,062 documents and 9,215 chunks ingested. 94 DLQ rows accumulating on `content.article.stored.v1`. Latest `canonical_entities.created_at` = 2026-05-24. Latest `relations.created_at` = 2026-05-25.
- **Why**: Unknown without deeper investigation — could be (a) NER worker crashed and not restarted (despite Sub-Plan A restart policies — check if `nlp-pipeline-article-consumer` is in the `unless-stopped` set), (b) GLiNER container offline, (c) a code change in NER persistence path that silently rejects all writes.
- **When**: started ~24h before audit (2026-05-25 19:00 UTC by latest timestamps)

#### Impact
- Until NLP NER persists again, AGE/embedding backfills cannot regenerate
- New articles flow in (7,062) but produce no entities
- Highest-leverage next action — without this, fixing F-DB-002 / F-DB-003 / F-DB-004 is pointless

#### Recommended Fix
Immediate ops investigation. Read DLQ messages, inspect article-consumer logs since 2026-05-25 19:00, identify the systematic failure cause.

---

### Issue F-CR-003: PLAN-0094 JWT contextvar leak in `public_briefings.py`

**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: QA-2

#### Root Cause
- **What**: `public_briefings.py` calls `set_current_jwt(bg_jwt)` BEFORE `asyncio.create_task(...)`. The contextvar is set in the parent request's context, then leaks into other requests sharing the same task scope.
- **Why**: ContextVar semantics — set + create_task in same scope makes the background JWT visible to anything sharing the parent context.
- **Impact**: cross-request JWT contamination; could leak a privileged background JWT into a less-privileged user's request context

#### Recommended Fix
Use `contextvars.copy_context()` and run the background task in the copy. Or restructure so the bg JWT is passed as a positional arg, not via contextvar.

---

### Issue F-CR-004: PLAN-0094 silent data destruction in pre-gen worker

**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: QA-2

#### Root Cause
- **What**: `morning_brief_pregeneration_worker.py:243` calls `execute_public_morning(internal_jwt=None)` after PRD-0025 mandated internal JWT validation on every upstream call. Upstream S5/S6/S7 return 401. `BriefingContextGatherer` catches and "degrades safely" to empty payload. The worker then **overwrites the last-good key with the empty brief on every "successful" run**.
- **Why**: The worker was written before realising internal JWT propagation is mandatory; nobody noticed because the metric shows "1 brief generated, 0 errors" — the failure is silent.
- **Impact**: every scheduled pre-generation run destroys the last-good cached brief

#### Recommended Fix
1. Pass a service-level internal JWT (machine-to-machine) to the worker
2. Add a "non-empty content" check before overwriting the cache key
3. Add a Prometheus counter `brief_pregen_empty_payload_total`

---

### Issue F-LIVE-O: Tesla contradictions classifier returns wrong intent

**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: QA-1

#### Root Cause
- **What**: Q7 ("What contradicts the bull thesis on Tesla right now?") routes with `intent=GENERAL` instead of `CONTRADICTION` or `RELATIONSHIP`. The contradictions tool runs but with an unresolved Tesla entity context and returns empty.
- **Why**: The intent inference logic (T-E-1-02) probably doesn't have a strong "contradiction" signal pattern. ITER-8 fix (`461d030b`) addressed classifier fail-open but didn't add a CONTRADICTION trigger.

#### Recommended Fix
Add explicit `CONTRADICTION` intent pattern matching for question forms like "what contradicts", "what disagrees with", "counterargument to X". Wire into the intent classifier OR make `get_contradictions` a tool that ALWAYS runs when these phrases appear, regardless of intent.

---

### Issue F-LIVE-NEW-001: Entity resolver fuzzy-matches "AI semiconductor space" → SpaceX

**Severity**: MAJOR | **Confidence**: HIGH | **Flagged by**: QA-1 (correlation with QA-2 FIX-LIVE-II concern B)

#### Root Cause
- **What**: Q6 ("Find me companies in the AI semiconductor space with rising analyst sentiment") routed the phrase "AI semiconductor space" to entity resolution. Fuzzy match returned **SpaceX** (substring "space"). Agent spent 100s reconciling.
- **Why**: FIX-LIVE-II relaxed the similarity threshold to fix Tesla alias collision (F-LIVE-O). The relaxed threshold now admits weak substring matches across the canonical-name index.
- **When**: introduced by commit `f6b76ff9` (FIX-LIVE-II)

#### Recommended Fix
Tighten the similarity threshold; add a stop-word filter to entity resolution that strips "space", "industry", "sector", "market", "system" from the input before matching.

---

### MAJOR/MINOR Issues (Summary)

| ID | Source | File / Area | One-line |
|---|---|---|---|
| F-CR-001 | QA-2 | `test_structured_enrichment.py:461` | KG test inverted in ITER-8 — R19 borderline |
| F-LIVE-NEW-002 | QA-1 | `NewsHandler._handle_search_documents` | rejects `to_date` kwarg — schema drift |
| F-ARCH-001 | QA-4 | `morning_brief_pregeneration_worker.py:240` | imports `rag_chat.api.schemas` (LAYER-APP-ISOLATION) |
| F-ARCH-002 | QA-4 | `brief_scheduler_main.py:209` | `datetime.utcnow()` (IG-COMMON-002) |
| F-ARCH-003 | QA-4 | `brief_scheduler_main.py:148` | direct `redis.asyncio` import (IG-MSG-002) |
| F-TEST-001..008 | QA-4 | `test_middleware.py`, `test_rate_limit_middleware.py` | 8 fails — PLAN-0094 added 3 RateLimitMiddleware kwargs |
| F-DB-003 | QA-3 | `document_source_metadata.impact_score` | 100% NULL despite T-C-3-03 wiring |
| F-DB-004 | QA-3 | `entity_embedding_state.fundamentals_ohlcv` | 100% NULL despite T-C-4-03 scoping |
| F-DB-005 | QA-3 | rdkafka `broker.address.ttl=30000` | not visible in env — unverifiable |
| F-DB-006 | QA-3 | definition embeddings | 568/5503 NULL (10.3%, above 5% SLO) |
| F-DB-007 | QA-3 | synthetic-monitor | 55 errors/hr, 401 on `/v1/quotes/{id}` |
| F-DOCS-001 | QA-5 | `market-data/.claude-context.md` | missing T-C-3-01 entry |
| F-DOCS-002 | QA-5 | TRACKING.md | still `in-progress` despite closeout recommendation |
| F-DOCS-003 | QA-5 | plan frontmatter `revision_log` | not updated past 2026-05-23 |
| F-CR (5 MINOR) | QA-2 | various | provider-chain stream metric conflation, backoff no jitter, etc. |

---

## Recommendations

### Immediate (P0 — fix today)
1. **Investigate F-DB-NEW-001** (NLP pipeline stalled 24h). Until NER persists again, every other data-layer fix is pointless. Read DLQ messages on `content.article.stored.v1`; inspect article-consumer logs.
2. **Investigate F-DB-002** (AGE TemporalEvent sync). Read `age_sync_worker.py` `_bootstrap_age_labels()`. Run watermark reset. Confirm vlabel created.
3. **Patch F-CR-004** (empty-brief overwrite) — add the "non-empty content" guard before overwriting the cache key. This is silent data destruction in production.

### Short-term (P1 — fix this week)
4. **F-LIVE-P** — add `WHERE period_type = :period_type` to fundamentals SQL. Fixes the AMD $34.6B root cause permanently.
5. **F-LIVE-O + F-LIVE-NEW-001** — tighten entity-resolver similarity threshold + add stop-word filter ("space", "industry", "sector").
6. **F-CR-003** — fix JWT contextvar leak with `contextvars.copy_context()`.
7. **F-ARCH-001..005 + F-TEST-001..008** — fix PLAN-0094 layer violations and update middleware tests.

### Medium-term (P2)
8. **F-DB-003 + F-DB-004** — investigate why `impact_score` writer (T-C-3-03) and `fundamentals_ohlcv` worker (T-C-4-03) produce no rows despite the code being shipped.
9. **F-CR-001** — restore the KG test's behavioural assertion (uninvert ITER-8 test).
10. **F-DOCS-001..003** — close documentation drift.

### Process improvements
- The "implementation code is clean but data layer doesn't deliver" pattern recurred across multiple fixes (T-B-1-01, T-C-3-03, T-C-4-03). Future plans should require **post-deploy live SLO verification** (not just unit tests) before declaring a wave done.
- PLAN-0094 overlay introduced regressions that this audit caught only because the QA scope included the whole branch. Plans that overlay on top of in-progress plans should run their own QA gates, not inherit the parent plan's "done" state.

---

## Verdict Logic Applied

- BLOCKING findings: **1** (F-LIVE-P)
- CRITICAL findings: **5** (F-DB-002 AGE, F-DB-NEW-001 NLP stalled, F-CR-003 JWT leak, F-CR-004 empty-brief, F-LIVE-O Tesla)
- Test layer failures: **2** (architecture 5 fails, api-gateway 8 fails) — both PLAN-0094-attributable
- Live chat-eval: **2 of 8 fail**

**Verdict**: **FAIL** — cannot mark PLAN-0093 done. Both data-layer SLOs and PLAN-0094 architecture/test regressions block completion.

**However**: PLAN-0093's *own* code is clean. The 2026-05-25 closeout was right that the plan's implementation is sound; the wrong conclusion was that the data layer would catch up. It hasn't. Recommend opening **PLAN-0095** to address F-LIVE-P/O/NEW-001 + F-DB-002/NEW-001/003/004, and a separate **PLAN-0094-fix** wave to address the architecture/test regressions on this same branch.

---

## TRACKING.md Update Required

```diff
- | PLAN-0093 | ... | in-progress | 24/24 | F-LIVE-006 + F-LIVE-008 (RAG quality) | 2026-05-24 |
+ | PLAN-0093 | ... | qa-fail | 24/24 | 5 CRITICAL: F-LIVE-P, F-DB-002, F-DB-NEW-001, F-CR-003, F-CR-004, F-LIVE-O. See 2026-05-26 iter-9 report. | 2026-05-26 |
```

## Compounding (Mandatory)

- **BP-NEW candidates** (to add to `docs/BUG_PATTERNS.md`):
  - BP-571 — "Implementation code is clean but data layer doesn't deliver" — wave declared done without post-deploy SLO verification (recurred 3x in PLAN-0093: T-B-1-01, T-C-3-03, T-C-4-03)
  - BP-572 — "Period-type leak in fundamentals query" — annual rows leak into quarterly result sets when no `WHERE period_type` clause (root of $34.6B AMD bug)
  - BP-573 — "Silent worker overwrites lastgood with empty payload after upstream auth failure" — pattern in F-CR-004
  - BP-574 — "Relaxing similarity threshold creates new false-positives" — F-LIVE-NEW-001 SpaceX as direct consequence of F-LIVE-O Tesla fix
  - BP-575 — "JWT contextvar leak via set-before-create_task" — F-CR-003
- **HR-NEW candidates**: HR-054 "Cross-plan branch overlay" — plans that share a branch can leak regressions without their own QA gate.
- **REVIEW_CHECKLIST.md additions**:
  - "Does this wave's claimed fix have a live SLO query verifying it works on real data?"
  - "Does this background worker have a 'non-empty content' guard before overwriting cached state?"
  - "Does this fuzzy-matcher have a stop-word filter for common ambiguous terms (space, industry, sector)?"
- **Skill improvement** (`.claude/skills/qa/SKILL.md`): add a step explicitly checking for cross-plan overlay on the audited branch — `git log --grep "PLAN-0[0-9][0-9][0-9]" | sort -u`.

---

**Report file**: `docs/audits/2026-05-26-qa-plan-0093-iter-9-report.md`
**Raw findings**: `/tmp/qa-iter9-A{1..5}-*.md`
