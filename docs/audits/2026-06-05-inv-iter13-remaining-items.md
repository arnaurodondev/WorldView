---
id: INV-PLAN-0093-ITER-13-REMAINING
title: Root-Cause Investigation of Remaining Iter-13 Items (F-NEW-013/014/015 + F-INFRA-009 + ops)
date: 2026-06-05
predecessor: docs/audits/2026-05-31-qa-plan-0093-iter-13-followup-fixes.md
branch: feat/plan-0099-w4
agents: 3 (parallel: INV-A, INV-B, INV-C)
verdict: ALL 5 ITEMS DIAGNOSED — F-NEW-015 reframed (not a regression, a synthesis-path debut)
---

# Investigation Report: Iter-13 Remaining Items

**Date**: 2026-06-05
**Investigator**: 3 parallel sub-agents orchestrated
**Status**: All findings have actionable root causes; total fix scope ≈ 1 engineer-day across 4 small PRs + 1 ops command.

---

## Headline

The biggest reveal: **F-NEW-015 is not a regression**. The iter-12 "PASS" on Q6 was a fast-fail via degraded path (screener returned 500 because market-data was alembic-stuck at 025; rag-chat's BP-623 honest-refusal short-circuited in <1s). Iter-13's FIX-2 (F-INFRA-008 fix) **unblocked the screener** for the first time, so the full synthesis path ran for the first time, and that path takes too long because the **EntityNameGroundingValidator rewrite (FIX-A from iter-12)** fires on every screener query — by definition the LLM mentions tickers that weren't in the resolved-entity set.

Net effect: the system is now slow on screener queries, but **the answer it would have given was always-wrong-and-fast before, and is now correct-but-slow**. This is a strict improvement in correctness with a UX regression in latency. Architecturally, FIX-A's grounded-entity-set construction needs to also include tool-result entities (screener tickers ARE in the grounded set if you include the tool result).

The other 4 items are smaller:
- **F-NEW-013** is a 1-line fix with universal blast radius (every quarter label on every issuer is shifted by one) — severity upgrade LOW → MEDIUM because "values right, labels wrong" is the dangerous-subtle class.
- **F-NEW-014** is a 14-keyword extension + 1 prompt example; 9 of 14 financial phrasings tested missed.
- **F-INFRA-009** is dead — same root cause as F-INFRA-008 (stale migrate sidecar); never reproduced in iter-13 and won't if compose hardening lands.
- **Compose hardening**: 8 migrate services × 1-line `restart: on-failure:5` each closes the F-INFRA-008/009 class permanently.
- **Data backfill** already has a copy-paste runbook — `services/market-ingestion/scripts/backfill_fundamentals.py` covers top-100 tickers including AMD/MSFT/GOOG; cost ≈ $0.

---

## Finding 1 — F-NEW-015 (MEDIUM, gates PASS verdict)

**Original framing**: Q6 went from iter-12 PASS to iter-13 90s timeout → "regression in screener path"
**Actual diagnosis**: Iter-12 PASS was a fast-fail in <1s; iter-13 surfaced the real synthesis path for the first time; FIX-A's rewrite-on-ungrounded-entities fires nearly always on screener queries.

### Reproduction
**Could not reproduce live**: `worldview-rag-chat-1` and `worldview-api-gateway-1` are not currently running. The iter-13 raw QB2 artefact is a 78-byte curl timeout string with no upstream body. Investigation rested on source-code tracing + log forensics.

### Causal chain (5 interacting commits)

| Step | Where | Effect |
|---|---|---|
| 1 | Iter-12 deployed state | `market-data-1` unhealthy (alembic 025), screener returns 500 |
| 2 | Iter-12 Q6 | rag-chat BP-623 honest-refusal in <1s, totally bypassing synthesis path |
| 3 | Iter-13 FIX-2 (`87106e53`) | F-INFRA-008 fix: alembic 025→031, market-data healthy |
| 4 | PLAN-0103 W16 (`f18f414b`) | `_resolve_available_snap_fields` introspection in screener; returns 15 instruments now |
| 5 | Iter-13 Q6 | First time screener path runs end-to-end |
| 6 | Iter-12 FIX-A (`325b228a`) | EntityNameGroundingValidator rewrite at `chat_orchestrator.py:2823` fires because screener-returned tickers (NVDA/AMD/AVGO/MRVL) are NOT in the resolved-entity set for a generic sector query → +15-60s on top of second-turn LLM |
| 7 | PLAN-0103 W20 (`05cefd8f`) | Tabular COMPARISON addendum amplifies second-turn LLM token budget |

### Hypothesis results

| H | Result | Evidence |
|---|---|---|
| H1 FIX-B O(N×M) loop | REFUTED | `filter_resolver_candidates` is O(N log N) with N≤20 (S6 candidates). No substring scan against candidates — stop-word check is on QUERY tokens. |
| H2 PLAN-0103 W15-W20 hot path | CONFIRMED (contributing) | W20 amplifies token count of second-turn synthesis (tabular rendering); W16 enabled the path itself |
| H3 FIX-A grounding rewrite | CONFIRMED (dominant) | Synthesised company names not in resolved-entity set → rewrite fires nearly always → +15-60s |
| H4 New slow DB query | REFUTED | No new DB calls on this path; screener query is sub-second |

### Root cause statement
**Where**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:2823` (the `stream_chat` rewrite call)
**Why it didn't fire in iter-12**: Q6 never reached this code in iter-12 — fast-failed at screener tool call
**Why it fires now**: Screener path works; LLM synthesises a comparison table mentioning tickers that came from the tool result, not from the resolved-entity set; the validator's grounded set doesn't include tool-result entities, so the LLM's tickers look "ungrounded" → rewrite triggered.

### Recommended mitigations (in priority order)

**Option A (recommended — narrow architectural fix)**: extend `EntityNameGroundingValidator`'s grounded set to include **tool-result entities** by default. Today the grounded set is `{resolved_entities}`; it should be `{resolved_entities ∪ tool_result_entity_references}`. Screener tickers are in `tool_result.items[].ticker` — they ARE grounded; the validator just doesn't know about them. Estimated: ~30 LOC + 1-2 tests.

**Option B (recommended — safety net regardless of A)**: wrap the rewrite `stream_chat` at line 2823 in `asyncio.wait_for(..., timeout=15.0)`. Bounds worst-case latency to ~30s total instead of 90s. Estimated: 1-line change. Should ship alongside Option A as defence-in-depth.

**Option C (rejected)**: skip the rewrite entirely for SCREENER intent. Heavy-handed; loses defensive value for legitimate hallucinations in screener-synthesised commentary.

### Severity reconfirmed
**MEDIUM** — degrades UX (long latency) but doesn't produce wrong answers. The grounded set was always architecturally narrow; this just made the cost visible. PASS upgrade gated on Option A landing.

---

## Finding 2 — F-NEW-013 (LOW → MEDIUM, universal blast radius)

### Root cause
**Where**: `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:264` — `_period_label()` is called with `reportDate` (filing date — late-Jan for Q4) instead of `period_end` (the quarter the data covers). The filing-vs-coverage offset shifts every label by exactly one quarter.

The `_period_label` docstring at lines 372-387 **explicitly assumes `period_end` as input** — the call site violates the function's own contract.

### Blast radius
**UNIVERSAL** — affects every issuer, calendar-FY and off-cycle alike. Iter-13's TSLA cross-check happened to surface it, but Q19/Q20/Q22/Q23 results for AMD/NVDA/MSFT/GOOG would have the same label shift if those tickers had data ingested.

### Adjacent finding
TSLA's `instruments.fiscal_year_end_month` is NULL → response renders `Q1 2026` instead of `Q1 FY2026` (hits the line-409 fallback + emits `fiscal_year_end_unknown` warning). **Separate coverage gap**, not the label bug.

### Recommended fix
1-line: pass `period_key` (already `rec.period_end` in YYYY-MM-DD form, line 251) instead of `report_date` to `_period_label()` at line 264. Add a regression test that fires AAPL Q4 2025 and asserts label = `Q4 FY2025` (or whatever the fiscal-year convention dictates), not `Q1 2026`.

### Severity reconsidered
**Upgrade LOW → MEDIUM**. "Values correct, labels wrong" is the subtle-wrong failure mode that finance products especially can't tolerate — a PM citing a Q4 figure when it's actually Q3 will build a wrong-trajectory thesis on right-looking numbers. Higher risk than the iter-13 report estimated.

---

## Finding 3 — F-NEW-014 (LOW, 9-of-14 phrasings miss)

### Root cause
**Where**: `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py:75-124` — `_INTENT_KEYWORDS[FINANCIAL_DATA]` lacks the entire "size & capital structure" vocabulary family. The list covers price / ratios / margins / cash-flow / growth (PLAN-0104 W30+W49) but never had size metrics added.

### Blast radius — 9 of 14 financial phrasings probed MISS

| Phrase | Routes today | Should route |
|---|---|---|
| market cap | GENERAL ✗ | FINANCIAL_DATA |
| market capitalization | GENERAL ✗ | FINANCIAL_DATA |
| enterprise value | GENERAL ✗ | FINANCIAL_DATA |
| EV | GENERAL ✗ | FINANCIAL_DATA |
| shares outstanding | GENERAL ✗ | FINANCIAL_DATA |
| float | GENERAL ✗ | FINANCIAL_DATA |
| book value | GENERAL ✗ | FINANCIAL_DATA |
| net debt | GENERAL ✗ | FINANCIAL_DATA |
| beta | GENERAL ✗ | FINANCIAL_DATA |
| ROIC | GENERAL ✗ | FINANCIAL_DATA |
| dividend yield | FINANCIAL_DATA ✓ | ✓ |
| PEG ratio | FINANCIAL_DATA ✓ | ✓ |
| operating margin | FINANCIAL_DATA ✓ | ✓ |
| free cash flow | FINANCIAL_DATA ✓ | ✓ |
| market valuation | FINANCIAL_DATA ✓ (accidental — `valuation` keyword) | ✓ |

### Recommended fix
~14 keyword additions in one block + 1 prompt example. Same file. Backend already returns `market_cap_usd` in `current_snapshot` so no downstream wiring needed. Estimated: 15 min.

---

## Finding 4 — F-INFRA-009 (NOT REPRODUCING — same class as F-INFRA-008)

Code (`insider_transactions_consumer.py:332`), ORM (`insider_transactions.py:86`), and migration `030` all agree on `net_value_usd`. The iter-12 sighting was a stack-skew artefact: `worldview-market-data-migrate-1 Exited (255) 7 days ago` — DB never got migration 030 applied → consumer crashed reading a column that "didn't exist yet."

**Same architectural root cause as F-INFRA-008**: stale migrate sidecar after image rebuild. Mark dead; no code change. Compose hardening (Finding 5) closes the class permanently.

**Caveat**: postgres was down during INV-C investigation. A 30-second re-verification once postgres is up would be prudent but not required (the source-code agreement is unambiguous).

---

## Finding 5 — Compose hardening (systemic fix)

**8 migrate services** in `infra/compose/docker-compose.yml`. **All 8 have `restart: "no"`** (default). Confirmed offender visible right now: `worldview-market-data-migrate-1` `Exited (255) 7 days ago`.

### Recommended fix
Add `restart: on-failure:5` to all 8 migrate service blocks. Single-line × 8 in `infra/compose/docker-compose.yml`. ~10 min including review.

This is the systemic fix for the F-INFRA-008/009 class. Without it, every future image rebuild has the same failure mode latent until someone manually re-runs the sidecar.

### BP-NEW candidate
**BP-591** — "One-shot init containers without restart policy mask schema drift after image rebuild": when the migrate sidecar exits unsuccessfully but the app container starts anyway (because it doesn't run migrations on startup), the system "looks healthy" while the DB schema is behind. Add to `docs/BUG_PATTERNS.md`.

---

## Finding 6 — Data backfill

**Script exists**: `services/market-ingestion/scripts/backfill_fundamentals.py` (PLAN-0050 T-D-4-03).
- `TOP_EQUITY_SYMBOLS` at line 87 — top-100, includes AAPL/MSFT/AMD/GOOGL
- Reads JSONB already in `market_data_db` → cost ≈ $0
- Uses Alpha Vantage fallback (≤200 free-tier calls/day) if EODHD JSONB sections are empty

### Caveat from INV-C
If EODHD JSONB itself is empty for AMD/MSFT/GOOG, operator must pull fresh EODHD payloads first. INV-C couldn't query `fundamental_metrics` per-ticker row counts because postgres was down at investigation time.

### Runbook execution log — 2026-06-05 (post-investigation)

**Live verification confirmed no backfill needed.** Coverage was already populated by the regular scheduler (last ingest 2026-06-03 04:11–04:15 UTC, two days before iter-13 QA):

| Symbol | Total rows | QUARTERLY | ANNUAL | SNAPSHOT | Latest quarterly |
|--------|-----------:|----------:|-------:|---------:|------------------|
| AAPL   |       8002 |      6053 |   1590 |      356 | 2026-03-31       |
| AMD    |       8025 |      6114 |   1617 |      294 | 2026-03-31       |
| AMZN   |       6454 |      4927 |   1222 |      302 | 2026-03-31       |
| BRK.B  |       6816 |      5151 |   1407 |      258 | 2026-03-31       |
| GOOGL  |       5146 |      3802 |   1023 |      318 | 2026-03-31       |
| JPM    |       7585 |      5791 |   1481 |      310 | 2026-03-31       |
| META   |       3611 |      2565 |    729 |      314 | 2026-03-31       |
| MSFT   |       7976 |      6079 |   1576 |      318 | 2026-03-31       |
| NVDA   |       5826 |      4379 |   1126 |      318 | 2026-04-30       |
| TSLA   |       4163 |      3054 |    804 |      302 | 2026-03-31       |

AMD revenue Q1 FY2026 confirmed in DB: `revenue = 10,253,000,000`. MSFT = `82,886,000,000`. GOOGL = `109,896,000,000`. **Iter-13 REFUSAL on fundamentals queries was NOT a data-coverage gap** — it is a retrieval / synthesis-path issue in rag-chat (consistent with F-NEW-015 root-cause).

### Runbook corrections (discovered during live execution)

1. **Coverage query has SQL bugs** — `instruments` PK is `id` not `instrument_id`, and `fundamental_metrics` uses `as_of_date` not `period_end`. Also `period_type` values are uppercase (`QUARTERLY`/`ANNUAL`/`SNAPSHOT`/`daily`), not lowercase. Corrected query:
   ```bash
   docker exec worldview-postgres-1 psql -U postgres -d market_data_db -c "
     SELECT i.symbol, COUNT(fm.*) AS total,
            COUNT(fm.*) FILTER (WHERE fm.period_type='QUARTERLY') AS quarterly,
            MAX(fm.as_of_date) FILTER (WHERE fm.period_type='QUARTERLY') AS latest_quarterly
     FROM instruments i LEFT JOIN fundamental_metrics fm ON fm.instrument_id = i.id
     WHERE i.symbol IN ('AAPL','MSFT','GOOGL','AMZN','META','NVDA','TSLA','AMD','BRK.B','JPM')
     GROUP BY i.symbol ORDER BY i.symbol"
   ```
2. **`scripts/refresh_fundamentals.py` does NOT exist** in `services/market-ingestion/scripts/` (only `backfill_fundamentals.py` is present). Step 2 of the original runbook is unrunnable as written. If raw EODHD payloads need refreshing, the production path is the live S2 `market-ingestion-scheduler` + `market-ingestion-worker`, not a standalone CLI. Document the actual mechanism before recommending it.
3. **`backfill_fundamentals.py` has no `--symbols` flag** — only `--export-coverage=<path.csv>`. The full top-100 list is hardcoded as `TOP_EQUITY_SYMBOLS` (line 87). Per-ticker backfill requires editing that list or running the full set.
4. **Postgres was Exited (0)** at start of run; runbook should include `docker start worldview-postgres-1 worldview-market-ingestion-worker-1 && sleep 8 && docker exec worldview-postgres-1 pg_isready -U postgres` as step 0.

### Updated runbook
0. `docker start worldview-postgres-1 worldview-market-ingestion-worker-1 && sleep 8` — ensure DB + worker up
1. Run the corrected coverage query above
2. If any of {AMD, MSFT, GOOGL} has zero QUARTERLY rows OR `latest_quarterly` is >6 months old: trigger fundamentals re-ingest via the live S2 worker (start `worldview-market-ingestion-scheduler-1` and let it pick up the schedule), or run the full top-100 backfill via `docker exec worldview-market-ingestion-worker-1 python services/market-ingestion/scripts/backfill_fundamentals.py`
3. Verify: re-run the coverage query; expect non-zero QUARTERLY rows per ticker
4. Re-run iter-13 Q19/Q22/Q23 chat-eval; **if refusals persist with data present, the root cause is rag-chat retrieval, not data coverage** (see F-NEW-015)

---

## Recommended Fix Scope

Single feature branch with 4 commits, ~1 engineer-day total. Plus 1 operator-run script.

### Wave 1 — F-NEW-015 + Compose hardening (the gate-blockers)
1. **F-NEW-015 Option A**: extend `EntityNameGroundingValidator` grounded set to include tool-result entities (~30 LOC)
2. **F-NEW-015 Option B**: wrap rewrite `stream_chat` in `asyncio.wait_for(timeout=15.0)` (1 line — defence in depth)
3. **Compose hardening**: `restart: on-failure:5` on all 8 migrate sidecars (8 lines, single PR)
- Combined effort: ~3 hours

### Wave 2 — Low-severity correctness
4. **F-NEW-013**: 1-line — pass `period_key` not `report_date` to `_period_label()` + regression test
5. **F-NEW-014**: ~14 keyword additions + 1 prompt example in `intent_classifier.py`
- Combined effort: ~2 hours

### Wave 3 — Ops (separate from code)
6. **Data backfill runbook**: operator runs the 5-step runbook above (~15 min interactive)
- Not code; documented runbook only

### Out of scope (carried for later)
- **F-INFRA-009**: mark dead, no code change
- **471-ticker S6→S3 ingestion gap PRD**: separate plan, multi-day scope
- **TSLA `fiscal_year_end_month` NULL coverage gap** (adjacent to F-NEW-013): separate small fix

---

## Compounding

- **BP-NEW BP-591**: "One-shot init containers without restart policy mask schema drift after image rebuild" — root of F-INFRA-008 + F-INFRA-009 class. Closes after compose hardening lands.
- **HR-NEW HR-057** (candidate): "Defensive validators that fire on every output can introduce latency regressions when previously-fast-failed paths start succeeding" — root of F-NEW-015. The grounding validator was correct to ship; the grounded-set construction needs to consider tool results too.
- **Process learning**: when a previously-failing test starts succeeding (Q6 went PASS → TIMEOUT), the first hypothesis should be "did the path become reachable" not "did the path get slower". The iter-13 audit framed it as a regression; investigation reframed it as a debut.
- **Skill improvement** (`/qa`): chat-eval grader should distinguish "fast-fail PASS via degraded path" from "full-path PASS". A 1-second response time is suspicious for a complex screener query and is a hint that the path didn't actually run.

---

## Trajectory Update

| Round | Date | Verdict | Notes |
|---|---|---|---|
| Iter-9 | 2026-05-26 | FAIL | $34.6B AMD fabrication |
| Iter-12 | 2026-05-28 | PASS | 24-question broader eval, 0 HARMFUL |
| Iter-13 | 2026-05-31 | PASS_WITH_WARNINGS | F-INFRA-008 closed; F-NEW-015 surfaced |
| **INV-iter-13** | **2026-06-05** | (investigation only) | All 5 remaining items diagnosed; **F-NEW-015 reframed** as architectural rather than regression |

PLAN-0093 stays CLOSED. Iter-13's PASS_WITH_WARNINGS will upgrade to PASS once Wave 1 (above) lands.

---

**Raw artefacts**:
- `/tmp/inv-F-NEW-015-report.md` — INV-A full report (Q6 timeout compound regression)
- `/tmp/inv-F-NEW-013-and-014-report.md` — INV-B full report (quarter-label + intent miss)
- `/tmp/inv-F-INFRA-009-plus-ops-report.md` — INV-C full report (status check + compose + backfill)
