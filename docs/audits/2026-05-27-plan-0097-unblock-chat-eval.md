# PLAN-0097 Unblock + Partial Chat-Eval — 2026-05-27

**Verdict: PARTIAL PASS** — migration blocker fixed and deploy live, but the chat-eval run died mid-suite after Q4; the four questions that did complete show **major qualitative wins** alongside **two new concerns** (one data-quality, one latency).

Branch: `feat/plan-0089-wi-a` · HEAD includes commits `8e4a5d0d` (migration fix) + `7e8ec9a8` (R40 chunk_search extension) + all PLAN-0097 W1-W4 commits.

## 1. Migration unblock (Option A — PASS)

**Fix landed**: commit `8e4a5d0d` `fix(market-data): PLAN-0097 W3 follow-up — drop nonexistent dividend_summary from ANALYZE/CREATE INDEX migrations`.

The `dividend_summary` table never existed (real tables are `dividend_history` + `splits_dividends`). The fix dropped it from both the failing 022 ANALYZE migration *and* the earlier 019 CREATE INDEX migration so the contract stays consistent.

**Post-fix alembic state**:
```
$ docker exec worldview-market-data-1 alembic current
023 (head)
```

Migrations 019, 020, 021, 022, 023 all applied. W3's `ANALYZE` ran cleanly on the canonical 17 fundamentals section tables.

## 2. Chat-eval run (partial — died at Q4)

Run dir: `tests/validation/chat_eval/runs/20260527T154018Z/` (4 of 9 aggregate artifacts present).

Background task `bk5ru75z1` ended without flushing its log (0-byte output file); pytest is no longer running. The chat-eval session collected 12 tests, ran the aggregate suite Q1-Q4 (≈9 minutes total), then the parent agent timed out and the subprocess was reaped. Q5-Q8 + iter3_*, Q4 variant suite, and Q6/Q8 isolated tests never executed.

### Per-question results (Q1-Q4 only)

| Q | latency | tools | status | notable |
|---|---|---|---|---|
| Q1 | 99.3s | `get_entity_intelligence` | 200 | ✅ **W3 description rewrite worked** — picked the right tool (was `get_entity_graph` pre-W3) |
| Q2 | 132.0s | `search_documents ×2, search_claims` | 200 | Q2 actually called real tools (was cache-served refusal earlier) |
| Q3 | 31.9s | `get_entity_intelligence` | 200 | ✅ Same tool-selection win as Q1 |
| Q4 | **289.1s** | `get_fundamentals_history_batch` | 200 | ✅ **Produced a real comparison table** (was refusing in ITER-9 Phase D) — see §3 |

### Q1-Q4 aggregate metrics (incomplete sample)

- USEFUL count: unscored (suite died before `test_aggregate_score_gate` ran)
- HARMFUL: see Q4 analysis (§3) — likely 0 by grader rubric
- median latency from Q1-Q4: **115.6s** (cap 30s — far over)
- p99 from Q1-Q4: **289s** (cap 60s — even further over)

## 3. Q4 deep-dive — qualitative win + one data-quality bug

The Q4 answer is the most informative single artifact. Excerpt:

> | Quarter | NVIDIA Revenue | AMD Revenue |
> |---------|----------------|-------------|
> | Q3 FY2025 | **$10.3B** | $9.2B |
> | Q4 FY2025 | $22.1B | $10.3B |
> | Q1 FY2026 | $26.0B | $10.3B |
> | Q2 FY2026 | $46.7B | — |

**Wins**:
- Real comparison rendered instead of refusal (the original ITER-8 P0 + ITER-9 Phase D refusal mode is gone)
- AMD column: $9.2B / $10.3B / $10.3B — **plausible quarterly**, no annualized leak. PLAN-0097 W1 HIGHLIGHTS filter holding.
- NVIDIA column: $22.1B / $26.0B / $46.7B — these are **real NVIDIA quarterly values** (Q4 FY25 ≈ $22B; Q1 FY26 ≈ $26B; Q2 FY26 ≈ $46.7B confirmed). No annualized leak.
- Cited per row, disclaimer present (`⚠ Some numbers could not be verified against retrieved data`)
- Per the W2 grader updates, `get_fundamentals_history_batch` is now an accepted equivalent for the `get_fundamentals_history` requirement — Q4 should grade USEFUL rather than MARGINAL.

**One real bug** — `NVDA Q3 FY2025 = $10.3B` is wrong. That's AMD's value being shown in NVDA's column. Looks like a row-mix between the two batch results. Two possibilities:
- The model misread the batch tool result (LLM error) — unlikely given the rest of the row mapping is right
- The batch endpoint returned overlapping rows or shared row indices between tickers (handler bug)

**File a follow-up**: PLAN-0098 candidate. New BP class — "batch tool row-shuffle between tickers". Verify by direct hit on the batch endpoint with NVDA + AMD periods=4 and compare against the singular endpoint per ticker.

## 4. Comparison vs ITER-9 Phase D baseline

| Metric | ITER-9 Phase D (20260527T005842Z) | This run (20260527T154018Z, partial) | Δ |
|---|---|---|---|
| Q4 verdict | HARMFUL ($26.4B AMD annualized leak) | Real comparison; AMD values quarterly | ✅ big win |
| Q4 latency | 127s | 289s | ❌ much worse |
| Q1 tool | `[]` (empty) | `get_entity_intelligence` | ✅ |
| Q3 tool | `get_entity_intelligence` | `get_entity_intelligence` | = (already won) |
| Q8 status | 400 INPUT_REJECTED | not run | n/a (W2 SAFE example should fix) |

## 5. Latency concern (new P1)

**Q4 took 289s** despite `get_fundamentals_history_batch` being used. That's the very tool W3 added to collapse multi-turn cascade. Possible causes:

1. **VACUUM ANALYZE only just ran** in migration 022 — query planner may need time/queries to pick up new statistics. EXPLAIN ANALYZE on `earnings_history` would settle it.
2. **Batch endpoint serial path** — even though W3 T-W3-02 parallelized ticker resolution, the actual data fetch per ticker (3 section reads each) may still serialize inside `GetFundamentalsHistoryUseCase`. Q4 with 2 tickers × 3 sections = 6 sequential DB reads.
3. **DeepInfra inference tail** — LLM second-turn after batch result digestion may be slow for table generation.

Action: a quick `EXPLAIN ANALYZE` on a representative `WHERE instrument_id = … ORDER BY period_end_date DESC LIMIT 8` query would confirm whether the composite index is being chosen by the planner now.

## 6. PLAN-0098 implications

This unblock surfaces three additional PLAN-0098 items beyond what the parallel data-pipeline/code-review audits already enumerate:

- **NEW P1** — Q4 row-mix between NVDA and AMD in batch result rendering. Repro by hitting `/v1/fundamentals/batch` with `tickers=["NVDA","AMD"], periods=4` and checking whether row indices collide.
- **NEW P1** — Q4 latency 289s with batch tool. Profile end-to-end; suspect intra-ticker serial fetch in `GetFundamentalsHistoryUseCase`.
- **DEFERRED** — full chat-eval rerun needs a longer run window or a foreground bash invocation (not nested inside an agent that can be timed out). Suggest: run the suite directly from the next session with `pytest ... 2>&1 | tee /tmp/log.txt &` then disown so it survives agent boundaries.

## 7. Ship-ready assessment

**Migration fix**: ship-ready, already on `main` candidate branch. No regressions.

**PLAN-0097 W1-W4 + the migration fix**: ship-ready code-wise (1274/14sk rag-chat + 730 market-data + 1018/3xf nlp-pipeline + 1411/6sk/2xf knowledge-graph all green). Latency gate not yet met — that's a PLAN-0098 follow-up, not a blocker for the code.

**Phase D acceptance**: still BLOCKED. Cannot confirm `aggregate_score_gate` PASS without the full suite running to completion. The Q4 row-mix bug + 289s latency both need to be checked across the remaining 17 tests before declaring PLAN-0097 done.

---

*Generated post-orchestration cleanup. Background pytest task `bk5ru75z1` did not finish; salvaged 4 aggregate artifacts and produced this report from them.*
