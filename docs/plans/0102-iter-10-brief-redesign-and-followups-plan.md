---
plan_id: PLAN-0102
title: Brief Redesign + ITER-10 Followups
status: draft
created: 2026-05-28
last_updated: 2026-05-28
owner: TBD
waves: 7
total_effort_h: ~22
related_audits:
  - docs/audits/2026-05-28-plan-0102-brief-redesign.md
  - docs/audits/2026-05-28-plan-0101-phase-d-code-review.md
  - docs/audits/2026-05-28-plan-0101-phase-d-slo-check.md
  - docs/audits/2026-05-28-plan-0101-phase-d-doc-audit.md
  - docs/audits/2026-05-28-plan-0100-phase-d-chat-eval.md
acceptance_gates:
  - chat-eval USEFUL ≥ 6 (currently 5)
  - chat-eval HARMFUL = 0 (currently 0 ✓)
  - chat-eval ttft_p95 < 5s (currently 2.20s ✓)
  - chat-eval tps_streaming_p50 ≥ 15 tok/s (currently NaN — W4)
  - chat-eval e2e_p99 < 90s (currently 128.6s — partial, Q6 outlier)
  - live brief A/B: synthetic-user brief includes Your Portfolio Today section with non-empty P&L (W1+W2)
---

# PLAN-0102 — Brief Redesign + ITER-10 Followups

## §0 Inline PRD

### Why now

A potential user reviewed the morning brief and gave concrete feedback: *"It doesn't give general market info, no relation or impact to my portfolio. The daily brief should be the summary an investor would have to read if they only had 5 minutes that day."*

The current brief reads like a Bloomberg headline crawl: news items aggregated into thematic sections (`AI & TECH DEVELOPMENTS`, `CORPORATE STRATEGY`) with no portfolio context, no overnight tape, no macro calendar, and no actionable framing. The brief redesign audit found the **biggest bug is data we already fetch but silently drop**: per-holding quotes pulled from S3 are loaded into `BriefingContext` but the formatter never renders them; portfolio holdings and news both expose `entity_id` but are never intersected; macro events are queried only by portfolio-entity scope so Fed/CPI without `subject_entity_id` are invisible. Most of the user-visible improvement can ship with **zero new endpoints** — just wire the dropped data.

Alongside the brief redesign, ITER-10 surfaced 4 followups from the PLAN-0101 chat-eval + QA:
- `tps_streaming` metric returns NaN across all questions (the new gate we shipped in PLAN-0101 W3 doesn't produce data live)
- Q2/Q5 graded MARGINAL with new reason "citation marker out of bounds" — likely BP-613's `joined_tokens` fallback ships rejected text with stale `[N#]` markers
- Q3 graded USELESS for honest refusal — grader treats every refusal as USELESS regardless of whether tools actually returned empty
- One `market.dataset.fetched` message dead-letters per ~5 min (45s persist timeout)

Plus three doc gaps from the audit round (BP-610 audit missing, BP-612/613 not in BUG_PATTERNS, no PLAN-0101 plan file).

### Acceptance criteria

Chat-eval rerun on rebuilt stack with the four env flags must show:
- USEFUL ≥ 6 (today 5/9; W5 grader policy + W1 brief improvements help)
- HARMFUL = 0 ✓ (today 0; defended)
- TTFT p95 < 5 s ✓ (today 2.20 s)
- `tps_streaming` p50 ≥ 15 tok/s (today NaN; W4 closes)
- E2E p99 < 90 s (today 128.6 s; W5 grader + Q6 narrow target)

Live brief check: trigger a brief for a synthetic user with 5 holdings (AAPL, MSFT, NVDA, AMD, TSLA). Verify:
- "Tape" section names SPY / QQQ / VIX with current pre-mkt levels (or "after-hours" tag)
- "Your Portfolio Today" section names every holding and at least 3 P&L numbers
- "Macro Today" section names ≥ 1 macro event from the next 48 h (or "no scheduled prints")
- "News That Matters To You" section contains ≤ 5 items and every item references an entity held or in the same sector as a held entity
- Total ≤ 250 words; cap enforced

### Cross-PRD conflict check

- PLAN-0101 W3 shipped `tps_streaming` metric — this plan's W4 closes the NaN regression in that metric (not a conflict; this is the natural completion of PLAN-0101 W3).
- PLAN-0094 (rate-limits + daily brief pre-generation) shipped the brief pre-gen worker. The Wave A prompt + formatter rewrites under this plan affect the SAME brief artefact the W3 worker emits. Coordination: redeploy the brief-scheduler container after W1 lands.

## §1 Dependency Graph

```
W1 (Brief A) ────► W2 (Brief B) ────► W3 (Brief C)
                       │
                       └── needs S1 + S6 endpoints

W4 (latency metric) ─── independent
W5 (grader policy) ──── independent
W6 (DLQ timeout) ────── independent
W7 (doc gaps) ───────── can ship anytime
```

W1, W4, W5, W6, W7 can run in parallel.
W2 depends on W1 (shared files: `briefing_context.py`, `brief_context_formatter.py`).
W3 depends on W2.

## §2 Codebase Verification

| Citation | File:line | Verified |
|---|---|---|
| Brief context gatherer | `services/rag-chat/src/rag_chat/application/use_cases/briefing_context.py` | ✅ exists |
| Brief context formatter | `services/rag-chat/src/rag_chat/application/use_cases/brief_context_formatter.py` | ✅ exists |
| Brief generator | `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` | ✅ exists |
| Morning prompt | `libs/prompts/src/prompts/briefing/morning.py:30-85` | ✅ per brief-redesign audit |
| `MarketOverview` model | location TBD by W1 agent | per audit it's defined but never populated |
| Harness `_compute_tps_streaming` | `tests/validation/chat_eval/harness.py` | ✅ exists; logic returns NaN |
| Orchestrator phase wrappers | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:1687,1696` | ✅ verified PLAN-0101 review |
| Grader entry point | `tests/validation/chat_eval/grading.py` | ✅ exists |
| Fundamentals consumer | `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:589` | ✅ touch call confirmed live |

## §3 Sub-plans

### Wave 1 — Brief Wave A: Repackage Existing Data (P0, ~6 h)

**Goal**: 70% of the user-perceived pain closed with zero new endpoints. The biggest bug is data we already fetch but silently drop.

#### Tasks

- **T-W1-01 — Wire `market_overview` end-to-end**
  - **Pain point**: per-holding quotes are fetched from S3 (briefing_context.py around line 155) and loaded into `BriefingContext`, but `format_market_overview()` (brief_context_formatter.py:240-250) only renders `ctx.market_overview.sector_performance` and the `market_overview` field is **never populated**. We pay for the upstream call and discard the data. Classic returned-value-persistence footgun (see `memory/feedback_audit_returned_value_persistence.md`).
  - **Root cause**: `MarketOverview.for_morning()` (or equivalent constructor) takes `sector_performance` only; the per-holding quote list goes into `ctx.holdings_quotes` but the formatter doesn't read that field.
  - **Point of failure**: silent drop at formatter; metrics show success because the upstream call returned 200 and items were captured.
  - **Best long-term fix**: rebuild `MarketOverview` as `{indices: list[QuoteSummary], holdings: list[QuoteSummary], sector_performance: dict}`; populate all three from the same S3 batch call; render all three in the formatter under explicit section headers.
  - **File:line**: `briefing_context.py:155-200` (gatherer), `brief_context_formatter.py:240-280` (formatter), domain model in `application/models/briefing_context.py`.
  - **Regression test**: feed synthetic quote list with `[AAPL, MSFT, SPY, QQQ, VIX]`; assert formatter output mentions every symbol with its quote.
  - **Acceptance**: rendered brief for a 5-holding user mentions every holding's quote in the "Your Portfolio Today" pre-section.

- **T-W1-02 — Add SPY / QQQ / VIX to the ticker batch**
  - **Pain point**: brief has no "tape direction" — user can't tell at a glance if markets are up or down overnight.
  - **Root cause**: gatherer only queries S3 for portfolio-held tickers; no baseline market tickers.
  - **Best long-term fix**: extend the S3 batch call with `["SPY", "QQQ", "VIX"]` appended to the holdings list; surface them as a distinct "Tape" section, separately from holdings.
  - **File:line**: `briefing_context.py` around the S3 batch construction.
  - **Regression test**: assert the S3 batch input includes SPY/QQQ/VIX; assert formatter renders a "Tape" section.
  - **Acceptance**: brief has a 1-line tape summary like `"S&P futures +0.3% | NASDAQ +0.5% | VIX 14.2"`.

- **T-W1-03 — Portfolio-news entity-overlap scoring**
  - **Pain point**: news section is identical for every user. We have `NewsArticleSummary.primary_entity_id` and `PortfolioSnapshot.holdings[*].entity_id` but never intersect them, so a user holding NVDA sees the same generic AI news as a user holding KO.
  - **Root cause**: news is ranked only by `relevance_score`; no overlap multiplier.
  - **Best long-term fix**: compute `overlap_set = {h.entity_id for h in holdings} & {n.primary_entity_id for n in news}`; multiply news score by `1.5` (configurable) when `n.primary_entity_id in overlap_set`. Re-rank. Top N taken after re-ranking.
  - **File:line**: `briefing_context.py:601` area for news gathering; new helper `_score_news_by_overlap()`.
  - **Regression test**: synthetic news + holdings; assert overlapping items rank higher; assert non-overlapping items still appear if no overlapping items exist (floor).
  - **Acceptance**: 5-holding synthetic user sees news ordered so that holding-related items appear first.

- **T-W1-04 — Macro events: second S7 call without entity scope**
  - **Pain point**: Fed meetings, CPI prints, jobless claims are invisible because they have no `subject_entity_id` so `_fetch_events()` (briefing_context.py:450) — which filters by `entity_ids=portfolio_entities` — drops them.
  - **Root cause**: single S7 call with overly tight filter.
  - **Best long-term fix**: split into two calls: (a) `entity_ids=portfolio_entities, event_types=["earnings","analyst_action","corporate"]` and (b) `entity_ids=None, event_types=["macro","economic"]`. Merge results; tag each event with its source tier so the formatter can group them.
  - **File:line**: `briefing_context.py:450-500`.
  - **Regression test**: mock S7 returning 2 entity-scoped + 2 entity-less macro; assert all 4 surface in the merged context.
  - **Acceptance**: brief has a "Macro Today" section listing ≥ 1 macro event when one exists in the next 48 h, OR an explicit "no scheduled prints" placeholder.

- **T-W1-05 — Rewrite the morning prompt**
  - **Pain point**: prompt at `libs/prompts/src/prompts/briefing/morning.py:30-85` says "synthesize this data into a structured brief" without telling the LLM HOW to structure it for a 5-min read.
  - **Root cause**: prompt is structurally generic; LLM falls back to its training prior ("write a news summary") instead of "write a 5-min investor brief".
  - **Best long-term fix**: replace the prompt body with the 6-section spec from the audit:
    ```
    You are writing the 5-minute morning brief for an investor about to scan it before market open.
    Goal: tell them what changed overnight that affects their decisions today.

    You have:
      - Portfolio: <holdings + sector + last close>
      - Overnight tape: <SPY/QQQ/VIX>
      - Macro calendar: <events today + tomorrow>
      - News (pre-ranked by relevance × portfolio overlap): <list>

    Output sections in this exact order:
      1. **Tape** — one sentence. Futures + VIX.
      2. **Your Portfolio Today** — bullet per material holding. Lead with implication.
      3. **Macro Today** — bullet list of today/tomorrow's prints.
      4. **News That Matters To You** — 3-5 items. Each leads with the implication for the investor, then the fact, then [N#] citation.
      5. **Risks + Opportunities** — 2-3 model-generated lines synthesising signal across the data.
      6. **Bonus context** — 1-2 generic high-impact items.

    Rules:
      - Cap total at 250 words.
      - Cite sources [N1] [N2].
      - NEVER include news that doesn't connect to a holding, sector, or macro event.
      - On quiet days, surface 1 sector-relevant macro signal rather than padding with irrelevant news.
    ```
  - **File:line**: `libs/prompts/src/prompts/briefing/morning.py:30-85`.
  - **Regression test**: snapshot test asserting the prompt contains the 6 section names and the word "implication".
  - **Acceptance**: rendered brief has all 6 named sections and stays ≤ 250 words.

- **T-W1-06 — Docs sync**
  - Update `services/rag-chat/.claude-context.md` to note the new brief structure + the "data we fetch but drop" anti-pattern.
  - Update `docs/services/rag-chat.md` Brief section with the new 6-section spec.

#### W1 acceptance gate

Trigger a brief for a synthetic user with 5 holdings. Verify:
- 6 named sections present
- Every holding has a quote line
- ≥ 1 macro event named (or explicit placeholder)
- News section reordered by overlap
- Total ≤ 250 words

#### W1 compounding

- `docs/services/rag-chat.md` Brief section rewrite
- `services/rag-chat/.claude-context.md` pitfall: "format pulls only sector_performance from market_overview — populate the holdings + indices arrays explicitly"
- `docs/BUG_PATTERNS.md` BP-614 (silent data drop in brief formatter)
- `docs/plans/TRACKING.md` PLAN-0102 row → 1/7

---

### Wave 2 — Brief Wave B: Real Personalisation (P1, ~12 h)

**Status**: SHIPPED on `feat/plan-0099-w4` 2026-05-29 (T-W2-01..04 + T-W2-06; T-W2-05 delta-from-yesterday deferred to PLAN-0103). New endpoints live: `GET /internal/v1/users/{user_id}/portfolio/pnl` on S1 + `GET /internal/v1/entities/sectors` on S7. `BriefContextFormatter.format_portfolio_morning()` renders per-holding "AAPL +1.45% pre-mkt — +$280" lines + total P&L footer + sector mix footer; legacy weight-only fallback preserved on upstream failure. 19 new unit tests. See TRACKING.md PLAN-0102 row for full per-task LOC + test counts.

**Goal**: add the two new endpoints needed for true portfolio context — overnight P&L and sector exposure.

#### Tasks

- **T-W2-01 — New `GET /internal/v1/users/{user_id}/portfolio/pnl` on S1**
  - Returns: `{holdings: [{symbol, entity_id, qty, last_close, current_price, overnight_pnl_usd, overnight_pnl_pct}], total_overnight_pnl_usd, total_overnight_pnl_pct, generated_at}`.
  - Auth: existing internal-JWT.
  - Cache: 60 s Valkey.
  - **File**: new `services/portfolio/src/portfolio/api/routers/internal_pnl.py`.
  - **Test**: unit test for the use case; integration test asserting auth requirement.

- **T-W2-02 — New `GET /internal/v1/entities/sectors?ids=...` on S6 or S7**
  - Returns: `{entity_id: sector_label}` map.
  - Cache: long (1 h) — sectors rarely change.
  - **File**: TBD by agent (probably S7 which already owns canonical entities).

- **T-W2-03 — Wire both into `briefing_context.py`**
  - Add `_fetch_portfolio_pnl()` and `_fetch_sectors_for_holdings()`.
  - Compute sector-exposure aggregates (% of portfolio value per sector).
  - Render in "Your Portfolio Today" section with lines like `"AAPL +1.2% pre-mkt — +$842 (Tech 28% of portfolio)"`.

- **T-W2-04 — Delta-from-yesterday section**
  - Persist last brief's `news_entity_ids` and `events_ids` in Valkey under `brief:last:{user_id}` with 36 h TTL.
  - On generation, flag items NOT in yesterday's set as "NEW".
  - Optionally render only the new items in a compact "Since yesterday" section.

#### W2 acceptance gate

Brief for AAPL/MSFT/NVDA holder includes:
- "AAPL +1.2% pre-mkt | +$842" (real P&L)
- "Tech 65% of portfolio" exposure line
- A "Since yesterday" section listing items absent from the prior brief

---

### Wave 3 — Brief Wave C: Tape + Earnings (P2, ~8 h) — **ENDPOINTS + PORTS SHIPPED 2026-05-29**

**Status**: Backend endpoints + rag-chat adapter ports landed on `feat/plan-0099-w4`. The actual brief-side wiring (calling these new clients from `briefing_context.py` / rendering in `brief_context_formatter.py`) is intentionally deferred to a **separate follow-up commit** to avoid colliding with the parallel W2 session that was actively editing those two files.

Files shipped:
- `services/market-data/src/market_data/api/routers/internal_market_tape.py` (`GET /internal/v1/market/tape`, ~280 LOC + 12 unit tests)
- `services/market-data/src/market_data/api/routers/internal_earnings_calendar.py` (`GET /internal/v1/calendar/earnings`, ~210 LOC + 8 unit tests)
- `services/rag-chat/src/rag_chat/infrastructure/clients/market_tape_client.py` (new adapter, ~120 LOC + 6 unit tests)
- `services/rag-chat/src/rag_chat/infrastructure/clients/earnings_calendar_client.py` (new adapter, ~125 LOC + 7 unit tests)
- `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` (added `MarketTapePort`, `EarningsCalendarPort`, DTOs)

#### Tasks

- **T-W3-01 — Futures + pre-mkt feed integration**
  - Shipped. Reads existing OHLCV (1d + 5m) + Quote rows; per-symbol fail-open with `session="unavailable"`; Valkey 60 s cache; 20-symbol cap.
- **T-W3-02 — Earnings calendar endpoint**
  - Shipped. Reads `earnings_calendar` table joined with `instruments`; 90-day range cap; Valkey 5 min cache; fail-open empty `events: []` on DB error.
- **T-W3-03 — Render in Tape + Macro Today sections** — **DEFERRED to a follow-up commit**
  - The actual `briefing_context.py` + `brief_context_formatter.py` edits to call `MarketTapeClient.get_tape()` and `EarningsCalendarClient.get_earnings()` and render the new sections will land as a separate commit after W2 ships. Coordination note recorded in TRACKING.md.

#### W3 acceptance gate

Brief includes:
- "S&P futures +0.3%, NASDAQ +0.5%, VIX 14.2" in Tape
- "Earnings this week: NVDA Tue AMC, CRM Wed AMC" in Macro Today

(Gate verified after T-W3-03 follow-up commit lands.)

---

### Wave 4 — `tps_streaming` NaN repair (P0, ~2 h)  — **SHIPPED 2026-05-29**

**Goal**: fix the metric that's the whole gate, AND fix the latent double-record found in PLAN-0101 code review.

**Status**: SHIPPED on `feat/plan-0099-w4`. Root cause was (1) the `_compute_tps_streaming()` helper returned NaN that the JSON serialiser collapsed to `None` for both "skipped" (direct-text branch, no synthesis stream fires — typical of short factual questions) and "failed", and the gate then treated every chat-eval row uniformly. Live verification confirmed (a) `phase_timings_ms.llm_synthesis_streaming` IS recorded by the backend on tool-heavy queries — observed 13016 ms on `"Compare AAPL and NVDA fundamentals"` and 157622 ms on the MSTR query — and (b) is correctly ABSENT on direct-text-branch queries like `"What is Apple?"`. The harness now returns `float | None` from `_compute_tps_streaming()`; `None` means "no data, gate skipped". BP-618 filed for the latent double-record risk and closed by `PhaseTimings.record_once()` (strict in tests, WARN-and-sum in prod). See W4 fields in TRACKING.md PLAN-0102 row.

#### Tasks

- **T-W4-01 — Trace + fix the NaN**
  - **Pain point**: `tps_streaming` is NaN for every question in the latest chat-eval. The gate we shipped in PLAN-0101 W3 can't evaluate.
  - **Root cause hypotheses** (must verify live):
    1. Backend emits `phase_timings_ms.llm_synthesis_streaming` with value 0 (the phase wrapper records the path even when no streaming happens, e.g. direct-text answer branch).
    2. Harness extracts ms but divides without converting to seconds → tiny float yields NaN under all-zero denominator handling.
    3. Harness reads the wrong key (e.g. `synthesis_streaming` vs `llm_synthesis_streaming`).
  - **Verification**: trigger a synthetic chat request via curl; capture SSE events; print the `done` event's `phase_timings_ms` dict. Diff against the harness extraction logic.
  - **Best long-term fix**: typed return for `_compute_tps_streaming()` that returns `None` (not NaN) when denominator < 100 ms; harness records `None` and gate treats `None` as "skipped" not "fail". Plus: keep ms units explicit (`phase_timings_ms`) and convert to seconds INSIDE the helper.
  - **File:line**: `tests/validation/chat_eval/harness.py` (helper); `tests/validation/chat_eval/test_aggregate_score.py` (gate handles None).
  - **Regression test**: synthetic event stream with `llm_synthesis_streaming=500ms` and 100 tokens → assert `tps_streaming = 200.0`; stream with 0 ms → assert `None`.

- **T-W4-02 — Latent double-record guard on `llm_synthesis_streaming`**
  - **Pain point**: `PhaseTimings.record` accumulates. Lines 1687 + 1696 in `chat_orchestrator.py` are mutually exclusive only by current control-flow accident. Any new partial-recovery branch will silently halve TPS-streaming denominator.
  - **Root cause**: no idempotency guard on phase recording.
  - **Best long-term fix**: add `PhaseTimings.record_once(phase_name, ms)` that asserts the phase hasn't been recorded yet, OR a `set` semantics where re-recording REPLACES instead of summing.
  - **File:line**: `services/rag-chat/src/rag_chat/application/observability/phase_timings.py`; usages at `chat_orchestrator.py:1687, 1696`.
  - **Regression test**: assert calling `record_once` twice on the same phase raises (test mode) or warns (prod mode) without summing.

- **T-W4-03 — Live verification**
  - Trigger a synthetic chat. Assert `phase_timings_ms.llm_synthesis_streaming` present and the harness computes a real number.

- **T-W4-B — Followup: record `llm_direct_text_generation` on direct-text branches (BP-621)**
  - **Pain point**: After T-W4-01..03 shipped, the next chat-eval run still produced `tps_streaming p50 = NaN` because ~100% of 9 questions returned `tps_streaming: None`. Live tracing: agg_q*.json `phase_timings_ms` contained neither `llm_synthesis_streaming` nor any synthesis-equivalent key — only `llm_tool_planning` + `tool_execution`. Even questions that fired tools then produced direct text (FIX-LIVE-Y path) terminated WITHOUT entering the second-turn stream.
  - **Root cause**: Hypothesis 1 from T-W4-01 confirmed in the wild. The orchestrator only records `llm_synthesis_streaming` on the second-turn `stream_chat` path (line ~1660); direct-text answers ("What is Apple?") and FIX-LIVE-Y tool-then-direct-text answers both set `_skip_final_stream=True` and emit via `emit_delta` without recording any synthesis-equivalent phase.
  - **Fix**: orchestrator records `llm_direct_text_generation = THIS iteration's chat_with_tools wall-clock` on the direct-text branch (BOTH iter-0 and iter>0 paths) using `record_once`; harness `_compute_tps_streaming()` accepts EITHER `llm_synthesis_streaming` OR `llm_direct_text_generation` (synthesis-stream wins when both present — defensive).
  - **File:line**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:~962`; `tests/validation/chat_eval/harness.py::_compute_tps_streaming` (OR-fallback).
  - **Regression tests**: `tests/validation/chat_eval/test_harness_latency.py::TestTpsStreaming::test_direct_text_phase_used_when_synthesis_absent` + `::test_synthesis_phase_wins_when_both_present`.
  - **Live verification**: 9/9 questions now have finite `tps_streaming`; aggregate p50 = 16.09 tok/s (was NaN). TTFT p95 = 4.65 s (still <5s gate; semantics unchanged). New BP-621 entry.

#### W4 acceptance gate

Chat-eval `tps_streaming_p50` is a finite number on ≥5 of 9 questions (gate satisfied — 9/9 finite after T-W4-B). Whether p50 ≥ 20 tok/s remains a separate content/throughput question (deferred to PLAN-0103).

---

### Wave 5 — Grader Policy Fixes (P1, ~3 h)  — **SHIPPED 2026-05-29**

**Status**: SHIPPED on `feat/plan-0099-w4`. All three policy gaps fixed under BP-619 (cascade). W5-01: longer-wins threshold raised to 10x so validator trims no longer trigger fallback + orphan citation marker scrubber added. W5-02: `tool_results` SSE events now captured on `ChatRunResult`; grader downgrades USELESS → MARGINAL when refusal coincides with `item_count=0`. W5-03: Q6 was actually parser-too-narrow — the model named NVIDIA / TSMC / Broadcom / AMD / Intel using company names; the test regex only matched ticker symbols. Added 11-entry `_NAME_ALIASES` map. See W5 fields in TRACKING.md PLAN-0102 row.

#### Tasks

- **T-W5-01 — BP-613 longer-wins ↔ numeric-grounding fix**
  - **Pain point**: Q2 + Q5 graded MARGINAL with reason `"citation marker out of bounds"`. The numeric-grounding validator (PLAN-0093) strips ungrounded numbers from `final_answer`; the BP-613 longer-wins rule then prefers the longer `joined_tokens` (the pre-validation text) — which still contains `[N7]` markers pointing to citations that were also stripped.
  - **Root cause**: longer-wins rule treats the validator's truncation as "answer assembly failure" and falls back to the rejected text.
  - **Best long-term fix**: prefer `final_answer` unless it's < 10 % of `joined_tokens` length; OR re-scrub citation markers in the fallback path to drop refs > max valid index.
  - **File:line**: `tests/validation/chat_eval/harness.py` around line 590-598 (per audit).
  - **Regression test**: synthetic event stream with `joined_tokens` carrying `[N7]` and `final_answer` validated down to no citations — assert harness picks the validated answer.

- **T-W5-02 — Honest-refusal grader policy**
  - **Pain point**: Q3 Tim Cook graded USELESS with reason `"response reads as a refusal"`. The model correctly refused because the upstream `get_entity_intelligence` returned empty — that's our W1 BP-604/605 doing its job.
  - **Root cause**: grader treats every refusal as USELESS regardless of whether tools actually returned empty.
  - **Best long-term fix**: refusal-with-evidence ≠ refusal-from-nowhere. Add a check: if answer contains "tool returned empty" / "did not find" / "no data" markers AND at least one tool call event has `item_count=0`, downgrade verdict from USELESS to MARGINAL.
  - **File:line**: `tests/validation/chat_eval/grading.py` refusal-detection branch.
  - **Regression test**: synthetic events with one tool call returning empty + answer containing "I cannot find" — assert MARGINAL not USELESS.

- **T-W5-03 — Q6 screener output trimmed to 1 ticker**
  - **Pain point**: Q6 screener test asserted ≥ 3 tickers; live brief mentioned only AMD.
  - **Root cause to verify**: either (a) the screener tool result was truncated to 1 row before reaching the LLM, OR (b) the LLM dropped the others on synthesis, OR (c) the answer parser only extracted the first ticker.
  - **Best long-term fix**: depends on root cause. If (a), bump the screener result limit in the tool handler. If (b), add prompt instruction "if the tool returns N rows, mention all N in your answer". If (c), fix the parser.
  - **File:line**: TBD by agent — likely `services/rag-chat/src/rag_chat/application/pipeline/handlers/screen_universe.py` for (a) or the system prompt for (b).
  - **Regression test**: synthetic screener tool returning 8 tickers — assert the brief output mentions all 8 (or at least the configured display cap).

#### W5 acceptance gate

Q2 / Q3 / Q5 / Q6 each move out of MARGINAL/USELESS in chat-eval.

---

### Wave 6 — DLQ Persist Timeout (P1, ~2 h)

#### Tasks

- **T-W6-01 — Bump per-message timeout for `market.dataset.fetched`**
  - **Pain point**: 1 message per ~5 min dead-lettered for 45 s persist timeout. Discovered during BP-610 live verification.
  - **Root cause to verify**: large-universe payloads (Russell 1000 with 600+ sections in a single message) exceed 45 s consumer budget.
  - **Best long-term fix**:
    - Raise `message_processing_timeout_s` for the fundamentals consumer to 90 s.
    - Paginate the consumer's per-section batch writes so each transaction commits every N sections instead of all-or-nothing.
    - Emit Prom histogram `fundamentals_consumer_processing_ms` so we can see the tail.
  - **File:line**: `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer_main.py` for the timeout; `fundamentals_consumer.py:550-650` for pagination.
  - **Regression test**: synthetic payload with 600 sections — assert it commits in chunks of N and stays under the budget.

#### W6 acceptance gate

Zero DLQ messages for `market.dataset.fetched` over 24 h post-deploy.

---

### Wave 7 — Doc Gaps (P2, ~1 h)

#### Tasks

- **T-W7-01** — Create `docs/audits/2026-05-28-plan-0101-bp-610-touch-at.md` (referenced from `BUG_PATTERNS.md` but file doesn't exist).
- **T-W7-02** — Add BP-612 + BP-613 entries to `docs/BUG_PATTERNS.md` (commits cite them but no entries).
- **T-W7-03** — Create `docs/plans/0101-iter-10-tps-redesign-and-graders.md` retroactively from the PLAN-0101 TRACKING.md row + commits.

## §5 Cross-cutting Acceptance Gate

After all 7 waves deploy:

1. **Chat-eval rerun** on rebuilt stack with `APP_ENV=development DEBUG_SKIP_CLASSIFIER=true RAG_COMPLETION_CACHE_DISABLED=true RAG_CHAT_BASE_URL=http://localhost:8000`:
   - USEFUL ≥ 6 ✓
   - HARMFUL = 0 ✓
   - TTFT p95 < 5 s ✓
   - `tps_streaming` p50 ≥ 15 tok/s ✓ (NaN closed by W4)
   - E2E p99 < 90 s (partial — Q6 outlier is a separate problem)

2. **Live brief check** for a synthetic user with holdings {AAPL, MSFT, NVDA, AMD, TSLA}:
   - 6 named sections present
   - Every holding mentioned
   - ≥ 1 macro event named or placeholder shown
   - News reordered by overlap (NVDA-related items rank above generic AI news)
   - Total ≤ 250 words
   - Lead sentence synthesises tape + most material exposure

3. **DLQ check**: zero `market.dataset.fetched` DLQ messages in last 24 h.

## §6 Risk Register

| Risk | Mitigation |
|---|---|
| Brief Wave A over-aggressively rejects "irrelevant" news on quiet days → empty brief | Floor of 3 "general high-impact" items even when overlap is empty; the prompt explicitly handles the quiet-day case |
| `tps_streaming` fix surfaces a different metric semantics issue | Gate redefine deferred to PLAN-0103 if needed; W4 returns `None` not NaN so the gate can skip cleanly |
| DLQ timeout bump masks a real slow-query regression | Add the Prom histogram in the same wave so we observe the tail explicitly |
| New S1 P&L endpoint introduces a race when prices update mid-call | 60 s cache + best-effort `as_of` timestamp in the response |
| Sector classification drift between S6 and S7 | Single source of truth in S7 canonical entity store; S6 is fallback only |
| Tape integration adds an external dependency on EODHD intraday feed | Cache aggressively (60 s); graceful degradation to "tape unavailable" placeholder if the feed is down |

## §7 Compounding Steps

Per wave:
- W1: rag-chat docs + .claude-context.md + BP-614 entry + TRACKING.md
- W2: portfolio.md docs (new endpoint) + S6 or S7 docs (new endpoint) + TRACKING.md
- W3: market-data docs (new endpoints) + TRACKING.md
- W4: chat-eval README (semantics of `tps_streaming`) + BP-615 entry (latent double-record)
- W5: chat-eval grader doc (new policy) + BP-616 entry (citation marker scrub)
- W6: market-data docs (timeout + pagination) + BP-617 entry (large-payload DLQ)
- W7: BP-612 + BP-613 entries + plan file

**BP numbers reserved**: BP-614 (silent format drop), BP-615 (phase double-record), BP-616 (citation marker fallback), BP-617 (DLQ large payload). Verify against live `BUG_PATTERNS.md` high-water before filing.

## §8 Owner

TBD — recommend owner per wave:
- W1 — backend (rag-chat domain)
- W2 — full-stack (S1 + S7 endpoints + rag-chat gatherer)
- W3 — full-stack (market-data feed + rag-chat formatter)
- W4 — backend (chat-eval + rag-chat observability)
- W5 — chat-eval tooling owner
- W6 — market-data consumer owner
- W7 — anyone; pure docs

---

## Estimated Effort

| Wave | Hours | Notes |
|---|---|---|
| W1 — Brief A | 6 | No new endpoints; biggest single quality win |
| W2 — Brief B | 12 | Two new endpoints + wiring + delta-from-yesterday |
| W3 — Brief C | 8 | Tape + earnings calendar feeds |
| W4 — TPS metric | 2 | Trace + fix + record_once guard |
| W5 — Grader | 3 | Three small policy fixes |
| W6 — DLQ timeout | 2 | Timeout bump + pagination + histogram |
| W7 — Docs | 1 | Three doc adds |
| **Total** | **~34 h** | Brief work dominates |

If W1-W2 ship first, the user-perceived improvement is immediate and large. W3-W7 can be sequenced afterwards without blocking.
