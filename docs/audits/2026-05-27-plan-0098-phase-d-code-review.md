# PLAN-0098 Phase-D Adversarial Code Review

**Date**: 2026-05-27
**Reviewer**: Code-review agent (parallel with W2/W3/W4 implementation)
**Branch**: `feat/plan-0093-remediation` HEAD `7e8ec9a8`
**Scope**: Every PLAN-0098 commit landed plus uncommitted working-tree work for W2/W3/W4

---

## VERDICT: FAIL (blocking) on stash markers + CONDITIONAL PASS on code

**FAIL deal-breaker**: five files contain unresolved `<<<<<<< Updated upstream` stash conflict markers (alert/routes.py, alert tests, rag-chat brief_scheduler_main, briefing_context_gatherer tests). Two cause Python SyntaxErrors collected today in rag-chat. All five are staged via `git status -M`. **Any W2/W3/W4 commit captures them and lands a SyntaxError.**

Otherwise CONDITIONAL PASS — on-disk W2/W3/W4 code is largely correct; bookkeeping (BP-584 missing, TRACKING.md claims W3 shipped before commit) is inconsistent.

---

## 1. Commit & Working-tree Inventory

| Item | Status | Commit / Path |
|---|---|---|
| W1 T-W1-01 (chunk_search R40 sentinel) | **SHIPPED** | `7e8ec9a8` |
| W2 T-W2-01 (NLP article_consumer pre-persist guard + new test) | uncommitted | `article_consumer.py`, `test_article_consumer_tenant_id_propagation.py` (344 LOC, untracked) |
| W2 T-W2-02..04 (AGE reconcile, FundamentalsRefreshWorker, revenue JSONB) | **NOT STARTED** | n/a |
| W3 T-W3-01/02 (screen_field numeric coercion + regression test) | uncommitted | `services/market-data/src/market_data/app.py`, `services/market-data/tests/unit/test_app.py` |
| W4 T-W4-01 (benign-relationship asymmetric test) | uncommitted | `test_llm_injection_classifier_benign_relationships.py` |
| W4 T-W4-02 (fundamentals.py:222 None handling + `_REASON_INVALID_LOOKUP`) | uncommitted | `services/market-data/src/market_data/api/routers/fundamentals.py` |
| W4 (R36→R41 comment cleanup) | uncommitted | `age_sync_worker.py` |
| W5 T-W5-01/02 (NVDA/AMD row-mix, intra-ticker parallel) | **NOT STARTED** | n/a |

TRACKING.md (line 40) claims W3 SHIPPED 2026-05-27. **It is not committed.** Doc drift.

---

## 2. Test Regression Sweep (per-service targeted suites)

| Service | Result | Baseline | Delta |
|---|---|---|---|
| nlp-pipeline | `1018 passed, 3 xfailed` (144 s) | matches W1 commit message claim | clean |
| market-data | `731 passed` (27 s) | prior 730 from PLAN-0097 W3 + 1 new W3 BP-585 test | clean |
| knowledge-graph | `1411 passed, 6 skipped, 2 xfailed` (83 s) | prior baseline | clean |
| rag-chat | **2 collection ERRORS** (SyntaxError @ line 689 + line 172) | n/a | **regression** |
| rag-chat (excluding the 2 broken files) | `1263 passed, 14 skipped` (22 s) | matches W4 strengthening | clean |

The two rag-chat collection errors are **not** the pre-existing tool-registry collection skip the prompt mentioned; they are brand-new SyntaxErrors caused by unresolved stash conflict markers (see §3).

---

## 3. BLOCKING: Five Unresolved Stash Conflict Markers

```
services/alert/src/alert/api/routes.py:185
services/alert/tests/unit/api/test_alerts_api.py:879
services/alert/tests/unit/api/test_alerts_api.py:931
services/rag-chat/tests/unit/application/test_briefing_context_gatherer.py:689
services/rag-chat/src/rag_chat/infrastructure/scheduling/brief_scheduler_main.py:172
```

Likely artefact of a `git stash pop` that conflicted during the parallel-agent multiplexing. None of these files is owned by PLAN-0098 W1, but all five are staged for modification (`git status -M`) and will travel with the next commit if not scrubbed. Two cause immediate Python SyntaxErrors; the alert/route.py one almost certainly breaks the alert service.

**Mandatory pre-commit step for any PLAN-0098 W2/W3/W4 commit**: `grep -rn "^<<<<<<< " services/ apps/` must return zero hits.

---

## 4. W2 NLP Fix — Multi-tenant Correctness

`article_consumer.py`:
- **Pre-persist guard (lines 671-697)**: substitutes `PUBLIC_TENANT_ID` only when `m.tenant_id is None`; real tenant values never overwritten. Correct.
- **NER post-stamp (lines 580-590)**: now unconditional (`m.tenant_id = tenant_id`). Comment claims `tenant_id` guaranteed non-None upstream. **Not verified.** If wrong, the prior `if tenant_id is not None` guard was harmless; unconditional now writes None. **MEDIUM** — add defensive `tenant_id or PUBLIC_TENANT_ID`.
- **Sentinel visibility downstream**: W1 (`7e8ec9a8`) + PLAN-0097 W4 (`news_query`) — symmetry restored on both retrieval surfaces.
- **SQL injection / widening**: substitution is at ORM layer with typed UUID. No widening.
- New `test_article_consumer_tenant_id_propagation.py` (344 LOC, untracked) not run.

---

## 5. W3 BP-585 Fix — Frontend Consumer Audit (per prompt §3)

`grep -rn "fieldType\|field_type" apps/worldview-web/` returns **one match**: `components/screener/ColumnSettingsPopover.tsx:57` and it is a *comment* explicitly noting that the static category map is **not** derived from `field_type`. No `field_type === 'boolean'` or `field_type === "boolean"` matches in `components/`, `lib/`, `features/`, `hooks/`. **Safe** — flipping `"boolean"` → `"numeric"` cannot change any rendering branch.

Downstream the values are already stored as 0/1 ints (per inline comment), so the screener numeric filter still applies and the change is observationally inert. The BP-585 entry in `BUG_PATTERNS.md` is well written.

---

## 6. W4 Test-Quality Strengthening

`test_llm_injection_classifier_benign_relationships.py`:
- New `_labelled_response_mock(label)` parametrises SAFE/UNSAFE.
- New `_ASYMMETRIC_SAMPLE` of 5 queries + `test_classifier_routes_llm_unsafe_verdict_through` asserts `True` on UNSAFE mock. **Confirms genuine LLM-routing, not allowlist short-circuit.**
- SAFE test now also asserts `mock_client.post.await_count == 1` and query string in JSON body. A regression that hard-coded `return False` would now fail.

`fundamentals.py` (W4 T-W4-02): adds `_REASON_INVALID_LOOKUP`, wraps `UUID(resolution.instrument.id)` in `try/except (AttributeError, TypeError, ValueError)`, records in `resolution_overrides[ticker]`. Existing `assert isinstance(resolution, BaseException)` preserved only in non-override branch — refactored correctly. Does not break PLAN-0097 W3 typed reason codes (additive).

`age_sync_worker.py`: R36→R41 in comment + log message, with explanatory aside. No code path change.

---

## 7. Cross-commit interactions (per prompt §5)

- W2 (article_consumer) and W3 (market-data app.py) touch disjoint services. No conflict.
- W4 fundamentals.py:222 defensiveness preserves PLAN-0097 W3 typed reason codes (`invalid_ticker`, `upstream_timeout`, `upstream_404`, `upstream_error`) — they remain the codes for the BaseException branch; `invalid_lookup` is additive.
- W4 R36 → R41 comment update only references RULES.md; no link in `docs/plans/0096-*` or 0097 plan is invalidated (those docs were never updated to call the rule by number).

---

## 8. Documentation Drift

- `BUG_PATTERNS.md`: BP-583 (chunk_search) + BP-585 (screen_field_metadata) filed. **BP-584 missing.** Plan reserves BP-584 for NLP tenant_id stamping. Either BP-584 was silently skipped or future filing will collide. Prompt's hypothesis (BP-585=screen_field, BP-586=NLP) does not match plan (BP-584=NLP, BP-585=screen_field). **File BP-584 for NLP fix per plan.**
- `docs/services/rag-chat.md:506` mentions `RAG_CACHE_DEPLOY_TOKEN` with PLAN-0098 W4 docs-bundle note. Periodicity-column note not verified line-by-line.
- `TRACKING.md:40` claims **W3 SHIPPED 2026-05-27** but no commit exists on this branch. Drift ahead of HEAD.

---

## 9. Migration audit (per prompt §7)

`git log --diff-filter=A --name-only --grep "PLAN-0098" | grep alembic` → no hits. W3 is correctly code-only, no migration shipped. Matches intent.

---

## 10. Latent risk

W2 pre-persist guard is a **safety net** — the actual upstream that produces `tenant_id=None` mentions is not fixed, just stamped. Structlog WARN is invisible without a metric. **Recommend Prom counter** `nlp_pipeline_pre_persist_tenant_id_substituted_total`; if non-zero a week post-deploy, trace upstream block from WARN sample. Otherwise this is BP-575 silent-stats-hygiene repeated.

## 11. New/weird

- Unconditional NER post-stamp (line 583-585): see §4.
- `services/portfolio/src/portfolio/api/internal.py` and `migration 019_composite_fundamentals_indexes.py` are modified in working tree but not in any documented PLAN-0098 wave. Possible accidental contamination from concurrent work; verify before commit.

---

## 12. Verdict (top-level summary)

| Aspect | Verdict |
|---|---|
| W1 chunk_search R40 extension (`7e8ec9a8`) | **PASS** — 4 surfaces fixed, 4 tests pin, BP-583 documented, no regressions |
| W2 NLP pre-persist guard | **CONDITIONAL PASS** — invariant looks right; verify the non-None precondition on the post-stamp loop or add a defensive `or PUBLIC_TENANT_ID` |
| W3 BP-585 numeric coercion | **PASS** — no frontend consumer keys on `boolean`; tests added |
| W4 test strengthening + fundamentals defensiveness | **PASS** — asymmetric test is real, fundamentals widening is additive |
| Stash conflict markers in 5 files | **FAIL — must scrub before next commit** |
| BP numbering (584 skipped or colliding) | **FAIL — file BP-584 for NLP fix before commit** |
| TRACKING.md W3-SHIPPED claim | **FAIL — claim made before commit landed** |

---

## 13. Punch-list for PLAN-0099

1. **Scrub stash markers** in alert/routes.py, alert tests, rag-chat brief_scheduler_main, briefing_context_gatherer tests *before* committing W2/W3/W4. Add a hook: `pre-commit` step `! grep -rn "^<<<<<<< " <staged-files>`.
2. **File BP-584** for the NLP entity_mentions tenant_id pre-persist guard. The plan reserved BP-584 for this; numbering must match plan.
3. **Add `nlp_pipeline_pre_persist_tenant_id_substituted_total` counter** so the W2 safety net is observable. Without this, "happily writing sentinel-tagged rows forever because the upstream is silently broken" is a stable bad state.
4. **Investigate upstream `tenant_id=None` source** in article_consumer that the W2 pre-persist guard catches. The fix is to stamp at construction site, not at persist.
5. **TRACKING.md discipline**: never mark a wave SHIPPED until the commit hash is in `git log`. Add a one-line lint or pre-PR script.
6. **Defensive `or PUBLIC_TENANT_ID`** on the now-unconditional NER post-stamp loop at `article_consumer.py:585` — preserves the prior safety even if the upstream precondition silently breaks.
7. **Verify `services/portfolio/src/portfolio/api/internal.py`** and `migration 019_composite_fundamentals_indexes.py` modifications are intentional; if not, revert before commit.
8. **W2 T-W2-02..04 and W5 still owed** — AGE reconcile drain, FundamentalsRefreshWorker, revenue JSONB hydration fix, NVDA/AMD row-mix, intra-ticker parallel. None of these have started.
9. **chat-eval rerun gating**: the prompt is correct that the gate cannot be re-run honestly until W2 data pipeline tasks ship. Track explicitly.
10. **Schema drift watch**: BP-585 is a class-of-bug, not a one-off — any other `ScreenFieldMetadata(field_type=...)` literal in any service is at risk. Add a repo-wide arch test that grep-walks for `field_type=` literals and asserts the value is in `{"numeric", "text"}`.
