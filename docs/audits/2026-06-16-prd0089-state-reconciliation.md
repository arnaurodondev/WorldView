---
title: PRD-0089 Deferred-Work State Reconciliation (FOUNDATION audit)
date: 2026-06-16
source_doc: docs/plans/0089-pages/DEFERRED-WORK-PLAN.md
source_doc_dated: 2026-05-28
doc_branch: feat/plan-0099-w4 @ 77d3d720 (STALE)
audited_branch: feat/md-reliability-followups @ 2e447e8be (current worktree)
status: read-only investigation — no code/schema/data changed
purpose: >
  Establish what DEFERRED-WORK-PLAN.md §0 CLAIMS shipped vs what is ACTUALLY in
  the current code, as the shared foundation for 5 sibling deep-dive
  investigations. This is a MAP, not a deep dive.
---

# PRD-0089 Deferred-Work State Reconciliation

## TL;DR

The DEFERRED-WORK-PLAN.md is **substantially stale**. Since 2026-05-28 the branch
has advanced **436 commits** (the doc references HEAD `77d3d720` on the long-gone
`feat/plan-0099-w4`; current HEAD is `2e447e8be` on `feat/md-reliability-followups`).

The single biggest change: **§1 L-5b (the 3-engineer-day flagship deferred item)
is now FULLY SHIPPED in the backend** — model columns, migration 035, 4 typed
HTTP clients, `sync_intelligence_rollup` use case, the `_intelligence_rollup_loop`
04:00 UTC lifespan task, and the screener filter schema are all present. The
frontend **IB-L5 is also mostly shipped** (5 of 7 intelligence rows live).

Everything the doc's §0 listed as "already shipped" is **confirmed present** — no
regressions/reverts found. Several deferred items are now done beyond what the doc
knew. Only §3 (insider universe scheduling), §4/§5 ops follow-ups, and §6 (audit
note) remain genuinely open — and §6's recommended action is now **moot** (the
contamination commit no longer exists in history).

---

## Part A — §0 "already shipped" claims, verified against current code

| §0 claim | Claimed | Actual now | Verdict | Evidence |
|---|---|---|---|---|
| Static screener fields | 38–39 | **44** registered | CONFIRMED + GROWN | `app.py:42` `_get_static_screen_fields()` → 44 `ScreenFieldMetadata(...)`; includes all 6 L-5b intelligence fields |
| Migration chain head | `031` | **`039`** (linear: 035 down_rev=034 … chained) | CONFIRMED + ADVANCED | `alembic/versions/` 001…039; head `039_unique_isin_exchange_instruments.py` |
| `POST /v1/fundamentals/screen` | shipped | present | CONFIRMED | `api/routers/fundamental_metrics.py:164` |
| `GET /v1/fundamentals/screen/fields` | shipped | present | CONFIRMED | `api/routers/fundamental_metrics.py:386` |
| S6 `/internal/v1/instruments/{id}/news-rollup-7d` | shipped | present | CONFIRMED | `services/nlp-pipeline/.../api/routes/internal_news_rollup.py` |
| S7 `/internal/v1/instruments/{id}/intelligence-rollup-7d` | shipped | present | CONFIRMED | `services/knowledge-graph/.../api/internal_intelligence_rollup.py` |
| S8 `/internal/v1/instruments/{id}/ai-brief-flag` | shipped | present | CONFIRMED | `services/rag-chat/.../api/routes/internal_ai_brief_flag.py` |
| S10 `/internal/v1/instruments/{id}/active-alert-flag` | shipped | present | CONFIRMED | `services/alert/.../api/routes.py` (active-alert-flag) |
| Computed-metrics worker (02:00) | shipped | present | CONFIRMED | `app.py:714` `_computed_metrics_refresh_loop`; `ComputedMetricsBackfillWorker` ref `app.py:688/718` |
| Insider-rollup worker (03:00) | shipped | present | CONFIRMED | `app.py:912/915` `insider_rollup_loop`; `application/use_cases/rollup_insider_90d.py` |
| `InsiderTransactionsConsumer` | shipped | present | CONFIRMED | `infrastructure/messaging/consumers/insider_transactions_consumer.py:132` |
| `instrument_fundamentals_snapshot` L-2/L-3/L-4/L-5 columns | shipped | all present | CONFIRMED + GROWN | model has L-2 (7), L-4a (4: analyst_target/consensus/inst_own/short), insider_net_buy_90d, L-5c (next_earnings/dividend_date), AND **all 6 L-5b columns + intelligence_rollup_synced_at** (`fundamentals_snapshot.py:165-171`) |

**No regressions or reverts found.** Every §0-claimed artifact is present in the
current tree.

---

## Part B — §1–§7 deferred items: current-status map

| # | Deferred item | Doc verdict (2026-05-28) | Current status | Verdict | Evidence |
|---|---|---|---|---|---|
| §1 | **L-5b** S3 intelligence sync worker (~3d) | not shipped; ready to schedule | **Backend fully built**: migration 035 (6 cols + `intelligence_rollup_synced_at`), `infrastructure/clients/intelligence_clients.py`, `application/use_cases/sync_intelligence_rollup.py`, `_intelligence_rollup_loop` @04:00 UTC (`app.py:586/922`, env `MARKET_DATA_INTELLIGENCE_ROLLUP_HOUR_UTC`), filter schema fields (`api/schemas/fundamental_metrics.py:115-124`), 6 static fields registered | **FULLY-DONE-SINCE** | the doc's entire §1.6 task list (T-WL5B-01..06) appears implemented |
| §2 | **IB-L3 / IB-L4 / IB-L5** frontend (~3d) | IB-L3/L4 unblocked, IB-L5 gated on §1 | IB-L3 returns cols + IB-L4 analyst/insider cols present in `ag-screener-columns.tsx`; build-filters maps L-5b intel fields (`build-filters.ts:163-172`); IntelligenceFilterGroup `IB_L5_DEFAULTS` = **5 of 7 rows live** (`newsCount7d/aiBrief/activeAlert/contradictions/llmRelevance = true`; `upcomingEarnings/upcomingDividend = false`) | **PARTIALLY-DONE-SINCE** (IB-L3 ~done, IB-L4 ~done, IB-L5 mostly done — only the 2 calendar-window rows still carry `BackendPendingBadge`) | `IntelligenceFilterGroup.tsx:70-78`, `:176/205/235/261/286/301` |
| §3 | **L-4b insider universe activation** (~0.5d + budget) | loader exists, not scheduled | `insider_universe_loader.py` exists; **still NOT scheduled** — no `_insider_universe_refresh_loop` / `INSIDER_UNIVERSE_REFRESH_*` in market-ingestion `app.py`/`config.py` | **STILL-PENDING** (decision/budget-gated, as doc said) | grep on market-ingestion app.py/config.py = 0 hits |
| §4 | **Migration 031 deploy-window runbook note** (~10min) | trivial runbook update | no constraint-window note found in `docs/services/market-data.md` | **STILL-PENDING** (low value; see note below) | grep `ck_screen_field_metadata_field_type` in market-data.md = 0 hits |
| §5 | **L-3 smoke test + runbook fill + Prometheus alert** (~0.5d+) | post-staging follow-ups | `docs/runbooks/computed-metrics-worker.md` exists with **no remaining TBD/placeholder markers** (numbers may be filled or were never placeheld); **but no Prometheus `computed_metrics_worker_runs_total` / `last_success_timestamp` metric exists** | **PARTIALLY-DONE-SINCE** (runbook present; alert metric still missing — needs sibling deep-dive) | runbook grep clean; metric grep = 0 hits in market-data/src |
| §6 | **Contamination commit `c60c7810`** (recommend Option C audit note) | leave / file 5-min note | commit `c60c7810` is **NOT in current history**; `8906009f` also **NOT in history**; the rag-chat test it referenced **IS present** (`services/rag-chat/tests/unit/test_app_deploy_token_cache_flush.py`, 4760 bytes, mtime 2026-06-16); no audit note written | **SUPERSEDED / MOOT** | see §6 verdict below |

---

## Part C — §6 contamination verdict (per task #4)

- `git log --oneline | grep c60c7810` → **no match.** The contamination commit
  does not exist on the current branch.
- `8906009f` (the commit the test "should have" belonged to) → **also not in
  history.** Both SHAs lived on the abandoned `feat/plan-0099-w4` line.
- The 436 commits since 2026-05-28 plus the branch rename (`feat/plan-0099-w4`
  → … → `feat/md-reliability-followups`) mean the history the doc worried about
  was rewritten/re-derived. The "misleading attribution" the §6 audit note was
  meant to explain **no longer exists** — `git log -p` on the rag-chat test will
  not surface `c60c7810`.
- The test file itself **survived** and is present and current.

**Verdict: §6 Option C (the audit note) is MOOT.** There is no longer a confusing
attribution to document. Writing the note now would document a commit that does
not exist in the branch a future archaeologist would inspect. Recommend: drop §6
entirely. (If anything, note in the deferred plan that the history was rebuilt.)

---

## Part D — "What changed since 2026-05-28"

1. **Branch identity changed twice.** Doc: `feat/plan-0099-w4 @ 77d3d720`.
   Now: `feat/md-reliability-followups @ 2e447e8be`. **+436 commits.**
2. **L-5b shipped end-to-end (backend).** This was the doc's largest deferred
   item (§1, ~3 engineer-days, "unblocks IB-L5"). It is done: migration 035,
   model columns, clients, use case, 04:00 lifespan loop, screener filter schema,
   static field registration. Migration chain advanced 031 → 039.
3. **IB-L5 frontend mostly shipped.** `IB_L5_DEFAULTS` flips 5 of 7 intelligence
   rows live; `build-filters.ts` plumbs the L-5b filter params. Only the two
   calendar-window rows (`next_earnings_within_days`, `next_dividend_within_days`)
   remain behind `BackendPendingBadge`. This is the inverse of the doc's claim
   that IB-L5 is fully gated on §1.
4. **IB-L3 + IB-L4 columns landed** in `ag-screener-columns.tsx` (returns,
   52W-distance, analyst target/consensus, insider 90d, inst-own, short %),
   including the client-side ANALYST UPSIDE derivation the doc specified.
5. **Static screener field count grew 38/39 → 44.**
6. **§6 contamination became moot** (history rewritten; commit gone, test kept).

### Genuinely still open (for the sibling deep-dives to own)
- §3 insider-universe loader is **still unscheduled** (budget-gated by design).
- §5 Prometheus alert metric for the computed-metrics worker is **absent**.
- §4 migration-031 runbook note is **absent** (cosmetic; constraint window is the
  same near-zero risk the doc described).
- §2 IB-L5 last-mile: the 2 calendar-window rows still show pending badges; worth
  a sibling confirming whether `next_earnings_within_days` /
  `next_dividend_within_days` filters are backend-supported (L-5c columns exist,
  so this may be a pure frontend flip).

### Items to flag as "done beyond doc's knowledge"
- L-5b backend (§1) — doc estimated 3 engineer-days remaining; now 0.
- IB-L3/IB-L4 frontend (§2) — doc listed as ~2 engineer-days remaining; appears
  largely landed.
- IB-L5 frontend — doc said "GATED"; now 5/7 live.

---

## Caveats for sibling agents

- This audit is a **presence/wiring map**, not a correctness review. "Present"
  means the artifact exists and is referenced/wired — it does not assert the
  worker writes correct data, the clients handle BP-235 timeouts, the lockstep
  test passes, or the 04:00 loop has run successfully in any environment. Those
  are the deep-dive questions.
- All paths are relative to the worktree root
  `/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability`.
- File line numbers are as of HEAD `2e447e8be`.
