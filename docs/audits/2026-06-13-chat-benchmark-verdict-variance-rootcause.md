# Investigation Report: Chat-Quality Benchmark Verdict Variance

**Date**: 2026-06-13
**Investigator**: Claude (investigate skill)
**Severity**: HIGH — threatens the credibility of the thesis evaluation number
**Status**: Root cause(s) identified

---

## 1. Summary

Two 67-question runs of the chat-quality benchmark produced **19 verdict flips (~28%)**,
bidirectional (9 FAIL→PASS, 1 ERROR→PASS, 1 WARN→PASS, 4 FAIL→WARN, 4 PASS→FAIL).
The variance is **not a single bug** — it is the product of **three compounding,
independent non-determinism sources**, plus **one confound that invalidates the
"same build" premise**:

1. **CONFOUND (dominant systematic driver): the two runs used DIFFERENT judge
   prompts.** OLD = `chat_quality_judge@3.0#dbbee7f7c6b5`, NEW =
   `chat_quality_judge@1.1#59c4250d31ea` (`_meta.json`). v3.0 **DELETED the
   "PRESUME GROUNDED → award 20-25" instruction**; v1.1 still presumes grounding.
   This systematically pushes v3.0 grounding scores below the floor (→FAIL) where
   v1.1 awards 20-25 (→PASS). These are **not the same build** — the entire
   FAIL→PASS direction is largely explained by OLD being graded by the stricter
   v3.0 judge and NEW by the lenient v1.1 judge.
2. **Agent-side non-determinism**: the agent tool-planning call runs at
   `temperature=0.1` with **no seed** and the planning API (`chat_with_tools`)
   **does not even accept a `seed` argument**. Different runs pick different tool
   plans and emit different answer text (often a refusal-stub vs a real answer).
   **None of the 19 answer pairs are byte-identical.**
3. **Agent self-grounding-veto stub fires non-deterministically**: the
   orchestrator's own phantom-citation / empty-pool / plan-only gates replace the
   answer with a worded refusal stub. The stub fired **13× in OLD vs 7× in NEW**,
   on largely different questions — because it keys off the exact (non-deterministic)
   generated text.
4. **Judge-side non-determinism**: the judge runs at `temperature=0.0` but **no
   seed**; DeepSeek-V4-Flash is a MoE model, so temp=0 is not bit-deterministic.
   The grounding floor (12) sits exactly between the modal scores 10 and 20, so a
   one-band judge wobble flips the verdict.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| OLD judge `@3.0`, NEW judge `@1.1` | `runs/*/_meta.json` | Different builds — invalidates "same build" premise |
| v3.0 "DELETED PRESUME GROUNDED" | `libs/prompts/src/prompts/evaluation/chat_quality_judge.py:3-9,350-360` | Systematic grounding-score shift |
| Current tree = `@3.0#dbbee7f7c6b5` | `CHAT_QUALITY_JUDGE.identifier()` | NEW (later) run used an OLDER prompt → runs not comparable |
| Planning call `temperature=0.1`, no seed | `chat_orchestrator.py:2009-2025` | Tool-plan non-determinism |
| `chat_with_tools` has no `seed` param | `deepinfra_adapter.py:281-317` | Planning step cannot be seeded even if asked |
| Stub fallback strings | `chat_orchestrator.py:895-913` | Source of the 273-char refusal answers |
| Stub fired 13× (OLD) vs 7× (NEW), different sets | run JSON scan | Agent answer non-determinism |
| Judge `temperature=0.0`, no `seed` | `chat_quality_judge.py:432-443` | Judge non-determinism on MoE model |
| `GROUNDING_VETO_FLOOR = 12`; modal grounding ∈ {0,5,10,20,22,25} | `chat_quality_judge.py:114` | Floor sits in the gap → 1-band wobble flips verdict |
| `ru_googl_pe_vs_history` OLD: all dims None, raw_response empty, latency 118s | `q_ru_googl_pe_vs_history.json` | Judge-call infra failure (ERROR), transient |

---

## 3. Per-Question Classification (19 flips)

Dominant-cause codes:
`JUDGE_PROMPT_VER` (v3.0 vs v1.1 grounding-presumption difference),
`AGENT_STUB` (self-grounding-veto refusal stub fired in one run only),
`AGENT_TOOL_PLAN` (different tool set chosen),
`AGENT_EMPTY_TOOL` (no/empty tool result → empty answer),
`JUDGE_FLOOR_WOBBLE` (equivalent answer, grounding score crossed floor 12),
`JUDGE_GATE_FLAKE` (phantom-citation gate fired in one run only on equivalent answer),
`INFRA_TRANSIENT`.

| # | id | OLD→NEW | dominant cause | one-line evidence |
|---|----|---------|----------------|-------------------|
| 1 | agg_q3_tim_cook | FAIL→PASS | JUDGE_PROMPT_VER | same 2 tools, both real answers; OLD@3.0 gr=5 ("marked unverified") vs NEW@1.1 gr=20 (same prose presumed) → floor cross |
| 2 | chain_nvda_competitor_growth_rank | FAIL→PASS | AGENT_STUB + AGENT_TOOL_PLAN | OLD stub 273ch (get_entity_paths plan) vs NEW 2777ch (fundamentals_history plan) |
| 3 | da_apple_revenue_fy2024q4_precision | FAIL→PASS | JUDGE_PROMPT_VER | same 1 tool; OLD@3.0 gr=10 flags "$94.949B fabricated full precision" vs NEW@1.1 gr=25 "presumed" |
| 4 | iter3_apple_suppliers_compound | FAIL→PASS | AGENT_STUB | OLD stub 273ch vs NEW 2416ch, same 4 tools — agent refused in OLD only |
| 5 | iter3_tesla_revenue_since_2023 | FAIL→PASS | AGENT_EMPTY_TOOL | OLD 0 tools / empty answer (empty_answer veto) vs NEW called get_fundamentals_history → 2878ch |
| 6 | iter3_top5_tech_marketcap | FAIL→PASS | AGENT_EMPTY_TOOL | OLD 0 tools / empty answer vs NEW called screen_universe (then stub but PASS@1.1) |
| 7 | tc_entity_graph_tesla_neighbors | FAIL→PASS | JUDGE_GATE_FLAKE | same 2 tools, ~equivalent answer; OLD phantom_citation:has_executive fired, NEW did not |
| 8 | tc_get_alerts_list_active | FAIL→PASS | AGENT_STUB + JUDGE_PROMPT_VER | OLD 289ch "claims no access" gr=0 vs NEW 1283ch lists alerts gr=20 |
| 9 | tc_price_history_msft_ytd_range | FAIL→PASS | AGENT_STUB + JUDGE_PROMPT_VER | OLD stub 273ch (refused despite data) gr=0 vs NEW 1318ch real answer gr=25 |
| 10 | ru_googl_pe_vs_history | ERROR→PASS | INFRA_TRANSIENT | OLD judge call returned empty raw / all dims None, latency 118s (DeepInfra zero-chunk); NEW judge succeeded |
| 11 | tc_portfolio_dividend_yielders | WARN→PASS | AGENT_TOOL_PLAN + AGENT_STUB | OLD stub 273ch (1 tool) vs NEW 954ch (added query_fundamentals) |
| 12 | chain_portfolio_upcoming_earnings | FAIL→WARN | AGENT_STUB | OLD stub 273ch (framing=5) vs NEW 398ch (framing=10); both low-quality, band shifted |
| 13 | da_aapl_pe_dec2024 | FAIL→WARN | AGENT_STUB | OLD stub 273ch framing=10 vs NEW 160ch framing=25; agent refused only in OLD |
| 14 | iter3_apple_competitors_spanish | FAIL→WARN | JUDGE_PROMPT_VER | same 2 tools; OLD@3.0 all-zero+grounding veto vs NEW@1.1 gr=20/fr=25 (presumed) |
| 15 | tc_search_claims_tesla_margins | FAIL→WARN | JUDGE_GATE_FLAKE + AGENT_TOOL_PLAN | OLD phantom_citation veto; NEW added get_fundamentals_history, no phantom flag |
| 16 | chain_apple_suppliers_high_margin | PASS→FAIL | AGENT_TOOL_PLAN | OLD 1093ch (3 tools) vs NEW 260ch (added search_documents, shorter answer) gr=0 floor veto |
| 17 | chain_unhealthy_entity_investigation | PASS→FAIL | AGENT_TOOL_PLAN + JUDGE_GATE_FLAKE | OLD called 7 tools (incl. get_entity_paths/news/narrative) → PASS; NEW called 3 → phantom_citation:query_data_quality |
| 18 | da_msft_fy2024q4_earnings_citations | PASS→FAIL | AGENT_STUB | OLD 1296ch real (gr=22) vs NEW stub 273ch (gr=0) — agent refused only in NEW |
| 19 | tc_search_claims_ai_chip_demand | PASS→FAIL | AGENT_STUB | OLD stub 273ch (treated as honest refusal gr=25) vs NEW 611ch fabricated claims gr=0 floor veto |

> Note: codes are the *dominant* cause. Most flips are multi-causal — the agent
> emitted a different answer AND the judge graded under a different prompt/seed.
> Where the answer was materially equivalent (same tools, both substantive or both
> refusals), the flip is attributed to the judge.

---

## 4. Agent vs Judge vs Infra Aggregate

| Layer | Flips (dominant) | ids |
|-------|------------------|-----|
| **AGENT-side** (different answer/tool plan/stub) | **12** | 2,4,5,6,8,9,11,12,13,16,18,19 |
| **JUDGE-side** (prompt-ver, floor wobble, gate flake on equivalent answer) | **6** | 1,3,7,14,15,17 |
| **INFRA-transient** | **1** | 10 |

(#8, #9, #15, #17 are genuinely multi-causal; counted under their dominant layer.)

**Roughly 2/3 agent-side, 1/3 judge-side, 1 infra.** But the single largest
*systematic* lever is the **judge-prompt-version confound**, which sits underneath
many of the agent-side flips too: every borderline answer was graded with a
different grounding philosophy in the two runs.

---

## 5. Top Systemic Drivers (ranked)

### Driver 1 — Different judge prompt between runs (confound + systematic bias)
**Evidence**: `runs/run_20260613T053200Z/_meta.json` judge `@3.0`;
`runs/run_20260613T204300Z/_meta.json` judge `@1.1`. The current tree is
`@3.0#dbbee7f7c6b5` (`CHAT_QUALITY_JUDGE.identifier()`), so the *later* run used an
*older* prompt. v3.0 deleted "PRESUME GROUNDED → 20-25"
(`chat_quality_judge.py:3-9, 350-360`). Direct proof — same answer, opposite
grounding score: `da_apple_revenue_fy2024q4_precision` OLD@3.0 gr=10 vs NEW@1.1
gr=25; `agg_q3_tim_cook` OLD@3.0 gr=5 vs NEW@1.1 gr=20. **The two runs are not a
fair same-build A/B.**

### Driver 2 — Unseeded, temperature>0 agent tool-planning
**Evidence**: `chat_orchestrator.py:2009-2025` calls `chat_with_tools(...,
temperature=0.1, ...)` with **no seed**, and `deepinfra_adapter.py:281-317`
(`chat_with_tools`) has **no `seed` parameter** at all (the streaming synthesis
path at `:3131-3145` does pass `seed=request.seed`, but the *planning* path does
not). Result: different tool sets across runs (`iter3_tesla_revenue_since_2023`,
`chain_unhealthy_entity_investigation`, `chain_apple_suppliers_high_margin`,
`tc_portfolio_dividend_yielders`, `chain_nvda_competitor_growth_rank`) and
different generated text feeding the orchestrator's own grounding gates.

### Driver 3 — Self-grounding-veto stub + judge grounding floor both bistable
**Evidence**: stub strings at `chat_orchestrator.py:895-913`; gates at
`:3785-3808` and `:4019`. Stub fired 13× (OLD) vs 7× (NEW) on different question
sets. The judge floor `GROUNDING_VETO_FLOOR = 12` (`chat_quality_judge.py:114`)
sits in the empty gap between the modal grounding scores 10 and 20, so a single
qualitative judge wobble (or an unseeded MoE re-route) crosses it and flips
PASS↔FAIL. Judge itself is `temperature=0.0` but **unseeded**
(`chat_quality_judge.py:432-443`).

---

## 6. Impact

- **Immediate**: the headline pass-rate is unstable to ±~28% verdict churn; any
  single-run number in the thesis is not defensible.
- **Blast radius**: every downstream artefact (`_summary.json`, `_report.md`,
  `_regressions.json`, trend chart) inherits the instability.
- **Data integrity**: no corruption — the runs faithfully record a genuinely
  non-deterministic pipeline.

---

## 7. Ranked Mitigations

| # | Mitigation | What to change | Expected variance reduction | Cost |
|---|-----------|----------------|-----------------------------|------|
| **1 (highest leverage)** | **Pin ONE judge prompt + report multi-run aggregate** | Always run with `max_runs_per_q=3` (framework already supports it; both audited runs used `1`) and report the **per-question majority verdict** + **mean dimension scores**; assert both runs use the same `judge_prompt_id` (fail loudly on mismatch). | Eliminates the prompt-version confound entirely; majority-of-3 cuts residual flip rate ~3-4× (a 28% single-run flip rate → roughly 5-9% on the aggregate). | 3× judge+agent calls per question (~3× run cost/time). |
| 2 | **Seed the agent tool-planning call** | Add a `seed` param to `chat_with_tools` (`deepinfra_adapter.py:281`) and pass `seed=request.seed` at `chat_orchestrator.py:2009`; lower planning `temperature` 0.1→0.0 for benchmark runs. | Removes most AGENT_TOOL_PLAN + AGENT_STUB flips (≈8 of 12 agent-side). Note: DeepInfra seed is best-effort on MoE, not a guarantee. | Small code change; near-zero runtime cost. |
| 3 | **Seed the judge call** | Add `"seed": <fixed>` to the judge payload (`chat_quality_judge.py:432`). | Reduces JUDGE_FLOOR_WOBBLE / JUDGE_GATE_FLAKE; best-effort on MoE. | None. |
| 4 | **Add hysteresis / report means, not the floor cross** | In the report, surface mean grounding score and a "borderline" band (10-14) flag instead of a single hard floor=12 verdict; or widen the floor's dead-band and require 2/3 runs below floor to veto. | Stops 1-band wobbles from flipping the headline; converts ~6 judge-side flips into stable "borderline". | None (reporting change). |
| 5 | **Make retrieval deterministic for the benchmark** | Audit RAG retrieval for ANN/RRF tie-ordering, `ORDER BY random()`, and time-windowed (`utc_now()`-relative) queries; pin a fixed `as_of` clock for benchmark runs. | Removes tool-result drift that feeds both the agent gate and the judge. | Medium (needs retrieval audit). |
| 6 | **Pin the fallback model & log when it fires** | Record `stream_chat_fallback_model` activation in the per-question artefact; treat any fallback fire as a flagged (non-headline) result. | Distinguishes infra-transient (#10-style) from logic variance; doesn't reduce variance but makes it attributable. | None. |

**Single highest-leverage action: mitigation #1** — pin a single judge prompt and
report the `max_runs_per_q=3` majority/mean the framework already supports. It both
removes the build-confound and structurally suppresses the residual stochasticity
from drivers 2-4, for a defensible thesis number.

---

## 8. BUG_PATTERNS Candidate (determinism gap confirmed)

> **BP-CANDIDATE — Agent tool-planning is unseeded while synthesis is seeded.**
> `ChatOrchestrator` seeds the streaming synthesis call (`seed=request.seed`) but
> the tool-planning call (`chat_with_tools`, `chat_orchestrator.py:2009`,
> `temperature=0.1`) takes no seed and the adapter method
> (`deepinfra_adapter.py:281`) has no `seed` parameter. "Determinism mode" is
> therefore only half-applied: the agent still picks different tool plans across
> identical requests, producing different answers and verdicts. **Fix**: thread a
> `seed` through `chat_with_tools` and set planning `temperature=0` whenever a seed
> is supplied. **Symptom**: high run-to-run benchmark verdict churn despite
> `seed=42`; different `distinct_tools_called` for the same question.

> Secondary pattern — **Benchmark "same-build" comparisons must assert identical
> `judge_prompt_id`/model/verdict_model_version across runs**; a silent
> judge-prompt bump (v3.0 vs v1.1) invalidates run-to-run deltas. The runner should
> refuse to diff two runs whose `_meta.json` judge identifiers differ.

---

## 9. Open Questions

- Why did the *later* run (20:43Z) use the *older* judge `@1.1` while the tree is
  `@3.0`? Likely run from a stale worktree/checkout — worth confirming so future
  runs always reflect the committed prompt.
- DeepInfra/DeepSeek-V4-Flash honouring of `seed` on MoE is best-effort; quantify
  residual judge variance after seeding before relying on it.

---

## 10. Verification update (2026-06-13, post-investigation)

Two of this report's load-bearing claims were tested empirically; one is **revised**.

**Open question 1 — ANSWERED.** The 20:43Z run used judge `@1.1` because the host
`.venv312` resolves `prompts` from a **stale agent worktree** via uv editable-install
`.pth` hooks left dangling by a directory rename (`Final Thesis` → `final_thesis`).
`sys.prefix` still points at the old path; the loaded site-packages carries
`_editable_impl_prompts.pth` → `.claude/worktrees/agent-a3aa85e751651be8a/libs/prompts/src`,
which ships `chat_quality_judge@1.1`, while the main tree has `@3.0`. The agent
*answers* were unaffected (generated by the freshly-built rag-chat container); only
the host-side *grading* used the wrong judge. Captured as **BP-693**. Workaround:
`PYTHONPATH=<repo>/libs/prompts/src` forces `@3.0` (verified).

**Conclusion REVISED — the judge prompt was NOT the dominant flip driver.** Re-grading
the 20:43Z *answers* with `@3.0` (`run_20260613T204300Z_regrade_v30`) and diffing
against the 05:32Z run (also `@3.0`) — i.e. **judge held fixed, only the agent run
differs** — gives **21 / 67 flips (31%)**, essentially the same churn as the
cross-prompt comparison (19/28%). So pinning the prompt removes a *leniency* shift
(under `@3.0` both runs land 44 vs 51 STRONG / 16 vs 10 FAIL, vs the lenient `@1.1`
50/7) but **does not reduce the flip rate**. The ~30% churn is genuinely
**agent-side**: the unseeded, `temperature=0.1` tool-planning step (driver #2) takes
different tool paths across identical requests. Mitigation #1's prompt-pin is still
required for *comparability and correctness* (the thesis must report `@3.0`), but the
**highest-leverage variance reducer is seeding the planner + the `max_runs_per_q=3`
majority verdict**, not the prompt pin. Expected residual after both: the majority of
three independent ~30%-flip draws is far more stable than any single pass.

**Thesis impact.** §5.4.2 now reports the `@3.0` separation as an indicative range
(two-thirds to three-quarters STRONG; a 10–16 failed tail) and states the ~one-third
judge-fixed flip rate with its agent-side cause. The `@1.1` numbers are quarantined
(`run_20260613T204300Z` retains them as evidence; `_regrade_v30` holds the corrected
`@3.0` grading). The κ calibration (§5.4.3) MUST likewise be run with `@3.0` forced —
any prior κ computed on the contaminated venv is suspect and is being redone on the
author's full label pass.
