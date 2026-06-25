# Exhaustive QA — PLAN-0112 flagged-issue fixes (FR-11/12/13 + edge direction + pairwise multi-path)

**Date**: 2026-06-13
**Scope**: Validate the four post-PLAN-0112 fixes against the live stack after the parallel
ticker-dedup session finished. Triggered by user request: "after the implementation we must launch
an exhaustive qa session to validate that everything still works as expected."

## Fixes under test (all committed)
| Commit | Fix |
|--------|-----|
| `50cc8d229` | Pairwise returns several routes across hop-depths (not just shortest) |
| `068f78552` | Edge-direction rendering — true subject→object (`PathEdge.forward`) |
| `41aa65884` | FR-13 — AGE phantom-edge reconcile + delete-aware sync + graph-aware merge |
| `6c8361972` | FR-12 — `exchange` entity_type (migration 0053) + prompt v2.1 + hub re-typing |
| `d76de21d9` | FR-11 — ticker-less name-duplicate merge + name-superset prevention |

## Test suites (from source) — ALL GREEN
- knowledge-graph unit: **1534 passed**, 5 skipped, 2 xfailed
- api-gateway unit: pass (exit 0)
- rag-chat unit: pass (exit 0; only live-classifier integration tests skipped)
- libs/prompts: pass

## Live data operations applied (in order)
1. **FR-13 reconcile** (`reconcile_age_graph.py --apply`): deleted 4,541 phantom edges
   (2,197 distinct relation_ids) + 607 phantom vertices. AGE edges 9,980 → 5,439; max_degree 393 → 292.
2. **Migration 0053** applied to live `intelligence_db` (head 0052 → 0053; `exchange` type added).
3. **FR-12 backfill** (`retype_mishtyped_entities.py --apply`): 32 rows — 22 exchanges
   (NYSE/NASDAQ/… → `exchange`), 10 countries (U.S./… → `place`).
4. **FR-11 auto-tier merge** (`merge_name_duplicates.py --apply --tier auto`): 120 losers / 113
   clusters; SpaceX 7 → 2. 8 review-tier rows emitted to `/tmp/fr11_review.csv` (human-review, NOT merged).

## Regression FOUND and FIXED during QA (the key value of live QA)
After the reconcile + name-merge, live pairwise queries showed previously-connected pairs as
disconnected (NVDA↔Meta, NVDA↔AAPL). Investigation:
- **Root cause**: the FR-13 reconcile correctly deleted edges whose `relation_id` was absent from
  `relations`, but the earlier ticker-merge had re-pointed many relations to new ids **without**
  creating AGE edges, and the AGE sync is **watermark-incremental** — so it would not re-create edges
  for not-recently-updated relations. Net: **1,331 / 4,758 relations (28%) had no AGE edge**;
  NVIDIA had 96 relations but only 18 edges (degree 18).
- **Fix**: forced a **full AGE re-sync** (`reset_age_watermark.sh` → epoch → one `AgeSyncWorker.run()`
  cycle). Idempotent MERGE rebuilt all edges from the authoritative `relations`: AGE edges 3,977 →
  5,234; relations-with-edge **3,427 → 4,684 / 4,758 (98.4%)**; NVIDIA degree 18 → **98**.
  NVDA↔Meta / NVDA↔AAPL reconnected.
- **Residual**: the 74 relations still without edges are (a) 5 relation types in the registry but NOT
  in the AGE label whitelist (`divested_from`, `reported_revenue_of`, `downgraded_by`, `appointed_as`,
  `filed_lawsuit_against`) → logged `age_sync_unknown_relation_type`, never synced — **a separate
  pre-existing gap, recommended follow-up: add these to the AGE whitelist**; (b) normal recent
  forward-sync lag.

## path_insights regeneration
The stored `path_insights` were computed on the phantom-inflated graph (stale, inflated degrees).
Reset one job/anchor → pending (796 anchors) so the worker recomputed on the clean graph in place
(`replace_for_anchor`). Regenerated weirdness distribution: **p10 0.380 / p50 0.458 / p90 0.689**
(spread 0.31, discriminating — vs the old `surprise_score` saturated at 0.95). `failed` jobs
317 → 200 (anchors that timed out on the phantom graph now complete on the clean one).

## Live endpoint validation (post-fixes)
- **Pairwise** `GET /v1/paths/between`: multi-route (NVDA↔Meta returns multiple across depths),
  `PathEdge.forward` present (true direction), self-pair → 400, not-found → 404, disconnected pairs
  correctly `connected:false` (e.g. NVDA↔SpaceX — its only old link was a phantom edge, correctly gone).
- **Global feed** `GET /v1/connections/weird`: genuine cross-domain bridges (Schwab→Webull→FINRA,
  Twilio→Redpoint→Ramp), discriminating weirdness.
- **Frontend** `/connections`: HTTP 200; production build compiles.

## Data-fix verification
- NYSE → `exchange`, U.S. → `place` (FR-12). SpaceX 8 → 2 honest rows (FR-11). 0 phantom edges /
  0 phantom vertices (FR-13). Postgres flood: ~42/2min → ~0 under load.

## Outstanding follow-ups (documented, not blocking)
1. **FR-12 bulk reprofile** — ~6,235 tickerless `financial_instrument` rows still need an LLM
   re-profile; generic-phrase entities ("common shares", "Nvidia shares") still surface in the feed.
2. **FR-11 review-tier** — 8 clusters (0.80–0.92 similarity) in `/tmp/fr11_review.csv` await human
   merge/reject; 2 residual ticker-bearing exact-name dups for the ticker-merge path; then
   migration 0054 (unconditional name unique index).
3. **AGE label whitelist** — add the 5 missing registry relation types so all relations sync.
4. **FR-13 FK** — `relation_evidence → relations` FK infeasible (HASH-partitioned) — prevention via
   delete-aware sync + graph-aware merge instead.

## Verdict
All five fixes validated live; one regression (AGE under-sync) found and fixed during QA; the graph
is now 98.4% consistent with `relations`, weirdness is discriminating, and all endpoints + frontend
work. **PASS** with the documented follow-ups.
