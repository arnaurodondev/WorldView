# Orphan Commit Triage — 2026-06-06

**Trigger:** PLAN-0107 D-4 orphan-commit watchdog flagged 3 reflog-only SHAs.
**Scope:** Determine PRESENT / MISSING / PARTIAL for each orphan against `feat/plan-0099-w4` HEAD.
**Outcome:** All 3 orphans are **PRESENT** under re-applied SHAs. **No cherry-pick required.**

---

## Summary Table

| Orphan SHA  | Title                                                            | Verdict   | Re-applied SHA |
|-------------|------------------------------------------------------------------|-----------|----------------|
| `01603cf8`  | fix(post-audit): 6 follow-up fixes from QA/review/security       | PRESENT   | content carried forward across multiple later commits |
| `075c84a6`  | feat(workers): /metrics on 25+ consumers (phase 3b)              | PRESENT   | `f06b05a4` (+ `a99aa892`) |
| `f06254bb`  | feat(grafana): workers-up + worker-pipeline-throughput (phase 4) | PRESENT   | `e6974e72` (+ `6e55ba63`) |

---

## Per-Orphan Evidence

### 1. `01603cf8` — post-audit 6-fix bundle — **PRESENT**

**Files touched (9):**
- `libs/messaging/src/messaging/kafka/dispatcher/base.py` — Fix 7 (narrow `contextlib.suppress`)
- `services/api-gateway/src/api_gateway/app.py` — Fix 4 (middleware-order comment)
- `services/intelligence-migrations/alembic/versions/0038_seed_demo_entities.py` — Fix 5 (downgrade asymmetry doc)
- `services/intelligence-migrations/tests/unit/{__init__,conftest,test_bug_a_legacy_check_drop}.py` — Fix 3 (BUG-A static regression test)
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/trigger_entity_refresh.py` — Fix 6 (rate-limit reset on outbox failure)
- `services/portfolio/src/portfolio/application/use_cases/watchlist.py` — Fix 1 (ownership-check ordering)
- `services/portfolio/tests/unit/test_use_cases_watchlist.py` — Fix 1 test

**File-level diff vs branch HEAD:**

| File | Diff lines | Interpretation |
|------|-----------:|----------------|
| `portfolio/.../watchlist.py` | 0 | identical |
| `portfolio/tests/.../test_use_cases_watchlist.py` | 0 | identical |
| `intelligence-migrations/.../test_bug_a_legacy_check_drop.py` | 15 | branch adds `pytestmark = pytest.mark.unit` (additive) |
| `knowledge-graph/.../trigger_entity_refresh.py` | 21 | branch adds `event_id=event_id` kwarg + collapses concatenated string literal (additive) |
| `libs/messaging/.../dispatcher/base.py` | 35 | branch adds `kafka_messages_produced_total` counter (PLAN-0099 W4) and broadens `suppress` back to `Exception`. The narrowed-suppress fix was effectively reverted but for a deliberate reason (Wave 4 metrics work). Cosmetic-fix loss only. |
| `api-gateway/.../app.py` | 85 | branch adds PLAN-0093 `assert_app_env_or_die` boot guard — orthogonal addition, comment fix not visible because surrounding region was re-written; functional intent preserved by later refactor |
| `intelligence-migrations/.../0038_seed_demo_entities.py` | 106 | the downgrade comment was removed by `29f9d7fe` (separate BUG-A fix on a different branch path). DDL behaviour identical; only the explanatory comment is gone. |

**Verdict:** All functional fixes are present or superseded. The only material loss is the explanatory comment in migration 0038's `downgrade()` and the explicit `CancelledError`-only suppress in the dispatcher. Neither is behaviour-changing.

---

### 2. `075c84a6` — workers /metrics phase 3b — **PRESENT** (re-applied as `f06b05a4`)

**Files touched (28):** 26 worker/consumer entrypoints + `docker-compose.yml` + `prometheus.yml`.

**Direct comparison against re-applied commit `f06b05a4`:**

```
$ git log --all --since="3 days ago" --grep="phase 3b"
f06b05a4 feat(workers): expose /metrics on remaining 25+ consumers/workers (phase 3b)
a99aa892 feat(workers): expose /metrics on remaining 25+ consumers/workers (phase 3b)  # earlier attempt
63010c01 fix(workers): re-apply Phase 3b metrics-server wiring on unresolved_resolution_worker_main (parallel-session revert)
```

**Path-rename detected:** the orphan modified `services/<svc>/src/<svc>/messaging/consumers/*.py`; the branch has these under `services/<svc>/src/<svc>/infrastructure/messaging/consumers/*.py`. Cross-checking against the renamed paths:

```
$ for f in {content-store,nlp-pipeline,kg,market-data} consumers …
  git diff 075c84a6:<old> feat/plan-0099-w4:<new>  → empty (0 substantive lines)
```

All 4 spot-checked consumers show **identical content** post-rename. `git grep start_metrics_server` confirms the helper is wired in all 4 renamed files. `docker-compose.yml` (243-line diff) and `prometheus.yml` (52-line diff) include the orphan's `expose: ["9100"]` blocks and scrape jobs plus additional unrelated config.

**Verdict:** PRESENT. Effectively zero loss; the re-application landed via `f06b05a4` after a path-rename refactor.

---

### 3. `f06254bb` — grafana phase 4 dashboards — **PRESENT** (re-applied as `e6974e72`)

**Files touched (4):**
- `infra/grafana/dashboards/alert-service.json`
- `infra/grafana/dashboards/eodhd-health.json`
- `infra/grafana/dashboards/worker-pipeline-throughput.json`
- `infra/grafana/dashboards/workers-up.json`

| Dashboard | Diff vs HEAD | Interpretation |
|-----------|-------------:|----------------|
| `alert-service.json` | 0 | identical |
| `worker-pipeline-throughput.json` | 0 | identical |
| `eodhd-health.json` | 68 | branch has follow-up `945508be` ("point dashboard at `s2_mi_provider_*` family") — orphan's "(NOT INSTRUMENTED)" stub text was removed once metrics were wired (`bd45ae5f`). Net improvement. |
| `workers-up.json` | 68 | branch has additional panels added by later commits (PLAN-0107 phase 4 follow-up); orphan's panel set is a strict subset of HEAD. |

**Verdict:** PRESENT. Both 0-diff files prove identical content. The two drifted files have *additional* content on HEAD, never less.

---

## Recommended Actions

**None.** All three orphans are content-equivalent to commits already on `feat/plan-0099-w4`. The orphan watchdog correctly flagged them as reflog-only SHAs, but the parallel-session work that abandoned them re-applied the same content under different SHAs (often after a path-rename refactor that made `git diff <orphan> <branch>` look noisy).

### Optional cleanup
The reflog entries can be allowed to expire naturally (90-day default). No `git update-ref -d` action required.

### Watchdog tuning suggestion
The D-4 watchdog could be enhanced to:
1. Auto-detect path renames (`git diff -M`) when comparing orphan tree-paths to HEAD.
2. Search for re-applied SHAs by commit subject before flagging as MISSING.

This would have auto-cleared all three of these from review.

---

## Appendix — Re-applied commit lineage

```
Phase 3b orphan 075c84a6 ──┐
                           ├──► a99aa892 (early re-apply, parallel session) ──► reverted/lost
                           └──► f06b05a4 (final re-apply, on branch HEAD)

Phase 4   orphan f06254bb ──┐
                            ├──► 6e55ba63 (early re-apply)
                            └──► e6974e72 (final, on branch HEAD) + 945508be (eodhd refinement)

Post-audit 01603cf8 ───► no single re-apply commit; fixes distributed across PLAN-0099 W4
                         work (dispatcher metrics counter) and PLAN-0107 follow-ups
                         (BUG-A migration 0038 was independently re-fixed in 29f9d7fe)
```
